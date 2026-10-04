"""
Period-compare routing for SAP billing/revenue questions.

Ensures "Compare 1998 vs 1999 revenue" is action=compare with explicit per-year
subqueries (FKDAT calendar year), not a single generic aggregate.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .sap_sql_agent import SqlAgentResult


def extract_distinct_calendar_years(question: str) -> List[str]:
    """Ordered unique 4-digit calendar years (19xx / 20xx) from the question."""
    if not question:
        return []
    found = re.findall(r"\b((?:19|20)\d{2})\b", question)
    return list(dict.fromkeys(found))


def is_billing_revenue_question(question: str) -> bool:
    q = (question or "").lower()
    return bool(
        re.search(
            r"\b(revenue|sales|billing|invoice|turnover|netwr|amount|totals?|earnings)\b",
            q,
        )
    )


def should_route_period_compare(user_query: str) -> bool:
    """
    True when the user is comparing (or juxtaposing) two+ calendar years in a revenue/billing context.
    Must run before _should_force_new_action so compare is not downgraded to generic 'new'.
    """
    years = extract_distinct_calendar_years(user_query)
    if len(years) < 2:
        return False
    q = (user_query or "").lower()
    compare_cues = bool(
        re.search(
            r"\b(compare|comparison|vs\.?|versus|between|against|difference|changed?\b|from\b.+?\bto\b|"
            r"year over year|yoy|each other|which (is|was) (higher|lower|larger|smaller))\b",
            q,
        )
    )
    if compare_cues and len(years) >= 2:
        return True
    if compare_cues and is_billing_revenue_question(user_query):
        return True
    # Two explicit years + revenue wording often means period comparison even without "compare"
    if is_billing_revenue_question(user_query):
        return True
    return False


def deterministic_year_compare_sql(years: List[str]) -> str:
    """Header-grain VBRK totals by calendar year — no LLM."""
    ys = [y for y in years if re.fullmatch(r"(?:19|20)\d{2}", str(y))][:4]
    quoted = ", ".join(f"'{y}'" for y in ys)
    return f"""
SELECT
  SUBSTRING(TRIM(k."fkdat"), 1, 4) AS calendar_year,
  k."waerk" AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
FROM "VBRK" k
WHERE TRIM(CAST(k."fkdat" AS TEXT)) <> ''
  AND SUBSTRING(TRIM(k."fkdat"), 1, 4) IN ({quoted})
GROUP BY SUBSTRING(TRIM(k."fkdat"), 1, 4), k."waerk"
ORDER BY calendar_year, total_sales DESC
""".strip()


def build_billing_revenue_subqueries_for_years(years: List[str]) -> List[str]:
    """
    Standalone sub-questions that force FKDAT calendar-year filters (validator + sanitizer aligned).
    """
    out: List[str] = []
    for y in years[:4]:
        out.append(
            f"Calculate total SAP billing revenue for calendar year {y} only: "
            f"use VBRP joined to VBRK on billing document; "
            f"SUM line net amounts; "
            f"MANDATORY WHERE SUBSTRING(TRIM(r.\"fkdat\"),1,4) = '{y}' "
            f"when VBRK table alias is r (adjust alias to match generated SQL). "
            f"Return one row with the year {y} and total revenue."
        )
    return out


def _coerce_numeric(v: Any) -> Optional[float]:
    """Coerce int/float/Decimal/numeric-string to float; else None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v)
    except Exception:
        pass
    try:
        s = str(v).strip().replace(",", "").replace(" ", "")
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def merge_year_compare_rows_for_chart(
    years: List[str],
    datasets: List[Tuple[str, List[Dict[str, Any]]]],
) -> List[Dict[str, Any]]:
    """
    Build rows [{calendar_year, total_revenue, ...}] for side-by-side bar charts.
    """
    merged: List[Dict[str, Any]] = []
    for i, y in enumerate(years):
        if i >= len(datasets):
            break
        label, rows = datasets[i]
        total: Optional[float] = None
        if rows:
            r0 = rows[0] if isinstance(rows[0], dict) else {}
            # Prefer obvious total columns
            for key in r0:
                lk = str(key).lower()
                if lk in ("total", "total_revenue", "revenue", "sum", "amount", "sales", "total_sales", "t"):
                    total = _coerce_numeric(r0.get(key))
                    if total is not None:
                        break
            if total is None:
                for _k, v in r0.items():
                    total = _coerce_numeric(v)
                    if total is not None:
                        break
        merged.append(
            {
                "calendar_year": y,
                "total_revenue": total,
                "period_label": f"Year {y}",
            }
        )
    return merged


def pick_numeric_total_from_rows(rows: List[Dict[str, Any]]) -> Optional[float]:
    if not rows or not isinstance(rows[0], dict):
        return None
    r0 = rows[0]
    priority = (
        "total_revenue",
        "revenue",
        "total",
        "sum",
        "amount",
        "total_sales",
        "sales",
    )
    lower_map = {str(k).lower(): k for k in r0}
    for p in priority:
        if p in lower_map:
            coerced = _coerce_numeric(r0.get(lower_map[p]))
            if coerced is not None:
                return coerced
    for _k, v in r0.items():
        coerced = _coerce_numeric(v)
        if coerced is not None:
            return coerced
    return None


def run_compare_subquery_with_schema_pipeline(
    sq: str,
    sql_db: Any,
    few_shot_factory: Callable[[str], List[Dict[str, str]]],
) -> SqlAgentResult | None:
    """
    Run the same primary SQL path as 'new' (schema-driven → adaptive → standard) for one sub-question.
    """
    from .sap_sql_agent import (
        run_adaptive_sap_sql_agent,
        run_schema_driven_sql_agent,
        run_sap_sql_agent,
    )

    few_shot = few_shot_factory(sq)
    _intent_ctx = None
    try:
        from .ai_intent_classifier import build_intent_sql_prompt_block

        _intent_ctx = build_intent_sql_prompt_block(sq)
    except Exception:
        pass
    result = None
    try:
        result = run_schema_driven_sql_agent(
            sq,
            sql_db,
            few_shot_examples=few_shot,
            intent_context=_intent_ctx,
        )
    except Exception:
        pass
    if result is None or not getattr(result, "rows", None):
        try:
            result = run_adaptive_sap_sql_agent(
                sq,
                sql_db,
                knowledge_context=None,
                time_scope="both",
                few_shot_examples=few_shot,
            )
        except Exception:
            pass
    if result is None or not getattr(result, "rows", None):
        result = run_sap_sql_agent(
            sq,
            sql_db,
            knowledge_context=None,
            time_scope="both",
            few_shot_examples=few_shot,
        )
    # Post-sanitize with original compare question for any FKDAT inject edge cases
    if result and getattr(result, "sql", None):
        from .sql_generation_sanitizers import sanitize_generated_sap_sql
        from .sap_sql_agent import _quote_catalog_sql_tables, _run_sql

        clean = sanitize_generated_sap_sql(result.sql, sq)
        if clean != result.sql:
            try:
                quoted = _quote_catalog_sql_tables(clean)
                rows = _run_sql(sql_db, quoted)
                result = SqlAgentResult(sql=quoted, rows=rows)
            except Exception:
                pass
    return result
