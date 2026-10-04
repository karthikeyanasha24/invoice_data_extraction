"""Governed domain overviews (purchasing, production, master data). No LLM SQL."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from ..data_catalog.format_semantics import column_semantics_for_rows
from ..data_catalog.knowledge import resolve_knowledge
from ..data_catalog.physical import has_column, has_table
from ..data_catalog.source_selector import SourceSpec
from .sql_grain_guard import sql_has_unsafe_monetary_fanout

logger = logging.getLogger("zodiac-api.domain-overview")

ExecuteSql = Callable[[Any, str], List[Dict[str, Any]]]


def _num(alias: str, col: str) -> str:
    return f"CAST(NULLIF(TRIM(CAST({alias}.\"{col}\" AS TEXT)), '') AS NUMERIC)"


def _wrap(
    spec: SourceSpec,
    sql: str,
    rows: List[Dict[str, Any]],
    summary: str,
    grain: str,
    definition: str,
    elapsed_ms: int,
    intent: str,
) -> Dict[str, Any]:
    rows = rows or []
    charts: List[Dict[str, Any]] = []
    if rows:
        label = next((k for k in ("vendor_name", "product", "aufnr", "name1", "matnr") if k in rows[0]), None)
        value = next((k for k in ("purchase_value", "production_qty", "order_count") if k in rows[0]), None)
        if label and value:
            charts.append({
                "type": "bar",
                "title": summary.split("\n", 1)[0][:80],
                "data": [{"name": str(r.get(label) or ""), "value": float(r.get(value) or 0)} for r in rows[:15]],
            })
    return {
        "sql": sql,
        "rowCount": len(rows),
        "data": rows[:200],
        "summary": summary,
        "keyFindings": [f"{len(rows)} rows"],
        "charts": charts,
        "answer_status": "SUCCESS",
        "query_plan": {
            "analytical_context": {
                "deep_analysis": True,
                "intent": intent,
                "domain": spec.domain,
                "metric": spec.metric,
                "tables": spec.tables,
                "grain": grain,
                "fact_grain": grain,
                "aggregation": definition,
                "period_label": ", ".join(spec.years) if spec.years else "Extract snapshot",
                "data_gaps": [],
            },
            "intent": intent,
            "domain": spec.domain,
            "tables": spec.tables,
        },
        "column_semantics": column_semantics_for_rows(rows),
        "meta": {"domain": spec.domain, "tables": spec.tables, "pipeline_ms": elapsed_ms, "query_source": "domain_catalog"},
        "pipeline": "domain_catalog",
        "sql_generation_method": "catalog_governed",
        "llm_calls": 0,
    }


def knowledge_payload(question: str, spec: SourceSpec) -> Dict[str, Any]:
    info = resolve_knowledge(spec.named_table or question, allow_external=False)
    exists = bool(info.get("exists"))
    meaning = info.get("meaning") or ""
    if spec.named_table == "VBED" or (spec.reason == "table_absent"):
        summary = spec.clarification_message or (
            f"{spec.named_table} is not available in the connected migrated dataset."
        )
        status = "CANNOT_ANSWER"
    elif exists:
        summary = (
            f"**{info.get('term')}** — {meaning}\n\n"
            f"Domain: {info.get('domain')}. Grain: {info.get('grain')}. "
            "Meaning is from the governed catalog; columns are from the migrated schema."
        )
        status = "SUCCESS"
    else:
        summary = f"{spec.named_table or 'That table'} is not available in the connected migrated dataset."
        status = "CANNOT_ANSWER"
    return {
        "sql": "",
        "rowCount": 0,
        "data": [],
        "summary": summary,
        "answer": summary,
        "keyFindings": [info.get("evidence") or spec.reason],
        "charts": [],
        "answer_status": status,
        "query_plan": {
            "analytical_context": {
                "intent": "schema_knowledge",
                "domain": spec.domain,
                "tables": spec.tables,
                "grain": "not applicable",
                "data_gaps": [] if exists else [summary],
            }
        },
        "meta": {"query_source": "catalog_knowledge", "verified": exists},
        "pipeline": "catalog_knowledge",
        "llm_calls": 0,
    }


def try_domain_overview(
    question: str,
    spec: SourceSpec,
    db: Any,
    execute_sql: ExecuteSql,
) -> Optional[Dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        if spec.domain == "purchasing" and has_table("EKPO"):
            if has_table("EKKO") and has_table("LFA1"):
                sql = f'''
SELECT h."lifnr" AS vendor, v."name1" AS vendor_name,
       SUM({_num("p", "netwr")}) AS purchase_value
FROM "EKPO" p
JOIN "EKKO" h ON TRIM(p."ebeln") = TRIM(h."ebeln")
LEFT JOIN "LFA1" v ON TRIM(h."lifnr") = TRIM(v."lifnr")
WHERE TRIM(CAST(p."ebeln" AS TEXT)) <> ''
GROUP BY h."lifnr", v."name1"
ORDER BY purchase_value DESC NULLS LAST
LIMIT 20
'''
            else:
                sql = f'''
SELECT SUM({_num("p", "netwr")}) AS purchase_value
FROM "EKPO" p
WHERE TRIM(CAST(p."ebeln" AS TEXT)) <> ''
'''
            if sql_has_unsafe_monetary_fanout(sql):
                return None
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _wrap(
                spec, sql, rows,
                "**Purchasing**\n\nPO item net value (EKPO.NETWR). This is not billed sales and not invoice COGS.",
                "purchase-order item, then vendor",
                "SUM(EKPO.NETWR)",
                ms,
                "purchasing_overview",
            )

        if spec.domain == "production" and has_table("AFKO"):
            qty = _num("a", "gamng") if has_column("AFKO", "gamng") else "NULL"
            mat = 'a."plnbez" AS product' if has_column("AFKO", "plnbez") else "NULL AS product"
            sql = f'''
SELECT a."aufnr" AS aufnr, {mat}, {qty} AS production_qty
FROM "AFKO" a
WHERE TRIM(CAST(a."aufnr" AS TEXT)) <> ''
ORDER BY production_qty DESC NULLS LAST
LIMIT 20
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _wrap(
                spec, sql, rows,
                "**Production**\n\nProduction order headers (AFKO). This is not sales quantity.",
                "production order header",
                "AFKO.GAMNG (where populated)",
                ms,
                "production_overview",
            )

        if spec.domain == "customer" and has_table("KNA1"):
            sql = '''
SELECT k."kunnr" AS customer, k."name1" AS name1, k."land1" AS country, k."brsch" AS industry_key
FROM "KNA1" k
WHERE TRIM(CAST(k."kunnr" AS TEXT)) <> ''
LIMIT 50
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _wrap(
                spec, sql, rows,
                "**Customer master (KNA1)**\n\nMaster data listing, not a sales ranking.",
                "customer",
                "KNA1 listing",
                ms,
                "customer_master",
            )

        if spec.domain == "product" and has_table("MARA"):
            join_t = 'LEFT JOIN "MAKT" t ON TRIM(m."matnr") = TRIM(t."matnr")' if has_table("MAKT") else ""
            name = 't."maktx" AS description' if has_table("MAKT") else "NULL AS description"
            sql = f'''
SELECT m."matnr" AS matnr, {name}
FROM "MARA" m
{join_t}
WHERE TRIM(CAST(m."matnr" AS TEXT)) <> ''
LIMIT 50
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _wrap(
                spec, sql, rows,
                "**Product/material master (MARA)**\n\nMaster data listing, not billed sales.",
                "material",
                "MARA listing",
                ms,
                "product_master",
            )

        if spec.domain == "vendor" and has_table("LFA1"):
            sql = '''
SELECT v."lifnr" AS vendor, v."name1" AS name1, v."land1" AS country
FROM "LFA1" v
WHERE TRIM(CAST(v."lifnr" AS TEXT)) <> ''
LIMIT 50
'''
            rows = execute_sql(db, sql)
            ms = int((time.perf_counter() - t0) * 1000)
            return _wrap(
                spec, sql, rows,
                "**Vendor master (LFA1)**\n\nMaster data listing, not purchase-order spend.",
                "vendor",
                "LFA1 listing",
                ms,
                "vendor_master",
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("domain_overview failed: %s", type(exc).__name__)
        return None
    return None
