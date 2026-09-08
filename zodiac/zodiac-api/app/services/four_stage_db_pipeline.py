"""
Four-stage AI database intelligence pipeline.

User Question
  → Pipeline 1: Table Selection (lightweight catalog from cached registry)
  → Pipeline 2: Column Selection (columns for selected tables only)
  → Pipeline 3: SQL Generation (verified context only)
  → SQL Validation → Execution
  → Pipeline 4: Result Analysis & Presentation

Schema is loaded once from files via schema_intelligence_registry — never
re-introspected from the database per question.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..data_catalog.physical import has_column, has_table, resolve_table_name
from ..services.adaptive_analyst.llm_provider import analyze_json, complete_text
from ..services.adaptive_nl_sql_hardening import repair_generated_sql
from ..services.ai_native_pipeline import _schema_violations, extract_sql
from ..services.sap_sql_precision_validator import validate_sql_precision_for_db
from ..services.schema_intelligence_registry import get_schema_registry
from ..services.sql_grain_guard import sql_has_unsafe_monetary_fanout

logger = logging.getLogger("zodiac-api.four_stage_pipeline")

ExecuteSql = Callable[[Session, str, str], List[Dict[str, Any]]]

_FOLLOWUP_LIMIT = re.compile(
    r"\b(top|limit|only)\s+(\d+|one|two|three|four|five|ten|twenty)\b", re.I
)
_FOLLOWUP_YEAR = re.compile(r"\b(20\d{2}|19\d{2})\b")


@dataclass
class VerifiedDbContext:
    question: str
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)  # TABLE.col
    joins: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    pipeline_log: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _log_stage(ctx: VerifiedDbContext, stage: str, payload: Dict[str, Any]) -> None:
    ctx.pipeline_log[stage] = payload
    logger.info("[four_stage] %s %s", stage, json.dumps(payload, default=str)[:1200])


def _question_needs_operational_tables(question: str) -> bool:
    q = (question or "").lower()
    return any(
        k in q
        for k in (
            "sat", "edi", "zodiac", "supplier token", "cfdi", "invoice pipeline",
            "failed invoice", "conversion rate",
        )
    )


def _apply_followup_to_context(
    question: str,
    prior: Optional[Dict[str, Any]],
) -> Optional[VerifiedDbContext]:
    if not isinstance(prior, dict):
        return None
    prev_ctx = prior.get("verified_db_context")
    if not isinstance(prev_ctx, dict):
        prev_ctx = prior.get("investigation_state", {}).get("verified_db_context")
    if not isinstance(prev_ctx, dict) or not prev_ctx.get("tables"):
        return None
    q = (question or "").lower()
    is_followup = (
        len(q.split()) <= 8
        and (
            bool(_FOLLOWUP_LIMIT.search(q))
            or bool(_FOLLOWUP_YEAR.search(q))
            or q.startswith("show only")
            or q.startswith("same for")
            or q.startswith("show the same")
        )
    )
    if not is_followup:
        return None
    ctx = VerifiedDbContext(
        question=question,
        tables=list(prev_ctx.get("tables") or []),
        columns=list(prev_ctx.get("columns") or []),
        joins=list(prev_ctx.get("joins") or []),
        relationships=list(prev_ctx.get("relationships") or []),
        pipeline_log={"followup_reuse": True},
    )
    _log_stage(ctx, "PIPELINE_1_TABLE_SELECTION", {"reused": True, "tables": ctx.tables})
    _log_stage(ctx, "PIPELINE_2_COLUMN_SELECTION", {"reused": True, "columns": ctx.columns})
    return ctx


def pipeline1_table_selection(question: str, ctx: VerifiedDbContext) -> None:
    reg = get_schema_registry()
    include_ops = _question_needs_operational_tables(question)
    scored = reg.score_tables_for_question(question, include_operational=include_ops)
    candidates = scored[:25]

    if not candidates and include_ops:
        scored = reg.score_tables_for_question(question, include_operational=True)
        candidates = scored[:25]

    catalog_slice = [
        t for t in reg.lightweight_table_catalog(include_operational=include_ops)
        if t["table"] in {c[0] for c in candidates} or len(candidates) < 8
    ][:30]

    pick, provider = analyze_json(
        "You are Pipeline 1 — TABLE SELECTION ONLY. Return JSON only. "
        "Pick tables that exist in the catalog. Do NOT generate SQL. Do NOT list all columns.",
        (
            f"Question: {question}\n\n"
            f"Top rule-based candidates: {json.dumps([{'table': t, 'score': s, 'reason': r} for t, s, r in candidates[:15]])}\n\n"
            f"Table catalog (descriptions only):\n{json.dumps(catalog_slice[:25])}\n\n"
            "Return JSON: {\"selected_tables\":[{\"table\":\"\",\"confidence\":0.0,\"reason\":\"\"}], "
            "\"data_limitation\": null}. "
            "If no table can answer the question, set data_limitation to a short honest message. "
            "For SAT processing logs use sat_processing_logs if present — never invent SAT, SAT_LOG, SAT_PROCESSING_LOG."
        ),
    )

    selected: List[str] = []
    for item in pick.get("selected_tables") or []:
        if isinstance(item, dict):
            tbl = str(item.get("table") or "").strip()
            if tbl and has_table(tbl):
                selected.append(resolve_table_name(tbl) or tbl)
        elif isinstance(item, str) and has_table(item):
            selected.append(resolve_table_name(item) or item)

    if not selected:
        selected = [t for t, _, _ in candidates[:6]]

    # Dedupe preserve order
    seen: set[str] = set()
    ctx.tables = [t for t in selected if not (t in seen or seen.add(t))]

    limitation = pick.get("data_limitation") or reg.resolve_data_limitation(question, ctx.tables)
    _log_stage(
        ctx,
        "PIPELINE_1_TABLE_SELECTION",
        {
            "provider": provider,
            "selected_tables": ctx.tables,
            "candidates": candidates[:10],
            "data_limitation": limitation,
        },
    )
    if limitation and not ctx.tables:
        ctx.pipeline_log["data_limitation"] = limitation


def pipeline2_column_selection(question: str, ctx: VerifiedDbContext) -> None:
    reg = get_schema_registry()
    col_meta = reg.columns_for_tables(ctx.tables)
    column_text = reg.column_detail_for_selection(ctx.tables)
    suggested_joins = reg.suggested_joins(ctx.tables)

    pick, provider = analyze_json(
        "You are Pipeline 2 — COLUMN SELECTION ONLY. Return JSON only. "
        "Select columns from the provided tables. Do NOT generate SQL.",
        (
            f"Question: {question}\n"
            f"Selected tables: {ctx.tables}\n"
            f"Column metadata:\n{json.dumps(col_meta)}\n\n"
            f"{column_text}\n\n"
            f"Suggested joins from registry: {json.dumps(suggested_joins)}\n\n"
            "Return JSON: {\"selected_columns\":[{\"table\":\"\",\"column\":\"\",\"purpose\":\"\"}], "
            "\"joins\":[{\"left_table\":\"\",\"left_column\":\"\",\"right_table\":\"\",\"right_column\":\"\",\"reason\":\"\"}]}. "
            "Use FKIMG for billed quantity on vbrp, NETWR for billed amount, KUNAG/KUNNR for customer."
        ),
    )

    columns: List[str] = []
    for item in pick.get("selected_columns") or []:
        if not isinstance(item, dict):
            continue
        tbl = str(item.get("table") or "").strip()
        col = str(item.get("column") or "").strip()
        if tbl and col and has_column(tbl, col):
            columns.append(f"{resolve_table_name(tbl) or tbl}.{col}")

    if not columns:
        for tbl in ctx.tables:
            meta = reg.get_table(tbl)
            if not meta:
                continue
            for col in (meta.important_columns or [])[:8]:
                if has_column(tbl, col):
                    columns.append(f"{tbl}.{col}")

    joins = pick.get("joins") if isinstance(pick.get("joins"), list) else suggested_joins
    relationships: List[str] = []
    for j in joins or []:
        if not isinstance(j, dict):
            continue
        lt = str(j.get("left_table") or "")
        lc = str(j.get("left_column") or j.get("join_key") or "")
        rt = str(j.get("right_table") or "")
        rc = str(j.get("right_column") or lc or "")
        if lt and rt and lc:
            relationships.append(f"{lt}.{lc} = {rt}.{rc}")
            ctx.joins.append(j)

    ctx.columns = columns
    ctx.relationships = relationships
    _log_stage(
        ctx,
        "PIPELINE_2_COLUMN_SELECTION",
        {"provider": provider, "columns": columns, "joins": ctx.joins},
    )


def _validate_sql_against_context(sql: str, ctx: VerifiedDbContext, db: Session) -> List[str]:
    errors = list(_schema_violations(sql) or [])
    if errors:
        return errors
    allowed_tables = {t.upper() for t in ctx.tables}
    # Extract quoted identifiers as table refs
    for m in re.finditer(r'"([A-Za-z0-9_]+)"', sql or ""):
        ref = m.group(1)
        if ref.upper() in {"SELECT", "FROM", "WHERE", "GROUP", "ORDER", "LIMIT", "AS", "ON", "AND", "OR"}:
            continue
        if has_table(ref) and ref.upper() not in allowed_tables and len(ctx.tables) <= 6:
            # allow dimension tables discovered via joins if they exist
            if ref.lower().startswith(("sat_", "zodiac_", "invoice_")):
                continue
            errors.append(f"table {ref} not in verified selection {ctx.tables}")
    try:
        prec = validate_sql_precision_for_db(db, sql, question)
        if prec and getattr(prec, "errors", None):
            errors.extend([str(e) for e in prec.errors[:5]])
    except Exception:
        pass
    return errors


def _deterministic_sql_if_known(question: str, ctx: VerifiedDbContext) -> Optional[str]:
    """Known-good SQL for common ranking questions — avoids over-filtered LLM SQL."""
    q = (question or "").lower()
    tables_lower = {t.lower() for t in ctx.tables}

    if "customer" in q and ("billing revenue" in q or "billed revenue" in q or "top" in q and "customer" in q):
        if "vbrp" in tables_lower or "vbrk" in tables_lower:
            limit = 10
            m = re.search(r"\btop\s+(\d+)", q)
            if m:
                limit = int(m.group(1))
            return (
                'SELECT TRIM(k."kunag") AS customer_id, TRIM(c."name1") AS customer_name, '
                'SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS total_billed '
                'FROM "vbrp" p '
                'JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"), 10, \'0\') = LPAD(TRIM(k."vbeln"), 10, \'0\') '
                'LEFT JOIN "KNA1" c ON LPAD(TRIM(k."kunag"), 10, \'0\') = LPAD(TRIM(c."kunnr"), 10, \'0\') '
                'WHERE NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') IS NOT NULL '
                'GROUP BY 1, 2 ORDER BY total_billed DESC NULLS LAST '
                f"LIMIT {limit}"
            )

    if "material" in q and ("billed quantity" in q or "billing quantity" in q):
        if "vbrp" in tables_lower:
            limit = 20
            m = re.search(r"\btop\s+(\d+)", q)
            if m:
                limit = int(m.group(1))
            return (
                'SELECT TRIM(p."matnr") AS material_id, TRIM(m."maktx") AS material_name, '
                'SUM(CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), \'\') AS NUMERIC)) AS billed_quantity '
                'FROM "vbrp" p '
                'LEFT JOIN "MAKT" m ON TRIM(p."matnr") = TRIM(m."matnr") '
                'WHERE NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), \'\') IS NOT NULL '
                'GROUP BY 1, 2 ORDER BY billed_quantity DESC NULLS LAST '
                f"LIMIT {limit}"
            )

    if "sat" in q and "process" in q and "sat_processing_logs" in tables_lower:
        return (
            'SELECT step_name, step_status, message, error_details, created_at '
            'FROM "sat_processing_logs" '
            "WHERE LOWER(COALESCE(step_status, '')) LIKE '%fail%' "
            "   OR LOWER(COALESCE(message, '')) LIKE '%error%' "
            "ORDER BY created_at DESC LIMIT 100"
        )
    return None


def pipeline3_sql_generation(question: str, ctx: VerifiedDbContext) -> str:
    known = _deterministic_sql_if_known(question, ctx)
    if known:
        _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"source": "deterministic_template"})
        return known
    reg = get_schema_registry()
    detail = reg.column_detail_for_selection(ctx.tables)
    sql_text, provider = complete_text(
        "You are Pipeline 3 — SQL GENERATION ONLY. PostgreSQL SELECT. ```sql block only. "
        "Use ONLY the verified tables, columns, and relationships provided. "
        "Quote identifiers. CAST text numerics with NULLIF(TRIM(...),''). "
        "Do not invent tables. Do not add restrictive date filters unless the question asks for a period. "
        "Ranking questions: GROUP BY dimensions, ORDER BY metric DESC, LIMIT from question (default 10).",
        (
            f"Question: {question}\n\n"
            f"Verified tables: {ctx.tables}\n"
            f"Verified columns: {ctx.columns}\n"
            f"Relationships: {ctx.relationships}\n\n"
            f"{detail}\n\nGenerate SQL."
        ),
    )
    sql = extract_sql(sql_text) or sql_text.strip()
    sql = repair_generated_sql(sql, question)
    _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"provider": provider, "sql": sql[:2000]})
    return sql


def pipeline4_result_analysis(
    question: str,
    sql: str,
    rows: List[Dict[str, Any]],
    ctx: VerifiedDbContext,
    *,
    exec_ms: int = 0,
) -> Dict[str, Any]:
    narrative, provider = analyze_json(
        "You are Pipeline 4 — RESULT ANALYSIS. JSON only. Use ONLY numbers in the rows. Never invent.",
        (
            f"Question: {question}\nSQL:\n{sql[:1500]}\n"
            f"Tables: {ctx.tables}\nColumns: {ctx.columns}\n"
            f"Row count: {len(rows)}\nSample: {json.dumps(rows[:12], default=str)[:4000]}\n\n"
            "Return JSON: {\"answer\":\"\",\"summary\":\"\",\"findings\":[], "
            "\"presentation_type\":\"table|bar|line|pie|none\", "
            "\"calculation_explanation\":\"\", \"follow_up_suggestions\":[]}. "
            "If 0 rows: say query succeeded but no matching records — do NOT claim data does not exist globally."
        ),
    )
    _log_stage(
        ctx,
        "PIPELINE_4_RESULT_ANALYSIS",
        {"provider": provider, "row_count": len(rows), "exec_ms": exec_ms},
    )
    return narrative


def run_four_stage_database_query(
    question: str,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_sql: str = "",
) -> Dict[str, Any]:
    """
    Run P1→P4. Returns orchestrator-compatible dict with sql, rows, tables, error, narrative.
    """
    t0 = time.perf_counter()
    ctx = _apply_followup_to_context(question, prior_plan)
    if ctx is None:
        ctx = VerifiedDbContext(question=question)
        pipeline1_table_selection(question, ctx)
        if ctx.pipeline_log.get("data_limitation") and not ctx.tables:
            msg = str(ctx.pipeline_log["data_limitation"])
            return {
                "error": "data_limitation",
                "detail": [msg],
                "tables": [],
                "missing": [],
                "sql": "",
                "rows": [],
                "verified_context": ctx.to_dict(),
                "pipeline_log": ctx.pipeline_log,
                "data_limitation": msg,
            }
        pipeline2_column_selection(question, ctx)

    if prior_sql and ctx.pipeline_log.get("followup_reuse"):
        sql = pipeline3_sql_generation(
            question + f"\nModify the previous SQL (do not rediscover tables):\n{prior_sql[:3000]}",
            ctx,
        )
        _log_stage(ctx, "PIPELINE_3_SQL_GENERATION", {"followup_modified": True})
    else:
        sql = pipeline3_sql_generation(question, ctx)

    viol = _validate_sql_against_context(sql, ctx, db)
    _log_stage(ctx, "SQL_VALIDATION", {"pass": not viol, "errors": viol})
    if viol:
        reg = get_schema_registry()
        sql = pipeline3_sql_generation(
            question + f" Fix these validation errors: {'; '.join(viol[:5])}",
            ctx,
        )
        viol = _validate_sql_against_context(sql, ctx, db)
        _log_stage(ctx, "SQL_VALIDATION_RETRY", {"pass": not viol, "errors": viol})

    if not sql or viol:
        return {
            "error": "sql_validation_failed",
            "detail": viol or ["empty sql"],
            "tables": ctx.tables,
            "missing": [],
            "sql": sql,
            "rows": [],
            "verified_context": ctx.to_dict(),
            "pipeline_log": ctx.pipeline_log,
        }

    if sql_has_unsafe_monetary_fanout(sql):
        return {
            "error": "unsafe_grain",
            "detail": ["mixed monetary grains"],
            "tables": ctx.tables,
            "sql": sql,
            "rows": [],
            "verified_context": ctx.to_dict(),
            "pipeline_log": ctx.pipeline_log,
        }

    t_exec = time.perf_counter()
    rows = execute_sql(db, sql, question) or []
    exec_ms = int((time.perf_counter() - t_exec) * 1000)
    _log_stage(ctx, "SQL_EXECUTION", {"row_count": len(rows), "exec_ms": exec_ms})

    narrative = pipeline4_result_analysis(question, sql, rows, ctx, exec_ms=exec_ms)
    total_ms = int((time.perf_counter() - t0) * 1000)
    ctx.pipeline_log["total_ms"] = total_ms

    return {
        "sql": sql,
        "rows": rows,
        "tables": ctx.tables,
        "verified_context": ctx.to_dict(),
        "pipeline_log": ctx.pipeline_log,
        "narrative": narrative,
        "pick": {"tables": ctx.tables, "columns": ctx.columns, "joins": ctx.joins},
    }
