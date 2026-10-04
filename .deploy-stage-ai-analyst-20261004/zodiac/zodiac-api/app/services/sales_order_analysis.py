"""Governed sales-order SQL (VBAK/VBAP/VBEP). Additive — does not replace billing R3/R4."""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

from ..data_catalog.format_semantics import column_semantics_for_rows
from ..data_catalog.physical import has_column, has_table
from ..data_catalog.source_selector import SourceSpec
from .sql_grain_guard import sql_has_unsafe_monetary_fanout

logger = logging.getLogger("zodiac-api.sales-order-analysis")

ExecuteSql = Callable[[Any, str], List[Dict[str, Any]]]


def _num(alias: str, col: str) -> str:
    return f"CAST(NULLIF(TRIM(CAST({alias}.\"{col}\" AS TEXT)), '') AS NUMERIC)"


def _year_pred(alias: str, col: str, years: List[str]) -> str:
    if not years:
        return "TRUE"
    ys = ", ".join("'" + y.replace("'", "") + "'" for y in years)
    return (
        f"TRIM(CAST({alias}.\"{col}\" AS TEXT)) <> '' "
        f"AND SUBSTRING(TRIM(CAST({alias}.\"{col}\" AS TEXT)), 1, 4) IN ({ys})"
    )


def _date_col() -> str:
    if has_column("VBAK", "audat"):
        return "audat"
    return "erdat"


def _chart(rows: List[Dict[str, Any]], title: str) -> List[Dict[str, Any]]:
    if not rows:
        return []
    label_key = next(
        (k for k in ("customer_name", "product_name", "country", "industry", "year", "vbeln", "matnr") if k in rows[0]),
        None,
    )
    value_key = next(
        (k for k in ("order_value", "order_count", "order_qty", "wmeng", "netwr") if k in rows[0]),
        None,
    )
    if not label_key or not value_key:
        return []
    return [{
        "type": "bar",
        "title": title[:120],
        "description": "Sales-order metric (not billed revenue)",
        "data": [
            {"name": str(r.get(label_key) or ""), "value": float(r.get(value_key) or 0)}
            for r in rows[:15]
        ],
    }]


def _payload(
    question: str,
    spec: SourceSpec,
    sql: str,
    rows: List[Dict[str, Any]],
    summary: str,
    findings: List[str],
    grain: str,
    definition: str,
    elapsed_ms: int,
    gaps: Optional[List[str]] = None,
) -> Dict[str, Any]:
    rows = rows or []
    return {
        "sql": sql,
        "rowCount": len(rows),
        "data": rows[:200],
        "summary": summary,
        "keyFindings": findings[:6],
        "charts": _chart(rows, summary.split("\n", 1)[0][:80]),
        "answer_status": "SUCCESS",
        "query_plan": {
            "analytical_context": {
                "deep_analysis": True,
                "intent": "sales_order_analysis",
                "domain": "sales",
                "metric": spec.metric,
                "primary_metric": spec.metric,
                "dimensions": spec.dimensions,
                "tables": spec.tables,
                "joins": ["VBAK.vbeln = VBAP.vbeln"] if "VBAP" in spec.tables and "VBAK" in spec.tables else [],
                "grain": grain,
                "fact_grain": grain,
                "aggregation": definition,
                "period_label": ", ".join(spec.years) if spec.years else "All sales orders in the extract",
                "data_gaps": gaps or [],
            },
            "deep_analysis": True,
            "intent": "sales_order_analysis",
            "domain": "sales",
            "tables": spec.tables,
        },
        "column_semantics": column_semantics_for_rows(rows),
        "suggested_followups": [
            "Show sales orders from 2004.",
            "Which customers had the highest sales-order value?",
            "Show billed invoices instead.",
        ],
        "meta": {
            "deep_analysis": True,
            "domain": "sales",
            "tables": spec.tables,
            "pipeline_ms": elapsed_ms,
            "query_source": "sales_order_catalog",
        },
        "pipeline": "sales_order_catalog",
        "sql_generation_method": "catalog_governed",
        "llm_calls": 0,
    }


def try_sales_order_analysis(
    question: str,
    spec: SourceSpec,
    db: Any,
    execute_sql: ExecuteSql,
) -> Optional[Dict[str, Any]]:
    t0 = time.perf_counter()
    if not has_table("VBAK"):
        return None
    ql = (question or "").lower()
    date_col = _date_col()
    years = spec.years or []

    try:
        if spec.named_table == "VBEP" or "schedul" in ql:
            if not has_table("VBEP"):
                return None
            sql = f'''
SELECT e."vbeln" AS vbeln, e."posnr" AS posnr, e."etenr" AS etenr,
       e."edatu" AS schedule_date, {_num("e", "wmeng") if has_column("VBEP", "wmeng") else "NULL"} AS wmeng
FROM "VBEP" e
WHERE TRIM(CAST(e."vbeln" AS TEXT)) <> ''
ORDER BY e."edatu" DESC NULLS LAST
LIMIT 50
'''
            rows = execute_sql(db, sql)
            if sql_has_unsafe_monetary_fanout(sql):
                return None
            ms = int((time.perf_counter() - t0) * 1000)
            return _payload(
                question, spec, sql, rows,
                "**Sales schedule lines**\n\nSchedule-line data from VBEP (this extract does not include VBED).",
                [f"{len(rows)} schedule-line rows"],
                "schedule line (VBELN+POSNR+ETENR)",
                "VBEP listing — quantities not summed across fan-out",
                ms,
            )

        if spec.named_table == "VBAK" and not spec.dimensions and "highest" not in ql and "how many" not in ql:
            sql = f'''
SELECT v."vbeln" AS vbeln, v."kunnr" AS customer, v."audat" AS order_date,
       v."auart" AS order_type, {_num("v", "netwr") if has_column("VBAK", "netwr") else "NULL"} AS netwr,
       v."waerk" AS currency
FROM "VBAK" v
WHERE TRIM(CAST(v."vbeln" AS TEXT)) <> ''
ORDER BY v."audat" DESC NULLS LAST
LIMIT 50
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _payload(
                question, spec, sql, rows,
                "**Sales document headers (VBAK)**\n\nHeader-grain listing. This is not billed revenue.",
                [f"{len(rows)} sales documents (display capped at 50)"],
                "sales document header",
                "VBAK listing",
                ms,
            )

        if spec.named_table == "VBAP" and not spec.dimensions:
            sql = f'''
SELECT p."vbeln" AS vbeln, p."posnr" AS posnr, p."matnr" AS matnr, p."arktx" AS description,
       {_num("p", "kwmeng") if has_column("VBAP", "kwmeng") else "NULL"} AS order_qty,
       {_num("p", "netwr") if has_column("VBAP", "netwr") else "NULL"} AS order_value,
       p."waerk" AS currency
FROM "VBAP" p
WHERE TRIM(CAST(p."vbeln" AS TEXT)) <> ''
LIMIT 50
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _payload(
                question, spec, sql, rows,
                "**Sales document items (VBAP)**\n\nItem-grain listing. This is not billed revenue.",
                [f"{len(rows)} sales items (display capped at 50)"],
                "sales document item",
                "VBAP listing",
                ms,
            )

        if spec.metric == "sales_order_count" or re.search(r"\b(how many|number of)\s+sales orders\b", ql):
            year_sql = _year_pred("v", date_col, years)
            sql = f'''
SELECT COUNT(DISTINCT v."vbeln") AS order_count
FROM "VBAK" v
WHERE TRIM(CAST(v."vbeln" AS TEXT)) <> '' AND {year_sql}
'''
            if len(years) >= 2:
                sql = f'''
SELECT SUBSTRING(TRIM(CAST(v."{date_col}" AS TEXT)), 1, 4) AS year,
       COUNT(DISTINCT v."vbeln") AS order_count
FROM "VBAK" v
WHERE TRIM(CAST(v."vbeln" AS TEXT)) <> '' AND {year_sql}
GROUP BY 1
ORDER BY 1
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            n = rows[0].get("order_count") if rows else 0
            return _payload(
                question, spec, sql, rows,
                f"**Sales order count**\n\n{n} sales documents in VBAK"
                + (f" for {', '.join(years)}" if years else "")
                + ".\n\nThis is not invoice count.",
                [f"order_count={n}"],
                "sales document header",
                "COUNT(DISTINCT VBAK.VBELN)",
                ms,
            )

        if len(years) >= 2 and spec.metric != "sales_order_count" and not spec.dimensions:
            year_sql = _year_pred("v", date_col, years)
            sql = f'''
SELECT SUBSTRING(TRIM(CAST(v."{date_col}" AS TEXT)), 1, 4) AS year,
       COUNT(DISTINCT v."vbeln") AS order_count,
       SUM({_num("p", "netwr")}) AS order_value
FROM "VBAP" p
JOIN "VBAK" v ON TRIM(p."vbeln") = TRIM(v."vbeln")
WHERE TRIM(CAST(p."vbeln" AS TEXT)) <> '' AND {year_sql}
GROUP BY 1
ORDER BY 1
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _payload(
                question, spec, sql, rows,
                f"**Sales orders {years[0]} vs {years[1]}**\n\nOrder count (VBAK) and order value (VBAP.NETWR). Not billed revenue.",
                [f"{len(rows)} years"],
                "sales document item aggregated by year",
                "COUNT(DISTINCT VBAK.VBELN) and SUM(VBAP.NETWR) by AUDAT year",
                ms,
            )

        # Ranked / grouped order value at item grain, then N:1 masters.
        year_sql = _year_pred("v", date_col, years)
        join_c = ""
        join_i = ""
        join_m = ""
        if has_table("KNA1") and has_column("VBAK", "kunnr"):
            join_c = 'LEFT JOIN "KNA1" k ON TRIM(v."kunnr") = TRIM(k."kunnr")'
        if "industry" in spec.dimensions and has_table("T016T"):
            join_i = 'LEFT JOIN "T016T" t ON TRIM(k."brsch") = TRIM(t."brsch")'
        if (spec.dimensions == ["product"] or "product" in spec.dimensions) and has_table("MAKT"):
            join_m = "LEFT JOIN \"MAKT\" m ON TRIM(p.\"matnr\") = TRIM(m.\"matnr\") AND m.\"spras\" = 'E'"
            if not has_column("MAKT", "spras"):
                join_m = 'LEFT JOIN "MAKT" m ON TRIM(p."matnr") = TRIM(m."matnr")'

        if spec.dimensions == ["product"] or (
            "product" in spec.dimensions and "customer" not in spec.dimensions
        ):
            sql = f'''
SELECT p."matnr" AS matnr,
       MAX(p."arktx") AS product_name,
       SUM({_num("p", "netwr")}) AS order_value,
       SUM({_num("p", "kwmeng") if has_column("VBAP", "kwmeng") else "0"}) AS order_qty
FROM "VBAP" p
JOIN "VBAK" v ON TRIM(p."vbeln") = TRIM(v."vbeln")
{join_m}
WHERE TRIM(CAST(p."vbeln" AS TEXT)) <> '' AND {year_sql}
GROUP BY p."matnr"
ORDER BY order_value DESC NULLS LAST
LIMIT 20
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _payload(
                question, spec, sql, rows,
                "**Highest sales-order value by product**\n\nSource: VBAP.NETWR (sales-order items), not VBRP billed revenue.",
                [f"{len(rows)} products"],
                "sales document item, then product",
                "SUM(VBAP.NETWR) grouped by MATNR",
                ms,
            )

        # customer / country / industry (default ranking)
        select_dims = [
            'v."kunnr" AS customer',
            'k."name1" AS customer_name' if join_c else "NULL AS customer_name",
        ]
        group_dims = ['v."kunnr"', 'k."name1"'] if join_c else ['v."kunnr"']
        if "country" in spec.dimensions and join_c and has_column("KNA1", "land1"):
            select_dims.append('k."land1" AS country')
            group_dims.append('k."land1"')
        if "industry" in spec.dimensions and join_c and has_column("KNA1", "brsch"):
            select_dims.append('k."brsch" AS industry_key')
            group_dims.append('k."brsch"')
            if join_i:
                select_dims.append('MAX(t."brtxt") AS industry')
        select_sql = ",\n       ".join(select_dims)
        group_sql = ", ".join(group_dims)
        sql = f'''
SELECT {select_sql},
       SUM({_num("p", "netwr")}) AS order_value
FROM "VBAP" p
JOIN "VBAK" v ON TRIM(p."vbeln") = TRIM(v."vbeln")
{join_c}
{join_i}
WHERE TRIM(CAST(p."vbeln" AS TEXT)) <> '' AND {year_sql}
GROUP BY {group_sql}
ORDER BY order_value DESC NULLS LAST
LIMIT 20
'''
        if sql_has_unsafe_monetary_fanout(sql):
            logger.info("sales_order sql rejected by grain guard")
            return None
        rows = execute_sql(db, sql)
        ms = int((time.perf_counter() - t0) * 1000)
        dim_label = ", ".join(spec.dimensions) if spec.dimensions else "customer"
        return _payload(
            question, spec, sql, rows,
            f"**Sales-order value by {dim_label}**\n\nSource: VBAK + VBAP. This is not billed invoice revenue.",
            [f"{len(rows)} groups"],
            "sales document item, then " + dim_label,
            "SUM(VBAP.NETWR); N:1 customer master only",
            ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("sales_order_analysis failed: %s", type(exc).__name__)
        return None
