"""
Generic query-plan and SQL repair for the adaptive analyst pipeline.

Repairs classes of failures (GROUP BY, spurious columns, aggregation grain)
from question intent and schema metadata — not per-question hardcoding.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..data_catalog.physical import column_names, has_column, has_table, resolve_table_name
from .adaptive_structured_sql import (
    StructuredQueryPlan,
    numeric_cast_expr,
    qualified_column,
)
_MEASURE_COLS = frozenset({"netwr", "dmbtr", "wrbtr", "rmwwr", "fkimg", "menge", "wavwr", "kwert"})
_DATE_COLS = frozenset({"fkdat", "audat", "bedat", "budat", "erdat", "bldat", "wadat", "cpudt"})
_CURRENCY_COLS = frozenset({"waerk", "waers", "rtcur", "hwaer"})
_UNIT_COLS = frozenset({"meins", "vrkme", "gewei"})
_RANKING_CUE = re.compile(r"\b(top|highest|lowest|most|best|worst|bottom|largest|smallest|rank)\b", re.I)


def _question_text(question: str, semantic: Optional[Dict[str, Any]]) -> str:
    return (question or "").lower()


def _semantic_dimensions(semantic: Optional[Dict[str, Any]]) -> Set[str]:
    dims: Set[str] = set()
    if not semantic:
        return dims
    raw = semantic.get("dimensions")
    if isinstance(raw, list):
        for d in raw:
            dims.add(str(d).lower())
    return dims


def column_required_for_question(
    table: str,
    column: str,
    question: str,
    semantic: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when a physical column is semantically required to answer the question."""
    col = column.lower()
    q = _question_text(question, semantic)
    dims = _semantic_dimensions(semantic)

    if col in _MEASURE_COLS:
        if any(w in q for w in ("quantity", "qty", "units", "volume")) and col in {"fkimg", "menge"}:
            return True
        if any(w in q for w in ("sales", "revenue", "billing", "amount", "value")) and col in {"netwr", "dmbtr", "wrbtr"}:
            return True
        return False

    if col in _DATE_COLS:
        if any(w in q for w in ("year", "month", "date", "period", "when", "time", "daily", "monthly")):
            return True
        if semantic and semantic.get("time_filter"):
            return True
        return False

    if col in _CURRENCY_COLS:
        return any(w in q for w in ("currency", "currencies", "waerk", "per currency", "by currency"))

    if col in _UNIT_COLS:
        return any(w in q for w in ("unit", "uom", "meins", "measure unit"))

    if col in {"matnr", "material", "product"} or "material" in col:
        return "material" in q or "product" in q or any("material" in d or "product" in d for d in dims)

    if col in {"maktx", "arktx"}:
        return "material" in q or "product" in q or "description" in q or "name" in q

    if col in {"kunnr", "kunag", "name1", "land1", "brsch", "brtxt"}:
        for token in ("customer", "country", "industry", "sector", "client"):
            if token in q or any(token in d for d in dims):
                if token == "customer" and col in {"kunnr", "kunag", "name1"}:
                    return True
                if token == "country" and col == "land1":
                    return True
                if token in {"industry", "sector"} and col in {"brsch", "brtxt"}:
                    return True
    return False


def prune_plan_for_aggregation(plan: StructuredQueryPlan) -> None:
    """
    Remove non-essential columns from an aggregating plan before SQL render.
    Prevents GROUP BY errors from spurious date/uom columns the LLM added.
    """
    if not _needs_plan_aggregation(plan):
        return

    kept: List[PlanField] = []
    for pf in plan.select:
        if pf.type == "expression":
            kept.append(pf)
            continue
        if pf.column.lower() in _MEASURE_COLS:
            kept.append(pf)
            continue
        if column_required_for_question(
            pf.table or "", pf.column, plan.question, plan.semantic_requirements
        ):
            kept.append(pf)
            continue
        # drop spurious dimension (e.g. erdat on a material quantity ranking)
    plan.select = kept

    if plan.group_by:
        plan.group_by = [
            g
            for g in plan.group_by
            if g.type == "expression"
            or column_required_for_question(g.table or "", g.column, plan.question, plan.semantic_requirements)
            or g.column.lower() in _MEASURE_COLS
        ]


def _needs_plan_aggregation(plan: StructuredQueryPlan) -> bool:
    sem = plan.semantic_requirements or {}
    if isinstance(sem.get("ranking"), dict):
        return True
    measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or "").upper()
    if agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"}:
        return True
    return bool(plan.group_by)


def extract_grouping_error_column(error_text: str) -> Optional[Tuple[str, str]]:
    """Parse PostgreSQL GroupingError for table.column."""
    m = re.search(r'column\s+"?([A-Za-z0-9_]+)"?\."?([A-Za-z0-9_]+)"?\s+must appear', error_text, re.I)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r'column\s+"?([A-Za-z0-9_.]+)"?\s+must appear', error_text, re.I)
    if m:
        parts = m.group(1).split(".")
        if len(parts) == 2:
            return parts[0], parts[1]
    return None


def repair_grouping_error_sql(
    sql: str,
    question: str,
    error_text: str,
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Generic GROUP BY repair: remove ungrouped columns not required by question intent.
    Falls back to adding column to GROUP BY only when semantically required.
    """
    if not sql or not error_text:
        return None
    parsed = extract_grouping_error_column(error_text)
    if not parsed:
        return None
    tbl, col = parsed
    if column_required_for_question(tbl, col, question, semantic):
        # Add to GROUP BY instead of removing
        qual = qualified_column(resolve_table_name(tbl) or tbl, col)
        if re.search(r"\bGROUP\s+BY\b", sql, re.I):
            return re.sub(
                r"(\bGROUP\s+BY\b[^;]+?)(\s+ORDER\s+BY|\s+LIMIT|$)",
                rf"\1, {qual}\2",
                sql,
                count=1,
                flags=re.I,
            )
        m = re.search(r"\s+(ORDER\s+BY|LIMIT)\b", sql, re.I)
        suffix = f" GROUP BY {qual}"
        if m:
            return sql[: m.start()] + suffix + sql[m.start() :]
        return sql.rstrip().rstrip(";") + suffix

    # Remove column from SELECT list
    rt = resolve_table_name(tbl) or tbl
    patterns = [
        rf',?\s*"{re.escape(rt)}"\."{re.escape(col)}"(?:\s+AS\s+"[^"]+")?',
        rf',?\s*{re.escape(rt)}\."{re.escape(col)}"(?:\s+AS\s+"[^"]+")?',
        rf',?\s*"{re.escape(rt)}"\.{re.escape(col)}(?:\s+AS\s+\w+)?',
        rf',?\s*{re.escape(rt)}\.{re.escape(col)}(?:\s+AS\s+\w+)?',
    ]
    out = sql
    for pat in patterns:
        out2 = re.sub(pat, "", out, count=1, flags=re.I)
        if out2 != out:
            out = out2
            break
    out = re.sub(r"SELECT\s+,", "SELECT ", out, flags=re.I)
    out = re.sub(r",\s*,", ",", out)
    return out.strip() if out.strip() else None


def detect_measure_ranking_intent(
    question: str, semantic: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Return measure kind for ranking: quantity | sales | None."""
    q = _question_text(question, semantic)
    if not _RANKING_CUE.search(q):
        return None
    sem = semantic or {}
    measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    concept = str(measure.get("concept") or "").lower()
    if concept in {"quantity", "qty", "volume", "units"} or any(
        w in q for w in ("quantity", "qty", "units", " billed quantity", "billing quantity")
    ):
        return "quantity"
    if concept in {"sales", "revenue", "billing", "amount"} or any(
        w in q for w in ("sales", "revenue", "billing", "billed")
    ):
        return "sales"
    if "material" in q or "product" in q:
        return "quantity"
    return "sales"


def _discover_line_measure(measure_kind: str, tables: List[str]) -> Optional[Tuple[str, str]]:
    qty_cols = ("fkimg", "menge")
    sales_cols = ("netwr", "dmbtr", "wrbtr")
    targets = qty_cols if measure_kind == "quantity" else sales_cols
    search = list(dict.fromkeys(tables))
    if has_table("vbrp") and "vbrp" not in {t.lower() for t in search}:
        search.insert(0, "vbrp")
    for t in search:
        rt = resolve_table_name(t) or t
        for c in column_names(rt):
            if c.lower() in targets:
                return rt, c
    return None


def _discover_material_text_join(tables: List[str]) -> Optional[Tuple[str, str, str, str]]:
    line = "vbrp" if has_table("vbrp") else None
    text_tbl = "MAKT" if has_table("MAKT") else None
    if not line or not text_tbl or not has_column(line, "matnr") or not has_column(text_tbl, "matnr"):
        return None
    text_col = "maktx" if has_column(text_tbl, "maktx") else "arktx"
    if not has_column(text_tbl, text_col):
        return None
    return resolve_table_name(line) or line, "matnr", resolve_table_name(text_tbl) or text_tbl, text_col


def build_measure_ranking_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Generic measure ranking SQL discovered from schema + intent (material/customer/etc.).
    """
    kind = detect_measure_ranking_intent(question, semantic)
    if not kind:
        return None
    measure = _discover_line_measure(kind, tables)
    if not measure:
        return None
    mtbl, mcol = measure
    q = _question_text(question, semantic)
    limit = 10
    m = re.search(r"\btop\s+(\d+)", q)
    if m:
        limit = int(m.group(1))
    elif re.search(r"\b(highest|most|best|largest|biggest)\b", q):
        limit = 1

    sel: List[str] = []
    gb: List[str] = []
    joins: List[str] = []

    mat = _discover_material_text_join(tables)
    if mat and ("material" in q or "product" in q or kind == "quantity"):
        line, line_key, text_tbl, text_col = mat
        sel.append(f'TRIM("{line}"."{line_key}") AS "material_id"')
        sel.append(f'TRIM("{text_tbl}"."{text_col}") AS "material_name"')
        gb.extend([f'TRIM("{line}"."{line_key}")', f'TRIM("{text_tbl}"."{text_col}")'])
        joins.append(
            f'LEFT JOIN "{text_tbl}" ON TRIM("{line}"."{line_key}") = TRIM("{text_tbl}"."{line_key}")'
        )
        from_tbl = line
    else:
        from_tbl = mtbl

    agg_expr = f"SUM({numeric_cast_expr(mtbl, mcol)})"
    alias = "billed_quantity" if kind == "quantity" else "total_sales"
    sel.append(f'{agg_expr} AS "{alias}"')

    sql = f"SELECT {', '.join(sel)}\nFROM \"{from_tbl}\""
    for j in joins:
        sql += f"\n{j}"
    sql += f"\nWHERE NULLIF(TRIM(CAST(\"{mtbl}\".\"{mcol}\" AS TEXT)), '') IS NOT NULL"
    if gb:
        sql += f"\nGROUP BY {', '.join(gb)}"
    direction = "ASC" if re.search(r"\b(lowest|smallest|minimum|worst)\b", q) else "DESC"
    sql += f'\nORDER BY "{alias}" {direction} NULLS LAST'
    sql += f"\nLIMIT {max(1, min(limit, 500))}"
    return sql.strip()


def validate_monetary_result(rows: List[Dict[str, Any]], question: str) -> List[str]:
    """Flag cross-currency ranking when multiple currencies appear without conversion."""
    if not rows:
        return []
    q = (question or "").lower()
    if not any(w in q for w in ("sales", "revenue", "billing", "amount", "highest", "top")):
        return []
    if any(w in q for w in ("by currency", "per currency", "each currency")):
        return []
    currencies = {str(r.get("currency") or r.get("waerk") or "").strip() for r in rows}
    currencies.discard("")
    if len(currencies) > 1:
        return [
            "MULTI_CURRENCY: results mix "
            f"{', '.join(sorted(currencies)[:6])} without conversion — rankings are not directly comparable."
        ]
    return []
