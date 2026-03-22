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

    # 0a) Total cost by profit center (FAGLFLEXA) - highest cost, current fiscal year
    pc_cost_phrases = (
        "profit center", "profit centres", "cost by profit center", "total cost by profit center",
        "highest total cost", "which profit centers", "profit centers by cost",
    )
    if any(p in q for p in pc_cost_phrases) and ("cost" in q or "total" in q) and ok("FAGLFLEXA"):
        current_year_only = "current fiscal year" in q or "current year" in q or "fiscal year only" in q
        where_parts = [f"f.{_quote('prctr')} IS NOT NULL"]
        if current_year_only:
            # FAGLFLEXA: ryear (New GL) or gjahr - prefer ryear
            where_parts.append(f"f.{_quote('ryear')}::text = EXTRACT(YEAR FROM CURRENT_DATE)::text")
        where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""
        sql = (
            f"SELECT f.{_quote('prctr')} AS profit_center, "
            f"SUM(f.{_quote('hsl')}) AS total_cost "
            f"FROM {tbl('FAGLFLEXA')} f "
            f"{where_clause} "
            f"GROUP BY f.{_quote('prctr')} "
            f"ORDER BY total_cost DESC NULLS LAST LIMIT 100"
        )
        return sql.strip()

    # 0) Profit margin by product/customer/country (REQUIRED - runs before other patterns)
    margin_phrases = ("profit margin", "margin by product", "product profitability", "margin by customer",
                      "contribution margin", "gross margin", "customer profitability", "top profitable",
                      "profit by customer", "profit by country", "margin by country",
                      "profit margin for all products", "margin for all products")
    if any(m in q for m in margin_phrases):
        if ok("VBRP") and ok("VBRK"):
            # Dimension: product (default), customer, or country
            by_customer = "customer" in q or "margin by customer" in q or "profit by customer" in q or "customer profitability" in q
            by_country = "country" in q or "margin by country" in q or "profit by country" in q
            # Prefer MBEW (standard price) when available; else CKIS (cost estimate)
            if ok("MBEW"):
                cost_expr = (
                    f"(SELECT COALESCE(b2.{_quote('stprs')}, 0) FROM {tbl('MBEW')} b2 "
                    f"WHERE b2.{_quote('matnr')} = v.{_quote('matnr')} LIMIT 1)"
                )
                if by_customer and ok("KNA1"):
                    sql = (
                        f"SELECT COALESCE(n.{_quote('name1')}, r.{_quote('kunag')}) AS customer, "
                        f"SUM(v.{_quote('netwr')}) AS revenue, "
                        f"SUM({cost_expr} * v.{_quote('fkimg')}) AS cost, "
                        f"SUM(v.{_quote('netwr')}) - SUM({cost_expr} * v.{_quote('fkimg')}) AS profit, "
                        f"CASE WHEN SUM(v.{_quote('netwr')}) <> 0 THEN "
                        f"((SUM(v.{_quote('netwr')}) - SUM({cost_expr} * v.{_quote('fkimg')})) / SUM(v.{_quote('netwr')})) * 100 ELSE NULL END AS margin "
                        f"FROM {tbl('VBRP')} v "
                        f"JOIN {tbl('VBRK')} r ON v.{_quote('vbeln')} = r.{_quote('vbeln')} "
                        f"LEFT JOIN {tbl('KNA1')} n ON r.{_quote('kunag')} = n.{_quote('kunnr')} "
                        f"GROUP BY r.{_quote('kunag')}, n.{_quote('name1')} "
                        f"ORDER BY margin DESC NULLS LAST LIMIT 500"
                    )
                    return sql
                if by_country:
                    sql = (
                        f"SELECT r.{_quote('land1')} AS country, "
                        f"SUM(v.{_quote('netwr')}) AS revenue, "
                        f"SUM({cost_expr} * v.{_quote('fkimg')}) AS cost, "
                        f"SUM(v.{_quote('netwr')}) - SUM({cost_expr} * v.{_quote('fkimg')}) AS profit, "
                        f"CASE WHEN SUM(v.{_quote('netwr')}) <> 0 THEN "
                        f"((SUM(v.{_quote('netwr')}) - SUM({cost_expr} * v.{_quote('fkimg')})) / SUM(v.{_quote('netwr')})) * 100 ELSE NULL END AS margin "
                        f"FROM {tbl('VBRP')} v "
                        f"JOIN {tbl('VBRK')} r ON v.{_quote('vbeln')} = r.{_quote('vbeln')} "
                        f"GROUP BY r.{_quote('land1')} "
                        f"ORDER BY margin DESC NULLS LAST LIMIT 500"
                    )
                    return sql
                # Default: by product
                if ok("MAKT"):
                    sql = (
                        f"SELECT COALESCE(MAX(m.{_quote('maktx')}), v.{_quote('matnr')}) AS product, "
                        f"SUM(v.{_quote('netwr')}) AS revenue, "
                        f"SUM({cost_expr} * v.{_quote('fkimg')}) AS cost, "
                        f"SUM(v.{_quote('netwr')}) - SUM({cost_expr} * v.{_quote('fkimg')}) AS profit, "
                        f"CASE WHEN SUM(v.{_quote('netwr')}) <> 0 THEN "
                        f"((SUM(v.{_quote('netwr')}) - SUM({cost_expr} * v.{_quote('fkimg')})) / SUM(v.{_quote('netwr')})) * 100 ELSE NULL END AS margin "
                        f"FROM {tbl('VBRP')} v "
                        f"LEFT JOIN {tbl('MAKT')} m ON v.{_quote('matnr')} = m.{_quote('matnr')} AND (m.spras = 'E' OR m.spras IS NULL) "
                        f"GROUP BY v.{_quote('matnr')} "
                        f"ORDER BY margin DESC NULLS LAST LIMIT 500"
                    )
                    return sql
            if ok("CKIS") and ok("KEKO") and ok("MAKT"):
                ckis_cost = (
                    f"(SELECT COALESCE(SUM(c.{_quote('wertn')}), 0) FROM {tbl('KEKO')} k2 "
                    f"JOIN {tbl('CKIS')} c ON k2.{_quote('kalnr')} = c.{_quote('kalnr')} WHERE k2.{_quote('matnr')} = v.{_quote('matnr')})"
                )
                sql = (
                    f"SELECT m.{_quote('maktx')} AS product, "
                    f"SUM(v.{_quote('netwr')}) AS revenue, "
                    f"{ckis_cost} AS cost, "
                    f"SUM(v.{_quote('netwr')}) - {ckis_cost} AS profit, "
                    f"CASE WHEN SUM(v.{_quote('netwr')}) <> 0 THEN "
                    f"((SUM(v.{_quote('netwr')}) - {ckis_cost}) / SUM(v.{_quote('netwr')})) * 100 ELSE NULL END AS margin "
                    f"FROM {tbl('VBRP')} v "
                    f"LEFT JOIN {tbl('MAKT')} m ON v.{_quote('matnr')} = m.{_quote('matnr')} AND (m.spras = 'E' OR m.spras IS NULL) "
                    f"GROUP BY v.{_quote('matnr')}, m.{_quote('maktx')} "
                    f"ORDER BY margin DESC NULLS LAST LIMIT 500"
                )
                return sql

    # 0b) Sales trend by year (dimension = year)
    # CRITICAL: VBRK.gjahr stores '0000' in this DB — NEVER use it.
    # Use SUBSTRING(TRIM(fkdat),1,4) for year dimension instead.
    # Skip when query asks for "lowest", "negative", "highest", "top", "by customer", "by product" —
    # those need dimension breakdown (handled by schema-driven LLM, not year-aggregate template).
    _dim_keywords = ("lowest", "negative", "highest", "top ", "bottom", "best", "worst",
                     "by customer", "by product", "by material", "by vendor", "by country")
    if (("sales" in q or "revenue" in q) and ("year" in q or "trend" in q)
            and ok("VBRP") and ok("VBRK")
            and not any(kw in q for kw in _dim_keywords)):
        # If question asks for a specific year (e.g. "for year 2000"), add a WHERE filter
        import re as _yr_re
        year_match = _yr_re.search(r'\b(19\d{2}|20[0-2]\d)\b', q)
        where_clause = ""
        if year_match:
            yr = year_match.group(1)
            where_clause = f"WHERE SUBSTRING(TRIM(r.{_quote('fkdat')}),1,4) = '{yr}' "
        sql = (
            f"SELECT SUBSTRING(TRIM(r.{_quote('fkdat')}),1,4) AS year, "
            f"SUM(NULLIF(TRIM(v.{_quote('netwr')}::text),'')::numeric) AS sales, "
            f"COUNT(*) AS records "
            f"FROM {tbl('VBRP')} v "
            f"JOIN {tbl('VBRK')} r ON LPAD(TRIM(v.{_quote('vbeln')}),10,'0') = LPAD(TRIM(r.{_quote('vbeln')}),10,'0') "
            f"{where_clause}"
            f"GROUP BY SUBSTRING(TRIM(r.{_quote('fkdat')}),1,4) "
            f"ORDER BY year ASC LIMIT 100"
        )
        return sql

    # 0c) Purchase order totals by material (quantity + cost from EKPO)
    if (any(p in q for p in ("purchase", "purchased", "po ", "ekpo", "purchase order totals")) and
            "material" in q and ok("EKPO") and ok("MAKT")):
        if ok("MARA"):
            sql = (
                f"SELECT COALESCE(m.{_quote('maktx')}, e.{_quote('matnr')}) AS product, "
                f"SUM(e.{_quote('menge')}) AS total_quantity, "
                f"SUM(e.{_quote('netwr')}) AS total_cost "
                f"FROM {tbl('EKPO')} e "
                f"LEFT JOIN {tbl('MAKT')} m ON e.{_quote('matnr')} = m.{_quote('matnr')} AND (m.spras = 'E' OR m.spras IS NULL) "
                f"GROUP BY e.{_quote('matnr')}, m.{_quote('maktx')} "
                f"ORDER BY total_cost DESC NULLS LAST LIMIT 100"
            )
            return sql

    # 0d) Vendor invoice totals by vendor (RBKP + LFA1)
    if ("vendor invoice" in q or "invoice value" in q and "vendor" in q or "top vendors by invoice" in q) and ok("RBKP") and ok("LFA1"):
        sql = (
            f"SELECT l.{_quote('name1')} AS vendor, "
            f"SUM(r.{_quote('rmwwr')}) AS value "
            f"FROM {tbl('RBKP')} r "
            f"LEFT JOIN {tbl('LFA1')} l ON r.{_quote('lifnr')} = l.{_quote('lifnr')} "
            f"GROUP BY r.{_quote('lifnr')}, l.{_quote('name1')} "
            f"ORDER BY value DESC NULLS LAST LIMIT 100"
        )
        return sql

    # 0e) Vendor invoice totals by currency
    if "vendor invoice" in q and "currency" in q and ok("RBKP"):
        sql = (
            f"SELECT r.{_quote('waers')} AS currency, "
            f"SUM(r.{_quote('rmwwr')}) AS value "
            f"FROM {tbl('RBKP')} r "
            f"GROUP BY r.{_quote('waers')} "
            f"ORDER BY value DESC NULLS LAST LIMIT 100"
        )
        return sql

    # 0f) Outbound delivery quantities by product (LIPS)
    if ("delivery" in q or "delivered" in q) and ("quantity" in q or "quantities" in q) and "product" in q and ok("LIPS") and ok("MAKT"):
        sql = (
            f"SELECT COALESCE(m.{_quote('maktx')}, l.{_quote('matnr')}) AS product, "
            f"SUM(l.{_quote('lfimg')}) AS total_quantity "
            f"FROM {tbl('LIPS')} l "
            f"LEFT JOIN {tbl('MAKT')} m ON l.{_quote('matnr')} = m.{_quote('matnr')} AND (m.spras = 'E' OR m.spras IS NULL) "
            f"GROUP BY l.{_quote('matnr')}, m.{_quote('maktx')} "
            f"ORDER BY total_quantity DESC NULLS LAST LIMIT 100"
        )
        return sql

    # 0g) Procurement spend by vendor (EKPO path)
    if (("procurement" in q and "vendor" in q) or "vendor spend" in q or "spend by vendor" in q or
        ("purchase" in q and "vendor" in q) or "procurement spend" in q) and ok("EKPO") and ok("EKKO") and ok("LFA1"):
        sql = (
            f"SELECT l.{_quote('name1')} AS vendor, "
            f"SUM(e.{_quote('netwr')}) AS value "
            f"FROM {tbl('EKPO')} e "
            f"JOIN {tbl('EKKO')} k ON e.{_quote('ebeln')} = k.{_quote('ebeln')} "
            f"LEFT JOIN {tbl('LFA1')} l ON k.{_quote('lifnr')} = l.{_quote('lifnr')} "
            f"GROUP BY k.{_quote('lifnr')}, l.{_quote('name1')} "
            f"ORDER BY value DESC LIMIT 100"
        )
        return sql

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
