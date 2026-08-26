"""
Governed product growth / decline change expressions.

absolute_change = current - previous
growth_pct = ((current - previous) / previous) * 100  when previous != 0 else NULL

Do not fabricate infinity or arbitrary percentages for zero prior values.
"""
from __future__ import annotations

from typing import Literal, Optional, Tuple

ChangeMode = Literal["absolute", "pct"]
Direction = Literal["growth", "decline"]

# Metrics allowed for product period change (billing grain only).
GROWTH_METRICS = (
    "revenue",
    "cogs",
    "gross_profit",
    "gross_margin_pct",
    "quantity",
    "avg_selling_price",
    "invoice_count",
)


def abs_change_sql(curr: str, prev: str, alias: str) -> str:
    return f"({curr} - {prev}) AS {alias}"


def pct_change_sql(curr: str, prev: str, alias: str) -> str:
    """NULL when previous is 0 or NULL — never divide by zero."""
    return (
        f"CASE WHEN {prev} IS NULL OR {prev} = 0 THEN NULL "
        f"ELSE ROUND(100.0 * ({curr} - {prev}) / {prev}, 2) END AS {alias}"
    )


def period_status_sql(curr: str, prev: str, alias: str = "period_status") -> str:
    """Classify NEW / FULL_DECLINE / CONTINUING for missing-period honesty."""
    return (
        f"CASE "
        f"WHEN ({prev} IS NULL OR {prev} = 0) AND ({curr} IS NOT NULL AND {curr} <> 0) "
        f"THEN 'NEW_NO_PRIOR_BASE' "
        f"WHEN ({curr} IS NULL OR {curr} = 0) AND ({prev} IS NOT NULL AND {prev} <> 0) "
        f"THEN 'FULL_DECLINE_NO_CURRENT' "
        f"ELSE 'CONTINUING' END AS {alias}"
    )


def resolve_change_mode(question_lower: str) -> ChangeMode:
    """
    Percentage vs absolute ranking — semantic, not phrase patches.

    Percentage: fastest / percent / rate / relative growth.
    Absolute: added / absolute / most revenue / largest increase in amount.
    Default for 'grew the most' / 'declined the most' on monetary metrics: absolute
    (business impact); use pct when speed/rate language is present.
    """
    ql = question_lower or ""
    pct_signals = (
        "fastest",
        "percent",
        "percentage",
        "%",
        "rate of",
        "growth rate",
        "relative",
        "proportion",
    )
    abs_signals = (
        "absolute",
        "added the most",
        "add the most",
        "largest increase",
        "largest decrease",
        "most revenue",
        "most profit",
        "most volume",
        "biggest increase in",
        "biggest decrease in",
        "added most",
    )
    if any(s in ql for s in pct_signals):
        return "pct"
    if any(s in ql for s in abs_signals):
        return "absolute"
    # "grew fastest" already covered; bare "grew the most" → absolute for money impact
    if "fast" in ql:
        return "pct"
    return "absolute"


def resolve_growth_metric(question_lower: str, prior_metrics: Optional[list] = None) -> str:
    ql = question_lower or ""
    if any(x in ql for x in ("margin", "gross margin")):
        return "gross_margin_pct"
    if any(x in ql for x in ("asp", "average selling", "unit price", "selling price")):
        return "avg_selling_price"
    if any(x in ql for x in ("quantity", "volume", "qty", "units")):
        return "quantity"
    if any(x in ql for x in ("cogs", "cost of goods", "wavwr")):
        return "cogs"
    if any(x in ql for x in ("gross profit", "gp growth", "gp decline", "profit growth", "profit decline")):
        return "gross_profit"
    if any(x in ql for x in ("invoice count", "invoices")):
        return "invoice_count"
    if any(x in ql for x in ("revenue", "sales")):
        return "revenue"
    if prior_metrics:
        for m in ("revenue", "gross_profit", "gross_margin_pct", "quantity", "avg_selling_price"):
            if m in prior_metrics:
                return m
    return "revenue"


def resolve_direction(question_lower: str) -> Direction:
    ql = question_lower or ""
    decline = (
        "decline",
        "declined",
        "drop",
        "dropped",
        "fell",
        "fall",
        "loser",
        "losers",
        "lost",
        "worsen",
        "deteriorate",
        "decrease",
        "decreased",
        "negative growth",
        "shrunk",
        "shrink",
    )
    if any(s in ql for s in decline):
        return "decline"
    # margin "improvement" is growth of margin
    if "improv" in ql:
        return "growth"
    return "growth"


def resolve_period_grain(question_lower: str) -> str:
    """year (YoY default) | month (MoM) | quarter (QoQ)."""
    ql = question_lower or ""
    if any(
        x in ql
        for x in (
            "month over month",
            "month-over-month",
            "mom",
            "monthly growth",
            "monthly decline",
            "grew month",
            "declined month",
            "by month",
        )
    ) or (
        "month" in ql
        and any(x in ql for x in ("grew", "grow", "growth", "decline", "declined", "increase", "decrease"))
        and "which month" not in ql
    ):
        return "month"
    if any(
        x in ql
        for x in (
            "quarter over quarter",
            "quarter-over-quarter",
            "qoq",
            "quarterly growth",
            "quarterly decline",
            "grew quarter",
            "declined quarter",
            "by quarter",
        )
    ) or (
        "quarter" in ql
        and any(x in ql for x in ("grew", "grow", "growth", "decline", "declined", "increase", "decrease"))
        and "which quarter" not in ql
    ):
        return "quarter"
    return "year"


def wants_product_change(question_lower: str) -> bool:
    """True when question asks for product-level growth/decline ranking."""
    ql = question_lower or ""
    if not ql:
        return False
    # Time-grain margin decline stays on monthly/quarterly trend (R4-1).
    if ("month" in ql or "quarter" in ql) and "margin" in ql and any(
        x in ql for x in ("decline", "improv", "change")
    ):
        return False
    productish = any(
        x in ql
        for x in (
            "product",
            "products",
            "material",
            "materials",
            "sku",
            "skus",
            "item",
            "items",
        )
    ) or ql.startswith("which ") or "who grew" in ql or "who declined" in ql
    changeish = any(
        x in ql
        for x in (
            "grew",
            "grow",
            "growth",
            "growing",
            "grower",
            "growers",
            "decline",
            "declined",
            "declining",
            "increase",
            "increased",
            "decrease",
            "decreased",
            "fell",
            "fall",
            "rose",
            "rise",
            "lost",
            "loser",
            "losers",
            "gainer",
            "gainers",
            "improv",
            "worsen",
            "deteriorate",
            "perform better",
            "performed better",
            "biggest change",
        )
    )
    if productish and changeish:
        return True
    # "Show the biggest growers/losers" without saying product
    if any(x in ql for x in ("grower", "growers", "loser", "losers", "gainer", "gainers")):
        return True
    return False


def order_col_for(metric: str, mode: ChangeMode, direction: Direction) -> Tuple[str, str]:
    """Return (order_column, ASC|DESC)."""
    if metric == "gross_margin_pct":
        col = "margin_change_pp"
    else:
        suffix = "pct" if mode == "pct" else "abs"
        col = f"{metric}_change_{suffix}"
    # Growth → largest positive first (DESC); Decline → most negative first (ASC)
    if direction == "decline":
        return col, "ASC"
    return col, "DESC"
