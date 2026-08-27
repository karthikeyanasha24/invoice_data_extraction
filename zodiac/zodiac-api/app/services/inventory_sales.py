"""
Governed inventory snapshot ↔ sales activity helpers (R4-3).

Schema-backed only (schema_full.json):

  Inventory value     = SUM(MBEW.SALK3)     grain: material + valuation area (+ valuation type)
  Inventory quantity  = SUM(MBEW.LBKUM)     valuated stock qty (accepted R3 stock_qty)
  Unrestricted qty    = SUM(MARD.LABST)     grain: material + plant + storage location
  Sales revenue       = SUM(VBRP.NETWR)     grain: billing_item (VBRP→VBRK)
  Sales quantity      = SUM(VBRP.FKIMG)
  COGS / GP           = SUM(WAVWR) / NETWR−WAVWR

Inventory is a current snapshot. Sales is historical billing (VBRK.FKDAT).
These are independently aggregated and joined at MATNR (or MATKL / WERKS)
so billing amounts never fan-out through MARD/MBEW.

Not supported (DATA GAP):
  inventory aging (MSEG absent)
  true inventory turnover (COGS / average inventory — no dated snapshots)
  inventory trend (no historical inventory snapshots)
"""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional, Sequence, Tuple

RiskDirection = Literal["high_inv_low_sales", "low_inv_high_sales"]
RankMetric = Literal["stock_value", "stock_qty"]
InvIntent = str

INVENTORY_INTENTS = frozenset(
    {
        "inventory_analysis",
        "inventory_sales_comparison",
        "inventory_risk_analysis",
        "inventory_by_plant",
        "inventory_aging_gap",
        "inventory_turnover_gap",
        "inventory_trend_gap",
    }
)
INVENTORY_GAP_INTENTS = frozenset(
    {
        "inventory_aging_gap",
        "inventory_turnover_gap",
        "inventory_trend_gap",
    }
)

# Snapshot metrics accepted in R3 production.
STOCK_VALUE_FORMULA = "SUM(MBEW.SALK3)"
STOCK_QTY_FORMULA = "SUM(MBEW.LBKUM)"
UNRESTRICTED_QTY_FORMULA = "SUM(MARD.LABST)"

# Grain documentation (actual extract, not SAP textbook defaults).
GRAIN = {
    "MBEW": "material + valuation area (BWKEY) + valuation type (BWTAR). "
            "Material-level comparison SUM(SALK3)/SUM(LBKUM) GROUP BY MATNR.",
    "MARD": "material + plant (WERKS) + storage location (LGORT). "
            "Plant totals SUM(LABST) GROUP BY WERKS or MATNR+WERKS.",
    "VBRP": "billing item (VBELN+POSNR). Monetary facts NETWR/WAVWR/FKIMG.",
    "VBRK": "billing header. Period = FKDAT (YYYYMMDD text). Sold-to KUNAG.",
    "MARA": "material master. Product group = MATKL.",
    "MAKT": "material text. MAKTX / SPRAS.",
}

SNAPSHOT_CAVEAT = (
    "Inventory is a current MBEW/MARD snapshot (stock value = SALK3, "
    "valuated qty = LBKUM, unrestricted qty = MARD.LABST). "
    "It is not synchronized to billing FKDAT. Comparisons are "
    "inventory snapshot vs sales activity — not same-period measurements."
)

AGING_GAP_REASON = (
    "True inventory aging requires material movement history (MSEG), which is "
    "not in this extract. Billing dates, product creation dates, and expiry "
    "dates are not inventory age."
)

TURNOVER_GAP_REASON = (
    "True inventory turnover (COGS / average inventory) needs temporally "
    "aligned inventory snapshots. Only a current MBEW/MARD snapshot exists. "
    "Sales quantity / current stock is not inventory turnover."
)

TREND_GAP_REASON = (
    "Inventory trend needs multiple dated inventory snapshots. MBEW/MARD in "
    "this extract are a current snapshot (LFGJA/LFMON are last-movement "
    "period stamps, not a snapshot series). Historical inventory is not invented."
)

RATIO_DOCS = {
    "sales_qty_to_stock_qty": {
        "formula": "SUM(VBRP.FKIMG) / NULLIF(SUM(MBEW.LBKUM), 0)",
        "grain": "material (independent sales_agg ⋈ inventory_agg on MATNR)",
        "units": "billed quantity per valuated stock quantity",
        "limitations": "Not inventory turnover. Snapshot denominator vs historical billed qty. NULL if stock_qty is 0 or NULL.",
    },
    "inventory_value_to_revenue": {
        "formula": "SUM(MBEW.SALK3) / NULLIF(SUM(VBRP.NETWR), 0)",
        "grain": "material (independent aggregations joined on MATNR)",
        "units": "snapshot stock value per billed revenue",
        "limitations": "Not a P&L ratio and not turnover. NULL if revenue is 0 or NULL.",
    },
}


def wants_inventory_topic(ql: str) -> bool:
    q = ql or ""
    if any(
        x in q
        for x in (
            "inventory",
            "stock value",
            "stock qty",
            "stock quantity",
            "overstock",
            "overstocked",
            "unrestricted stock",
            "slow-moving",
            "fast-moving",
            "slow moving",
            "fast moving",
            "high stock",
            "low stock",
            "highest stock",
            "lowest stock",
        )
    ):
        return True
    return bool(re.search(r"\bstock\b", q) and any(
        x in q for x in ("sales", "revenue", "plant", "warehouse", "product", "high", "low")
    ))


def wants_inventory_aging(ql: str) -> bool:
    q = ql or ""
    if any(
        x in q
        for x in (
            "inventory aging",
            "inventory age",
            "stock aging",
            "age of inventory",
            "aged inventory",
            "aging of inventory",
            "how old is the inventory",
            "how old is this stock",
            "older inventory",
            "which inventory is older",
        )
    ):
        return True
    if any(x in q for x in ("inventory", "stock")) and any(
        x in q for x in ("sitting", "how old", "aging", "age of this")
    ):
        return True
    if "how long" in q and any(x in q for x in ("stock", "inventory")) and not any(
        x in q for x in ("buy", "purchas", "been buying")
    ):
        return True
    return False


def wants_true_inventory_turnover(ql: str) -> bool:
    q = ql or ""
    return any(
        x in q
        for x in (
            "inventory turnover",
            "stock turnover",
            "inventory turns",
            "stock turns",
            "days of inventory",
            "days inventory outstanding",
            "average inventory",
        )
    )


def wants_inventory_trend(ql: str) -> bool:
    q = ql or ""
    if not any(x in q for x in ("inventory", "stock value", "stock qty", "stock quantity")):
        return False
    if any(
        x in q
        for x in (
            "inventory trend",
            "stock trend",
            "inventory over time",
            "inventory by month",
            "inventory by quarter",
            "inventory history",
            "historical inventory",
            "inventory snapshots",
        )
    ):
        return True
    # "inventory in 2004" without sales activity language → unsupported historical snapshot
    if re.search(r"\binventory\b.{0,40}\b(19|20)\d{2}\b", q) or re.search(
        r"\b(19|20)\d{2}\b.{0,40}\binventory\b", q
    ):
        if not any(x in q for x in ("sales", "revenue", "sold", "billed", "versus", " vs ", "compare")):
            return True
    return False


def wants_inventory_vs_sales(ql: str) -> bool:
    q = ql or ""
    if not wants_inventory_topic(q):
        return False
    return any(
        x in q
        for x in (
            "versus sales",
            "vs sales",
            "versus revenue",
            "vs revenue",
            "versus quantity",
            "with sales",
            "with revenue",
            "and sales",
            "and revenue",
            "compared with sales",
            "compared to sales",
            "compare inventory",
            "inventory versus",
            "inventory vs",
            "inventory and sales",
            "sales and inventory",
            "inventory with revenue",
            "inventory with quantity",
            "quantity sold",
        )
    ) or (
        any(x in q for x in ("compare", "versus", " vs "))
        and any(x in q for x in ("sales", "revenue", "sold", "gross profit"))
        and "last year" not in q
        and "previous year" not in q
        and not re.search(r"\b(19|20)\d{2}\b", q)
    )


def wants_inventory_by_plant(ql: str) -> bool:
    q = ql or ""
    if not wants_inventory_topic(q) and "plant" not in q and "warehouse" not in q:
        return False
    return any(
        x in q
        for x in (
            "by plant",
            "by warehouse",
            "at each plant",
            "inventory by plant",
            "stock by plant",
            "which plants",
            "plant inventory",
            "plants hold",
            "warehouse",
        )
    ) and ("plant" in q or "warehouse" in q)


def wants_inventory_by_group(ql: str) -> bool:
    q = ql or ""
    return wants_inventory_topic(q) and any(
        x in q for x in ("product group", "material group", "category")
    )


def resolve_risk_direction(ql: str) -> Optional[RiskDirection]:
    q = ql or ""
    high_inv = any(
        x in q
        for x in (
            "high inventory",
            "highest inventory",
            "high stock",
            "highest stock",
            "overstock",
            "overstocked",
            "slow-moving",
            "slow moving",
            "excess inventory",
            "excess stock",
        )
    )
    low_sales = any(
        x in q
        for x in (
            "low sales",
            "lowest sales",
            "low revenue",
            "slow",
            "relative to inventory",
            "versus sales",
            "vs sales",
            "but low",
            "and low sales",
        )
    )
    low_inv = any(
        x in q
        for x in (
            "low inventory",
            "lowest inventory",
            "low stock",
            "lowest stock",
            "fast-moving",
            "fast moving",
        )
    )
    high_sales = any(
        x in q
        for x in (
            "high sales",
            "highest sales",
            "strong sales",
            "high revenue",
            "fast",
            "but high",
            "and high sales",
        )
    )
    if "relative to inventory" in q and any(x in q for x in ("low sales", "low revenue")):
        return "high_inv_low_sales"
    if "relative to inventory" in q and any(x in q for x in ("high sales", "strong sales")):
        return "low_inv_high_sales"
    if "overstock" in q or "overstocked" in q:
        return "high_inv_low_sales"
    if (high_inv and low_sales) or (high_inv and "low" in q and any(x in q for x in ("sales", "revenue"))):
        return "high_inv_low_sales"
    if (low_inv and high_sales) or (low_inv and "high" in q and any(x in q for x in ("sales", "revenue"))):
        return "low_inv_high_sales"
    if "slow-moving" in q or "slow moving" in q:
        return "high_inv_low_sales"
    if "fast-moving" in q or "fast moving" in q:
        return "low_inv_high_sales"
    return None


def resolve_inventory_rank_metric(ql: str) -> RankMetric:
    q = ql or ""
    if any(x in q for x in ("stock quantity", "stock qty", "quantity on hand", "unrestricted")):
        return "stock_qty"
    if "quantity" in q and "inventory" in q and "sales" not in q and "sold" not in q:
        return "stock_qty"
    return "stock_value"


def resolve_inventory_rank_dir(ql: str) -> str:
    q = ql or ""
    if any(x in q for x in ("lowest", "least", "smallest", "lowest inventory")):
        return "ASC"
    return "DESC"


def resolve_inventory_intent(ql: str) -> Optional[InvIntent]:
    """Map a question to a governed inventory intent, or None if not inventory."""
    q = (ql or "").strip().lower()
    if wants_inventory_aging(q):
        return "inventory_aging_gap"
    if wants_true_inventory_turnover(q):
        return "inventory_turnover_gap"
    if wants_inventory_trend(q):
        return "inventory_trend_gap"
    if not wants_inventory_topic(q) and not (
        ("plant" in q or "warehouse" in q) and any(x in q for x in ("stock", "inventory"))
    ):
        return None
    if wants_inventory_by_plant(q):
        return "inventory_by_plant"
    if resolve_risk_direction(q):
        return "inventory_risk_analysis"
    if wants_inventory_vs_sales(q) or wants_inventory_by_group(q):
        return "inventory_sales_comparison"
    if wants_inventory_topic(q):
        return "inventory_analysis"
    return None


def gap_reason_for_intent(intent: str) -> str:
    return {
        "inventory_aging_gap": AGING_GAP_REASON,
        "inventory_turnover_gap": TURNOVER_GAP_REASON,
        "inventory_trend_gap": TREND_GAP_REASON,
    }.get(intent, SNAPSHOT_CAVEAT)


def availability_sql(stock_expr: str, sales_expr: str, alias: str = "data_availability") -> str:
    return (
        f"CASE "
        f"WHEN {stock_expr} IS NULL AND {sales_expr} IS NULL THEN 'NO_DATA' "
        f"WHEN {stock_expr} IS NULL THEN 'SALES_ONLY' "
        f"WHEN {sales_expr} IS NULL THEN 'INVENTORY_ONLY' "
        f"ELSE 'BOTH' END AS {alias}"
    )


def ratio_sql(numer: str, denom: str, alias: str) -> str:
    """NULL-safe ratio — never divide by zero."""
    return (
        f"CASE WHEN {denom} IS NULL OR {denom} = 0 THEN NULL "
        f"ELSE ROUND(({numer}) / ({denom}), 6) END AS {alias}"
    )


def comparison_label(years: Optional[list] = None) -> str:
    if years:
        ytxt = ", ".join(str(y) for y in years)
        return (
            f"Current inventory snapshot compared with {ytxt} sales activity. "
            "Inventory is not a historical position at those billing dates."
        )
    return (
        "Current inventory snapshot compared with billed sales activity. "
        "These are not same-period synchronized measurements."
    )


def risk_language(direction: RiskDirection) -> Tuple[str, str]:
    """Observed ranking language — not prediction or causal claims."""
    if direction == "high_inv_low_sales":
        return (
            "high_inventory_low_sales",
            "These products have relatively high inventory compared with sales activity "
            "on the current snapshot. This is a ranking, not a stock-out or aging claim.",
        )
    return (
        "low_inventory_high_sales",
        "These products have relatively high sales activity compared with the current "
        "inventory snapshot. This does not predict that stock will run out.",
    )


def compile_inventory_queries(
    *,
    intent: str,
    products: Sequence[str],
    yfilter: str,
    pfilter: str,
    pfilter_b: str,
    pfilter_d: str,
    pfilter_a: str,
    rev: str,
    cogs: str,
    qty: str,
    years: Optional[list],
    rank_metric: str,
    rank_dir: str,
    inventory_grain: str,
    risk_direction: str,
    ql: str,
    limit: int,
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Compile grain-safe inventory SQL. Never FROM vbrp JOIN MBEW/MARD."""
    queries: List[Dict[str, str]] = []
    gaps: List[str] = []
    if intent in INVENTORY_GAP_INTENTS:
        return [], [gap_reason_for_intent(intent)]

    if intent == "inventory_analysis":
        col = rank_metric if rank_metric in {"stock_value", "stock_qty"} else "stock_value"
        direction = rank_dir if rank_dir in {"ASC", "DESC"} else "DESC"
        queries.append({
            "id": "stock_value_by_material",
            "sql": f"""
SELECT
  TRIM(CAST(b."matnr" AS TEXT)) AS product,
  COALESCE(MAX(m."maktx"), TRIM(CAST(b."matnr" AS TEXT))) AS product_name,
  TRIM(CAST(b."bwkey" AS TEXT)) AS valuation_area,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(b."salk3", '0') AS TEXT)), '') AS NUMERIC)) AS stock_value,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(b."lbkum", '0') AS TEXT)), '') AS NUMERIC)) AS stock_qty,
  MAX(CAST(NULLIF(TRIM(CAST(COALESCE(b."stprs", '0') AS TEXT)), '') AS NUMERIC)) AS standard_price
FROM "MBEW" b
LEFT JOIN "MAKT" m ON TRIM(CAST(b."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
  AND (m."spras" = 'E' OR m."spras" IS NULL)
WHERE b."matnr" IS NOT NULL AND TRIM(CAST(b."matnr" AS TEXT)) <> ''
  {pfilter_b}
GROUP BY TRIM(CAST(b."matnr" AS TEXT)), TRIM(CAST(b."bwkey" AS TEXT))
ORDER BY {col} {direction} NULLS LAST
LIMIT {max(limit, 30)}
""".strip(),
        })
        gaps.append(SNAPSHOT_CAVEAT)
        return queries, gaps

    if intent == "inventory_by_plant":
        plant_only = (not products) and ("product" not in (ql or ""))
        if plant_only:
            queries.append({
                "id": "inventory_by_plant",
                "sql": f"""
SELECT
  TRIM(CAST(d."werks" AS TEXT)) AS plant,
  SUM(CAST(NULLIF(TRIM(CAST(d."labst" AS TEXT)), '') AS NUMERIC)) AS unrestricted_stock_qty,
  COUNT(DISTINCT TRIM(CAST(d."matnr" AS TEXT))) AS material_count,
  COUNT(DISTINCT TRIM(CAST(d."lgort" AS TEXT))) AS storage_location_count
FROM "MARD" d
WHERE d."matnr" IS NOT NULL AND TRIM(CAST(d."matnr" AS TEXT)) <> ''
  AND d."werks" IS NOT NULL AND TRIM(CAST(d."werks" AS TEXT)) <> ''
  {pfilter_d}
GROUP BY TRIM(CAST(d."werks" AS TEXT))
ORDER BY unrestricted_stock_qty DESC NULLS LAST
LIMIT {max(limit, 30)}
""".strip(),
            })
        else:
            queries.append({
                "id": "inventory_by_plant",
                "sql": f"""
SELECT
  TRIM(CAST(d."werks" AS TEXT)) AS plant,
  TRIM(CAST(d."matnr" AS TEXT)) AS product,
  COALESCE(MAX(m."maktx"), TRIM(CAST(d."matnr" AS TEXT))) AS product_name,
  TRIM(CAST(d."lgort" AS TEXT)) AS storage_location,
  SUM(CAST(NULLIF(TRIM(CAST(d."labst" AS TEXT)), '') AS NUMERIC)) AS unrestricted_stock_qty
FROM "MARD" d
LEFT JOIN "MAKT" m ON TRIM(CAST(d."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
  AND (m."spras" = 'E' OR m."spras" IS NULL)
WHERE d."matnr" IS NOT NULL AND TRIM(CAST(d."matnr" AS TEXT)) <> ''
  AND d."werks" IS NOT NULL AND TRIM(CAST(d."werks" AS TEXT)) <> ''
  {pfilter_d}
GROUP BY TRIM(CAST(d."werks" AS TEXT)), TRIM(CAST(d."matnr" AS TEXT)), TRIM(CAST(d."lgort" AS TEXT))
ORDER BY unrestricted_stock_qty DESC NULLS LAST
LIMIT {max(limit, 40)}
""".strip(),
            })
        gaps.append(
            "Plant is MARD.WERKS (plant code). T001W is not in this extract. "
            "Quantity is unrestricted stock (LABST). Inventory is not customer-owned or region-owned."
        )
        return queries, gaps

    group_grain = inventory_grain == "product_group"
    inv_key = (
        "COALESCE(NULLIF(TRIM(CAST(a.\"matkl\" AS TEXT)), ''), 'Unknown')"
        if group_grain
        else "TRIM(CAST(b.\"matnr\" AS TEXT))"
    )
    sales_key = (
        "COALESCE(NULLIF(TRIM(CAST(a.\"matkl\" AS TEXT)), ''), 'Unknown')"
        if group_grain
        else "TRIM(CAST(v.\"matnr\" AS TEXT))"
    )
    inv_join_mara = (
        'LEFT JOIN "MARA" a ON TRIM(CAST(b."matnr" AS TEXT)) = TRIM(CAST(a."matnr" AS TEXT))'
        if group_grain
        else ""
    )
    sales_join_mara = (
        'LEFT JOIN "MARA" a ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(a."matnr" AS TEXT))'
        if group_grain
        else ""
    )
    name_select_inv = (
        f"{inv_key} AS product_group"
        if group_grain
        else f'{inv_key} AS product,\n    COALESCE(MAX(m."maktx"), {inv_key}) AS product_name'
    )
    name_select_sales = (
        f'{sales_key} AS product_group,\n    MAX(vk."waerk") AS currency'
        if group_grain
        else (
            f'{sales_key} AS product,\n    COALESCE(MAX(m."maktx"), {sales_key}) AS product_name,'
            '\n    MAX(vk."waerk") AS currency'
        )
    )
    join_on = "i.product_group = s.product_group" if group_grain else "i.product = s.product"
    coalesced_key = (
        "COALESCE(i.product_group, s.product_group) AS product_group"
        if group_grain
        else (
            "COALESCE(i.product, s.product) AS product,\n    "
            "COALESCE(i.product_name, s.product_name) AS product_name"
        )
    )
    makt_inv = (
        ""
        if group_grain
        else (
            'LEFT JOIN "MAKT" m ON TRIM(CAST(b."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))'
            " AND (m.\"spras\" = 'E' OR m.\"spras\" IS NULL)"
        )
    )
    makt_sales = (
        ""
        if group_grain
        else (
            'LEFT JOIN "MAKT" m ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))'
            " AND (m.\"spras\" = 'E' OR m.\"spras\" IS NULL)"
        )
    )
    inv_where_extra = pfilter_b
    extra_with = ""
    extra_select = ""
    order_expr = "COALESCE(stock_value, 0) DESC"
    from_final = "joined"
    if intent == "inventory_risk_analysis":
        extra_with = """,
ranked AS (
  SELECT
    j.*,
    PERCENT_RANK() OVER (ORDER BY COALESCE(j.stock_value, 0)) AS inv_value_pct,
    PERCENT_RANK() OVER (ORDER BY COALESCE(j.revenue, 0)) AS sales_rev_pct,
    PERCENT_RANK() OVER (ORDER BY COALESCE(j.stock_qty, 0)) AS inv_qty_pct,
    PERCENT_RANK() OVER (ORDER BY COALESCE(j.billed_qty, 0)) AS sales_qty_pct,
    (
      PERCENT_RANK() OVER (ORDER BY COALESCE(j.stock_value, 0))
      - PERCENT_RANK() OVER (ORDER BY COALESCE(j.revenue, 0))
    ) AS overstock_score,
    (
      PERCENT_RANK() OVER (ORDER BY COALESCE(j.revenue, 0))
      - PERCENT_RANK() OVER (ORDER BY COALESCE(j.stock_value, 0))
    ) AS undersupply_score
  FROM joined j
)"""
        extra_select = ""
        from_final = "ranked r"
        order_expr = (
            "undersupply_score DESC"
            if risk_direction == "low_inv_high_sales"
            else "overstock_score DESC"
        )
    select_star = "r.*" if "ranked r" in from_final else "*"
    key_col = "product_group" if group_grain else "product"
    key_ref = f"r.{key_col}" if "ranked r" in from_final else key_col
    sql = f"""
WITH inventory_agg AS (
  SELECT
    {name_select_inv},
    SUM(CAST(NULLIF(TRIM(CAST(b."salk3" AS TEXT)), '') AS NUMERIC)) AS stock_value,
    SUM(CAST(NULLIF(TRIM(CAST(b."lbkum" AS TEXT)), '') AS NUMERIC)) AS stock_qty
  FROM "MBEW" b
  {inv_join_mara}
  {makt_inv}
  WHERE b."matnr" IS NOT NULL AND TRIM(CAST(b."matnr" AS TEXT)) <> ''
    {inv_where_extra}
  GROUP BY {inv_key}
),
sales_agg AS (
  SELECT
    {name_select_sales},
    SUM({rev}) AS revenue,
    SUM({cogs}) AS cogs,
    SUM({rev}) - SUM({cogs}) AS gross_profit,
    CASE WHEN SUM({rev}) > 0 THEN
      ROUND(100.0 * (SUM({rev}) - SUM({cogs})) / SUM({rev}), 2)
    ELSE NULL END AS gross_margin_pct,
    SUM({qty}) AS billed_qty,
    CASE WHEN SUM({qty}) > 0 THEN ROUND(SUM({rev}) / SUM({qty}), 4) ELSE NULL END AS avg_selling_price
  FROM "vbrp" v
  JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
  {sales_join_mara}
  {makt_sales}
  WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
    AND {rev} IS NOT NULL
    {yfilter}
    {pfilter}
  GROUP BY {sales_key}
),
joined AS (
  SELECT
    {coalesced_key},
    s.currency,
    i.stock_value,
    i.stock_qty,
    s.revenue,
    s.cogs,
    s.gross_profit,
    s.gross_margin_pct,
    s.billed_qty,
    s.avg_selling_price,
    {ratio_sql("s.billed_qty", "i.stock_qty", "sales_qty_to_stock_qty")},
    {ratio_sql("i.stock_value", "s.revenue", "inventory_value_to_revenue")},
    {availability_sql("i.stock_value", "s.revenue")}
  FROM inventory_agg i
  FULL OUTER JOIN sales_agg s ON {join_on}
)
{extra_with}
SELECT {select_star}{extra_select}
FROM {from_final}
WHERE COALESCE(CAST({key_ref} AS TEXT), '') <> ''
ORDER BY {order_expr} NULLS LAST
LIMIT {max(limit, 30)}
""".strip()
    queries.append({"id": intent, "sql": sql})
    gaps.append(comparison_label(years))
    if intent == "inventory_risk_analysis":
        gaps.append(risk_language(risk_direction or "high_inv_low_sales")[1])
    gaps.append(
        "Ratios are snapshot-vs-activity (not inventory turnover). "
        "NULL when the denominator is 0 or missing."
    )
    return queries, gaps

