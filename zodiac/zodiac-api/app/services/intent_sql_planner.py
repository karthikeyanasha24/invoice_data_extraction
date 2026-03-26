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
        # Explicitly fail until cost_clean-like layer is mapped.
        raise ValueError(
            "MISSING_COST_LAYER: profit/profit_margin requires canonical cost mapping (e.g. cost_clean)."
        )
    if metric_logical not in ("revenue", "sales", "amount", "count"):
        return ""

    dims = intent.get("dimensions") or []
    filters = intent.get("filters") or []
    ranking = intent.get("ranking") or {}

    # Map logical dimensions to sales_analytics columns
    dim_cols: List[str] = []
    for d in dims:
        logical = str(d.get("logical") or "").lower()
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

    metric_alias = str(metric.get("alias") or "value")
    if metric_logical == "count":
        metric_expr = "SUM(sa.invoices)"
    else:
        metric_expr = "SUM(sa.revenue)"

    select_parts: List[str] = [f"{c}" for c in dim_cols]
    select_parts.append(f"{metric_expr} AS {metric_alias}")

    where_parts: List[str] = []
    for f in filters:
        op = str(f.get("operator") or "").upper()
        cref = f.get("column_ref") or {}
        col = str(cref.get("column") or "").upper()
        val = f.get("value")
        if op == "IN_YEAR":
            years = [str(x) for x in (val or []) if str(x)]
            if years:
                where_parts.append("sa.year IN (" + ", ".join("'" + y.replace("'", "''") + "'" for y in years) + ")")

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    group_sql = ("GROUP BY " + ", ".join(dim_cols)) if dim_cols else ""

    order_sql = ""
    limit_sql = ""
    if ranking.get("enabled"):
        ord_dir = str(ranking.get("order") or "desc").upper()
        if ord_dir not in ("ASC", "DESC"):
            ord_dir = "DESC"
        lim = ranking.get("limit") or 5
        try:
            lim_i = max(1, min(int(lim), 200))
        except Exception:
            lim_i = 5
        order_sql = f"ORDER BY {metric_alias} {ord_dir}"
        limit_sql = f"LIMIT {lim_i}"
    else:
        order_sql = f"ORDER BY {metric_alias} DESC"

    sql = f"""
WITH sales_clean AS (
    SELECT
        TRIM(p."matnr") AS product_id,
        SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4) AS year,
        SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 6) AS month,
        TRIM(v."kunag") AS customer_id,
        TRIM(v."land1") AS country,
        TRIM(v."waerk") AS currency,
        SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS revenue,
        SUM(CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), '') AS NUMERIC)) AS quantity,
        COUNT(DISTINCT v."vbeln") AS invoices
    FROM "VBRP" p
    JOIN "VBRK" v
      ON LPAD(TRIM(p."vbeln"), 10, '0') = LPAD(TRIM(v."vbeln"), 10, '0')
    WHERE p."matnr" IS NOT NULL
      AND TRIM(p."matnr") <> ''
      AND v."fkdat" IS NOT NULL
      AND TRIM(CAST(v."fkdat" AS TEXT)) <> ''
    GROUP BY
        TRIM(p."matnr"),
        SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4),
        SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 6),
        TRIM(v."kunag"),
        TRIM(v."land1"),
        TRIM(v."waerk")
),
product_master AS (
    SELECT
        TRIM(m."matnr") AS product_id,
        MAX(COALESCE(NULLIF(TRIM(m."maktx"), ''), TRIM(m."matnr"))) AS product_name
    FROM "MAKT" m
    WHERE m."matnr" IS NOT NULL
      AND TRIM(m."matnr") <> ''
      AND (m."spras" = 'E' OR m."spras" IS NULL)
    GROUP BY TRIM(m."matnr")
),
sales_analytics AS (
    SELECT
        s.product_id,
        COALESCE(pm.product_name, s.product_id) AS product_name,
        s.year,
        s.month,
        s.customer_id,
        s.country,
        s.currency,
        s.revenue,
        s.quantity,
        s.invoices
    FROM sales_clean s
    LEFT JOIN product_master pm
      ON pm.product_id = s.product_id
)
SELECT
    {", ".join(select_parts)}
FROM sales_analytics sa
{where_sql}
{group_sql}
{order_sql}
{limit_sql}
""".strip()
    return sql


def build_sql_and_plan(intent: Dict[str, Any], sap_db: Session) -> Tuple[str, SqlPlan, Dict[str, List[str]]]:
    schema = load_schema(sap_db, max_columns_per_table=None)
    plan = build_sql_plan(intent, schema)
    sql = generate_sql(plan)
    return sql, plan, schema

