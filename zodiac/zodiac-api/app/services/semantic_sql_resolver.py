"""
Semantic SQL resolver: maps natural-language questions to tables, metrics, dimensions,
and SQL using the SAP semantic dictionary (entities, joins, metrics, templates).
Reduces "No SQL could be generated" by giving the agent explicit entity → table → column → aggregation.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DICTIONARY: Optional[Dict[str, Any]] = None


def load_semantic_dictionary() -> Dict[str, Any]:
    """Load sap_semantic_dictionary.json (entities, joins, metrics, templates)."""
    global _DICTIONARY
    if _DICTIONARY is not None:
        return _DICTIONARY
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "sap_semantic_dictionary.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _DICTIONARY = json.load(f)
            return _DICTIONARY or {}
    except Exception as e:
        logger.debug("semantic_sql_resolver: could not load dictionary: %s", e)
    _DICTIONARY = {}
    return {}


def _quote_identifier(name: str) -> str:
    """Quote identifier for PostgreSQL if it contains lower case or is reserved."""
    if not name:
        return name
    if name.upper() == name and name.isalpha():
        return f'"{name}"'
    return name


def _detect_metric_phrase(question: str) -> Optional[Tuple[str, str]]:
    """Return (metric_key, remainder) if a known metric phrase is found, else None."""
    q = (question or "").strip().lower()
    data = load_semantic_dictionary()
    phrases = data.get("metric_phrases") or {}
    for phrase, metric_key in sorted(phrases.items(), key=lambda x: -len(x[0])):
        if phrase in q:
            remainder = q.replace(phrase, "", 1).strip()
            return (metric_key, remainder)
    return None


def _detect_dimension(remainder: str) -> Optional[Dict[str, Any]]:
    """From remainder (e.g. 'by material', 'by vendor'), return dimension alias info."""
    remainder = (remainder or "").strip().lower()
    data = load_semantic_dictionary()
    aliases = data.get("dimension_aliases") or {}
    by_match = re.search(r"\bby\s+(\w+)", remainder)
    if by_match:
        dim_word = by_match.group(1).strip()
        if dim_word in aliases:
            return aliases[dim_word]
        if dim_word + "s" in aliases:
            return aliases[dim_word + "s"]
    for alias, info in aliases.items():
        if alias in remainder and ("by " in remainder or "per " in remainder):
            return info
    return None


def _get_metric_spec(metric_key: str) -> Optional[Dict[str, Any]]:
    """Return { table, column, aggregation } for a metric key."""
    data = load_semantic_dictionary()
    metrics = data.get("metrics") or {}
    return metrics.get(metric_key)


def _get_join_for_tables(left: str, right: str) -> Optional[Dict[str, str]]:
    """Return join spec { left_key, right_key } if a join exists between left and right."""
    data = load_semantic_dictionary()
    for j in data.get("joins") or []:
        if (j.get("left_table") == left and j.get("right_table") == right) or (
            j.get("left_table") == right and j.get("right_table") == left
        ):
            if j.get("left_table") == left:
                return {"left_key": j["left_key"], "right_key": j["right_key"]}
            return {"left_key": j["right_key"], "right_key": j["left_key"]}
    return None


def resolve_to_sql(
    question: str,
    available_tables: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Resolve a natural-language question to a concrete SQL query using the semantic dictionary.
    Step 1: Detect metric phrase (e.g. "delivery value" → LIPS.netwr SUM)
    Step 2: Detect dimension (e.g. "by material" → matnr, MAKT for name)
    Step 3: Look up template and fill table, column, aggregation, dimension
    Step 4: Add JOIN for name table when dimension has name_column in another table
    Returns SQL string or None if resolution fails. Caller should validate and run.
    """
    if not question or not question.strip():
        return None
    data = load_semantic_dictionary()
    if not data:
        return None

    available_set = None
    if available_tables:
        available_set = {t.upper() for t in available_tables}

    def table_available(t: str) -> bool:
        if available_set is None:
            return True
        return (t or "").upper() in available_set

    # Step 1: detect metric
    metric_result = _detect_metric_phrase(question)
    if not metric_result:
        return None
    metric_key, remainder = metric_result
    metric_spec = _get_metric_spec(metric_key)
    if not metric_spec or not table_available(metric_spec.get("table", "")):
        return None

    table = metric_spec["table"]
    metric_column = metric_spec["column"]
    aggregation = metric_spec.get("aggregation", "SUM")

    # Step 2: detect dimension
    dimension_info = _detect_dimension(remainder) if remainder else None

    # Step 3 & 4: build SQL from template
    q = (question or "").strip().lower()
    templates = data.get("templates") or {}

    if dimension_info:
        dim_table = dimension_info.get("table") or table
        dim_column = dimension_info.get("dimension_column") or dimension_info.get("column")
        name_table = dimension_info.get("name_table")
        name_column = dimension_info.get("name_column")
        dimension_key = dimension_info.get("column") or dim_column  # key for join

        # Domain-aware: when metric table has the dimension column (e.g. EKPO.matnr for material),
        # use metric table for dimension so purchasing queries work (purchase by material -> EKPO+MAKT)
        if dim_column and table_available(table):
            if table.upper() in ("EKPO", "LIPS", "VBRP", "RESB") and dim_column.lower() == "matnr":
                dim_table = table
        if not table_available(dim_table):
            dim_table = table
        if dim_column and dim_table == table and table_available(table):
            # Same table: SUM(metric) GROUP BY dimension
            tpl = templates.get("sum_by_dimension") or "SELECT {dimension_column}, {aggregation}({metric_column}) AS total FROM {table} GROUP BY {dimension_column} ORDER BY total DESC LIMIT 100"
            sql = tpl.format(
                dimension_column=dim_column,
                dimension_name=dim_column,
                aggregation=aggregation,
                metric_column=metric_column,
                table=_quote_identifier(table),
            )
            return sql

        if name_table and name_column and table_available(name_table) and _get_join_for_tables(table, name_table):
            join_spec = _get_join_for_tables(table, name_table)
            lk, rk = join_spec["left_key"], join_spec["right_key"]
            # JOIN name table for labels (e.g. LIPS + MAKT for material name)
            sql = (
                f'SELECT t.{_quote_identifier(dim_column) if dim_column else _quote_identifier(dimension_key)} AS dimension, '
                f'n.{_quote_identifier(name_column)} AS name, '
                f'{aggregation}(t.{_quote_identifier(metric_column)}) AS total '
                f'FROM {_quote_identifier(table)} t '
                f'LEFT JOIN {_quote_identifier(name_table)} n ON t.{_quote_identifier(lk)} = n.{_quote_identifier(rk)}'
            )
            if name_table == "MAKT":
                sql += " AND (n.spras = 'E' OR n.spras IS NULL)"
            sql += f" GROUP BY t.{_quote_identifier(dim_column) if dim_column else _quote_identifier(dimension_key)}, n.{_quote_identifier(name_column)} ORDER BY total DESC LIMIT 100"
            return sql

        if dim_column:
            tpl = templates.get("sum_by_dimension") or "SELECT {dimension_column}, {aggregation}({metric_column}) AS total FROM {table} GROUP BY {dimension_column} ORDER BY total DESC LIMIT 100"
            sql = tpl.format(
                dimension_column=dim_column,
                dimension_name=dim_column,
                aggregation=aggregation,
                metric_column=metric_column,
                table=_quote_identifier(table),
            )
            return sql

    # No dimension: total only
    tpl = templates.get("total_metric") or "SELECT {aggregation}({metric_column}) AS total FROM {table} LIMIT 1"
    sql = tpl.format(
        aggregation=aggregation,
        metric_column=metric_column,
        table=_quote_identifier(table),
    )
    return sql


def resolve_count_by_dimension(question: str, available_tables: Optional[List[str]] = None) -> Optional[str]:
    """
    Fallback: when no metric phrase is found, try "COUNT by dimension" (e.g. "vendors by country").
    """
    if not question or not question.strip():
        return None
    data = load_semantic_dictionary()
    dimension_info = _detect_dimension((question or "").strip().lower())
    if not dimension_info:
        return None
    dim_table = dimension_info.get("table")
    dim_column = dimension_info.get("dimension_column") or dimension_info.get("column")
    if not dim_table or not dim_column:
        return None
    available_set = None
    if available_tables:
        available_set = {t.upper() for t in available_tables}
    if available_set and dim_table.upper() not in available_set:
        return None
    templates = data.get("templates") or {}
    tpl = templates.get("count_by_dimension") or "SELECT {dimension_column} AS {dimension_name}, COUNT(*) AS cnt FROM {table} GROUP BY {dimension_column} ORDER BY cnt DESC LIMIT 100"
    return tpl.format(
        dimension_column=dim_column,
        dimension_name=dim_column,
        table=_quote_identifier(dim_table),
    )


def semantic_fast_path_matches_question(question: str, sql: str) -> bool:
    """
    Reject semantic-dictionary fast-path SQL when it answers a different question than the user asked.

    Primary guard: do not return a revenue **by industry** query unless the user asked for
    industry / sector / brsch (or industry table by name).
    """
    q = (question or "").lower()
    s = (sql or "").lower()
    if not s.strip():
        return False

    industry_ask = any(
        x in q
        for x in (
            "industry",
            "industries",
            "sector",
            "sectors",
            "brsch",
            "t016",
            "business sector",
        )
    )
    looks_like_industry_sql = (
        "t016t" in s
        or " as industry" in s
        or " as industry," in s
        or "brtxt" in s
        or (" group by " in s and "brsch" in s)
    )
    if looks_like_industry_sql and not industry_ask:
        logger.info(
            "semantic_sql_resolver: rejecting fast-path SQL — industry breakdown without industry intent",
        )
        return False

    return True


def resolve_to_spec(
    question: str,
) -> Optional[Dict[str, Any]]:
    """
    Resolve question to a spec dict (metric, dimension, table, metric_column, aggregation)
    without generating SQL. Useful for feeding the LLM with strong hints.
    """
    if not question or not question.strip():
        return None
    data = load_semantic_dictionary()
    if not data:
        return None

    metric_result = _detect_metric_phrase(question)
    if not metric_result:
        return None
    metric_key, remainder = metric_result
    metric_spec = _get_metric_spec(metric_key)
    if not metric_spec:
        return None

    dimension_info = _detect_dimension(remainder) if remainder else None
    spec = {
        "metric": metric_key,
        "table": metric_spec["table"],
        "metric_column": metric_spec["column"],
        "aggregation": metric_spec.get("aggregation", "SUM"),
        "dimension": None,
        "dimension_table": None,
        "dimension_column": None,
        "name_table": None,
        "name_column": None,
    }
    if dimension_info:
        spec["dimension"] = dimension_info.get("entity")
        spec["dimension_table"] = dimension_info.get("table")
        spec["dimension_column"] = dimension_info.get("column") or dimension_info.get("dimension_column")
        spec["name_table"] = dimension_info.get("name_table")
        spec["name_column"] = dimension_info.get("name_column")
    return spec


def get_join_graph_text() -> str:
    """Return a compact join graph summary for the LLM (which tables join on which keys)."""
    data = load_semantic_dictionary()
    joins = data.get("joins") or []
    lines = ["Join graph (use for multi-table queries):"]
    seen = set()
    for j in joins:
        line = f"  {j.get('left_table')}.{j.get('left_key')} = {j.get('right_table')}.{j.get('right_key')}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def get_metrics_text() -> str:
    """Return a compact metrics summary for the LLM (which column to aggregate for which concept)."""
    data = load_semantic_dictionary()
    metrics = data.get("metrics") or {}
    lines = ["Metrics (use these for aggregation):"]
    for name, m in list(metrics.items())[:20]:
        lines.append(f"  {name}: {m.get('table')}.{m.get('column')} -> {m.get('aggregation', 'SUM')}")
    return "\n".join(lines)
