"""
Multi-dimensional analytical planner + compiler for GA Chat.

Flow:
  question (+ prior analytical context)
    → AnalyticalPlan
    → one or more governed SQL queries
    → validation
    → interpretation + guided drill-downs
    → persistent analytical_context in query_plan

Preserves classify_turn routing: this module is only invoked AFTER turn intent
is NEW_ANALYTICAL_QUERY or FOLLOWUP_DELTA.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .business_semantic_layer import (
    METRICS,
    available_drilldowns,
    data_gap_payload,
    resolve_metric,
)

logger = logging.getLogger("zodiac-api.analytical-deep-dive")

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_TOP_N_RE = re.compile(r"\b(?:top|highest|lowest|bottom)\s+(\d+)\b", re.I)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.I)


@dataclass
class AnalyticalPlan:
    intent: str
    entities: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    years: List[int] = field(default_factory=list)
    ranking: Optional[Dict[str, Any]] = None
    comparisons: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    queries: List[Dict[str, str]] = field(default_factory=list)
    selected_products: List[str] = field(default_factory=list)
    selected_customers: List[str] = field(default_factory=list)
    base_question: str = ""
    drilldowns: List[Dict[str, str]] = field(default_factory=list)

    def to_context(self) -> Dict[str, Any]:
        return {
            "deep_analysis": True,
            "intent": self.intent,
            "entities": self.entities,
            "metrics": self.metrics,
            "dimensions": self.dimensions,
            "filters": self.filters,
            "years": self.years,
            "ranking": self.ranking,
            "comparisons": self.comparisons,
            "relationships": self.relationships,
            "selected_products": self.selected_products,
            "selected_customers": self.selected_customers,
            "base_question": self.base_question,
            "available_drilldowns": self.drilldowns,
            "data_gaps": self.data_gaps,
        }


def _ql(q: str) -> str:
    return (q or "").strip().lower()


def is_deep_analysis_candidate(question: str, prior_ctx: Optional[Dict[str, Any]] = None) -> bool:
    """Heuristic gate — deep engine only for multi-dim / profit / process / COGS style asks.

    Must NOT steal ordinary sales/ranking questions (e.g. highest sales 2004 + industry)
    from intent_sql_fast / sql_catalog / universal.
    """
    if prior_ctx and prior_ctx.get("deep_analysis"):
        return True
    ql = _ql(question)
    deep_keys = (
        "profit",
        "margin",
        "cogs",
        "cost of goods",
        "cost component",
        "breakdown of component",
        "break down the cost",
        "break down component",
        "components of",
        "expir",
        "shelf life",
        "process behind",
        "selling process",
        "buying process",
        "upstream of billing",
        "order to cash",
        "procurement process",
        "gross profit",
        "lowest margin",
        "highest profit",
        "which customers buy",
        "customers buy",
        "bought by which",
        "products bought by",
        "product mix",
        "how long",
        "purchase history",
        "margin decline",
        "declining margin",
        "profitability",
        "customers with industry",
        "industry data and region",
    )
    return any(k in ql for k in deep_keys)


def _extract_years(q: str) -> List[int]:
    years = sorted({int(m.group(0)) for m in _YEAR_RE.finditer(q or "")})
    return years


def _extract_limit(q: str, default: int = 10) -> int:
    m = _TOP_N_RE.search(q or "") or _LIMIT_RE.search(q or "")
    if m:
        try:
            n = int(m.group(1))
            return max(1, min(n, 100))
        except Exception:
            pass
    return default


def _merge_prior(plan: AnalyticalPlan, prior: Optional[Dict[str, Any]]) -> AnalyticalPlan:
    if not prior:
        return plan
    if prior.get("selected_products") and not plan.selected_products:
        plan.selected_products = list(prior.get("selected_products") or [])
    if prior.get("selected_customers") and not plan.selected_customers:
        plan.selected_customers = list(prior.get("selected_customers") or [])
    if prior.get("metrics") and not plan.metrics:
        plan.metrics = list(prior.get("metrics") or [])
    if prior.get("years") and not plan.years:
        plan.years = list(prior.get("years") or [])
    if prior.get("base_question") and not plan.base_question:
        plan.base_question = str(prior.get("base_question") or "")
    # inherit product filter from prior when follow-up is dimensional
    if prior.get("filters") and isinstance(prior.get("filters"), dict):
        for k, v in prior["filters"].items():
            plan.filters.setdefault(k, v)
    return plan


def build_analytical_plan(
    question: str,
    prior_ctx: Optional[Dict[str, Any]] = None,
) -> AnalyticalPlan:
    ql = _ql(question)
    years = _extract_years(question)
    limit = _extract_limit(question, 10)
    plan = AnalyticalPlan(intent="generic", base_question=question, years=years)

    # Detect unavailable metrics early
    if any(x in ql for x in ("net profit", "ebit", "bottom line")):
        plan.data_gaps.append(
            "True net profit is unavailable — operating costs are not linked at product grain."
        )
    if "logistics cost" in ql or "freight cost" in ql:
        plan.data_gaps.append(
            "Logistics cost amounts are not reliably linked; delivery counts exist without cost."
        )

    # Intent detection (semantic, not single-keyword architecture — uses metric registry)
    wants_cogs = resolve_metric("cogs") and any(
        a in ql for a in METRICS["cogs"].aliases
    )
    wants_margin = any(a in ql for a in METRICS["gross_margin_pct"].aliases) or "lowest margin" in ql
    wants_profit = any(a in ql for a in ("profit", "gross profit", "highest profit", "lowest profit", "profitability"))
    wants_components = any(x in ql for x in ("component", "breakdown", "break down", "break-down"))
    wants_customers = "customer" in ql
    wants_industry = "industry" in ql
    wants_region = any(x in ql for x in ("region", "country"))
    wants_product = any(x in ql for x in ("product", "material"))
    wants_process_sell = any(x in ql for x in ("selling process", "process behind sell", "process involved behind sell", "order to cash", "upstream of billing", "to sell"))
    wants_process_buy = any(x in ql for x in ("buying process", "purchase process", "to buy", "procurement"))
    wants_expiry = any(x in ql for x in ("expir", "shelf life"))
    wants_compare = any(x in ql for x in ("compare", "vs", "versus", "yoy", "year over year")) or len(years) >= 2
    wants_history = any(x in ql for x in ("how long", "purchase history", "buying them"))

    # Follow-up shorthand against prior deep context
    if prior_ctx and prior_ctx.get("deep_analysis"):
        if wants_customers and not wants_profit:
            plan.intent = "customers_of_selection"
        elif wants_industry:
            plan.intent = "industry_breakdown"
        elif wants_region:
            plan.intent = "country_breakdown"
        elif wants_cogs and not wants_profit:
            plan.intent = "cogs_by_product"
        elif wants_margin and not wants_profit:
            plan.intent = "margin_by_product"
        elif wants_compare or wants_history:
            plan.intent = "period_compare_selection"
        elif wants_components:
            plan.intent = "profit_components"
        elif wants_process_sell:
            plan.intent = "process_sell"
        elif wants_process_buy:
            plan.intent = "process_buy"
        elif wants_expiry:
            plan.intent = "product_expiry"
        elif wants_profit:
            plan.intent = "product_profitability"
        else:
            # dimensional extension default
            plan.intent = "dimensional_extend"

    if plan.intent == "generic":
        if wants_process_sell and wants_process_buy:
            plan.intent = "process_sell_and_buy"
        elif wants_process_sell:
            plan.intent = "process_sell"
        elif wants_process_buy:
            plan.intent = "process_buy"
        elif wants_expiry:
            plan.intent = "product_expiry"
        elif wants_components and (wants_profit or wants_cogs or prior_ctx):
            plan.intent = "profit_components"
        elif wants_cogs and not wants_profit:
            plan.intent = "cogs_by_product"
        elif wants_margin and "lowest" in ql:
            plan.intent = "lowest_margin_products"
        elif wants_profit or wants_margin:
            plan.intent = "product_profitability"
        elif wants_customers and wants_product:
            plan.intent = "customer_product_mix"
        elif wants_industry and wants_product:
            plan.intent = "product_by_industry"
        elif wants_customers and wants_industry:
            plan.intent = "customer_industry_region"
        else:
            plan.intent = "unsupported_deep"
            return plan

    # Metrics / dimensions
    if plan.intent in {"product_profitability", "lowest_margin_products", "profit_components"}:
        plan.metrics = ["revenue", "cogs", "gross_profit", "gross_margin_pct"]
        plan.entities = ["product", "billing_item", "billing_header"]
        plan.dimensions = ["product", "currency"]
        plan.relationships = ["billing_item→billing_header", "billing_item→product"]
        direction = "asc" if "lowest" in ql or plan.intent == "lowest_margin_products" else "desc"
        metric = "gross_margin_pct" if "margin" in ql and "profit" not in ql else "gross_profit"
        if plan.intent == "lowest_margin_products":
            metric = "gross_margin_pct"
            direction = "asc"
        plan.ranking = {"metric": metric, "direction": direction, "limit": limit}
    elif plan.intent == "cogs_by_product":
        plan.metrics = ["cogs", "revenue"]
        plan.entities = ["product"]
        plan.dimensions = ["product", "currency"]
        plan.ranking = {"metric": "cogs", "direction": "desc", "limit": limit}
    elif plan.intent == "customers_of_selection":
        plan.metrics = ["revenue", "quantity"]
        plan.entities = ["customer", "product"]
        plan.dimensions = ["customer", "product", "currency"]
        plan.relationships = ["billing→customer", "billing→product"]
    elif plan.intent == "industry_breakdown":
        plan.metrics = ["revenue", "gross_profit"]
        plan.dimensions = ["industry", "currency"]
        plan.entities = ["industry", "customer", "product"]
    elif plan.intent == "country_breakdown":
        plan.metrics = ["revenue", "gross_profit"]
        plan.dimensions = ["country", "currency"]
    elif plan.intent == "customer_product_mix":
        plan.metrics = ["revenue", "quantity"]
        plan.dimensions = ["customer", "product", "currency"]
    elif plan.intent == "customer_industry_region":
        plan.metrics = ["revenue"]
        plan.dimensions = ["customer", "industry", "country"]
    elif plan.intent == "product_by_industry":
        plan.metrics = ["revenue"]
        plan.dimensions = ["industry", "product"]
    elif plan.intent == "period_compare_selection":
        plan.metrics = plan.metrics or ["revenue", "gross_profit", "gross_margin_pct"]
        plan.dimensions = ["product", "year", "currency"]
        plan.comparisons = ["yoy"]
    elif plan.intent.startswith("process_"):
        plan.entities = ["sales_order", "delivery", "billing_header", "purchase", "document_flow"]
        plan.metrics = ["invoice_count"]
        plan.dimensions = ["process_stage"]
        plan.relationships = ["VBFA document flow", "VBAK", "LIKP", "VBRK", "EKKO"]

    if wants_industry and "industry" not in plan.dimensions:
        plan.dimensions.append("industry")
    if wants_region and "country" not in plan.dimensions:
        plan.dimensions.append("country")
    if years:
        plan.filters["years"] = years
    if "year" not in plan.dimensions and years:
        plan.dimensions.append("year")

    plan = _merge_prior(plan, prior_ctx)
    plan.drilldowns = available_drilldowns(set(plan.dimensions), set(plan.metrics))
    return plan


def _year_predicate(alias: str = "vk") -> str:
    return f"EXTRACT(YEAR FROM CAST(NULLIF(TRIM({alias}.fkdat), '') AS DATE))"


def _year_filter_sql(years: Sequence[int], alias: str = "vk") -> str:
    if not years:
        return ""
    ys = ", ".join(str(y) for y in years)
    return f" AND {_year_predicate(alias)} IN ({ys})"


def _product_in_sql(products: Sequence[str]) -> str:
    clean = [p.replace("'", "''") for p in products if p]
    if not clean:
        return ""
    vals = ", ".join(f"'{p}'" for p in clean[:50])
    return f" AND TRIM(v.matnr) IN ({vals})"


def compile_queries(plan: AnalyticalPlan) -> Tuple[List[Dict[str, str]], List[str]]:
    """Compile plan → SQL list. Returns (queries, gaps)."""
    gaps = list(plan.data_gaps)
    queries: List[Dict[str, str]] = []
    years = list(plan.filters.get("years") or plan.years or [])
    yfilter = _year_filter_sql(years)
    products = plan.selected_products
    pfilter = _product_in_sql(products)
    limit = int((plan.ranking or {}).get("limit") or 10)
    direction = str((plan.ranking or {}).get("direction") or "desc").upper()
    if direction not in {"ASC", "DESC"}:
        direction = "DESC"
    rank_metric = str((plan.ranking or {}).get("metric") or "gross_profit")

    order_col = {
        "gross_profit": "gross_profit",
        "gross_margin_pct": "gross_margin_pct",
        "revenue": "revenue",
        "cogs": "cogs",
    }.get(rank_metric, "gross_profit")

    base_select = f"""
SELECT
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct,
  SUM(CAST(NULLIF(TRIM(v.fkimg), '') AS NUMERIC)) AS quantity
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) <> ''
  AND CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY TRIM(v.matnr), vk.waerk
""".strip()

    if plan.intent in {"product_profitability", "lowest_margin_products", "dimensional_extend"}:
        sql = f"""{base_select}
ORDER BY {order_col} {direction} NULLS LAST
LIMIT {limit}"""
        queries.append({"id": "product_profitability", "sql": sql})

    elif plan.intent == "profit_components":
        # Multi-query: product ranking + component totals for selection
        sql_rank = f"""{base_select}
ORDER BY gross_profit DESC NULLS LAST
LIMIT {limit}"""
        queries.append({"id": "profit_rank", "sql": sql_rank})
        sql_comp = f"""
SELECT
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY vk.waerk
ORDER BY revenue DESC NULLS LAST
LIMIT 20
""".strip()
        queries.append({"id": "profit_components", "sql": sql_comp})

    elif plan.intent == "cogs_by_product":
        sql = f"""{base_select}
ORDER BY cogs DESC NULLS LAST
LIMIT {limit}"""
        queries.append({"id": "cogs_by_product", "sql": sql})

    elif plan.intent == "margin_by_product":
        sql = f"""{base_select}
ORDER BY gross_margin_pct ASC NULLS LAST
LIMIT {limit}"""
        queries.append({"id": "margin_by_product", "sql": sql})

    elif plan.intent == "customers_of_selection":
        sql = f"""
SELECT
  TRIM(vk.kunag) AS customer,
  MAX(k.name1) AS customer_name,
  MAX(k.brsch) AS industry,
  MAX(k.land1) AS country,
  vk.waerk AS currency,
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(v.fkimg), '') AS NUMERIC)) AS quantity,
  MIN(vk.fkdat) AS first_billing_date,
  MAX(vk.fkdat) AS last_billing_date
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN KNA1 k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY TRIM(vk.kunag), vk.waerk, TRIM(v.matnr)
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 30)}
""".strip()
        queries.append({"id": "customers_of_products", "sql": sql})

    elif plan.intent == "industry_breakdown":
        sql = f"""
SELECT
  COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown') AS industry,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS gross_profit,
  COUNT(DISTINCT vk.kunag) AS customer_count
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN KNA1 k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN T016T t ON TRIM(k.brsch) = TRIM(t.brsch)
WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown'), vk.waerk
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 20)}
""".strip()
        queries.append({"id": "industry_breakdown", "sql": sql})

    elif plan.intent == "country_breakdown":
        sql = f"""
SELECT
  COALESCE(NULLIF(TRIM(vk.land1), ''), 'Unknown') AS country,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS gross_profit
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY COALESCE(NULLIF(TRIM(vk.land1), ''), 'Unknown'), vk.waerk
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 20)}
""".strip()
        queries.append({"id": "country_breakdown", "sql": sql})

    elif plan.intent in {"customer_product_mix", "customer_industry_region"}:
        sql = f"""
SELECT
  TRIM(vk.kunag) AS customer,
  MAX(k.name1) AS customer_name,
  MAX(k.brsch) AS industry_key,
  MAX(t.brtxt) AS industry,
  MAX(k.land1) AS country,
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(v.fkimg), '') AS NUMERIC)) AS quantity,
  MIN(vk.fkdat) AS first_billing_date,
  MAX(vk.fkdat) AS last_billing_date
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN KNA1 k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN T016T t ON TRIM(k.brsch) = TRIM(t.brsch)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
GROUP BY TRIM(vk.kunag), TRIM(v.matnr), vk.waerk
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 50)}
""".strip()
        queries.append({"id": "customer_product_industry_region", "sql": sql})

    elif plan.intent == "product_by_industry":
        sql = f"""
SELECT
  COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown') AS industry,
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN KNA1 k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN T016T t ON TRIM(k.brsch) = TRIM(t.brsch)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter}
GROUP BY COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown'),
         TRIM(v.matnr), vk.waerk
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 50)}
""".strip()
        queries.append({"id": "product_by_industry", "sql": sql})

    elif plan.intent == "period_compare_selection":
        ylist = years if len(years) >= 2 else sorted(set(years + [2024, 2025]))[:2]
        yfilter2 = _year_filter_sql(ylist)
        sql = f"""
SELECT
  {_year_predicate('vk')} AS year,
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) <> ''
  AND CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL
  {yfilter2}
  {pfilter}
GROUP BY {_year_predicate('vk')}, TRIM(v.matnr), vk.waerk
ORDER BY year, gross_profit DESC NULLS LAST
LIMIT 200
""".strip()
        queries.append({"id": "period_compare", "sql": sql})

    elif plan.intent in {"process_sell", "process_sell_and_buy", "process_buy"}:
        if plan.intent in {"process_sell", "process_sell_and_buy"}:
            queries.append({
                "id": "process_sell_stages",
                "sql": """
SELECT stage, doc_count FROM (
  SELECT '1_sales_orders' AS stage, COUNT(*) AS doc_count FROM VBAK
  UNION ALL
  SELECT '2_deliveries', COUNT(*) FROM LIKP
  UNION ALL
  SELECT '3_billing_documents', COUNT(*) FROM VBRK
) s
ORDER BY stage
""".strip(),
            })
            queries.append({
                "id": "process_sell_flow_sample",
                "sql": """
SELECT
  f.vbtyp_v AS preceding_type,
  f.vbtyp_n AS subsequent_type,
  COUNT(*) AS link_count
FROM VBFA f
GROUP BY f.vbtyp_v, f.vbtyp_n
ORDER BY link_count DESC NULLS LAST
LIMIT 30
""".strip(),
            })
        if plan.intent in {"process_buy", "process_sell_and_buy"}:
            queries.append({
                "id": "process_buy_stages",
                "sql": """
SELECT stage, doc_count FROM (
  SELECT '1_purchase_orders' AS stage, COUNT(*) AS doc_count FROM EKKO
  UNION ALL
  SELECT '2_po_items', COUNT(*) FROM EKPO
  UNION ALL
  SELECT '3_vendors', COUNT(*) FROM LFA1
) s
ORDER BY stage
""".strip(),
            })

    elif plan.intent == "product_expiry":
        gaps.append(
            "Product expiry BI is partial: MARA shelf-life and LIPS.VFDAT exist, "
            "but batch expiry completeness varies."
        )
        queries.append({
            "id": "product_shelf_life",
            "sql": """
SELECT
  TRIM(a.matnr) AS product,
  COALESCE(m.maktx, a.matnr) AS product_name,
  a.mhdhb AS total_shelf_life_days,
  a.mhdrz AS remaining_shelf_life_days,
  a.sled_bbd AS sled_bbd_indicator
FROM MARA a
LEFT JOIN MAKT m ON TRIM(a.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE a.mhdhb IS NOT NULL OR a.mhdrz IS NOT NULL OR a.sled_bbd IS NOT NULL
ORDER BY CAST(NULLIF(TRIM(COALESCE(a.mhdrz, a.mhdhb, '0')), '') AS NUMERIC) ASC NULLS LAST
LIMIT 50
""".strip(),
        })

    else:
        gaps.append(f"No governed SQL compiler path for intent={plan.intent}")

    # Explicit unavailable metrics
    for mname in plan.metrics:
        m = METRICS.get(mname)
        if m and m.status == "unavailable":
            gaps.append(m.caveats or f"{mname} unavailable")

    return queries, gaps


def _fmt_num(v: Any) -> str:
    try:
        n = float(v)
        if abs(n) >= 1000:
            return f"{n:,.2f}"
        return f"{n:.2f}"
    except Exception:
        return str(v)


def _interpret(plan: AnalyticalPlan, bundled: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    findings: List[str] = []
    lines: List[str] = []
    lines.append(f"**Deep analysis** — intent `{plan.intent}`")
    lines.append("")
    lines.append(
        "Metrics use governed definitions: "
        "**Revenue** = billing NETWR; **COGS** = billing WAVWR (document cost); "
        "**Gross profit** = Revenue − COGS; **Gross margin %** = Gross profit / Revenue. "
        "This is **not** true net profit."
    )
    lines.append("")

    for block in bundled:
        qid = block.get("id")
        rows = block.get("rows") or []
        if not rows:
            lines.append(f"- `{qid}`: no rows returned.")
            continue
        lines.append(f"### {qid} ({len(rows)} rows)")
        top = rows[0]
        if "gross_profit" in top or "revenue" in top:
            pname = top.get("product_name") or top.get("product") or top.get("industry") or top.get("country") or top.get("customer_name")
            lines.append(
                f"- Top row: **{pname}** | revenue={_fmt_num(top.get('revenue'))} "
                f"| cogs={_fmt_num(top.get('cogs'))} | gross_profit={_fmt_num(top.get('gross_profit'))} "
                f"| margin%={_fmt_num(top.get('gross_margin_pct'))} | currency={top.get('currency')}"
            )
            findings.append(
                f"{pname}: gross profit {_fmt_num(top.get('gross_profit'))} {top.get('currency') or ''}".strip()
            )
        elif "stage" in top:
            for r in rows[:8]:
                lines.append(f"- {r.get('stage')}: {r.get('doc_count')}")
                findings.append(f"{r.get('stage')}={r.get('doc_count')}")
        elif "preceding_type" in top:
            lines.append("- Document-flow type pairs (VBFA) sample:")
            for r in rows[:5]:
                lines.append(
                    f"  - {r.get('preceding_type')} → {r.get('subsequent_type')}: {r.get('link_count')}"
                )
        elif "first_billing_date" in top:
            lines.append(
                f"- Example: {top.get('customer_name')} bought {top.get('product_name')} "
                f"from {top.get('first_billing_date')} to {top.get('last_billing_date')} "
                f"(revenue {_fmt_num(top.get('revenue'))} {top.get('currency')})"
            )
            findings.append("Customer–product period coverage computed from billing dates.")
        else:
            lines.append(f"- Sample keys: {', '.join(list(top.keys())[:8])}")

    if plan.data_gaps:
        lines.append("")
        lines.append("### Data limitations")
        for g in plan.data_gaps:
            lines.append(f"- {g}")

    if plan.drilldowns:
        lines.append("")
        lines.append("### Available deeper analysis")
        for i, d in enumerate(plan.drilldowns, 1):
            lines.append(f"{i}. {d.get('label')}")
        lines.append("")
        lines.append("Ask a follow-up, for example: *Show their customers* / *Break down by industry* / *Show COGS* / *Compare 2024 and 2025*.")

    return "\n".join(lines), findings


def try_deep_multidim_analysis(
    question: str,
    db: Any,
    execute_sql,
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_rows: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Attempt governed multi-dimensional analysis.
    Returns payload dict or None to fall through to existing engines.
    """
    t0 = time.perf_counter()
    prior_ctx = None
    if isinstance(prior_plan, dict):
        prior_ctx = prior_plan.get("analytical_context") or (
            prior_plan if prior_plan.get("deep_analysis") else None
        )

    if not is_deep_analysis_candidate(question, prior_ctx):
        return None

    plan = build_analytical_plan(question, prior_ctx)
    if plan.intent == "unsupported_deep" and not prior_ctx:
        return None

    # Seed selected products from prior result rows if follow-up needs them
    if prior_rows and not plan.selected_products:
        prods = []
        for r in prior_rows[:20]:
            if not isinstance(r, dict):
                continue
            p = r.get("product") or r.get("matnr") or r.get("material_number")
            if p:
                prods.append(str(p).strip())
        plan.selected_products = list(dict.fromkeys(prods))

    # Hard data-gap for unavailable metrics when that is the only ask
    ql = _ql(question)
    if "net profit" in ql or "ebit" in ql:
        return data_gap_payload(
            question,
            METRICS["net_profit"].caveats,
            can_answer=[
                "Product gross profit (NETWR − WAVWR)",
                "Gross margin %",
                "Revenue and invoice COGS by product/customer/industry/country/year",
            ],
        )
    if "logistics cost" in ql or "freight cost" in ql:
        return data_gap_payload(
            question,
            METRICS["logistics_cost"].caveats,
            can_answer=["Delivery document counts (LIKP)", "Order→delivery→billing document flow (VBFA)"],
        )

    queries, gaps = compile_queries(plan)
    plan.data_gaps = list(dict.fromkeys((plan.data_gaps or []) + gaps))
    if not queries:
        if plan.data_gaps:
            return data_gap_payload(question, "; ".join(plan.data_gaps), can_answer=[
                "Billing revenue by product/customer/industry/country",
                "Gross profit proxy via WAVWR where populated",
            ])
        return None

    bundled: List[Dict[str, Any]] = []
    primary_rows: List[Dict[str, Any]] = []
    primary_sql = ""
    for q in queries[:6]:
        sql = q["sql"]
        try:
            rows = execute_sql(db, sql, question) or []
        except Exception as exc:
            logger.info("[deep] query %s failed: %s", q.get("id"), exc)
            plan.data_gaps.append(f"Query {q.get('id')} failed: {exc}")
            continue
        bundled.append({"id": q["id"], "sql": sql, "rows": rows})
        if not primary_rows and rows:
            primary_rows = rows
            primary_sql = sql

    if not bundled or (not primary_rows and plan.intent not in {"process_sell", "process_buy", "process_sell_and_buy"}):
        # fall through if we produced nothing useful
        if plan.data_gaps and not primary_rows:
            return data_gap_payload(question, "; ".join(plan.data_gaps[:3]), can_answer=[
                "Product revenue from billing",
                "Customer / industry / country sales cuts",
            ])
        return None

    # Update selection from primary product rows
    if primary_rows and (primary_rows[0].get("product") or primary_rows[0].get("matnr")):
        plan.selected_products = [
            str(r.get("product") or r.get("matnr")).strip()
            for r in primary_rows[:20]
            if r.get("product") or r.get("matnr")
        ]
    if primary_rows and primary_rows[0].get("customer"):
        plan.selected_customers = [
            str(r.get("customer")).strip()
            for r in primary_rows[:20]
            if r.get("customer")
        ]

    plan.drilldowns = available_drilldowns(set(plan.dimensions), set(plan.metrics))
    summary, findings = _interpret(plan, bundled)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    ctx = plan.to_context()
    query_plan = {
        "analytical_context": ctx,
        "deep_analysis": True,
        "intent": plan.intent,
        "metrics": plan.metrics,
        "dimensions": plan.dimensions,
        "delta_ops": [],
    }

    # Simple chart from primary rows when numeric
    charts: List[Dict[str, Any]] = []
    if primary_rows and ("gross_profit" in primary_rows[0] or "revenue" in primary_rows[0]):
        label_key = "product_name" if "product_name" in primary_rows[0] else (
            "customer_name" if "customer_name" in primary_rows[0] else (
                "industry" if "industry" in primary_rows[0] else (
                    "country" if "country" in primary_rows[0] else "product"
                )
            )
        )
        value_key = "gross_profit" if "gross_profit" in primary_rows[0] else "revenue"
        charts.append({
            "type": "bar",
            "title": question[:120],
            "description": "Governed deep-analysis metric chart",
            "data": [
                {"name": str(r.get(label_key) or ""), "value": float(r.get(value_key) or 0)}
                for r in primary_rows[:15]
            ],
        })

    return {
        "sql": primary_sql,
        "rowCount": len(primary_rows),
        "data": primary_rows,
        "summary": summary,
        "keyFindings": findings[:12],
        "charts": charts,
        "answer_status": "SUCCESS",
        "query_plan": query_plan,
        "suggested_followups": [d.get("label") for d in plan.drilldowns],
        "meta": {
            "deep_analysis": True,
            "analytical_plan": ctx,
            "query_count": len(bundled),
            "planning_ms": elapsed_ms,
            "data_gaps": plan.data_gaps,
            "bundled_queries": [{"id": b["id"], "rows": len(b["rows"])} for b in bundled],
        },
        "pipeline": "deep_multidim",
        "sql_generation_method": "deep_multidim",
        "llm_calls": 0,
        "stage_timings": {"deep_analysis_ms": elapsed_ms},
    }
