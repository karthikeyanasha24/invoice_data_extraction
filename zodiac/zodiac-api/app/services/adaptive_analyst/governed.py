"""Optional governed execution under the orchestrator (preserves R3/R4 SQL)."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("zodiac-api.adaptive_analyst.governed")

ExecuteSql = Callable[..., List[Dict[str, Any]]]


def try_governed_database(
    question: str,
    db: Any,
    execute_sql: ExecuteSql,
    *,
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_rows: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Return an existing compiler payload or None to continue LLM SQL."""
    try:
        from ..analytical_deep_dive import try_deep_multidim_analysis

        deep = try_deep_multidim_analysis(
            question, db, execute_sql, prior_plan=prior_plan, prior_rows=prior_rows
        )
        if deep:
            deep.setdefault("sql_generation_method", "deep_multidim")
            deep["pipeline"] = deep.get("pipeline") or "deep_multidim"
            return deep
    except Exception as exc:
        logger.info("[governed] deep_multidim skipped: %s", exc)

    try:
        from ...data_catalog.source_selector import select_source
        from ..domain_overview_analysis import knowledge_payload, try_domain_overview
        from ..sales_order_analysis import try_sales_order_analysis

        spec = select_source(question, prior_plan=prior_plan)
        if spec.route == "knowledge" or spec.reason == "table_absent":
            return knowledge_payload(question, spec)
        if spec.needs_clarification:
            return {
                "answer_status": "CLARIFICATION",
                "type": "clarification",
                "mode": "clarification",
                "sql": "",
                "data": [],
                "rowCount": 0,
                "summary": spec.clarification_message or "Please clarify sales orders vs billed invoices.",
                "answer": spec.clarification_message,
                "pipeline": "governed_clarification",
            }
        if spec.route == "sales_order":
            so = try_sales_order_analysis(question, spec, db, execute_sql)
            if so:
                return so
        if spec.route == "domain_overview":
            ov = try_domain_overview(question, spec, db, execute_sql)
            if ov:
                return ov
    except Exception as exc:
        logger.info("[governed] catalog path skipped: %s", exc)
    return None
