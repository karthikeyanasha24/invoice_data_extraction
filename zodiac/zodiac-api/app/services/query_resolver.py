"""
Query resolution pipeline: natural language → semantic dictionary → tables/metrics/dimensions → SQL template.
Uses sap_semantic_dictionary.json (entities, joins, metrics, dimensions, templates).
When resolution succeeds, generates SQL without LLM; otherwise returns None for LLM fallback.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SEMANTIC_DICT: Optional[Dict[str, Any]] = None


def load_semantic_dictionary() -> Dict[str, Any]:
    """Load sap_semantic_dictionary.json."""
    global _SEMANTIC_DICT
    if _SEMANTIC_DICT is not None:
        return _SEMANTIC_DICT
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "sap_semantic_dictionary.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _SEMANTIC_DICT = json.load(f)
            return _SEMANTIC_DICT or {}
    except Exception as e:
        logger.debug("query_resolver: could not load sap_semantic_dictionary.json: %s", e)
    _SEMANTIC_DICT = {}
    return {}


def resolve_metric(question: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Match question to a known metric. Returns (metric_key, table, column, aggregation) or None.
    """
    q = (question or "").strip().lower()
    if not q:
        return None
    data = load_semantic_dictionary()
    metrics = data.get("metrics") or {}
    for key, m in metrics.items():
        table = (m.get("table") or "").strip()
        column = (m.get("column") or "").strip()
        agg = (m.get("aggregation") or "SUM").strip().upper()
        aliases = m.get("aliases") or []
        for alias in aliases:
            if alias.lower() in q or q in alias.lower():
                return (key, table, column, agg)
        if key.replace("_", " ").lower() in q:
            return (key, table, column, agg)
    return None


def resolve_dimension(question: str) -> Optional[Tuple[str, str, str, Optional[str], Optional[str], Optional[str], Optional[str]]]:
    """
    Match question to a known dimension. Returns (dim_key, table, column, name_column, name_table, metric_join_key, name_join_key) or None.
    """
    q = (question or "").strip().lower()
    if not q:
        return None
    data = load_semantic_dictionary()
    dimensions = data.get("dimensions") or {}
    # Order: try "by X" first
    by_match = re.search(r"\bby\s+(\w+(?:\s+\w+)?)\b", q)
    dim_phrase = by_match.group(1).strip().lower() if by_match else q
    is_warehouse_context = "warehouse" in q or "stock" in q or "inventory" in q
    # Prefer material_warehouse when question is about warehouse/stock
    if is_warehouse_context and "material" in (dim_phrase + " " + q):
        d = dimensions.get("material_warehouse")
        if d:
            table = (d.get("table") or "").strip()
            column = (d.get("column") or "").strip()
            return ("material_warehouse", table, column, d.get("name_column"), d.get("name_table"), None, None)
    # Prefer material_billing/material_order when question is about revenue/order/invoice
    is_sales_context = "revenue" in q or "order" in q or "invoice" in q or "sales" in q or "billing" in q
    if is_sales_context and "material" in (dim_phrase + " " + q):
        if "order" in q and "invoice" not in q and "revenue" not in q:
            d = dimensions.get("material_order")
            key = "material_order"
        else:
            d = dimensions.get("material_billing")
            key = "material_billing"
        if d:
            table = (d.get("table") or "").strip()
            column = (d.get("column") or "").strip()
            return (key, table, column, d.get("name_column"), d.get("name_table"), None, None)
    for key, d in dimensions.items():
        table = (d.get("table") or "").strip()
        column = (d.get("column") or "").strip()
        name_col = d.get("name_column")
        name_table = d.get("name_table")
        metric_jk = d.get("metric_join_key")
        name_jk = d.get("name_join_key")
        key_lower = key.replace("_", " ").lower()
        if key_lower in dim_phrase or dim_phrase in key_lower or key_lower in q:
            return (key, table, column, name_col, name_table, metric_jk, name_jk)
    # Fallback: check entity names
    entities = data.get("entities") or {}
    for ent_name, ent in entities.items():
        if ent_name in q or f"by {ent_name}" in q:
            pt = ent.get("primary_table") or (ent.get("tables") or [None])[0]
            pk = ent.get("primary_key") or ""
            name_col = ent.get("name_column")
            if pt and pk:
                return (ent_name, pt, pk, name_col, None, None, None)
    return None


def resolve_query(
    question: str,
    available_tables: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve question to metric + dimension and return resolution dict for SQL generation.
    Returns None if no confident resolution.
    available_tables: if provided, resolution tables must be in this list (for schema-driven check).
    """
    q = (question or "").strip().lower()
    if not q:
        return None
    data = load_semantic_dictionary()
    metrics = data.get("metrics") or {}
    dimensions = data.get("dimensions") or {}
    entities = data.get("entities") or {}

    # 1) Resolve metric
    metric_tuple = resolve_metric(question)
    if not metric_tuple:
        metric_tuple = None
    else:
        metric_key, metric_table, metric_column, aggregation = metric_tuple
        if available_tables and metric_table.upper() not in [t.upper() for t in available_tables]:
            metric_tuple = None

    # 2) Resolve dimension (e.g. "by material", "by vendor")
    dim_tuple = resolve_dimension(question)
    if dim_tuple and len(dim_tuple) >= 4:
        dim_key = dim_tuple[0]
        dim_table = dim_tuple[1]
        dim_column = dim_tuple[2]
        name_column = dim_tuple[3]
        name_table = dim_tuple[4] if len(dim_tuple) > 4 else None
        metric_join_key = dim_tuple[5] if len(dim_tuple) > 5 else None
        name_join_key = dim_tuple[6] if len(dim_tuple) > 6 else None
        if available_tables:
            if dim_table.upper() not in [t.upper() for t in available_tables]:
                dim_tuple = None
            elif name_table and name_table.upper() not in [t.upper() for t in available_tables]:
                name_table = None
                dim_tuple = (dim_key, dim_table, dim_column, name_column, None, metric_join_key, name_join_key)
    else:
        dim_tuple = None

    # Build resolution: require at least a metric or a dimension (for "list X by dimension" we need dimension + COUNT)
    tables = []
    if metric_tuple:
        _, mt, mc, agg = metric_tuple
        if mt and mt not in tables:
            tables.append(mt)
    if dim_tuple:
        dt = dim_tuple[1]
        if dt and dt not in tables:
            tables.append(dt)
        if len(dim_tuple) > 4 and dim_tuple[4] and dim_tuple[4] not in tables:
            tables.append(dim_tuple[4])

    if not tables:
        return None

    year_phrases = ("year", "including year", "per year", "by year", "yearly", "trend")
    include_year = any(yp in q for yp in year_phrases)
    if include_year and metric_tuple and metric_tuple[1].upper() == "VBRP" and "VBRK" not in [t.upper() for t in tables]:
        tables.append("VBRK")

    result = {
        "tables": tables,
        "metric_table": metric_tuple[1] if metric_tuple else None,
        "metric_column": metric_tuple[2] if metric_tuple else None,
        "aggregation": metric_tuple[3] if metric_tuple else "SUM",
        "dimension_table": dim_tuple[1] if dim_tuple else None,
        "dimension_column": dim_tuple[2] if dim_tuple else None,
        "dimension_name_column": dim_tuple[3] if dim_tuple else None,
        "dimension_name_table": dim_tuple[4] if dim_tuple and len(dim_tuple) > 4 else None,
        "dimension_metric_join_key": dim_tuple[5] if dim_tuple and len(dim_tuple) > 5 else None,
        "dimension_name_join_key": dim_tuple[6] if dim_tuple and len(dim_tuple) > 6 else None,
        "include_year": include_year,
    }
    return result


def build_sql_from_resolution(
    resolution: Dict[str, Any],
    schema_table_case: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    Build a single SELECT from resolution. Uses template sum_by_dimension or total_metric.
    schema_table_case: optional dict mapping logical name (e.g. LIPS) to actual DB name (e.g. LIPS or lips).
    """
    if not resolution:
        return None
    metric_table = resolution.get("metric_table")
    metric_column = resolution.get("metric_column")
    aggregation = (resolution.get("aggregation") or "SUM").upper()
    dim_table = resolution.get("dimension_table")
    dim_column = resolution.get("dimension_column")
    name_table = resolution.get("dimension_name_table")
    name_column = resolution.get("dimension_name_column")
    metric_join_key = resolution.get("dimension_metric_join_key")
    name_join_key = resolution.get("dimension_name_join_key")

    def _tbl(t: str) -> str:
        if not t:
            return t
        if schema_table_case:
            key = t.upper() if t else ""
            if key in schema_table_case:
                return schema_table_case[key]
        return f'"{t}"' if t and t.isupper() else t

    # Same table for metric and dimension (e.g. LIPS for delivery value by material)
    # If metric table has the dimension column (e.g. EKPO/LIPS/VBRP have matnr), use metric table for GROUP BY
    base_table = metric_table
    if dim_table and dim_column and base_table and dim_table != base_table and not metric_join_key:
        if dim_column == "matnr" and base_table.upper() in ("EKPO", "LIPS", "VBRP"):
            dim_table = base_table
    if metric_table and metric_column:
        if dim_table and dim_column:
            # SUM(metric) GROUP BY dimension
            if dim_table == metric_table and not name_table:
                sql = (
                    f"SELECT {_tbl(dim_table)}.{dim_column} AS dimension, "
                    f"{aggregation}({_tbl(metric_table)}.{metric_column}) AS total "
                    f"FROM {_tbl(metric_table)} "
                    f"GROUP BY {_tbl(dim_table)}.{dim_column} "
                    f"ORDER BY total DESC LIMIT 100"
                )
                return sql
            if dim_table == metric_table and name_table and name_column:
                # Join for name (e.g. material + MAKT.maktx)
                join_key = name_join_key or dim_column
                name_table_key = name_join_key or dim_column
                year_col = ""
                year_group = ""
                if resolution.get("include_year") and metric_table.upper() == "VBRP":
                    tables_upper = [t.upper() for t in (resolution.get("tables") or [])]
                    vbrk = "VBRK" if "VBRK" in tables_upper else None
                    if vbrk:
                        year_col = f", {_tbl(vbrk)}.GJAHR AS year "
                        year_group = f", {_tbl(vbrk)}.GJAHR"
                        sql = (
                            f"SELECT a.{dim_column} AS dimension, b.{name_column} AS name{year_col}, "
                            f"{aggregation}(a.{metric_column}) AS total "
                            f"FROM {_tbl(metric_table)} a "
                            f"LEFT JOIN {_tbl(name_table)} b ON a.{join_key} = b.{name_table_key} "
                            f"LEFT JOIN {_tbl(vbrk)} h ON a.vbeln = h.vbeln "
                            f"GROUP BY a.{dim_column}, b.{name_column}{year_group} "
                            f"ORDER BY total DESC LIMIT 100"
                        )
                        return sql
                sql = (
                    f"SELECT a.{dim_column} AS dimension, b.{name_column} AS name, "
                    f"{aggregation}(a.{metric_column}) AS total "
                    f"FROM {_tbl(metric_table)} a "
                    f"LEFT JOIN {_tbl(name_table)} b ON a.{join_key} = b.{name_table_key} "
                    f"GROUP BY a.{dim_column}, b.{name_column} "
                    f"ORDER BY total DESC LIMIT 100"
                )
                return sql
            if dim_table != metric_table:
                # Different tables: use metric_join_key if provided (e.g. VBRP–VBRK on vbeln)
                join_col = metric_join_key or dim_column
                sql = (
                    f"SELECT {_tbl(dim_table)}.{dim_column} AS dimension, "
                    f"{aggregation}({_tbl(metric_table)}.{metric_column}) AS total "
                    f"FROM {_tbl(metric_table)} "
                    f"LEFT JOIN {_tbl(dim_table)} ON {_tbl(metric_table)}.{join_col} = {_tbl(dim_table)}.{join_col} "
                    f"GROUP BY {_tbl(dim_table)}.{dim_column} "
                    f"ORDER BY total DESC LIMIT 100"
                )
                return sql
        else:
            # Total only
            sql = f"SELECT {aggregation}({_tbl(metric_table)}.{metric_column}) AS total FROM {_tbl(metric_table)} LIMIT 100"
            return sql
    return None


def try_resolve_and_build_sql(
    question: str,
    available_tables: Optional[List[str]] = None,
    schema_table_case: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    One-shot: resolve question and if successful build SQL. Returns SQL string or None (then use LLM).
    """
    res = resolve_query(question, available_tables=available_tables)
    if not res:
        return None
    sql = build_sql_from_resolution(res, schema_table_case=schema_table_case)
    if sql:
        logger.info("query_resolver: template SQL generated for question (first 80 chars): %s", (question or "")[:80])
    return sql


def get_semantic_context_for_prompt() -> str:
    """Return a compact block for the LLM prompt: entities, joins, metrics, and template hints.
    Built dynamically from sap_semantic_dictionary.json."""
    data = load_semantic_dictionary()
    if not data:
        return ""
    lines = ["Semantic dictionary (use for correct table/column/aggregation):"]

    # Entities: entity_name → primary_table (key columns)
    entities = data.get("entities") or {}
    ent_parts = []
    for name, ent in entities.items():
        pt = ent.get("primary_table") or ""
        cols = []
        if ent.get("primary_key"):
            cols.append(ent["primary_key"])
        if ent.get("name_column"):
            cols.append(ent["name_column"])
        if ent.get("value"):
            cols.append(ent["value"])
        if ent.get("quantity"):
            cols.append(ent["quantity"])
        if not cols and ent.get("dimension_columns"):
            cols = list(ent["dimension_columns"][:4])
        ent_parts.append(f"{name}→{pt} ({', '.join(cols) or '—'})")
    if ent_parts:
        lines.append("Entities: " + "; ".join(ent_parts) + ".")

    # Metrics: key → table.column AGG
    metrics = data.get("metrics") or {}
    met_parts = []
    for key, m in metrics.items():
        t = m.get("table") or ""
        c = m.get("column") or ""
        agg = (m.get("aggregation") or "SUM").upper()
        met_parts.append(f"{key}→{t}.{c} {agg}")
    if met_parts:
        lines.append("Metrics: " + "; ".join(met_parts) + ".")

    # Joins: left.right_key = right.right_key
    joins = data.get("joins") or []
    join_parts = []
    for j in joins[:20]:
        lt = j.get("left_table") or ""
        rt = j.get("right_table") or ""
        lk = j.get("left_key") or ""
        rk = j.get("right_key") or ""
        if lt and rt and lk and rk:
            join_parts.append(f"{lt}.{lk}={rt}.{rk}")
    if join_parts:
        lines.append("Joins: " + "; ".join(join_parts) + ".")

    # Templates
    templates = data.get("templates") or {}
    if templates:
        tmpl_names = list(templates.keys())[:5]
        lines.append("Templates: " + ", ".join(tmpl_names) + " — use for 'X by dimension' (sum_by_dimension) or 'total X' (total_metric).")

    return "\n".join(lines)
