"""AdaptiveAnalystOrchestrator — one conversation, three cooperating pipelines.

Pipeline 1: general LLM (intent, follow-up rewrite, greeting)
Pipeline 2: database intelligence (schema retrieve → tables → columns → SQL → execute)
Pipeline 3: result intelligence (summary, findings, presentation)

Catalog/SQL examples are guides. The live schema is authoritative.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ...data_catalog.physical import has_table
from ..ai_native_pipeline import (
    _safe_select,
    _schema_violations,
    columns_guide,
    extract_sql,
    repair_generated_sql,
)
from ..sql_grain_guard import sql_has_unsafe_monetary_fanout
from .conversation_state import InvestigationState
from .llm_provider import analyze_json, complete_text
from .schema_retrieval import retrieve_candidate_tables, schema_context_for

logger = logging.getLogger("zodiac-api.adaptive_analyst")

ExecuteSql = Callable[[Session, str, str], List[Dict[str, Any]]]
ChartFn = Callable[[str, str, List[Dict[str, Any]]], List[Dict[str, Any]]]


def orchestrator_enabled() -> bool:
    return os.getenv("AI_NATIVE_PIPELINE", "true").strip().lower() in {"1", "true", "yes", "on"}


def _log_stage(name: str, payload: Dict[str, Any]) -> None:
    safe = {k: payload.get(k) for k in list(payload)[:12]}
    logger.info("[adaptive-orch] %s %s", name, json.dumps(safe, default=str)[:800])


def _force_general_chat(question: str) -> bool:
    """Safety net: never send obvious non-data chat to SQL. LLM still classifies first."""
    ql = re.sub(r"[?!.,]+$", "", (question or "").strip().lower())
    if ql in {"hi", "hello", "hey", "how are you", "how are you doing", "thanks", "thank you", "yo"}:
        return True
    if "meaning of life" in ql:
        return True
    if ql.startswith("explain ") and not any(
        t in ql for t in ("sales", "invoice", "customer", "vbak", "revenue", "purchase")
    ):
        return True
    return False


_DIM_ALIASES = {
    "customer": ("customer", "customer_name", "kunnr", "name1", "payer_name"),
    "country": ("country", "land1"),
    "industry": ("industry", "brsch", "industry_key"),
    "product": ("product", "matnr", "product_name", "maktx"),
}


def missing_result_dimensions(rows: List[Dict[str, Any]], requested: List[str]) -> List[str]:
    if not requested:
        return []
    if not rows or not isinstance(rows[0], dict):
        return [str(d) for d in requested]
    keys = {str(k).lower() for k in rows[0].keys()}
    missing = []
    for dim in requested:
        d = str(dim).lower().strip()
        aliases = _DIM_ALIASES.get(d, (d,))
        if not any(a in keys for a in aliases):
            missing.append(d)
    return missing


def _pipeline1_understand(
    question: str,
    state: InvestigationState,
    sample_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    analysis, provider = analyze_json(
        "You are Pipeline 1 of BridgeEDI AI Analyst. Return JSON only. "
        "You understand conversation AND whether SAP/database access is required. "
        "Never invent table names or company numbers.",
        (
            "Classify and rewrite the user turn.\n"
            "question_type: greeting|general_conversation|general_knowledge|business_question|"
            "database_question|follow_up_question|clarification|comparison|calculation|"
            "explanation|mixed_question\n"
            "Also set route: general|database|mixed|clarification\n"
            "JSON keys: question_type, route, intent, rewritten_question, requires_database, "
            "requires_general_llm, is_follow_up, follow_up_target, entities, metrics, dimensions, "
            "filters, time_period, ranking, comparison, requested_output, ambiguities, "
            "clarification_needed, clarification_question, reply (if no database), "
            "conversation_reference.\n"
            "Greetings, how are you, thanks, what can you do, what is SAP, meaning of life, "
            "explain machine learning → requires_database=false, question_type greeting/"
            "general_conversation/general_knowledge.\n"
            "OUR company facts (sales, invoices, VBAK, customers) → requires_database=true.\n"
            "Short follow-ups (which country?, reflected?, they, Germany, top 5, 2005, why?, "
            "industry?, the product, who supplied) MUST is_follow_up=true and rewritten_question "
            "must be a FULL question using investigation state. Never send 'reflected?' to SQL.\n"
            "If sales orders vs billed invoices is ambiguous AND there is no prior investigation, "
            "clarification_needed=true.\n"
            f"User: {question}\n"
            f"Investigation state: {json.dumps(state.to_dict(), default=str)}\n"
            f"Prior result sample: {json.dumps(sample_rows[:5], default=str)[:1500]}\n"
        ),
    )
    analysis["_provider"] = provider
    _log_stage("PIPELINE_1", analysis)
    return analysis


def _pipeline2_sql(
    resolved: str,
    original: str,
    analysis: Dict[str, Any],
    state: InvestigationState,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    use_sap: bool,
    get_sap_session: Optional[Callable[[], Any]],
) -> Dict[str, Any]:
    """Returns dict with sql, rows, tables, error (optional). Never COUNT(*) fallback."""
    schema = schema_context_for(resolved, state.tables)
    pick, p2 = analyze_json(
        "You are Pipeline 2 table/column selector. JSON only. Use only tables/columns in the schema.",
        (
            f"Resolved question: {resolved}\nOriginal: {original}\n"
            f"Plan: {json.dumps({k: analysis.get(k) for k in ('metrics','dimensions','time_period','ranking','filters','intent')})}\n"
            f"{schema}\n"
            "Return JSON: {\"tables\":[], \"columns\": {\"TABLE\":[\"col\"]}, \"joins\":[], "
            "\"grain\":\"\", \"why\":\"\", \"missing\":[]}. "
            "Every requested dimension (customer, country, industry, year) must appear if columns exist. "
            "If a table is absent (e.g. VBED), list it in missing. Never invent columns."
        ),
    )
    tables = [t for t in (pick.get("tables") or []) if has_table(str(t))]
    if not tables:
        tables = retrieve_candidate_tables(resolved, state.tables)[:6]
    missing = [str(x) for x in (pick.get("missing") or [])]
    sql_text, p3 = complete_text(
        "Write one PostgreSQL SELECT. ```sql block only. SELECT only. "
        "Quote SAP identifiers. CAST text numerics. LIMIT 50 unless aggregate ranking (then LIMIT 10). "
        "Do not join VBAK.vbeln = VBRK.vbeln. Do not mix billing NETWR with EKPO/MBEW in one SUM. "
        "Never query invoice_business_data unless the user asked about EDI invoice pipeline.",
        (
            f"Question: {resolved}\nTables: {tables}\nSelection: {json.dumps(pick)}\n"
            f"Column detail:\n{columns_guide(tables)}\n{schema[:5000]}\nGenerate SQL."
        ),
    )
    sql = _safe_select(repair_generated_sql(extract_sql(sql_text), resolved) or "") or ""
    if sql and sql_has_unsafe_monetary_fanout(sql):
        repaired, _ = complete_text(
            "Rewrite SQL with one fact grain only. ```sql block.",
            f"Unsafe grain mix. Question: {resolved}\nSQL:\n{sql}",
        )
        sql = _safe_select(repair_generated_sql(extract_sql(repaired), resolved) or "") or ""
    viol = _schema_violations(sql) if sql else ["empty sql"]
    if viol:
        repaired, _ = complete_text(
            "Fix SQL to use real tables/columns. ```sql block.",
            f"Errors: {viol}\nQuestion: {resolved}\nSQL:\n{sql}\n{schema[:4000]}",
        )
        sql = _safe_select(repair_generated_sql(extract_sql(repaired), resolved) or "") or ""
        viol = _schema_violations(sql) if sql else ["empty sql"]
    if not sql or viol:
        return {
            "error": "sql_generation_failed",
            "detail": viol or ["empty sql"],
            "tables": tables,
            "missing": missing,
            "providers": [p2, p3],
            "pick": pick,
        }
    su = sql.upper()
    if "INVOICE_BUSINESS_DATA" in su or "INVOICE_V2_BUSINESS_DATA" in su:
        if "edi" not in resolved.lower() and "pipeline" not in resolved.lower():
            return {
                "error": "refused_unrelated_fallback",
                "tables": tables,
                "missing": missing,
                "providers": [p2, p3],
                "pick": pick,
            }

    sess = db
    sap = None
    try:
        if use_sap and get_sap_session:
            sap = get_sap_session()
            if sap is not None:
                sess = sap
        try:
            rows = execute_sql(sess, sql, resolved)
        except Exception as exc:
            logger.warning("[adaptive-orch] execute failed: %s", exc)
            repaired, _ = complete_text(
                "Fix PostgreSQL error. ```sql block. SELECT only.",
                f"Error: {str(exc)[:500]}\nSQL:\n{sql}\nQuestion: {resolved}\n{schema[:3000]}",
            )
            sql2 = _safe_select(repair_generated_sql(extract_sql(repaired), resolved) or "") or ""
            if not sql2 or _schema_violations(sql2):
                return {
                    "error": "execution_failed",
                    "detail": str(exc)[:400],
                    "sql": sql,
                    "tables": tables,
                    "missing": missing,
                    "providers": [p2, p3],
                    "pick": pick,
                }
            try:
                rows = execute_sql(sess, sql2, resolved)
                sql = sql2
            except Exception as exc2:
                return {
                    "error": "execution_failed",
                    "detail": str(exc2)[:400],
                    "sql": sql2,
                    "tables": tables,
                    "missing": missing,
                    "providers": [p2, p3],
                    "pick": pick,
                }
    finally:
        if sap is not None:
            try:
                sap.close()
            except Exception:
                pass

    _log_stage("PIPELINE_2", {"tables": tables, "row_count": len(rows), "sql": sql[:180]})
    return {
        "sql": sql,
        "rows": rows,
        "tables": tables,
        "pick": pick,
        "missing": missing,
        "providers": [p2, p3],
    }


def _pipeline3_interpret(
    original: str,
    resolved: str,
    sql: str,
    rows: List[Dict[str, Any]],
    tables: List[str],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    narrative, provider = analyze_json(
        "You are Pipeline 3 result intelligence. JSON only. Use only numbers and fields in the rows. Never invent.",
        (
            f"User: {original}\nResolved: {resolved}\nSQL:\n{sql[:1500]}\n"
            f"Tables: {tables}\nRequested dimensions: {analysis.get('dimensions')}\n"
            f"Row count: {len(rows)}\nSample: {json.dumps(rows[:12], default=str)[:4000]}\n"
            "Return JSON: {\"answer\":\"\", \"summary\":\"\", \"findings\":[], "
            "\"limitations\":[], \"presentation_type\":\"table|bar|line|kpi|none\", "
            "\"incomplete\": false, \"follow_up_suggestions\":[]}. "
            "If 0 rows, say no records matched — that is success, not failure. "
            "If a requested dimension is missing from columns, set incomplete=true and explain."
        ),
    )
    narrative["_provider"] = provider
    _log_stage("PIPELINE_3", narrative)
    return narrative


def run_adaptive_orchestrator(
    question: str,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    use_sap: bool = False,
    chart_fn: Optional[ChartFn] = None,
    prior_question: str = "",
    prior_sql: str = "",
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_rows: Optional[List[Dict[str, Any]]] = None,
    get_sap_session: Optional[Callable[[], Any]] = None,
    thread_id: str = "",
) -> Dict[str, Any]:
    q = (question or "").strip()
    state = InvestigationState.from_context(prior_plan, prior_question, prior_sql)
    if thread_id:
        state.conversation_id = thread_id

    p1 = _pipeline1_understand(q, state, prior_rows or [])
    qtype = str(p1.get("question_type") or "").lower()
    route = str(p1.get("route") or "").lower()
    requires_db = bool(p1.get("requires_database"))
    if _force_general_chat(q) or qtype in {
        "greeting", "general_conversation", "general_knowledge",
    }:
        requires_db = False
        route = "general"
    elif route == "general" or (p1.get("requires_database") is False and route != "clarification"):
        requires_db = False
    if route in {"database", "mixed"} and not _force_general_chat(q):
        requires_db = True
    if qtype in {"business_question", "database_question", "follow_up_question", "comparison", "calculation"}:
        if not _force_general_chat(q):
            requires_db = True

    if (route == "clarification" or p1.get("clarification_needed")) and not _force_general_chat(q):
        msg = str(p1.get("clarification_question") or p1.get("reply") or "").strip()
        if not msg:
            msg = (
                "I can answer that from the imported SAP data. "
                "Do you mean sales orders (VBAK/VBAP) or invoiced/billed sales (VBRK/VBRP)?"
            )
        return {
            "mode": "clarification",
            "route": "clarification",
            "status": "clarification",
            "answer_status": "CLARIFICATION",
            "type": "clarification",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": msg,
            "answer": msg,
            "keyFindings": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "pipeline1_clarification",
            "llm_calls": 1,
            "query_plan": {"investigation_state": state.to_dict(), "pipeline1": p1},
            "suggested_followups": [
                "Show the top customers by billed sales.",
                "How many sales orders are there?",
            ],
        }

    if not requires_db:
        reply = str(p1.get("reply") or "").strip()
        if not reply:
            text, _ = complete_text(
                "You are a helpful SAP business analyst assistant. Be concise and friendly. "
                "Do not invent company numbers.",
                q,
            )
            reply = text
        return {
            "mode": "general_chat",
            "route": "general",
            "status": "success",
            "answer_status": "SUCCESS",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": reply,
            "answer": reply,
            "keyFindings": [],
            "charts": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "pipeline1_general",
            "llm_calls": 1,
            "query_plan": {"investigation_state": state.to_dict(), "pipeline1": p1},
            "meta": {"mode": "general_chat", "intent": p1.get("intent")},
        }

    resolved = str(p1.get("rewritten_question") or q).strip() or q
    from .governed import try_governed_database

    gov = try_governed_database(
        resolved, db, execute_sql, prior_plan=prior_plan, prior_rows=prior_rows
    )
    if not gov:
        gov = try_governed_database(
            q, db, execute_sql, prior_plan=prior_plan, prior_rows=prior_rows
        )
    if gov:
        if str(gov.get("answer_status") or "").upper() == "CLARIFICATION" or gov.get("type") == "clarification":
            gov["mode"] = "clarification"
            gov["pipeline"] = gov.get("pipeline") or "adaptive_orchestrator"
            return gov
        qp = gov.get("query_plan") if isinstance(gov.get("query_plan"), dict) else {}
        ac = qp.get("analytical_context") if isinstance(qp.get("analytical_context"), dict) else {}
        state.tables = list(ac.get("tables") or state.tables)
        state.metric = str(ac.get("metric") or state.metric or "")
        state.last_sql = str(gov.get("sql") or "")
        state.last_user_question = q
        state.last_resolved_question = resolved
        gov["mode"] = gov.get("mode") or "database_analysis"
        gov["route"] = "database"
        gov["query_plan"] = {**qp, "investigation_state": state.to_dict(), "pipeline1": p1}
        gov.setdefault("pipeline", gov.get("pipeline") or "governed_under_orchestrator")
        return gov

    p2 = _pipeline2_sql(
        resolved, q, p1, state, db, execute_sql,
        use_sap=use_sap, get_sap_session=get_sap_session,
    )
    if p2.get("error"):
        missing = p2.get("missing") or []
        if any(str(m).upper() == "VBED" for m in missing) or "vbed" in q.lower():
            msg = (
                "VBED is not available in the imported dataset. "
                "Schedule-line data in this extract is in VBEP. Would you like me to use VBEP?"
            )
            status = "CANNOT_ANSWER"
        else:
            msg = (
                "I understood this as a database question, but I could not build a valid query "
                "for the requested tables and columns. I did not invent a row-count fallback. "
                f"{p2.get('detail') or p2.get('error')}"
            )
            status = "CANNOT_ANSWER"
        return {
            "mode": "error",
            "route": "database",
            "status": "error",
            "answer_status": status,
            "type": "cannot_answer",
            "sql": p2.get("sql") or "",
            "data": [],
            "rowCount": 0,
            "summary": msg,
            "answer": msg,
            "keyFindings": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "pipeline2_failed",
            "degraded_fallback": False,
            "llm_calls": 3,
            "query_plan": {"investigation_state": state.to_dict(), "pipeline1": p1, "pipeline2": {k: p2.get(k) for k in ("error", "tables", "missing")}},
        }

    sql = p2["sql"]
    rows = p2["rows"]
    tables = p2["tables"]
    requested_dims = p1.get("dimensions") or state.dimensions or []
    if isinstance(requested_dims, str):
        requested_dims = [requested_dims]
    missing_dims = missing_result_dimensions(rows, [str(d) for d in requested_dims])
    if missing_dims and rows:
        extra = dict(p1)
        extra["dimensions"] = list(requested_dims) + missing_dims
        extra["_complete_missing"] = missing_dims
        p2b = _pipeline2_sql(
            resolved + f" Also include these missing fields: {', '.join(missing_dims)}.",
            q,
            extra,
            state,
            db,
            execute_sql,
            use_sap=use_sap,
            get_sap_session=get_sap_session,
        )
        if not p2b.get("error") and p2b.get("rows"):
            sql, rows, tables = p2b["sql"], p2b["rows"], p2b["tables"]
            p2 = p2b
            missing_dims = missing_result_dimensions(rows, [str(d) for d in requested_dims])
    p3 = _pipeline3_interpret(q, resolved, sql, rows, tables, p1)
    charts: List[Dict[str, Any]] = []
    if chart_fn and rows:
        try:
            charts = chart_fn(resolved, sql, rows) or []
        except Exception as exc:
            logger.warning("[adaptive-orch] charts failed: %s", exc)

    dims = p1.get("dimensions") or state.dimensions
    if isinstance(dims, str):
        dims = [dims]
    state.metric = str((p1.get("metrics") or [state.metric])[0] if isinstance(p1.get("metrics"), list) and p1.get("metrics") else p1.get("metrics") or state.metric)
    if isinstance(p1.get("metrics"), str):
        state.metric = p1["metrics"]
    state.dimensions = [str(d) for d in dims if d]
    state.time_period = str(p1.get("time_period") or state.time_period or "")
    state.ranking = str(p1.get("ranking") or state.ranking or "")
    state.tables = tables
    state.last_sql = sql
    state.last_user_question = q
    state.last_resolved_question = resolved
    state.last_summary = str(p3.get("summary") or p3.get("answer") or "")[:2000]

    findings = p3.get("findings") or []
    if not isinstance(findings, list):
        findings = [str(findings)]
    findings = [str(f).strip() for f in findings if str(f).strip()][:8]
    limitations = p3.get("limitations") or []
    if not isinstance(limitations, list):
        limitations = [str(limitations)] if limitations else []

    empty = len(rows) == 0
    summary = str(p3.get("summary") or p3.get("answer") or "").strip()
    if empty and not summary:
        summary = f"No records matched “{resolved}”."

    return {
        "mode": "database_analysis",
        "route": "database",
        "status": "empty" if empty else "success",
        "answer_status": "SUCCESS",
        "sql": sql,
        "data": rows,
        "rowCount": len(rows),
        "summary": summary,
        "answer": str(p3.get("answer") or summary),
        "keyFindings": findings,
        "charts": charts,
        "pipeline": "adaptive_orchestrator",
        "sql_generation_method": "pipeline2_sql",
        "llm_calls": 4,
        "tables_used": tables,
        "resolved_question": resolved,
        "suggested_followups": p3.get("follow_up_suggestions") or [
            "Which country?",
            "And industry?",
            "Show the top 5.",
        ],
        "query_plan": {
            "investigation_state": state.to_dict(),
            "analytical_context": {
                "intent": p1.get("intent") or "adaptive_analysis",
                "metric": state.metric,
                "dimensions": state.dimensions,
                "tables": tables,
                "period": state.time_period,
                "domain": state.domain,
            },
        },
        "calculation": {
            "source": ", ".join(tables),
            "definition": state.metric or "As selected by database intelligence",
            "aggregation": "See SQL",
            "period": state.time_period or "Not specified",
            "grain": (p2.get("pick") or {}).get("grain") or "",
            "limitations": limitations,
        },
        "meta": {
            "mode": "database_analysis",
            "tables": tables,
            "incomplete": bool(p3.get("incomplete")),
            "warnings": limitations,
            "providers": [p1.get("_provider")],
        },
        "presentation": {
            "type": p3.get("presentation_type") or ("kpi" if len(rows) == 1 else "table"),
            "title": resolved[:120],
        },
    }
