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
from .analytical_followup_resolver import resolve_analytical_followup

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


def _is_basic_engine_query(ql: str) -> bool:
    """True when existing intent_sql/catalog/universal should keep the question.

    Protects GA golden paths like highest sales + customer + industry.
    """
    if any(
        x in ql
        for x in (
            "profit",
            "margin",
            "cogs",
            "cost of goods",
            "wavwr",
            "making us",
            "most money",
            "money and why",
            "expir",
            "shelf life",
            "process behind",
            "selling process",
            "buying process",
            "process involved",
            "logistics cost",
            "freight",
            "net profit",
            "component",
            "breakdown",
            "break down",
            "slow-moving",
            "fast-moving",
            "inventory age",
            "how long",
            "purchase history",
            "type of products bought",
            "products bought by",
            "customers buy",
            "customers buying",
        )
    ):
        return False
    # Classic sales / ranking / invoice count without cost/profit semantics
    basic_patterns = (
        r"\bhighest sales\b",
        r"\btotal sales\b",
        r"\bsales for\b",
        r"\binvoice count\b",
        r"\btop\s+\d+\s+customers\b",
        r"\bfive biggest customers\b",
        r"\bshow top\s+\d+\s+customers\b",
        r"\bsales by industry\b",
        r"\bsales by country\b",
        r"\bcompare\s+20\d{2}\s+(vs|versus|and|with)\s+20\d{2}\b",
    )
    if any(re.search(p, ql) for p in basic_patterns):
        return True
    # "Top 5" alone is a follow-up delta, not deep — unless prior deep context
    if re.fullmatch(r"(now\s+)?(show\s+)?(the\s+)?top\s+\d+\b.*", ql):
        return True
    if re.fullmatch(r"(only|just|filter).{0,40}industry\b.*", ql):
        return True
    return False


def is_deep_analysis_candidate(question: str, prior_ctx: Optional[Dict[str, Any]] = None) -> bool:
    """Semantic gate for multi-dimensional analysis.

    Uses meaning signals (profit/COGS/process/expiry/history) rather than exact
    canned phrases. Prior deep analytical_context always qualifies follow-ups.
    Must NOT steal basic sales/ranking questions from existing engines.
    """
    if prior_ctx and prior_ctx.get("deep_analysis"):
        return True
    ql = _ql(question)
    if not ql:
        return False
    if _is_basic_engine_query(ql):
        return False

    # Metric / profitability semantics (including paraphrases)
    profit_signals = (
        "profit",
        "profitable",
        "profitability",
        "margin",
        "cogs",
        "cost of goods",
        "making us the most money",
        "making the most money",
        "most money",
        "making money",
        "money and why",
        "actually making",
    )
    structure_signals = (
        "component",
        "breakdown",
        "break down",
        "break-down",
        "why did",
        "why is the margin",
        "why are margins",
        "decline",
        "erosion",
    )
    dim_chain_signals = (
        "customers buying",
        "customers buy",
        "bought by which",
        "type of products",
        "products bought",
        "industry data",
        "with industry",
        "and regions",
        "and region",
        "how long",
        "purchase history",
        "buying them",
        "buying those",
    )
    process_signals = (
        "process",
        "upstream",
        "order to cash",
        "procure",
        "selling",
        "buying",
        "delivery",
        "logistics",
    )
    lifecycle_signals = (
        "expir",
        "shelf life",
        "slow-moving",
        "fast-moving",
        "inventory age",
        "stock value",
    )

    score = 0
    if any(s in ql for s in profit_signals):
        score += 3
    if any(s in ql for s in structure_signals) and (
        any(s in ql for s in profit_signals) or "cost" in ql
    ):
        score += 2
    if any(s in ql for s in dim_chain_signals):
        score += 2
    if any(s in ql for s in process_signals) and (
        "process" in ql or "upstream" in ql or "logistics" in ql
    ):
        score += 2
    if any(s in ql for s in lifecycle_signals):
        score += 2
    # Multi-dimension ask without saying "profit"
    if ("product" in ql and "customer" in ql) or (
        "customer" in ql and "industry" in ql and "region" in ql
    ):
        score += 2
    return score >= 2


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

    # Deterministic follow-up resolver (general — not phrase patches)
    if prior_ctx and prior_ctx.get("deep_analysis"):
        follow = resolve_analytical_followup(question, prior_ctx)
        if follow.resolved and follow.intent:
            plan.intent = follow.intent
            if follow.metrics:
                plan.metrics = list(follow.metrics)
            if follow.years:
                plan.years = follow.years
                plan.filters["years"] = follow.years
            if follow.comparisons:
                plan.comparisons = list(follow.comparisons)
            for d in follow.add_dimensions:
                if d not in plan.dimensions:
                    plan.dimensions.append(d)
            for d in follow.remove_dimensions:
                plan.dimensions = [x for x in plan.dimensions if x != d]
            if follow.replace_dimensions:
                plan.dimensions = list(follow.replace_dimensions)
            if follow.data_gap_metric:
                plan.data_gaps.append(METRICS[follow.data_gap_metric].caveats)
            plan = _merge_prior(plan, prior_ctx)
            # Apply intent-specific metrics/dimensions below via shared block
            if plan.intent not in {"generic", "unsupported_deep"}:
                pass  # fall through to metrics/dimensions assignment
            else:
                return plan

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
    wants_profit = any(
        a in ql
        for a in (
            "profit",
            "gross profit",
            "highest profit",
            "lowest profit",
            "profitability",
            "profitable",
            "most money",
            "making money",
            "making us",
        )
    )
    wants_components = any(x in ql for x in ("component", "breakdown", "break down", "break-down"))
    wants_customers = "customer" in ql
    wants_industry = "industry" in ql
    wants_region = any(x in ql for x in ("region", "country"))
    wants_product = any(x in ql for x in ("product", "material"))
    wants_process_sell = any(
        x in ql
        for x in (
            "selling process",
            "process behind sell",
            "process involved behind sell",
            "process involved behind selling",
            "behind selling",
            "order to cash",
            "upstream of billing",
            "to sell",
        )
    )
    wants_process_buy = any(
        x in ql
        for x in (
            "buying process",
            "purchase process",
            "process involved in buy",
            "process involved behind buy",
            "involved in buying",
            "behind buying",
            "to buy",
            "procurement",
        )
    )
    wants_expiry = any(x in ql for x in ("expir", "shelf life"))
    wants_compare = any(x in ql for x in ("compare", "vs", "versus", "yoy", "year over year")) or len(years) >= 2
    wants_history = any(
        x in ql for x in ("how long", "purchase history", "been buying", "buying them")
    )
    wants_logistics = "logistics" in ql or "freight" in ql
    wants_margin_decline = any(
        x in ql
        for x in (
            "margin decline",
            "declining margin",
            "biggest margin decline",
            "margin erosion",
            "why did the margin",
            "why did margin",
            "why is the margin",
            "why are margins",
            "yoy margin",
        )
    )
    wants_monthly = "monthly" in ql or "by month" in ql or "month trend" in ql
    wants_inventory = any(
        x in ql for x in ("inventory", "stock value", "slow-moving", "fast-moving", "inventory age")
    )
    wants_why = ql.startswith("why ") or " why " in ql or ql.startswith("explain why")

    # Follow-up shorthand against prior deep context (legacy keyword path — resolver runs first)
    if prior_ctx and prior_ctx.get("deep_analysis") and plan.intent == "generic":
        if wants_logistics and "cost" in ql:
            plan.intent = "logistics_cost_gap"
        elif wants_expiry and wants_industry:
            plan.intent = "product_expiry_by_industry"
        elif wants_expiry:
            plan.intent = "product_expiry"
        elif wants_margin_decline or (wants_why and wants_margin):
            plan.intent = "margin_decline_drivers"
        elif wants_compare:
            plan.intent = "period_compare_selection"
        elif wants_history:
            plan.intent = "purchase_history"
        elif wants_process_sell and wants_process_buy:
            plan.intent = "process_sell_and_buy"
        elif wants_process_sell:
            plan.intent = "process_sell"
        elif wants_process_buy:
            plan.intent = "process_buy"
        elif wants_logistics:
            plan.intent = "process_sell"
        elif wants_monthly:
            plan.intent = "monthly_trend"
        elif wants_inventory:
            plan.intent = "inventory_analysis"
        elif wants_cogs and not wants_profit:
            plan.intent = "cogs_by_product"
        elif wants_margin and any(x in ql for x in ("lowest", "worst", "poor", "least")):
            plan.intent = "lowest_margin_products"
        elif wants_margin and not wants_profit:
            plan.intent = "margin_by_product"
        elif wants_customers and wants_industry and wants_region:
            plan.intent = "customer_industry_region"
        elif wants_customers and not wants_profit:
            plan.intent = "customers_of_selection"
        elif wants_industry and wants_region:
            plan.intent = "product_industry_region"
        elif wants_industry:
            plan.intent = "industry_breakdown"
        elif wants_region:
            plan.intent = "country_breakdown"
        elif wants_components:
            plan.intent = "profit_components"
        elif wants_profit:
            plan.intent = "product_profitability"
        else:
            plan.intent = "dimensional_extend"

    if plan.intent == "generic":
        if wants_logistics and "cost" in ql:
            plan.intent = "logistics_cost_gap"
        elif wants_margin_decline or (wants_why and wants_margin):
            plan.intent = "margin_decline_drivers"
        elif wants_history and (wants_customers or wants_product or prior_ctx):
            plan.intent = "purchase_history"
        elif wants_monthly:
            plan.intent = "monthly_trend"
        elif wants_inventory:
            plan.intent = "inventory_analysis"
        elif wants_process_sell and wants_process_buy:
            plan.intent = "process_sell_and_buy"
        elif wants_process_sell:
            plan.intent = "process_sell"
        elif wants_process_buy:
            plan.intent = "process_buy"
        elif wants_expiry and wants_industry:
            plan.intent = "product_expiry_by_industry"
        elif wants_expiry:
            plan.intent = "product_expiry"
        elif wants_components and (wants_profit or wants_cogs or prior_ctx):
            plan.intent = "profit_components"
        elif wants_cogs and not wants_profit:
            plan.intent = "cogs_by_product"
        elif wants_margin and "lowest" in ql:
            plan.intent = "lowest_margin_products"
        elif wants_profit and wants_industry and wants_region:
            plan.intent = "product_industry_region"
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
    if plan.intent in {
        "product_profitability",
        "lowest_margin_products",
        "profit_components",
        "margin_decline_drivers",
        "product_industry_region",
    }:
        plan.metrics = ["revenue", "cogs", "gross_profit", "gross_margin_pct"]
        plan.entities = ["product", "billing_item", "billing_header"]
        plan.dimensions = ["product", "currency"]
        plan.relationships = ["billing_item→billing_header", "billing_item→product"]
        direction = "asc" if "lowest" in ql or plan.intent == "lowest_margin_products" else "desc"
        metric = "gross_margin_pct" if "margin" in ql and "profit" not in ql else "gross_profit"
        if plan.intent == "lowest_margin_products":
            metric = "gross_margin_pct"
            direction = "asc"
            plan.filters["min_revenue"] = 1000
        if plan.intent == "margin_decline_drivers":
            plan.comparisons = ["yoy_margin"]
            plan.dimensions.extend(["year", "customer", "industry"])
        if plan.intent == "product_industry_region":
            plan.dimensions.extend(["industry", "country"])
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
    elif plan.intent == "purchase_history":
        plan.metrics = ["revenue", "quantity", "invoice_count"]
        plan.entities = ["customer", "product"]
        plan.dimensions = ["customer", "product", "time"]
        plan.relationships = ["billing→customer", "billing→product"]
    elif plan.intent == "logistics_cost_gap":
        plan.metrics = ["logistics_cost"]
        plan.data_gaps.append(METRICS["logistics_cost"].caveats)
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
    elif plan.intent == "monthly_trend":
        plan.metrics = ["revenue", "gross_profit", "gross_margin_pct"]
        plan.dimensions = ["month", "currency"]
        plan.comparisons = ["mom"]
    elif plan.intent == "inventory_analysis":
        plan.metrics = ["quantity"]
        plan.entities = ["inventory", "product"]
        plan.dimensions = ["product", "plant"]
        plan.data_gaps.append(
            "Inventory uses MBEW/MARD stock value/qty — not equated to COGS or logistics cost."
        )
    elif plan.intent in {"product_expiry", "product_expiry_by_industry"}:
        plan.metrics = ["product_expiry"]
        plan.dimensions = ["product"]
        if plan.intent == "product_expiry_by_industry":
            plan.dimensions.append("industry")
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
    # Match intent_sql_fast: fkdat is TEXT in this DB — never EXTRACT(YEAR FROM date).
    return f'SUBSTRING(TRIM(CAST({alias}."fkdat" AS TEXT)), 1, 4)'


def _year_filter_sql(years: Sequence[int], alias: str = "vk") -> str:
    if not years:
        return ""
    ys = ", ".join(f"'{int(y)}'" for y in years)
    return (
        f' AND {alias}."fkdat" IS NOT NULL'
        f" AND TRIM(CAST({alias}.\"fkdat\" AS TEXT)) <> ''"
        f" AND {_year_predicate(alias)} IN ({ys})"
    )


def _product_in_sql(products: Sequence[str]) -> str:
    clean = [p.replace("'", "''") for p in products if p]
    if not clean:
        return ""
    vals = ", ".join(f"'{p}'" for p in clean[:50])
    return f' AND TRIM(CAST(v."matnr" AS TEXT)) IN ({vals})'


def _num(expr: str) -> str:
    """Governed TEXT→NUMERIC cast used across adaptive SAP SQL."""
    return f"CAST(NULLIF(TRIM(CAST({expr} AS TEXT)), '') AS NUMERIC)"


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

    rev = _num('v."netwr"')
    cogs = _num('COALESCE(v."wavwr", \'0\')')
    qty = _num('v."fkimg"')

    # Quoted SAP identifiers: "VBRK"/"MAKT"/… uppercase; vbrp stays lowercase.
    base_select = f"""
SELECT
  TRIM(CAST(v."matnr" AS TEXT)) AS product,
  COALESCE(MAX(m."maktx"), TRIM(CAST(v."matnr" AS TEXT))) AS product_name,
  vk."waerk" AS currency,
  SUM({rev}) AS revenue,
  SUM({cogs}) AS cogs,
  SUM({rev}) - SUM({cogs}) AS gross_profit,
  CASE WHEN SUM({rev}) > 0 THEN
    ROUND(100.0 * (SUM({rev}) - SUM({cogs})) / SUM({rev}), 2)
  ELSE NULL END AS gross_margin_pct,
  SUM({qty}) AS quantity
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
LEFT JOIN "MAKT" m ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
  AND (m."spras" = 'E' OR m."spras" IS NULL)
WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
  AND {rev} IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY TRIM(CAST(v."matnr" AS TEXT)), vk."waerk"
""".strip()

    if plan.intent in {"product_profitability", "lowest_margin_products", "dimensional_extend"}:
        having = ""
        min_rev = plan.filters.get("min_revenue")
        if plan.intent == "lowest_margin_products" or min_rev:
            try:
                min_rev_n = float(min_rev if min_rev is not None else 1000)
            except (TypeError, ValueError):
                min_rev_n = 1000.0
            # Avoid tiny-denominator margin rankings; require meaningful revenue.
            having = (
                f"\nHAVING SUM({rev}) >= {min_rev_n}"
            )
        sql = f"""{base_select}{having}
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
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
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
        min_rev = plan.filters.get("min_revenue") or 1000
        try:
            min_rev_n = float(min_rev)
        except (TypeError, ValueError):
            min_rev_n = 1000.0
        sql = f"""{base_select}
HAVING SUM({rev}) >= {min_rev_n}
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
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(v."fkimg" AS TEXT)), '') AS NUMERIC)) AS quantity,
  MIN(vk.fkdat) AS first_billing_date,
  MAX(vk.fkdat) AS last_billing_date
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "KNA1" k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY TRIM(vk.kunag), vk.waerk, TRIM(v.matnr)
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 30)}
""".strip()
        queries.append({"id": "customers_of_products", "sql": sql})

    elif plan.intent == "purchase_history":
        # How long have they been buying: first/last date, duration, purchase count.
        sql = f"""
SELECT
  TRIM(vk.kunag) AS customer,
  MAX(k.name1) AS customer_name,
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  vk.waerk AS currency,
  MIN(vk."fkdat") AS first_purchase_date,
  MAX(vk."fkdat") AS last_purchase_date,
  (
    CAST(NULLIF(TRIM(CAST(MAX(vk."fkdat") AS TEXT)), '') AS DATE)
    - CAST(NULLIF(TRIM(CAST(MIN(vk."fkdat") AS TEXT)), '') AS DATE)
  ) AS purchase_duration_days,
  COUNT(DISTINCT TRIM(CAST(vk."vbeln" AS TEXT))) AS purchase_count,
  SUM(CAST(NULLIF(TRIM(CAST(v."fkimg" AS TEXT)), '') AS NUMERIC)) AS quantity,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "KNA1" k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  AND vk.fkdat IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY TRIM(vk.kunag), TRIM(v.matnr), vk.waerk
ORDER BY purchase_duration_days DESC NULLS LAST, revenue DESC NULLS LAST
LIMIT {max(limit, 40)}
""".strip()
        queries.append({"id": "purchase_history", "sql": sql})
        gaps.append(
            "Purchase duration is derived from billing dates (VBRK.FKDAT), not order creation. "
            "Coverage is limited to loaded billing history."
        )

    elif plan.intent == "logistics_cost_gap":
        gaps.append(METRICS["logistics_cost"].caveats)
        # No monetary logistics SQL — intentional empty compile for CANNOT_ANSWER path.

    elif plan.intent == "industry_breakdown":
        sql = f"""
SELECT
  COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown') AS industry,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS gross_profit,
  COUNT(DISTINCT vk.kunag) AS customer_count
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "KNA1" k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN "T016T" t ON TRIM(k.brsch) = TRIM(t.brsch)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
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
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS gross_profit
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
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
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(v."fkimg" AS TEXT)), '') AS NUMERIC)) AS quantity,
  MIN(vk.fkdat) AS first_billing_date,
  MAX(vk.fkdat) AS last_billing_date
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "KNA1" k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN "T016T" t ON TRIM(k.brsch) = TRIM(t.brsch)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
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
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "KNA1" k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN "T016T" t ON TRIM(k.brsch) = TRIM(t.brsch)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  {yfilter}
GROUP BY COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown'),
         TRIM(v.matnr), vk.waerk
ORDER BY revenue DESC NULLS LAST
LIMIT {max(limit, 50)}
""".strip()
        queries.append({"id": "product_by_industry", "sql": sql})

    elif plan.intent == "period_compare_selection":
        ylist = years if len(years) >= 2 else sorted(set(years + [2004, 2005]))[:2]
        yfilter2 = _year_filter_sql(ylist)
        sql = f"""
SELECT
  {_year_predicate('vk')} AS year,
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) <> ''
  AND CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  {yfilter2}
  {pfilter}
GROUP BY {_year_predicate('vk')}, TRIM(v.matnr), vk.waerk
ORDER BY year, gross_profit DESC NULLS LAST
LIMIT 200
""".strip()
        queries.append({"id": "period_compare", "sql": sql})

    elif plan.intent == "margin_decline_drivers":
        ylist = years if len(years) >= 2 else [2004, 2005]
        y1, y2 = int(ylist[0]), int(ylist[1])
        sql_decline = f"""
WITH yearly AS (
  SELECT
    {_year_predicate('vk')} AS year,
    TRIM(CAST(v."matnr" AS TEXT)) AS product,
    COALESCE(MAX(m."maktx"), TRIM(CAST(v."matnr" AS TEXT))) AS product_name,
    vk."waerk" AS currency,
    SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
    SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
    CASE WHEN SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) > 0 THEN
      ROUND(100.0 * (
        SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
        - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC))
      ) / SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)), 2)
    ELSE NULL END AS gross_margin_pct
  FROM "vbrp" v
  JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
  LEFT JOIN "MAKT" m ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
    AND (m."spras" = 'E' OR m."spras" IS NULL)
  WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
    AND CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
    AND {_year_predicate('vk')} IN ('{y1}', '{y2}')
    {pfilter}
  GROUP BY {_year_predicate('vk')}, TRIM(CAST(v."matnr" AS TEXT)), vk."waerk"
)
SELECT
  a.product,
  a.product_name,
  a.currency,
  a.revenue AS revenue_{y1},
  b.revenue AS revenue_{y2},
  a.cogs AS cogs_{y1},
  b.cogs AS cogs_{y2},
  a.gross_margin_pct AS margin_{y1},
  b.gross_margin_pct AS margin_{y2},
  (b.gross_margin_pct - a.gross_margin_pct) AS margin_change_pp
FROM yearly a
JOIN yearly b
  ON a.product = b.product AND a.currency = b.currency
 AND a.year = '{y1}' AND b.year = '{y2}'
ORDER BY margin_change_pp ASC NULLS LAST
LIMIT {limit}
""".strip()
        queries.append({"id": "margin_decline", "sql": sql_decline})
        # Driver slice: customer mix for declining set (same product filter if present)
        sql_cust = f"""
SELECT
  TRIM(CAST(vk."kunag" AS TEXT)) AS customer,
  MAX(k."name1") AS customer_name,
  MAX(k."brsch") AS industry,
  MAX(vk."land1") AS country,
  {_year_predicate('vk')} AS year,
  vk."waerk" AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
LEFT JOIN "KNA1" k ON TRIM(CAST(vk."kunag" AS TEXT)) = TRIM(CAST(k."kunnr" AS TEXT))
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  AND {_year_predicate('vk')} IN ('{y1}', '{y2}')
  {pfilter}
GROUP BY TRIM(CAST(vk."kunag" AS TEXT)), {_year_predicate('vk')}, vk."waerk"
ORDER BY revenue DESC NULLS LAST
LIMIT 40
""".strip()
        queries.append({"id": "margin_decline_customer_drivers", "sql": sql_cust})

    elif plan.intent == "monthly_trend":
        sql = f"""
SELECT
  EXTRACT(YEAR FROM CAST(NULLIF(TRIM(vk.fkdat), '') AS DATE)) AS year,
  EXTRACT(MONTH FROM CAST(NULLIF(TRIM(vk.fkdat), '') AS DATE)) AS month,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY EXTRACT(YEAR FROM CAST(NULLIF(TRIM(vk.fkdat), '') AS DATE)),
         EXTRACT(MONTH FROM CAST(NULLIF(TRIM(vk.fkdat), '') AS DATE)),
         vk.waerk
ORDER BY year, month
LIMIT 120
""".strip()
        queries.append({"id": "monthly_trend", "sql": sql})

    elif plan.intent == "product_industry_region":
        sql = f"""
SELECT
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown') AS industry,
  COALESCE(NULLIF(TRIM(vk.land1), ''), 'Unknown') AS country,
  vk.waerk AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS cogs,
  SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
    - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC)) AS gross_profit,
  CASE WHEN SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) > 0 THEN
    ROUND(100.0 * (
      SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC))
      - SUM(CAST(NULLIF(TRIM(CAST(COALESCE(v."wavwr", '0') AS TEXT)), '') AS NUMERIC))
    ) / SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)), 2)
  ELSE NULL END AS gross_margin_pct
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "KNA1" k ON TRIM(vk.kunag) = TRIM(k.kunnr)
LEFT JOIN "T016T" t ON TRIM(k.brsch) = TRIM(t.brsch)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) IS NOT NULL
  {yfilter}
  {pfilter}
GROUP BY TRIM(v.matnr),
         COALESCE(NULLIF(TRIM(t.brtxt), ''), NULLIF(TRIM(k.brsch), ''), 'Unknown'),
         COALESCE(NULLIF(TRIM(vk.land1), ''), 'Unknown'),
         vk.waerk
ORDER BY gross_profit DESC NULLS LAST
LIMIT {max(limit, 30)}
""".strip()
        queries.append({"id": "product_industry_region", "sql": sql})

    elif plan.intent == "inventory_analysis":
        queries.append({
            "id": "stock_value_by_material",
            "sql": f"""
SELECT
  TRIM(b.matnr) AS product,
  COALESCE(m.maktx, b.matnr) AS product_name,
  b.bwkey AS valuation_area,
  CAST(NULLIF(TRIM(COALESCE(b.salk3, '0')), '') AS NUMERIC) AS stock_value,
  CAST(NULLIF(TRIM(COALESCE(b.lbkum, '0')), '') AS NUMERIC) AS stock_qty,
  CAST(NULLIF(TRIM(COALESCE(b.stprs, '0')), '') AS NUMERIC) AS standard_price
FROM MBEW b
LEFT JOIN "MAKT" m ON TRIM(b.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE CAST(NULLIF(TRIM(COALESCE(b.salk3, '0')), '') AS NUMERIC) IS NOT NULL
ORDER BY stock_value DESC NULLS LAST
LIMIT {max(limit, 30)}
""".strip(),
        })
        queries.append({
            "id": "billing_velocity_proxy",
            "sql": f"""
SELECT
  TRIM(v.matnr) AS product,
  COALESCE(MAX(m.maktx), TRIM(v.matnr)) AS product_name,
  SUM(CAST(NULLIF(TRIM(CAST(v."fkimg" AS TEXT)), '') AS NUMERIC)) AS billed_qty,
  COUNT(DISTINCT vk.vbeln) AS invoice_count
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN "MAKT" m ON TRIM(v.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL)
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) <> ''
  {yfilter}
GROUP BY TRIM(v.matnr)
ORDER BY billed_qty ASC NULLS LAST
LIMIT {max(limit, 30)}
""".strip(),
        })
        gaps.append(
            "Slow/fast-moving uses billed quantity as a proxy; true inventory age needs movement history (MSEG not in schema_full)."
        )

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

    elif plan.intent in {"product_expiry", "product_expiry_by_industry"}:
        gaps.append(
            "Product expiry BI is partial: MARA shelf-life and LIPS.VFDAT exist, "
            "but batch expiry completeness varies."
        )
        if plan.intent == "product_expiry_by_industry":
            queries.append({
                "id": "product_expiry_by_industry",
                "sql": """
SELECT
  TRIM(CAST(a."matnr" AS TEXT)) AS product,
  COALESCE(MAX(mx."maktx"), TRIM(CAST(a."matnr" AS TEXT))) AS product_name,
  MAX(a."mhdhb") AS total_shelf_life_days,
  MAX(a."mhdrz") AS remaining_shelf_life_days,
  COALESCE(NULLIF(TRIM(CAST(MAX(t."brtxt") AS TEXT)), ''), NULLIF(TRIM(CAST(MAX(k."brsch") AS TEXT)), ''), 'Unknown') AS industry,
  COUNT(DISTINCT vk."kunag") AS customer_count
FROM "MARA" a
LEFT JOIN "MAKT" mx ON TRIM(CAST(a."matnr" AS TEXT)) = TRIM(CAST(mx."matnr" AS TEXT))
  AND (mx."spras" = 'E' OR mx."spras" IS NULL)
LEFT JOIN "vbrp" v ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(a."matnr" AS TEXT))
LEFT JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
LEFT JOIN "KNA1" k ON TRIM(CAST(vk."kunag" AS TEXT)) = TRIM(CAST(k."kunnr" AS TEXT))
LEFT JOIN "T016T" t ON TRIM(CAST(k."brsch" AS TEXT)) = TRIM(CAST(t."brsch" AS TEXT))
WHERE a."mhdhb" IS NOT NULL OR a."mhdrz" IS NOT NULL OR a."sled_bbd" IS NOT NULL
GROUP BY TRIM(CAST(a."matnr" AS TEXT))
ORDER BY CAST(NULLIF(TRIM(CAST(COALESCE(MAX(a."mhdrz"), MAX(a."mhdhb"), '0') AS TEXT)), '') AS NUMERIC) ASC NULLS LAST
LIMIT 50
""".strip(),
            })
        else:
            queries.append({
                "id": "product_shelf_life",
                "sql": """
SELECT
  TRIM(CAST(a."matnr" AS TEXT)) AS product,
  COALESCE(m."maktx", TRIM(CAST(a."matnr" AS TEXT))) AS product_name,
  a."mhdhb" AS total_shelf_life_days,
  a."mhdrz" AS remaining_shelf_life_days,
  a."sled_bbd" AS sled_bbd_indicator
FROM "MARA" a
LEFT JOIN "MAKT" m ON TRIM(CAST(a."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
  AND (m."spras" = 'E' OR m."spras" IS NULL)
WHERE a."mhdhb" IS NOT NULL OR a."mhdrz" IS NOT NULL OR a."sled_bbd" IS NOT NULL
ORDER BY CAST(NULLIF(TRIM(CAST(COALESCE(a."mhdrz", a."mhdhb", '0') AS TEXT)), '') AS NUMERIC) ASC NULLS LAST
LIMIT 50
""".strip(),
            })

    elif plan.intent == "dimensional_extend":
        # Reuse profitability grain when follow-up is ambiguous but context is deep
        sql = f"""{base_select}
ORDER BY {order_col} {direction} NULLS LAST
LIMIT {limit}"""
        queries.append({"id": "dimensional_extend", "sql": sql})

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
        if "gross_profit" in top or "revenue" in top or "margin_change_pp" in top:
            pname = top.get("product_name") or top.get("product") or top.get("industry") or top.get("country") or top.get("customer_name")
            if "margin_change_pp" in top:
                lines.append(
                    f"- Top decline/change: **{pname}** | margin_change_pp={_fmt_num(top.get('margin_change_pp'))} "
                    f"| currency={top.get('currency')}"
                )
                findings.append(
                    f"{pname}: margin change {_fmt_num(top.get('margin_change_pp'))} pp"
                )
            else:
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
        elif "first_purchase_date" in top or "purchase_duration_days" in top:
            lines.append(
                f"- Example: {top.get('customer_name') or top.get('customer')} × "
                f"{top.get('product_name') or top.get('product')}: "
                f"first={top.get('first_purchase_date')} last={top.get('last_purchase_date')} "
                f"duration_days={top.get('purchase_duration_days')} "
                f"purchases={top.get('purchase_count')} "
                f"revenue={_fmt_num(top.get('revenue'))} {top.get('currency')}"
            )
            findings.append(
                "Purchase duration = last billing date − first billing date (VBRK.FKDAT)."
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
    prior_for_gap = prior_ctx if isinstance(prior_ctx, dict) else None
    follow_gap = resolve_analytical_followup(question, prior_for_gap)
    if follow_gap.data_gap_metric == "net_profit" or "net profit" in ql or "ebit" in ql:
        return data_gap_payload(
            question,
            METRICS["net_profit"].caveats,
            can_answer=[
                "Product gross profit (NETWR − WAVWR)",
                "Gross margin %",
                "Revenue and invoice COGS by product/customer/industry/country/year",
            ],
            prior_analytical_context=prior_for_gap,
        )
    if (
        plan.intent in {"logistics_cost_gap", "net_profit_gap"}
        or follow_gap.data_gap_metric == "logistics_cost"
        or "logistics cost" in ql
        or "freight cost" in ql
        or (("logistics" in ql or "freight" in ql) and "cost" in ql)
    ):
        return data_gap_payload(
            question,
            METRICS["logistics_cost"].caveats,
            can_answer=[
                "Delivery/logistics activity (LIKP/LIPS document flow)",
                "Order→delivery→billing flow (VBFA)",
                "Invoice COGS proxy (WAVWR) — not freight",
            ],
            prior_analytical_context=prior_for_gap,
        )

    queries, gaps = compile_queries(plan)
    plan.data_gaps = list(dict.fromkeys((plan.data_gaps or []) + gaps))
    if not queries:
        if plan.data_gaps:
            return data_gap_payload(
                question,
                "; ".join(plan.data_gaps),
                can_answer=[
                    "Billing revenue by product/customer/industry/country",
                    "Gross profit proxy via WAVWR where populated",
                ],
                prior_analytical_context=prior_for_gap,
            )
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

    if not bundled or (
        not primary_rows
        and plan.intent
        not in {
            "process_sell",
            "process_buy",
            "process_sell_and_buy",
            "inventory_analysis",
            "monthly_trend",
            "margin_decline_drivers",
            "period_compare_selection",
            "product_expiry",
            "product_expiry_by_industry",
        }
    ):
        # fall through if we produced nothing useful
        if plan.data_gaps and not primary_rows:
            return data_gap_payload(
                question,
                "; ".join(plan.data_gaps[:3]),
                can_answer=[
                    "Product revenue from billing",
                    "Customer / industry / country sales cuts",
                ],
                prior_analytical_context=prior_for_gap,
            )
        return None

    # Empty year-compare / margin-decline: keep deep answer (do not fall through)
    if (
        not primary_rows
        and plan.intent in {"period_compare_selection", "margin_decline_drivers"}
        and bundled
    ):
        yrs = plan.filters.get("years") or plan.years or [2024, 2025]
        plan.data_gaps.append(
            f"No billing rows found for year(s) {yrs} on the current product selection. "
            "This loaded SAP extract is historical (billing years roughly through ~2018); "
            "2024/2025 comparisons need those periods present in the database."
        )
        primary_sql = bundled[0].get("sql") or ""
        summary = (
            f"**Deep analysis** — intent `{plan.intent}`\n\n"
            f"No rows for years {yrs} with the current filters.\n\n"
            "### Data limitations\n"
            + "\n".join(f"- {g}" for g in plan.data_gaps)
            + "\n\nTry: *Compare 2004 and 2005* or remove the year filter and ask again."
        )
        ctx = plan.to_context()
        return {
            "sql": primary_sql,
            "rowCount": 0,
            "data": [],
            "summary": summary,
            "keyFindings": plan.data_gaps[:4],
            "charts": [],
            "answer_status": "SUCCESS",
            "query_plan": {
                "analytical_context": ctx,
                "deep_analysis": True,
                "intent": plan.intent,
                "metrics": plan.metrics,
                "dimensions": plan.dimensions,
                "selected_products": plan.selected_products,
                "years": list(yrs),
            },
            "suggested_followups": [
                "Compare 2004 and 2005",
                "Show COGS",
                "Show their customers",
            ],
            "meta": {
                "deep_analysis": True,
                "analytical_plan": ctx,
                "query_count": len(bundled),
                "data_gaps": plan.data_gaps,
                "empty_year_compare": True,
            },
            "pipeline": "deep_multidim",
            "sql_generation_method": "deep_multidim",
            "llm_calls": 0,
        }

    # Update selection from primary product rows (do not let process/expiry
    # stage outputs wipe the monetary product selection used for follow-ups).
    _preserve_product_selection = plan.intent in {
        "process_sell",
        "process_buy",
        "process_sell_and_buy",
        "product_expiry",
        "product_expiry_by_industry",
        "inventory_analysis",
    }
    if (
        primary_rows
        and (primary_rows[0].get("product") or primary_rows[0].get("matnr"))
        and not _preserve_product_selection
    ):
        plan.selected_products = [
            str(r.get("product") or r.get("matnr")).strip()
            for r in primary_rows[:20]
            if r.get("product") or r.get("matnr")
        ]
    if primary_rows and primary_rows[0].get("customer") and not _preserve_product_selection:
        plan.selected_customers = [
            str(r.get("customer")).strip()
            for r in primary_rows[:20]
            if r.get("customer")
        ]

    plan.drilldowns = available_drilldowns(set(plan.dimensions), set(plan.metrics))
    summary, findings = _interpret(plan, bundled)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "[deep] analysis_complete intent=%s metrics=%s dims=%s query_count=%s "
        "row_count=%s gaps=%s elapsed_ms=%s status=SUCCESS",
        plan.intent,
        plan.metrics,
        plan.dimensions,
        len(bundled),
        len(primary_rows),
        plan.data_gaps[:3],
        elapsed_ms,
    )

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
    if primary_rows and (
        "gross_profit" in primary_rows[0]
        or "revenue" in primary_rows[0]
        or "margin_change_pp" in primary_rows[0]
        or "stock_value" in primary_rows[0]
    ):
        label_key = "product_name" if "product_name" in primary_rows[0] else (
            "customer_name" if "customer_name" in primary_rows[0] else (
                "industry" if "industry" in primary_rows[0] else (
                    "country" if "country" in primary_rows[0] else "product"
                )
            )
        )
        value_key = (
            "margin_change_pp"
            if "margin_change_pp" in primary_rows[0]
            else (
                "gross_profit"
                if "gross_profit" in primary_rows[0]
                else ("stock_value" if "stock_value" in primary_rows[0] else "revenue")
            )
        )
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
