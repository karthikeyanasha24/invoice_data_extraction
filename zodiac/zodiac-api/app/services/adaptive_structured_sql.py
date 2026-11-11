"""
Structured query plan → validated SQL renderer for the adaptive four-stage pipeline.

Separates physical columns from SQL expressions so the LLM cannot produce
invalid identifiers like "VBRK"."SUBSTRING(TRIM(fkdat),1,4)".
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..data_catalog.physical import column_names, has_column, has_table, resolve_table_name
from .adaptive_analyst.llm_provider import analyze_json
from .schema_intelligence_registry import get_schema_registry

logger = logging.getLogger("zodiac-api.structured_sql")

# SAP dates stored as YYYYMMDD text — never EXTRACT(YEAR FROM col) directly
_SAP_TEXT_DATE_COLUMNS = frozenset({
    "fkdat", "audat", "bedat", "budat", "erdat", "bldat", "wadat", "cpudt", "aedat",
    "wadat_ist", "lfdat", "bldat", "valdt",
})

_QUALIFIED_SQL_COLUMN = r'(?:"[A-Za-z0-9_]+"|[A-Za-z0-9_]+)\s*\.\s*(?:"[A-Za-z0-9_]+"|[A-Za-z0-9_]+)'
_EXTRACT_TEXT_DATE_PATTERN = re.compile(
    rf"""EXTRACT\s*\(\s*(?P<part>YEAR|MONTH)\s+FROM\s+
        (?:CAST\s*\(\s*(?P<cast_ref>{_QUALIFIED_SQL_COLUMN})\s+AS\s+(?:DATE|TIMESTAMP(?:\s+WITHOUT\s+TIME\s+ZONE)?)\s*\)
        |(?P<plain_ref>{_QUALIFIED_SQL_COLUMN})(?:\s*::\s*(?:DATE|TIMESTAMP(?:\s+WITHOUT\s+TIME\s+ZONE)?))?)
        \s*\)""",
    re.I | re.X,
)

_SQL_FUNCS = (
    "SUBSTRING", "TRIM", "CAST", "EXTRACT", "COALESCE", "NULLIF", "LPAD", "RTRIM", "LTRIM",
    "UPPER", "LOWER", "SUM", "COUNT", "AVG", "MAX", "MIN", "DATE_PART", "TO_DATE", "TO_CHAR",
    "ROUND", "ABS", "GREATEST", "LEAST", "CASE", "WHEN", "THEN", "ELSE", "END",
)


def _makt_join(matnr_expr: str) -> str:
    """Join material texts without multiplying rows across languages."""
    on = (
        f'LPAD(TRIM(CAST({matnr_expr} AS TEXT)), 10, \'0\') = '
        'LPAD(TRIM(CAST(m."matnr" AS TEXT)), 10, \'0\')'
    )
    if has_column("MAKT", "spras"):
        on += " AND UPPER(TRIM(CAST(m.\"spras\" AS TEXT))) IN ('E', 'EN')"
    return f'LEFT JOIN "MAKT" m ON {on}'

# "TABLE"."EXPR(...)" — expression incorrectly quoted as a column identifier
_QUOTED_EXPR_AS_COL = re.compile(
    r'"([A-Za-z0-9_]+)"\s*\.\s*"([^"]*\([^"]*)"',
    re.I,
)

# CAST("TABLE"."EXPR(...)" AS ...) wrapper around invalid pseudo-column
_CAST_QUOTED_EXPR = re.compile(
    r'CAST\s*\(\s*"([A-Za-z0-9_]+)"\s*\.\s*"([^"]*\([^"]*)"\s*AS\s+([A-Za-z0-9_]+)\s*\)',
    re.I,
)


@dataclass
class PlanField:
    """Physical column OR SQL expression — never both."""

    type: str  # "column" | "expression"
    table: str = ""
    column: str = ""
    expression: str = ""
    alias: str = ""
    purpose: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlanFilter:
    type: str  # "column" | "expression"
    table: str = ""
    column: str = ""
    expression: str = ""
    operator: str = "="
    value: Any = None
    alias_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StructuredQueryPlan:
    question: str = ""
    tables: List[str] = field(default_factory=list)
    select: List[PlanField] = field(default_factory=list)
    joins: List[Dict[str, Any]] = field(default_factory=list)
    filters: List[PlanFilter] = field(default_factory=list)
    group_by: List[PlanField] = field(default_factory=list)
    order_by: List[Dict[str, Any]] = field(default_factory=list)
    limit: Optional[int] = None
    transformations: List[Dict[str, Any]] = field(default_factory=list)
    semantic_requirements: Dict[str, Any] = field(default_factory=dict)
    intent: str = ""
    result_grain: str = ""
    ranking: Optional[Dict[str, Any]] = None
    negation: Optional[Dict[str, Any]] = None
    period_compare: Optional[Dict[str, Any]] = None
    currency_strategy: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "tables": self.tables,
            "select": [s.to_dict() for s in self.select],
            "joins": self.joins,
            "filters": [f.to_dict() for f in self.filters],
            "group_by": [g.to_dict() for g in self.group_by],
            "order_by": self.order_by,
            "limit": self.limit,
            "transformations": self.transformations,
            "semantic_requirements": self.semantic_requirements,
            "intent": self.intent,
            "result_grain": self.result_grain,
            "ranking": self.ranking,
            "negation": self.negation,
            "period_compare": self.period_compare,
            "currency_strategy": self.currency_strategy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredQueryPlan":
        plan = cls(
            question=str(data.get("question") or ""),
            tables=list(data.get("tables") or []),
            joins=list(data.get("joins") or []),
            semantic_requirements=dict(data.get("semantic_requirements") or {}),
            limit=data.get("limit"),
            order_by=list(data.get("order_by") or []),
            transformations=list(data.get("transformations") or []),
            intent=str(data.get("intent") or ""),
            result_grain=str(data.get("result_grain") or ""),
            ranking=data.get("ranking") if isinstance(data.get("ranking"), dict) else None,
            negation=data.get("negation") if isinstance(data.get("negation"), dict) else None,
            period_compare=data.get("period_compare") if isinstance(data.get("period_compare"), dict) else None,
            currency_strategy=data.get("currency_strategy") if isinstance(data.get("currency_strategy"), dict) else None,
        )
        for raw in data.get("select") or []:
            pf = _parse_plan_field(raw if isinstance(raw, dict) else {})
            if pf:
                plan.select.append(pf)
        for raw in data.get("filters") or []:
            flt = _parse_plan_filter(raw if isinstance(raw, dict) else {})
            if flt:
                plan.filters.append(flt)
        for raw in data.get("group_by") or []:
            pf = _parse_plan_field(raw if isinstance(raw, dict) else {})
            if pf:
                plan.group_by.append(pf)
        return plan


def column_type(table: str, column: str) -> str:
    reg = get_schema_registry()
    meta = reg.get_table(table)
    if not meta:
        return ""
    for c in meta.columns:
        if c.name.lower() == (column or "").lower():
            return (c.data_type or "").lower()
    return ""


def qualified_column(table: str, column: str) -> str:
    tbl = resolve_table_name(table) or table
    return f'"{tbl}"."{column}"'


def numeric_cast_expr(table: str, column: str) -> str:
    """Safe numeric cast for SAP text-stored amounts."""
    q = qualified_column(table, column)
    return f"CAST(NULLIF(TRIM(CAST({q} AS TEXT)), '') AS NUMERIC)"


def month_bucket_expression(table: str, column: str) -> str:
    """YYYYMM bucket from SAP text dates (YYYYMMDD) or native dates."""
    q = qualified_column(table, column)
    col_lower = (column or "").lower()
    ctype = column_type(table, column)
    if col_lower in _SAP_TEXT_DATE_COLUMNS or ctype in {"text", "varchar", "character varying", "char", ""}:
        return f"SUBSTRING(TRIM(CAST({q} AS TEXT)), 1, 6)"
    if ctype in {"date", "timestamp", "timestamp without time zone", "timestamptz"}:
        return f"TO_CHAR(CAST({q} AS DATE), 'YYYYMM')"
    return f"SUBSTRING(TRIM(CAST({q} AS TEXT)), 1, 6)"


def year_filter_expression(table: str, column: str) -> str:
    """Build year extraction — SAP text dates use SUBSTRING, never bare EXTRACT on text."""
    q = qualified_column(table, column)
    col_lower = (column or "").lower()
    ctype = column_type(table, column)

    if col_lower in _SAP_TEXT_DATE_COLUMNS or ctype in {"text", "varchar", "character varying", "char", ""}:
        return f"SUBSTRING(TRIM(CAST({q} AS TEXT)), 1, 4)"

    if ctype in {"date", "timestamp", "timestamp without time zone", "timestamptz"}:
        return f"EXTRACT(YEAR FROM CAST({q} AS DATE))"

    return f"SUBSTRING(TRIM(CAST({q} AS TEXT)), 1, 4)"


def relative_period_predicate(table: str, column: str, relative: str) -> str:
    """Generic date predicate from column datatype + relative period name.

    Boundaries are resolved in Python from the execution date — never guessed by the LLM.
    """
    from .semantic_requirements import resolve_relative_period_bounds

    q = qualified_column(table, column)
    col_lower = (column or "").lower()
    ctype = column_type(table, column)
    sap_text = col_lower in _SAP_TEXT_DATE_COLUMNS or ctype in {
        "text", "varchar", "character varying", "char", "",
    }
    start, end = resolve_relative_period_bounds(str(relative))
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    if sap_text:
        return (
            f"TRIM(CAST({q} AS TEXT)) >= '{start_s}' "
            f"AND TRIM(CAST({q} AS TEXT)) < '{end_s}'"
        )
    return (
        f"CAST({q} AS DATE) >= DATE '{start.isoformat()}' "
        f"AND CAST({q} AS DATE) < DATE '{end.isoformat()}'"
    )


def repair_extract_on_text_dates(sql: str) -> str:
    """Normalize date-part extraction on SAP/text dates without casting YYYYMMDD to DATE."""
    if not sql or "EXTRACT" not in sql.upper():
        return sql

    def repl(m: re.Match[str]) -> str:
        ref = m.group("cast_ref") or m.group("plain_ref")
        identifiers = re.match(
            r'\s*(?:"(?P<quoted_table>[A-Za-z0-9_]+)"|(?P<bare_table>[A-Za-z0-9_]+))\s*\.\s*'
            r'(?:"(?P<quoted_column>[A-Za-z0-9_]+)"|(?P<bare_column>[A-Za-z0-9_]+))\s*$',
            ref,
            re.I,
        )
        if not identifiers:
            return m.group(0)

        table = identifiers.group("quoted_table") or identifiers.group("bare_table")
        column = identifiers.group("quoted_column") or identifiers.group("bare_column")
        ctype = column_type(table, column)
        if ctype in {"date", "timestamp", "timestamp without time zone", "timestamp with time zone", "timestamptz"}:
            return m.group(0)
        is_text_date = column.lower() in _SAP_TEXT_DATE_COLUMNS or ctype in {
            "text", "varchar", "character varying", "char", "character"
        }
        if not is_text_date:
            return m.group(0)

        text_ref = f"TRIM(CAST({ref} AS TEXT))"
        start, width = (1, 4) if m.group("part").upper() == "YEAR" else (5, 2)
        # EXTRACT returns a number, including in predicates and arithmetic.
        # Preserve that meaning; YYYYMM grouping is built separately by the plan.
        return f"CAST(NULLIF(SUBSTRING({text_ref}, {start}, {width}), '') AS INTEGER)"

    # SQL-looking text inside a string literal is data, not an expression.
    return "".join(
        segment if index % 2 else _EXTRACT_TEXT_DATE_PATTERN.sub(repl, segment)
        for index, segment in enumerate(re.split(r"('(?:''|[^'])*')", sql))
    )


def _normalize_plan_expressions(plan: StructuredQueryPlan) -> None:
    """Normalize date expressions and remove duplicate select/filter entries."""
    from .sql_structure import qualify_expression

    for pf in plan.select + plan.group_by:
        if pf.type == "expression" and pf.expression:
            pf.expression = qualify_expression(repair_extract_on_text_dates(pf.expression), plan.tables)
    for flt in plan.filters:
        if flt.type == "expression" and flt.expression:
            prefix = "__HAVING__ " if flt.expression.startswith("__HAVING__") else ""
            body = flt.expression.replace("__HAVING__", "", 1).strip() if prefix else flt.expression
            flt.expression = prefix + qualify_expression(repair_extract_on_text_dates(body), plan.tables)

    # SELECT aliases are unavailable in WHERE/HAVING in PostgreSQL. The model
    # may name a verified transformation and then use that name as a field;
    # expand only aliases derived from actual plan expressions.
    derived_aliases = {
        pf.alias: pf.expression for pf in plan.select
        if pf.type == "expression" and pf.alias and pf.expression
    }
    for flt in plan.filters:
        if flt.type != "expression":
            continue
        for alias, expression in derived_aliases.items():
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
                segments = re.split(r"('(?:''|[^'])*')", flt.expression)
                pattern = rf'(?<![\w.])(?:"{re.escape(alias)}"|{re.escape(alias)})(?![\w.]|\s*\(|\s+FROM\b)'
                flt.expression = "".join(
                    segment if index % 2 else re.sub(pattern, f"({expression})", segment, flags=re.I)
                    for index, segment in enumerate(segments)
                )

    seen_select: set[str] = set()
    deduped_select: List[PlanField] = []
    for pf in plan.select:
        key = pf.alias or (f"{pf.table}.{pf.column}" if pf.type == "column" else pf.expression[:80])
        if key in seen_select:
            continue
        seen_select.add(key)
        deduped_select.append(pf)
    plan.select = deduped_select

    seen_filters: set[str] = set()
    deduped_filters: List[PlanFilter] = []
    for flt in plan.filters:
        key = flt.expression if flt.type == "expression" else f"{flt.table}.{flt.column}{flt.operator}{flt.value}"
        if key in seen_filters:
            continue
        seen_filters.add(key)
        deduped_filters.append(flt)
    plan.filters = deduped_filters


def _is_filter_list_question(semantic: Dict[str, Any], question: str = "") -> bool:
    """Row-level filter questions (show/list negative sales) — not SUM rankings."""
    if detect_filter_list_intent(question, semantic):
        return True
    condition = semantic.get("condition") if isinstance(semantic.get("condition"), dict) else {}
    ranking = semantic.get("ranking")
    measure = semantic.get("measure") if isinstance(semantic.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or "").lower()
    if isinstance(condition, dict) and condition.get("measure_operator") is not None:
        if not isinstance(ranking, dict) and agg in {"", "none", "null"}:
            return True
    return False


def detect_filter_list_intent(question: str, semantic: Optional[Dict[str, Any]] = None) -> bool:
    """Detect show/list/filter row-level questions from comparison semantics."""
    from .analytical_operations import extract_analytical_operations, merge_semantic_requirements

    sem = merge_semantic_requirements(question, semantic or {})
    ops = sem.get("analytical_operations") or extract_analytical_operations(question)
    comparison = (
        sem.get("comparison")
        if isinstance(sem.get("comparison"), dict)
        else ops.get("comparison")
    )
    condition = sem.get("condition") if isinstance(sem.get("condition"), dict) else {}
    ranking = sem.get("ranking") if isinstance(sem.get("ranking"), dict) else ops.get("ranking")
    measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or ops.get("aggregation") or "").lower()
    q = (question or "").lower()
    if re.search(r"\b(top|highest|lowest|best|worst|rank|most)\b", q) and not (
        isinstance(comparison, dict) and comparison.get("operator") and agg in {"", "none", "null"}
    ):
        return False
    if re.search(r"\b(total|sum of|aggregate|combined)\b", q):
        return False
    has_pred = (
        (isinstance(comparison, dict) and comparison.get("operator") is not None)
        or (isinstance(condition, dict) and condition.get("measure_operator") is not None)
        or bool(ops.get("negative_measure"))
    )
    if has_pred and not isinstance(ranking, dict) and agg in {"", "none", "null"}:
        return True
    if has_pred and str(ops.get("aggregation") or "").lower() == "none":
        return True
    return False


def build_filter_list_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
    *,
    limit: int = 200,
) -> Optional[str]:
    """
    Deterministic row-level SQL for filter/list questions (no SUM/GROUP BY).
    Discovers measure and date columns from verified tables.
    """
    if not detect_filter_list_intent(question, semantic):
        return None

    sem = semantic or {}
    from .analytical_operations import extract_analytical_operations, merge_semantic_requirements

    sem = merge_semantic_requirements(question, sem)
    ops = sem.get("analytical_operations") or extract_analytical_operations(question)
    condition = sem.get("condition") if isinstance(sem.get("condition"), dict) else {}
    comparison = (
        sem.get("comparison")
        if isinstance(sem.get("comparison"), dict)
        else ops.get("comparison")
    )
    op = str(
        (comparison or {}).get("operator")
        or condition.get("measure_operator")
        or "<"
    ).strip()
    val = (
        (comparison or {}).get("value")
        if comparison and comparison.get("value") is not None
        else condition.get("measure_value", 0)
    )
    if val is None:
        val = 0

    year: Optional[str] = None
    tf = sem.get("time_filter")
    if isinstance(tf, dict) and tf.get("value") is not None:
        year = str(tf["value"])
    if not year and ops.get("years"):
        year = str(ops["years"][0])
    if not year:
        ym = re.search(r"\b((?:19|20)\d{2})\b", question or "")
        if ym:
            year = ym.group(1)

    tables_lower = {(resolve_table_name(t) or t).lower() for t in tables}
    search_tables = list(dict.fromkeys(tables))
    if has_table("VBRK") and "vbrk" not in tables_lower:
        search_tables.insert(0, resolve_table_name("VBRK") or "VBRK")
    if has_table("vbrp") and "vbrp" not in tables_lower:
        search_tables.append(resolve_table_name("vbrp") or "vbrp")
    q_lower = (question or "").lower()
    concept = str(ops.get("measure_concept") or "").lower()
    qty_measure = concept in {"quantity"} or any(k in concept for k in ("quant", "qty"))
    amount_cols = ("fkimg", "menge") if qty_measure else ("netwr", "dmbtr", "wrbtr", "rmwwr")
    want_line = qty_measure or any(w in q_lower for w in ("material", "line item", "item level", "product"))

    def pick_measure_date() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Prefer billing header amounts; quantity lives on the billing item."""
        mt, mc, dt, dc = None, None, None, None
        header_tbl = resolve_table_name("VBRK") if has_table("VBRK") else None
        if header_tbl and not want_line:
            for cand in amount_cols:
                if has_column(header_tbl, cand):
                    mt, mc = header_tbl, cand
                    break
            if has_column(header_tbl, "fkdat"):
                dt, dc = header_tbl, "fkdat"
            if mt and dt:
                return mt, mc, dt, dc

        for t in search_tables:
            rt = resolve_table_name(t) or t
            for c in column_names(rt):
                cl = c.lower()
                if cl in amount_cols and mc is None:
                    mt, mc = rt, c
                if cl in _SAP_TEXT_DATE_COLUMNS and dc is None:
                    dt, dc = rt, c
        if header_tbl:
            if mc is None:
                for cand in amount_cols:
                    if has_column(header_tbl, cand):
                        mt, mc = header_tbl, cand
                        break
            if dc is None and has_column(header_tbl, "fkdat"):
                dt, dc = header_tbl, "fkdat"
        return mt, mc, dt, dc

    measure_tbl, measure_col, date_tbl, date_col = pick_measure_date()
    if not measure_tbl or not measure_col:
        return None

    net_expr = numeric_cast_expr(measure_tbl, measure_col)
    where_parts = [f"{net_expr} {op} {val if isinstance(val, (int, float)) else 0}"]
    relative = ops.get("relative_period")
    if year and date_tbl and date_col:
        year_expr = year_filter_expression(date_tbl, date_col)
        where_parts.append(f"{year_expr} = '{year}'")
    elif relative and date_tbl and date_col:
        where_parts.append(relative_period_predicate(date_tbl, date_col, str(relative)))

    if want_line and "vbrp" in tables_lower and has_table("vbrp"):
        hdr = resolve_table_name("VBRK") or "VBRK"
        line = resolve_table_name("vbrp") or "vbrp"
        line_col = measure_col if (measure_tbl or "").lower() == line.lower() else (
            "fkimg" if qty_measure and has_column(line, "fkimg") else "netwr"
        )
        if not has_column(line, line_col):
            line_col = "netwr" if has_column(line, "netwr") else measure_col
        line_net = numeric_cast_expr(line, line_col)
        line_where = [f"{line_net} {op} {val if isinstance(val, (int, float)) else 0}"]
        if year and has_column(hdr, "fkdat"):
            line_where.append(f"{year_filter_expression(hdr, 'fkdat')} = '{year}'")
        elif relative and has_column(hdr, "fkdat"):
            line_where.append(relative_period_predicate(hdr, "fkdat", str(relative)))
        sel = [
            f'"{line}"."vbeln"',
            f'"{line}"."posnr"',
            f'"{line}"."matnr"',
            f'{line_net} AS "net_value"',
            f'"{hdr}"."fkdat"',
            f'"{hdr}"."kunag"',
            f'"{hdr}"."waerk" AS "currency"',
        ]
        if year and has_column(hdr, "fkdat"):
            sel.append(f'{year_filter_expression(hdr, "fkdat")} AS "billing_year"')
        sql = (
            f"SELECT {', '.join(sel)}\n"
            f'FROM "{line}"\n'
            f'JOIN "{hdr}" ON LPAD(TRIM(CAST("{line}"."vbeln" AS TEXT)), 10, \'0\') '
            f'= LPAD(TRIM(CAST("{hdr}"."vbeln" AS TEXT)), 10, \'0\')\n'
            f"WHERE {' AND '.join(line_where)}\n"
            f'ORDER BY "net_value" ASC\n'
            f"LIMIT {limit}"
        )
        return sql.strip()

    hdr = measure_tbl if measure_tbl.upper() == "VBRK" else (resolve_table_name("VBRK") or "VBRK")
    if has_table(hdr) and measure_tbl.lower() != hdr.lower():
        measure_tbl = hdr

    sel = [f'"{measure_tbl}"."vbeln"', f'"{measure_tbl}"."kunag"', f'{net_expr} AS "net_value"']
    if has_column(measure_tbl, "fkdat"):
        sel.append(f'"{measure_tbl}"."fkdat"')
    if has_column(measure_tbl, "waerk"):
        sel.append(f'"{measure_tbl}"."waerk" AS "currency"')
    if year and date_tbl and date_col:
        sel.append(f'{year_filter_expression(date_tbl, date_col)} AS "billing_year"')

    sql = (
        f"SELECT {', '.join(sel)}\n"
        f'FROM "{measure_tbl}"\n'
        f"WHERE {' AND '.join(where_parts)}\n"
        f'ORDER BY "net_value" ASC\n'
        f"LIMIT {limit}"
    )
    return sql.strip()


def detect_multidim_ranking_intent(question: str, semantic: Optional[Dict[str, Any]] = None) -> bool:
    """Multi-dimension sales ranking (country + customer + industry, etc.)."""
    q = (question or "").lower()
    # Include "bottom" — ensure_default_ranking_limit rewrites "lowest" to "bottom 10".
    if not re.search(
        r"\b(highest|top|most|best|largest|biggest|lowest|worst|bottom|smallest|least|minimum)\b",
        q,
    ):
        return False
    if not re.search(r"\b(sales|revenue|billing|turnover)\b", q):
        return False
    dim_keywords = ("country", "customer", "industry", "sector", "product", "material", "region")
    dim_count = sum(1 for d in dim_keywords if d in q)
    if dim_count >= 2:
        return True
    sem = semantic or {}
    dims = sem.get("dimensions")
    # Currency is a safety/grain key for monetary measures, not an entity
    # dimension. Treating [customer, currency] as a multi-entity ranking sent
    # ordinary per-currency Top-N questions to a renderer that applied a
    # global LIMIT and dropped currency from its grouping.
    ranked_dims = [
        d for d in dims
        if str(d).strip().lower() not in {"currency", "waerk", "waers", "rtcur"}
    ] if isinstance(dims, list) else []
    if len(ranked_dims) >= 2:
        return True
    return False


def build_multidim_ranking_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
    *,
    limit: Optional[int] = None,
) -> Optional[str]:
    """
    Deterministic SQL for multi-dimensional sales rankings.

    Country/customer/industry stay on VBRK → KNA1 (no line fan-out).
    Product/material grain uses vbrp amounts and material id — no MAKT
    language explosion (that join times out on serverless).
    """
    if not detect_multidim_ranking_intent(question, semantic):
        return None
    if not has_table("VBRK") or not has_column("VBRK", "netwr"):
        return None

    q = (question or "").lower()
    if limit is None:
        limit = extract_ranking_limit(question, default=10)
        # "by country, customer and product" is a ranked list, not a single row.
        if limit == 1 and re.search(r"\bby\b.+\band\b", q):
            limit = 10

    want_country = bool(re.search(r"\b(country|countries|nation)\b", q))
    want_customer = bool(re.search(r"\b(customer|customers|client|clients)\b", q))
    want_industry = bool(re.search(r"\b(industry|industries|sector|sectors)\b", q))
    want_product = bool(re.search(r"\b(products?|materials?)\b", q))
    if not any((want_country, want_customer, want_industry, want_product)):
        sem_dims = (semantic or {}).get("dimensions")
        if isinstance(sem_dims, list):
            for d in sem_dims:
                dl = str(d).lower()
                if "country" in dl:
                    want_country = True
                if "customer" in dl:
                    want_customer = True
                if "industry" in dl or "sector" in dl:
                    want_industry = True
                if "product" in dl or "material" in dl:
                    want_product = True

    hdr = resolve_table_name("VBRK") or "VBRK"
    line = resolve_table_name("vbrp") or "vbrp"
    years = extract_question_years(question)
    sel: List[str] = []
    gb: List[str] = []
    joins: List[str] = []
    where_parts: List[str] = []

    use_line = want_product and has_table(line) and has_column(line, "matnr")
    if use_line:
        net = (
            'CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)'
            if has_column(line, "netwr")
            else numeric_cast_expr(hdr, "netwr")
        )
        joins.append(f'FROM "{line}" p')
        joins.append(
            f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') = '
            f'LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')'
        )
        if (want_country or want_customer or want_industry) and has_table("KNA1"):
            joins.append(
                'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
                'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
            )
        if want_country and has_column("KNA1", "land1"):
            sel.append('TRIM(c."land1") AS "country"')
            gb.append('TRIM(c."land1")')
        if want_customer and has_table("KNA1"):
            if has_column("KNA1", "name1"):
                sel.append('TRIM(c."name1") AS "customer"')
                gb.append('TRIM(c."name1")')
            elif has_column("KNA1", "kunnr"):
                sel.append('TRIM(c."kunnr") AS "customer"')
                gb.append('TRIM(c."kunnr")')
        sel.append('TRIM(p."matnr") AS "product"')
        gb.append('TRIM(p."matnr")')
        year_pred = _sap_year_predicate("k", "fkdat", years) if has_column(hdr, "fkdat") else None
    else:
        net = numeric_cast_expr(hdr, "netwr")
        joins.append(f'FROM "{hdr}" k')
        if has_table("KNA1") and has_column(hdr, "kunag") and has_column("KNA1", "kunnr"):
            joins.append(
                'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
                'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
            )
        if want_country and has_table("KNA1") and has_column("KNA1", "land1"):
            sel.append('TRIM(c."land1") AS "country"')
            gb.append('TRIM(c."land1")')
        if want_customer and has_table("KNA1"):
            if has_column("KNA1", "kunnr"):
                sel.append('TRIM(c."kunnr") AS "customer_id"')
                gb.append('TRIM(c."kunnr")')
            if has_column("KNA1", "name1"):
                sel.append('TRIM(c."name1") AS "customer_name"')
                gb.append('TRIM(c."name1")')
        if want_industry and has_table("KNA1") and has_table("T016T"):
            if has_column("T016T", "brtxt"):
                joins.append(
                    'LEFT JOIN "T016T" ON '
                    "LPAD(TRIM(CAST(c.\"brsch\" AS TEXT)), 10, '0') = "
                    "LPAD(TRIM(CAST(\"T016T\".\"brsch\" AS TEXT)), 10, '0')"
                )
                sel.append('TRIM("T016T"."brtxt") AS "industry"')
                gb.append('TRIM("T016T"."brtxt")')
            elif has_column("KNA1", "brsch"):
                sel.append('TRIM(c."brsch") AS "industry_code"')
                gb.append('TRIM(c."brsch")')
        if want_customer:
            where_parts.append("NULLIF(TRIM(CAST(k.\"kunag\" AS TEXT)), '') IS NOT NULL")
        year_pred = _sap_year_predicate("k", "fkdat", years) if has_column(hdr, "fkdat") else None

    if not sel:
        return None

    sel.append(f'SUM({net}) AS "total_sales"')
    if year_pred:
        where_parts.append(year_pred)

    sql = f"SELECT {', '.join(sel)}\n" + "\n".join(joins)
    if where_parts:
        sql += f"\nWHERE {' AND '.join(where_parts)}"
    sql += f"\nGROUP BY {', '.join(gb)}"
    direction = "ASC" if re.search(r"\b(lowest|worst|smallest|minimum|bottom)\b", q) else "DESC"
    sql += f'\nORDER BY "total_sales" {direction} NULLS LAST'
    sql += f"\nLIMIT {max(1, min(int(limit), 500))}"
    return sql.strip()


_YEAR_TOKEN = re.compile(r"\b((?:19|20)\d{2})\b")
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20,
}
_SUPERLATIVE = re.compile(
    r"\b(highest|lowest|most|least|best|worst|largest|biggest|smallest|maximum|minimum)\b", re.I
)
_DESCENDING_EXCEPTIONS = re.compile(r"\b(lowest|least|worst|smallest|minimum|bottom)\b", re.I)

# ISO country codes for "customers in <country>" style filters (KNA1.land1).
_COUNTRY_CODES = {
    "germany": "DE", "united states": "US", "usa": "US", "us": "US", "america": "US",
    "india": "IN", "france": "FR", "united kingdom": "GB", "uk": "GB", "britain": "GB",
    "italy": "IT", "spain": "ES", "canada": "CA", "china": "CN", "japan": "JP",
    "brazil": "BR", "australia": "AU", "mexico": "MX", "netherlands": "NL",
    "switzerland": "CH", "austria": "AT", "belgium": "BE", "sweden": "SE",
    "poland": "PL", "russia": "RU", "portugal": "PT", "denmark": "DK", "norway": "NO",
}


def extract_question_years(question: str) -> List[str]:
    return list(dict.fromkeys(_YEAR_TOKEN.findall(question or "")))


def extract_ranking_limit(question: str, default: int = 10) -> int:
    """Row limit implied by the question: explicit N, spelled-out N, or 1 for superlatives."""
    q = (question or "").lower()
    m = re.search(r"\b(?:top|bottom|first|last)\s+(\d{1,3})\b", q)
    if m:
        return max(1, min(int(m.group(1)), 500))
    m = re.search(r"\b(\d{1,3})\s+(?:most|least)\b", q)
    if m:
        return max(1, min(int(m.group(1)), 500))
    m = re.search(
        r"\b(\d{1,3})\s+(?:biggest|largest|smallest|highest|lowest|best|worst|top|leading)\b", q
    )
    if m:
        return max(1, min(int(m.group(1)), 500))
    words = "|".join(_NUMBER_WORDS)
    m = re.search(
        rf"\b({words})\s+(?:biggest|largest|smallest|highest|lowest|best|worst|top|leading)\b", q
    )
    if m:
        return _NUMBER_WORDS[m.group(1)]
    # "five customers … most revenue" / "which five biggest customers"
    m = re.search(
        rf"\b({words}|\d{{1,3}})\s+"
        rf"(?:(?:biggest|largest|top|best|highest|leading)\s+)?"
        rf"(?:customers?|clients?|buyers?|vendors?|suppliers?|products?|materials?|countries)\b",
        q,
    )
    if m and re.search(r"\b(most|biggest|largest|highest|top|revenue|sales|brought)\b", q):
        raw = m.group(1)
        return max(1, min(int(_NUMBER_WORDS.get(raw, raw)), 500))
    # Singular "top country/customer/…" without an explicit N ⇒ top-1.
    if re.search(
        r"\btop\s+(country|customer|client|buyer|material|product|supplier|vendor|industry)\b",
        q,
    ):
        return 1
    if _SUPERLATIVE.search(q):
        # Plural entities ("which customers…highest") imply a short list, not a single row.
        if re.search(
            r"\b(customers|clients|buyers|countries|materials|products|suppliers|vendors|industries)\b",
            q,
        ):
            return default
        return 1
    return default


def ranking_direction(question: str) -> str:
    q = question or ""
    if _DESCENDING_EXCEPTIONS.search(q):
        return "ASC"
    # "Most negative" is the lowest signed value (e.g. -100 < -5),
    # even though the superlative itself normally implies DESC.
    if re.search(r"\bmost\s+negative\b", q, re.I):
        return "ASC"
    return "DESC"


def _sap_year_predicate(qualifier: str, column: str, years: List[str]) -> Optional[str]:
    """SAP dates are YYYYMMDD text — scope by SUBSTRING, never EXTRACT."""
    if not years:
        return None
    expr = f'SUBSTRING(TRIM(CAST({qualifier}."{column}" AS TEXT)), 1, 4)'
    if len(years) == 1:
        return f"{expr} = '{years[0]}'"
    joined = ", ".join(f"'{y}'" for y in years)
    return f"{expr} IN ({joined})"


def detect_ranking_dimension(
    question: str, semantic: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """The single entity being ranked. Multi-dimension questions are handled elsewhere."""
    q = (question or "").lower()
    # Prefer purchasing entities before customer when both appear with PO/vendor language.
    checks = (
        ("vendor", r"\b(vendors?|suppliers?)\b"),
        ("country", r"\b(countr(?:y|ies)|nation|nations)\b"),
        ("industry", r"\b(industr(?:y|ies)|sector|sectors)\b"),
        ("material", r"\b(material|materials|product|products|sku|skus|article|articles)\b"),
        ("customer", r"\b(customer|customers|client|clients|buyer|buyers|account|accounts)\b"),
        ("plant", r"\b(plants?|werks)\b"),
    )
    for name, pattern in checks:
        if re.search(pattern, q):
            return name
    dims = (semantic or {}).get("dimensions")
    if isinstance(dims, list) and len(dims) == 1:
        d = str(dims[0]).lower()
        for name, pattern in checks:
            if re.search(pattern, d):
                return name
    return None


def detect_ranking_measure(
    question: str, semantic: Optional[Dict[str, Any]] = None
) -> str:
    """Resolve a ranking measure from the semantic metric catalog first."""
    q = (question or "").lower()
    # Supplier/vendor *invoice* amount → MM vendor invoices (RBKP), not PO value.
    if (
        re.search(r"\b(vendors?|suppliers?)\b", q)
        and re.search(r"\b(invoice amount|invoice value|invoiced amount|vendor invoice)\b", q)
        and not re.search(r"\b(purchase order|po value|procurement)\b", q)
    ):
        return "vendor_invoice_value"
    if re.search(
        r"\b(purchase order value|po value|purchasing value|procurement value)\b",
        q,
    ) or (
        re.search(r"\b(vendors?|suppliers?)\b", q)
        and re.search(r"\b(purchase|po\b|order value)\b", q)
        and not re.search(r"\binvoice\b", q)
    ):
        return "purchase_value"
    # Resolve curated business metrics before defaulting generic sales words.
    try:
        from .business_semantic_layer import resolve_metric

        proposed = resolve_metric(question)
        measure = (semantic or {}).get("measure")
        concept = str(measure.get("concept") or "").strip() if isinstance(measure, dict) else ""
        metric = proposed or resolve_metric(concept)
        if metric:
            return metric.name
    except Exception:
        pass
    # Sales/revenue phrases take precedence over incidental 'invoice' wording.
    if re.search(r"\b(billed sales|invoice value|billing amount|revenue|turnover|netwr)\b", q) or (
        re.search(r"\bsales\b", q) and not re.search(r"\b(how many|number of|count of)\s+invoices?\b", q)
    ):
        return "sales"
    if re.search(
        r"\b(invoice count|invoice counts|number of invoices|how many invoices|"
        r"billing documents?|document count)\b",
        q,
    ):
        return "invoice_count"
    if re.search(r"\b(quantity|qty|units|volume|fkimg)\b", q):
        return "quantity"
    concept = ""
    measure = (semantic or {}).get("measure")
    if isinstance(measure, dict):
        concept = str(measure.get("concept") or "").lower()
    if concept in {"quantity", "qty", "volume", "units"}:
        return "quantity"
    if concept in {"count", "invoice_count"}:
        return "invoice_count"
    if any(k in concept for k in ("purchase", "po", "procurement")):
        return "purchase_value"
    if any(k in concept for k in ("sales", "revenue", "amount", "billing", "billed")):
        return "sales"
    return "sales"


def build_billing_item_ranking_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return ranked billing-item facts without multiplying duplicate SAP rows.

    The result remains at VBRP item grain, with VBRK used only for header
    context such as date, customer, and currency.
    """
    q = (question or "").lower()
    if not (
        re.search(r"\b(?:billing|invoice)[- ]items?\b|\bitem[- ]level\b", q)
        and re.search(r"\b(top|bottom|highest|lowest|most|least|largest|smallest|rank|ranking)\b", q)
    ):
        return None
    if not all(has_table(t) for t in ("VBRK", "VBRP")):
        return None
    header = resolve_table_name("VBRK") or "VBRK"
    item = resolve_table_name("VBRP") or "VBRP"
    if not all(has_column(item, c) for c in ("mandt", "vbeln", "posnr", "netwr")):
        return None
    if not all(has_column(header, c) for c in ("mandt", "vbeln", "fkdat")):
        return None

    try:
        limit = extract_ranking_limit(question, default=10)
    except Exception:
        limit = 10
    limit = max(1, min(int(limit), 500))
    direction = ranking_direction(question)
    amount = 'CAST(NULLIF(TRIM(CAST(i."netwr" AS TEXT)), \'\') AS NUMERIC)'
    row_columns = ["mandt", "vbeln", "posnr", "netwr"]
    row_columns.extend(
        c for c in ("aubel", "aupos", "matnr", "fkimg", "vrkme", "shkzg")
        if has_column(item, c)
    )
    select = [
        'TRIM(CAST(i."vbeln" AS TEXT)) AS "billing_document"',
        'TRIM(CAST(i."posnr" AS TEXT)) AS "billing_item"',
        'TRIM(CAST(h."fkdat" AS TEXT)) AS "billing_date"',
        f'SUM({amount}) AS "billing_item_net_value"',
    ]
    joins = [
        f'JOIN "{header}" h ON i."mandt" = h."mandt" '
        'AND LPAD(TRIM(CAST(i."vbeln" AS TEXT)), 10, \'0\') '
        '= LPAD(TRIM(CAST(h."vbeln" AS TEXT)), 10, \'0\')'
    ]
    if has_column(header, "kunag"):
        select.append('TRIM(CAST(h."kunag" AS TEXT)) AS "customer_id"')
        if has_table("KNA1") and has_column("KNA1", "kunnr"):
            joins.append(
                'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(h."kunag" AS TEXT)), 10, \'0\') '
                '= LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
            )
            if has_column("KNA1", "name1"):
                select.append('TRIM(c."name1") AS "customer_name"')
    if has_column(item, "matnr"):
        select.append('TRIM(CAST(i."matnr" AS TEXT)) AS "material_id"')
    currency_col = next((c for c in ("waerk", "waers") if has_column(header, c)), None)
    if currency_col:
        select.append(f'TRIM(CAST(h."{currency_col}" AS TEXT)) AS "currency"')
    if has_column(item, "shkzg"):
        select.append('TRIM(CAST(i."shkzg" AS TEXT)) AS "debit_credit_indicator"')

    where = [f"{amount} IS NOT NULL"]
    if re.search(r"\bnegative\b", q):
        where.append(f"{amount} < 0")
    years = extract_question_years(question)
    if years:
        where.append(_sap_year_predicate("h", "fkdat", years))
    grouped = [
        re.sub(r'\s+AS\s+"[^"]+"\s*$', "", column, flags=re.I)
        for column in select
        if not column.startswith("SUM(")
    ]
    return (
        'WITH "billing_item_rows" AS (\n'
        '  SELECT DISTINCT ' + ", ".join(f'src."{c}"' for c in row_columns) +
        f' FROM "{item}" src\n'
        ')\nSELECT ' + ", ".join(select) +
        '\nFROM "billing_item_rows" i\n' + "\n".join(joins) +
        '\nWHERE ' + "\n  AND ".join(where) +
        '\nGROUP BY ' + ", ".join(grouped) +
        f'\nORDER BY SUM({amount}) {direction}, "billing_document", "billing_item"\nLIMIT {limit}'
    )


def build_unbilled_order_items_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """List sales-order items without directly linked billing items."""
    q = (question or "").lower()
    if not (
        re.search(r"\bsales[- ]order\s+items?\b", q)
        and re.search(r"\b(no|without|unbilled|not\s+billed)\b", q)
        and re.search(r"\b(billing|invoice)\s+items?\b", q)
    ):
        return None
    if not all(has_table(t) for t in ("VBAP", "VBRP")):
        return None
    order_item = resolve_table_name("VBAP") or "VBAP"
    billing_item = resolve_table_name("VBRP") or "VBRP"
    needed = (
        (order_item, ("mandt", "vbeln", "posnr")),
        (billing_item, ("mandt", "aubel", "aupos")),
    )
    if any(not has_column(table, column) for table, cols in needed for column in cols):
        return None

    row_columns = ["mandt", "vbeln", "posnr"]
    row_columns.extend(
        c for c in ("netwr", "matnr", "kwmeng", "vrkme", "waerk") if has_column(order_item, c)
    )
    select = [
        'TRIM(CAST(i."vbeln" AS TEXT)) AS "sales_order"',
        'TRIM(CAST(i."posnr" AS TEXT)) AS "sales_order_item"',
    ]
    if has_column(order_item, "matnr"):
        select.append('TRIM(CAST(i."matnr" AS TEXT)) AS "material_id"')
    if has_column(order_item, "netwr"):
        select.append(
            'CAST(NULLIF(TRIM(CAST(i."netwr" AS TEXT)), \'\') AS NUMERIC) AS "ordered_net_value"'
        )
    if has_column(order_item, "kwmeng"):
        select.append(
            'CAST(NULLIF(TRIM(CAST(i."kwmeng" AS TEXT)), \'\') AS NUMERIC) AS "ordered_quantity"'
        )
    if has_column(order_item, "waerk"):
        select.append('TRIM(CAST(i."waerk" AS TEXT)) AS "currency"')
    billing_match = (
        'p."mandt" = i."mandt" AND '
        'LPAD(TRIM(CAST(p."aubel" AS TEXT)), 10, \'0\') '
        '= LPAD(TRIM(CAST(i."vbeln" AS TEXT)), 10, \'0\') AND '
        'LPAD(TRIM(CAST(p."aupos" AS TEXT)), 6, \'0\') '
        '= LPAD(TRIM(CAST(i."posnr" AS TEXT)), 6, \'0\')'
    )
    requested_order = re.search(
        r"\b(?:order|sales\s+order)(?:\s+(?:number|id|#))?\s*[:#]?\s*['\"]?(\d{6,12})\b",
        question,
        re.I,
    )
    scope = ""
    if requested_order:
        value = requested_order.group(1).replace("'", "''")
        scope = (
            '\n  AND LPAD(TRIM(CAST(i."vbeln" AS TEXT)), 10, \'0\') '
            f"= LPAD('{value}', 10, '0')"
        )
    try:
        limit = extract_ranking_limit(question, default=200)
    except Exception:
        limit = 200
    limit = max(1, min(int(limit), 500))
    return (
        'WITH "order_item_rows" AS (\n'
        '  SELECT DISTINCT ' + ", ".join(f'src."{c}"' for c in row_columns) +
        f' FROM "{order_item}" src\n'
        ')\nSELECT ' + ", ".join(select) +
        '\nFROM "order_item_rows" i\n'
        f'WHERE NOT EXISTS (SELECT 1 FROM "{billing_item}" p WHERE {billing_match})'
        + scope +
        '\nORDER BY i."vbeln", i."posnr"' +
        f'\nLIMIT {limit}'
    )


def build_order_item_billing_reconciliation_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Compare ordered item net values with amounts on directly linked billing items.

    The order and billing facts are deduplicated and aggregated independently
    at client/order/item/currency grain before they are joined. This supports
    split and partial billing without multiplying the ordered item amount.
    """
    q = question or ""
    if not (
        re.search(r"\b(?:compare|reconcile|difference|versus|vs\.?|against)\b", q, re.I)
        and re.search(r"\border[- ]items?\b", q, re.I)
        and re.search(r"\b(?:billing|invoice)[- ]items?\b", q, re.I)
        and re.search(r"\b(?:net\s+values?|amounts?|netwr|values?)\b", q, re.I)
    ):
        return None
    if not all(has_table(t) for t in ("VBAP", "VBRP", "VBRK")):
        return None
    order, item, header = (
        resolve_table_name(name) or name for name in ("VBAP", "VBRP", "VBRK")
    )
    if any(not has_column(table, col) for table, cols in (
        (order, ("mandt", "vbeln", "posnr", "netwr", "waerk")),
        (item, ("mandt", "vbeln", "posnr", "aubel", "aupos", "netwr")),
        (header, ("mandt", "vbeln", "waerk")),
    ) for col in cols):
        return None

    requested_order = re.search(
        r"\b(?:order|sales\s+order)(?:\s+(?:number|id|#))?\s*[:#]?\s*['\"]?(\d{6,12})\b",
        q, re.I,
    )
    order_filter = ""
    invoice_filter = ""
    if requested_order:
        value = requested_order.group(1).replace("'", "''")
        normalized = f"LPAD(TRIM(CAST(\"VBAP\".\"vbeln\" AS TEXT)), 10, '0') = LPAD('{value}', 10, '0')"
        order_filter = f" WHERE {normalized}"
        invoice_filter = (
            f" AND LPAD(TRIM(CAST(i.\"aubel\" AS TEXT)), 10, '0') = LPAD('{value}', 10, '0')"
        )

    item_attrs = [col for col in ("shkzg",) if has_column(item, col)]
    billing_distinct = [
        'i."mandt"', 'i."vbeln" AS "billing_document"', 'i."posnr" AS "billing_item"',
        'i."aubel" AS "order_document"', 'i."aupos" AS "order_item"', 'i."netwr"',
        'h."waerk" AS "currency"',
    ]
    billing_distinct.extend(f'i."{col}"' for col in item_attrs)
    if has_column(header, "vbtyp"):
        billing_distinct.append('h."vbtyp"')
    order_distinct = ['"mandt"', '"vbeln"', '"posnr"', '"netwr"', '"waerk"']
    billing_row_key = ["mandt", "billing_document", "billing_item", "order_document", "order_item", "netwr", "currency", *item_attrs]
    order_amount = 'CAST(NULLIF(TRIM(CAST("netwr" AS TEXT)), \'\') AS NUMERIC)'
    billing_amount = 'CAST(NULLIF(TRIM(CAST("netwr" AS TEXT)), \'\') AS NUMERIC)'
    return (
        'WITH "order_item_rows" AS (\n'
        '  SELECT DISTINCT ' + ', '.join(f'"VBAP".{col}' for col in order_distinct) +
        f' FROM "{order}" AS "VBAP"{order_filter}\n'
        '), "billing_headers" AS (\n'
        f'  SELECT "mandt", "vbeln", MAX("waerk") AS "waerk"{", MAX(\"vbtyp\") AS \"vbtyp\"" if has_column(header, "vbtyp") else ""} FROM "{header}" GROUP BY "mandt", "vbeln"\n'
        '), "billing_item_rows" AS (\n'
        '  SELECT DISTINCT ' + ', '.join(billing_distinct) +
        f' FROM "{item}" AS i JOIN "billing_headers" AS h '
        'ON h."mandt" = i."mandt" AND h."vbeln" = i."vbeln"\n'
        '  WHERE NULLIF(TRIM(CAST(i."aubel" AS TEXT)), \'\') IS NOT NULL '
        'AND NULLIF(TRIM(CAST(i."aupos" AS TEXT)), \'\') IS NOT NULL'
        + invoice_filter + '\n'
        '), "order_values" AS (\n'
        '  SELECT "mandt", "vbeln", "posnr", "waerk" AS "currency", '
        f'SUM({order_amount}) AS "order_item_net_value", COUNT(*) FILTER (WHERE {order_amount} IS NULL) AS "missing_order_amount_count"\n'
        '  FROM "order_item_rows" GROUP BY "mandt", "vbeln", "posnr", "waerk"\n'
        '), "billing_values" AS (\n'
        '  SELECT "mandt", "order_document", "order_item", "currency", '
        f'SUM({billing_amount}) AS "linked_billing_item_net_value", COUNT(*) AS "linked_billing_item_count", '
        'COUNT(DISTINCT "billing_document") AS "linked_billing_document_count"\n'
        '  FROM "billing_item_rows" GROUP BY "mandt", "order_document", "order_item", "currency"\n'
        ')\n'
        'SELECT COALESCE(o."mandt", b."mandt") AS "client", '
        'COALESCE(o."vbeln", b."order_document") AS "sales_order", '
        'COALESCE(o."posnr", b."order_item") AS "sales_order_item", '
        'o."currency" AS "order_currency", b."currency" AS "billing_currency", '
        'o."order_item_net_value", b."linked_billing_item_net_value", '
        'b."linked_billing_item_count", b."linked_billing_document_count", '
        'CASE WHEN o."currency" = b."currency" AND o."missing_order_amount_count" = 0 '
        'THEN o."order_item_net_value" - b."linked_billing_item_net_value" END AS "order_minus_billed_value", '
        'CASE WHEN o."vbeln" IS NULL THEN \'Billing item without matched order item\' '
        'WHEN b."order_document" IS NULL THEN \'Order item without linked billing item\' '
        'WHEN o."currency" <> b."currency" THEN \'Currency differs; amounts not subtracted\' '
        'ELSE \'Compared at order-item and currency grain\' END AS "comparison_status" '
        'FROM "order_values" o FULL OUTER JOIN "billing_values" b '
        'ON o."mandt" = b."mandt" AND o."vbeln" = b."order_document" '
        'AND o."posnr" = b."order_item" AND o."currency" = b."currency"\n'
        'ORDER BY "sales_order", "sales_order_item", "order_currency", "billing_currency"'
    )


def build_linked_order_invoice_totals_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Compare all sales-order and linked-invoice header values by client/currency."""
    q = question or ""
    if not (
        re.search(r"\b(?:compare|reconcile|difference|versus|vs\.?|against)\b", q, re.I)
        and re.search(r"\bsales\s+orders?\b", q, re.I)
        and re.search(r"\b(?:linked\s+)?invoices?\b", q, re.I)
        and re.search(r"\b(?:net\s+values?|amounts?|netwr|values?)\b", q, re.I)
        and not re.search(r"\border[- ]items?\b|\bbilling[- ]items?\b|\binvoice[- ]items?\b", q, re.I)
    ):
        return None
    if not all(has_table(t) for t in ("VBAK", "VBFA", "VBRK")):
        return None
    order, flow, invoice = (
        resolve_table_name(name) or name for name in ("VBAK", "VBFA", "VBRK")
    )
    if any(not has_column(table, col) for table, cols in (
        (order, ("mandt", "vbeln", "netwr", "waerk")),
        (flow, ("mandt", "vbelv", "vbeln")),
        (invoice, ("mandt", "vbeln", "netwr", "waerk")),
    ) for col in cols):
        return None

    def document_type(alias: str, table: str, col: str, value: str) -> str:
        return f' AND {alias}."{col}" = \'{value}\'' if has_column(table, col) else ""

    order_type = document_type('o', order, "vbtyp", "C")
    invoice_type = document_type('k', invoice, "vbtyp", "M")
    flow_types = (
        document_type('f', flow, "vbtyp_v", "C")
        + document_type('f', flow, "vbtyp_n", "M")
    )
    cancelled_filter = (
        ' AND COALESCE(TRIM(CAST("fksto" AS TEXT)), \'\') <> \'X\''
        if has_column(invoice, "fksto") else ""
    )
    amount_o = 'CAST(NULLIF(TRIM(CAST("net_value" AS TEXT)), \'\') AS NUMERIC)'
    amount_i = 'CAST(NULLIF(TRIM(CAST("net_value" AS TEXT)), \'\') AS NUMERIC)'
    return (
        'WITH "order_rows" AS (\n'
        f'  SELECT DISTINCT "mandt", "vbeln", "waerk" AS "currency", "netwr" AS "net_value" FROM "{order}" o\n'
        f'  WHERE 1 = 1{order_type}\n'
        '), "invoice_rows" AS (\n'
        f'  SELECT DISTINCT k."mandt", k."vbeln", k."waerk" AS "currency", k."netwr" AS "net_value" FROM "{invoice}" k\n'
        f'  WHERE 1 = 1{invoice_type}{cancelled_filter}\n'
        '    AND EXISTS (SELECT 1 FROM "' + flow + '" f JOIN "order_rows" o '
        'ON o."mandt" = f."mandt" AND o."vbeln" = f."vbelv" '
        'WHERE f."mandt" = k."mandt" AND f."vbeln" = k."vbeln"' + flow_types + ')\n'
        '), "order_totals" AS (\n'
        f'  SELECT "mandt", "currency", COUNT(*) AS "sales_order_count", SUM({amount_o}) AS "sales_order_net_value", '
        f'COUNT(*) FILTER (WHERE {amount_o} IS NULL) AS "missing_order_amount_count"\n'
        '  FROM "order_rows" GROUP BY "mandt", "currency"\n'
        '), "invoice_totals" AS (\n'
        f'  SELECT "mandt", "currency", COUNT(*) AS "linked_invoice_count", SUM({amount_i}) AS "linked_invoice_net_value", '
        f'COUNT(*) FILTER (WHERE {amount_i} IS NULL) AS "missing_invoice_amount_count"\n'
        '  FROM "invoice_rows" GROUP BY "mandt", "currency"\n'
        ')\n'
        'SELECT COALESCE(o."mandt", i."mandt") AS "client", '
        'COALESCE(o."currency", i."currency") AS "currency", '
        'o."sales_order_count", i."linked_invoice_count", '
        'o."sales_order_net_value", i."linked_invoice_net_value", '
        'CASE WHEN o."currency" = i."currency" AND o."missing_order_amount_count" = 0 '
        'AND i."missing_invoice_amount_count" = 0 '
        'THEN o."sales_order_net_value" - i."linked_invoice_net_value" END AS "order_minus_invoice_net_value", '
        'CASE WHEN o."sales_order_count" IS NULL THEN \'Linked invoices only at this currency\' '
        'WHEN i."linked_invoice_count" IS NULL THEN \'Sales orders only at this currency\' '
        'ELSE \'Compared separately by client and currency\' END AS "comparison_status", '
        '\'All available dates; sales-order and invoice headers; document-flow-linked invoices; cancelled originals excluded; no currency conversion\' AS "comparison_scope" '
        'FROM "order_totals" o FULL OUTER JOIN "invoice_totals" i '
        'ON o."mandt" = i."mandt" AND o."currency" = i."currency"\n'
        'ORDER BY "client", "currency"'
    )


def build_sales_order_invoice_customer_comparison_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
    *,
    catalog_schema: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Build year-scoped order/invoice comparisons at the requested business grain.

    Header totals remain at customer/country grain. Product and cost/profit
    comparisons use independently aggregated order/invoice item facts. Order
    and invoice dates remain independent, and cross-currency differences are
    never calculated.
    """
    q = question or ""
    if catalog_schema is None:
        table_exists, column_exists, table_name = has_table, has_column, resolve_table_name
    else:
        names = {name.upper(): name for name in catalog_schema}
        for canonical in ("VBAK", "VBRK", "KNA1", "VBAP", "VBRP", "MARA"):
            if canonical in catalog_schema:
                names[canonical] = canonical
        fields = {name: {c["col"].lower() for c in catalog_schema[physical]} for name, physical in names.items()}
        table_exists = lambda name: name.upper() in names
        column_exists = lambda name, column: column.lower() in fields.get(name.upper(), set())
        table_name = lambda name: names.get(name.upper())
    wants_product = bool(re.search(r"\b(?:products?|materials?)\b", q, re.I))
    wants_region = bool(re.search(r"\bregions?\b", q, re.I))
    wants_customer = bool(re.search(r"\bcustomers?\b", q, re.I))
    wants_country = bool(re.search(r"\bcountr(?:y|ies)\b", q, re.I))
    if not (
        re.search(r"\b(?:compare|comparison|difference|differences|versus|vs\.?|against)\b", q, re.I)
        and re.search(r"\b(?:(?:sales\s+)?orders?)\b", q, re.I)
        and re.search(r"\binvoices?\b", q, re.I)
        and re.search(r"\b(?:value|values|amount|amounts|net|sales|revenue|costs?|profits?)\b", q, re.I)
        and not re.search(r"\blinked\b|\breconcil", q, re.I)
    ):
        return None

    years = extract_question_years(question)
    if not years:
        return None

    # Item facts are required to compare individual products. Country/customer/
    # region facts can be carried alongside them through the shared customer
    # dimension; the year and currency remain part of every comparison key.
    asks_cost_or_profit = bool(re.search(r"\b(?:costs?|profits?|profitability)\b", q, re.I))
    if wants_product or wants_region or asks_cost_or_profit or not (wants_country and wants_customer):
        return _build_sales_order_invoice_grouped_comparison_sql(
            q,
            years,
            table_exists=table_exists,
            column_exists=column_exists,
            table_name=table_name,
            wants_product=wants_product,
            wants_customer=wants_customer,
            wants_country=wants_country,
            wants_region=wants_region,
        )

    if not all(table_exists(name) for name in ("VBAK", "VBRK", "KNA1")):
        return None

    order, invoice, customer = (
        table_name(name) or name for name in ("VBAK", "VBRK", "KNA1")
    )
    required = (
        (order, ("mandt", "vbeln", "kunnr", "audat", "netwr", "waerk")),
        (invoice, ("mandt", "vbeln", "kunag", "fkdat", "netwr", "waerk")),
        (customer, ("mandt", "kunnr", "land1")),
    )
    if any(not column_exists(table, column) for table, columns in required for column in columns):
        return None

    # The connector identifies a range by its language or dash separator. Two
    # years joined by a plain "and" remain a discrete selection.
    year_pair = re.search(r"\b(?:between|from)\s+(20\d{2}|19\d{2})\s+(?:and|to|through|until)\s+(20\d{2}|19\d{2})\b", q, re.I)
    if not year_pair:
        year_pair = re.search(r"\b(20\d{2}|19\d{2})\s+(?:to|through|until)\s+(20\d{2}|19\d{2})\b", q, re.I)
    if not year_pair:
        year_pair = re.search(r"\b(20\d{2}|19\d{2})\s*[-–—]\s*(20\d{2}|19\d{2})\b", q)
    if year_pair:
        first, last = sorted((year_pair.group(1), year_pair.group(2)))
        order_year_filter = (
            f'SUBSTRING(TRIM(CAST(o."audat" AS TEXT)), 1, 4) BETWEEN \'{first}\' AND \'{last}\''
        )
        invoice_year_filter = (
            f'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4) BETWEEN \'{first}\' AND \'{last}\''
        )
    else:
        order_year_filter = _sap_year_predicate('o', "audat", years)
        invoice_year_filter = _sap_year_predicate('k', "fkdat", years)
    if not order_year_filter or not invoice_year_filter:
        return None

    order_year = 'SUBSTRING(TRIM(CAST(o."audat" AS TEXT)), 1, 4)'
    invoice_year = 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4)'
    customer_name = (
        'COALESCE(MAX(TRIM(CAST(c."name1" AS TEXT))), \'\') AS "customer_name"'
        if column_exists(customer, "name1") else '\'\' AS "customer_name"'
    )
    invoice_cancelled_filter = (
        ' AND COALESCE(TRIM(CAST(k."fksto" AS TEXT)), \'\') <> \'X\''
        if column_exists(invoice, "fksto") else ""
    )

    return (
        'WITH "customer_dim" AS (\n'
        '  SELECT c."mandt", c."kunnr", LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\') AS "customer_id", '
        'MAX(TRIM(CAST(c."land1" AS TEXT))) AS "country_code", '
        f'{customer_name}\n'
        f'  FROM "{customer}" c\n'
        '  GROUP BY c."mandt", c."kunnr"\n'
        '), "order_rows" AS (\n'
        '  SELECT DISTINCT o."mandt", o."vbeln", c."customer_id", c."country_code", '
        f'c."customer_name", {order_year} AS "year", o."waerk" AS "currency", o."netwr" AS "netwr"\n'
        f'  FROM "{order}" o JOIN "customer_dim" c ON c."mandt" = o."mandt" '
        'AND c."kunnr" = o."kunnr"\n'
        f'  WHERE {order_year_filter} AND NULLIF(TRIM(CAST(o."audat" AS TEXT)), \'\') IS NOT NULL\n'
        '), "invoice_rows" AS (\n'
        '  SELECT DISTINCT k."mandt", k."vbeln", c."customer_id", c."country_code", '
        f'c."customer_name", {invoice_year} AS "year", k."waerk" AS "currency", k."netwr" AS "netwr"\n'
        f'  FROM "{invoice}" k JOIN "customer_dim" c ON c."mandt" = k."mandt" '
        'AND c."kunnr" = k."kunag"\n'
        f'  WHERE {invoice_year_filter} AND NULLIF(TRIM(CAST(k."fkdat" AS TEXT)), \'\') IS NOT NULL'
        f'{invoice_cancelled_filter}\n'
        '), "order_totals" AS (\n'
        '  SELECT r."mandt" AS "client", r."customer_id", r."country_code", r."customer_name", r."year", r."currency", '
        'COUNT(*) AS "sales_order_count", '
        'SUM(CAST(NULLIF(TRIM(CAST(r."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "sales_order_net_value"\n'
        '  FROM "order_rows" r GROUP BY r."mandt", r."customer_id", r."country_code", '
        'r."customer_name", r."year", r."currency"\n'
        '), "invoice_totals" AS (\n'
        '  SELECT r."mandt" AS "client", r."customer_id", r."country_code", r."customer_name", r."year", r."currency", '
        'COUNT(*) AS "invoice_count", '
        'SUM(CAST(NULLIF(TRIM(CAST(r."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "invoice_net_value"\n'
        '  FROM "invoice_rows" r GROUP BY r."mandt", r."customer_id", r."country_code", '
        'r."customer_name", r."year", r."currency"\n'
        ')\n'
        'SELECT COALESCE(o."client", i."client") AS "client", '
        'COALESCE(o."year", i."year") AS "year", '
        'COALESCE(o."country_code", i."country_code") AS "country_code", '
        'COALESCE(o."customer_id", i."customer_id") AS "customer_id", '
        'COALESCE(o."customer_name", i."customer_name") AS "customer_name", '
        'COALESCE(o."currency", i."currency") AS "currency", '
        'o."client" AS "sales_order_client", i."client" AS "invoice_client", '
        'o."currency" AS "sales_order_currency", i."currency" AS "invoice_currency", '
        'o."sales_order_count", i."invoice_count", '
        'o."sales_order_net_value", i."invoice_net_value", '
        'CASE WHEN o."currency" = i."currency" '
        'AND o."sales_order_net_value" IS NOT NULL AND i."invoice_net_value" IS NOT NULL '
        'THEN o."sales_order_net_value" - i."invoice_net_value" END AS "order_minus_invoice_net_value", '
        'CASE WHEN o."client" IS NULL THEN \'Invoices only for this customer/year/currency\' '
        'WHEN i."client" IS NULL THEN \'Sales orders only for this customer/year/currency\' '
        'ELSE \'Compared by customer, document year, client and currency\' END AS "comparison_status", '
        '\'Order date: AUDAT; invoice date: FKDAT; independent customer/year totals; no document-flow reconciliation or currency conversion\' AS "comparison_scope"\n'
        'FROM "order_totals" o FULL OUTER JOIN "invoice_totals" i '
        # PostgreSQL needs a hash/merge equality for a FULL JOIN. MANDT is
        # non-null after the customer joins; nullable descriptive keys below
        # still use null-safe equality. Expose both clients for the grain proof.
        'ON o."client" = i."client" '
        'AND o."customer_id" IS NOT DISTINCT FROM i."customer_id" '
        'AND o."country_code" IS NOT DISTINCT FROM i."country_code" '
        'AND o."customer_name" IS NOT DISTINCT FROM i."customer_name" '
        'AND o."year" IS NOT DISTINCT FROM i."year" '
        'AND o."currency" IS NOT DISTINCT FROM i."currency"\n'
        'ORDER BY ABS(COALESCE(o."sales_order_net_value", 0) - COALESCE(i."invoice_net_value", 0)) DESC, '
        '"country_code", "customer_id", "year", "currency"\n'
        'LIMIT 200'
    )


def _build_sales_order_invoice_grouped_comparison_sql(
    question: str,
    years: list[str],
    *,
    table_exists: Callable[[str], bool],
    column_exists: Callable[[str, str], bool],
    table_name: Callable[[str], Optional[str]],
    wants_product: bool,
    wants_customer: bool,
    wants_country: bool,
    wants_region: bool,
) -> Optional[str]:
    """Build a currency-safe independent-fact comparison at requested detail."""
    order, invoice = table_name("VBAK") or "VBAK", table_name("VBRK") or "VBRK"
    if not (table_exists("VBAK") and table_exists("VBRK")):
        return None

    item_order = table_name("VBAP") or "VBAP"
    item_invoice = table_name("VBRP") or "VBRP"
    customer = table_name("KNA1") or "KNA1"
    material = table_name("MARA") or "MARA"
    needs_customer = wants_customer or wants_country or wants_region
    needs_country = wants_country or wants_region
    asks_cost_or_profit = bool(re.search(r"\b(?:costs?|profits?|profitability)\b", question, re.I))
    item_level = wants_product or asks_cost_or_profit

    required = [
        (order, ("mandt", "vbeln", "audat", "netwr", "waerk")),
        (invoice, ("mandt", "vbeln", "fkdat", "netwr", "waerk")),
    ]
    if needs_customer:
        required.extend([
            (order, ("kunnr",)), (invoice, ("kunag",)),
            (customer, ("mandt", "kunnr")),
        ])
        if needs_country:
            required.append((customer, ("land1",)))
        if wants_region:
            required.append((customer, ("regio",)))
    if item_level:
        required.extend([
            (item_order, ("mandt", "vbeln", "posnr", "netwr")),
            (item_invoice, ("mandt", "vbeln", "posnr", "netwr")),
        ])
        if wants_product:
            required.extend([(item_order, ("matnr",)), (item_invoice, ("matnr",))])
            required.append((material, ("mandt", "matnr")))
    if any(not table_exists(table) or any(not column_exists(table, col) for col in columns)
           for table, columns in required):
        return None

    cost_available = (
        item_level
        and column_exists(item_order, "wavwr")
        and column_exists(item_invoice, "wavwr")
    )
    if asks_cost_or_profit and not cost_available:
        return None

    year_pair = re.search(
        r"\b(?:between|from)\s+(20\d{2}|19\d{2})\s+(?:and|to|through|until)\s+(20\d{2}|19\d{2})\b",
        question, re.I,
    ) or re.search(r"\b(20\d{2}|19\d{2})\s+(?:to|through|until)\s+(20\d{2}|19\d{2})\b", question, re.I) \
      or re.search(r"\b(20\d{2}|19\d{2})\s*[-–—]\s*(20\d{2}|19\d{2})\b", question)
    if year_pair:
        first, last = sorted((year_pair.group(1), year_pair.group(2)))
        order_filter = f'SUBSTRING(TRIM(CAST(h."audat" AS TEXT)), 1, 4) BETWEEN \'{first}\' AND \'{last}\''
        invoice_filter = f'SUBSTRING(TRIM(CAST(h."fkdat" AS TEXT)), 1, 4) BETWEEN \'{first}\' AND \'{last}\''
    else:
        order_filter = _sap_year_predicate("h", "audat", years)
        invoice_filter = _sap_year_predicate("h", "fkdat", years)
    if not order_filter or not invoice_filter:
        return None

    customer_dim = ""
    customer_join_order = ""
    customer_join_invoice = ""
    dimensions: list[tuple[str, str]] = []
    if wants_customer:
        dimensions.append(("customer_id", 'c."customer_id"'))
    if needs_country:
        dimensions.append(("country_code", 'c."country_code"'))
    if wants_region:
        dimensions.append(("region_code", 'c."region_code"'))
    if needs_customer:
        country_expr = (
            'MAX(TRIM(CAST(c."land1" AS TEXT))) AS "country_code"'
            if column_exists(customer, "land1") else "NULL AS \"country_code\""
        )
        region_expr = (
            'MAX(TRIM(CAST(c."regio" AS TEXT))) AS "region_code"'
            if column_exists(customer, "regio") else "NULL AS \"region_code\""
        )
        name_expr = (
            'MAX(TRIM(CAST(c."name1" AS TEXT))) AS "customer_name"'
            if column_exists(customer, "name1") else "'' AS \"customer_name\""
        )
        customer_dim = (
            '"customer_dim" AS (SELECT c."mandt", c."kunnr", '
            'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\') AS "customer_id", '
            f'{country_expr}, {region_expr}, {name_expr} FROM "{customer}" c '
            'GROUP BY c."mandt", c."kunnr")'
        )
        customer_join_order = (
            ' LEFT JOIN "customer_dim" c ON c."mandt" = h."mandt" AND c."kunnr" = h."kunnr"'
        )
        customer_join_invoice = (
            ' LEFT JOIN "customer_dim" c ON c."mandt" = h."mandt" AND c."kunnr" = h."kunag"'
        )

    def row_dimensions(customer_column: str) -> str:
        values = []
        for name, expr in dimensions:
            if name == "customer_id":
                expr = (
                    f'COALESCE(c."customer_id", '
                    f'LPAD(TRIM(CAST(h."{customer_column}" AS TEXT)), 10, \'0\'))'
                )
            values.append(f'{expr} AS "{name}"')
        if wants_product:
            values.append('COALESCE(m."matnr", p."matnr") AS "product_id"')
        return ", ".join(values)

    order_row_dims_sql = row_dimensions("kunnr")
    invoice_row_dims_sql = row_dimensions("kunag")
    total_dims = ", ".join(f'r."{name}"' for name, _ in dimensions)
    total_select_dims = ", ".join(f'r."{name}" AS "{name}"' for name, _ in dimensions)
    output_dims = ", ".join(
        f'COALESCE(o."{name}", i."{name}") AS "{name}"' for name, _ in dimensions
    )
    join_dims = " ".join(
        f'AND o."{name}" IS NOT DISTINCT FROM i."{name}"' for name, _ in dimensions
    )
    grouping = ["r.\"mandt\"", *(total_dims.split(", ") if total_dims else []), 'r."year"', 'r."currency"']
    grouping_sql = ", ".join(grouping)
    order_year = 'SUBSTRING(TRIM(CAST(h."audat" AS TEXT)), 1, 4)'
    invoice_year = 'SUBSTRING(TRIM(CAST(h."fkdat" AS TEXT)), 1, 4)'
    order_item_join = (
        f' JOIN "{item_order}" p ON p."mandt" = h."mandt" AND p."vbeln" = h."vbeln"'
        if item_level else ""
    )
    invoice_item_join = (
        f' JOIN "{item_invoice}" p ON p."mandt" = h."mandt" AND p."vbeln" = h."vbeln"'
        if item_level else ""
    )
    material_join = (
        f' LEFT JOIN "{material}" m ON m."mandt" = p."mandt" AND m."matnr" = p."matnr"'
        if wants_product else ""
    )
    product_dim = [('product_id', 'COALESCE(m."matnr", p."matnr")')] if wants_product else []
    all_dims = [*dimensions, *product_dim]
    if item_level:
        total_dims = ", ".join(f'r."{name}"' for name, _ in all_dims)
        total_select_dims = ", ".join(f'r."{name}" AS "{name}"' for name, _ in all_dims)
        output_dims = ", ".join(
            f'COALESCE(o."{name}", i."{name}") AS "{name}"' for name, _ in all_dims
        )
        join_dims = " ".join(
            f'AND o."{name}" IS NOT DISTINCT FROM i."{name}"' for name, _ in all_dims
        )
        grouping = ["r.\"mandt\"", *(total_dims.split(", ") if total_dims else []), 'r."year"', 'r."currency"']
        grouping_sql = ", ".join(grouping)
    order_amount = 'p."netwr"' if item_level else 'h."netwr"'
    invoice_amount = 'p."netwr"' if item_level else 'h."netwr"'
    cost_projection = ', p."wavwr" AS "wavwr"' if cost_available else ""
    cost_sums_order = (
        ', SUM(CAST(NULLIF(TRIM(CAST(r."wavwr" AS TEXT)), \'\') AS NUMERIC)) AS "sales_order_cost"'
        if cost_available else ""
    )
    cost_sums_invoice = (
        ', SUM(CAST(NULLIF(TRIM(CAST(r."wavwr" AS TEXT)), \'\') AS NUMERIC)) AS "invoice_cost"'
        if cost_available else ""
    )
    order_count_name = "sales_order_item_count" if item_level else "sales_order_count"
    invoice_count_name = "invoice_item_count" if item_level else "invoice_count"
    output_cost = ""
    if cost_available:
        output_cost = (
            ', o."sales_order_cost", i."invoice_cost", '
            'CASE WHEN o."currency" = i."currency" AND o."sales_order_cost" IS NOT NULL '
            'AND i."invoice_cost" IS NOT NULL THEN o."sales_order_cost" - i."invoice_cost" '
            'END AS "order_minus_invoice_cost", '
            'o."sales_order_net_value" - o."sales_order_cost" AS "sales_order_profit", '
            'i."invoice_net_value" - i."invoice_cost" AS "invoice_profit", '
            'CASE WHEN o."currency" = i."currency" AND o."sales_order_net_value" IS NOT NULL '
            'AND i."invoice_net_value" IS NOT NULL AND o."sales_order_cost" IS NOT NULL '
            'AND i."invoice_cost" IS NOT NULL THEN '
            '(o."sales_order_net_value" - o."sales_order_cost") - '
            '(i."invoice_net_value" - i."invoice_cost") END AS "order_minus_invoice_profit"'
        )

    cancelled_filter = (
        ' AND COALESCE(TRIM(CAST(h."fksto" AS TEXT)), \'\') <> \'X\''
        if column_exists(invoice, "fksto") else ""
    )
    order_total_dims = f", {total_select_dims}" if total_select_dims else ""
    pos_projection = f', p."posnr" AS "posnr"' if item_level else ""
    material_join_order = material_join
    material_join_invoice = material_join
    prefix = f'WITH {customer_dim}, ' if customer_dim else "WITH "
    return (
        prefix + '"order_rows" AS (SELECT DISTINCT h."mandt", h."vbeln"' + pos_projection +
        ', ' + order_year + ' AS "year", h."waerk" AS "currency", ' + order_amount + ' AS "netwr"' +
        cost_projection + (f', {order_row_dims_sql}' if order_row_dims_sql else "") +
        f' FROM "{order}" h{order_item_join}{material_join_order}{customer_join_order} '
        f'WHERE {order_filter} AND NULLIF(TRIM(CAST(h."audat" AS TEXT)), \'\') IS NOT NULL), '
        '"invoice_rows" AS (SELECT DISTINCT h."mandt", h."vbeln"' + pos_projection +
        ', ' + invoice_year + ' AS "year", h."waerk" AS "currency", ' + invoice_amount + ' AS "netwr"' +
        cost_projection + (f', {invoice_row_dims_sql}' if invoice_row_dims_sql else "") +
        f' FROM "{invoice}" h{invoice_item_join}{material_join_invoice}{customer_join_invoice} '
        f'WHERE {invoice_filter} AND NULLIF(TRIM(CAST(h."fkdat" AS TEXT)), \'\') IS NOT NULL{cancelled_filter}), '
        '"order_totals" AS (SELECT r."mandt" AS "client"' + order_total_dims +
        f', r."year", r."currency", COUNT(*) AS "{order_count_name}", ' +
        'SUM(CAST(NULLIF(TRIM(CAST(r."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "sales_order_net_value"' +
        cost_sums_order + f' FROM "order_rows" r GROUP BY {grouping_sql}), '
        '"invoice_totals" AS (SELECT r."mandt" AS "client"' + order_total_dims +
        f', r."year", r."currency", COUNT(*) AS "{invoice_count_name}", ' +
        'SUM(CAST(NULLIF(TRIM(CAST(r."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "invoice_net_value"' +
        cost_sums_invoice + f' FROM "invoice_rows" r GROUP BY {grouping_sql}) '
        'SELECT COALESCE(o."client", i."client") AS "client", '
        'o."client" AS "sales_order_client", i."client" AS "invoice_client", ' +
        (output_dims + ', ' if output_dims else "") +
        'COALESCE(o."year", i."year") AS "year", COALESCE(o."currency", i."currency") AS "currency", '
        'o."currency" AS "sales_order_currency", i."currency" AS "invoice_currency", '
        f'o."{order_count_name}", i."{invoice_count_name}", o."sales_order_net_value", i."invoice_net_value", ' +
        'CASE WHEN o."currency" = i."currency" AND o."sales_order_net_value" IS NOT NULL '
        'AND i."invoice_net_value" IS NOT NULL THEN o."sales_order_net_value" - i."invoice_net_value" '
        'END AS "order_minus_invoice_net_value"' + output_cost +
        ' FROM "order_totals" o FULL OUTER JOIN "invoice_totals" i '
        'ON o."client" = i."client" ' + join_dims +
        ' AND o."year" IS NOT DISTINCT FROM i."year" '
        'AND o."currency" IS NOT DISTINCT FROM i."currency" '
        'ORDER BY CASE WHEN o."currency" = i."currency" THEN '
        'ABS(o."sales_order_net_value" - i."invoice_net_value") END DESC NULLS LAST '
        'LIMIT 200'
    )


def build_industry_line_extreme_sql(question: str) -> Optional[str]:
    """Individual item minima/maxima, grouped without losing unknown industries."""
    from .analyst_line_metrics import billing_line_extreme

    operation = billing_line_extreme(question)
    if not operation or not re.search(r"\bindustr(?:y|ies)\b", question, re.I):
        return None
    # Only this complete shape is supported. Extra filters or dimensions must
    # continue through the general planner rather than being silently dropped.
    remainder = re.sub(r"\b(?:19|20)\d{2}\b", "", question.lower())
    remainder = re.sub(
        r"\b(?:show|me|the|what|are|is|find|give|lowest|smallest|minimum|highest|largest|maximum|"
        r"billing|invoice|invoices|line|lines|item|items|net|amount|amounts|value|values|"
        r"by|per|each|industry|industries|in|for|year|years|between|and|to|through|all)\b",
        "", remainder,
    )
    if re.sub(r"[\s,.?!–—-]", "", remainder):
        return None
    required = {"VBRK": ("mandt", "vbeln", "fkdat", "waerk", "kunag"),
                "vbrp": ("mandt", "vbeln", "posnr", "netwr"),
                "KNA1": ("mandt", "kunnr", "brsch")}
    if not all(has_table(t) and all(has_column(t, c) for c in columns)
               for t, columns in required.items()):
        return None
    header, item, customer = (resolve_table_name(t) or t for t in required)
    years = extract_question_years(question)
    if not years and re.search(r"\byears?\b", question, re.I) and not re.search(r"\ball years\b", question, re.I):
        return None
    if len(years) == 2 and re.search(r"\bbetween\b|\bto\b|\bthrough\b|[–—-]", question, re.I):
        years = [str(y) for y in range(min(map(int, years)), max(map(int, years)) + 1)]
    predicate = _sap_year_predicate("h", "fkdat", years)
    where = "\nWHERE " + predicate if predicate else ""
    alias = "lowest_billing_line_amount" if operation == "MIN" else "highest_billing_line_amount"
    # Keep the industry code as the grouping key. Missing master rows and
    # missing industry codes remain in the NULL group instead of disappearing.
    return (
        f'SELECT h."mandt" AS "client", '
        'SUBSTRING(TRIM(CAST(h."fkdat" AS TEXT)), 1, 4) AS "billing_year", '
        'h."waerk" AS "currency", NULLIF(TRIM(CAST(c."brsch" AS TEXT)), \'\') AS "industry_code", '
        f'{operation}(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "{alias}"\n'
        f'FROM "{item}" p JOIN "{header}" h ON h."mandt" = p."mandt" AND h."vbeln" = p."vbeln"\n'
        f'LEFT JOIN "{customer}" c ON c."mandt" = h."mandt" AND c."kunnr" = h."kunag"'
        + where
        + '\nGROUP BY h."mandt", SUBSTRING(TRIM(CAST(h."fkdat" AS TEXT)), 1, 4), '
        'h."waerk", NULLIF(TRIM(CAST(c."brsch" AS TEXT)), \'\')\n'
        'ORDER BY "client", "billing_year", "currency", "industry_code" LIMIT 200'
    )


def build_dimension_ranking_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
    *,
    limit: Optional[int] = None,
) -> Optional[str]:
    """
    Single-dimension ranking (country / industry / customer / material / vendor) for
    sales, quantity, invoice count, or purchase value — with optional year scoping.

    Uses VBRK header amounts for customer/country/industry to avoid line fan-out,
    vbrp line amounts for material-level and quantity measures, and EKPO/EKKO/LFA1
    for vendor / purchase-order value rankings.
    """
    q = (question or "").lower()
    from .analyst_line_metrics import billing_line_extreme
    if billing_line_extreme(question):
        return build_industry_line_extreme_sql(question)
    if not re.search(r"\b(top|bottom|highest|lowest|most|least|best|worst|largest|biggest|smallest|leading|rank|ranking|list)\b", q):
        return None
    # "List customers in Germany" is a filtered master list, not a sales ranking.
    if not re.search(r"\b(top|bottom|highest|lowest|most|least|best|worst|largest|biggest|smallest|leading|rank|ranking)\b", q):
        return None

    dimension = detect_ranking_dimension(question, semantic)
    if not dimension:
        return None
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
    ranking = req.get("ranking") if isinstance(req.get("ranking"), dict) else None
    if ranking and ranking.get("partition_by"):
        partitions = ranking.get("partition_by")
        if isinstance(partitions, str):
            partitions = [partitions]
        # Currency is a comparison-safety key, not a user-visible ranking
        # dimension. This builder already adds a currency partition for every
        # monetary rank, so it can satisfy the currency-partitioned Top-N too.
        unsupported_partitions = {
            str(value).strip().lower()
            for value in (partitions or [])
            if str(value).strip().lower() not in {"currency", "waerk", "waers", "rtcur"}
        }
        if unsupported_partitions:
            return None  # another partitioned Top-N template owns this shape
    # Multi-entity rankings (country+customer+industry) belong to the multidim builder.
    q_dims = sum(
        1
        for pat in (
            r"\b(countr(?:y|ies)|nations?|markets?)\b",
            r"\b(customers?|clients?|buyers?)\b",
            r"\b(industr(?:y|ies)|sectors?)\b",
        )
        if re.search(pat, q)
    )
    if q_dims >= 2 and re.search(r"\b(and|,)\b", q):
        return None
    measure = detect_ranking_measure(question, semantic)
    years = extract_question_years(question)
    resolved_tf = (req.get("semantic") or {}).get("time_filter") or {}
    if not years and resolved_tf.get("resolved_from_data") is True:
        years = [str(y) for y in (resolved_tf.get("years") or [])]
    if limit is None:
        limit = extract_ranking_limit(question)
    direction = ranking_direction(question)

    # --- Vendor invoice amount (RBKP + LFA1) ---
    if measure == "vendor_invoice_value" or (
        dimension == "vendor"
        and re.search(r"\binvoice\b", q)
        and not re.search(r"\b(purchase|po\b)\b", q)
    ):
        inv = _build_vendor_invoice_ranking_sql(
            question, limit=limit, direction=direction, years=years
        )
        if inv:
            return inv

    # --- Vendor / purchase-value path (EKPO + EKKO + LFA1) ---
    if dimension == "vendor" or measure == "purchase_value":
        return _build_vendor_purchase_ranking_sql(
            question, limit=limit, direction=direction, years=years
        )

    if not has_table("VBRK"):
        return None

    hdr = resolve_table_name("VBRK") or "VBRK"
    line = resolve_table_name("vbrp") or "vbrp"
    metric_def = None
    try:
        from .business_semantic_layer import METRICS

        metric_def = METRICS.get(measure)
    except Exception:
        metric_def = None
    if metric_def and metric_def.status != "supported":
        # Never reinterpret a known-but-unavailable metric as sales.
        return None
    # Choose the fact grain from the requested result, not from a metric's
    # broad set of possible source tables. Unqualified billed-sales rankings
    # by customer/country/industry use one VBRK header amount per invoice;
    # material and explicitly item-level views use VBRP line amounts.
    asks_item_grain = bool(
        re.search(r"\b(?:line[- ]items?|item[- ]level|billing[- ]items?|per item)\b", q)
    )
    use_line = dimension == "material" or measure == "quantity" or asks_item_grain
    if use_line and not has_table("vbrp"):
        return None

    sel: List[str] = []
    gb: List[str] = []
    joins: List[str] = []
    where: List[str] = []
    currency_rank = False

    if use_line:
        from_clause = 'FROM "billing_item_rows" p'
        joins.append(
            f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') '
            f'= LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')'
        )
        if has_column(line, "mandt") and has_column(hdr, "mandt"):
            joins[-1] += ' AND p."mandt" = k."mandt"'
    else:
        from_clause = f'FROM "{hdr}" k'

    needs_customer_master = dimension in {"country", "industry", "customer"}
    if needs_customer_master:
        if not has_table("KNA1") or not has_column(hdr, "kunag"):
            return None
        joins.append(
            'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') '
            '= LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
        )
        where.append('NULLIF(TRIM(CAST(k."kunag" AS TEXT)), \'\') IS NOT NULL')

    if dimension == "country":
        if not has_column("KNA1", "land1"):
            return None
        sel.append('TRIM(c."land1") AS "country"')
        gb.append('TRIM(c."land1")')
        where.append('NULLIF(TRIM(CAST(c."land1" AS TEXT)), \'\') IS NOT NULL')
    elif dimension == "industry":
        if has_table("T016T") and has_column("T016T", "brtxt") and has_column("KNA1", "brsch"):
            joins.append(
                'LEFT JOIN "T016T" t ON LPAD(TRIM(CAST(c."brsch" AS TEXT)), 10, \'0\') '
                '= LPAD(TRIM(CAST(t."brsch" AS TEXT)), 10, \'0\')'
            )
            sel.append('TRIM(t."brtxt") AS "industry"')
            gb.append('TRIM(t."brtxt")')
            where.append('NULLIF(TRIM(CAST(t."brtxt" AS TEXT)), \'\') IS NOT NULL')
        elif has_column("KNA1", "brsch"):
            sel.append('TRIM(c."brsch") AS "industry_code"')
            gb.append('TRIM(c."brsch")')
            where.append('NULLIF(TRIM(CAST(c."brsch" AS TEXT)), \'\') IS NOT NULL')
        else:
            return None
    elif dimension == "customer":
        if not has_column("KNA1", "kunnr"):
            return None
        sel.append('TRIM(c."kunnr") AS "customer_id"')
        gb.append('TRIM(c."kunnr")')
        if has_column("KNA1", "name1"):
            sel.append('TRIM(c."name1") AS "customer_name"')
            gb.append('TRIM(c."name1")')
    elif dimension == "material":
        if not has_column(line, "matnr"):
            return None
        sel.append('TRIM(p."matnr") AS "material_id"')
        gb.append('TRIM(p."matnr")')
        if has_table("MAKT") and has_column("MAKT", "maktx"):
            joins.append(_makt_join("p.\"matnr\""))
            sel.append('TRIM(m."maktx") AS "material_name"')
            gb.append('TRIM(m."maktx")')
        where.append('NULLIF(TRIM(CAST(p."matnr" AS TEXT)), \'\') IS NOT NULL')
    else:
        return None

    if metric_def and metric_def.formula_sql:
        # MetricDef formulas are curated and schema-backed. Adapt their logical
        # billing aliases to this query's aliases, then group by the metric's
        # currency field so rankings never combine unlike currencies.
        # The general revenue metric is line-grain, but invoice/customer/country
        # rankings need the billing document total so they agree with monthly
        # and invoice-level follow-ups. Product and explicitly item-level
        # requests continue to use the line-grain metric formula.
        if metric_def.name == "revenue":
            # The DB catalogue may expose SAP amount columns as native NUMERIC
            # even though imported demo extracts store them as text. Always cast
            # to text before TRIM so this shared metric works for both schemas.
            amount_alias = "p" if use_line else "k"
            formula = (
                f'SUM(CAST(NULLIF(TRIM(CAST({amount_alias}."netwr" AS TEXT)), \'\') AS NUMERIC))'
            )
        elif metric_def.name == "gross_profit" and use_line:
            # The curated metric formula is expressed with text-oriented SAP
            # aliases. Cast native numeric imports to text before TRIM so it
            # runs on both CSV-derived and normalized PostgreSQL schemas.
            formula = (
                'SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) '
                '- SUM(CAST(NULLIF(TRIM(CAST(COALESCE(p."wavwr", 0) AS TEXT)), \'\') AS NUMERIC))'
            )
        else:
            formula = metric_def.formula_sql
        alias_map = {"v": "p", "vk": "k"} if use_line else {"vk": "k"}
        for source_alias, sql_alias in alias_map.items():
            formula = re.sub(
                rf"\b{re.escape(source_alias)}\.([A-Za-z_][A-Za-z0-9_]*)",
                lambda m: f'{sql_alias}."{m.group(1).lower()}"',
                formula,
                flags=re.I,
            )
        references = re.findall(r'\b([pk])\."([A-Za-z_][A-Za-z0-9_]*)"', formula, re.I)
        for sql_alias, column in references:
            source_table = line if sql_alias.lower() == "p" else hdr
            if not has_column(source_table, column):
                return None
        currency_field = str(getattr(metric_def, "currency_field", None) or "").strip()
        currency_match = re.fullmatch(r"(?:vk|k)\.([A-Za-z_][A-Za-z0-9_]*)", currency_field, re.I)
        currency_col = (
            currency_match.group(1).lower()
            if currency_match
            else next(
                (column for column in ("waerk", "waers", "rtcur") if has_column(hdr, column)),
                None,
            )
        )
        if measure not in {"invoice_count", "quantity"} and not currency_col:
            return None
        if currency_col:
            if not has_column(hdr, currency_col):
                return None
            sel.append(f'k."{currency_col}" AS "currency"')
            gb.append(f'k."{currency_col}"')
            currency_rank = measure not in {"invoice_count", "quantity"}
        alias = "total_sales" if metric_def.name == "revenue" else metric_def.name
        sel.append(f'({formula}) AS "{alias}"')
    elif measure == "invoice_count":
        if not has_column(hdr, "vbeln"):
            return None
        sel.append('COUNT(DISTINCT TRIM(CAST(k."vbeln" AS TEXT))) AS "invoice_count"')
        alias = "invoice_count"
    elif measure == "quantity":
        if not has_column(line, "fkimg"):
            return None
        sel.append(
            'SUM(CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), \'\') AS NUMERIC)) AS "billed_quantity"'
        )
        alias = "billed_quantity"
        where.append('NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), \'\') IS NOT NULL')
    else:
        amount_qual, amount_tbl = ("p", line) if use_line else ("k", hdr)
        if not has_column(amount_tbl, "netwr"):
            return None
        currency_col = next(
            (column for column in ("waerk", "waers", "rtcur") if has_column(hdr, column)),
            None,
        )
        if not currency_col:
            # A monetary ranking without a currency key cannot safely compare
            # groups. Let the caller report the missing schema evidence.
            return None
        if not any('AS "currency"' in column for column in sel):
            sel.append(f'k."{currency_col}" AS "currency"')
            gb.append(f'k."{currency_col}"')
        currency_rank = True
        sel.append(
            f'SUM(CAST(NULLIF(TRIM(CAST({amount_qual}."netwr" AS TEXT)), \'\') AS NUMERIC)) '
            'AS "total_sales"'
        )
        alias = "total_sales"
        where.append(f'NULLIF(TRIM(CAST({amount_qual}."netwr" AS TEXT)), \'\') IS NOT NULL')

    if years and has_column(hdr, "fkdat"):
        pred = _sap_year_predicate("k", "fkdat", years)
        if pred:
            where.append(pred)
    elif has_column(hdr, "fkdat"):
        # Ranking templates bypass the generic structured-plan renderer, so
        # carry its resolved relative date window into this SQL path as well.
        # This keeps "last year" bounded to the prior calendar year and lets
        # latest-data-year questions use the dynamically resolved SAP period.
        date_filter = req.get("date_filter") if isinstance(req.get("date_filter"), dict) else {}
        semantic_tf = (req.get("semantic") or {}).get("time_filter") or {}
        start = str(date_filter.get("start_yyyymmdd") or semantic_tf.get("start_yyyymmdd") or "")
        end = str(date_filter.get("end_yyyymmdd") or semantic_tf.get("end_yyyymmdd") or "")
        if start.isdigit() and end.isdigit() and len(start) == 8 and len(end) == 8:
            date_expr = 'TRIM(CAST(k."fkdat" AS TEXT))'
            where.extend([f"{date_expr} >= '{start}'", f"{date_expr} < '{end}'"])
    displayed_year = years[0] if len(years) == 1 else None
    if not displayed_year:
        date_filter = req.get("date_filter") if isinstance(req.get("date_filter"), dict) else {}
        semantic_tf = (req.get("semantic") or {}).get("time_filter") or {}
        start = str(date_filter.get("start_yyyymmdd") or semantic_tf.get("start_yyyymmdd") or "")
        end = str(date_filter.get("end_yyyymmdd") or semantic_tf.get("end_yyyymmdd") or "")
        if (
            len(start) == 8 and start.isdigit() and start.endswith("0101")
            and len(end) == 8 and end.isdigit() and end.endswith("0101")
            and int(end[:4]) == int(start[:4]) + 1
        ):
            displayed_year = start[:4]
    if displayed_year and re.search(r"\b(?:show|include|with|including)?\s*(?:the\s+)?year\b", question, re.I):
        sel.append(f"'{displayed_year}' AS \"billing_year\"")

    sql = f"SELECT {', '.join(sel)}\n{from_clause}"
    for j in joins:
        sql += f"\n{j}"
    if where:
        sql += "\nWHERE " + "\n  AND ".join(where)
    sql += f"\nGROUP BY {', '.join(gb)}"
    if use_line:
        # VBRP can contain exact duplicate item copies. Collapse only rows with
        # the complete SAP item identity and the attributes that can affect a
        # ranking/calculation before joining headers or aggregating measures.
        # DISTINCT on amount alone would merge legitimate equal-value items.
        identity_attributes = (
            "mandt", "vbeln", "posnr", "netwr", "aubel", "aupos",
            "matnr", "fkimg", "vrkme", "wavwr",
        )
        row_columns = [column for column in identity_attributes if has_column(line, column)]
        if not {"mandt", "vbeln", "posnr"} <= set(row_columns):
            return None
        projections = ", ".join(f'src."{column}"' for column in row_columns)
        sql = (
            'WITH "billing_item_rows" AS (\n'
            f'  SELECT DISTINCT {projections} FROM "{line}" src\n'
            ')\n' + sql
        )
    safe_limit = max(1, min(int(limit), 500))
    if currency_rank:
        # Amounts in different currencies are not comparable. Keep all currency
        # values in the result, and apply the requested top-N independently
        # inside each currency instead of silently ranking mixed amounts.
        sql = (
            'WITH grouped AS (\n'
            + "\n".join("  " + line for line in sql.splitlines())
            + '\n), ranked AS (\n'
            '  SELECT grouped.*, ROW_NUMBER() OVER (\n'
            '    PARTITION BY grouped."currency" '
            f'ORDER BY grouped."{alias}" {direction} NULLS LAST\n'
            '  ) AS "rank_within_currency"\n'
            '  FROM grouped\n'
            ')\n'
            'SELECT * FROM ranked\n'
            f'WHERE "rank_within_currency" <= {safe_limit}\n'
            'ORDER BY "currency", "rank_within_currency"\n'
            f'LIMIT {min(safe_limit * 20, 500)}'
        )
    else:
        sql += f'\nORDER BY "{alias}" {direction} NULLS LAST'
        sql += f"\nLIMIT {safe_limit}"
    return sql.strip()


def build_billing_document_ranking_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Build a document-grain list from the billing header's verified fields.

    A requested customer or country is an attribute/filter on these rows; it
    must not silently change the output grain to a customer aggregate.
    """
    from .semantic_requirements import required_semantics

    q = (question or "").lower()
    if not has_table("VBRK") or not re.search(r"\b(?:billing\s+documents?|invoices?|billed\s+documents?)\b", q):
        return None
    req = required_semantics(question, semantic)
    if "document" not in [str(g).lower() for g in (req.get("group_by") or [])]:
        return None
    header = resolve_table_name("VBRK") or "VBRK"
    document_col = next((c for c in ("vbeln", "belnr") if has_column(header, c)), None)
    amount_col = next((c for c in ("netwr", "dmbtr", "wrbtr", "rmwwr") if has_column(header, c)), None)
    if not document_col or not amount_col:
        return None

    rank = req.get("ranking") if isinstance(req.get("ranking"), dict) else {}
    try:
        limit = int(rank.get("limit") or extract_ranking_limit(question, default=200))
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 500))
    direction = str(rank.get("direction") or ranking_direction(question)).upper()
    if direction not in {"ASC", "DESC"}:
        direction = ranking_direction(question)

    doc_expr = f'TRIM(CAST(k."{document_col}" AS TEXT))'
    amount_expr = numeric_cast_expr(header, amount_col).replace(f'"{header}".', "k.")
    select = [f'{doc_expr} AS "billing_document"']
    where = [f'NULLIF(TRIM(CAST(k."{amount_col}" AS TEXT)), \'\') IS NOT NULL']
    joins: List[str] = []

    date_col = next((c for c in ("fkdat", "budat", "bldat", "audat") if has_column(header, c)), None)
    if date_col:
        select.append(f'TRIM(CAST(k."{date_col}" AS TEXT)) AS "billing_date"')
    customer_col = next((c for c in ("kunag", "kunnr") if has_column(header, c)), None)
    if customer_col:
        select.append(f'TRIM(CAST(k."{customer_col}" AS TEXT)) AS "customer_id"')
        customer_match = re.search(
            r"\bcustomer\s+(?:id|number)\s+(?:is\s+|=\s*)?['\"]?([A-Za-z0-9_-]+)", question, re.I
        )
        if customer_match:
            customer_id = customer_match.group(1).replace("'", "''")
            where.append(
                f"LPAD(TRIM(CAST(k.\"{customer_col}\" AS TEXT)), 10, '0') = "
                f"LPAD('{customer_id}', 10, '0')"
            )
    if customer_col and has_table("KNA1") and has_column("KNA1", "kunnr"):
        joins.append(
            'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."' + customer_col + '" AS TEXT)), 10, \'0\') '
            '= LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
        )
        if has_column("KNA1", "name1"):
            select.append('TRIM(CAST(c."name1" AS TEXT)) AS "customer_name"')
    select.append(f'{amount_expr} AS "billed_amount"')
    currency_col = next((c for c in ("waerk", "waers", "rtcur") if has_column(header, c)), None)
    if currency_col:
        select.append(f'TRIM(CAST(k."{currency_col}" AS TEXT)) AS "currency"')
        currency_match = re.search(r"\bcurrency\s+([A-Za-z]{3})\b", question, re.I)
        if currency_match:
            currency = currency_match.group(1).upper()
            where.append(f'TRIM(CAST(k."{currency_col}" AS TEXT)) = \'{currency}\'')

    # Carry a document's existing order reference when this extract provides it.
    for order_col in ("aubel", "vgbel"):
        if has_column(header, order_col):
            select.append(f'TRIM(CAST(k."{order_col}" AS TEXT)) AS "linked_sales_order"')
            break

    comparison = req.get("comparison") if isinstance(req.get("comparison"), dict) else {}
    if comparison.get("operator") is not None:
        op = str(comparison["operator"])
        if op not in {"<", "<=", ">", ">=", "=", "!="}:
            return None
        try:
            value = float(comparison.get("value", 0))
        except (TypeError, ValueError):
            return None
        where.append(f'{amount_expr} {op} {value:g}')
    elif re.search(r"\bnegative\b", q):
        where.append(f"{amount_expr} < 0")

    years = extract_question_years(question)
    tf = (req.get("semantic") or {}).get("time_filter") or {}
    if not years and tf.get("resolved_from_data") is True:
        years = [str(y) for y in (tf.get("years") or [])]
    if years and date_col:
        where.append(_sap_year_predicate("k", date_col, years) or "")
    elif date_col and req.get("date_filter"):
        date_filter = req["date_filter"]
        start = str(date_filter.get("start_yyyymmdd") or "")
        end = str(date_filter.get("end_yyyymmdd") or "")
        if start and end and start.isdigit() and end.isdigit():
            date_expr = f'TRIM(CAST(k."{date_col}" AS TEXT))'
            where.extend([f"{date_expr} >= '{start}'", f"{date_expr} < '{end}'"])

    return (
        f'SELECT {", ".join(select)}\nFROM "{header}" k'
        + ("\n" + "\n".join(joins) if joins else "")
        + "\nWHERE " + "\n  AND ".join(part for part in where if part)
        + f'\nORDER BY "billed_amount" {direction} NULLS LAST\nLIMIT {limit}'
    )


def _build_vendor_invoice_ranking_sql(
    question: str,
    *,
    limit: int,
    direction: str,
    years: Optional[List[str]] = None,
) -> Optional[str]:
    """Generic vendor ranking by vendor-invoice amount (RBKP + LFA1)."""
    if not has_table("RBKP") or not has_column("RBKP", "lifnr"):
        return None
    hdr = resolve_table_name("RBKP") or "RBKP"
    amount_col = None
    for cand in ("rmwwr", "netwr", "dmbtr", "wrbtr"):
        if has_column(hdr, cand):
            amount_col = cand
            break
    if not amount_col:
        return None
    amt = numeric_cast_expr(hdr, amount_col)
    sel = [
        f'TRIM(CAST(h."lifnr" AS TEXT)) AS "vendor_id"',
        f'SUM({amt}) AS "invoice_amount"',
    ]
    gb = [f'TRIM(CAST(h."lifnr" AS TEXT))']
    joins = [f'FROM "{hdr}" h']
    if has_table("LFA1") and has_column("LFA1", "lifnr"):
        joins.append(
            'LEFT JOIN "LFA1" v ON LPAD(TRIM(CAST(h."lifnr" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(v."lifnr" AS TEXT)), 10, \'0\')'
        )
        if has_column("LFA1", "name1"):
            sel.insert(1, 'TRIM(v."name1") AS "vendor_name"')
            gb.append('TRIM(v."name1")')
    where = [
        'NULLIF(TRIM(CAST(h."lifnr" AS TEXT)), \'\') IS NOT NULL',
        f'NULLIF(TRIM(CAST(h."{amount_col}" AS TEXT)), \'\') IS NOT NULL',
    ]
    date_col = next((c for c in ("budat", "bldat", "cpudt") if has_column(hdr, c)), None)
    if years and date_col:
        pred = _sap_year_predicate("h", date_col, years)
        if pred:
            where.append(pred)
    sql = f"SELECT {', '.join(sel)}\n" + "\n".join(joins)
    sql += "\nWHERE " + "\n  AND ".join(where)
    sql += f"\nGROUP BY {', '.join(gb)}"
    sql += f'\nORDER BY "invoice_amount" {direction} NULLS LAST'
    sql += f"\nLIMIT {max(1, min(int(limit), 500))}"
    return sql.strip()


def _build_vendor_purchase_ranking_sql(
    question: str,
    *,
    limit: int,
    direction: str,
    years: Optional[List[str]] = None,
) -> Optional[str]:
    """Generic vendor ranking by purchase-order value (EKPO/EKKO/LFA1)."""
    if not has_table("EKPO") or not has_table("EKKO"):
        return None
    if not has_column("EKPO", "netwr") or not has_column("EKKO", "lifnr"):
        return None
    line = resolve_table_name("EKPO") or "EKPO"
    hdr = resolve_table_name("EKKO") or "EKKO"
    net = numeric_cast_expr(line, "netwr")
    sel = [
        f'TRIM(CAST(h."lifnr" AS TEXT)) AS "vendor_id"',
        f'SUM({net}) AS "purchase_order_value"',
    ]
    gb = [f'TRIM(CAST(h."lifnr" AS TEXT))']
    joins = [
        f'FROM "{line}" p',
        f'JOIN "{hdr}" h ON LPAD(TRIM(CAST(p."ebeln" AS TEXT)), 10, \'0\') = '
        f'LPAD(TRIM(CAST(h."ebeln" AS TEXT)), 10, \'0\')',
    ]
    if has_table("LFA1") and has_column("LFA1", "lifnr"):
        joins.append(
            'LEFT JOIN "LFA1" v ON LPAD(TRIM(CAST(h."lifnr" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(v."lifnr" AS TEXT)), 10, \'0\')'
        )
        if has_column("LFA1", "name1"):
            sel.insert(1, 'TRIM(v."name1") AS "vendor_name"')
            gb.append('TRIM(v."name1")')
    where = [
        'NULLIF(TRIM(CAST(h."lifnr" AS TEXT)), \'\') IS NOT NULL',
        f'NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') IS NOT NULL',
    ]
    if years and has_column(hdr, "bedat"):
        pred = _sap_year_predicate("h", "bedat", years)
        if pred:
            where.append(pred)
    # Do not GROUP BY currency here — that multiplies ranking rows and trips the
    # limit validator. Currency safety is applied later via filter injection.

    sql = f"SELECT {', '.join(sel)}\n" + "\n".join(joins)
    sql += "\nWHERE " + "\n  AND ".join(where)
    sql += f"\nGROUP BY {', '.join(gb)}"
    sql += f'\nORDER BY "purchase_order_value" {direction} NULLS LAST'
    sql += f"\nLIMIT {max(1, min(int(limit), 500))}"
    return sql.strip()


def build_country_customer_list_sql(
    question: str,
    tables: List[str],
) -> Optional[str]:
    """'List all customers in Germany' — customer master filtered by country."""
    q = (question or "").lower()
    if not re.search(r"\b(list|show|display|give me|who are)\b", q):
        return None
    if not re.search(r"\b(customer|customers|client|clients)\b", q):
        return None
    if _SUPERLATIVE.search(q) or re.search(r"\btop\s+\d+\b", q):
        return None
    if not has_table("KNA1") or not has_column("KNA1", "land1"):
        return None

    code: Optional[str] = None
    for name, iso in sorted(_COUNTRY_CODES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(name)}\b", q):
            code = iso
            break
    if not code:
        return None

    cols = ['TRIM("KNA1"."kunnr") AS "customer_id"']
    if has_column("KNA1", "name1"):
        cols.append('TRIM("KNA1"."name1") AS "customer_name"')
    cols.append('TRIM("KNA1"."land1") AS "country"')
    if has_column("KNA1", "ort01"):
        cols.append('TRIM("KNA1"."ort01") AS "city"')

    return (
        f"SELECT {', '.join(cols)}\n"
        'FROM "KNA1"\n'
        f'WHERE TRIM(CAST("KNA1"."land1" AS TEXT)) = \'{code}\'\n'
        'ORDER BY "customer_id" ASC\n'
        "LIMIT 500"
    )


def build_period_sales_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Sales bucketed by billing period (year / quarter / month) from VBRK header.

    Also covers 'compare sales in 2004 and 2005' by scoping to the named years.
    SAP FKDAT is YYYYMMDD text, so buckets use SUBSTRING — never EXTRACT/TO_CHAR.
    """
    q = (question or "").lower()
    if not re.search(r"\b(sales|revenue|billing|billed|turnover)\b", q):
        return None
    if not has_table("VBRK") or not has_column("VBRK", "netwr") or not has_column("VBRK", "fkdat"):
        return None
    if re.search(r"\b(customer|customers|country|countries|industr|material|product|vendor)\b", q):
        return None

    years = extract_question_years(question)
    wants_month = bool(
        re.search(
            r"\b(month|monthly|per month|by month|each month|month by month)\b",
            q,
        )
    )
    wants_quarter = bool(re.search(r"\b(quarter|quarterly|per quarter|by quarter|each quarter)\b", q))
    wants_year = bool(re.search(r"\b(year|yearly|annual|annually|by year|per year)\b", q))
    wants_compare = bool(re.search(r"\b(compare|comparison|versus|vs\.?|trend|over time)\b", q))

    if not (wants_month or wants_quarter or wants_year or (wants_compare and len(years) >= 1)):
        return None

    hdr = resolve_table_name("VBRK") or "VBRK"
    net = numeric_cast_expr(hdr, "netwr")
    fkdat = f'TRIM(CAST("{hdr}"."fkdat" AS TEXT))'

    if wants_month:
        bucket, label = f"SUBSTRING({fkdat}, 1, 6)", "month"
    elif wants_quarter:
        bucket = (
            f"SUBSTRING({fkdat}, 1, 4) || '-Q' || "
            f"CAST(CEIL(CAST(SUBSTRING({fkdat}, 5, 2) AS NUMERIC) / 3) AS INTEGER)"
        )
        label = "quarter"
    else:
        bucket, label = f"SUBSTRING({fkdat}, 1, 4)", "year"

    where = [f'NULLIF({fkdat}, \'\') IS NOT NULL']
    year_pred = _sap_year_predicate(f'"{hdr}"', "fkdat", years)
    if year_pred:
        where.append(year_pred)

    return (
        f'SELECT {bucket} AS "{label}", SUM({net}) AS "total_sales"\n'
        f'FROM "{hdr}"\n'
        "WHERE " + "\n  AND ".join(where) + "\n"
        f"GROUP BY {bucket}\n"
        f'ORDER BY "{label}" ASC'
    )


def build_dimension_period_sales_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Build a verified period series scoped to an explicit prior-result entity."""
    from .semantic_requirements import required_semantics

    q = question or ""
    if not re.search(r"\b(?:sales|revenue|billing|billed|turnover)\b", q, re.I):
        return None
    if re.search(r"\b(?:by|per|each|and)\s+months?|\bmonthly\b|\bmonth[- ]by[- ]month\b", q, re.I):
        period_grain = "month"
    elif re.search(r"\b(?:by|per|each)\s+quarters?|\bquarterly\b", q, re.I):
        period_grain = "quarter"
    elif re.search(r"\b(?:by|per|each)\s+(?:(?:calendar|fiscal)\s+)?years?|\byearly\b|\bannually\b", q, re.I):
        period_grain = "year"
    else:
        period_grain = None
    header = resolve_table_name("VBRK") or "VBRK"
    if not has_table(header) or not has_column(header, "netwr"):
        return None
    req = required_semantics(q, semantic)
    time_filter = (req.get("semantic") or {}).get("time_filter") or {}
    years = extract_question_years(q)
    if not years and time_filter.get("resolved_from_data") is True:
        years = [str(year) for year in (time_filter.get("years") or [])]
    if not has_column(header, "fkdat"):
        return None

    where: List[str] = []
    joins: List[str] = []
    select_dims: List[str] = []
    group_dims: List[str] = []
    ops = (req.get("semantic") or {}).get("analytical_operations") or {}
    requested_dims = {
        str(dim).lower()
        for dim in (
            req.get("group_by")
            or (req.get("semantic") or {}).get("group_by")
            or ops.get("group_by")
            or []
        )
    }
    if period_grain is None and "currency" not in requested_dims:
        return None
    country_match = re.search(r"\bcountry\s+code\s+['\"]?([A-Za-z]{2,3})\b", q, re.I)
    customer_match = re.search(
        r"\bcustomer\s+(?:id|number)\s+(?:is\s+|=\s*)?['\"]?([A-Za-z0-9_-]+)", q, re.I
    )


    group_country = "country" in requested_dims
    group_customer = "customer" in requested_dims
    if country_match or customer_match or group_country or group_customer:
        if not has_table("KNA1") or not has_column(header, "kunag") or not has_column("KNA1", "kunnr") or not has_column("KNA1", "land1"):
            return None
        joins.append(
            'JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') '
            '= LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
        )
        if country_match:
            country = country_match.group(1).upper()
            where.append(f'TRIM(CAST(c."land1" AS TEXT)) = \'{country}\'')
        if customer_match:
            customer = customer_match.group(1).replace("'", "''")
            where.append(f'LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = LPAD(\'{customer}\', 10, \'0\')')
        if group_country:
            select_dims.append('TRIM(CAST(c."land1" AS TEXT)) AS "country"')
            group_dims.append('TRIM(CAST(c."land1" AS TEXT))')
        if group_customer:
            select_dims.append('TRIM(CAST(c."kunnr" AS TEXT)) AS "customer_id"')
            group_dims.append('TRIM(CAST(c."kunnr" AS TEXT))')
            if has_column("KNA1", "name1"):
                select_dims.append('TRIM(CAST(c."name1" AS TEXT)) AS "customer_name"')
                group_dims.append('TRIM(CAST(c."name1" AS TEXT))')
    elif requested_dims.difference({"month", "year", "quarter", "currency"}):
        return None

    date_expr = 'TRIM(CAST(k."fkdat" AS TEXT))'
    where.append(f"NULLIF({date_expr}, '') IS NOT NULL")
    if years:
        where.append(f"SUBSTRING({date_expr}, 1, 4) IN ({', '.join(repr(year) for year in years)})")
    currency_col = next((col for col in ("waerk", "waers", "rtcur") if has_column(header, col)), None)
    currency_match = re.search(r"\bcurrency\s+([A-Z]{3})\b", q)
    if not currency_match:
        # A bare code after "in" is recognizable by its conventional uppercase
        # spelling; don't consume articles in phrases such as "in the last year".
        currency_match = re.search(r"\bin\s+(?:currency\s+)?([A-Z]{3})\b", q)
    if currency_col and currency_match:
        currency = currency_match.group(1).upper()
        where.append(f'TRIM(CAST(k."{currency_col}" AS TEXT)) = \'{currency}\'')
        currency_select = f', k."{currency_col}" AS "currency"'
        currency_group = f', k."{currency_col}"'
    elif currency_col:
        # Never combine amounts whose currency is unknown or different.
        currency_select = f', k."{currency_col}" AS "currency"'
        currency_group = f', k."{currency_col}"'
    else:
        currency_select = currency_group = ""

    # Keep month buckets year-qualified (YYYYMM), even when the request is
    # scoped to one year. This avoids merging January from different years and
    # satisfies the same FKDAT month-grain guard used by other query paths.
    bucket_length = 6 if period_grain == "month" else 4
    bucket = f'SUBSTRING({date_expr}, 1, {bucket_length})' if period_grain in {"month", "year"} else None
    if period_grain == "quarter":
        month_expr = f'CAST(SUBSTRING({date_expr}, 5, 2) AS INTEGER)'
        quarter_num = (
            f"CASE WHEN {month_expr} BETWEEN 1 AND 3 THEN '1' "
            f"WHEN {month_expr} BETWEEN 4 AND 6 THEN '2' "
            f"WHEN {month_expr} BETWEEN 7 AND 9 THEN '3' "
            f"WHEN {month_expr} BETWEEN 10 AND 12 THEN '4' END"
        )
        bucket = f"(SUBSTRING({date_expr}, 1, 4) || '-Q' || {quarter_num})"
    period_label = period_grain if period_grain else None
    amount_expr = numeric_cast_expr(header, "netwr").replace(f'"{header}".', "k.")
    select_parts = [
        *select_dims,
    ]
    if bucket and period_label:
        select_parts.append(f'{bucket} AS "{period_label}"')
    select_parts.append(f'SUM({amount_expr}) AS "total_billed_sales"')
    if "currency" in requested_dims and not currency_col:
        return None
    if currency_col:
        select_parts.append(f'k."{currency_col}" AS "currency"')
    groups = [*group_dims, *([bucket] if bucket else [])]
    if currency_col:
        groups.append(f'k."{currency_col}"')
    order_by = f'"{period_label}" ASC' if period_label else '"currency" ASC'
    return (
        f'SELECT {", ".join(select_parts)}\n'
        f'FROM "{header}" k' + ("\n" + "\n".join(joins) if joins else "") + "\n"
        + "WHERE " + "\n  AND ".join(where) + "\n"
        + f'GROUP BY {", ".join(groups)}\nORDER BY {order_by}'
    )


def build_linked_sales_orders_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Resolve sales-order predecessors for explicit billing IDs via SAP flow."""
    q = question or ""
    if not re.search(r"\b(?:sales\s+orders?|linked\s+orders?)\b", q, re.I):
        return None
    if not all(
        has_table(table) and has_column(table, column)
        for table, column in (
            ("VBFA", "vbeln"), ("VBFA", "vbelv"),
            ("VBAK", "vbeln"), ("VBRK", "vbeln"),
        )
    ):
        return None
    id_clause = re.search(r"\bbilling\s+document\s+ids?\s*:\s*([\s\S]+)$", q, re.I)
    if not id_clause:
        return None
    ids = list(dict.fromkeys(value.replace("''", "'") for value in re.findall(r"'((?:''|[^'])*)'", id_clause.group(1))))
    ids = [value for value in ids if value.strip()][:50]
    if not ids:
        return None
    id_list = ", ".join(
        f"LPAD('{value.replace(chr(39), chr(39) * 2)}', 10, '0')" for value in ids
    )
    flow = resolve_table_name("VBFA") or "VBFA"
    orders = resolve_table_name("VBAK") or "VBAK"
    invoices = resolve_table_name("VBRK") or "VBRK"
    return (
        'SELECT DISTINCT TRIM(CAST(f."vbeln" AS TEXT)) AS "billing_document", '
        'TRIM(CAST(o."vbeln" AS TEXT)) AS "linked_sales_order"\n'
        f'FROM "{flow}" f\n'
        f'JOIN "{invoices}" b ON LPAD(TRIM(CAST(f."vbeln" AS TEXT)), 10, \'0\') '
        f'= LPAD(TRIM(CAST(b."vbeln" AS TEXT)), 10, \'0\')\n'
        f'JOIN "{orders}" o ON LPAD(TRIM(CAST(f."vbelv" AS TEXT)), 10, \'0\') '
        f'= LPAD(TRIM(CAST(o."vbeln" AS TEXT)), 10, \'0\')\n'
        f'WHERE LPAD(TRIM(CAST(f."vbeln" AS TEXT)), 10, \'0\') IN ({id_list})\n'
        'ORDER BY "billing_document", "linked_sales_order"'
    )


def build_linked_billing_documents_for_orders_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """List billing headers linked to explicitly named sales orders.

    The identifiers are extracted from the user's request at runtime. SAP
    document flow is deduplicated before joining the monetary header fact so
    item-level flow rows cannot multiply invoice values.
    """
    q = question or ""
    if not re.search(r"\b(?:list|show|display|find|give)\b", q, re.I):
        return None
    if not re.search(r"\b(?:linked|related)\b[\s\S]{0,80}\b(?:billing\s+documents?|invoices?)\b", q, re.I):
        return None
    if not re.search(r"\bsales\s+orders?\b", q, re.I):
        return None

    # Document numbers are schema values, never embedded constants. Ignore
    # calendar years, which appear in many date-scoped questions.
    ids = list(dict.fromkeys(
        value for value in re.findall(r"(?<!\d)\d{6,10}(?!\d)", q)
        if not (len(value) == 4 and value.startswith(("19", "20")))
    ))[:50]
    if not ids or not all(
        has_table(table) and all(has_column(table, column) for column in columns)
        for table, columns in (
            ("VBFA", ("mandt", "vbelv", "vbeln")),
            ("VBAK", ("mandt", "vbeln")),
            ("VBRK", ("mandt", "vbeln", "netwr", "waerk")),
        )
    ):
        return None

    order_table = resolve_table_name("VBAK") or "VBAK"
    flow_table = resolve_table_name("VBFA") or "VBFA"
    invoice_table = resolve_table_name("VBRK") or "VBRK"
    id_list = ", ".join(
        f"LPAD('{value}', 10, '0')" for value in ids
    )
    optional_fields = []
    for col, alias in (
        ("fkart", "billing_type"),
        ("vbtyp", "billing_category"),
        ("fksto", "cancellation_flag"),
        ("sfakn", "cancellation_reference"),
    ):
        if has_column(invoice_table, col):
            optional_fields.append(f'TRIM(CAST(b."{col}" AS TEXT)) AS "{alias}"')
    fields = [
        'TRIM(CAST(l."sales_order" AS TEXT)) AS "sales_order"',
        'TRIM(CAST(b."vbeln" AS TEXT)) AS "billing_document"',
        'CAST(NULLIF(TRIM(CAST(b."netwr" AS TEXT)), \'\') AS NUMERIC) AS "billing_net_value"',
        'TRIM(CAST(b."waerk" AS TEXT)) AS "currency"',
        *optional_fields,
    ]
    return (
        'WITH "order_billing_links" AS (\n'
        '  SELECT DISTINCT f."mandt", f."vbelv" AS "sales_order", f."vbeln" AS "billing_document"\n'
        f'  FROM "{flow_table}" f\n'
        f'  JOIN "{order_table}" o ON o."mandt" = f."mandt" '
        'AND LPAD(TRIM(CAST(o."vbeln" AS TEXT)), 10, \'0\') = '
        'LPAD(TRIM(CAST(f."vbelv" AS TEXT)), 10, \'0\')\n'
        f'  JOIN "{invoice_table}" bh ON bh."mandt" = f."mandt" '
        'AND LPAD(TRIM(CAST(bh."vbeln" AS TEXT)), 10, \'0\') = '
        'LPAD(TRIM(CAST(f."vbeln" AS TEXT)), 10, \'0\')\n'
        '  WHERE LPAD(TRIM(CAST(o."vbeln" AS TEXT)), 10, \'0\') IN ('
        f'{id_list})\n'
        ')\n'
        f'SELECT {", ".join(fields)}\n'
        f'FROM "order_billing_links" l\n'
        f'JOIN "{invoice_table}" b ON b."mandt" = l."mandt" '
        'AND LPAD(TRIM(CAST(b."vbeln" AS TEXT)), 10, \'0\') = '
        'LPAD(TRIM(CAST(l."billing_document" AS TEXT)), 10, \'0\')\n'
        'ORDER BY "sales_order", "billing_document"'
    )


def build_linked_order_period_comparison_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Rank a billing-document cohort, then compare its linked orders by year.

    This builder is intentionally schema-gated: it only emits SQL when the
    billing, document-flow, order, date, amount, and currency fields needed to
    make the requested comparison are present in the verified catalog.
    """
    from .semantic_requirements import required_semantics

    q = question or ""
    if not re.search(r"\b(?:linked|related)\b[\s\S]{0,50}\bsales\s+orders?\b|\bsales\s+orders?\b[\s\S]{0,50}\b(?:linked|related)\b", q, re.I):
        return None
    if not re.search(r"\b(?:invoices?|billing\s+documents?)\b", q, re.I):
        return None

    req = required_semantics(question, semantic)
    if "document" not in [str(g).lower() for g in (req.get("group_by") or [])]:
        return None
    period = req.get("period_compare") if isinstance(req.get("period_compare"), dict) else {}

    def _period_year(key: str) -> Optional[str]:
        raw = period.get(key)
        if isinstance(raw, dict):
            raw = raw.get("year") or raw.get("start")
        value = str(raw or "")[:4]
        return value if re.fullmatch(r"\d{4}", value) else None

    year_a, year_b = _period_year("base_period"), _period_year("comparison_period")
    years = extract_question_years(question)
    if not year_a or not year_b:
        if len(years) < 2:
            return None
        year_a, year_b = years[0], years[-1]
    if year_a == year_b:
        return None

    required = {
        "VBRK": ("vbeln", "netwr", "waerk"),
        "VBFA": ("vbeln", "vbelv"),
        "VBAK": ("vbeln", "netwr", "waerk", "erdat"),
    }
    if any(
        not has_table(table) or any(not has_column(table, column) for column in columns)
        for table, columns in required.items()
    ):
        return None

    invoice_table = resolve_table_name("VBRK") or "VBRK"
    flow_table = resolve_table_name("VBFA") or "VBFA"
    order_table = resolve_table_name("VBAK") or "VBAK"
    customer_col = next(
        (column for column in ("kunag", "kunnr") if has_column(invoice_table, column)),
        None,
    )
    if not customer_col:
        return None

    invoice_date_alias, invoice_date_col = "k", "fkdat"
    invoice_joins: List[str] = []
    invoice_year_start = f"{year_a}0101"
    invoice_year_end = f"{int(year_a) + 1:04d}0101"
    if re.search(r"\bposting\s+date\b", q, re.I):
        # VBRK.FKDAT is billing date, not financial posting date. Resolve the
        # latter through the accounting document only when its full key exists.
        if not all(
            has_table(table)
            and has_column(table, column)
            for table, column in (
                (invoice_table, "belnr"), (invoice_table, "gjahr"), (invoice_table, "bukrs"),
                ("BKPF", "belnr"), ("BKPF", "gjahr"), ("BKPF", "bukrs"), ("BKPF", "budat"),
            )
        ):
            return None
        bkpf = resolve_table_name("BKPF") or "BKPF"
        invoice_date_alias, invoice_date_col = "fi", "budat"
        invoice_joins.append(
            f'JOIN "{bkpf}" fi ON fi."belnr" = k."belnr" '
            'AND fi."gjahr" = k."gjahr" AND fi."bukrs" = k."bukrs"'
        )
    elif not has_column(invoice_table, "fkdat"):
        return None

    # An explicit request for independently ranked invoice periods needs both
    # cohorts. A base-year selection followed by an order comparison keeps its
    # original single invoice cohort.
    cohort_scope = (semantic or {}).get("invoice_cohort_scope")
    each_invoice_period = cohort_scope == "each_period" if cohort_scope in {"each_period", "base_period"} else bool(re.search(
        r"\b(?:each|both|per)\s+(?:calendar\s+)?(?:years?|periods?)\b|"
        r"\b(?:independently|separately|separate)\b[\s\S]{0,100}\b(?:invoices?|billing\s+documents?)\b",
        q, re.I,
    ))
    invoice_date_expr = f'TRIM(CAST({invoice_date_alias}."{invoice_date_col}" AS TEXT))'
    invoice_amount = 'CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), \'\') AS NUMERIC)'
    order_date_expr = 'TRIM(CAST(l."linked_order_date" AS TEXT))'
    order_amount = 'CAST(NULLIF(TRIM(CAST(l."linked_order_amount" AS TEXT)), \'\') AS NUMERIC)'
    rank = req.get("ranking") if isinstance(req.get("ranking"), dict) else {}
    try:
        limit = int(rank.get("limit") or extract_ranking_limit(question, default=10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 500))

    select = [
        'k."vbeln" AS "_billing_document_key"',
        'TRIM(CAST(k."vbeln" AS TEXT)) AS "billing_document"',
        f'{invoice_date_expr} AS "invoice_date"',
        f'TRIM(CAST(k."{customer_col}" AS TEXT)) AS "customer_id"',
        f'{invoice_amount} AS "invoice_amount"',
        'TRIM(CAST(k."waerk" AS TEXT)) AS "currency"',
    ]
    invoice_joins.extend([
        f'LEFT JOIN "KNA1" c ON k."{customer_col}" = c."kunnr"'
    ] if has_table("KNA1") and has_column("KNA1", "kunnr") else [])
    if has_table("KNA1") and has_column("KNA1", "kunnr") and has_column("KNA1", "name1"):
        select.append('TRIM(CAST(c."name1" AS TEXT)) AS "customer_name"')

    invoice_predicates = [
        f'{invoice_date_expr} >= \'{invoice_year_start}\'',
        f'{invoice_date_expr} < \'{invoice_year_end}\'',
        f'{invoice_amount} < 0',
        'NULLIF(TRIM(CAST(k."waerk" AS TEXT)), \'\') IS NOT NULL',
    ]
    currency_match = re.search(r"\bcurrency\s+([A-Za-z]{3})\b", q, re.I)
    if currency_match:
        invoice_predicates.append(
            f'UPPER(TRIM(CAST(k."waerk" AS TEXT))) = \'{currency_match.group(1).upper()}\''
        )

    customer_join_sql = "\n".join(invoice_joins)
    candidate_cte = (
        'invoice_cohort AS (\n'
        f'  SELECT {", ".join(select)}\n'
        f'  FROM "{invoice_table}" k\n'
        + (f'{customer_join_sql}\n' if customer_join_sql else "")
        + '  WHERE ' + '\n    AND '.join(invoice_predicates) + '\n'
        + f'  ORDER BY "invoice_amount" ASC, "billing_document" ASC\n  LIMIT {limit}\n'
        + ')'
    )
    if each_invoice_period:
        scoped_predicates = [
            f"SUBSTRING({invoice_date_expr}, 1, 4) IN ('{year_a}', '{year_b}')",
            *invoice_predicates[2:],
        ]
        candidate_cte = (
            'invoice_candidates AS (\n'
            f'  SELECT {", ".join(select)}, SUBSTRING({invoice_date_expr}, 1, 4) AS "invoice_year", '
            f'ROW_NUMBER() OVER (PARTITION BY SUBSTRING({invoice_date_expr}, 1, 4), k."waerk" '
            f'ORDER BY {invoice_amount} ASC, k."vbeln" ASC) AS "invoice_rank"\n'
            f'  FROM "{invoice_table}" k\n'
            + (f'{customer_join_sql}\n' if customer_join_sql else '')
            + '  WHERE ' + '\n    AND '.join(scoped_predicates) + '\n),\n'
            + f'invoice_cohort AS (SELECT * FROM invoice_candidates WHERE "invoice_rank" <= {limit})'
        )

    order_year_a = (
        f'({order_date_expr} >= \'{year_a}0101\' AND '
        f'{order_date_expr} < \'{int(year_a) + 1:04d}0101\')'
    )
    order_year_b = (
        f'({order_date_expr} >= \'{year_b}0101\' AND '
        f'{order_date_expr} < \'{int(year_b) + 1:04d}0101\')'
    )
    order_currency_match = (
        'UPPER(TRIM(CAST(l."linked_order_currency" AS TEXT))) = UPPER(i."currency")'
    )
    linked_projection = (
        'i."billing_document", o."vbeln" AS "linked_order_key", '
        'TRIM(CAST(o."vbeln" AS TEXT)) AS "linked_sales_order", '
        'o."erdat" AS "linked_order_date", o."netwr" AS "linked_order_amount", '
        'o."waerk" AS "linked_order_currency"'
    )
    linked_query = (
        f'  SELECT DISTINCT {linked_projection}\n'
        '  FROM invoice_cohort i\n'
        f'  JOIN "{flow_table}" f ON f."vbeln" = i."_billing_document_key"\n'
        f'  JOIN "{order_table}" o ON o."vbeln" = f."vbelv"\n'
    )
    # The item order reference and document flow are independent verified
    # relationships. UNION deduplicates orders reached through both routes.
    if has_table("vbrp") and all(has_column("vbrp", col) for col in ("vbeln", "aubel")):
        item_table = resolve_table_name("vbrp") or "vbrp"
        linked_query += (
            '  UNION\n'
            f'  SELECT DISTINCT {linked_projection}\n'
            '  FROM invoice_cohort i\n'
            f'  JOIN "{item_table}" b ON b."vbeln" = i."_billing_document_key"\n'
            f'  JOIN "{order_table}" o ON o."vbeln" = b."aubel"\n'
        )
    linked_cte = (
        'linked_orders AS (\n'
        + linked_query +
        ')'
    )
    periods_cte = (
        'order_periods AS (\n'
        '  SELECT l."billing_document", i."currency", '
        'STRING_AGG(DISTINCT l."linked_sales_order", \', \' ORDER BY l."linked_sales_order") AS "linked_sales_orders", '
        'COUNT(DISTINCT l."linked_order_key") AS "linked_order_count_all_periods", '
        'MIN(l."linked_order_date") AS "earliest_linked_order_date", '
        'MAX(l."linked_order_date") AS "latest_linked_order_date", '
        f'COUNT(DISTINCT CASE WHEN NOT ({order_year_a} OR {order_year_b}) THEN l."linked_order_key" END) AS "linked_order_count_outside_comparison", '
        f'COUNT(DISTINCT CASE WHEN {order_year_a} AND {order_currency_match} THEN l."linked_order_key" END) AS "linked_order_count_{year_a}", '
        f'SUM(CASE WHEN {order_year_a} AND {order_currency_match} THEN {order_amount} END) AS "order_amount_{year_a}", '
        f'COUNT(DISTINCT CASE WHEN {order_year_b} AND {order_currency_match} THEN l."linked_order_key" END) AS "linked_order_count_{year_b}", '
        f'SUM(CASE WHEN {order_year_b} AND {order_currency_match} THEN {order_amount} END) AS "order_amount_{year_b}", '
        f'COUNT(DISTINCT CASE WHEN ({order_year_a} OR {order_year_b}) AND NOT ({order_currency_match}) THEN l."linked_order_key" END) AS "currency_mismatch_order_count"\n'
        '  FROM linked_orders l\n'
        '  JOIN invoice_cohort i ON i."billing_document" = l."billing_document"\n'
        '  GROUP BY l."billing_document", i."currency"\n'
        ')'
    )
    change_expr = f'(p."order_amount_{year_b}" - p."order_amount_{year_a}")'
    pct_expr = (
        f'ROUND(({change_expr}) / NULLIF(ABS(p."order_amount_{year_a}"), 0) * 100, 2)'
    )
    customer_name_result = (
        'i."customer_name", '
        if has_table("KNA1") and has_column("KNA1", "kunnr") and has_column("KNA1", "name1")
        else ""
    )
    return (
        'WITH ' + candidate_cte + ',\n' + linked_cte + ',\n' + periods_cte + '\n'
        'SELECT i."billing_document", i."customer_id", ' + customer_name_result +
        ('i."invoice_year", i."invoice_rank", ' if each_invoice_period else '') +
        'i."invoice_date", i."invoice_amount", i."currency", p."linked_sales_orders", '
        'p."linked_order_count_all_periods", p."earliest_linked_order_date", p."latest_linked_order_date", '
        'p."linked_order_count_outside_comparison", '
        f'p."linked_order_count_{year_a}", p."order_amount_{year_a}", '
        f'p."linked_order_count_{year_b}", p."order_amount_{year_b}", p."currency_mismatch_order_count", '
        f'{change_expr} AS "absolute_change", {pct_expr} AS "percent_change"\n'
        'FROM invoice_cohort i\n'
        'LEFT JOIN order_periods p ON p."billing_document" = i."billing_document"\n'
        'ORDER BY ' + ('i."invoice_year", ' if each_invoice_period else '') +
        'i."customer_id", i."invoice_amount" ASC, i."billing_document"'
    )


def build_period_compare_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
    *,
    aggregate_only: bool = False,
    force_dims: Optional[List[str]] = None,
) -> Optional[str]:
    """Generic period-change SQL from semantic period_compare (any year pair).

    When aggregate_only=True, emit a single totals row (confirm-direction gate)
    with no entity GROUP BY — used by investigation re-planning.
    When force_dims is set, use those dimensions (investigation grain switch).
    """
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
    original_user_question = str(
        (semantic or {}).get("_original_user_question") or question or ""
    )
    period = req.get("period_compare")
    if not isinstance(period, dict):
        return None
    y_a = None
    y_b = None
    for key, dest in (("base_period", "a"), ("comparison_period", "b")):
        val = period.get(key)
        year = None
        if isinstance(val, dict):
            year = val.get("year") or (str(val.get("start") or "")[:4] if val.get("start") else None)
        elif val is not None:
            year = str(val)
        if year and re.fullmatch(r"\d{4}", str(year)):
            if dest == "a":
                y_a = str(year)
            else:
                y_b = str(year)
    if not y_a or not y_b:
        years = extract_question_years(question)
        if len(years) >= 2:
            y_a, y_b = sorted(set(years))[0], sorted(set(years))[-1]
        else:
            return None
    # A conversation rewrite can mention a prior query's year (for example,
    # "the 2017 top customers") alongside the current comparison. The user's
    # current message is authoritative for the periods being compared.
    explicit_user_years = extract_question_years(original_user_question)
    if len(explicit_user_years) >= 2:
        y_a, y_b = explicit_user_years[-2], explicit_user_years[-1]
    if not has_table("VBRK") or not has_column("VBRK", "netwr") or not has_column("VBRK", "fkdat"):
        return None

    hdr = resolve_table_name("VBRK") or "VBRK"
    net = f'CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), \'\') AS NUMERIC)'
    yexpr = 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4)'
    month_requested = bool(
        re.search(r"\b(monthly|month[- ]by[- ]month|by month|per month|each month|monthly comparison)\b", original_user_question, re.I)
        or "month" in [str(d).lower() for d in (req.get("group_by") or req.get("dimensions") or [])]
    )
    if month_requested and not aggregate_only:
        # Compare like-for-like months across the requested years. Keep each
        # currency as its own row because the nominal amounts are incomparable.
        currency_col = next((c for c in ("waerk", "waers", "rtcur") if has_column(hdr, c)), None)
        document_col = next((c for c in ("vbeln", "belnr") if has_column(hdr, c)), None)
        if not currency_col or not document_col:
            return None
        month_expr = 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 5, 2)'
        amount_a = f"SUM(CASE WHEN {yexpr} = '{y_a}' THEN {net} ELSE 0 END)"
        amount_b = f"SUM(CASE WHEN {yexpr} = '{y_b}' THEN {net} ELSE 0 END)"
        difference = f"({amount_b} - {amount_a})"
        identity_columns = [
            column for column in ("mandt", document_col, "fkdat", currency_col, "netwr")
            if has_column(hdr, column)
        ]
        if document_col not in identity_columns or "fkdat" not in identity_columns or "netwr" not in identity_columns:
            return None
        identity_projection = ", ".join(f'src."{column}"' for column in identity_columns)
        return (
            'WITH "billing_document_rows" AS (\n'
            f'  SELECT DISTINCT {identity_projection} FROM "{hdr}" src\n'
            ')\n'
            f'SELECT {month_expr} AS "month", TRIM(CAST(k."{currency_col}" AS TEXT)) AS "currency", '
            f'{amount_a} AS "period_a", {amount_b} AS "period_b", '
            f'{difference} AS "change"\n'
            'FROM "billing_document_rows" k\n'
            f"WHERE NULLIF(TRIM(CAST(k.\"fkdat\" AS TEXT)), '') IS NOT NULL\n"
            f"  AND {yexpr} IN ('{y_a}', '{y_b}')\n"
            f'GROUP BY {month_expr}, TRIM(CAST(k."{currency_col}" AS TEXT))\n'
            f'ORDER BY "month", "currency"'
        )
    if aggregate_only:
        period_a = f"SUM(CASE WHEN {yexpr} = '{y_a}' THEN {net} ELSE 0 END)"
        period_b = f"SUM(CASE WHEN {yexpr} = '{y_b}' THEN {net} ELSE 0 END)"
        change = f"({period_b} - {period_a})"
        currency_col = next((col for col in ("waerk", "waers", "rtcur") if has_column(hdr, col)), None)
        currency_select = ""
        currency_group = ""
        if currency_col:
            currency_select = f', TRIM(CAST(k."{currency_col}" AS TEXT)) AS "currency"'
            currency_group = f'\nGROUP BY TRIM(CAST(k."{currency_col}" AS TEXT))'
        return (
            f'SELECT {period_a} AS "period_a", {period_b} AS "period_b", '
            f'{change} AS "change"{currency_select}\n'
            f'FROM "{hdr}" k\n'
            f"WHERE NULLIF(TRIM(CAST(k.\"fkdat\" AS TEXT)), '') IS NOT NULL\n"
            f"  AND {yexpr} IN ('{y_a}', '{y_b}')" + currency_group
        )

    if force_dims is not None:
        dims = [d for d in force_dims if d not in {"year", "month", "quarter"}]
    else:
        dims = [
            d
            for d in (req.get("group_by") or req.get("dimensions") or [])
            if d not in {"year", "month", "quarter"}
        ]
    if not dims:
        if re.search(r"\bcustomers?\b", question or "", re.I):
            dims = ["customer"]
        elif re.search(r"\bcountr", question or "", re.I):
            dims = ["country"]
        elif re.search(r"\b(materials?|products?)\b", question or "", re.I):
            dims = ["material"]
        elif period.get("contribution") or req.get("contribution") or re.search(
            r"\b(why\s+did|contribut\w*|accounted for)\b", question or "", re.I
        ):
            dims = ["customer"]
        elif re.search(
            r"\b(how much|what (was|were) the (change|difference)|did .+ (increase|decrease)|better than|worse than)\b",
            question or "",
            re.I,
        ):
            # Scalar period change — no entity grain.
            return build_period_compare_sql(
                question, tables, semantic, aggregate_only=True
            )
        else:
            # A year comparison that names no customer, country, or material
            # compares the totals. It does not list every customer.
            return build_period_compare_sql(
                question, tables, semantic, aggregate_only=True
            )

    sel: List[str] = []
    gb: List[str] = []
    joins: List[str]
    where: List[str]

    if "material" in dims and has_table("vbrp") and has_table("MAKT"):
        joins = [
            'FROM "vbrp" p',
            f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') = '
            f'LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')',
            _makt_join("p.\"matnr\""),
        ]
        net = 'CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)'
        sel.append('TRIM(p."matnr") AS "material_id"')
        gb.append('TRIM(p."matnr")')
        if has_column("MAKT", "maktx"):
            sel.append('TRIM(m."maktx") AS "material_name"')
            gb.append('TRIM(m."maktx")')
    else:
        joins = [f'FROM "{hdr}" k']
        if any(d in {"customer", "country", "industry"} for d in dims) and has_table("KNA1"):
            joins.append(
                'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
                'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
            )
        for d in dims:
            if d == "customer" and has_table("KNA1"):
                sel.append('TRIM(c."kunnr") AS "customer_id"')
                gb.append('TRIM(c."kunnr")')
                if has_column("KNA1", "name1"):
                    sel.append('TRIM(c."name1") AS "customer_name"')
                    gb.append('TRIM(c."name1")')
            elif d == "country" and has_column("KNA1", "land1"):
                sel.append('TRIM(c."land1") AS "country"')
                gb.append('TRIM(c."land1")')
            elif d == "industry" and has_column("KNA1", "brsch"):
                sel.append('TRIM(c."brsch") AS "industry"')
                gb.append('TRIM(c."brsch")')

    if not sel:
        return None

    where = [
        "NULLIF(TRIM(CAST(k.\"fkdat\" AS TEXT)), '') IS NOT NULL",
        f"{yexpr} IN ('{y_a}', '{y_b}')",
    ]
    comparison = req.get("comparison")
    measure_predicate = None
    if isinstance(comparison, dict):
        operator = str(comparison.get("operator") or "")
        value = comparison.get("value")
        if operator in {"<", "<=", ">", ">=", "=", "!=", "<>"} and isinstance(value, (int, float)) and not isinstance(value, bool):
            import math

            if math.isfinite(value):
                where.append(f"{net} {operator} {value}")
                measure_predicate = (operator, value)
    # A referential follow-up such as "for the same customers returned
    # previously" must scope the aggregate to verified IDs from that result.
    # Names and arbitrary model filters are not accepted as entity identifiers.
    same_customer_scope = bool(
        re.search(
            r"\b(?:(?:same|those|these|previous|prior)\s+){1,2}(?:result\s+)?customers?\b|"
            r"\bcustomers?\s+(?:returned|identified|selected)\s+previously\b",
            original_user_question,
            re.I,
        )
    )
    scoped_customer_ids: List[str] = []
    if same_customer_scope:
        prior_rows = (semantic or {}).get("prior_result_rows") if isinstance(semantic, dict) else []
        prior_customer_ids = []
        for row in prior_rows or []:
            if not isinstance(row, dict):
                continue
            value = next(
                (
                    row.get(key)
                    for key in ("customer_id", "kunnr", "kunag", "customer_number", "sold_to_customer")
                    if row.get(key) is not None and str(row.get(key)).strip()
                ),
                None,
            )
            if value is not None:
                prior_customer_ids.append(str(value).strip())
        prior_customer_ids = list(dict.fromkeys(prior_customer_ids))
        customer_col = next((c for c in ("kunag", "kunnr") if has_column(hdr, c)), None)
        if not prior_customer_ids or not customer_col:
            return None
        if len(prior_customer_ids) > 200:
            # Do not silently truncate a prior-result scope and claim completeness.
            return None
        id_expr = f'LPAD(TRIM(CAST(k."{customer_col}" AS TEXT)), 10, \'0\')'
        id_values = ", ".join(
            f"LPAD('{value.replace(chr(39), chr(39) * 2)}', 10, '0')"
            for value in prior_customer_ids
        )
        where.append(f"{id_expr} IN ({id_values})")
        scoped_customer_ids = prior_customer_ids
    period_a = f"SUM(CASE WHEN {yexpr} = '{y_a}' THEN {net} ELSE 0 END)"
    period_b = f"SUM(CASE WHEN {yexpr} = '{y_b}' THEN {net} ELSE 0 END)"
    change = f"({period_b} - {period_a})"
    sel.extend([
        f'{period_a} AS "period_a"',
        f'{period_b} AS "period_b"',
        f'{change} AS "change"',
    ])
    # Keep explicitly requested document identifiers in the selected period's
    # customer row. A text-only narrative cannot satisfy a request to list the
    # source billing documents, and the grouping grain remains customer-level.
    include_fields = (semantic or {}).get("include_fields") if isinstance(semantic, dict) else []
    include_document_numbers = bool(
        re.search(r"\b(?:invoice|billing\s+document)\s+numbers?\b", original_user_question, re.I)
        or any(
            isinstance(field, dict)
            and str(field.get("field") or "").lower() in {
                "invoice_number", "billing_document", "billing_document_number", "document_number"
            }
            for field in (include_fields or [])
        )
    )
    if include_document_numbers and has_column(hdr, "vbeln"):
        base_documents = (
            f"STRING_AGG(DISTINCT CASE WHEN {yexpr} = '{y_a}' "
            'THEN TRIM(CAST(k."vbeln" AS TEXT)) END, \', \')'
        )
        sel.append(f'{base_documents} AS "invoice_numbers_{y_a}"')

    calculation = str(period.get("calculation") or "").lower()
    if calculation in {"both", "percentage_change", "percent_change", "percentage"} or re.search(
        r"\b(percent(?:age)?\s+change|pct\s+change)\b|%\s*change",
        original_user_question,
        re.I,
    ):
        sel.append(
            f'ROUND(100.0 * {change} / NULLIF({period_a}, 0), 2) AS "percent_change"'
        )
    condition = str(period.get("condition") or period.get("op") or "").lower()
    having = None
    ql = (question or "").lower()
    # Ranking by magnitude of decline/growth still needs the correct signed filter.
    # Decline language wins when both cues appear or LLM pollutes condition as growth.
    if re.search(r"\b(declin\w*|decreas\w*|drop(?:ped|s)?|fell|falling|reduc\w*)\b", ql) or condition in {
        "decreased", "decline", "decrease"
    }:
        having = f"{change} < 0"
        order_dir = "ASC"
    elif condition in {"increased", "growth", "increase"} or re.search(
        r"\b(grew|increased|growth|increase)\b", ql
    ):
        having = f"{change} > 0"
        order_dir = "DESC"
    else:
        order_dir = "DESC"
    # "Largest decline" / "grew the most" / contribution ranking → top-N by change.
    lim = 50
    ranking = req.get("ranking") if isinstance(req.get("ranking"), dict) else None
    if ranking and ranking.get("limit"):
        lim = int(ranking["limit"])
    elif re.search(r"\b(largest|biggest|strongest|most)\b", ql) and re.search(
        r"\b(declin|decreas|growth|grew|increase|contribut)\b", ql
    ):
        lim = extract_ranking_limit(question, default=1)
    want_contribution = bool(
        period.get("contribution")
        or (req.get("contribution") if isinstance(req, dict) else False)
        or re.search(r"\b(contribut\w*|why\s+did|what\s+caused)\b", ql)
    )
    order_field = "change"
    if ranking and not having and not want_contribution:
        rank_metric = str(ranking.get("metric") or ranking.get("measure") or "").lower()
        if not any(term in rank_metric for term in ("change", "growth", "difference", "decline")):
            order_field = "period_a"
            order_dir = str(ranking.get("direction") or "DESC").upper()
    # The ranked baseline cohort must actually exist in the baseline period.
    # Comparison-only entities cannot enter the ranking through CASE ELSE 0.
    baseline_rank = bool(ranking and order_field == "period_a")
    baseline_count = f"COUNT(CASE WHEN {yexpr} = '{y_a}' THEN 1 END)"
    baseline_having = [f"{baseline_count} > 0"] if baseline_rank else []
    if baseline_rank and measure_predicate:
        op, threshold = measure_predicate
        baseline_having.append(f"{period_a} {op} {threshold}")
    if want_contribution:
        sel.append(
            f'ROUND(100.0 * {change} / NULLIF(SUM({change}) OVER (), 0), 2) AS "contribution_pct"'
        )
        lim = min(max(int(lim), 1), 50)

    # A same-entity follow-up describes the entity set returned earlier. Drive
    # the result from that verified set and left-join period facts so customers
    # without invoices in either requested period remain visible as 0 / 0.
    # Put all fact-side predicates inside the aggregate CTE; placing a currency
    # or period condition in the outer WHERE would turn the LEFT JOIN into an
    # effective INNER JOIN and silently drop those customers again.
    if scoped_customer_ids and "customer" in dims and not aggregate_only:
        explicit_ranking = bool(re.search(
            r"\b(top|bottom|rank(?:ed|ing)?|highest|lowest|largest|smallest|most|least)\b",
            original_user_question,
            re.I,
        ))
        if not explicit_ranking:
            # The previous turn may have been a top-N query. A comparison
            # follow-up means all returned entities unless the user ranks them
            # again explicitly.
            lim = max(1, min(len(scoped_customer_ids), 200))
        customer_values = ", ".join(
            "(" + f"LPAD('{value.replace(chr(39), chr(39) * 2)}', 10, '0')" + ")"
            for value in scoped_customer_ids
        )
        customer_expr = f'LPAD(TRIM(CAST(k."{customer_col}" AS TEXT)), 10, \'0\')'
        fact_select = [
            f'{customer_expr} AS "customer_id"',
            f'{period_a} AS "period_a"',
            f'{period_b} AS "period_b"',
        ]
        if baseline_rank:
            fact_select.append(f'{baseline_count} AS "_base_period_count"')
        if include_document_numbers and has_column(hdr, "vbeln"):
            fact_select.append(
                f'{base_documents} AS "invoice_numbers_{y_a}"'
            )
        fact_sql = (
            'period_totals AS (\n'
            f'    SELECT {", ".join(fact_select)}\n'
            f'    FROM "{hdr}" k\n'
            f'    WHERE NULLIF(TRIM(CAST(k."fkdat" AS TEXT)), \'\') IS NOT NULL\n'
            f'      AND {yexpr} IN (\'{y_a}\', \'{y_b}\')\n'
            f'      AND {customer_expr} IN (SELECT customer_id FROM selected_customers)\n'
            f'    GROUP BY {customer_expr}\n'
            ')'
        )
        out_select = ['sc.customer_id AS "customer_id"']
        out_joins = []
        if has_table("KNA1") and has_column("KNA1", "kunnr"):
            out_joins.append(
                'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\') = sc.customer_id'
            )
            if has_column("KNA1", "name1"):
                out_select.append('TRIM(c."name1") AS "customer_name"')
        period_a_out = 'COALESCE(pt."period_a", 0)'
        period_b_out = 'COALESCE(pt."period_b", 0)'
        change_out = f'({period_b_out} - {period_a_out})'
        out_select.extend([
            f'{period_a_out} AS "period_a"',
            f'{period_b_out} AS "period_b"',
            f'{change_out} AS "change"',
        ])
        if include_document_numbers and has_column(hdr, "vbeln"):
            out_select.append(f'pt."invoice_numbers_{y_a}" AS "invoice_numbers_{y_a}"')
        if calculation in {"both", "percentage_change", "percent_change", "percentage"} or re.search(
            r"\b(percent(?:age)?\s+change|pct\s+change)\b|%\s*change",
            original_user_question,
            re.I,
        ):
            out_select.append(
                f'ROUND(100.0 * {change_out} / NULLIF({period_a_out}, 0), 2) AS "percent_change"'
            )
        if want_contribution:
            out_select.append(
                f'ROUND(100.0 * {change_out} / NULLIF(SUM({change_out}) OVER (), 0), 2) AS "contribution_pct"'
            )
        scoped_sql = (
            'WITH selected_customers(customer_id) AS (\n'
            f'    VALUES {customer_values}\n'
            '),\n'
            f'{fact_sql}\n'
            f'SELECT {", ".join(out_select)}\n'
            'FROM selected_customers sc\n'
            + ("\n".join(out_joins) + "\n" if out_joins else "")
            + 'LEFT JOIN period_totals pt ON pt.customer_id = sc.customer_id\n'
        )
        scoped_filters = []
        if having:
            scoped_filters.append(f'{change_out} {"< 0" if having.endswith("< 0") else "> 0"}')
        if baseline_rank:
            scoped_filters.append('pt."_base_period_count" > 0')
            if measure_predicate:
                op, threshold = measure_predicate
                scoped_filters.append(f"{period_a_out} {op} {threshold}")
        if scoped_filters:
            scoped_sql += "WHERE " + " AND ".join(scoped_filters) + "\n"
        scoped_sql += f'ORDER BY "{order_field}" {order_dir}\nLIMIT {max(1, min(int(lim), 200))}'
        return scoped_sql

    sql = (
        f"SELECT {', '.join(sel)}\n"
        + "\n".join(joins) + "\n"
        + "WHERE " + "\n  AND ".join(where) + "\n"
        + f"GROUP BY {', '.join(gb)}\n"
    )
    having_parts = ([having] if having else []) + baseline_having
    if having_parts:
        sql += "HAVING " + " AND ".join(having_parts) + "\n"
    sql += f'ORDER BY "{order_field}" {order_dir}\nLIMIT {max(1, min(int(lim), 200))}'
    return sql


def build_partitioned_topn_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generic partitioned Top-N (e.g. top 5 customers in each country / plant)."""
    from .analytical_sql_safety import canonicalize_text_joins
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
    ranking = req.get("ranking") if isinstance(req.get("ranking"), dict) else None
    parts = list((ranking or {}).get("partition_by") or req.get("partition_by") or [])
    if not parts:
        return None
    limit = int((ranking or {}).get("limit") or 5)
    direction = str((ranking or {}).get("direction") or "DESC").upper()
    partition = str(parts[0]).lower()
    q = (question or "").lower()
    entity = "material" if re.search(r"\b(materials?|products?)\b", q) else "customer"

    # Plant partition (vbrp.werks)
    if partition in {"plant", "werks"}:
        if not has_table("vbrp") or not has_column("vbrp", "werks"):
            return None
        line = resolve_table_name("vbrp") or "vbrp"
        hdr = resolve_table_name("VBRK") or "VBRK"
        metric_col = "fkimg" if re.search(r"\b(quantity|qty)\b", q) and has_column(line, "fkimg") else "netwr"
        if not has_column(line, metric_col):
            return None
        metric = f'CAST(NULLIF(TRIM(CAST(p."{metric_col}" AS TEXT)), \'\') AS NUMERIC)'
        alias = "billed_quantity" if metric_col == "fkimg" else "total_sales"
        sel_parts = [
            'TRIM(CAST(p."werks" AS TEXT)) AS "plant"',
            'TRIM(CAST(p."matnr" AS TEXT)) AS "material_id"',
            f'SUM({metric}) AS "{alias}"',
        ]
        gb = 'TRIM(CAST(p."werks" AS TEXT)), TRIM(CAST(p."matnr" AS TEXT))'
        joins = [f'FROM "{line}" p']
        if has_table("VBRK"):
            joins.append(
                f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') = '
                f'LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')'
            )
        if has_table("MAKT") and has_column("MAKT", "maktx"):
            joins.append(_makt_join("p.\"matnr\""))
            sel_parts.insert(2, 'TRIM(m."maktx") AS "material_name"')
            gb += ', TRIM(m."maktx")'
        inner = (
            f"SELECT {', '.join(sel_parts)}\n"
            + "\n".join(joins) + "\n"
            + "WHERE NULLIF(TRIM(CAST(p.\"werks\" AS TEXT)), '') IS NOT NULL\n"
            + f"  AND NULLIF(TRIM(CAST(p.\"matnr\" AS TEXT)), '') IS NOT NULL\n"
            + f"GROUP BY {gb}"
        )
        return canonicalize_text_joins(
            f"SELECT * FROM (\n"
            f"  SELECT inner_q.*, ROW_NUMBER() OVER ("
            f"PARTITION BY \"plant\" ORDER BY \"{alias}\" {direction}"
            f") AS rank_in_partition\n"
            f"  FROM (\n{inner}\n  ) inner_q\n"
            f") ranked WHERE rank_in_partition <= {limit}"
        )

    if partition != "country" or not has_table("VBRK") or not has_table("KNA1"):
        return None
    if not has_column("KNA1", "land1"):
        return None
    hdr = resolve_table_name("VBRK") or "VBRK"

    if entity == "material" and has_table("vbrp"):
        line = resolve_table_name("vbrp") or "vbrp"
        metric_col = "fkimg" if re.search(r"\b(quantity|qty)\b", q) and has_column(line, "fkimg") else "netwr"
        if not has_column(line, metric_col):
            return None
        metric = f'CAST(NULLIF(TRIM(CAST(p."{metric_col}" AS TEXT)), \'\') AS NUMERIC)'
        alias = "billed_quantity" if metric_col == "fkimg" else "total_sales"
        joins = [
            f'FROM "{line}" p',
            f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') = '
            f'LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')',
            'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')',
        ]
        if has_table("MAKT"):
            joins.append(_makt_join("p.\"matnr\""))
            sel = (
                f'TRIM(c."land1") AS "country", TRIM(p."matnr") AS "material_id", '
                f'TRIM(m."maktx") AS "material_name", SUM({metric}) AS "{alias}"'
            )
            gb = 'TRIM(c."land1"), TRIM(p."matnr"), TRIM(m."maktx")'
        else:
            sel = (
                f'TRIM(c."land1") AS "country", TRIM(p."matnr") AS "material_id", '
                f'SUM({metric}) AS "{alias}"'
            )
            gb = 'TRIM(c."land1"), TRIM(p."matnr")'
        inner = (
            f"SELECT {sel}\n"
            + "\n".join(joins) + "\n"
            + "WHERE NULLIF(TRIM(CAST(c.\"land1\" AS TEXT)), '') IS NOT NULL\n"
            + f"GROUP BY {gb}"
        )
        order_field = alias
    else:
        if not has_column(hdr, "netwr"):
            return None
        net = 'CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), \'\') AS NUMERIC)'
        inner = (
            f'SELECT TRIM(c."land1") AS "country", TRIM(c."kunnr") AS "customer_id", '
            f'TRIM(c."name1") AS "customer_name", SUM({net}) AS "total_sales"\n'
            f'FROM "{hdr}" k\n'
            f'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
            f'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')\n'
            f"WHERE NULLIF(TRIM(CAST(c.\"land1\" AS TEXT)), '') IS NOT NULL\n"
            f'GROUP BY TRIM(c."land1"), TRIM(c."kunnr"), TRIM(c."name1")'
        )
        order_field = "total_sales"

    return canonicalize_text_joins(
        f"SELECT * FROM (\n"
        f"  SELECT inner_q.*, ROW_NUMBER() OVER ("
        f"PARTITION BY \"country\" ORDER BY \"{order_field}\" {direction}"
        f") AS rank_in_partition\n"
        f"  FROM (\n{inner}\n  ) inner_q\n"
        f") ranked WHERE rank_in_partition <= {limit}"
    )


def build_relative_document_list_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Row-level document list for relative calendar periods (e.g. invoices last month)."""
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
    df = req.get("date_filter")
    if not isinstance(df, dict) or not df.get("start_yyyymmdd"):
        return None
    q = (question or "").lower()
    if re.search(r"\b(top|highest|lowest|sum|total|rank|growth|decline)\b", q):
        return None
    if not re.search(r"\b(show|list|display|from)\b", q):
        return None

    start = str(df["start_yyyymmdd"])
    end = str(df["end_yyyymmdd"])
    if re.search(r"\b(invoices?|billing|billed)\b", q) and has_table("VBRK") and has_column("VBRK", "fkdat"):
        hdr = resolve_table_name("VBRK") or "VBRK"
        cols = [
            f'TRIM(CAST("{hdr}"."vbeln" AS TEXT)) AS "invoice_id"',
            f'TRIM(CAST("{hdr}"."fkdat" AS TEXT)) AS "invoice_date"',
        ]
        if has_column(hdr, "kunag"):
            cols.append(f'TRIM(CAST("{hdr}"."kunag" AS TEXT)) AS "customer_id"')
        if has_column(hdr, "netwr"):
            cols.append(f'{numeric_cast_expr(hdr, "netwr")} AS "invoice_amount"')
        if has_column(hdr, "waerk"):
            cols.append(f'TRIM(CAST("{hdr}"."waerk" AS TEXT)) AS "currency"')
        return (
            f"SELECT {', '.join(cols)}\n"
            f'FROM "{hdr}"\n'
            f"WHERE TRIM(CAST(\"{hdr}\".\"fkdat\" AS TEXT)) >= '{start}'\n"
            f"  AND TRIM(CAST(\"{hdr}\".\"fkdat\" AS TEXT)) < '{end}'\n"
            f'ORDER BY "invoice_date" DESC\n'
            f"LIMIT 200"
        )
    if re.search(r"\b(purchase order|purchase orders|po\b)\b", q) and has_table("EKKO") and has_column("EKKO", "bedat"):
        hdr = resolve_table_name("EKKO") or "EKKO"
        return (
            f'SELECT TRIM(CAST("{hdr}"."ebeln" AS TEXT)) AS "purchase_order_id", '
            f'TRIM(CAST("{hdr}"."bedat" AS TEXT)) AS "order_date", '
            f'TRIM(CAST("{hdr}"."lifnr" AS TEXT)) AS "vendor_id"\n'
            f'FROM "{hdr}"\n'
            f"WHERE TRIM(CAST(\"{hdr}\".\"bedat\" AS TEXT)) >= '{start}'\n"
            f"  AND TRIM(CAST(\"{hdr}\".\"bedat\" AS TEXT)) < '{end}'\n"
            f'ORDER BY "order_date" DESC\n'
            f"LIMIT 200"
        )
    return None


def build_document_total_count_sql(
    question: str, tables: List[str], semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Count explicit SAP documents at their header key, never a nearby ledger."""
    q = (question or "").lower()
    if not re.search(r"\b(?:count|how many|number of)\b", q):
        return None
    # Only supported filters belong here. Other predicates must be planned
    # normally rather than silently erased by this capability.
    missing_currency = bool(re.search(
        r"\b(?:missing|blank|empty|without|no)\s+(?:(?:a|the)\s+)?currency(?:\s+code)?\b",
        q,
    ))
    allowed = {
        "count", "how", "many", "number", "of", "sales", "orders", "order",
        "billed", "billing", "invoices", "invoice", "documents", "document",
        "are", "were", "was", "there", "do", "we", "have", "the", "all", "total",
        "distinct", "issued", "in", "for", "during", "year", "years", "and", "please",
    }
    if missing_currency:
        allowed.update({"missing", "blank", "empty", "without", "no", "a", "currency", "code", "with"})
    tokens = re.findall(r"[a-z0-9_]+", q)
    if any(token not in allowed and not re.fullmatch(r"(?:19|20)\d{2}", token) for token in tokens):
        return None
    if re.search(r"\b(?:by|per|each|compare|top|highest|lowest|linked|supplier|vendor|sat|cfdi|edi)\b", q):
        return None
    if "without" in tokens and not missing_currency:
        return None
    if re.search(r"\b(?:last|latest|recent|this|previous|current)\b", q):
        return None
    if re.search(r"\bsales orders?\b", q):
        table, alias, date_col = "VBAK", "sales_order_count", "audat"
    elif re.search(r"\b(?:billed|billing|invoices?)\b", q):
        table, alias, date_col = "VBRK", "billing_document_count", "fkdat"
    else:
        return None
    if missing_currency and (table != "VBRK" or not has_column(table, "waerk")):
        return None
    if not has_table(table) or not has_column(table, "vbeln"):
        return None
    table = resolve_table_name(table) or table
    document_key = f'NULLIF(TRIM(CAST("{table}"."vbeln" AS TEXT)), \'\')'
    keys = [document_key]
    if has_column(table, "mandt"):
        keys.insert(0, f'TRIM(CAST("{table}"."mandt" AS TEXT))')
    identity = '(' + ', '.join(keys) + ')' if len(keys) > 1 else keys[0]
    filters = [document_key + ' IS NOT NULL']
    if missing_currency:
        filters.append(f'NULLIF(TRIM(CAST("{table}"."waerk" AS TEXT)), \'\') IS NULL')
    years = extract_question_years(question)
    if years:
        if not has_column(table, date_col):
            return None
        dates = ' OR '.join(
            f'TRIM(CAST("{table}"."{date_col}" AS TEXT)) LIKE \'{year}%\''
            for year in years
        )
        filters.append('(' + dates + ')')
    return (f'SELECT COUNT(DISTINCT {identity}) AS "{alias}" FROM "{table}" WHERE '
            + ' AND '.join(filters))


def build_document_count_by_period_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """COUNT documents grouped by year/month/quarter (billing or sales orders)."""
    from .semantic_requirements import required_semantics
    from .analytical_operations import extract_analytical_operations, merge_semantic_requirements

    q = (question or "").lower()
    if not re.search(r"\b(count|how many|number of)\b", q) and not re.search(
        r"\b(each year|by year|per year|yearly|each month|by month|per month)\b", q
    ):
        return None
    # Ranking / comparison questions are not document-count trends.
    if re.search(r"\b(top|highest|lowest|growth|decline|without|above average)\b", q):
        return None

    sem = merge_semantic_requirements(question, semantic or {})
    ops = sem.get("analytical_operations") or extract_analytical_operations(question)
    req = required_semantics(question, sem)
    group_by = [str(g).lower() for g in (req.get("group_by") or ops.get("group_by") or [])]
    grain = str(ops.get("time_grain") or "").lower()
    if "month" in group_by or grain == "month" or re.search(r"\b(by|per|each)\s+month", q):
        grain = "month"
    elif "quarter" in group_by or grain == "quarter":
        grain = "quarter"
    elif "year" in group_by or grain == "year" or re.search(r"\b(by|per|each)\s+year|each year|yearly\b", q):
        grain = "year"
    else:
        return None

    # Prefer sales orders when asked; otherwise billing documents.
    use_so = bool(re.search(r"\b(sales orders?|sales documents?)\b", q)) and has_table("VBAK")
    use_billing = (not use_so) and (
        re.search(r"\b(billing|invoice|invoices|billing documents?)\b", q) or has_table("VBRK")
    )
    if use_so:
        tbl = resolve_table_name("VBAK") or "VBAK"
        id_col, date_col, alias = "vbeln", "erdat" if has_column(tbl, "erdat") else "audat", "sales_order_count"
        if not has_column(tbl, date_col) or not has_column(tbl, id_col):
            return None
    elif use_billing and has_table("VBRK") and has_column("VBRK", "fkdat"):
        tbl = resolve_table_name("VBRK") or "VBRK"
        id_col, date_col, alias = "vbeln", "fkdat", "billing_document_count"
    else:
        return None

    date_expr = f'TRIM(CAST("{tbl}"."{date_col}" AS TEXT))'
    if grain == "month":
        bucket, label = f"SUBSTRING({date_expr}, 1, 6)", "month"
    elif grain == "quarter":
        bucket = (
            f"SUBSTRING({date_expr}, 1, 4) || '-Q' || "
            f"CAST(CEIL(CAST(SUBSTRING({date_expr}, 5, 2) AS NUMERIC) / 3) AS INTEGER)"
        )
        label = "quarter"
    else:
        bucket, label = f"SUBSTRING({date_expr}, 1, 4)", "year"

    return (
        f'SELECT {bucket} AS "{label}", '
        f'COUNT(DISTINCT TRIM(CAST("{tbl}"."{id_col}" AS TEXT))) AS "{alias}"\n'
        f'FROM "{tbl}"\n'
        f"WHERE NULLIF({date_expr}, '') IS NOT NULL\n"
        f"GROUP BY {bucket}\n"
        f'ORDER BY "{label}" ASC'
    )


def build_above_average_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Entities whose measure is above/below the overall entity average."""
    q = (question or "").lower()
    below = bool(re.search(r"\b(below|under|less than)\s+(?:the\s+)?average\b", q))
    above = bool(re.search(r"\b(above|over|greater than|higher than)\s+(?:the\s+)?average\b", q))
    if not (above or below):
        ops = (semantic or {}).get("analytical_operations") if isinstance(semantic, dict) else {}
        cf = (semantic or {}).get("comparison_filter") if isinstance(semantic, dict) else None
        if isinstance(ops, dict) and isinstance(ops.get("comparison_filter"), dict):
            cf = ops["comparison_filter"]
        if isinstance(cf, dict):
            below = str(cf.get("type") or "").lower() == "below_average"
            above = str(cf.get("type") or "").lower() == "above_average"
        if not (above or below):
            return None
    if not has_table("VBRK") or not has_table("KNA1"):
        return None
    hdr = resolve_table_name("VBRK") or "VBRK"
    if not has_column(hdr, "netwr") or not has_column(hdr, "kunag"):
        return None
    net = "CAST(NULLIF(TRIM(CAST(k.\"netwr\" AS TEXT)), '') AS NUMERIC)"
    op = "<" if below else ">"
    return (
        f'WITH cust AS (\n'
        f'  SELECT TRIM(c."kunnr") AS "customer_id", TRIM(c."name1") AS "customer_name",\n'
        f'         SUM({net}) AS "total_sales"\n'
        f'  FROM "{hdr}" k\n'
        f'  LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
        f'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')\n'
        f"  WHERE NULLIF(TRIM(CAST(k.\"kunag\" AS TEXT)), '') IS NOT NULL\n"
        f'  GROUP BY TRIM(c."kunnr"), TRIM(c."name1")\n'
        f'), avg_v AS (\n'
        f'  SELECT AVG("total_sales") AS "avg_sales" FROM cust\n'
        f')\n'
        f'SELECT cust.*, avg_v."avg_sales"\n'
        f'FROM cust CROSS JOIN avg_v\n'
        f'WHERE cust."total_sales" {op} avg_v."avg_sales"\n'
        f'ORDER BY cust."total_sales" DESC\n'
        f'LIMIT 100'
    )


def build_multi_entity_having_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generic HAVING COUNT(DISTINCT dim) > N at the correct analytical grain.

    Prefer a transactional geo column (e.g. VBRK.LAND1) when the question implies
    activity attribution ("bought", "sold", "billed"). Master-only country
    (KNA1.LAND1) is refused for transactional multi-country questions because a
    customer has exactly one master country — COUNT(DISTINCT) would never exceed 1
    meaningfully for "bought in more than one country".
    """
    from .join_cardinality import (
        assess_join_cardinality,
        discover_join_path,
        resolve_master_geo_column,
        resolve_transactional_geo_column,
    )

    q = (question or "").lower()
    ops = (semantic or {}).get("analytical_operations") if isinstance(semantic, dict) else {}
    having = None
    if isinstance(ops, dict) and isinstance(ops.get("having_distinct"), dict):
        having = ops["having_distinct"]
    if isinstance(semantic, dict) and isinstance(semantic.get("having_distinct"), dict):
        having = semantic["having_distinct"]

    m = re.search(
        r"\bmore than\s+(one|1|two|2|three|3|\d+)\b|\bmultiple\b|\b(?:in|>)\s*(\d+)\s+(?:different\s+)?",
        q,
    )
    cue = bool(
        m
        or re.search(r"\b(more than one|multiple countr|across countr|in different countr)\b", q)
        or having
    )
    if not cue:
        return None

    words = {"one": 1, "1": 1, "two": 2, "2": 2, "three": 3, "3": 3}
    threshold = 1
    if isinstance(having, dict) and having.get("threshold") is not None:
        try:
            threshold = int(having["threshold"])
        except (TypeError, ValueError):
            threshold = 1
    elif m:
        raw = (m.group(1) or m.group(2) or "1").lower()
        threshold = int(words.get(raw, raw if str(raw).isdigit() else 1))

    entity = str((having or {}).get("entity") or "").lower()
    dim = str((having or {}).get("dimension") or "").lower()
    if not entity:
        if re.search(r"\b(customers?|clients?|buyers?)\b", q):
            entity = "customer"
        elif re.search(r"\b(vendors?|suppliers?)\b", q):
            entity = "vendor"
        else:
            return None
    if not dim:
        if re.search(r"\b(countr(?:y|ies)|nations?|markets?)\b", q):
            dim = "country"
        else:
            return None
    if dim not in {"country", "nation", "market"}:
        return None

    # Activity language ⇒ transactional grain required.
    transactional_needed = bool(
        re.search(
            r"\b(bought|buy|purchased|sold|billed|invoice|order|shipped|delivered|activity)\b",
            q,
        )
        or (isinstance(having, dict) and having.get("grain") == "transaction")
    )

    geo = resolve_transactional_geo_column()
    if transactional_needed and not geo:
        # No safe transactional country column — refuse rather than fabricate via master.
        return None
    if not geo:
        geo = resolve_master_geo_column(
            master_candidates=("KNA1",) if entity == "customer" else ("LFA1", "KNA1")
        )
    if not geo:
        return None

    fact = geo["table"]
    geo_col = geo["column"]

    if entity == "customer":
        if not has_column(fact, "kunag") and not has_column(fact, "kunnr"):
            return None
        cust_key = "kunag" if has_column(fact, "kunag") else "kunnr"
        if not has_table("KNA1") or not has_column("KNA1", "kunnr"):
            # Still answerable from fact customer id alone.
            return (
                f'SELECT TRIM(CAST(k."{cust_key}" AS TEXT)) AS "customer_id",\n'
                f'       COUNT(DISTINCT TRIM(CAST(k."{geo_col}" AS TEXT))) AS "distinct_country_count"\n'
                f'FROM "{fact}" k\n'
                f"WHERE NULLIF(TRIM(CAST(k.\"{geo_col}\" AS TEXT)), '') IS NOT NULL\n"
                f'  AND NULLIF(TRIM(CAST(k."{cust_key}" AS TEXT)), \'\') IS NOT NULL\n'
                f'GROUP BY TRIM(CAST(k."{cust_key}" AS TEXT))\n'
                f"HAVING COUNT(DISTINCT TRIM(CAST(k.\"{geo_col}\" AS TEXT))) > {threshold}\n"
                f'ORDER BY "distinct_country_count" DESC\n'
                f"LIMIT 200"
            )
        path = discover_join_path(fact, "KNA1") or []
        assessment = assess_join_cardinality(fact, path, aggregation=True)
        if path and not assessment["safe"]:
            return None
        # COUNT(DISTINCT fact.geo) grouped by customer — geo is on the fact side,
        # so joining KNA1 for name is N:1 and does not inflate the distinct count.
        return (
            f'SELECT TRIM(c."kunnr") AS "customer_id", TRIM(c."name1") AS "customer_name",\n'
            f'       COUNT(DISTINCT TRIM(CAST(k."{geo_col}" AS TEXT))) AS "distinct_country_count"\n'
            f'FROM "{fact}" k\n'
            f'JOIN "KNA1" c ON LPAD(TRIM(CAST(k."{cust_key}" AS TEXT)), 10, \'0\') = '
            f'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')\n'
            f"WHERE NULLIF(TRIM(CAST(k.\"{geo_col}\" AS TEXT)), '') IS NOT NULL\n"
            f'GROUP BY TRIM(c."kunnr"), TRIM(c."name1")\n'
            f"HAVING COUNT(DISTINCT TRIM(CAST(k.\"{geo_col}\" AS TEXT))) > {threshold}\n"
            f'ORDER BY "distinct_country_count" DESC\n'
            f"LIMIT 200"
        )

    if entity == "vendor":
        if not has_table("EKKO") or not has_column("EKKO", "lifnr"):
            return None
        # Vendor multi-country: prefer LFA1 master only when question is about vendor domicile;
        # for transactional PO country we need a geo on EKKO (often absent) → refuse.
        vendor_geo = resolve_transactional_geo_column(fact_candidates=("EKKO", "RBKP", "EKPO"))
        if transactional_needed and not vendor_geo:
            return None
        master = resolve_master_geo_column(master_candidates=("LFA1",))
        if not master:
            return None
        # Without transactional vendor country, master land1 cannot answer "activity in countries".
        if transactional_needed:
            return None
        return (
            f'SELECT TRIM(v."lifnr") AS "vendor_id", TRIM(v."name1") AS "vendor_name",\n'
            f'       COUNT(DISTINCT TRIM(CAST(v."{master["column"]}" AS TEXT))) AS "distinct_country_count"\n'
            f'FROM "LFA1" v\n'
            f"WHERE NULLIF(TRIM(CAST(v.\"{master['column']}\" AS TEXT)), '') IS NOT NULL\n"
            f'GROUP BY TRIM(v."lifnr"), TRIM(v."name1")\n'
            f"HAVING COUNT(DISTINCT TRIM(CAST(v.\"{master['column']}\" AS TEXT))) > {threshold}\n"
            f'ORDER BY "distinct_country_count" DESC\n'
            f"LIMIT 200"
        )

    return None


def build_negation_anti_join_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generic EXISTS / NOT EXISTS patterns for required vs forbidden entities."""
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
    neg = req.get("negation") if isinstance(req.get("negation"), dict) else None
    if not neg:
        return None
    required = str(neg.get("required") or "").lower()
    forbidden = str(neg.get("forbidden") or "").lower()
    q = (question or "").lower()

    # Suppliers/vendors with POs but no invoices (billing)
    if (
        (required in {"purchase_order", "order", "po"} or re.search(r"purchase orders?", q))
        and (forbidden in {"invoice", "billing"} or re.search(r"\bno invoices?\b", q))
        and has_table("EKKO")
    ):
        hdr = resolve_table_name("EKKO") or "EKKO"
        # Prefer MM vendor invoices (RBKP) over SD billing (VBRK) — correct LIFNR link.
        inv_tbl = None
        inv_vendor_col = "lifnr"
        if has_table("RBKP") and has_column("RBKP", "lifnr"):
            inv_tbl = resolve_table_name("RBKP") or "RBKP"
        elif has_table("VBRK") and has_column("VBRK", "kunag"):
            inv_tbl = resolve_table_name("VBRK") or "VBRK"
            inv_vendor_col = "kunag"
        if inv_tbl and has_table("LFA1"):
            return (
                f'SELECT TRIM(CAST(h."lifnr" AS TEXT)) AS "vendor_id", '
                f'TRIM(v."name1") AS "vendor_name", '
                f'COUNT(DISTINCT TRIM(CAST(h."ebeln" AS TEXT))) AS "purchase_order_count"\n'
                f'FROM "{hdr}" h\n'
                f'LEFT JOIN "LFA1" v ON LPAD(TRIM(CAST(h."lifnr" AS TEXT)), 10, \'0\') = '
                f'LPAD(TRIM(CAST(v."lifnr" AS TEXT)), 10, \'0\')\n'
                f"WHERE NULLIF(TRIM(CAST(h.\"lifnr\" AS TEXT)), '') IS NOT NULL\n"
                f"  AND NOT EXISTS (\n"
                f'    SELECT 1 FROM "{inv_tbl}" i\n'
                f'    WHERE LPAD(TRIM(CAST(i."{inv_vendor_col}" AS TEXT)), 10, \'0\') = '
                f'LPAD(TRIM(CAST(h."lifnr" AS TEXT)), 10, \'0\')\n'
                f"  )\n"
                f'GROUP BY TRIM(CAST(h."lifnr" AS TEXT)), TRIM(v."name1")\n'
                f'ORDER BY "purchase_order_count" DESC\n'
                f"LIMIT 200"
            )
        if inv_tbl:
            return (
                f'SELECT TRIM(CAST(h."lifnr" AS TEXT)) AS "vendor_id", '
                f'COUNT(DISTINCT TRIM(CAST(h."ebeln" AS TEXT))) AS "purchase_order_count"\n'
                f'FROM "{hdr}" h\n'
                f"WHERE NULLIF(TRIM(CAST(h.\"lifnr\" AS TEXT)), '') IS NOT NULL\n"
                f"  AND NOT EXISTS (\n"
                f'    SELECT 1 FROM "{inv_tbl}" i\n'
                f'    WHERE LPAD(TRIM(CAST(i."{inv_vendor_col}" AS TEXT)), 10, \'0\') = '
                f'LPAD(TRIM(CAST(h."lifnr" AS TEXT)), 10, \'0\')\n'
                f"  )\n"
                f'GROUP BY TRIM(CAST(h."lifnr" AS TEXT))\n'
                f'ORDER BY "purchase_order_count" DESC\n'
                f"LIMIT 200"
            )
        return (
            f'SELECT TRIM(CAST(h."lifnr" AS TEXT)) AS "vendor_id", '
            f'COUNT(DISTINCT TRIM(CAST(h."ebeln" AS TEXT))) AS "purchase_order_count"\n'
            f'FROM "{hdr}" h\n'
            f"WHERE NULLIF(TRIM(CAST(h.\"lifnr\" AS TEXT)), '') IS NOT NULL\n"
            f'GROUP BY TRIM(CAST(h."lifnr" AS TEXT))\n'
            f'ORDER BY "purchase_order_count" DESC\n'
            f"LIMIT 200"
        )

    # Customers with sales orders but no billing
    if (
        (required in {"sales_order", "order"} or re.search(r"sales orders?", q))
        and (forbidden in {"invoice", "billing"} or re.search(r"\bno (billing|invoices?)\b", q))
        and has_table("VBAK")
        and has_table("VBRK")
        and has_table("KNA1")
    ):
        return (
            'SELECT TRIM(c."kunnr") AS "customer_id", TRIM(c."name1") AS "customer_name", '
            'COUNT(DISTINCT TRIM(CAST(o."vbeln" AS TEXT))) AS "sales_order_count"\n'
            'FROM "VBAK" o\n'
            'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(o."kunnr" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')\n'
            "WHERE NULLIF(TRIM(CAST(o.\"kunnr\" AS TEXT)), '') IS NOT NULL\n"
            "  AND NOT EXISTS (\n"
            '    SELECT 1 FROM "VBRK" k\n'
            '    WHERE LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(o."kunnr" AS TEXT)), 10, \'0\')\n'
            "  )\n"
            'GROUP BY TRIM(c."kunnr"), TRIM(c."name1")\n'
            'ORDER BY "sales_order_count" DESC\n'
            "LIMIT 200"
        )

    # Customers with invoices but no sales orders
    if (
        (required in {"invoice", "billing"} or re.search(r"\binvoices?\b", q))
        and (forbidden in {"sales_order", "order"} or re.search(r"\bno sales orders?\b", q))
        and has_table("VBAK")
        and has_table("VBRK")
        and has_table("KNA1")
    ):
        return (
            'SELECT TRIM(c."kunnr") AS "customer_id", TRIM(c."name1") AS "customer_name", '
            'COUNT(DISTINCT TRIM(CAST(k."vbeln" AS TEXT))) AS "invoice_count"\n'
            'FROM "VBRK" k\n'
            'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')\n'
            "WHERE NULLIF(TRIM(CAST(k.\"kunag\" AS TEXT)), '') IS NOT NULL\n"
            "  AND NOT EXISTS (\n"
            '    SELECT 1 FROM "VBAK" o\n'
            '    WHERE LPAD(TRIM(CAST(o."kunnr" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\')\n'
            "  )\n"
            'GROUP BY TRIM(c."kunnr"), TRIM(c."name1")\n'
            'ORDER BY "invoice_count" DESC\n'
            "LIMIT 200"
        )
    return None


def build_sales_by_year_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Backwards-compatible entry point for year-grain sales."""
    return build_period_sales_sql(question, tables, semantic)


def build_total_measure_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Single-number totals such as 'what were total billed sales in 2003'."""
    q = (question or "").lower()
    scalar_cue = bool(
        re.search(
            r"\b(total|sum of|how much|overall|altogether|combined|"
            r"what (was|were)|how much money|generate[d]? during)\b",
            q,
        )
    )
    if not scalar_cue:
        return None
    if _SUPERLATIVE.search(q) or re.search(r"\btop\s+\d+\b", q):
        return None
    # Reject dimensional / trend questions (keep totals scalar).
    if re.search(
        r"\b(by |per |each |customer|customers|country|countries|industr|material|product|"
        r"month|monthly|quarter|vendor|trend)\b",
        q,
    ):
        return None
    if re.search(r"\bby year\b|\bper year\b|\beach year\b", q):
        return None
    if not re.search(r"\b(sales|revenue|billing|billed|turnover|money|generat)\b", q):
        return None
    if not has_table("VBRK") or not has_column("VBRK", "netwr"):
        return None

    hdr = resolve_table_name("VBRK") or "VBRK"
    net = numeric_cast_expr(hdr, "netwr")
    where = [f'NULLIF(TRIM(CAST("{hdr}"."netwr" AS TEXT)), \'\') IS NOT NULL']
    if has_column(hdr, "fkdat"):
        pred = _sap_year_predicate(f'"{hdr}"', "fkdat", extract_question_years(question))
        if pred:
            where.append(pred)
    currency_col = next((col for col in ("waerk", "waers") if has_column(hdr, col)), None)
    currency_match = re.search(r"\b(?:in|currency)\s+([A-Z]{3})\b", question or "")
    currency_select = ""
    currency_group = ""
    if currency_col and currency_match:
        where.append(f'TRIM(CAST("{hdr}"."{currency_col}" AS TEXT)) = \'{currency_match.group(1)}\'')
    elif currency_col:
        # One row per currency so a billed total can open into that currency's documents.
        currency_select = f', TRIM(CAST("{hdr}"."{currency_col}" AS TEXT)) AS "currency"'
        currency_group = f'\nGROUP BY TRIM(CAST("{hdr}"."{currency_col}" AS TEXT))\nORDER BY "currency"'

    return (
        f'SELECT SUM({net}) AS "total_sales", '
        f'COUNT(DISTINCT TRIM(CAST("{hdr}"."vbeln" AS TEXT))) AS "invoice_count"{currency_select}\n'
        f'FROM "{hdr}"\n'
        "WHERE " + "\n  AND ".join(where) + currency_group
    )


def build_customer_industry_revenue_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Customers and industries with billed revenue."""
    q = (question or "").lower()
    if not re.search(r"\b(customer|customers)\b", q):
        return None
    if not re.search(r"\b(industr(y|ies)|sector)\b", q):
        return None
    if not re.search(r"\b(revenue|sales|billing|billed)\b", q):
        return None
    if not has_table("vbrp") or not has_table("VBRK") or not has_table("KNA1"):
        return None

    limit = 200
    m = re.search(r"\b(?:top|limit)\s+(\d+)\b", q)
    if m:
        limit = min(int(m.group(1)), 500)

    where = [
        'NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') IS NOT NULL',
        'NULLIF(TRIM(CAST(k."kunag" AS TEXT)), \'\') IS NOT NULL',
    ]
    year_pred = _sap_year_predicate("k", "fkdat", extract_question_years(question))
    if year_pred and has_column("VBRK", "fkdat"):
        where.append(year_pred)

    return (
        'SELECT TRIM(c."kunnr") AS customer_id, TRIM(c."name1") AS customer_name, '
        'TRIM(t."brtxt") AS industry, '
        'SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS billed_revenue\n'
        'FROM "vbrp" p\n'
        'JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"), 10, \'0\') = LPAD(TRIM(k."vbeln"), 10, \'0\')\n'
        'LEFT JOIN "KNA1" c ON LPAD(TRIM(k."kunag"), 10, \'0\') = LPAD(TRIM(c."kunnr"), 10, \'0\')\n'
        'LEFT JOIN "T016T" t ON LPAD(TRIM(c."brsch"), 10, \'0\') = LPAD(TRIM(t."brsch"), 10, \'0\')\n'
        "WHERE " + "\n  AND ".join(where) + "\n"
        'GROUP BY 1, 2, 3\n'
        'ORDER BY billed_revenue DESC NULLS LAST\n'
        f"LIMIT {limit}"
    )


def build_sat_logs_sql(question: str, tables: List[str]) -> Optional[str]:
    """SAT processing logs, optionally narrowed to failures/errors."""
    q = (question or "").lower()
    if not re.search(r"\bsat\b", q):
        return None
    if not re.search(r"\b(log|logs|processing|process|step|steps|error|errors|fail|failed|failure)\b", q):
        return None
    if not has_table("sat_processing_logs"):
        return None

    limit = 100
    m = re.search(r"\b(?:top|limit|latest|last)\s+(\d+)\b", q)
    if m:
        limit = min(int(m.group(1)), 500)

    sql = (
        'SELECT step_name, step_status, message, error_details, created_at\n'
        'FROM "sat_processing_logs"'
    )
    if re.search(r"\b(error|errors|fail|failed|failure|failures|problem|issue)\b", q):
        sql += (
            "\nWHERE LOWER(COALESCE(step_status, '')) LIKE '%fail%'"
            "\n   OR LOWER(COALESCE(step_status, '')) LIKE '%error%'"
            "\n   OR LOWER(COALESCE(message, '')) LIKE '%error%'"
            "\n   OR error_details IS NOT NULL"
        )
    sql += f'\nORDER BY created_at DESC\nLIMIT {limit}'
    return sql


def _qualify_bare_columns_in_expression(expr: str, table: str) -> str:
    """Replace bare column tokens inside an expression with qualified identifiers."""
    tbl = resolve_table_name(table) or table
    cols = {c.lower(): c for c in column_names(tbl)}
    if not cols:
        return expr

    def repl_token(m: re.Match[str]) -> str:
        tok = m.group(0)
        low = tok.lower()
        if low in cols:
            return qualified_column(tbl, cols[low])
        return tok

    # Replace bare identifiers that match known columns (skip already quoted)
    return re.sub(r'(?<!["\w])([A-Za-z_][A-Za-z0-9_]*)(?!["\w])', repl_token, expr)


def repair_quoted_expressions_as_columns(sql: str) -> str:
    """
    Fix SQL where a function/expression was quoted as a column name.

    "VBRK"."SUBSTRING(TRIM(fkdat),1,4)" → SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4)
    """
    if not sql:
        return sql
    out = sql

    def fix_cast(m: re.Match[str]) -> str:
        table, inner, cast_type = m.group(1), m.group(2), m.group(3)
        expr = _qualify_bare_columns_in_expression(inner, table)
        if cast_type.lower() in {"int", "integer", "numeric", "float", "double"}:
            return f"CAST({expr} AS {cast_type.upper()})"
        return expr

    out = _CAST_QUOTED_EXPR.sub(fix_cast, out)

    def fix_quoted(m: re.Match[str]) -> str:
        table, inner = m.group(1), m.group(2)
        return _qualify_bare_columns_in_expression(inner, table)

    out = _QUOTED_EXPR_AS_COL.sub(fix_quoted, out)
    return out


def detect_expression_as_column_errors(sql: str) -> List[str]:
    """Pre-execution validation: find quoted expressions masquerading as columns."""
    errors: List[str] = []
    for m in _QUOTED_EXPR_AS_COL.finditer(sql or ""):
        errors.append(
            f"expression incorrectly quoted as column: {m.group(1)}.{m.group(2)[:60]}"
        )
    for m in _CAST_QUOTED_EXPR.finditer(sql or ""):
        errors.append(
            f"CAST wraps expression-as-column: {m.group(1)}.{m.group(2)[:60]}"
        )
    return errors[:8]


def classify_sql_execution_error(error_text: str) -> str:
    txt = (error_text or "").lower()
    # Error messages include the whole query; JOIN in that query does not
    # turn an expression type failure into an invalid join.
    txt = txt.split("[sql:", 1)[0]
    if re.search(r"function\s+(?:pg_catalog\.)?b?trim\s*\(", txt) and "does not exist" in txt:
        return "invalid_datatype"
    if "column" in txt and "does not exist" in txt:
        if any(fn.lower() in txt for fn in _SQL_FUNCS):
            return "expression_as_column"
        return "undefined_column"
    if "relation" in txt and "does not exist" in txt:
        return "undefined_table"
    if "syntax error" in txt or "syntaxerror" in txt:
        return "syntax_error"
    if "join" in txt or "ambiguous" in txt:
        return "invalid_join"
    if "timeout" in txt or "canceling statement" in txt:
        return "timeout"
    if any(tok in txt for tok in ("could not connect", "connection refused", "connection reset", "operationalerror", "server closed the connection")):
        return "db_unavailable"
    if "invalid input syntax" in txt or "cannot cast" in txt:
        return "invalid_datatype"
    if "extract" in txt and "does not exist" in txt:
        return "invalid_date_extract"
    if "groupingerror" in txt or "must appear in the group by" in txt or "group by clause" in txt:
        return "grouping_error"
    if "invalid reference to from-clause" in txt or "perhaps you meant to reference the table alias" in txt:
        return "alias_mismatch"
    if "duplicatealias" in txt or "specified more than once" in txt:
        return "duplicate_alias"
    return "generic_sql_error"


def _parse_plan_field(raw: Dict[str, Any]) -> Optional[PlanField]:
    if not isinstance(raw, dict):
        return None
    ftype = str(raw.get("type") or "column").lower()
    if ftype == "expression":
        expr = str(raw.get("expression") or "").strip()
        if not expr:
            return None
        return PlanField(
            type="expression",
            expression=expr,
            alias=str(raw.get("alias") or ""),
            purpose=str(raw.get("purpose") or ""),
        )
    tbl = str(raw.get("table") or "").strip()
    col = str(raw.get("column") or "").strip()
    if tbl and col and has_column(tbl, col):
        return PlanField(
            type="column",
            table=resolve_table_name(tbl) or tbl,
            column=col,
            alias=str(raw.get("alias") or ""),
            purpose=str(raw.get("purpose") or ""),
        )
    return None


def _parse_plan_filter(raw: Dict[str, Any]) -> Optional[PlanFilter]:
    if not isinstance(raw, dict):
        return None
    ftype = str(raw.get("type") or "column").lower()
    op = str(raw.get("operator") or "=").strip()
    val = raw.get("value")
    alias_ref = str(raw.get("alias_ref") or raw.get("field") or "")

    if ftype == "expression":
        expr = str(raw.get("expression") or "").strip()
        if not expr:
            return None
        return PlanFilter(type="expression", expression=expr, operator=op, value=val, alias_ref=alias_ref)

    tbl = str(raw.get("table") or "").strip()
    col = str(raw.get("column") or "").strip()
    if tbl and col and has_column(tbl, col):
        return PlanFilter(
            type="column",
            table=resolve_table_name(tbl) or tbl,
            column=col,
            operator=op,
            value=val,
            alias_ref=alias_ref,
        )
    return None


def build_structured_query_plan(
    question: str,
    *,
    tables: List[str],
    columns: List[str],
    joins: List[Dict[str, Any]],
    relationships: List[str],
    semantic_requirements: Dict[str, Any],
) -> StructuredQueryPlan:
    """AI builds a machine-readable query plan before SQL generation."""
    reg = get_schema_registry()
    detail = reg.column_detail_for_selection(tables)
    col_block = "\n".join(f"- {c}" for c in columns)

    try:
        raw, provider = analyze_json(
            "You build a STRUCTURED QUERY PLAN. JSON only. Do NOT output SQL. "
        "Separate physical columns (type=column) from SQL expressions (type=expression). "
        "NEVER put function calls like SUBSTRING/EXTRACT/TRIM inside the column field.",
        (
            f"Question: {question}\n"
            f"Semantic requirements: {json.dumps(semantic_requirements)}\n"
            f"Verified tables: {tables}\n"
            f"Verified columns: {col_block}\n"
            f"Relationships: {relationships}\n\n"
            f"{detail}\n\n"
            "Return JSON: {\n"
            '  "select": [{"type":"column","table":"","column":"","alias":"","purpose":""}, '
            '{"type":"expression","expression":"SUBSTRING(...)","alias":"year","purpose":""}],\n'
            '  "filters": [{"type":"column","table":"","column":"","operator":"<","value":0}, '
            '{"type":"expression","expression":"EXTRACT(YEAR FROM ...) = 2000"}],\n'
            '  "transformations": [{"type":"extract_year","source_table":"","source_column":"","alias":"year"}],\n'
            '  "group_by": [], "order_by": [{"field":"netwr","direction":"DESC"}], "limit": null\n'
            "}\n"
            "Rules:\n"
            "- type=column: table+column must be verified physical columns only.\n"
            "- type=expression: put full SQL expression in expression field; never in column.\n"
            "- For year filters on YYYYMMDD text dates use extract_year transformation or expression SUBSTRING(TRIM(CAST(table.col AS TEXT)),1,4).\n"
            "- NEVER use EXTRACT(YEAR FROM fkdat) — SAP date columns are TEXT (YYYYMMDD).\n"
            "- For 'show/list negative sales' return row-level rows (no SUM) with netwr < 0 filter.\n"
            "- For negative sales: filter measure column with operator '<' and value 0.\n"
            "- Include all columns needed to answer the question in select.\n"
            ),
        )
    except Exception as exc:
        # Semantic defaults and the validated SQL templates below remain the
        # authority when plan generation is unavailable. An empty model plan
        # is safe: it contains no guessed tables, columns, or predicates.
        raw = {}
        provider = "local_semantic_fallback"
        logger.warning(
            "[structured_sql] plan model unavailable; using semantic defaults (%s)",
            type(exc).__name__,
        )
    logger.info("[structured_sql] QUERY_PLAN provider=%s keys=%s", provider, list(raw.keys())[:12])

    plan = StructuredQueryPlan(
        question=question,
        tables=[resolve_table_name(t) or t for t in tables],
        joins=list(joins),
        semantic_requirements=dict(semantic_requirements or {}),
    )

    for item in raw.get("select") or []:
        pf = _parse_plan_field(item if isinstance(item, dict) else {})
        if pf:
            plan.select.append(pf)

    for item in raw.get("filters") or []:
        flt = _parse_plan_filter(item if isinstance(item, dict) else {})
        if flt:
            plan.filters.append(flt)

    for item in raw.get("group_by") or []:
        pf = _parse_plan_field(item if isinstance(item, dict) else {})
        if pf:
            plan.group_by.append(pf)

    if isinstance(raw.get("order_by"), list):
        plan.order_by = [o for o in raw["order_by"] if isinstance(o, dict)]

    lim = raw.get("limit")
    if isinstance(lim, int) and lim > 0:
        plan.limit = min(lim, 500)
    elif isinstance(lim, str) and lim.isdigit():
        plan.limit = min(int(lim), 500)

    if isinstance(raw.get("transformations"), list):
        plan.transformations = [t for t in raw["transformations"] if isinstance(t, dict)]

    # Apply extract_year transformations deterministically from plan metadata
    _apply_transformations(plan)
    _ensure_baseline_columns(plan, semantic_requirements)
    _apply_semantic_defaults(plan, semantic_requirements)
    _normalize_plan_expressions(plan)

    return plan


def _ensure_baseline_columns(plan: StructuredQueryPlan, semantic: Dict[str, Any]) -> None:
    """Ensure measure/date columns exist in SELECT for filter-style questions."""
    condition = semantic.get("condition") if isinstance(semantic.get("condition"), dict) else {}
    tf = semantic.get("time_filter")
    measure = semantic.get("measure") if isinstance(semantic.get("measure"), dict) else {"concept": "sales"}

    if condition or tf:
        mcol = _find_measure_column(plan, measure)
        has_aggregate = any(
            pf.type == "expression" and re.search(r"\b(SUM|COUNT|AVG|MAX|MIN)\s*\(", pf.expression or "", re.I)
            for pf in plan.select
        )
        if mcol and not has_aggregate and not any(
            pf.type == "column" and pf.table == mcol[0] and pf.column == mcol[1] for pf in plan.select
        ):
            plan.select.append(
                PlanField(type="column", table=mcol[0], column=mcol[1], purpose="measure")
            )
        dcol = _find_date_column(plan)
        if dcol and not _needs_aggregation(plan) and not any(
            pf.type == "column" and pf.table == dcol[0] and pf.column == dcol[1] for pf in plan.select
        ):
            plan.select.append(
                PlanField(type="column", table=dcol[0], column=dcol[1], purpose="date")
            )
        if not plan.select:
            if mcol:
                plan.select.append(PlanField(type="column", table=mcol[0], column=mcol[1]))
            if dcol:
                plan.select.append(PlanField(type="column", table=dcol[0], column=dcol[1]))


def _apply_transformations(plan: StructuredQueryPlan) -> None:
    for tr in plan.transformations:
        if not isinstance(tr, dict):
            continue
        ttype = str(tr.get("type") or "").lower()
        if ttype != "extract_year":
            continue
        tbl = str(tr.get("source_table") or tr.get("table") or "").strip()
        col = str(tr.get("source_column") or tr.get("column") or "").strip()
        alias = str(tr.get("alias") or "year")
        if not tbl or not col or not has_column(tbl, col):
            continue
        expr = year_filter_expression(tbl, col)
        plan.select.append(PlanField(type="expression", expression=expr, alias=alias, purpose="year"))
        year_val = _year_from_semantic(plan.semantic_requirements)
        if year_val is not None:
            plan.filters.append(
                PlanFilter(
                    type="expression",
                    expression=f"{expr} = '{year_val}'",
                    operator="=",
                    value=year_val,
                    alias_ref=alias,
                )
            )


def _year_from_semantic(semantic: Dict[str, Any]) -> Optional[str]:
    tf = semantic.get("time_filter")
    if isinstance(tf, dict):
        v = tf.get("value")
        if v is not None and re.fullmatch(r"(?:19|20)\d{2}", str(v)):
            return str(v)
    for f in semantic.get("filters") or []:
        if isinstance(f, dict) and str(f.get("concept") or "").lower() in {"year", "time"}:
            return str(f.get("value")) if f.get("value") is not None else None
    filters = semantic.get("filters")
    if isinstance(filters, dict):
        years = filters.get("years") or filters.get("year")
        if isinstance(years, list) and years:
            return str(years[0])
        if years:
            return str(years)
    return None


def _period_year_value(period_side: Any) -> Optional[str]:
    if isinstance(period_side, dict):
        if period_side.get("year"):
            return str(period_side["year"])
        if period_side.get("start") and re.fullmatch(r"\d{4}", str(period_side["start"])[:4]):
            return str(period_side["start"])[:4]
        return None
    if period_side is not None and re.fullmatch(r"\d{4}", str(period_side)):
        return str(period_side)
    return None


def _apply_period_compare_fields(plan: StructuredQueryPlan, semantic: Dict[str, Any]) -> None:
    """Rewrite the plan select list into period_a / period_b / change expressions."""
    period = plan.period_compare or (
        semantic.get("period_compare") if isinstance(semantic.get("period_compare"), dict) else None
    )
    if not isinstance(period, dict):
        return
    plan.period_compare = dict(period)
    y_a = _period_year_value(period.get("base_period"))
    y_b = _period_year_value(period.get("comparison_period"))
    if not y_a or not y_b:
        # Relative YoY without concrete years: leave markers for repair / later resolution
        plan.semantic_requirements.setdefault("period_compare", period)
        return

    date_col = _find_date_column(plan)
    measure_col = _find_measure_column(plan, semantic.get("measure") if isinstance(semantic.get("measure"), dict) else {})
    if not date_col or not measure_col:
        return

    year_expr = year_filter_expression(date_col[0], date_col[1])
    amt = numeric_cast_expr(measure_col[0], measure_col[1])
    period_a = f"SUM(CASE WHEN {year_expr} = '{y_a}' THEN {amt} ELSE 0 END)"
    period_b = f"SUM(CASE WHEN {year_expr} = '{y_b}' THEN {amt} ELSE 0 END)"
    calc = str(period.get("calculation") or "difference").lower()
    change = f"({period_b} - {period_a})"
    change_alias = "change"
    change_fields = [
        PlanField(type="expression", expression=period_a, alias="period_a", purpose="measure"),
        PlanField(type="expression", expression=period_b, alias="period_b", purpose="measure"),
    ]
    change_fields.append(PlanField(type="expression", expression=change, alias="change", purpose="measure"))
    if calc in {"both", "absolute_and_percent", "absolute_and_percentage_change"}:
        pct_change = (
            f"CASE WHEN {period_a} <> 0 "
            f"THEN (({period_b} - {period_a}) / NULLIF({period_a}, 0)) * 100 END"
        )
        change_fields.append(
            PlanField(type="expression", expression=pct_change, alias="pct_change", purpose="measure")
        )
        change_alias = "pct_change"
    elif "percent" in calc or calc == "percentage_change":
        change = (
            f"CASE WHEN {period_a} <> 0 "
            f"THEN (({period_b} - {period_a}) / NULLIF({period_a}, 0)) * 100 END"
        )
        change_alias = "pct_change"
        change_fields = [
            PlanField(type="expression", expression=period_a, alias="period_a", purpose="measure"),
            PlanField(type="expression", expression=period_b, alias="period_b", purpose="measure"),
            PlanField(type="expression", expression=change, alias=change_alias, purpose="measure"),
        ]

    # Keep dimension columns; replace measure aggregates with period compare fields.
    kept: List[PlanField] = []
    from .sql_structure import expressions_equivalent

    for pf in plan.select:
        is_measure = (
            pf.purpose == "measure"
            or (pf.type == "column" and (pf.column or "").lower() in {"netwr", "dmbtr", "wrbtr", "fkimg"})
            or (pf.type == "expression" and re.search(r"\b(SUM|AVG)\s*\(", pf.expression or "", re.I))
        )
        is_year = (
            (pf.alias or "").lower() == "year" or (pf.purpose or "").lower() == "year"
            or pf.type == "expression" and expressions_equivalent(pf.expression, year_expr)
        )
        if is_measure or is_year:
            continue
        kept.append(pf)
    plan.select = kept + change_fields
    plan.group_by = [
        field for field in plan.group_by
        if not (field.type == "expression" and expressions_equivalent(field.expression, year_expr))
    ]

    condition = str(period.get("condition") or period.get("op") or "").lower()
    if condition in {"increased", "growth", "increase"}:
        already = any("__HAVING__" in (f.expression or "") for f in plan.filters if f.type == "expression")
        if not already:
            # PostgreSQL cannot reference SELECT aliases in HAVING — use full expression.
            plan.filters.append(
                PlanFilter(
                    type="expression",
                    expression=f"__HAVING__ ({change}) > 0",
                    operator=">",
                    value=0,
                    alias_ref=change_alias,
                )
            )
    elif condition in {"decreased", "decline", "decrease"}:
        already = any("__HAVING__" in (f.expression or "") for f in plan.filters if f.type == "expression")
        if not already:
            plan.filters.append(
                PlanFilter(
                    type="expression",
                    expression=f"__HAVING__ ({change}) < 0",
                    operator="<",
                    value=0,
                    alias_ref=change_alias,
                )
            )

    # A single-period model filter must not suppress the comparison period.
    # Rewrite only this date's year restrictions, preserving all other filters.
    from .sql_structure import widen_year_predicate

    for flt in plan.filters:
        if flt.type == "expression" and flt.expression and not flt.expression.startswith("__HAVING__"):
            flt.expression = widen_year_predicate(flt.expression, year_expr, [y_a, y_b])

    # Scope years in WHERE so indexes / scanners stay bounded
    year_scope = f"{year_expr} IN ('{y_a}', '{y_b}')"
    if not any(year_scope in (f.expression or "") for f in plan.filters):
        plan.filters.append(PlanFilter(type="expression", expression=year_scope, operator="IN", value=None))

    ranking = plan.ranking or semantic.get("ranking")
    if isinstance(ranking, dict) and not condition:
        # A base-period sales ranking is different from a ranking of changes.
        metric = str(ranking.get("metric") or ranking.get("measure") or "").lower()
        sort_field = change_alias if any(term in metric for term in ("change", "growth", "difference")) else "period_a"
        plan.order_by = [{"field": sort_field, "direction": str(ranking.get("direction") or "DESC").upper()}]
    else:
        plan.order_by = [{"field": change_alias, "direction": "DESC" if "increas" in condition or condition == "growth" else "ASC"}]
    if not plan.limit:
        plan.limit = 50


def _apply_semantic_defaults(plan: StructuredQueryPlan, semantic: Dict[str, Any]) -> None:
    """Fill measure condition, grouping, ranking, and time filter from semantic requirements."""
    from .analytical_operations import classify_column_role

    measure = semantic.get("measure") if isinstance(semantic.get("measure"), dict) else {}
    condition = semantic.get("condition") if isinstance(semantic.get("condition"), dict) else {}
    agg = str(measure.get("aggregation") or "").upper()
    group_by_dims = [str(d).lower() for d in (semantic.get("group_by") or [])]
    dimensions = [str(d).lower() for d in (semantic.get("dimensions") or [])]
    ranking = semantic.get("ranking") if isinstance(semantic.get("ranking"), dict) else None
    if ranking:
        plan.ranking = dict(ranking)
    if isinstance(semantic.get("negation"), dict):
        plan.negation = dict(semantic["negation"])
    if isinstance(semantic.get("period_compare"), dict):
        plan.period_compare = dict(semantic["period_compare"])

    # Negative / below-zero measure filter
    for pf in plan.select:
        if pf.type == "column" and pf.column and not pf.purpose:
            pf.purpose = classify_column_role(pf.table, pf.column)

    # Negative / below-zero measure filter
    op = str(condition.get("measure_operator") or "").strip()
    val = condition.get("measure_value")
    if op and val is not None:
        measure_col = _find_measure_column(plan, measure)
        if measure_col:
            already = any(
                f.type == "column"
                and f.table == measure_col[0]
                and f.column == measure_col[1]
                and f.operator == op
                for f in plan.filters
            )
            if not already:
                plan.filters.append(
                    PlanFilter(
                        type="column",
                        table=measure_col[0],
                        column=measure_col[1],
                        operator=op,
                        value=val,
                    )
                )

    # Time filter year
    tf = semantic.get("time_filter")
    if isinstance(tf, dict) and tf.get("value") is not None and re.fullmatch(r"(?:19|20)\d{2}", str(tf["value"])):
        year = str(tf["value"])
        date_col = _find_date_column(plan)
        if date_col:
            expr = year_filter_expression(date_col[0], date_col[1])
            has_year_filter = any(
                year in (f.expression or "") for f in plan.filters if f.type == "expression"
            )
            if not has_year_filter:
                plan.filters.append(
                    PlanFilter(type="expression", expression=f"{expr} = '{year}'", operator="=", value=year)
                )
            if not any(s.alias == "year" for s in plan.select):
                plan.select.append(PlanField(type="expression", expression=expr, alias="year", purpose="year"))
    if isinstance(tf, dict) and tf.get("relative"):
        date_col = _find_date_column(plan)
        if date_col:
            # Prefer pre-resolved calendar bounds when present.
            if tf.get("start_yyyymmdd") and tf.get("end_yyyymmdd"):
                q = qualified_column(date_col[0], date_col[1])
                col_lower = (date_col[1] or "").lower()
                ctype = column_type(date_col[0], date_col[1])
                sap_text = col_lower in _SAP_TEXT_DATE_COLUMNS or ctype in {
                    "text", "varchar", "character varying", "char", "",
                }
                if sap_text:
                    pred = (
                        f"TRIM(CAST({q} AS TEXT)) >= '{tf['start_yyyymmdd']}' "
                        f"AND TRIM(CAST({q} AS TEXT)) < '{tf['end_yyyymmdd']}'"
                    )
                else:
                    pred = (
                        f"CAST({q} AS DATE) >= DATE '{tf.get('start')}' "
                        f"AND CAST({q} AS DATE) < DATE '{tf.get('end')}'"
                    )
            else:
                pred = relative_period_predicate(date_col[0], date_col[1], str(tf["relative"]))
            if not any(pred in (f.expression or "") for f in plan.filters):
                plan.filters.append(PlanFilter(type="expression", expression=pred, operator="", value=None))

    # First-class period comparison: dual CASE aggregates + change
    if isinstance(plan.period_compare, dict) or isinstance(semantic.get("period_compare"), dict):
        _apply_period_compare_fields(plan, semantic)

    date_col = _find_date_column(plan)
    if date_col and ("month" in group_by_dims or "month" in dimensions):
        expr = month_bucket_expression(date_col[0], date_col[1])
        if not any(s.alias == "month" or "month" in (s.purpose or "").lower() for s in plan.select):
            plan.select.insert(0, PlanField(type="expression", expression=expr, alias="month", purpose="dimension"))
        if not any(g.alias == "month" or (g.type == "expression" and g.expression == expr) for g in plan.group_by):
            plan.group_by.append(PlanField(type="expression", expression=expr, alias="month", purpose="dimension"))
    if date_col and not plan.period_compare and ("year" in group_by_dims or "year" in dimensions) and "month" not in group_by_dims:
        expr = year_filter_expression(date_col[0], date_col[1])
        if not any(s.alias == "year" for s in plan.select):
            plan.select.insert(0, PlanField(type="expression", expression=expr, alias="year", purpose="dimension"))
        if not any(g.alias == "year" for g in plan.group_by):
            plan.group_by.append(PlanField(type="expression", expression=expr, alias="year", purpose="dimension"))

    requested_aggregations = {str(a).upper() for a in (semantic.get("aggregations") or [agg])}
    if agg in {"SUM", "AVG", "MAX", "MIN"} and not any(
        pf.type == "expression" and re.search(rf"\b{agg}\s*\(", pf.expression or "", re.I)
        or pf.type == "column" and classify_column_role(pf.table, pf.column) == "measure"
        for pf in plan.select
    ):
        measure_col = _find_measure_column(plan, measure)
        if measure_col:
            plan.select.append(PlanField(type="column", table=measure_col[0], column=measure_col[1], purpose="measure"))
    if "COUNT" in requested_aggregations:
        has_count = any(
            pf.type == "expression" and "COUNT(" in (pf.expression or "").upper() for pf in plan.select
        )
        if not has_count:
            id_col = _find_identifier_column(plan)
            if id_col:
                expr = f'COUNT(DISTINCT TRIM(CAST({qualified_column(id_col[0], id_col[1])} AS TEXT)))'
            else:
                expr = "COUNT(*)"
            plan.select.append(PlanField(type="expression", expression=expr, alias="count", purpose="measure"))
        if not plan.order_by and plan.group_by:
            plan.order_by = [{"field": "month" if "month" in group_by_dims else "count", "direction": "ASC" if "month" in group_by_dims else "DESC"}]

    if ranking:
        if isinstance(ranking.get("limit"), int) and ranking["limit"] > 0:
            plan.limit = min(int(ranking["limit"]), 500)
        direction = str(ranking.get("direction") or "DESC").upper()
        if not plan.order_by:
            alias = "count" if agg == "COUNT" else "netwr_total"
            for pf in plan.select:
                if pf.purpose == "measure" or (pf.alias and "total" in pf.alias.lower()):
                    alias = pf.alias or alias
                    break
            plan.order_by = [{"field": alias, "direction": direction}]

    if not plan.limit and not _needs_aggregation(plan) and not _is_filter_list_question(semantic, plan.question):
        plan.limit = 200
    elif not plan.limit and _is_filter_list_question(semantic, plan.question):
        plan.limit = 200


def _find_identifier_column(plan: StructuredQueryPlan) -> Optional[Tuple[str, str]]:
    from .adaptive_analyst.database_metadata import _column_meanings

    requested = set(re.findall(r"[a-z]+", (plan.question or "").lower()))
    subjects = requested & {"billing", "document", "documents", "invoice", "invoices", "order", "orders", "customer", "customers", "material", "materials", "vendor", "vendors"}
    subjects = {word.rstrip("s") for word in subjects}
    candidates = []
    for table in plan.tables:
        for column, meaning in _column_meanings(table).items():
            if not has_column(table, column):
                continue
            terms = set(re.findall(r"[a-z]+", meaning))
            if not terms & {"number", "identifier", "id"}:
                continue
            overlap = subjects & terms
            if overlap:
                candidates.append((len(overlap), -len(terms), table, column))
    if candidates:
        _, _, table, column = max(candidates)
        return resolve_table_name(table) or table, column
    id_names = {"vbeln", "belnr", "ebeln", "kunnr", "matnr"}
    for pf in plan.select:
        if pf.type == "column" and pf.column.lower() in id_names:
            return pf.table, pf.column
    for tbl in plan.tables:
        for c in column_names(tbl):
            if c.lower() in id_names:
                return resolve_table_name(tbl) or tbl, c
    return None


def _find_measure_column(plan: StructuredQueryPlan, measure: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    concept = str(measure.get("concept") or "sales").lower()
    for pf in plan.select:
        if pf.type == "column" and pf.table and pf.column:
            blob = f"{pf.column} {pf.purpose}".lower()
            if concept in blob or pf.column.lower() in {"netwr", "dmbtr", "wrbtr", "fkimg"}:
                return pf.table, pf.column
    for col_ref in plan.tables:
        for c in column_names(col_ref):
            if c.lower() in {"netwr", "dmbtr", "wrbtr"} and concept in {"sales", "revenue", "amount"}:
                return resolve_table_name(col_ref) or col_ref, c
    return None


def _find_date_column(plan: StructuredQueryPlan) -> Optional[Tuple[str, str]]:
    tf = (plan.semantic_requirements or {}).get("time_filter") or {}
    if tf.get("resolved_from_data") is True:
        table, column = str(tf.get("date_table") or ""), str(tf.get("date_column") or "")
        if table and column and has_column(table, column):
            return table, column
    date_names = {"fkdat", "audat", "bedat", "budat", "erdat", "bldat", "wadat"}
    for pf in plan.select:
        if pf.type == "column" and pf.column.lower() in date_names:
            return pf.table, pf.column
    for tbl in plan.tables:
        for c in column_names(tbl):
            if c.lower() in date_names:
                return resolve_table_name(tbl) or tbl, c
    return None


def validate_query_plan(plan: StructuredQueryPlan) -> List[str]:
    errors: List[str] = []
    for tbl in plan.tables:
        if not has_table(tbl):
            errors.append(f"plan table not in schema: {tbl}")

    for pf in plan.select + plan.group_by:
        if pf.type == "column":
            if not pf.table or not pf.column:
                errors.append("column field missing table/column")
            elif not has_column(pf.table, pf.column):
                errors.append(f"unknown column {pf.table}.{pf.column}")
        elif pf.type == "expression":
            if not pf.expression.strip():
                errors.append("empty expression in select")
            errors.extend(_validate_expression_refs(pf.expression, plan.tables))

    for flt in plan.filters:
        if flt.type == "column":
            if not flt.table or not flt.column:
                errors.append("filter missing table/column")
            elif not has_column(flt.table, flt.column):
                errors.append(f"filter unknown column {flt.table}.{flt.column}")
        elif flt.type == "expression":
            if not flt.expression.strip():
                errors.append("empty filter expression")
            errors.extend(_validate_expression_refs(flt.expression, plan.tables))

    semantic = plan.semantic_requirements or {}
    measure = semantic.get("measure") if isinstance(semantic.get("measure"), dict) else {}
    concept = str(measure.get("concept") or "").lower()
    agg = str(measure.get("aggregation") or "").upper()
    ranking = semantic.get("ranking")
    group_by_dims = [str(d).lower() for d in (semantic.get("group_by") or [])]
    monetary = any(k in concept for k in ("sales", "revenue", "amount", "billing", "quantity"))
    if (ranking or agg == "SUM") and monetary:
        from .analytical_operations import table_has_measure_columns, table_is_master

        if plan.tables and all(table_is_master(t) for t in plan.tables if has_table(t)):
            errors.append("measure source missing: selected tables are master data only")
        elif plan.tables and not any(
            table_has_measure_columns(t, concept or "sales") for t in plan.tables
        ):
            errors.append("measure source missing: no transactional amount/quantity column")
    if group_by_dims and agg in {"SUM", "COUNT", "AVG"} and not plan.group_by:
        errors.append("group_by required by analytical plan but missing from query plan")
    from .plan_satisfaction import _expression_time_grain

    for grain in ("year", "month", "quarter"):
        if grain in group_by_dims:
            if not any(
                pf.type == "expression" and _expression_time_grain(pf.expression) == grain
                for pf in plan.select
            ):
                errors.append(f"{grain} grouping missing from result projection")
            if not any(
                pf.type == "expression" and _expression_time_grain(pf.expression) == grain
                for pf in plan.group_by
            ):
                errors.append(f"{grain} grouping missing from query plan")

    return errors[:15]


def _validate_expression_refs(expr: str, allowed_tables: List[str]) -> List[str]:
    """Ensure expression references only verified table.column pairs."""
    errors: List[str] = []
    if re.search(r"\bSELECT\b", re.sub(r"'(?:''|[^'])*'", "", expr), re.I):
        errors.append("structured expressions cannot introduce nested query scopes; regenerate the query plan")
    allowed = {resolve_table_name(t) or t for t in allowed_tables}
    literal_free = re.sub(r"'(?:''|[^'])*'", "", expr)
    reference_pattern = r'"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\.\s*"?([A-Za-z_][A-Za-z0-9_]*)"?'
    for tbl, col in re.findall(reference_pattern, literal_free):
        if tbl.upper() not in {t.upper() for t in allowed}:
            errors.append(f"expression references unverified table {tbl}")
        elif not has_column(tbl, col):
            errors.append(f"expression references unknown column {tbl}.{col}")
    bare = re.sub(reference_pattern, "", literal_free)
    keywords = set(_SQL_FUNCS) | {
        "AS", "TEXT", "NUMERIC", "DECIMAL", "INTEGER", "INT", "BIGINT", "SMALLINT", "REAL", "DOUBLE", "PRECISION",
        "VARCHAR", "CHAR", "CHARACTER", "VARYING", "DATE", "TIMESTAMP", "TIMESTAMPTZ", "TIME", "ZONE", "WITHOUT",
        "DISTINCT", "FROM", "FOR", "IN", "IS", "NOT", "NULL", "AND", "OR", "LIKE", "ILIKE", "BETWEEN", "TRUE", "FALSE",
        "YEAR", "MONTH", "QUARTER", "DAY", "WEEK", "CURRENT_DATE", "CURRENT_TIMESTAMP", "INTERVAL", "OVER",
        "PARTITION", "BY", "ORDER", "ASC", "DESC", "NULLS", "FIRST", "LAST", "FILTER", "WHERE", "__HAVING__",
    }
    known_columns = {column.lower() for table in allowed for column in column_names(table)}
    for match in re.finditer(r'"([A-Za-z_][A-Za-z0-9_]*)"|\b([A-Za-z_][A-Za-z0-9_]*)\b', bare):
        token = match.group(1) or match.group(2)
        if token.upper() in keywords or re.match(r"\s*\(", bare[match.end():]):
            continue
        if token.lower() not in known_columns:
            errors.append(f"expression references unknown field {token}")
    return errors


def _render_field(pf: PlanField, *, numeric_measure: bool = False) -> str:
    if pf.type == "expression":
        base = pf.expression
    else:
        base = qualified_column(pf.table, pf.column)
        if numeric_measure and pf.column.lower() in {"netwr", "dmbtr", "wrbtr", "fkimg", "menge"}:
            base = numeric_cast_expr(pf.table, pf.column)
    if pf.alias:
        safe_alias = re.sub(r"[^A-Za-z0-9_]", "_", pf.alias)[:64]
        return f"{base} AS \"{safe_alias}\""
    return base


def _render_filter(flt: PlanFilter) -> str:
    if flt.type == "expression":
        return flt.expression
    lhs = qualified_column(flt.table, flt.column)
    if flt.column.lower() in {"netwr", "dmbtr", "wrbtr", "fkimg"}:
        lhs = numeric_cast_expr(flt.table, flt.column)
    op = flt.operator or "="
    val = flt.value
    if val is None:
        return f"{lhs} {op} NULL"
    if isinstance(val, (int, float)):
        return f"{lhs} {op} {val}"
    return f"{lhs} {op} '{val}'"


def _needs_aggregation(plan: StructuredQueryPlan) -> bool:
    from .sql_structure import has_group_aggregate

    # Projection semantics take precedence over a row-list classification.
    if any(pf.type == "expression" and has_group_aggregate(pf.expression) for pf in plan.select):
        return True
    if plan.period_compare or isinstance(plan.semantic_requirements.get("period_compare"), dict):
        return True
    if _is_filter_list_question(plan.semantic_requirements, plan.question):
        return False
    measure = plan.semantic_requirements.get("measure") if isinstance(plan.semantic_requirements.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or "").upper()
    if agg in {"SUM", "COUNT", "AVG", "MAX", "MIN"}:
        return True
    if isinstance(plan.semantic_requirements.get("ranking"), dict):
        return True
    if plan.period_compare or isinstance(plan.semantic_requirements.get("period_compare"), dict):
        return True
    if plan.group_by and not _is_filter_list_question(plan.semantic_requirements, plan.question):
        return True
    return False


def render_sql_from_plan(plan: StructuredQueryPlan) -> str:
    """Deterministic SQL renderer from validated structured plan."""
    if not plan.tables:
        return ""

    from .adaptive_query_repair import prune_plan_for_aggregation
    from .analytical_operations import find_measure_table

    prune_plan_for_aggregation(plan)

    measure = plan.semantic_requirements.get("measure") if isinstance(plan.semantic_requirements.get("measure"), dict) else {}
    concept = str(measure.get("concept") or "sales")
    primary = find_measure_table(plan.tables, concept) or (resolve_table_name(plan.tables[0]) or plan.tables[0])
    primary = resolve_table_name(primary) or primary
    aggregating = _needs_aggregation(plan)
    agg = str(measure.get("aggregation") or "").upper()

    select_parts: List[str] = []
    for pf in plan.select:
        if aggregating and agg != "COUNT" and pf.type == "column" and pf.column.lower() in {"netwr", "dmbtr", "wrbtr", "rmwwr", "fkimg", "wavwr"}:
            aggregate = agg if agg in {"SUM", "AVG", "MAX", "MIN"} else "SUM"
            expr = f"{aggregate}({numeric_cast_expr(pf.table, pf.column)})"
            alias = pf.alias or f"{pf.column.lower()}_total"
            select_parts.append(f'{expr} AS "{alias}"')
        else:
            select_parts.append(_render_field(pf))

    if not select_parts:
        select_parts = ["*"]

    sql = f"SELECT {', '.join(select_parts)}\nFROM \"{primary}\""
    joined_tables: Set[str] = {primary.upper()}

    for j in plan.joins:
        if not isinstance(j, dict):
            continue
        jtype = str(j.get("type") or "LEFT JOIN").upper()
        if "JOIN" not in jtype:
            jtype = f"LEFT {jtype}" if "LEFT" in jtype else f"INNER JOIN"
        lt = resolve_table_name(str(j.get("left_table") or primary)) or primary
        rt = resolve_table_name(str(j.get("right_table") or j.get("target_table") or "")) or ""
        if not rt or not has_table(rt):
            continue
        lc = str(j.get("left_column") or j.get("join_key") or "")
        rc = str(j.get("right_column") or lc or "")
        if not lc or not rc:
            continue

        new_tbl = rt
        anchor_tbl = lt
        anchor_col, new_col = lc, rc
        if new_tbl.upper() in joined_tables:
            if anchor_tbl.upper() in joined_tables:
                continue
            new_tbl, anchor_tbl = anchor_tbl, new_tbl
            anchor_col, new_col = rc, lc
        elif anchor_tbl.upper() not in joined_tables:
            anchor_tbl = primary
            anchor_col, new_col = rc, lc

        sql += (
            f"\n{jtype} \"{new_tbl}\" ON "
            f"LPAD(TRIM(CAST(\"{anchor_tbl}\".\"{anchor_col}\" AS TEXT)), 10, '0') = "
            f"LPAD(TRIM(CAST(\"{new_tbl}\".\"{new_col}\" AS TEXT)), 10, '0')"
        )
        joined_tables.add(new_tbl.upper())

    where_filters = []
    having_parts = []
    for f in plan.filters:
        if not (f.expression or (f.table and f.column)):
            continue
        expr = f.expression or ""
        if expr.startswith("__HAVING__"):
            having_parts.append(expr.replace("__HAVING__", "", 1).strip())
        else:
            where_filters.append(f)
    where_parts = [_render_filter(f) for f in where_filters]
    if where_parts:
        sql += "\nWHERE " + "\n  AND ".join(where_parts)

    if plan.group_by:
        gb = []
        for g in plan.group_by:
            if g.type == "expression":
                gb.append(g.expression)
            else:
                gb.append(qualified_column(g.table, g.column))
        sql += "\nGROUP BY " + ", ".join(gb)
    elif aggregating:
        dim_gb = [
            qualified_column(pf.table, pf.column)
            for pf in plan.select
            if pf.type == "column" and pf.column.lower() not in {"netwr", "dmbtr", "wrbtr", "rmwwr", "fkimg", "wavwr"}
        ]
        # Also group by non-aggregate expressions that aren't already period CASE sums
        for pf in plan.select:
            if pf.type == "expression" and pf.alias and not re.search(r"\b(SUM|COUNT|AVG|MAX|MIN)\s*\(", pf.expression or "", re.I):
                dim_gb.append(pf.expression)
        if dim_gb:
            sql += "\nGROUP BY " + ", ".join(dict.fromkeys(dim_gb))

    if having_parts:
        sql += "\nHAVING " + " AND ".join(having_parts)

    if plan.order_by:
        ob_parts = []
        for ob in plan.order_by:
            raw_order_field = ob.get("field") or ob.get("alias") or ob.get("column") or ""
            if isinstance(raw_order_field, dict):
                order_field = _parse_plan_field(raw_order_field)
                selected = next((
                    field for field in plan.select
                    if order_field and field.type == order_field.type
                    and (field.table, field.column, field.expression) == (order_field.table, order_field.column, order_field.expression)
                ), None)
                field_name = str(selected.alias if selected and selected.alias else order_field.column if order_field else "")
            else:
                field_name = str(raw_order_field)
            direction = str(ob.get("direction") or "ASC").upper()
            if field_name:
                ob_parts.append(f"\"{field_name}\" {direction}")
        if ob_parts:
            sql += "\nORDER BY " + ", ".join(ob_parts)

    ranking_now = plan.ranking if isinstance(plan.ranking, dict) else (
        plan.semantic_requirements.get("ranking")
        if isinstance(plan.semantic_requirements.get("ranking"), dict)
        else {}
    )
    if plan.limit and not (ranking_now or {}).get("partition_by"):
        sql += f"\nLIMIT {int(plan.limit)}"

    sql = repair_quoted_expressions_as_columns(sql.strip())
    sql = _wrap_partitioned_ranking(sql, plan)
    sql = _apply_anti_join_nulls(sql, plan)
    return sql


def _wrap_partitioned_ranking(sql: str, plan: StructuredQueryPlan) -> str:
    if plan.period_compare or isinstance(
        (plan.semantic_requirements or {}).get("period_compare"), dict
    ):
        return sql
    ranking = plan.ranking or (
        plan.semantic_requirements.get("ranking")
        if isinstance(plan.semantic_requirements.get("ranking"), dict)
        else None
    )
    if not isinstance(ranking, dict):
        return sql
    parts = ranking.get("partition_by") or []
    if not parts:
        return sql
    # Already partitioned — do not double-wrap (causes invalid nested ROW_NUMBER / stray columns).
    if re.search(r"\bROW_NUMBER\s*\(\s*\)\s*OVER\s*\(\s*PARTITION\s+BY", sql or "", re.I):
        if re.search(r"\brank_in_partition\b", sql or "", re.I) or re.search(
            r"WHERE\s+\w+\s*<=\s*\d+", sql or "", re.I
        ):
            return sql
        # Has PARTITION BY window but no outer filter — wrap once with filter only if needed
        if "rank_in_partition" not in (sql or "").lower():
            limit = int(ranking.get("limit") or 5)
            return (
                f"SELECT * FROM (\n{sql}\n) ranked WHERE rank_in_partition <= {limit}"
                if "rank_in_partition" in sql.lower()
                else sql
            )
        return sql
    limit = int(ranking.get("limit") or 5)
    direction = str(ranking.get("direction") or "DESC").upper()
    order_field = ""
    if plan.order_by:
        order_field = str(plan.order_by[0].get("field") or "")
    if not order_field:
        for pf in plan.select:
            if pf.purpose == "measure" or (pf.alias and "total" in (pf.alias or "").lower()):
                order_field = pf.alias or pf.column
                break
    partition_field = str(parts[0])
    for pf in plan.select:
        if partition_field in (pf.alias or pf.column or pf.purpose or "").lower():
            partition_field = pf.alias or pf.column
            break
    # Map common dimension names to selected aliases
    if partition_field.lower() in {"country", "plant", "werks", "industry", "customer"}:
        want = {"country": ("country", "land1"), "plant": ("plant", "werks"), "werks": ("plant", "werks"),
                "industry": ("industry", "brtxt", "brsch"), "customer": ("customer", "customer_id", "kunnr")}
        aliases = want.get(partition_field.lower(), (partition_field.lower(),))
        for pf in plan.select:
            alias = (pf.alias or pf.column or "").lower()
            if alias in aliases:
                partition_field = pf.alias or pf.column
                break
    # Prefer measure/order field over partition dimension for ORDER BY
    if order_field and partition_field and order_field.lower() == str(partition_field).lower():
        order_field = ""
        for pf in plan.select:
            if pf.purpose == "measure" or (pf.alias and any(
                t in (pf.alias or "").lower() for t in ("total", "sales", "quantity", "amount", "count", "value")
            )):
                order_field = pf.alias or pf.column
                break
    if not order_field or not partition_field:
        return sql
    # Refuse to wrap when order field still equals partition (would invent nonsense ranking)
    if str(order_field).lower() == str(partition_field).lower():
        return sql
    inner = sql
    if re.search(r"\bLIMIT\b", inner, re.I):
        inner = re.sub(r"\s+LIMIT\s+\d+\s*$", "", inner, flags=re.I)
    return (
        f"SELECT * FROM (\n"
        f"  SELECT inner_q.*, ROW_NUMBER() OVER ("
        f"PARTITION BY \"{partition_field}\" ORDER BY \"{order_field}\" {direction}"
        f") AS rank_in_partition\n"
        f"  FROM (\n{inner}\n  ) inner_q\n"
        f") ranked WHERE rank_in_partition <= {limit}"
    )


def _apply_anti_join_nulls(sql: str, plan: StructuredQueryPlan) -> str:
    """If the plan requests negation, keep LEFT JOIN semantics and require the fact key IS NULL."""
    from .semantic_requirements import required_semantics

    negation = required_semantics(plan.question, plan.semantic_requirements).get("negation")
    if not isinstance(negation, dict) or not negation.get("forbidden"):
        return sql
    if re.search(r"\bIS\s+NULL\b", sql, re.I):
        return sql
    if "LEFT JOIN" not in sql.upper():
        sql = re.sub(r"\bINNER JOIN\b", "LEFT JOIN", sql, flags=re.I)
    # Add IS NULL on the last joined table's first equality column if WHERE exists.
    m = list(re.finditer(r'LEFT JOIN\s+"([^"]+)"\s+ON\s+(.+?)(?=\n(?:LEFT JOIN|INNER JOIN|WHERE|GROUP BY|ORDER BY|LIMIT)|$)', sql, re.I | re.S))
    if not m:
        return sql
    last = m[-1]
    tbl = last.group(1)
    on_clause = last.group(2)
    col_m = re.search(r'"' + re.escape(tbl) + r'"\."([^"]+)"', on_clause)
    if not col_m:
        return sql
    null_pred = f'"{tbl}"."{col_m.group(1)}" IS NULL'
    if re.search(r"\bWHERE\b", sql, re.I):
        sql = re.sub(r"\bWHERE\b", f"WHERE {null_pred} AND", sql, count=1, flags=re.I)
    else:
        sql = re.sub(r"\n(GROUP BY|ORDER BY|LIMIT)\b", f"\nWHERE {null_pred}\n\\1", sql, count=1, flags=re.I)
    return sql


def repair_absurd_question_literal_filters(sql: str, question: str) -> str:
    """
    Remove WHERE clauses that treat question phrasing as data literals
    (e.g. name1 ILIKE '%names only%' from 'Show customer names only').
    """
    if not sql or not question:
        return sql
    q = (question or "").lower()
    if not re.search(r"\b(show|list|display|give me)\b", q):
        return sql
    out = sql
    for m in list(re.finditer(r"\b(?:AND\s+)?(\w+\.)?\w+\s+(?:I?LIKE)\s+'([^']+)'", sql, re.I)):
        literal = (m.group(2) or "").lower().strip(" %")
        if not literal:
            continue
        # Drop LIKE/ILIKE filters whose literal echoes command words from the question
        words = [w for w in re.findall(r"[a-z]{3,}", literal) if w not in {"and", "the", "for"}]
        if words and all(w in q for w in words):
            out = out.replace(m.group(0), "", 1)
    out = re.sub(r"\bWHERE\s+(AND|OR)\s+", "WHERE ", out, flags=re.I)
    out = re.sub(r"\bWHERE\s+(GROUP|ORDER|LIMIT)\b", r"\1", out, flags=re.I)
    if re.search(r"\bWHERE\s*$", out, re.I):
        out = re.sub(r"\bWHERE\s*$", "", out, flags=re.I)
    return out.strip()


def build_master_list_sql(question: str, tables: List[str]) -> Optional[str]:
    """Deterministic row list for 'show customer names only' style questions."""
    q = (question or "").lower()
    if not re.search(r"\b(show|list|display|give me)\b", q):
        return None
    if re.search(r"\b(top|highest|lowest|best|worst|most|sum|total)\b", q):
        return None

    limit = 200
    m = re.search(r"\b(?:top|limit)\s+(\d+)\b", q)
    if m:
        limit = min(int(m.group(1)), 500)

    if re.search(r"\bcustomer\s+names?\b", q) and has_table("KNA1") and has_column("KNA1", "name1"):
        return (
            f'SELECT TRIM("KNA1"."name1") AS "customer_name" '
            f'FROM "KNA1" '
            f'WHERE NULLIF(TRIM("KNA1"."name1"), \'\') IS NOT NULL '
            f'ORDER BY "customer_name" ASC '
            f"LIMIT {limit}"
        )
    if re.search(r"\bmaterial\s+names?\b", q) and has_table("MAKT") and has_column("MAKT", "maktx"):
        return (
            f'SELECT TRIM("MAKT"."matnr") AS "material_id", TRIM("MAKT"."maktx") AS "material_name" '
            f'FROM "MAKT" '
            f'WHERE NULLIF(TRIM("MAKT"."maktx"), \'\') IS NOT NULL '
            f'ORDER BY "material_name" ASC '
            f"LIMIT {limit}"
        )
    return None


def repair_bare_year_alias_in_case(sql: str) -> str:
    """Fix CASE WHEN year = 'YYYY' when year is only a SELECT alias (invalid in CASE)."""
    if not sql or not re.search(r"\bCASE\s+WHEN\s+year\s*=", sql, re.I):
        return sql
    # Prefer fkdat year expression when VBRK is present
    if re.search(r'\b"?VBRK"?\b', sql, re.I) and re.search(r"\bfkdat\b", sql, re.I):
        year_expr = "SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4)"
        return re.sub(r"\bCASE\s+WHEN\s+year\s*=", f"CASE WHEN {year_expr} =", sql, flags=re.I)
    if re.search(r'\b"?VBAK"?\b', sql, re.I) and re.search(r"\baudat\b", sql, re.I):
        year_expr = "SUBSTRING(TRIM(CAST(\"VBAK\".\"audat\" AS TEXT)), 1, 4)"
        return re.sub(r"\bCASE\s+WHEN\s+year\s*=", f"CASE WHEN {year_expr} =", sql, flags=re.I)
    return sql


def sanitize_generated_sql(sql: str, question: str = "") -> str:
    """Generic post-processing for any LLM-generated SQL."""
    from .sql_generation_sanitizers import (
        sanitize_netwr_sql,
        sanitize_sap_amount_columns_sql,
        sanitize_sap_amount_predicates_sql,
        sanitize_trim_type_safety_sql,
    )

    out = repair_quoted_expressions_as_columns(sql or "")
    out = repair_extract_on_text_dates(out)
    out = repair_bare_year_alias_in_case(out)
    out = repair_bare_time_grain_aliases(out)
    out = sanitize_sap_amount_columns_sql(out)
    out = sanitize_netwr_sql(out)
    out = sanitize_sap_amount_predicates_sql(out)
    if question:
        out = repair_absurd_question_literal_filters(out, question)
        from .adaptive_nl_sql_hardening import strip_customer_name_filter_from_country_query

        out = strip_customer_name_filter_from_country_query(out, question)
    from .analytical_sql_safety import canonicalize_text_joins

    # The four-stage planner validates candidates before the shared executor.
    # Bound language lookups here as well so valid repairs pass that boundary.
    return canonicalize_text_joins(sanitize_trim_type_safety_sql(out))


def repair_bare_time_grain_aliases(sql: str) -> str:
    """Rewrite illegal `year AS \"year\"` when GROUP BY already defines the year expression."""
    if not sql:
        return sql
    out = sql
    # SELECT ..., year AS "year" ... GROUP BY SUBSTRING(...erdat..., 1, 4)
    for grain, width in (("year", 4), ("month", 6)):
        gb = re.search(
            rf"GROUP\s+BY\s+(SUBSTRING\s*\(\s*TRIM\s*\(\s*CAST\s*\([^)]+\"(?:erdat|audat|fkdat|bedat|budat)\"[^)]*\)\s*\)\s*,\s*1\s*,\s*{width}\s*\))",
            out,
            re.I,
        )
        if not gb:
            continue
        expr = gb.group(1)
        out = re.sub(
            rf'(?i)(?<![.\w]){grain}\s+AS\s+"{grain}"',
            f'{expr} AS "{grain}"',
            out,
            count=1,
        )
        out = re.sub(
            rf'(?i)(?<![.\w]){grain}\s+AS\s+{grain}\b',
            f'{expr} AS "{grain}"',
            out,
            count=1,
        )
    return out
