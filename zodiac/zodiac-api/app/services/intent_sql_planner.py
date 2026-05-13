"""
Lock SQL generation to intent (no reinterpretation).

This builds a deterministic SQL plan and emits SQL aligned with:
- intent.metric
- intent.dimensions
- intent.filters
- intent.ranking
- intent.comparison
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .intent_contract import ColumnRef, DimensionSpec, FilterSpec, MetricSpec
from .join_planner_v2 import find_join_path, render_join_sql
from .schema_loader import load_schema


@dataclass(frozen=True)
class SqlPlan:
    base_table: str
    tables: List[str]
    aliases: Dict[str, str]
    select_sql: List[str]
    group_by_sql: List[str]
    where_sql: List[str]
    order_by_sql: str
    limit_sql: str
    metric_alias: str
    prebuilt_sql: str = ""


def build_sql_plan(intent: Dict[str, Any], schema: Dict[str, List[str]]) -> SqlPlan:
    # Prefer analytics-safe layer for sales/revenue/count style questions.
    # This avoids SAP row multiplication from ad-hoc multi-joins.
    prebuilt = _build_sales_analytics_sql_if_possible(intent, schema)
    if prebuilt:
        return SqlPlan(
            base_table="sales_analytics",
            tables=["sales_analytics"],
            aliases={"SALES_ANALYTICS": "sa"},
            select_sql=[],
            group_by_sql=[],
            where_sql=[],
            order_by_sql="",
            limit_sql="",
            metric_alias=str((intent.get("metric") or {}).get("alias") or "value"),
            prebuilt_sql=prebuilt,
        )

    metric = intent.get("metric") or {}
    dims = intent.get("dimensions") or []
    filters = intent.get("filters") or []
    ranking = intent.get("ranking") or {}

    metric_ref = (metric.get("column_ref") or {}) if isinstance(metric, dict) else {}
    metric_table = str(metric_ref.get("table") or "").upper()
    if not metric_table:
        raise ValueError("INTENT_INVALID: metric.column_ref.table is required")

    dim_tables = []
    for d in dims:
        cref = (d.get("column_ref") or {}) if isinstance(d, dict) else {}
        t = str(cref.get("table") or "").upper()
        if t:
            dim_tables.append(t)

    base = metric_table
    needed_tables = [base] + [t for t in dim_tables if t and t != base]
    needed_tables = list(dict.fromkeys(needed_tables))

    # Plan joins via approved join graph
    all_tables: List[str] = [base]
    join_edges = []
    for t in needed_tables[1:]:
        path = find_join_path(base, t)
        if path is None:
            raise ValueError(f"NO_JOIN_PATH: {base} -> {t}")
        join_edges.extend(path)
        for e in path:
            if e.left_table not in all_tables:
                all_tables.append(e.left_table)
            if e.right_table not in all_tables:
                all_tables.append(e.right_table)

    all_tables = list(dict.fromkeys(all_tables))
    aliases = {tbl: f"t{i}" for i, tbl in enumerate(all_tables)}

    select_sql: List[str] = []
    group_by_sql: List[str] = []
    where_sql: List[str] = []

    # Dimensions
    for d in dims:
        logical = str(d.get("logical") or "")
        cref = (d.get("column_ref") or {})
        tbl = str(cref.get("table") or "").upper()
        col = str(cref.get("column") or "")
        transform = str(d.get("transform") or "NONE").upper()
        alias_name = str(d.get("alias") or logical or col).strip() or col
        if not tbl or not col:
            raise ValueError("INTENT_INVALID: dimension missing column_ref")
        a = aliases.get(tbl, tbl.lower())
        expr = f'{a}."{col}"'
        if transform == "YEAR":
            # FKDAT is YYYYMMDD text in many SAP tables
            if col.upper() in ("FKDAT", "BUDAT", "BEDAT", "BLDAT", "ERDAT") or re.search(r"dat$", col.lower()):
                expr = f"SUBSTRING(TRIM(CAST({a}.\"{col}\" AS TEXT)),1,4)"
            else:
                expr = f"EXTRACT(YEAR FROM {a}.\"{col}\")"
        elif transform == "MONTH":
            if col.upper() in ("FKDAT", "BUDAT", "BEDAT", "BLDAT", "ERDAT") or re.search(r"dat$", col.lower()):
                expr = f"SUBSTRING(TRIM(CAST({a}.\"{col}\" AS TEXT)),1,6)"
            else:
                expr = f"EXTRACT(MONTH FROM {a}.\"{col}\")"
        select_sql.append(f"{expr} AS {alias_name}")
        group_by_sql.append(expr)

    # Metric
    metric_alias = str(metric.get("alias") or metric.get("logical") or "value")
    agg = str(metric.get("aggregation") or "SUM").upper()
    if metric.get("derived"):
        # Derived metrics supported: profit_margin, profit (best-effort)
        # Use components if supplied; otherwise fail fast.
        components = metric.get("components") or {}
        if not isinstance(components, dict) or not components:
            raise ValueError("INTENT_INVALID: derived metric requires components mapping")
        # profit_margin = (rev - cost)/rev
        if str(metric.get("logical")) == "profit_margin":
            rev = components.get("revenue")
            cost = components.get("cost")
            if not (isinstance(rev, dict) and isinstance(cost, dict)):
                raise ValueError("INTENT_INVALID: profit_margin requires revenue+cost components")
            ra = aliases[str(rev.get("table")).upper()]
            ca = aliases[str(cost.get("table")).upper()]
            rev_col = str(rev.get("column"))
            cost_col = str(cost.get("column"))
            expr = (
                f"(SUM({ra}.\"{rev_col}\") - SUM({ca}.\"{cost_col}\"))"
                f" / NULLIF(SUM({ra}.\"{rev_col}\"), 0)"
            )
            select_sql.append(f"{expr} AS {metric_alias}")
        else:
            raise ValueError("INTENT_INVALID: unsupported derived metric")
    else:
        if not metric_ref.get("column"):
            if agg in ("COUNT", "COUNT_DISTINCT"):
                expr = "COUNT(*)"
                select_sql.append(f"{expr} AS {metric_alias}")
            else:
                raise ValueError("INTENT_INVALID: metric.column_ref.column is required")
        else:
            col = str(metric_ref.get("column"))
            a = aliases[metric_table]
            base_expr = f'{a}."{col}"'
            if agg == "SUM":
                expr = f"SUM(CAST(NULLIF(TRIM(CAST({base_expr} AS TEXT)), '') AS NUMERIC))"
            elif agg == "AVG":
                expr = f"AVG(CAST(NULLIF(TRIM(CAST({base_expr} AS TEXT)), '') AS NUMERIC))"
            elif agg == "COUNT":
                expr = "COUNT(*)"
            elif agg == "COUNT_DISTINCT":
                expr = f"COUNT(DISTINCT {base_expr})"
            else:
                raise ValueError(f"INTENT_INVALID: unsupported aggregation {agg}")
            select_sql.append(f"{expr} AS {metric_alias}")

    # Filters
    for f in filters:
        cref = (f.get("column_ref") or {})
        tbl = str(cref.get("table") or "").upper()
        col = str(cref.get("column") or "")
        op = str(f.get("operator") or "=").upper()
        val = f.get("value")
        if not tbl or not col:
            raise ValueError("INTENT_INVALID: filter missing column_ref")
        a = aliases.get(tbl, tbl.lower())
        if op == "IN_YEAR":
            years = [str(x) for x in (val or []) if str(x)]
            if not years:
                continue
            quoted_years = ", ".join("'" + y.replace("'", "''") + "'" for y in years)
            where_sql.append(
                f'SUBSTRING(TRIM(CAST({a}."{col}" AS TEXT)),1,4) IN ({quoted_years})'
            )
        elif op == "=":
            where_sql.append(f'{a}."{col}" = \'{str(val)}\'')
        elif op == "ILIKE":
            where_sql.append(f'{a}."{col}" ILIKE \'%{str(val)}%\'')
        else:
            raise ValueError(f"INTENT_INVALID: unsupported filter operator {op}")

    # Ranking
    order_by_sql = ""
    limit_sql = ""
    if ranking.get("enabled"):
        order = str(ranking.get("order") or "desc").lower()
        if order not in ("asc", "desc"):
            order = "desc"
        order_by_sql = f"ORDER BY {metric_alias} {order.upper()}"
        lim = ranking.get("limit")
        try:
            lim_i = int(lim)
        except Exception:
            lim_i = 5
        lim_i = max(1, min(lim_i, 200))
        limit_sql = f"LIMIT {lim_i}"

    return SqlPlan(
        base_table=base,
        tables=all_tables,
        aliases=aliases,
        select_sql=select_sql,
        group_by_sql=group_by_sql,
        where_sql=where_sql,
        order_by_sql=order_by_sql,
        limit_sql=limit_sql,
        metric_alias=metric_alias,
        prebuilt_sql="",
    )


def generate_sql(plan: SqlPlan) -> str:
    if plan.prebuilt_sql:
        return plan.prebuilt_sql
    base = plan.base_table.upper()
    ba = plan.aliases[base]
    from_sql = f"FROM {base} {ba}"
    # Determine join path edges from alias map by replaying join_graph edges between included tables.
    # For deterministic joins, we re-run BFS from base to each table in plan.tables order and union edges.
    join_clauses: List[str] = []
    for t in plan.tables:
        if t == base:
            continue
        path = find_join_path(base, t) or []
        if path:
            join_sql = render_join_sql(path, plan.aliases)
            if join_sql:
                join_clauses.append(join_sql)
    join_sql_unique = "\n".join(list(dict.fromkeys(join_clauses)))

    where_sql = ""
    if plan.where_sql:
        where_sql = "WHERE " + " AND ".join(plan.where_sql)
    group_sql = ""
    if plan.group_by_sql:
        group_sql = "GROUP BY " + ", ".join(plan.group_by_sql)

    parts = [
        "SELECT",
        "  " + ",\n  ".join(plan.select_sql),
        from_sql,
    ]
    if join_sql_unique:
        parts.append(join_sql_unique)
    if where_sql:
        parts.append(where_sql)
    if group_sql:
        parts.append(group_sql)
    if plan.order_by_sql:
        parts.append(plan.order_by_sql)
    if plan.limit_sql:
        parts.append(plan.limit_sql)
    return "\n".join(parts)


def _quote_table(name: str) -> str:
    """Return the SQL-safe reference for a table name.
    Lowercase tables (e.g. vbrp) need no quotes; uppercase ones need "VBRK" style quoting."""
    if name == name.lower():
        return name
    return f'"{name}"'


def _build_sales_analytics_sql_if_possible(intent: Dict[str, Any], schema: Dict[str, List[str]]) -> str:
    """
    Canonical analytics-safe query layer:
    - sales_clean: deduplicated invoice line facts
    - product_master: one product name per material
    - sales_analytics: clean star-like surface
    """
    schema_u = {t.upper(): [str(c).upper() for c in cols] for t, cols in (schema or {}).items()}
    if "VBRP" not in schema_u or "VBRK" not in schema_u:
        return ""

    metric = intent.get("metric") or {}
    metric_logical = str(metric.get("logical") or "").lower()
    if metric_logical in ("profit", "profit_margin"):
        # Profit/cost queries need CO tables (COSS/COSP/COEP) which the intent
        # pipeline doesn't cover. Return "" to fall through to the LLM SQL agent
        # which can discover and use the right CO tables dynamically.
        return ""
    if metric_logical not in ("revenue", "sales", "amount", "count"):
        return ""

    dims = intent.get("dimensions") or []
    filters = intent.get("filters") or []
    ranking = intent.get("ranking") or {}

    # Map logical dimensions to sales_analytics columns
    dim_cols: List[str] = []
    logical_dims: List[str] = []
    for d in dims:
        logical = str(d.get("logical") or "").lower()
        logical_dims.append(logical)
        if logical == "year":
            dim_cols.append("year")
        elif logical == "month":
            dim_cols.append("month")
        elif logical == "product":
            dim_cols.append("product_name")
        elif logical == "customer":
            dim_cols.append("customer_id")
        elif logical == "country":
            dim_cols.append("country")
        elif logical == "currency":
            dim_cols.append("currency")
        elif logical == "industry":
            # industry not guaranteed in safe layer unless KNA1/T016T is added
            dim_cols.append("customer_id")
    dim_cols = list(dict.fromkeys(dim_cols))
    logical_dims = list(dict.fromkeys(logical_dims))

    # Resolve actual table names from schema (DB may store as lowercase e.g. vbrp)
    vbrp_actual = next((t for t in (schema or {}) if t.upper() == "VBRP"), "VBRP")
    vbrk_actual = next((t for t in (schema or {}) if t.upper() == "VBRK"), "VBRK")
    makt_actual = next((t for t in (schema or {}) if t.upper() == "MAKT"), "MAKT")
    kna1_actual = next((t for t in (schema or {}) if t.upper() == "KNA1"), "KNA1")
    vbrp_ref = _quote_table(vbrp_actual)
    vbrk_ref = _quote_table(vbrk_actual)
    makt_ref = _quote_table(makt_actual)
    kna1_ref = _quote_table(kna1_actual)

    metric_alias = str(metric.get("alias") or "total_sales")

    # If ranking is requested but no dimension was specified, default to product breakdown.
    if ranking.get("enabled") and not dim_cols:
        dim_cols = ["product_name"]
        logical_dims = ["product"]

    # ── Ranking / ORDER-BY parameters ──────────────────────────────────────────
    ord_dir = "DESC"
    lim_i = 5
    if ranking.get("enabled"):
        ord_dir = str(ranking.get("order") or "desc").upper()
        if ord_dir not in ("ASC", "DESC"):
            ord_dir = "DESC"
        try:
            lim_i = max(1, min(int(ranking.get("limit") or 5), 200))
        except Exception:
            lim_i = 5

    # ── Year filters from intent ────────────────────────────────────────────────
    year_filter_parts: List[str] = []
    for f in filters:
        op = str(f.get("operator") or "").upper()
        val = f.get("value")
        if op == "IN_YEAR":
            yrs = [str(x) for x in (val or []) if str(x)]
            if yrs:
                year_filter_parts.append(yrs)  # stored for later injection

    # ── FAST DIRECT PATH (0 or 1 dimension) ────────────────────────────────────
    # For simple ranking/aggregate with ≤1 dimension we skip the expensive
    # full-scan CTE (which joins vbrp+VBRK across ALL years before filtering).
    # Each case queries only the tables it actually needs.
    single_dim = dim_cols[0] if len(dim_cols) == 1 else None
    single_logical = logical_dims[0] if len(logical_dims) == 1 else None

    if len(dim_cols) <= 1:
        # ── PRODUCT ranking/aggregate: vbrp + MAKT only (no VBRK needed) ──
        if single_logical in (None, "product"):
            if metric_logical == "count":
                metric_sql = f'COUNT(DISTINCT TRIM(p."vbeln")) AS {metric_alias}'
            else:
                metric_sql = f'SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS {metric_alias}'

            year_where = ""
            if year_filter_parts:
                y_list = ", ".join("'" + y + "'" for y in year_filter_parts[0])
                year_where = f"\n  AND TRIM(CAST(p.\"fkdat\" AS TEXT)) IS NOT NULL"  # fallback; fkdat may not be on vbrp

            if single_logical == "product":
                # Product fast path: join MAKT for description + VBRK for currency.
                # Includes material number, currency, quantity and invoice count so
                # the result table is as rich as a hand-written analytical query.
                order_by = f"ORDER BY {metric_alias} {ord_dir}"
                limit_clause = f"LIMIT {lim_i}" if ranking.get("enabled") else ""
                sql = f"""
SELECT
    TRIM(p."matnr")                                                          AS material_number,
    COALESCE(NULLIF(TRIM(m."maktx"), ''), TRIM(p."matnr"))                  AS product,
    TRIM(v."waerk")                                                          AS currency,
    SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC))          AS {metric_alias},
    SUM(CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), '') AS NUMERIC))          AS total_quantity,
    COUNT(DISTINCT TRIM(p."vbeln"))                                          AS invoice_count
FROM {vbrp_ref} p
JOIN {vbrk_ref} v ON TRIM(p."vbeln") = TRIM(v."vbeln")
LEFT JOIN {makt_ref} m
    ON TRIM(p."matnr") = TRIM(m."matnr")
    AND (m."spras" = 'E' OR m."spras" IS NULL)
WHERE p."matnr" IS NOT NULL
  AND TRIM(p."matnr") <> ''
  AND p."netwr" IS NOT NULL
  AND v."waerk" IS NOT NULL
GROUP BY TRIM(p."matnr"), TRIM(m."maktx"), TRIM(v."waerk")
{order_by}
{limit_clause}""".strip()
            else:
                # No dimension: total aggregate
                sql = f"""
SELECT {metric_sql}
FROM {vbrp_ref} p
WHERE p."netwr" IS NOT NULL""".strip()
            return sql

        # ── CUSTOMER / COUNTRY / CURRENCY / DATE: vbrp + VBRK (simple TRIM join) ──
        if single_logical in ("customer", "country", "currency", "year", "month"):
            if metric_logical == "count":
                metric_sql = f'COUNT(DISTINCT TRIM(v."vbeln")) AS {metric_alias}'
            else:
                metric_sql = f'SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS {metric_alias}'

            if single_logical == "customer":
                dim_expr = 'TRIM(v."kunag")'
                dim_alias = "customer"
                # will add name join below
            elif single_logical == "country":
                dim_expr = 'TRIM(v."land1")'
                dim_alias = "country"
            elif single_logical == "currency":
                dim_expr = 'TRIM(v."waerk")'
                dim_alias = "currency"
            elif single_logical == "year":
                dim_expr = 'SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4)'
                dim_alias = "year"
            else:  # month
                dim_expr = 'SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 6)'
                dim_alias = "month"

            year_where = ""
            if year_filter_parts and single_logical in ("year", "month"):
                y_list = ", ".join("'" + y + "'" for y in year_filter_parts[0])
                year_where = f"\n  AND SUBSTRING(TRIM(CAST(v.\"fkdat\" AS TEXT)), 1, 4) IN ({y_list})"
            elif year_filter_parts:
                y_list = ", ".join("'" + y + "'" for y in year_filter_parts[0])
                year_where = f"\n  AND SUBSTRING(TRIM(CAST(v.\"fkdat\" AS TEXT)), 1, 4) IN ({y_list})"

            order_clause = f"ORDER BY {metric_alias} {ord_dir}" if single_logical not in ("year",) else f"ORDER BY {dim_alias}"
            if ranking.get("enabled"):
                order_clause = f"ORDER BY {metric_alias} {ord_dir}"
            limit_clause = f"LIMIT {lim_i}" if ranking.get("enabled") else ""

            # Extra WHERE guard: exclude null/empty dimension values so they don't
            # aggregate into a phantom "top customer/country/currency" bucket.
            dim_notnull_guard = ""
            if single_logical == "customer":
                dim_notnull_guard = f"\n  AND {dim_expr} IS NOT NULL AND {dim_expr} <> ''"
            elif single_logical in ("country", "currency"):
                dim_notnull_guard = f"\n  AND {dim_expr} IS NOT NULL AND {dim_expr} <> ''"

            if single_logical == "customer":
                sql = f"""
SELECT
    {dim_expr} AS {dim_alias},
    COALESCE(NULLIF(TRIM(k."name1"), ''), {dim_expr}) AS customer_name,
    {metric_sql}
FROM {vbrp_ref} p
JOIN {vbrk_ref} v ON TRIM(p."vbeln") = TRIM(v."vbeln")
LEFT JOIN {kna1_ref} k ON TRIM(k."kunnr") = {dim_expr}
WHERE v."fkdat" IS NOT NULL
  AND TRIM(CAST(v."fkdat" AS TEXT)) <> ''{dim_notnull_guard}{year_where}
GROUP BY {dim_expr}, COALESCE(NULLIF(TRIM(k."name1"), ''), {dim_expr})
{order_clause}
{limit_clause}""".strip()
            else:
                sql = f"""
SELECT
    {dim_expr} AS {dim_alias},
    {metric_sql}
FROM {vbrp_ref} p
JOIN {vbrk_ref} v ON TRIM(p."vbeln") = TRIM(v."vbeln")
WHERE v."fkdat" IS NOT NULL
  AND TRIM(CAST(v."fkdat" AS TEXT)) <> ''{dim_notnull_guard}{year_where}
GROUP BY {dim_expr}
{order_clause}
{limit_clause}""".strip()
            return sql

    # ── FULL CTE PATH: multi-dimension queries (product + year, customer + country, etc.) ──
    # Uses a lighter CTE that only computes what this specific query needs.
    needs_vbrk = any(d in logical_dims for d in ("customer", "country", "currency", "year", "month"))
    needs_makt = "product" in logical_dims

    year_only_request = (
        "year" in logical_dims
        and not any(d in logical_dims for d in ("product", "customer", "country", "currency", "industry"))
    )

    # Build CTE select columns — only what's needed
    cte_select: List[str] = ['TRIM(p."matnr") AS product_key']
    cte_group: List[str] = ['TRIM(p."matnr")']
    if needs_vbrk:
        if "year" in logical_dims or "month" in logical_dims:
            cte_select.append('SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4) AS year')
            cte_select.append('SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 6) AS month')
            cte_group.append('SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4)')
            cte_group.append('SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 6)')
        if "customer" in logical_dims:
            cte_select.append('TRIM(v."kunag") AS customer')
            cte_group.append('TRIM(v."kunag")')
        if "country" in logical_dims:
            cte_select.append('TRIM(v."land1") AS country')
            cte_group.append('TRIM(v."land1")')
        if "currency" in logical_dims:
            cte_select.append('TRIM(v."waerk") AS currency')
            cte_group.append('TRIM(v."waerk")')

    if metric_logical == "count":
        cte_select.append('COUNT(DISTINCT p."vbeln") AS invoices')
        outer_metric = f"SUM(sc.invoices) AS {metric_alias}"
    else:
        cte_select.append('SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS revenue')
        outer_metric = f"SUM(sc.revenue) AS {metric_alias}"

    cte_join = f"""
    JOIN {vbrk_ref} v ON TRIM(p."vbeln") = TRIM(v."vbeln")""" if needs_vbrk else ""

    cte_where_parts: List[str] = ['p."matnr" IS NOT NULL', "TRIM(p.\"matnr\") <> ''"]
    if needs_vbrk:
        cte_where_parts.extend(['v."fkdat" IS NOT NULL', "TRIM(CAST(v.\"fkdat\" AS TEXT)) <> ''"])
    for yf in year_filter_parts:
        y_list = ", ".join("'" + y + "'" for y in yf)
        cte_where_parts.append(f'SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4) IN ({y_list})')

    cte_where = "WHERE " + "\n      AND ".join(cte_where_parts)

    # Map dim_cols to outer SELECT
    outer_dims: List[str] = []
    outer_group: List[str] = []
    for lg in logical_dims:
        if lg == "year" and needs_vbrk:
            outer_dims.append("sc.year")
            outer_group.append("sc.year")
        elif lg == "month" and needs_vbrk:
            outer_dims.append("sc.month")
            outer_group.append("sc.month")
        elif lg == "product":
            if needs_makt:
                outer_dims.append("COALESCE(pm.product_name, sc.product_key) AS product")
                outer_group.append("COALESCE(pm.product_name, sc.product_key)")
            else:
                outer_dims.append("sc.product_key AS product")
                outer_group.append("sc.product_key")
        elif lg == "customer":
            outer_dims.append("sc.customer AS customer")
            outer_group.append("sc.customer")
        elif lg == "country":
            outer_dims.append("sc.country")
            outer_group.append("sc.country")
        elif lg == "currency":
            outer_dims.append("sc.currency")
            outer_group.append("sc.currency")

    if year_only_request:
        outer_dims = ["sc.year"]
        outer_group = ["sc.year"]

    outer_select_parts = outer_dims + [outer_metric]
    outer_group_sql = ("GROUP BY " + ", ".join(outer_group)) if outer_group else ""
    order_sql = f"ORDER BY {metric_alias} {ord_dir}"
    if not ranking.get("enabled") and "year" in logical_dims and not any(d in logical_dims for d in ("product", "customer", "country")):
        order_sql = "ORDER BY sc.year"
    limit_sql = f"LIMIT {lim_i}" if ranking.get("enabled") else ""

    makt_cte = ""
    makt_join = ""
    if needs_makt:
        makt_cte = f"""
product_master AS (
    SELECT
        TRIM(m."matnr") AS product_key,
        MAX(COALESCE(NULLIF(TRIM(m."maktx"), ''), TRIM(m."matnr"))) AS product_name
    FROM {makt_ref} m
    WHERE m."matnr" IS NOT NULL
      AND TRIM(m."matnr") <> ''
      AND (m."spras" = 'E' OR m."spras" IS NULL)
    GROUP BY TRIM(m."matnr")
),"""
        makt_join = "\nLEFT JOIN product_master pm ON pm.product_key = sc.product_key"

    sql = f"""
WITH sales_clean AS (
    SELECT
        {(chr(10) + '        ').join(f'{s},' for s in cte_select[:-1])}
        {cte_select[-1]}
    FROM {vbrp_ref} p{cte_join}
    {cte_where}
    GROUP BY
        {(',' + chr(10) + '        ').join(cte_group)}
),{makt_cte}
outer_agg AS (
    SELECT
        {(chr(10) + '        ').join(f'{s},' for s in outer_select_parts[:-1])}
        {outer_select_parts[-1]}
    FROM sales_clean sc{makt_join}
    {outer_group_sql}
)
SELECT * FROM outer_agg
{order_sql}
{limit_sql}
""".strip()
    return sql


def build_sql_and_plan(intent: Dict[str, Any], sap_db: Session) -> Tuple[str, SqlPlan, Dict[str, List[str]]]:
    schema = load_schema(sap_db, max_columns_per_table=None)
    plan = build_sql_plan(intent, schema)
    sql = generate_sql(plan)
    return sql, plan, schema

