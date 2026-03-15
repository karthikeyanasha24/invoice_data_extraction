"""
Deterministic SQL resolver: intent → semantic mapping → SQL template.
Runs BEFORE LLM to generate SQL for common patterns without model calls.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DICT: Optional[Dict[str, Any]] = None


def _load_dict() -> Dict[str, Any]:
    global _DICT
    if _DICT is not None:
        return _DICT
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "sap_semantic_dictionary.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _DICT = json.load(f)
            return _DICT or {}
    except Exception as e:
        logger.debug("deterministic_sql_resolver: load failed: %s", e)
    _DICT = {}
    return {}


def _quote(t: str) -> str:
    if not t:
        return t
    if t.upper() == t and t.replace("_", "").isalnum():
        return f'"{t}"'
    return t


def _resolve_metric(question: str) -> Optional[Tuple[str, str, str, str]]:
    """Return (metric_key, table, column, agg) or None."""
    q = (question or "").strip().lower()
    data = _load_dict()
    phrases = data.get("metric_phrases") or {}
    for phrase, key in sorted(phrases.items(), key=lambda x: -len(x[0])):
        if phrase in q:
            metrics = data.get("metrics") or {}
            m = metrics.get(key)
            if m:
                return (key, m.get("table", ""), m.get("column", ""), m.get("aggregation", "SUM"))
    metrics = data.get("metrics") or {}
    for key, m in metrics.items():
        if key.replace("_", " ") in q:
            return (key, m.get("table", ""), m.get("column", ""), m.get("aggregation", "SUM"))
    return None


def _resolve_dimension(question: str) -> Optional[Dict[str, Any]]:
    """Return dimension info dict or None."""
    q = (question or "").strip().lower()
    data = _load_dict()
    aliases = data.get("dimension_aliases") or {}
    by_m = re.search(r"\bby\s+(\w+(?:\s+\w+)?)\b", q)
    dim_word = (by_m.group(1) or "").strip().lower() if by_m else ""
    for alias, info in aliases.items():
        if alias in dim_word or alias in q or dim_word in alias:
            return dict(info)
    dimensions = data.get("dimensions") or {}
    for key, d in dimensions.items():
        if key.replace("_", " ") in (dim_word + " " + q):
            return dict(d)
    return None


def _get_join(left: str, right: str) -> Optional[Tuple[str, str]]:
    """Return (left_key, right_key) for joining left to right."""
    data = _load_dict()
    for j in data.get("joins") or []:
        lt, rt = j.get("left_table"), j.get("right_table")
        if (lt == left and rt == right) or (lt == right and rt == left):
            lk, rk = j.get("left_key"), j.get("right_key")
            if lt == left:
                return (lk, rk)
            return (rk, lk)
    return None


def resolve_deterministic_sql(
    question: str,
    available_tables: Optional[List[str]] = None,
    schema_table_case: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    Resolve question to SQL using intent + semantic mapping + templates.
    Returns SQL or None (fallback to LLM).
    """
    if not question or not question.strip():
        return None
    q = (question or "").strip().lower()
    avail = {t.upper() for t in (available_tables or [])} if available_tables else None

    def ok(tbl: str) -> bool:
        if not tbl:
            return False
        if avail is None:
            return True
        return (tbl or "").upper() in avail

    def tbl(t: str) -> str:
        if schema_table_case and t and t.upper() in schema_table_case:
            return _quote(schema_table_case[t.upper()])
        return _quote(t)

    # 1) Top N pattern: "top 10 customers by revenue"
    top_n = re.search(r"\btop\s+(\d+)\b", q) or re.search(r"\b(\d+)\s+top\b", q)
    if top_n:
        n = int(top_n.group(1))
        metric_t = _resolve_metric(question)
        dim_t = _resolve_dimension(question)
        if metric_t and dim_t:
            mkey, mtable, mcol, agg = metric_t
            if not ok(mtable):
                return None
            dtable = dim_t.get("table") or mtable
            dcol = dim_t.get("column") or dim_t.get("dimension_column")
            name_table = dim_t.get("name_table")
            name_col = dim_t.get("name_column")
            name_jk = dim_t.get("name_join_key") or dcol
            if dcol and ok(dtable):
                if dtable == mtable:
                    sql = (
                        f"SELECT {tbl(mtable)}.{dcol} AS dimension, "
                        f"{agg}({tbl(mtable)}.{mcol}) AS value "
                        f"FROM {tbl(mtable)} "
                        f"GROUP BY {tbl(mtable)}.{dcol} "
                        f"ORDER BY value DESC LIMIT {n}"
                    )
                    return sql
                join_spec = _get_join(mtable, dtable)
                if join_spec:
                    jk1, jk2 = join_spec
                    if name_table and name_col and ok(name_table):
                        jn = _get_join(dtable, name_table)
                        if jn:
                            jn1, jn2 = jn
                            sql = (
                                f"SELECT d.{_quote(dcol)} AS dimension, n.{_quote(name_col)} AS name, "
                                f"{agg}(m.{_quote(mcol)}) AS value "
                                f"FROM {tbl(mtable)} m "
                                f"JOIN {tbl(dtable)} d ON m.{_quote(jk1)} = d.{_quote(jk2)} "
                                f"LEFT JOIN {tbl(name_table)} n ON d.{_quote(jn1)} = n.{_quote(jn2)} "
                                f"GROUP BY d.{_quote(dcol)}, n.{_quote(name_col)} "
                                f"ORDER BY value DESC LIMIT {n}"
                            )
                            if name_table == "MAKT":
                                sql = sql.replace("LEFT JOIN", "LEFT JOIN")  # add AND n.spras='E' in ON
                                sql = sql.replace("= n.", "= n.")  # placeholder
                            return sql
                    sql = (
                        f"SELECT d.{_quote(dcol)} AS dimension, "
                        f"{agg}(m.{_quote(mcol)}) AS value "
                        f"FROM {tbl(mtable)} m "
                        f"JOIN {tbl(dtable)} d ON m.{_quote(jk1)} = d.{_quote(jk2)} "
                        f"GROUP BY d.{_quote(dcol)} "
                        f"ORDER BY value DESC LIMIT {n}"
                    )
                    return sql

    # 2) Comparison: "compare sales vs invoice" -> VBRP netwr vs VBAP netwr by matnr
    if "compare" in q or " vs " in q or "versus" in q:
        if "sales" in q and ("invoice" in q or "order" in q):
            if ok("VBRP") and ok("VBAP"):
                if ok("MAKT"):
                    sql = (
                        f'SELECT m.{_quote("maktx")} AS material_name, v.{_quote("matnr")} AS matnr, '
                        f'SUM(v.{_quote("netwr")}) AS invoice_sales, '
                        f'SUM(b.{_quote("netwr")}) AS order_sales '
                        f"FROM {tbl('VBRP')} v "
                        f"JOIN {tbl('VBAP')} b ON v.{_quote('matnr')} = b.{_quote('matnr')} "
                        f"LEFT JOIN {tbl('MAKT')} m ON v.{_quote('matnr')} = m.{_quote('matnr')} AND (m.spras = 'E' OR m.spras IS NULL) "
                        f"GROUP BY v.{_quote('matnr')}, m.{_quote('maktx')} "
                        f"ORDER BY invoice_sales DESC LIMIT 100"
                    )
                    return sql
                sql = (
                    f'SELECT v.{_quote("matnr")} AS dimension, '
                    f'SUM(v.{_quote("netwr")}) AS invoice_sales, '
                    f'SUM(b.{_quote("netwr")}) AS order_sales '
                    f"FROM {tbl('VBRP')} v "
                    f"JOIN {tbl('VBAP')} b ON v.{_quote('matnr')} = b.{_quote('matnr')} "
                    f"GROUP BY v.{_quote('matnr')} "
                    f"ORDER BY invoice_sales DESC LIMIT 100"
                )
                return sql

    # 3) Standard: metric + dimension
    metric_t = _resolve_metric(question)
    if not metric_t:
        return None
    mkey, mtable, mcol, agg = metric_t
    if not ok(mtable):
        return None
    dim_t = _resolve_dimension(question)
    dtable = mtable
    dcol = None
    name_table = None
    name_col = None
    if dim_t:
        dtable = dim_t.get("table") or mtable
        dcol = dim_t.get("column") or dim_t.get("dimension_column")
        name_table = dim_t.get("name_table")
        name_col = dim_t.get("name_column")
        if not dcol:
            dim_t = None

    if dim_t and dcol:
        # Customer: VBRP -> VBRK -> KNA1
        if "customer" in str(dim_t.get("entity", "")) and dtable == "VBRK" and mtable == "VBRP":
            if ok("VBRK") and ok("KNA1"):
                sql = (
                    f"SELECT k.{_quote('name1')} AS name, "
                    f"SUM(v.{_quote(mcol)}) AS value "
                    f"FROM {tbl('VBRP')} v "
                    f"JOIN {tbl('VBRK')} r ON v.{_quote('vbeln')} = r.{_quote('vbeln')} "
                    f"LEFT JOIN {tbl('KNA1')} k ON r.{_quote('kunag')} = k.{_quote('kunnr')} "
                    f"GROUP BY r.{_quote('kunag')}, k.{_quote('name1')} "
                    f"ORDER BY value DESC LIMIT 100"
                )
                return sql
        # Country: VBRP -> VBRK -> KNA1.land1 (VBRK also has land1)
        if "country" in str(dim_t.get("entity", "")) or "country" in q:
            if ok("VBRK"):
                sql = (
                    f"SELECT r.{_quote('land1')} AS country, "
                    f"SUM(v.{_quote(mcol)}) AS value "
                    f"FROM {tbl('VBRP')} v "
                    f"JOIN {tbl('VBRK')} r ON v.{_quote('vbeln')} = r.{_quote('vbeln')} "
                    f"GROUP BY r.{_quote('land1')} "
                    f"ORDER BY value DESC LIMIT 100"
                )
                return sql
        # Industry: VBRP -> VBRK -> KNA1 -> T016T
        if "industry" in q and ok("KNA1") and ok("T016T"):
            sql = (
                f"SELECT t.{_quote('brtxt')} AS industry, "
                f"SUM(v.{_quote(mcol)}) AS value "
                f"FROM {tbl('VBRP')} v "
                f"JOIN {tbl('VBRK')} r ON v.{_quote('vbeln')} = r.{_quote('vbeln')} "
                f"JOIN {tbl('KNA1')} k ON r.{_quote('kunag')} = k.{_quote('kunnr')} "
                f"LEFT JOIN {tbl('T016T')} t ON k.{_quote('brsch')} = t.{_quote('brsch')} "
                f"GROUP BY t.{_quote('brtxt')} "
                f"ORDER BY value DESC LIMIT 100"
            )
            return sql
        # Product/material: same table or VBRP + MAKT
        if dtable == mtable:
            sql = (
                f"SELECT {tbl(mtable)}.{dcol} AS dimension, "
                f"{agg}({tbl(mtable)}.{mcol}) AS value "
                f"FROM {tbl(mtable)} "
                f"GROUP BY {tbl(mtable)}.{dcol} "
                f"ORDER BY value DESC LIMIT 100"
            )
            return sql
        if name_table and name_col and ok(name_table):
            join_spec = _get_join(mtable, name_table)
            if join_spec:
                jk1, jk2 = join_spec
                makt_extra = " AND (n.spras = 'E' OR n.spras IS NULL)" if name_table == "MAKT" else ""
                sql = (
                    f"SELECT m.{_quote(dcol)} AS dimension, n.{_quote(name_col)} AS name, "
                    f"{agg}(m.{_quote(mcol)}) AS value "
                    f"FROM {tbl(mtable)} m "
                    f"LEFT JOIN {tbl(name_table)} n ON m.{_quote(jk1)} = n.{_quote(jk2)}{makt_extra} "
                    f"GROUP BY m.{_quote(dcol)}, n.{_quote(name_col)} "
                    f"ORDER BY value DESC LIMIT 100"
                )
                return sql
        join_spec = _get_join(mtable, dtable)
        if join_spec:
            jk1, jk2 = join_spec
            if name_col and not name_table and dtable == dim_t.get("table"):
                sql = (
                    f"SELECT d.{_quote(dcol)} AS dimension, d.{_quote(name_col)} AS name, "
                    f"{agg}(m.{_quote(mcol)}) AS value "
                    f"FROM {tbl(mtable)} m "
                    f"JOIN {tbl(dtable)} d ON m.{_quote(jk1)} = d.{_quote(jk2)} "
                    f"GROUP BY d.{_quote(dcol)}, d.{_quote(name_col)} "
                    f"ORDER BY value DESC LIMIT 100"
                )
            else:
                sql = (
                    f"SELECT d.{_quote(dcol)} AS dimension, "
                    f"{agg}(m.{_quote(mcol)}) AS value "
                    f"FROM {tbl(mtable)} m "
                    f"JOIN {tbl(dtable)} d ON m.{_quote(jk1)} = d.{_quote(jk2)} "
                    f"GROUP BY d.{_quote(dcol)} "
                    f"ORDER BY value DESC LIMIT 100"
                )
            return sql

    # 4) Total only
    sql = f"SELECT {agg}({tbl(mtable)}.{mcol}) AS total FROM {tbl(mtable)} LIMIT 1"
    return sql
