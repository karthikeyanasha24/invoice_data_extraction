"""
Fast path for /dashboard/ai-analysis/chat: strict intent SQL + light summary/chart.

Skips LangGraph (schema LLM, generate_sql, verify_answer, etc.) for billing/revenue
analytics that is_intent_pipeline_appropriate() accepts.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from .intent_extractor import extract_intent, is_intent_pipeline_appropriate
from .intent_sql_planner import build_sql_plan, generate_sql
from .intent_summary import generate_summary as generate_intent_summary
from .intent_charting import generate_chart_config as generate_intent_charts
from .result_validator_v2 import validate_result as validate_result_v2
from .schema_loader import load_schema_from_mapping_file

logger = logging.getLogger("zodiac-api.intent_dashboard_fast_path")


def _user_question_from_client_message(message: str) -> str:
    """
    Dashboard sends an augmented blob (routing + 'User question:'). Intent + year checks must
    use the tail only, otherwise behaviour depends on prefixed metadata noise.
    """
    s = (message or "").strip()
    marker = "User question:"
    if "[ZODIAC_GENERATIVE_CLIENT_ROUTING" in s and marker in s:
        idx = s.rfind(marker)
        if idx >= 0:
            tail = s[idx + len(marker) :].strip()
            if tail:
                return tail
    return s


def _sql_covers_question(q: str, generated_sql: str) -> Tuple[bool, str]:
    """Same guard as ai_analysis_orchestrator intent block — incomplete SQL falls through."""
    if not generated_sql:
        return False, "empty SQL"
    sql_lower = generated_sql.lower()
    q_lower = (q or "").lower()
    years_in_q = re.findall(r"\b((?:19|20)\d{2})\b", q_lower)
    for yr in years_in_q:
        if yr not in generated_sql:
            return False, f"question mentions year {yr} but SQL has no filter for it"
    if re.search(r"\blast\s+\d+\s+(year|month|day|week)", q_lower):
        if not re.search(
            r"(fkdat|budat|erdat|bldat|belnr|gjahr)\b.{0,80}(now|current_date|interval|extract|year|month)",
            sql_lower,
            re.DOTALL,
        ):
            return False, "question implies a date range filter but SQL has none"
    if re.search(
        r"\bby\s+(customer|product|country|vendor|sales_org|plant|currency|division|month|year|quarter)\b",
        q_lower,
    ):
        if "group by" not in sql_lower:
            return False, "question asks for grouping but SQL has no GROUP BY"
    return True, "ok"


def _period_blurb(question: str, days: int, time_scope: str) -> str:
    ql = (question or "").lower()
    bits: List[str] = []
    ts = (time_scope or "").strip().lower()
    if ts and ts not in ("current", ""):
        bits.append(f"scope={time_scope}")
    years = list(dict.fromkeys(re.findall(r"\b((?:19|20)\d{2})\b", question or "")))
    if years:
        bits.append(f"calendar year(s): {', '.join(years)}")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:month|months)\b", ql)
    if m:
        bits.append(f"last {m.group(1)} month(s)")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:day|days)\b", ql)
    if m:
        bits.append(f"last {m.group(1)} day(s)")
    if days and ("recent" in ql or "dashboard" in ql):
        bits.append(f"dashboard ~{days} day window")
    if not bits:
        return ""
    return "Interpreted period: " + "; ".join(bits)


def try_intent_dashboard_fast_path(
    db: Session,
    question: str,
    *,
    days: int = 30,
    time_scope: str = "current",
    rows_preview_limit: int = 80,
) -> Optional[Dict[str, Any]]:
    """
    Execute intent pipeline and return a run_planner-shaped payload, or None to use LangGraph.
    """
    raw = (question or "").strip()
    q = _user_question_from_client_message(raw)
    if not q or not is_intent_pipeline_appropriate(q):
        return None
    from .adaptive_nl_sql_hardening import extract_named_customer, apply_ranking_discipline
    if extract_named_customer(q):
        logger.info("intent_fast_path: skip (named customer filter)")
        return None

    try:
        intent_schema = load_schema_from_mapping_file(max_columns_per_table=None)
        intent = extract_intent(q, intent_schema)
        plan = build_sql_plan(intent, intent_schema)
        sql = generate_sql(plan)
        try:
            from .sap_sql_agent import _quote_catalog_sql_tables as _qct

            sql = _qct(sql)
        except Exception:
            pass
        from .adaptive_nl_sql_hardening import (
            extract_named_customer,
            apply_ranking_discipline,
            inject_year_filters_from_question,
            inject_lpad_join_keys,
            apply_statement_timeout,
        )
        sql = inject_year_filters_from_question(sql, q)
        sql = inject_lpad_join_keys(sql)
        sql = apply_ranking_discipline(sql, q)

        ok, reason = _sql_covers_question(q, sql)
        if not ok:
            logger.info("intent_fast_path: skip (%s)", reason)
            return None

        try:
            from .sql_generation_sanitizers import prepare_sql_for_sqlalchemy_text_execution as _prep

            safe_sql = _prep(sql)
        except Exception:
            safe_sql = sql

        apply_statement_timeout(db)
        rows_raw = db.execute(text(safe_sql)).mappings().all()
        result_rows = [dict(r) for r in rows_raw]

        validation = validate_result_v2(intent, sql, result_rows)
        if not validation.get("valid"):
            logger.info("intent_fast_path: validation failed %s", validation.get("errors"))
            return None

        reply = generate_intent_summary(intent, result_rows, validation)
        charts_data = generate_intent_charts(intent, result_rows, validation)

        preview = result_rows[: max(1, min(rows_preview_limit, 500))]

        period_blurb = _period_blurb(q, days, time_scope or "current")

        payload: Dict[str, Any] = {
            "reply": reply or "Analysis complete.",
            "action": "new",
            "reason": "intent_sql_fast",
            "schema_tables": [],
            "sql": sql,
            "rows_preview": preview,
            "charts": charts_data or [],
            "time_scope": (time_scope or "current").strip(),
            "date_range": {},
            "period_info": period_blurb,
            "errors": [],
            "warnings": [],
            "confidence": "high",
            "confidence_note": "Deterministic intent SQL (no generative schema/SQL loop).",
            "sql_generation_method": "intent_sql_fast",
            "llm_calls": 0,
            "node_log": [
                {
                    "service": "intent_fast_path",
                    "kind": "deterministic",
                    "message": "Billing analytics routed to strict intent SQL — skipped LangGraph.",
                }
            ],
        }
        logger.info(
            "intent_fast_path: ok — %d row(s), sql_len=%d",
            len(result_rows),
            len(sql or ""),
        )
        return payload
    except Exception as e:
        logger.info("intent_fast_path: fall through — %s", str(e)[:200])
        return None
