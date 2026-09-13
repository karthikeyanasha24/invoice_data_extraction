"""
Scalable dashboard NL→SQL router for /dashboard/ai-analysis/chat.

Pipeline (no per-table Python hardcoding):
  1. Zodiac operational resolver  — app tables (sat_documents, EDI, …)
  2. Intent billing fast path       — deterministic VBRK/VBRP revenue SQL
  3. sql_catalog keyword match    — sql_catalog.json templates
  4. Universal adaptive engine    — full 121-table schema + LLM + SQL retry
  5. LangGraph (optional fallback)  — only if LANGGRAPH_FALLBACK=true
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("zodiac-api.dashboard_query_router")

PREVIEW_LIMIT = 80


def _langgraph_fallback_enabled() -> bool:
    return os.getenv("LANGGRAPH_FALLBACK", "false").lower() in ("1", "true", "yes")


def _serialize_rows(rows_raw) -> List[Dict[str, Any]]:
    """Convert SQLAlchemy row mappings to JSON-safe dicts (Decimal → float)."""
    import datetime
    import decimal

    out: List[Dict[str, Any]] = []
    for r in rows_raw:
        d = dict(r)
        for k, v in list(d.items()):
            if isinstance(v, decimal.Decimal):
                d[k] = float(v)
            elif isinstance(v, (datetime.date, datetime.datetime)):
                d[k] = v.isoformat()
        out.append(d)
    return out


def _build_payload(
    *,
    query: str,
    pipeline: str,
    reason: str,
    sql: str,
    rows: List[Dict[str, Any]],
    reply: str,
    charts: Optional[List[Dict[str, Any]]] = None,
    schema_tables: Optional[List[str]] = None,
    time_scope: str = "current",
    period_info: str = "",
    confidence: str = "high",
    confidence_note: str = "",
    node_log: Optional[List[Dict[str, Any]]] = None,
    elapsed_ms: int = 0,
    execution_error: Optional[str] = None,
) -> Dict[str, Any]:
    preview = rows[:PREVIEW_LIMIT]
    payload: Dict[str, Any] = {
        "reply": reply,
        "action": "new",
        "reason": reason,
        "schema_tables": schema_tables or [],
        "sql": sql or "",
        "rows_preview": preview,
        "charts": charts or [],
        "time_scope": time_scope,
        "date_range": {},
        "period_info": period_info,
        "errors": [],
        "warnings": [],
        "confidence": confidence,
        "confidence_note": confidence_note,
        "node_log": node_log
        or [
            {
                "service": pipeline,
                "kind": "deterministic" if "fast" in pipeline or "catalog" in pipeline else "adaptive",
                "message": reason,
            }
        ],
        "sql_path_reason": reason,
    }
    from .ai_query_accuracy import build_query_telemetry, log_query_telemetry

    tel = build_query_telemetry(
        question=query or "",
        pipeline=pipeline,
        reason=reason,
        sql=str(sql or ""),
        preview_row_count=len(preview),
        total_ms=elapsed_ms,
        sql_repair_count=0,
        node_log_count=len(payload["node_log"]),
        execution_error=execution_error,
    )
    payload["query_telemetry"] = tel
    log_query_telemetry(tel, question_snip=query or "")
    return payload


def _should_skip_operational_for_sap(question: str) -> bool:
    """SAP analytics should use catalog/intent/universal — not Zodiac operational tables."""
    from .operational_query_resolver import _extract_user_question

    ql = _extract_user_question(question or "").lower()
    if any(k in ql for k in ("sat", "cfdi", "edi", "inbound sat", "sat document", "zodiac invoice")):
        return False
    sap_signals = (
        "revenue", "sales", "turnover", "highest sales", "total sales", "industry",
        "billing", "vbrk", "vbrp", "kna1", "t016t", "purchase order", "open po",
        "open purchase", "ekko", "ekpo", "sales order", "profit center",
        "cost center", "faglflexa", "customers by revenue", "billed amount",
        "billing document", "vendor spend", "cepc", "csks", "material master",
        "gl account", "accounting document", "by customer", "by industry",
        "invoice count", "how many invoices", "top products", "product sales",
        "product-level", "top customers", "top 10 customers", "top 5 customers",
        "biggest customers", "largest customers",
    )
    if any(s in ql for s in sap_signals):
        return True
    if re.search(r"\b(19|20)\d{2}\b", ql) and re.search(
        r"\b(invoice|sales|revenue|customer|billing|product|material)\b", ql
    ):
        return True
    return False


def _execute_sql(db: Session, sql: str, question: str = "") -> List[Dict[str, Any]]:
    from .sql_generation_sanitizers import (
        prepare_sql_for_sqlalchemy_text_execution as _prep,
        sanitize_generated_sap_sql as _sanitize,
    )
    from .adaptive_nl_sql_hardening import apply_statement_timeout
    from .adaptive_trusted_scope import enforce_trusted_user_scope

    safe = _sanitize(sql, question or None)
    bind: Dict[str, Any] = {}
    safe, bind = enforce_trusted_user_scope(safe)
    safe = _prep(safe)
    apply_statement_timeout(db)
    rows_raw = db.execute(text(safe), bind or {}).mappings().all()
    return _serialize_rows(rows_raw)


def _cell(row: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None


def _summarize_operational_rows(query: str, op_type: str, rows: List[Dict[str, Any]]) -> str:
    """Instant summary from SQL rows — no LLM round-trip (keeps SAT/EDI chips under ~1s)."""
    if not rows:
        return "Query ran successfully. No matching rows in this environment."

    n = len(rows)
    r0 = rows[0]
    name = _cell(r0, "supplier_name", "supplier", "customer", "account", "label", "doc_type")

    if op_type == "sat_documents_by_received_date":
        newest = _cell(r0, "received_at", "fecha")
        who = _cell(r0, "supplier_name", "supplier_rfc")
        extra = f" Latest: {who or 'unknown'}" + (f" at {newest}." if newest else ".")
        return f"Showing {n} inbound SAT document(s), newest first.{extra}"
    if op_type == "top_sat_suppliers":
        cnt = _cell(r0, "sat_document_count", "document_count")
        return f"Top SAT suppliers by document count ({n} shown). Leader: {name or 'unknown'} with {cnt} documents."
    if op_type == "sat_documents_this_week":
        return f"{n} SAT document(s) received this calendar week, newest first."
    if op_type == "sat_documents_this_week_count":
        total = _cell(r0, "sat_document_count", "document_count", "count")
        return f"{total if total is not None else n} SAT document(s) were received this calendar week."
    if op_type == "sat_document_count_by_type":
        parts = [f"{_cell(r, 'doc_type') or 'unknown'}: {_cell(r, 'document_count')}" for r in rows[:8]]
        return f"SAT document counts by type: {'; '.join(str(p) for p in parts)}."
    if op_type == "sat_missing_cfdi_uuid":
        return f"{n} SAT document(s) have a missing or empty CFDI UUID."
    if op_type == "top_invoice_supplier_amount":
        amt = _cell(r0, "total_invoice_amount", "total_amount")
        return f"Highest invoice amount is {name or 'unknown'} ({amt}). Showing top {n} supplier(s)."
    if op_type == "failed_invoices_summary":
        reason = _cell(r0, "failure_reason", "error_reason")
        cnt = _cell(r0, "invoice_count", "count")
        return f"Top EDI/invoice failure: {reason or 'unspecified'} ({cnt} invoices). {n} reason group(s) shown."
    if op_type == "inbound_sat_merge":
        return f"Inbound SAT merge snapshot — {n} row(s) covering merge status and top suppliers."
    if op_type == "inbound_vs_outbound_comparison":
        return f"Inbound SAT vs outbound comparison — {n} row(s)."

    hint = f" First row: {name}." if name else ""
    return f"Returned {n} row(s) from the operational database.{hint}"


def _try_operational(
    db: Session,
    query: str,
    *,
    time_scope: str,
    days: int,
    api_key: str,
) -> Optional[Dict[str, Any]]:
    from .operational_query_resolver import resolve_operational_query
    from .intent_dashboard_fast_path import _period_blurb as _period_blurb_fn

    op = resolve_operational_query(query or "", time_scope=time_scope, api_key=api_key)
    if op is None:
        return None
    op_sql, op_type = op
    rows = _execute_sql(db, op_sql, query)
    row_count = len(rows)
    reply = _summarize_operational_rows(query, op_type, rows)
    return _build_payload(
        query=query,
        pipeline="operational_fast_path",
        reason=f"operational_{op_type}",
        sql=op_sql,
        rows=rows,
        reply=reply,
        schema_tables=["sat_documents"],
        time_scope=time_scope,
        period_info=_period_blurb_fn(query, days, time_scope),
        confidence="high" if row_count else "medium",
        confidence_note="Zodiac app DB (operational resolver).",
        node_log=[
            {
                "service": "operational_resolver",
                "kind": "deterministic",
                "message": f"Matched operational pattern: {op_type}",
            }
        ],
        elapsed_ms=0,
    )


def _try_sql_catalog(db: Session, query: str) -> Optional[Tuple[str, List[Dict[str, Any]], List[str]]]:
    """Legacy catalog lookup — disabled as a runtime SAP analytics authority."""
    try:
        from .analytics_authority import CATALOG_IS_RUNTIME_AUTHORITY

        if not CATALOG_IS_RUNTIME_AUTHORITY:
            return None
    except Exception:
        return None

    from .sap_sql_agent import _lookup_sql_catalog, _quote_catalog_sql_tables
    from .adaptive_nl_sql_hardening import apply_ranking_discipline

    catalog_sql = _lookup_sql_catalog(query or "")
    if not catalog_sql:
        return None
    sql = apply_ranking_discipline(_quote_catalog_sql_tables(catalog_sql), query or "")
    rows = _execute_sql(db, sql, query)
    tables = []
    import re

    for m in re.finditer(r'(?:FROM|JOIN)\s+"?([A-Za-z0-9_]+)"?', sql, re.I):
        t = m.group(1).upper()
        if t not in tables:
            tables.append(t)
    return sql, rows, tables[:12]


def _try_intent(db: Session, query: str, *, days: int, time_scope: str) -> Optional[Dict[str, Any]]:
    try:
        from .analytics_authority import INTENT_FAST_PATH_IS_RUNTIME_AUTHORITY

        if not INTENT_FAST_PATH_IS_RUNTIME_AUTHORITY:
            return None
    except Exception:
        return None
    from .intent_dashboard_fast_path import try_intent_dashboard_fast_path

    fast = try_intent_dashboard_fast_path(db, query or "", days=days, time_scope=time_scope)
    if fast is None:
        return None
    fast["sql_path_reason"] = fast.get("sql_path_reason") or "intent_sql_fast"
    return fast


def _try_universal(
    db: Session,
    query: str,
    api_key: str,
    *,
    use_sap: bool,
) -> Optional[Dict[str, Any]]:
    from ..api.adaptive_query import _universal_query

    result = _universal_query(
        query or "", api_key, db, use_sap, max_retries=3, display_question=query,
    )
    if not result:
        return None
    rows = result.get("data") or []
    sql = result.get("sql") or ""
    reply = result.get("summary") or f"Query returned {len(rows)} row(s)."
    charts = result.get("charts") or []
    payload = _build_payload(
        query=query,
        pipeline="universal_adaptive",
        reason="universal_adaptive",
        sql=sql,
        rows=rows if isinstance(rows, list) else [],
        reply=reply,
        charts=charts,
        confidence="high" if rows else "medium",
        confidence_note="Universal 121-table adaptive engine (schema + SQL retry).",
        node_log=[
            {
                "service": "universal_adaptive",
                "kind": "adaptive",
                "message": "Matched via full schema NL→SQL with PostgreSQL error retry.",
            }
        ],
        elapsed_ms=0,
    )
    if result.get("stage_timings"):
        payload["stage_timings"] = result["stage_timings"]
        payload["llm_calls"] = (result.get("stage_timings") or {}).get("sql_llm_calls")
        payload["sql_generation_method"] = "universal_llm"
    return payload


def run_dashboard_query(
    db: Session,
    api_key: str,
    query: str,
    conversation_history: Optional[list] = None,
    *,
    dashboard_context: str = "",
    days: int = 30,
    time_scope: str = "current",
    langgraph_runner=None,
) -> Dict[str, Any]:
    """
    Main scalable entry for dashboard AI chat.
    langgraph_runner: callable returning run_planner-shaped dict when LANGGRAPH_FALLBACK is enabled.
    """
    t0 = time.time()
    from .operational_query_resolver import _extract_user_question

    raw_q = (query or "").strip()
    q = _extract_user_question(raw_q)
    ts = (time_scope or "current").strip()
    days_int = max(1, min(365, int(days) if isinstance(days, (int, float)) else 30))

    from ..config.config import USE_SAP_DB_FOR_AI

    def _elapsed_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        elapsed_ms = int((time.time() - t0) * 1000)
        if payload.get("query_telemetry"):
            payload["query_telemetry"]["total_ms"] = elapsed_ms
        logger.info(
            "dashboard_query_router: %s — %d preview row(s) in %dms",
            payload.get("sql_path_reason") or payload.get("reason"),
            len(payload.get("rows_preview") or []),
            elapsed_ms,
        )
        return payload

    # 1) Zodiac operational (small fixed app schema — skip for SAP analytics)
    empty_operational_fallback: Optional[Dict[str, Any]] = None
    if not _should_skip_operational_for_sap(q):
        try:
            op_payload = _try_operational(db, q, time_scope=ts, days=days_int, api_key=api_key)
            if op_payload is not None:
                if op_payload.get("rows_preview"):
                    return _elapsed_payload(op_payload)
                # 0 rows: only final when the question explicitly targets the
                # Zodiac app DB. Generic questions ("top customers by invoice
                # amount") must fall through to SAP paths that may hold the data.
                explicit_op = any(
                    k in q.lower()
                    for k in ("sat", "cfdi", "edi", "zodiac", "supplier token", "processing log", "v2 invoice")
                )
                if explicit_op:
                    return _elapsed_payload(op_payload)
                empty_operational_fallback = op_payload
                logger.info(
                    "dashboard_query_router: operational matched but 0 rows — falling through to SAP paths"
                )
        except Exception as exc:
            logger.warning("operational resolver failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    # 2) Billing intent fast path (narrow domain — before catalog for revenue/group-by)
    try:
        intent_payload = _try_intent(db, q, days=days_int, time_scope=ts)
        if intent_payload is not None:
            from .ai_query_accuracy import build_query_telemetry, log_query_telemetry

            elapsed_ms = int((time.time() - t0) * 1000)
            tel = build_query_telemetry(
                question=q,
                pipeline="intent_sql_fast",
                reason=str(intent_payload.get("reason") or "intent_sql_fast"),
                sql=str(intent_payload.get("sql") or ""),
                preview_row_count=len(intent_payload.get("rows_preview") or []),
                total_ms=elapsed_ms,
                sql_repair_count=0,
                node_log_count=len(intent_payload.get("node_log") or []),
                execution_error=None,
            )
            intent_payload["query_telemetry"] = tel
            intent_payload["sql_path_reason"] = "intent_sql_fast"
            log_query_telemetry(tel, question_snip=q)
            return intent_payload
    except Exception as exc:
        logger.debug("intent fast path skipped: %s", exc)

    # 3) sql_catalog.json keyword templates
    try:
        cat = _try_sql_catalog(db, q)
        if cat is not None:
            sql, rows, tables = cat
            reply = (
                f"Matched **sql_catalog** template — **{len(rows)}** row(s) returned."
                if rows
                else "Catalog SQL ran successfully but returned no rows."
            )
            payload = _build_payload(
                query=q,
                pipeline="sql_catalog",
                reason="sql_catalog",
                sql=sql,
                rows=rows,
                reply=reply,
                schema_tables=tables,
                time_scope=ts,
                confidence="high" if rows else "medium",
                confidence_note="Pre-built SQL from sql_catalog.json (keyword match).",
                node_log=[
                    {
                        "service": "sql_catalog",
                        "kind": "deterministic",
                        "message": "Keyword match in sql_catalog.json",
                    }
                ],
                elapsed_ms=0,
            )
            return _elapsed_payload(payload)
    except Exception as exc:
        logger.warning("sql_catalog path failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    # 4) Universal adaptive — all 121 tables
    try:
        uni = _try_universal(db, q, api_key, use_sap=bool(USE_SAP_DB_FOR_AI))
        if uni is not None:
            return _elapsed_payload(uni)
    except Exception as exc:
        logger.warning("universal adaptive failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    # 5) Optional LangGraph fallback (disabled by default)
    if _langgraph_fallback_enabled() and langgraph_runner is not None:
        logger.info("dashboard_query_router: falling back to LangGraph (LANGGRAPH_FALLBACK=true)")
        return langgraph_runner()

    # 6) Nothing else matched — surface the empty operational answer if we had one
    if empty_operational_fallback is not None:
        return _elapsed_payload(empty_operational_fallback)

    elapsed_ms = int((time.time() - t0) * 1000)
    return _build_payload(
        query=q,
        pipeline="dashboard_query_router",
        reason="no_match",
        sql="",
        rows=[],
        reply=(
            "Could not answer this question with the catalog or universal SQL engine. "
            "Try rephrasing, pin tables in the schema browser, or set LANGGRAPH_FALLBACK=true "
            "only for experimental deep queries."
        ),
        confidence="low",
        confidence_note="All scalable paths exhausted (operational → intent → catalog → universal).",
        elapsed_ms=elapsed_ms,
        execution_error="no_scalable_path_match",
    )
