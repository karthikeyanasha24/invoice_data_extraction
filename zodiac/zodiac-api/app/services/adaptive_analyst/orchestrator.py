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
from dataclasses import dataclass
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


SALES_ORDERS_VS_BILLED = (
    "I found both sales-order data (VBAK/VBAP) and invoiced/billed sales (VBRK/VBRP). "
    "Do you want: 1) Sales orders  2) Invoiced/billed sales?"
)

_GENERAL_CHAT_SYSTEM = (
    "You are BridgeEDI AI Analyst. Always respond in clear English unless the user writes "
    "their entire message in another language. Be concise and natural, like ChatGPT or Gemini. "
    "Answer general knowledge directly. Do not invent SAP database numbers. "
    "Do not mention pipelines, schemas, or internal tooling unless asked."
)


def _deterministic_greeting_reply(question: str) -> Optional[str]:
    """Fast English greeting — avoids LLM language drift on hi/hai/hey."""
    try:
        from ..adaptive_nl_sql_hardening import is_greeting_or_chitchat
    except Exception:
        return None
    if not is_greeting_or_chitchat(question):
        return None
    ql = re.sub(r"[?!.,]+$", "", (question or "").strip().lower())
    if ql in {"thanks", "thank you", "thankyou"}:
        return "You're welcome! Ask me anything — general questions or SAP business analysis."
    if ql in {"bye", "goodbye", "good night"}:
        return "Goodbye! Come back anytime you need help."
    if ql in {"good morning", "good evening", "good afternoon"}:
        return "Hello! How can I help you today?"
    return "Hi there! How can I help you today?"


def _is_questionnaire(text: str) -> bool:
    t = text or ""
    return (
        t.count("?") >= 3
        or len(t) > 280
        or "currency conversion" in t.lower()
        or "credit memo" in t.lower()
        or "preferred output" in t.lower()
    )


def _is_sales_vs_billing_clarify(msg: str) -> bool:
    t = (msg or "").lower()
    return ("sales order" in t or "sales-order" in t) and (
        "billed" in t or "invoice" in t or "billing" in t
    )


def _short_clarification(msg: str) -> str:
    if not msg or _is_questionnaire(msg):
        return SALES_ORDERS_VS_BILLED
    return msg.strip()


def _awaiting_sales_choice(prior_plan: Optional[Dict[str, Any]], prior_question: str = "") -> bool:
    plan = prior_plan or {}
    if plan.get("awaiting_sales_choice"):
        return True
    state = plan.get("investigation_state") if isinstance(plan.get("investigation_state"), dict) else {}
    if str(state.get("awaiting") or "") == "sales_vs_billing":
        return True
    pq = (prior_question or "").strip().lower()
    return bool(re.fullmatch(r"(show( me)?( our)? )?sales( data)?\.?", pq))


_TOPN_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "fifteen": 15, "twenty": 20, "fifty": 50,
}


def _parse_topn(question: str) -> Optional[int]:
    ql = re.sub(r"[.?!]+$", "", (question or "").strip().lower())
    if re.fullmatch(r"\d{1,3}", ql):
        n = int(ql)
        return n if 1 <= n <= 100 else None
    if ql in _TOPN_WORDS:
        return _TOPN_WORDS[ql]
    m = re.fullmatch(r"(top\s+)?(\d{1,3})(\s+customers?)?", ql)
    if m:
        n = int(m.group(2))
        return n if 1 <= n <= 100 else None
    return None


def _prior_is_sales_ranking(prior_question: str) -> bool:
    pq = (prior_question or "").strip().lower()
    if not pq:
        return False
    if re.search(r"\btop\s+(\d+\s+)?(customers?|countries)\s+by\s+(sales|revenue)\b", pq):
        return True
    if re.search(r"\bhighest sales\b", pq) or re.search(r"\bwho(m)? had\b", pq):
        return True
    return False


def ensure_default_ranking_limit(question: str) -> str:
    """If the question is a top-customers ranking without N, default to top 10."""
    q = (question or "").strip()
    if re.search(r"\btop\s+\d+\b", q, re.I):
        return q
    return re.sub(
        r"\btop\s+(customers?|countries)\s+by\s+",
        r"top 10 \1 by ",
        q,
        count=1,
        flags=re.I,
    )


def resolve_topn_choice(question: str, prior_question: str = "") -> Optional[str]:
    """Map a bare number after a ranking question to 'top N customers by sales'."""
    n = _parse_topn(question)
    if n is None:
        m = re.search(r"\btop\s+(\d{1,3})\b", (question or ""), re.I)
        if m:
            n = int(m.group(1))
    if n is None or not _prior_is_sales_ranking(prior_question):
        return None
    years = re.findall(r"\b((?:19|20)\d{2})\b", prior_question or "")
    q = f"top {n} customers by sales"
    if years:
        q += " in " + " and ".join(sorted(set(years)))
    return q


def resolve_sales_choice(question: str, awaiting: bool = False) -> Optional[str]:
    """Map a short answer to the sales-orders vs billed-invoices clarify into a real question."""
    ql = re.sub(r"[.?!]+$", "", (question or "").strip().lower())
    ql = re.sub(r"^\s*(option|choice|#)\s*", "", ql)
    if awaiting and re.fullmatch(r"(1|1\))", ql):
        return "How many sales orders are there?"
    if awaiting and re.fullmatch(r"(2|2\))", ql):
        return "Show the top customers by billed sales."
    if re.fullmatch(r"(orders?|sales\s*orders?|sales-order|vbak|vbap)", ql):
        return "How many sales orders are there?"
    if re.fullmatch(
        r"(billed|billing|invoices?|billed invoices?|invoiced|invoiced sales|"
        r"recognized invoices?|vbrk|vbrp)",
        ql,
    ):
        return "Show the top customers by billed sales."
    if awaiting and re.fullmatch(r"(first|the first( one)?)", ql):
        return "How many sales orders are there?"
    if awaiting and re.fullmatch(r"(second|the second( one)?)", ql):
        return "Show the top customers by billed sales."
    return None


def _is_limit_clarify(msg: str) -> bool:
    t = (msg or "").lower()
    return bool(
        re.search(r"how many (top )?customers", t)
        or "should i return" in t
        or "answer with a number" in t
        or ("how many" in t and "top" in t)
    )


@dataclass
class AdaptedTurn:
    """Deterministic reading of this user turn. LLM must not override it."""

    action: str  # query | clarify | chat
    question: str
    drop_prior: bool = False
    is_fragment: bool = False
    clarify_message: str = ""


def adapt_user_turn(
    question: str,
    *,
    prior_question: str = "",
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_status: str = "",
) -> AdaptedTurn:
    """Map the current message to query / one allowed clarify / chat. No LLM."""
    from ...data_catalog.source_selector import _ambiguous_sales, _ql
    from ..ai_followup_routing import looks_like_followup_utterance, looks_like_standalone_analytical
    from ..ranking_question_normalizer import normalize_ranking_question

    q = (question or "").strip()
    if _force_general_chat(q):
        return AdaptedTurn("chat", q)

    awaiting_sales = _awaiting_sales_choice(prior_plan, prior_question)
    chosen = resolve_sales_choice(q, awaiting=awaiting_sales)
    if chosen:
        return AdaptedTurn("query", chosen, drop_prior=True)

    status = (prior_status or "").upper()
    topn = resolve_topn_choice(q, prior_question)
    if not topn and _parse_topn(q) and not awaiting_sales:
        if status == "CLARIFICATION" or _prior_is_sales_ranking(prior_question):
            topn = resolve_topn_choice(q, prior_question or "highest sales")
    if topn:
        return AdaptedTurn("query", ensure_default_ranking_limit(topn), drop_prior=True)

    ranked = normalize_ranking_question(q)
    ranked = ensure_default_ranking_limit(ranked)
    ql = _ql(ranked)
    if _ambiguous_sales(ql):
        return AdaptedTurn(
            "clarify",
            ranked,
            clarify_message=SALES_ORDERS_VS_BILLED,
        )

    standalone = looks_like_standalone_analytical(ranked)
    fragment = looks_like_followup_utterance(q) and not standalone
    drop = standalone or bool(
        re.search(r"\b(highest sales|top \d+ customers by sales|who had)\b", ranked, re.I)
    )
    return AdaptedTurn("query", ranked, drop_prior=drop, is_fragment=fragment)


def _log_stage(name: str, payload: Dict[str, Any]) -> None:
    safe = {k: payload.get(k) for k in list(payload)[:12]}
    logger.info("[adaptive-orch] %s %s", name, json.dumps(safe, default=str)[:800])


def _force_general_chat(question: str) -> bool:
    """Safety net: never send non-database turns to SQL."""
    from ..adaptive_nl_sql_hardening import (
        is_capability_or_help_question,
        is_general_knowledge_question,
        is_greeting_or_chitchat,
    )

    if is_greeting_or_chitchat(question):
        return True
    if is_capability_or_help_question(question):
        return True
    if is_general_knowledge_question(question):
        return True
    ql = re.sub(r"[?!.,]+$", "", (question or "").strip().lower())
    if re.fullmatch(r"(as of|since when|when|how about that)\??", ql):
        return True
    return False


def _prior_summary_from_state(state: "InvestigationState", prior_plan: Optional[Dict[str, Any]]) -> str:
    if (state.last_summary or "").strip():
        return state.last_summary.strip()
    plan = prior_plan if isinstance(prior_plan, dict) else {}
    inv = plan.get("investigation_state") if isinstance(plan.get("investigation_state"), dict) else {}
    return str(inv.get("last_summary") or "").strip()


def _attach_understanding_meta(payload: Dict[str, Any], understanding: Any) -> Dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    public = understanding.to_public_dict() if hasattr(understanding, "to_public_dict") else {}
    payload["meta"] = {
        **meta,
        "understanding_model_called": bool(getattr(understanding, "understanding_model_called", False)),
        "understanding_result": public,
        "selected_capability": str(getattr(understanding, "intent", "") or meta.get("selected_capability") or ""),
    }
    qp = payload.get("query_plan") if isinstance(payload.get("query_plan"), dict) else {}
    payload["query_plan"] = {**qp, "understanding": public}
    return payload


def _general_chat_prompt(question: str, state: "InvestigationState") -> str:
    parts: List[str] = []
    if state.last_user_question and state.last_summary:
        parts.append(f"Previous user message: {state.last_user_question}")
        parts.append(f"Your previous answer: {state.last_summary}")
    parts.append(f"Current user message: {question}")
    return "\n".join(parts)


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
            "general_conversation/general_knowledge. reply MUST be in English.\n"
            "OUR company facts (sales, invoices, VBAK, customers) → requires_database=true.\n"
            "Short follow-ups (which country?, reflected?, they, Germany, top 5, 2005, why?, "
            "industry?, the product, who supplied) MUST is_follow_up=true and rewritten_question "
            "must be a FULL question using investigation state. Never send 'reflected?' to SQL.\n"
            "A COMPLETE question (who/which + highest sales + a year, or 'top customers by sales') "
            "is a NEW investigation. Do not reuse the previous tables. Unqualified highest/top sales "
            "means billed invoices (VBRK/VBRP), not sales orders.\n"
            "clarification_needed for sales orders vs billed invoices ONLY if the user said bare "
            "'sales' / 'show me our sales data' with no year, ranking, customer, or table name. "
            "Never re-ask that choice after they already answered, and never ask it for "
            "'who had the highest sales in 2004'. "
            "Never ask how many rows or top-N to return — default LIMIT 10. "
            "clarification_question MUST be exactly two short sentences. "
            "Never ask about currency conversion, credit memos, output format, metrics list, "
            "or more than one question mark.\n"
            f"User: {question}\n"
            f"Investigation state: {json.dumps(state.to_dict(), default=str)}\n"
            f"Prior result sample: {json.dumps(sample_rows[:5], default=str)[:1500]}\n"
        ),
    )
    analysis["_provider"] = provider
    _log_stage("PIPELINE_1", analysis)
    return analysis


def _run_four_stage_or_legacy_sql(
    resolved: str,
    original: str,
    analysis: Dict[str, Any],
    state: InvestigationState,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    use_sap: bool,
    get_sap_session: Optional[Callable[[], Any]],
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_sql: str = "",
) -> Dict[str, Any]:
    """Four-stage schema-intelligence pipeline (primary). Legacy _pipeline2_sql on crash."""
    sess = db
    sap = None
    try:
        if use_sap and get_sap_session:
            sap = get_sap_session()
            if sap is not None:
                sess = sap
        from ..four_stage_db_pipeline import run_four_stage_database_query

        merged_plan: Dict[str, Any] = dict(prior_plan or {})
        inv = merged_plan.get("investigation_state")
        if not isinstance(inv, dict):
            merged_plan["investigation_state"] = state.to_dict()
        return run_four_stage_database_query(
            resolved,
            sess,
            execute_sql,
            prior_plan=merged_plan,
            prior_sql=(prior_sql or state.last_sql or "").strip(),
        )
    except Exception as exc:
        from ..investigation_budget import InvestigationTimeout

        if isinstance(exc, InvestigationTimeout):
            raise
        # Legacy free-form NL→SQL is not an analytics authority. Fail closed so
        # four-stage remains the only SAP analytics path.
        logger.warning("[adaptive-orch] four_stage failed (%s); refusing legacy pipeline2 bypass", exc)
        return {
            "mode": "error",
            "status": "completed",
            "answer_status": "CANNOT_ANSWER",
            "error": "four_stage_failed",
            "error_kind": "pipeline_error",
            "error_class": "TECHNICAL_ERROR",
            "sql": "",
            "rows": [],
            "data": [],
            "rowCount": 0,
            "summary": (
                "The adaptive analytics engine encountered an internal failure and did not "
                "fall back to an unverified SQL path. Please retry the question."
            ),
            "answer": "The investigation could not be completed due to a technical failure.",
            "pipeline": "four_stage_failed_no_legacy",
            "query_plan": {"investigation_state": state.to_dict()},
            "meta": {"investigation_status": "failed", "legacy_bypass": False},
        }
    finally:
        if sap is not None:
            try:
                sap.close()
            except Exception:
                pass


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
    prior_status: str = "",
    force_general_chat: bool = False,
    schema_for_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from .understanding import (
        analytics_clarification_payload,
        capability_facts,
        generate_grounded_response,
        is_sufficiently_specified_ranking,
        technical_understanding_failure,
        understand_turn,
    )
    from ..ai_followup_routing import is_prior_general_chat

    q = (question or "").strip()
    adapted = adapt_user_turn(
        q,
        prior_question=prior_question,
        prior_plan=prior_plan,
        prior_status=prior_status,
    )
    # No canned greeting/capability text — every turn uses LLM understanding
    # (ChatGPT-style). Safety gates stay after understanding.

    # Sales-order vs billed choice remains a governed clarify (not LLM authorization).
    if adapted.action == "clarify":
        state = InvestigationState.from_context(prior_plan, prior_question, prior_sql)
        if thread_id:
            state.conversation_id = thread_id
        return {
            "mode": "clarification",
            "route": "clarification",
            "status": "clarification",
            "answer_status": "CLARIFICATION",
            "type": "clarification",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": adapted.clarify_message or SALES_ORDERS_VS_BILLED,
            "answer": adapted.clarify_message or SALES_ORDERS_VS_BILLED,
            "keyFindings": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "turn_adapter",
            "llm_calls": 0,
            "query_plan": {
                "investigation_state": {**state.to_dict(), "awaiting": "sales_vs_billing"},
                "awaiting_sales_choice": True,
            },
            "suggested_followups": [
                "How many sales orders are there?",
                "Show the top customers by billed sales.",
            ],
            "meta": {"selected_capability": "clarification", "understanding_model_called": False},
        }

    q = adapted.question
    # Preserve conversation context for understanding — do not drop prior on
    # standalone-looking chat follow-ups after general_chat.
    prior_was_chat = is_prior_general_chat(prior_plan, prior_status, prior_sql)
    preserved_turns: List[Dict[str, Any]] = []
    if isinstance(prior_plan, dict):
        inv_prior = prior_plan.get("investigation_state")
        if isinstance(inv_prior, dict) and isinstance(inv_prior.get("recent_turns"), list):
            preserved_turns = list(inv_prior.get("recent_turns") or [])
        elif isinstance(prior_plan.get("recent_turns"), list):
            preserved_turns = list(prior_plan.get("recent_turns") or [])
    if adapted.drop_prior and not prior_was_chat and not force_general_chat:
        # Drop analytical SQL/plan — but keep rolling chat turns (ChatGPT memory).
        prior_question = ""
        prior_sql = ""
        prior_plan = None
        prior_rows = []
    state = InvestigationState.from_context(prior_plan, prior_question, prior_sql)
    if preserved_turns and not state.recent_turns:
        state.recent_turns = preserved_turns[-12:]
    elif preserved_turns and adapted.drop_prior:
        # Merge: keep preserved history even if a thin plan was rebuilt.
        merged = list(preserved_turns)
        for t in state.recent_turns:
            if t not in merged:
                merged.append(t)
        state.recent_turns = merged[-12:]
    if thread_id:
        state.conversation_id = thread_id
    prior_summary = _prior_summary_from_state(state, prior_plan)

    from ...data_catalog.source_selector import (
        _ambiguous_sales,
        _explicit_invoice,
        _explicit_sales_order,
        _ql,
        select_source,
    )
    from ..adaptive_nl_sql_hardening import is_greeting_or_chitchat

    # Fast path: short greetings = ONE LLM reply (not understand JSON + respond).
    # Still model-generated — not a canned template — ChatGPT-like latency.
    if is_greeting_or_chitchat(q):
        try:
            from .llm_provider import complete_text

            prior_bit = ""
            if prior_summary:
                prior_bit = f"Prior assistant reply (context only): {prior_summary[:400]}\n"
            reply, provider = complete_text(
                "You are BridgeEDI AI Analyst. Reply naturally in 1-2 short sentences. "
                "Do not invent database numbers. Do not list capabilities unless asked.",
                f"{prior_bit}User: {q}\nAssistant:",
            )
            reply = (reply or "").strip() or "Hi — how can I help you today?"
        except Exception as greet_err:
            return technical_understanding_failure(q, greet_err)
        state.remember_turn(q, reply, mode="general_chat")
        out = {
            "mode": "general_chat",
            "route": "general",
            "status": "success",
            "answer_status": "SUCCESS",
            "failure_class": "SUCCESS",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": reply,
            "answer": reply,
            "keyFindings": [],
            "charts": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "llm_greeting_fast",
            "llm_calls": 1,
            "query_plan": {
                "investigation_state": {**state.to_dict(), "mode": "general_chat"},
                "last_mode": "general_chat",
            },
            "meta": {
                "mode": "general_chat",
                "failure_class": "SUCCESS",
                "understanding_model_called": False,
                "response_model_called": True,
                "selected_capability": "greeting",
                "provider": provider,
                "fast_path": "greeting_single_llm",
            },
            "suggested_followups": [
                "What can you help with?",
                "How many tables are there?",
                "Show top customers by billed sales.",
            ],
        }
        return out

    # ── LLM-first understanding (structured intent; not authorization) ──
    try:
        understanding = understand_turn(
            q,
            prior_question=prior_question,
            prior_summary=prior_summary,
            prior_plan=prior_plan if isinstance(prior_plan, dict) else None,
            prior_status=prior_status,
            capability_context=capability_facts(),
        )
    except Exception as understand_err:
        return technical_understanding_failure(q, understand_err)

    intent = understanding.intent
    # Do not over-clarify when the user already gave metric + top-N + dimension.
    if is_sufficiently_specified_ranking(q) and intent in {
        "analytics",
        "investigation",
        "clarification",
    }:
        understanding.intent = "analytics"
        understanding.clarification_needed = False
        understanding.clarification_question = None
        intent = "analytics"

    # Application capability selection (governed): map intent → safe path.
    # greeting uses the same grounded LLM reply path (no canned strings).
    if intent in {"conversation", "knowledge", "capability", "greeting"} or (
        force_general_chat and intent not in {"analytics", "investigation", "metadata"}
    ):
        try:
            resp_evidence = capability_facts() if intent == "capability" else None
            table_turns: List[Dict[str, Any]] = []
            if state.recent_turns:
                # Prefer true metadata tool answers over chat that merely says "tables".
                table_turns = [
                    t
                    for t in state.recent_turns
                    if str(t.get("mode") or "") == "database_metadata"
                    and str(t.get("role") or "") == "assistant"
                ]
                if not table_turns:
                    table_turns = [
                        t
                        for t in state.recent_turns
                        if str(t.get("role") or "") == "assistant"
                        and re.search(
                            r"\b\d+\s+tables?\b|table\(s\) may relate|available in the connected database",
                            str(t.get("content") or ""),
                            re.I,
                        )
                    ]
                base = {"recent_turns": state.recent_turns}
                if table_turns and re.search(r"\btables?\b", q, re.I):
                    base["relevant_prior_about_tables"] = table_turns[-6:]
                    base["instruction"] = (
                        "The user is asking about prior table/schema answers. "
                        "Summarize those prior assistant messages; do not pivot to sales."
                    )
                if resp_evidence is None:
                    resp_evidence = base
                elif isinstance(resp_evidence, dict):
                    resp_evidence = {**resp_evidence, **base}
            reply, provider = generate_grounded_response(
                q,
                understanding,
                prior_question=prior_question,
                prior_summary=prior_summary,
                evidence=resp_evidence,
            )
            # If user asks what we said about tables and we have prior metadata
            # turns, ground the reply on those turns (ChatGPT-style recall).
            if (
                table_turns
                and re.search(r"\btables?\b", q, re.I)
                and re.search(r"\b(tell|told|say|said|mention|about)\b", q, re.I)
            ):
                grounded_bits = []
                for t in table_turns:
                    if str(t.get("role")) != "assistant":
                        continue
                    c = str(t.get("content") or "").strip()
                    if c:
                        grounded_bits.append(c[:500])
                if grounded_bits:
                    recall_user = (
                        "The user asked what you previously said about tables/schema.\n"
                        "Prior assistant answers about tables (authoritative):\n- "
                        + "\n- ".join(grounded_bits[-4:])
                        + "\n\nWrite a short natural reply that recalls those facts. "
                        "Do not deny them. Do not switch to sales clarification."
                    )
                    try:
                        from .llm_provider import complete_text as _complete

                        recall, provider2 = _complete(
                            "You are BridgeEDI AI Analyst. Recall prior answers accurately.",
                            recall_user,
                        )
                        if (recall or "").strip():
                            reply = recall.strip()
                            provider = provider2 or provider
                    except Exception:
                        reply = "Earlier about tables I said:\n- " + "\n- ".join(grounded_bits[-3:])
        except Exception as resp_err:
            return technical_understanding_failure(q, resp_err)
        state.remember_turn(q, reply, mode="general_chat")
        out = {
            "mode": "general_chat",
            "route": "general",
            "status": "success",
            "answer_status": "SUCCESS",
            "failure_class": "SUCCESS",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": reply,
            "answer": reply,
            "keyFindings": [],
            "charts": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "llm_understanding_response",
            "llm_calls": 2,
            "query_plan": {
                "investigation_state": {
                    **state.to_dict(),
                    "mode": "general_chat",
                },
                "last_mode": "general_chat",
                "understanding": understanding.to_public_dict(),
            },
            "meta": {
                "mode": "general_chat",
                "failure_class": "SUCCESS",
                "understanding_model_called": True,
                "response_model_called": True,
                "selected_capability": intent,
                "provider": provider,
            },
            "suggested_followups": [
                "How many tables are there?",
                "Show the top customers by billed sales.",
                "What is SAP?",
            ],
        }
        return _attach_understanding_meta(out, understanding)

    if intent == "metadata" or understanding.requires_metadata:
        from .database_metadata import answer_database_metadata

        schema = schema_for_metadata if isinstance(schema_for_metadata, dict) else {}
        if not schema:
            try:
                from ...data_catalog.physical import load_physical_schema

                schema = load_physical_schema() or {}
            except Exception:
                schema = {}
        meta_payload = answer_database_metadata(q, schema=schema)
        if meta_payload is None and re.search(
            r"(?i)\b(all|entire|full|complete)\b|\blist\b|\b\d+\s+to\s+be\s+listed\b",
            q,
        ):
            # Follow-up "list all 121" may omit the word "tables" — still list them.
            from .database_metadata import (
                LIST_TABLES,
                MetadataPlan,
                build_metadata_payload,
                execute_metadata_plan,
            )

            forced = MetadataPlan(operation=LIST_TABLES, confidence=0.85, list_all=True)
            meta_payload = build_metadata_payload(q, forced, execute_metadata_plan(forced, schema))
        if meta_payload is None:
            # Understanding said metadata but tool could not map — clarify schema ask.
            msg = (
                "I can inspect the connected schema (table counts, columns, table search). "
                "Try: \"How many tables are there?\" or \"List all tables.\""
            )
            out = {
                "mode": "clarification",
                "route": "database_metadata",
                "answer_status": "CLARIFICATION",
                "type": "clarification",
                "sql": "",
                "data": [],
                "rowCount": 0,
                "summary": msg,
                "answer": msg,
                "keyFindings": [],
                "pipeline": "adaptive_orchestrator",
                "sql_generation_method": "metadata_clarify",
                "llm_calls": 1,
                "query_plan": {"last_mode": "clarification", "understanding": understanding.to_public_dict()},
                "meta": {"selected_capability": "metadata", "understanding_model_called": True},
            }
            return _attach_understanding_meta(out, understanding)
        meta_payload = dict(meta_payload)
        meta_payload["llm_calls"] = int(meta_payload.get("llm_calls") or 0) + 1
        meta_payload["pipeline"] = meta_payload.get("pipeline") or "adaptive_orchestrator"
        summary = str(meta_payload.get("summary") or meta_payload.get("answer") or "")
        state.remember_turn(q, summary, mode="database_metadata")
        qp = meta_payload.get("query_plan") if isinstance(meta_payload.get("query_plan"), dict) else {}
        meta_payload["query_plan"] = {
            **qp,
            "last_mode": "database_metadata",
            "investigation_state": {**state.to_dict(), "mode": "database_metadata"},
            "understanding": understanding.to_public_dict(),
        }
        logger.info("[adaptive-orch] tool_called=database_metadata op=%s", (meta_payload.get("meta") or {}).get("operation"))
        return _attach_understanding_meta(meta_payload, understanding)

    if intent == "clarification" or (
        understanding.clarification_needed and intent in {"analytics", "investigation", "clarification"}
    ):
        # Only after understanding established an analytical ask with gaps.
        clar = analytics_clarification_payload(q, understanding)
        state.remember_turn(q, str(clar.get("summary") or ""), mode="clarification")
        qp = clar.get("query_plan") if isinstance(clar.get("query_plan"), dict) else {}
        clar["query_plan"] = {
            **qp,
            "investigation_state": {**state.to_dict(), "mode": "clarification"},
            "last_mode": "clarification",
        }
        return _attach_understanding_meta(clar, understanding)

    if intent == "cannot_answer":
        msg = understanding.goal or "I cannot answer that with the available governed capabilities."
        out = {
            "mode": "error",
            "route": "understanding",
            "answer_status": "CANNOT_ANSWER",
            "type": "cannot_answer",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": msg,
            "answer": msg,
            "keyFindings": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "understanding_cannot_answer",
            "llm_calls": 1,
            "meta": {"selected_capability": "cannot_answer", "understanding_model_called": True},
            "query_plan": {"understanding": understanding.to_public_dict()},
        }
        return _attach_understanding_meta(out, understanding)

    # analytics / investigation → existing governed SQL pipeline
    adapted = AdaptedTurn("query", q, drop_prior=adapted.drop_prior, is_fragment=adapted.is_fragment)
    skip_p1_clarify = not adapted.is_fragment
    if skip_p1_clarify:
        p1 = {
            "question_type": "database_question",
            "route": "database",
            "requires_database": True,
            "clarification_needed": False,
            "rewritten_question": q,
            "intent": "understanding_analytics",
        }
    else:
        p1 = _pipeline1_understand(q, state, prior_rows or [])
    requires_db = True
    route = "database"
    skip_clarify = True
    logger.info(
        "[adaptive-orch] selected_capability=analytics understanding_intent=%s",
        intent,
    )

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
        if (
            str(gov.get("answer_status") or "").upper() == "CANNOT_ANSWER"
            or gov.get("type") == "cannot_answer"
            or (isinstance(gov.get("meta"), dict) and gov["meta"].get("data_gap"))
        ):
            gov["mode"] = "data_limitation"
        else:
            gov["mode"] = gov.get("mode") or "database_analysis"
        gov["route"] = "database"
        gov["query_plan"] = {**qp, "investigation_state": state.to_dict(), "pipeline1": p1}
        gov.setdefault("pipeline", gov.get("pipeline") or "governed_under_orchestrator")
        return _attach_understanding_meta(gov, understanding)

    from ..result_first_followup import try_answer_from_prior_rows, is_result_scoped_followup

    if prior_rows or is_result_scoped_followup(q, has_prior_rows=bool(prior_rows)):
        reused = try_answer_from_prior_rows(
            q, prior_rows, prior_sql=prior_sql, prior_plan=prior_plan
        )
        if reused and not reused.get("needs_plan_expansion"):
            reused["query_plan"] = {
                **(reused.get("query_plan") or {}),
                "investigation_state": state.to_dict(),
                "pipeline1": p1,
            }
            return reused
        if reused and reused.get("needs_plan_expansion") and reused.get("expanded_question"):
            # Adaptive replan: growth follow-up cannot invent deltas from levels —
            # continue with a scoped rewritten question grounded in prior entities.
            expanded = str(reused["expanded_question"]).strip()
            if expanded:
                resolved = expanded
                q = expanded
                p1 = {**(p1 or {}), "rewritten_question": expanded, "is_follow_up": True}
                _log_stage("FOLLOWUP_PLAN_EXPANSION", {"expanded": expanded[:200]})

    # ── Reliability: regenerate on a plan-check miss instead of dead-ending ──
    # SQL is generated fresh by the LLM each turn, so an answerable question can
    # fail the validation gate on one run and pass on the next. Give it a few
    # attempts to reach a plan-compliant result before falling through to the
    # existing gate. This only adds tries to runs that would otherwise fail; the
    # authoritative gate below is unchanged, so it never lowers the correctness bar.
    _MAX_SQL_ATTEMPTS = 3
    p2 = {}
    for _sql_attempt in range(_MAX_SQL_ATTEMPTS):
        p2 = _run_four_stage_or_legacy_sql(
            resolved, q, p1, state, db, execute_sql,
            use_sap=use_sap, get_sap_session=get_sap_session,
            prior_plan=prior_plan,
            prior_sql=prior_sql,
        )
        # Only retry the one failure we can improve: a completed query whose
        # result would be rejected by the plan gate. Errors, clarifications,
        # data limitations and empty results are handled by the logic below.
        if p2.get("error") or p2.get("data_limitation"):
            break
        _try_rows = p2.get("rows") or []
        if not _try_rows:
            break
        try:
            from ..plan_satisfaction import result_matches_analytical_intent as _rmai
            _try_sem = (
                (p2.get("verified_context") or {}).get("semantic_requirements")
                if isinstance(p2.get("verified_context"), dict)
                else None
            ) or p1
            _try_warnings = _rmai(
                _try_rows, resolved or q, _try_sem, sql=str(p2.get("sql") or "")
            )
        except Exception:
            _try_warnings = []
        if not _try_warnings:
            break
        _log_stage(
            "SQL_REGENERATE",
            {"attempt": _sql_attempt + 1, "warnings": _try_warnings[:4]},
        )
    if p2.get("data_limitation"):
        msg = str(p2["data_limitation"])
        return {
            "mode": "data_limitation",
            "route": "database",
            "status": "cannot_answer",
            "answer_status": "CANNOT_ANSWER",
            "type": "cannot_answer",
            "sql": "",
            "data": [],
            "rowCount": 0,
            "summary": msg,
            "answer": msg,
            "keyFindings": [],
            "charts": [],
            "pipeline": "four_stage_db_pipeline",
            "sql_generation_method": "pipeline1_data_limitation",
            "query_plan": {
                "investigation_state": state.to_dict(),
                "pipeline1": p1,
                "verified_db_context": p2.get("verified_context"),
                "pipeline_log": p2.get("pipeline_log"),
            },
        }
    if p2.get("error"):
        missing = p2.get("missing") or []
        err_kind = str(p2.get("error_kind") or "")
        if p2.get("error") == "clarification_required" or err_kind == "clarification":
            msg = str(
                p2.get("user_message")
                or (p2.get("clarification") or {}).get("message")
                or "Please clarify the missing analytical parameters."
            )
            clar_type = str((p2.get("clarification") or {}).get("type") or "clarification")
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
                "sql_generation_method": f"{clar_type}_clarification",
                "llm_calls": 2,
                "query_plan": {
                    "investigation_state": state.to_dict(),
                    "pipeline1": p1,
                    "clarification": p2.get("clarification"),
                },
                "suggested_followups": [],
            }
        is_timeout = (
            err_kind == "timeout"
            or p2.get("error") == "timeout"
            or p2.get("timeout")
            or str(p2.get("error_class") or "").lower() == "timeout"
        )
        if is_timeout:
            from ..investigation_budget import TIMEOUT_USER_MESSAGE, timeout_response

            payload = timeout_response(
                str((p2.get("pipeline_log") or {}).get("timeout_stage") or "database"),
                float((p2.get("pipeline_log") or {}).get("elapsed_s") or 0),
                question=q,
            )
            payload["query_plan"] = {
                "investigation_state": state.to_dict(),
                "pipeline1": p1,
                "pipeline_log": p2.get("pipeline_log"),
            }
            return payload
        is_data_limitation = (
            err_kind == "data_limitation"
            or p2.get("error") == "data_limitation"
        )
        if p2.get("error") == "semantic_mismatch":
            from ..investigation_budget import user_safe_pipeline_message as _safe

            msg = str(p2.get("user_message") or _safe("semantic_mismatch"))
            status = "CANNOT_ANSWER"
            failure_class = str(p2.get("failure_class") or "RESULT_VALIDATION_FAILED")
            is_data_limitation = False
        elif any(str(m).upper() == "VBED" for m in missing) or "vbed" in q.lower():
            msg = (
                "VBED is not available in the imported dataset. "
                "Schedule-line data in this extract is in VBEP. Would you like me to use VBEP?"
            )
            status = "CANNOT_ANSWER"
            failure_class = "DATA_NOT_AVAILABLE"
        elif is_data_limitation:
            from ..investigation_budget import user_safe_pipeline_message as _safe

            msg = str(p2.get("data_limitation") or _safe("data_limitation"))
            status = "CANNOT_ANSWER"
            failure_class = "DATA_NOT_AVAILABLE"
        else:
            from ..investigation_budget import user_safe_pipeline_message

            err_u = str(p2.get("error") or "").upper()
            if "SQL_VALIDATION" in err_u or p2.get("error") == "sql_validation_failed":
                failure_class = "SQL_VALIDATION_FAILED"
            elif p2.get("error") == "sql_execution_failed":
                failure_class = "TOOL_FAILURE"
            elif "SCHEMA" in err_u:
                failure_class = "SCHEMA_UNRESOLVED"
            elif "PLAN" in err_u:
                failure_class = "PLAN_INCOMPLETE"
            elif "GENERATION" in err_u or p2.get("error") == "sql_generation_failed":
                failure_class = "MODEL_FAILURE"
            else:
                failure_class = "SYSTEM_FAILURE"
            msg = user_safe_pipeline_message(
                "technical" if failure_class in {"TECHNICAL_ERROR", "SYSTEM_FAILURE", "TOOL_FAILURE", "MODEL_FAILURE"} else "repair_failed"
            )
            if failure_class == "TOOL_FAILURE":
                msg = "I couldn't complete the database analysis because the data service is temporarily unavailable."
            elif failure_class == "MODEL_FAILURE":
                msg = "I couldn't plan a verified query for that question. Try rephrasing with a metric and period."
            status = "CANNOT_ANSWER"
            logger.warning(
                "[adaptive-orch] pipeline error hidden from user: %s %s",
                p2.get("error"),
                p2.get("detail"),
            )
        return {
            "mode": "error" if not is_data_limitation else "data_limitation",
            "route": "database",
            "status": "error" if not is_data_limitation else "cannot_answer",
            "answer_status": status,
            "failure_class": failure_class,
            "type": "cannot_answer" if is_data_limitation else "pipeline_error",
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
            "meta": {
                "investigation_status": failure_class,
                "failure_class": failure_class,
            },
            "query_plan": {"investigation_state": state.to_dict(), "pipeline1": p1, "pipeline2": {k: p2.get(k) for k in ("error", "tables", "missing", "failure_class")}},
        }

    sql = p2["sql"]
    rows = p2["rows"]
    tables = p2["tables"]
    requested_dims = p1.get("dimensions") or state.dimensions or []
    if isinstance(requested_dims, str):
        requested_dims = [requested_dims]
    missing_dims = missing_result_dimensions(rows, [str(d) for d in requested_dims])
    four_stage_ok = bool(p2.get("verified_context")) and not p2.get("error")
    if missing_dims and rows and not four_stage_ok:
        # Do not bypass four-stage with legacy pipeline2. Treat as semantic gap.
        logger.warning(
            "[adaptive-orch] missing dimensions %s after non-four-stage path; refusing legacy repair",
            missing_dims,
        )
        msg = (
            "The result is missing required dimensions "
            f"({', '.join(missing_dims)}) and was not returned as a verified answer."
        )
        return {
            "mode": "error",
            "route": "database",
            "status": "cannot_answer",
            "answer_status": "CANNOT_ANSWER",
            "type": "cannot_answer",
            "sql": sql or "",
            "data": [],
            "rowCount": 0,
            "summary": msg,
            "answer": msg,
            "keyFindings": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "dimension_gap_no_legacy",
            "degraded_fallback": False,
            "llm_calls": 3,
            "query_plan": {"investigation_state": state.to_dict(), "pipeline1": p1, "missing_dims": missing_dims},
        }
    p3 = p2.get("narrative") if isinstance(p2.get("narrative"), dict) else None
    if not p3:
        p3 = _pipeline3_interpret(q, resolved, sql, rows, tables, p1)
    charts: List[Dict[str, Any]] = []
    if chart_fn and rows:
        try:
            charts = chart_fn(resolved, sql, rows) or []
        except Exception as exc:
            logger.warning("[adaptive-orch] charts failed: %s", exc)
    if not charts and rows:
        try:
            from ..chart_decision_engine import build_chart_specs_for_rows

            charts = build_chart_specs_for_rows(rows, resolved or q, sql) or []
        except Exception as exc:
            logger.warning("[adaptive-orch] row-grounded charts failed: %s", exc)

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
    if empty:
        from ..investigation_budget import user_safe_pipeline_message as _empty_msg

        grounded = _empty_msg("empty_success")
        if (not summary) or re.search(r"returned 0 row", summary, re.I):
            summary = grounded
        elif re.search(r"does not (exist|contain)|not in this extract|data limitation", summary, re.I):
            summary = grounded

    # HARD GATE: SQL success ≠ investigation success. Wrong results must never be SUCCESS.
    from ..plan_satisfaction import answer_consistent_with_rows, result_matches_analytical_intent

    semantic = (
        (p2.get("verified_context") or {}).get("semantic_requirements")
        if isinstance(p2.get("verified_context"), dict)
        else None
    ) or p1
    final_warnings = result_matches_analytical_intent(rows, resolved or q, semantic, sql=sql)
    answer_text = str(p3.get("answer") or summary)
    final_warnings.extend(answer_consistent_with_rows(answer_text, rows, resolved or q))
    if final_warnings:
        msg = (
            "The investigation could not be validated against the analytical requirements: "
            + "; ".join(final_warnings[:4])
        )
        return {
            "mode": "error",
            "route": "database",
            "status": "cannot_answer",
            "answer_status": "CANNOT_ANSWER",
            "failure_class": "RESULT_VALIDATION_FAILED",
            "type": "semantic_mismatch",
            "sql": sql or "",
            "data": [],
            "rowCount": 0,
            "summary": msg,
            "answer": msg,
            "keyFindings": [],
            "pipeline": "adaptive_orchestrator",
            "sql_generation_method": "pipeline2_sql",
            "degraded_fallback": False,
            "llm_calls": 4,
            "tables_used": tables,
            "resolved_question": resolved,
            "meta": {"investigation_status": "RESULT_VALIDATION_FAILED", "failure_class": "RESULT_VALIDATION_FAILED", "validation_warnings": final_warnings},
            "query_plan": {
                "investigation_state": state.to_dict(),
                "verified_db_context": p2.get("verified_context"),
                "pipeline_log": p2.get("pipeline_log"),
                "validation_warnings": final_warnings,
            },
        }

    if empty:
        answer_text = summary
    out = {
        "mode": "database_analysis",
        "route": "database",
        "status": "empty" if empty else "completed",
        # NO_DATA = validated empty result; SUCCESS_EMPTY kept as alias for older clients.
        "answer_status": "NO_DATA" if empty else "SUCCESS",
        "failure_class": "NO_DATA" if empty else "SUCCESS",
        "sql": sql,
        "data": rows,
        "rowCount": len(rows),
        "summary": summary,
        "answer": answer_text,
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
            "verified_db_context": p2.get("verified_context"),
            "pipeline_log": p2.get("pipeline_log"),
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
            "investigation_status": "NO_DATA" if empty else "completed",
            "failure_class": "NO_DATA" if empty else "SUCCESS",
            "legacy_status_alias": "SUCCESS_EMPTY" if empty else None,
        },
        "presentation": {
            "type": p3.get("presentation_type") or ("kpi" if len(rows) == 1 else "table"),
            "title": resolved[:120],
        },
    }
    try:
        from .presentation import plan_presentation

        presentation = plan_presentation(
            resolved or q,
            rows,
            semantic=semantic if isinstance(semantic, dict) else None,
            charts=charts,
        )
        out["presentation"] = presentation
        out.setdefault("meta", {})["presentation"] = presentation
    except Exception:
        pass
    try:
        from .diagnostics import build_analytical_diagnostics

        diag = build_analytical_diagnostics(
            question=resolved or q,
            route="database",
            semantic=semantic if isinstance(semantic, dict) else None,
            sql=sql,
            row_count=len(rows),
            result_validation=final_warnings,
            pipeline_log=p2.get("pipeline_log") if isinstance(p2.get("pipeline_log"), dict) else None,
            presentation=out.get("presentation") if isinstance(out.get("presentation"), dict) else None,
            answer_status=str(out.get("answer_status") or ""),
            failure_class=str(out.get("failure_class") or ""),
        )
        out["diagnostics"] = diag
        out.setdefault("meta", {})["diagnostics"] = diag
        out.setdefault("query_plan", {})["diagnostics"] = {
            k: diag.get(k)
            for k in (
                "semantic_plan",
                "replanning",
                "presentation",
                "final_status",
                "execution",
            )
        }
    except Exception:
        pass
    state.remember_turn(q, str(out.get("summary") or ""), mode="database_analysis")
    out.setdefault("query_plan", {})["investigation_state"] = {
        **state.to_dict(),
        "mode": "database_analysis",
    }
    return _attach_understanding_meta(out, understanding)
