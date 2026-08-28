"""
Deterministic follow-up resolver for multi-dimensional deep analysis.

Resolves short natural follow-ups against persisted analytical_context —
not phrase-specific patches. Used before clarification gates and inside the
deep planner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .business_semantic_layer import (
    DIMENSION_ALIASES,
    METRICS,
    metric_status,
    resolve_metric,
)
from .inventory_sales import (
    INVENTORY_GAP_INTENTS,
    INVENTORY_INTENTS,
    resolve_inventory_intent,
    resolve_risk_direction,
    wants_inventory_aging,
    wants_inventory_by_plant,
    wants_true_inventory_turnover,
    wants_inventory_trend,
)

FollowUpKind = str

KIND_METRIC_CHANGE = "METRIC_CHANGE"
KIND_DIMENSION_EXPANSION = "DIMENSION_EXPANSION"
KIND_DIMENSION_REPLACE = "DIMENSION_REPLACE"
KIND_DIMENSION_REMOVE = "DIMENSION_REMOVE"
KIND_FILTER_CHANGE = "FILTER_CHANGE"
KIND_TIME_CHANGE = "TIME_CHANGE"
KIND_COMPARISON = "COMPARISON"
KIND_RANKING_CHANGE = "RANKING_CHANGE"
KIND_DETAIL_BREAKDOWN = "DETAIL_BREAKDOWN"
KIND_CAUSE_ANALYSIS = "CAUSE_ANALYSIS"
KIND_PROCESS_EXPANSION = "PROCESS_EXPANSION"
KIND_HISTORY_EXPANSION = "HISTORY_EXPANSION"
KIND_DATA_GAP_REQUEST = "DATA_GAP_REQUEST"
KIND_RESET = "RESET"
KIND_NEW_QUESTION = "NEW_QUESTION"
KIND_CLARIFICATION = "CLARIFICATION"

_PRONOUN_RE = re.compile(
    r"\b(them|they|those|these|their|it|that|this|the same)\b",
    re.I,
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_BREAKDOWN_RE = re.compile(
    r"\b(break\s+(that|it|this)?\s*down|show\s+the?\s*breakdown|"
    r"show\s+(the\s+)?components|cost\s+components|breakdown)\b",
    re.I,
)
_COMPARE_RE = re.compile(
    r"\b(compare|vs\.?|versus|year over year|yoy)\b",
    re.I,
)
_WHY_RE = re.compile(
    r"\b(why\s+did|why\s+is|why\s+are|why\s+have|explain\s+why|what\s+caused)\b",
    re.I,
)
_HISTORY_RE = re.compile(
    r"\b(how\s+long|purchase\s+history|been\s+buying|buying\s+them|"
    r"first\s+purchase|last\s+purchase|purchase\s+duration|purchase\s+count)\b",
    re.I,
)
_PROCESS_RE = re.compile(
    r"\b(process|selling\s+process|buying\s+process|purchase\s+process|"
    r"delivery\s+process|order\s+to\s+cash|procure|upstream|billing\s+process)\b",
    re.I,
)
_REMOVE_DIM_RE = re.compile(
    r"\b(remove|drop|without|exclude|skip)\s+(the\s+)?(industry|industries|"
    r"region|regions|country|countries|customer|customers|product|products|year)\b",
    re.I,
)
_REPLACE_DIM_RE = re.compile(
    r"\b(just|only)\s+(show\s+)?(the\s+)?(regions?|countries?|customers?|"
    r"industries?|products?|years?)\b",
    re.I,
)
_RESET_RE = re.compile(
    r"\b(now\s+show\s+all|go\s+back|reset|start\s+over|all\s+products)\b",
    re.I,
)

# Short metric phrases → governed metric keys (deterministic, not LLM).
_SHORT_METRIC_PHRASES: Dict[str, str] = {
    "cogs": "cogs",
    "cost of goods sold": "cogs",
    "cost of goods": "cogs",
    "goods cost": "cogs",
    "product cost": "cogs",
    "show cost": "cogs",
    "the cost": "cogs",
    "cost": "cogs",
    "margin": "gross_margin_pct",
    "margins": "gross_margin_pct",
    "gross margin": "gross_margin_pct",
    "profit": "gross_profit",
    "profits": "gross_profit",
    "gross profit": "gross_profit",
    "revenue": "revenue",
    "sales": "revenue",
    "quantity": "quantity",
    "qty": "quantity",
    "asp": "avg_selling_price",
    "average selling price": "avg_selling_price",
    "unit price": "avg_selling_price",
    "selling price": "avg_selling_price",
    "invoice count": "invoice_count",
    "invoices": "invoice_count",
    "net profit": "net_profit",
    "bottom line": "net_profit",
    "logistics cost": "logistics_cost",
    "freight cost": "logistics_cost",
    "shipping cost": "logistics_cost",
}

# Short dimension phrases → canonical dimension keys.
_SHORT_DIMENSION_PHRASES: Dict[str, str] = {
    "customer": "customer",
    "customers": "customer",
    "their customers": "customer",
    "the customers": "customer",
    "industry": "industry",
    "industries": "industry",
    "region": "country",
    "regions": "country",
    "the regions": "country",
    "country": "country",
    "countries": "country",
    "product": "product",
    "products": "product",
    "year": "year",
    "years": "year",
    "month": "month",
    "months": "month",
    "quarter": "quarter",
    "quarters": "quarter",
    "supplier": "supplier",
    "delivery": "delivery",
    "expiry": "expiry",
    "inventory": "inventory",
    "stock": "inventory",
    "plant": "warehouse",
    "plants": "warehouse",
    "warehouse": "warehouse",
    "warehouses": "warehouse",
    "supplier": "supplier",
    "suppliers": "supplier",
    "vendor": "supplier",
    "vendors": "supplier",
    "product group": "product_group",
    "product groups": "product_group",
    "category": "product_group",
}

# Intent mapping from resolved follow-up kind + signals.
_INTENT_BY_RESOLUTION: Dict[str, str] = {
    "cogs": "cogs_by_product",
    "gross_margin_pct": "margin_by_product",
    "gross_profit": "product_profitability",
    "revenue": "product_profitability",
    "customer": "customers_of_selection",
    "industry": "industry_breakdown",
    "country": "country_breakdown",
    "purchase_history": "purchase_history",
    "process_sell": "process_sell",
    "process_buy": "process_buy",
    "process_both": "process_sell_and_buy",
    "process_delivery": "process_sell",
    "components": "profit_components",
    "margin_decline": "margin_decline_drivers",
    "product_growth": "product_growth_decline",
    "product_decline": "product_growth_decline",
    "period_compare": "period_compare_selection",
    "month": "monthly_trend",
    "quarter": "quarterly_trend",
    "logistics_cost": "logistics_cost_gap",
    "net_profit": "net_profit_gap",
    "supplier": "suppliers_of_selection",
    "inventory": "inventory_analysis",
    "inventory_sales": "inventory_sales_comparison",
    "inventory_risk": "inventory_risk_analysis",
    "warehouse": "inventory_by_plant",
    "plant": "inventory_by_plant",
    "product_group": "product_group_breakdown",
    "avg_selling_price": "product_profitability",
}

_TIME_GRAIN_INTENTS = frozenset({"monthly_trend", "quarterly_trend"})
_PRODUCT_CHANGE_INTENTS = frozenset({"product_growth_decline", "margin_decline_drivers"})
_GROWTH_SIGNAL_RE = re.compile(
    r"\b(grew|grow|growth|growers?|gainers?|increase[sd]?|rose|risen|improv\w*)\b",
    re.I,
)
_DECLINE_SIGNAL_RE = re.compile(
    r"\b(declin\w*|drop(?:ped)?|fell|fall|losers?|lost|worsen\w*|deteriorat\w*|decrease[sd]?|shrink\w*)\b",
    re.I,
)
_MONTH_SIGNAL_RE = re.compile(
    r"\b(monthly|by\s+month|each\s+month|per\s+month|months?|mom|month[\s-]over[\s-]month)\b",
    re.I,
)
_QUARTER_SIGNAL_RE = re.compile(
    r"\b(quarterly|by\s+quarter|each\s+quarter|per\s+quarter|quarters?|qoq|"
    r"quarter[\s-]over[\s-]quarter)\b",
    re.I,
)


@dataclass
class FollowUpResolution:
    kind: FollowUpKind = KIND_NEW_QUESTION
    intent: Optional[str] = None
    metrics: List[str] = field(default_factory=list)
    add_dimensions: List[str] = field(default_factory=list)
    remove_dimensions: List[str] = field(default_factory=list)
    replace_dimensions: List[str] = field(default_factory=list)
    years: List[int] = field(default_factory=list)
    comparisons: List[str] = field(default_factory=list)
    data_gap_metric: Optional[str] = None
    has_pronoun_reference: bool = False
    resolved: bool = False
    needs_clarification: bool = False
    clarification_reason: str = ""


def _ql(q: str) -> str:
    return (q or "").strip().lower().rstrip(".?!")


def _tokens(ql: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9]+", ql))


def _extract_years(q: str) -> List[int]:
    return sorted({int(m.group(0)) for m in _YEAR_RE.finditer(q or "")})


def _detect_metric(ql: str, prior_metrics: Optional[List[str]] = None) -> Optional[str]:
    """Resolve governed metric from short or partial phrasing."""
    # Longest phrase first to avoid "cost" matching before "cost of goods"
    for phrase, key in sorted(_SHORT_METRIC_PHRASES.items(), key=lambda x: -len(x[0])):
        if phrase in ql:
            return key
    for m in METRICS.values():
        for alias in m.aliases:
            if len(alias) >= 4 and alias in ql:
                return m.name
    # Contextual "cost" when prior analysis is profitability-focused
    if ql.strip() in {"cost", "show cost", "the cost"} and prior_metrics:
        if any(m in prior_metrics for m in ("gross_profit", "cogs", "revenue", "gross_margin_pct")):
            return "cogs"
    resolved = resolve_metric(ql)
    return resolved.name if resolved else None


def _detect_dimension(ql: str) -> Optional[str]:
    for phrase, key in sorted(_SHORT_DIMENSION_PHRASES.items(), key=lambda x: -len(x[0])):
        if phrase in ql:
            return key
    for token in _tokens(ql):
        if token in DIMENSION_ALIASES:
            return DIMENSION_ALIASES[token]
    if re.search(r"\bby\s+(industry|region|country|customer|product|year|month|quarter)\b", ql):
        m = re.search(r"\bby\s+(industry|region|country|customer|product|year|month|quarter)\b", ql)
        if m:
            return DIMENSION_ALIASES.get(m.group(1), m.group(1))
    return None


def _wants_process_sell(ql: str) -> bool:
    if ql.strip() in {"show the process", "show process", "the process"}:
        return True
    if "process" not in ql:
        return False
    return any(
        x in ql
        for x in (
            "selling process",
            "sell process",
            "selling",
            "order to cash",
            "delivery process",
            "billing process",
            "to sell",
            "delivery",
        )
    )


def _wants_process_buy(ql: str) -> bool:
    if ql.strip() in {"show the buying process", "buying process"}:
        return True
    return any(
        x in ql
        for x in (
            "buying process",
            "buy process",
            "purchase process",
            "procurement",
            "to buy",
            "involved in buying",
            "behind buying",
        )
    )


def has_deep_analytical_context(previous_plan: Optional[Dict[str, Any]]) -> bool:
    """True when prior turn established governed deep analysis state."""
    if not isinstance(previous_plan, dict):
        return False
    if previous_plan.get("deep_analysis"):
        return True
    ac = previous_plan.get("analytical_context")
    if isinstance(ac, dict) and ac.get("deep_analysis"):
        return True
    return False


def extract_analytical_context(previous_plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(previous_plan, dict):
        return None
    ac = previous_plan.get("analytical_context")
    if isinstance(ac, dict) and ac.get("deep_analysis"):
        return ac
    if previous_plan.get("deep_analysis"):
        return previous_plan
    return None


def is_deep_followup_allowed(question: str, previous_plan: Optional[Dict[str, Any]] = None) -> bool:
    """Gate helper: short analytical follow-ups against prior deep context."""
    if not has_deep_analytical_context(previous_plan):
        return False
    ql = _ql(question)
    if not ql:
        return False
    resolution = resolve_analytical_followup(question, extract_analytical_context(previous_plan))
    return resolution.resolved and not resolution.needs_clarification


def resolve_analytical_followup(
    question: str,
    prior_ctx: Optional[Dict[str, Any]] = None,
) -> FollowUpResolution:
    """
    Resolve a follow-up question against analytical context.

    Returns unresolved resolution when prior_ctx is absent or question is a
    standalone new analytical query.
    """
    res = FollowUpResolution()
    ql = _ql(question)
    if not ql:
        res.needs_clarification = True
        res.clarification_reason = "empty_question"
        return res

    if not prior_ctx or not prior_ctx.get("deep_analysis"):
        return res

    res.has_pronoun_reference = bool(_PRONOUN_RE.search(ql))
    prior_metrics = list(prior_ctx.get("metrics") or [])
    prior_dims = list(prior_ctx.get("dimensions") or [])
    prior_intent = str(prior_ctx.get("intent") or "")

    # ── Reset / new question detection ──
    if _RESET_RE.search(ql) and not res.has_pronoun_reference:
        res.kind = KIND_RESET
        res.intent = "product_profitability"
        res.resolved = True
        return res

    # ── Data gap metrics (must not destroy context) ──
    metric_key = _detect_metric(ql, prior_metrics)
    if metric_key in {"net_profit", "logistics_cost", "inventory_aging", "inventory_turnover"}:
        res.kind = KIND_DATA_GAP_REQUEST
        res.data_gap_metric = metric_key
        if metric_key == "inventory_aging":
            res.intent = "inventory_aging_gap"
        elif metric_key == "inventory_turnover":
            res.intent = "inventory_turnover_gap"
        else:
            res.intent = _INTENT_BY_RESOLUTION.get(metric_key, "logistics_cost_gap")
        res.resolved = True
        return res
    if wants_inventory_aging(ql):
        res.kind = KIND_DATA_GAP_REQUEST
        res.data_gap_metric = "inventory_aging"
        res.intent = "inventory_aging_gap"
        res.resolved = True
        return res
    if wants_true_inventory_turnover(ql):
        res.kind = KIND_DATA_GAP_REQUEST
        res.data_gap_metric = "inventory_turnover"
        res.intent = "inventory_turnover_gap"
        res.resolved = True
        return res
    if wants_inventory_trend(ql):
        res.kind = KIND_DATA_GAP_REQUEST
        res.data_gap_metric = "inventory_aging"
        res.intent = "inventory_trend_gap"
        res.resolved = True
        return res

    if re.search(
        r"\b(supplier\s+concentration|purchase\s+share|share\s+of\s+purchas|single[\s-]?source|top\s+suppliers?)\b",
        ql,
    ):
        res.kind = KIND_DIMENSION_EXPANSION
        res.add_dimensions = ["supplier"]
        res.intent = "supplier_concentration"
        res.resolved = True
        return res

    # ── Dimension remove / replace ──
    rm = _REMOVE_DIM_RE.search(ql)
    if rm:
        dim_word = rm.group(2).rstrip("s") if rm.group(2) else ""
        canonical = DIMENSION_ALIASES.get(dim_word, dim_word)
        res.kind = KIND_DIMENSION_REMOVE
        res.remove_dimensions = [canonical] if canonical else []
        res.intent = prior_intent or "dimensional_extend"
        res.resolved = True
        return res

    rep = _REPLACE_DIM_RE.search(ql)
    if rep:
        dim_word = rep.group(3).rstrip("s")
        canonical = DIMENSION_ALIASES.get(dim_word, dim_word)
        res.kind = KIND_DIMENSION_REPLACE
        res.replace_dimensions = [canonical] if canonical else []
        res.intent = _INTENT_BY_RESOLUTION.get(canonical, "dimensional_extend")
        res.resolved = True
        return res

    # ── Why / cause analysis ──
    if _WHY_RE.search(ql) or ql.strip() in {
        "why",
        "why?",
        "why did it decline?",
        "why did it decline",
        "what drove the decline?",
        "what drove the decline",
        "what drove the growth?",
        "what drove the growth",
        "what changed?",
        "what changed",
    }:
        if prior_intent in INVENTORY_INTENTS or prior_intent in INVENTORY_GAP_INTENTS:
            # Observed facts only — do not invent inventory causality.
            res.kind = KIND_CAUSE_ANALYSIS
            res.intent = prior_intent if prior_intent in INVENTORY_INTENTS else "inventory_analysis"
            res.resolved = True
            return res
        if prior_intent in _TIME_GRAIN_INTENTS:
            res.kind = KIND_CAUSE_ANALYSIS
            res.intent = prior_intent
            res.comparisons = ["yoy", "mom" if prior_intent == "monthly_trend" else "qoq"]
            res.resolved = True
            return res
        if prior_intent == "product_growth_decline" or (
            prior_intent in _PRODUCT_CHANGE_INTENTS
            and (_GROWTH_SIGNAL_RE.search(ql) or _DECLINE_SIGNAL_RE.search(ql) or ql.strip() in {"why", "why?"})
        ):
            # Preserve product growth/decline context for observed-driver follow-ups.
            if "margin" in ql and prior_intent == "margin_decline_drivers":
                res.kind = KIND_CAUSE_ANALYSIS
                res.intent = "margin_decline_drivers"
                res.comparisons = ["yoy_margin"]
                res.resolved = True
                return res
            res.kind = KIND_CAUSE_ANALYSIS
            res.intent = "product_growth_decline" if prior_intent == "product_growth_decline" else prior_intent
            res.comparisons = ["yoy", "product_change"]
            res.resolved = True
            return res
        if (
            "margin" in ql
            or "decline" in ql
            or "fall" in ql
            or "fell" in ql
            or prior_intent in {"margin_by_product", "margin_decline_drivers", "product_profitability"}
        ):
            res.kind = KIND_CAUSE_ANALYSIS
            res.intent = "margin_decline_drivers"
            res.comparisons = ["yoy_margin"]
            res.resolved = True
            return res

    # ── Product growth / decline ranking switch (before generic metric) ──
    # Do not steal dimension drills that merely contain the word "product"
    # (e.g. "Show their product groups.").
    _dim_drill = any(
        x in ql
        for x in (
            "product group",
            "product groups",
            "material group",
            "supplier",
            "suppliers",
            "inventory",
            "customer",
            "customers",
            "region",
            "regions",
            "industry",
            "industries",
            "country",
            "countries",
        )
    )
    if (
        not _dim_drill
        and (
            prior_intent == "product_growth_decline"
            or _GROWTH_SIGNAL_RE.search(ql)
            or _DECLINE_SIGNAL_RE.search(ql)
        )
        and any(
            x in ql
            for x in (
                "product",
                "products",
                "grower",
                "growers",
                "loser",
                "losers",
                "gainer",
                "gainers",
                "which of them",
                "which ones",
            )
        )
    ):
        # Keep R4-1 month/quarter margin ranking when grain is explicit.
        if _QUARTER_SIGNAL_RE.search(ql) and "margin" in ql:
            res.kind = KIND_RANKING_CHANGE
            res.intent = "quarterly_trend"
            res.add_dimensions = ["quarter"]
            res.comparisons = ["qoq", "yoy"]
            res.resolved = True
            return res
        if _MONTH_SIGNAL_RE.search(ql) and "margin" in ql:
            res.kind = KIND_RANKING_CHANGE
            res.intent = "monthly_trend"
            res.add_dimensions = ["month"]
            res.comparisons = ["mom", "yoy"]
            res.resolved = True
            return res
        # Bare prior-context + "product" without growth/decline language is not a ranking switch.
        if prior_intent == "product_growth_decline" and not (
            _GROWTH_SIGNAL_RE.search(ql)
            or _DECLINE_SIGNAL_RE.search(ql)
            or any(
                x in ql
                for x in (
                    "grower",
                    "growers",
                    "loser",
                    "losers",
                    "gainer",
                    "gainers",
                    "which of them",
                    "which ones",
                    "fastest",
                    "most",
                )
            )
        ):
            pass  # fall through to dimension / metric handlers
        else:
            res.kind = KIND_RANKING_CHANGE
            res.intent = "product_growth_decline"
            res.comparisons = ["yoy", "product_change"]
            if _MONTH_SIGNAL_RE.search(ql):
                res.comparisons = ["mom", "yoy", "product_change"]
                res.add_dimensions = ["month"]
            elif _QUARTER_SIGNAL_RE.search(ql):
                res.comparisons = ["qoq", "yoy", "product_change"]
                res.add_dimensions = ["quarter"]
            res.resolved = True
            return res
    if prior_intent == "product_growth_decline" and (
        _GROWTH_SIGNAL_RE.search(ql)
        or _DECLINE_SIGNAL_RE.search(ql)
        or any(x in ql for x in ("what changed", "components", "show their growth", "show growth"))
    ):
        res.kind = KIND_RANKING_CHANGE
        res.intent = "product_growth_decline"
        res.comparisons = ["yoy", "product_change"]
        res.resolved = True
        return res

    # ── Process expansion (before history — "buying process" is not purchase history) ──
    if _PROCESS_RE.search(ql) or ql.strip() in {"show the process", "show process"}:
        sell = _wants_process_sell(ql)
        buy = _wants_process_buy(ql)
        if sell and buy:
            res.kind = KIND_PROCESS_EXPANSION
            res.intent = "process_sell_and_buy"
        elif buy:
            res.kind = KIND_PROCESS_EXPANSION
            res.intent = "process_buy"
        elif sell or "delivery" in ql:
            res.kind = KIND_PROCESS_EXPANSION
            res.intent = "process_sell"
        elif ql.strip() in {"show the process", "show process", "the process"}:
            res.kind = KIND_PROCESS_EXPANSION
            res.intent = "process_sell"
        else:
            res.kind = KIND_PROCESS_EXPANSION
            res.intent = "process_sell"
        res.resolved = True
        return res

    # ── Purchase history (not when asking for customers) ──
    customer_primary = bool(
        re.search(r"\b(show|which|what|list)\s+(the\s+)?(their\s+)?customers?\b", ql)
        or (ql.startswith("show") and "customer" in ql and "how long" not in ql)
    )
    if not customer_primary and (
        _HISTORY_RE.search(ql)
        or (res.has_pronoun_reference and any(x in ql for x in ("how long", "been buying", "buying them")))
    ):
        res.kind = KIND_HISTORY_EXPANSION
        res.intent = "purchase_history"
        res.resolved = True
        return res

    # ── Inventory snapshot / vs-sales / risk / plant (before history and compare) ──
    inv_intent = resolve_inventory_intent(ql)
    if inv_intent:
        res.kind = KIND_DIMENSION_EXPANSION if inv_intent not in INVENTORY_GAP_INTENTS else KIND_DATA_GAP_REQUEST
        res.intent = inv_intent
        if inv_intent in INVENTORY_GAP_INTENTS:
            res.data_gap_metric = (
                "inventory_turnover" if inv_intent == "inventory_turnover_gap" else "inventory_aging"
            )
        if inv_intent == "inventory_by_plant":
            res.add_dimensions = ["warehouse"]
        elif inv_intent == "inventory_sales_comparison" and "product group" in ql:
            res.add_dimensions = ["product_group"]
        risk = resolve_risk_direction(ql)
        if risk:
            res.comparisons = [risk]
        res.resolved = True
        return res
    if wants_inventory_by_plant(ql) or (
        prior_intent in INVENTORY_INTENTS
        and any(x in ql for x in ("by plant", "by warehouse", "plants", "warehouse"))
    ):
        res.kind = KIND_DIMENSION_EXPANSION
        res.intent = "inventory_by_plant"
        res.add_dimensions = ["warehouse"]
        res.resolved = True
        return res
    if prior_intent in INVENTORY_INTENTS and any(
        x in ql for x in ("by product group", "product groups", "material group")
    ) and "inventory" not in ql:
        # "Show their product groups" after inventory → sales product_group_breakdown (existing)
        pass
    if prior_intent in INVENTORY_INTENTS and (
        ql.strip() in {"compare them", "compare", "compare that"}
        or (
            any(x in ql for x in ("compare", "versus", " vs "))
            and any(x in ql for x in ("sales", "revenue", "inventory"))
            and "last year" not in ql
            and "previous year" not in ql
            and not _YEAR_RE.search(ql)
        )
    ):
        res.kind = KIND_COMPARISON
        res.intent = "inventory_sales_comparison"
        res.resolved = True
        return res

    years = _extract_years(question)

    # ── Time grain change (month / quarter) before bare year compare ──
    if _QUARTER_SIGNAL_RE.search(ql) and (
        res.has_pronoun_reference
        or re.match(r"^(show|give|display|compare)\b", ql)
        or "trend" in ql
        or "performance" in ql
        or len(_tokens(ql)) <= 8
    ):
        res.kind = KIND_TIME_CHANGE
        res.intent = "quarterly_trend"
        res.add_dimensions = ["quarter"]
        res.years = years
        if _COMPARE_RE.search(ql) or len(years) >= 2 or "last year" in ql:
            res.comparisons = ["yoy", "qoq"]
        else:
            res.comparisons = ["qoq"]
        res.resolved = True
        return res
    if _MONTH_SIGNAL_RE.search(ql) and (
        res.has_pronoun_reference
        or re.match(r"^(show|give|display|compare)\b", ql)
        or "trend" in ql
        or len(_tokens(ql)) <= 8
    ):
        res.kind = KIND_TIME_CHANGE
        res.intent = "monthly_trend"
        res.add_dimensions = ["month"]
        res.years = years
        if _COMPARE_RE.search(ql) or len(years) >= 2 or "last year" in ql:
            res.comparisons = ["yoy", "mom"]
        else:
            res.comparisons = ["mom"]
        res.resolved = True
        return res

    # ── Time comparison ──
    prior_time = prior_intent in _TIME_GRAIN_INTENTS
    if _COMPARE_RE.search(ql) or len(years) >= 2 or (
        years and any(x in ql for x in ("compare", "versus", "vs", "and", "last year"))
    ):
        res.kind = KIND_COMPARISON
        if prior_time:
            # Keep month/quarter grain when comparing years inside a trend context.
            res.intent = prior_intent
            res.comparisons = ["yoy", "mom" if prior_intent == "monthly_trend" else "qoq"]
        else:
            res.intent = "period_compare_selection"
            res.comparisons = ["yoy"]
        res.years = years
        res.resolved = True
        return res

    # ── Breakdown / components (dimension-specific breakdown wins over generic) ──
    # Prefer multi-word dimensions (product group) before bare "product".
    dim_in_break = re.search(
        r"\bby\s+(product\s+groups?|material\s+groups?|industr(?:y|ies)|"
        r"regions?|countries?|customers?|products?|years?|months?|quarters?|plants?|warehouses?)\b",
        ql,
    )
    if dim_in_break:
        dim_word = dim_in_break.group(1).strip()
        if dim_word.startswith("product group") or dim_word.startswith("material group"):
            canonical = "product_group"
        else:
            # Normalize common plural forms to alias keys.
            plural_map = {
                "industries": "industry",
                "regions": "region",
                "countries": "country",
                "customers": "customer",
                "products": "product",
                "years": "year",
                "months": "month",
                "quarters": "quarter",
                "plants": "plant",
                "warehouses": "warehouse",
            }
            key = plural_map.get(dim_word, dim_word)
            canonical = DIMENSION_ALIASES.get(key, key)
        res.kind = KIND_DIMENSION_EXPANSION
        res.add_dimensions = [canonical]
        res.intent = _INTENT_BY_RESOLUTION.get(canonical, "dimensional_extend")
        res.resolved = True
        return res
    dim_break = re.search(
        r"\b(product\s+group|material\s+group|industry|regional|region|"
        r"country|customer|product)\s+breakdown\b",
        ql,
    )
    if dim_break:
        dim_word = dim_break.group(1)
        if dim_word in {"product group", "material group"}:
            canonical = "product_group"
        elif dim_word == "regional":
            canonical = "country"
        else:
            canonical = DIMENSION_ALIASES.get(dim_word, dim_word)
        res.kind = KIND_DIMENSION_EXPANSION
        res.add_dimensions = [canonical]
        res.intent = _INTENT_BY_RESOLUTION.get(canonical, "dimensional_extend")
        res.resolved = True
        return res
    if _BREAKDOWN_RE.search(ql):
        dim_key = _detect_dimension(ql)
        # "break ... down by X" (without the literal word "breakdown")
        if dim_key and "component" not in ql and (
            "breakdown" in ql or "break" in ql or "by " in ql
        ):
            res.kind = KIND_DIMENSION_EXPANSION
            res.add_dimensions = [dim_key]
            res.intent = _INTENT_BY_RESOLUTION.get(dim_key, "dimensional_extend")
            res.resolved = True
            return res
        res.kind = KIND_DETAIL_BREAKDOWN
        res.intent = "profit_components"
        res.resolved = True
        return res

    # ── Margin decline ranking (month/quarter grain wins over product YoY drivers) ──
    if any(x in ql for x in ("margin decline", "biggest margin", "declining margin", "margin erosion")):
        res.kind = KIND_RANKING_CHANGE
        if _QUARTER_SIGNAL_RE.search(ql) or prior_intent == "quarterly_trend":
            res.intent = "quarterly_trend"
            res.add_dimensions = ["quarter"]
            res.comparisons = ["qoq", "yoy"]
        elif _MONTH_SIGNAL_RE.search(ql) or prior_intent == "monthly_trend":
            res.intent = "monthly_trend"
            res.add_dimensions = ["month"]
            res.comparisons = ["mom", "yoy"]
        else:
            res.intent = "margin_decline_drivers"
            res.comparisons = ["yoy_margin"]
        res.resolved = True
        return res

    # ── Metric-only follow-ups (Show COGS / Show margins / Show profit) ──
    if metric_key and metric_status(metric_key) == "supported":
        dim_key = _detect_dimension(ql)
        # Pure metric switch: "show cogs", "show margins", "show cost"
        metric_only = (
            len(_tokens(ql)) <= 5
            or re.match(
                r"^(show|give|display)\s+(me\s+)?(the\s+)?"
                r"(cogs|cost|margin|margins|profit|revenue|sales|quantity)\.?$",
                ql,
            )
        )
        if metric_only and not dim_key:
            res.kind = KIND_METRIC_CHANGE
            res.metrics = [metric_key]
            if prior_intent in _TIME_GRAIN_INTENTS:
                # Keep month/quarter aggregation; only swap metrics.
                res.intent = prior_intent
            elif prior_intent == "product_growth_decline":
                res.intent = "product_growth_decline"
            elif prior_intent in INVENTORY_INTENTS and metric_key == "quantity":
                res.intent = prior_intent
            elif metric_key == "gross_profit" and prior_intent:
                res.intent = prior_intent
            else:
                res.intent = _INTENT_BY_RESOLUTION.get(metric_key, "dimensional_extend")
            res.resolved = True
            return res

    # ── Dimension expansion (Show regions / Show customers / Break by industry) ──
    dim_key = _detect_dimension(ql)
    if dim_key:
        # "break that down by industry" / "show the regions"
        expand = (
            res.has_pronoun_reference
            or "break" in ql
            or "by " in ql
            or re.match(r"^(show|give|display)\s+(me\s+)?(the\s+)?", ql)
            or len(_tokens(ql)) <= 6
        )
        if expand:
            res.kind = KIND_DIMENSION_EXPANSION
            res.add_dimensions = [dim_key]
            # Multi-dimension combos
            if dim_key == "customer" and "industry" in ql and ("region" in ql or "country" in ql):
                res.intent = "customer_industry_region"
            elif dim_key == "customer":
                res.intent = "customers_of_selection"
            elif dim_key == "industry":
                res.intent = "industry_breakdown"
            elif dim_key == "country":
                res.intent = "country_breakdown"
            elif dim_key == "supplier":
                res.intent = "suppliers_of_selection"
            elif dim_key == "inventory":
                res.intent = "inventory_analysis"
            elif dim_key == "warehouse":
                res.intent = "inventory_by_plant"
            elif dim_key == "product_group":
                res.intent = "product_group_breakdown"
            elif dim_key == "month":
                res.intent = "monthly_trend"
            elif dim_key == "quarter":
                res.intent = "quarterly_trend"
            else:
                res.intent = _INTENT_BY_RESOLUTION.get(dim_key, "dimensional_extend")
            res.resolved = True
            return res

    # ── Generic dimensional extend for very short utterances with pronouns ──
    if res.has_pronoun_reference and len(_tokens(ql)) <= 8:
        res.kind = KIND_DIMENSION_EXPANSION
        res.intent = prior_intent or "dimensional_extend"
        res.resolved = True
        return res

    # ── Fallback: inherit prior intent for short follow-ups (< 8 tokens) ──
    if len(_tokens(ql)) <= 8 and prior_intent:
        res.kind = KIND_DIMENSION_EXPANSION
        if prior_intent in _TIME_GRAIN_INTENTS or prior_intent == "product_growth_decline" or prior_intent in INVENTORY_INTENTS:
            res.intent = prior_intent
        else:
            res.intent = "dimensional_extend"
        res.resolved = True
        return res

    return res
