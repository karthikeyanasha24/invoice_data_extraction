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
from typing import Any, Dict, List, Optional, Set, Tuple

from ..data_catalog.physical import column_names, has_column, has_table, resolve_table_name
from .adaptive_analyst.llm_provider import analyze_json
from .schema_intelligence_registry import get_schema_registry

logger = logging.getLogger("zodiac-api.structured_sql")

# SAP dates stored as YYYYMMDD text — never EXTRACT(YEAR FROM col) directly
_SAP_TEXT_DATE_COLUMNS = frozenset({
    "fkdat", "audat", "bedat", "budat", "erdat", "bldat", "wadat", "cpudt", "aedat",
    "wadat_ist", "lfdat", "bldat", "valdt",
})

_EXTRACT_YEAR_PATTERN = re.compile(
    r"EXTRACT\s*\(\s*YEAR\s+FROM\s+((?:\"[A-Za-z0-9_]+\"\.\"[A-Za-z0-9_]+\"|\"[A-Za-z0-9_]+\"\.[A-Za-z0-9_]+))\s*\)",
    re.I,
)

_SQL_FUNCS = (
    "SUBSTRING", "TRIM", "CAST", "EXTRACT", "COALESCE", "NULLIF", "LPAD", "RTRIM", "LTRIM",
    "UPPER", "LOWER", "SUM", "COUNT", "AVG", "MAX", "MIN", "DATE_PART", "TO_DATE", "TO_CHAR",
    "ROUND", "ABS", "GREATEST", "LEAST", "CASE", "WHEN", "THEN", "ELSE", "END",
)

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
    """Replace EXTRACT(YEAR FROM text_date_col) with SUBSTRING — fixes SAP FKDAT etc."""
    if not sql or "EXTRACT" not in sql.upper():
        return sql

    def repl(m: re.Match[str]) -> str:
        ref = m.group(1)
        parts = re.findall(r'"([A-Za-z0-9_]+)"', ref)
        if len(parts) >= 2:
            return year_filter_expression(parts[0], parts[1])
        bare = re.match(r'"([A-Za-z0-9_]+)"\.([A-Za-z0-9_]+)', ref, re.I)
        if bare:
            return year_filter_expression(bare.group(1), bare.group(2))
        return f"SUBSTRING(TRIM(CAST({ref} AS TEXT)), 1, 4)"

    return _EXTRACT_YEAR_PATTERN.sub(repl, sql)


def _normalize_plan_expressions(plan: StructuredQueryPlan) -> None:
    """Normalize date expressions and remove duplicate select/filter entries."""
    for pf in plan.select + plan.group_by:
        if pf.type == "expression" and pf.expression:
            pf.expression = repair_extract_on_text_dates(pf.expression)
    for flt in plan.filters:
        if flt.type == "expression" and flt.expression:
            flt.expression = repair_extract_on_text_dates(flt.expression)

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
    """Detect show/list/filter row-level questions from semantics or natural language."""
    sem = semantic or {}
    condition = sem.get("condition") if isinstance(sem.get("condition"), dict) else {}
    ranking = sem.get("ranking")
    measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    agg = str(measure.get("aggregation") or "").lower()
    if isinstance(condition, dict) and condition.get("measure_operator") is not None:
        if not isinstance(ranking, dict) and agg in {"", "none", "null"}:
            return True

    q = (question or "").lower()
    if re.search(r"\b(top|highest|lowest|best|worst|rank|most)\b", q):
        return False
    if re.search(r"\b(total|sum of|aggregate|combined)\b", q):
        return False
    if re.search(r"\b(show|list|display|give me|get me|find|which)\b", q):
        if re.search(r"\b(negative|negatives|below zero|less than zero|loss.?making)\b", q):
            return True
        if re.search(r"\bnegative\w*\s+(sales|billing|invoice|amount|revenue)\b", q):
            return True
    if re.search(r"\bnegative\w*\s+(sales|billing|invoice|amount|revenue)\b", q):
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
    condition = sem.get("condition") if isinstance(sem.get("condition"), dict) else {}
    op = str(condition.get("measure_operator") or "<").strip()
    val = condition.get("measure_value", 0)
    if re.search(r"\bnegative\w*\b", (question or "").lower()) and val in (None, "", 0):
        op, val = "<", 0

    year: Optional[str] = None
    tf = sem.get("time_filter")
    if isinstance(tf, dict) and tf.get("value") is not None:
        year = str(tf["value"])
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
    want_line = any(w in q_lower for w in ("material", "line item", "item level", "product"))

    def pick_measure_date() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Prefer billing header (VBRK) for row-level billing filters unless line items requested."""
        mt, mc, dt, dc = None, None, None, None
        header_tbl = resolve_table_name("VBRK") if has_table("VBRK") else None
        if header_tbl and not want_line:
            if has_column(header_tbl, "netwr"):
                mt, mc = header_tbl, "netwr"
            if has_column(header_tbl, "fkdat"):
                dt, dc = header_tbl, "fkdat"
            if mt and dt:
                return mt, mc, dt, dc

        for t in search_tables:
            rt = resolve_table_name(t) or t
            for c in column_names(rt):
                cl = c.lower()
                if cl in {"netwr", "dmbtr", "wrbtr"} and mc is None:
                    mt, mc = rt, c
                if cl in _SAP_TEXT_DATE_COLUMNS and dc is None:
                    dt, dc = rt, c
        if header_tbl:
            if mc is None and has_column(header_tbl, "netwr"):
                mt, mc = header_tbl, "netwr"
            if dc is None and has_column(header_tbl, "fkdat"):
                dt, dc = header_tbl, "fkdat"
        return mt, mc, dt, dc

    measure_tbl, measure_col, date_tbl, date_col = pick_measure_date()
    if not measure_tbl or not measure_col:
        return None

    net_expr = numeric_cast_expr(measure_tbl, measure_col)
    where_parts = [f"{net_expr} {op} {val if isinstance(val, (int, float)) else 0}"]
    if year and date_tbl and date_col:
        year_expr = year_filter_expression(date_tbl, date_col)
        where_parts.append(f"{year_expr} = '{year}'")

    if want_line and "vbrp" in tables_lower and has_table("vbrp"):
        hdr = resolve_table_name("VBRK") or "VBRK"
        line = resolve_table_name("vbrp") or "vbrp"
        line_net = numeric_cast_expr(line, "netwr")
        line_where = [f"{line_net} {op} {val if isinstance(val, (int, float)) else 0}"]
        if year and has_column(hdr, "fkdat"):
            line_where.append(f"{year_filter_expression(hdr, 'fkdat')} = '{year}'")
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
    if not re.search(r"\b(highest|top|most|best|largest|biggest|lowest|worst)\b", q):
        return False
    if not re.search(r"\b(sales|revenue|billing|turnover)\b", q):
        return False
    dim_keywords = ("country", "customer", "industry", "sector", "product", "material", "region")
    dim_count = sum(1 for d in dim_keywords if d in q)
    if dim_count >= 2:
        return True
    sem = semantic or {}
    dims = sem.get("dimensions")
    if isinstance(dims, list) and len(dims) >= 2:
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
    Deterministic SQL for multi-dimensional sales rankings using VBRK → KNA1 → T016T.
    Avoids vbrp fan-out and bad LLM join plans.
    """
    if not detect_multidim_ranking_intent(question, semantic):
        return None
    if not has_table("VBRK") or not has_column("VBRK", "netwr"):
        return None

    q = (question or "").lower()
    if limit is None:
        limit = 1
        m = re.search(r"\btop\s+(\d+)", q)
        if m:
            limit = int(m.group(1))
        elif re.search(r"\b(highest|most|best|largest|biggest|lowest|worst)\b", q):
            limit = 1

    want_country = bool(re.search(r"\b(country|countries|nation)\b", q))
    want_customer = bool(re.search(r"\b(customer|customers|client|clients)\b", q))
    want_industry = bool(re.search(r"\b(industry|industries|sector|sectors)\b", q))
    if not any((want_country, want_customer, want_industry)):
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

    hdr = resolve_table_name("VBRK") or "VBRK"
    net = numeric_cast_expr(hdr, "netwr")
    sel: List[str] = []
    gb: List[str] = []

    if want_country and has_table("KNA1") and has_column("KNA1", "land1"):
        sel.append(f'TRIM("KNA1"."land1") AS "country"')
        gb.append('TRIM("KNA1"."land1")')
    if want_customer and has_table("KNA1"):
        if has_column("KNA1", "kunnr"):
            sel.append(f'TRIM("KNA1"."kunnr") AS "customer_id"')
            gb.append('TRIM("KNA1"."kunnr")')
        if has_column("KNA1", "name1"):
            sel.append(f'TRIM("KNA1"."name1") AS "customer_name"')
            gb.append('TRIM("KNA1"."name1")')
    if want_industry and has_table("KNA1") and has_table("T016T"):
        if has_column("T016T", "brtxt"):
            sel.append(f'TRIM("T016T"."brtxt") AS "industry"')
            gb.append('TRIM("T016T"."brtxt")')
        elif has_column("KNA1", "brsch"):
            sel.append(f'TRIM("KNA1"."brsch") AS "industry_code"')
            gb.append('TRIM("KNA1"."brsch")')

    if not sel:
        return None

    sel.append(f'SUM({net}) AS "total_sales"')

    sql = f"SELECT {', '.join(sel)}\nFROM \"{hdr}\""
    if has_table("KNA1") and has_column(hdr, "kunag") and has_column("KNA1", "kunnr"):
        sql += (
            f'\nLEFT JOIN "KNA1" ON '
            f"LPAD(TRIM(CAST(\"{hdr}\".\"kunag\" AS TEXT)), 10, '0') = "
            f"LPAD(TRIM(CAST(\"KNA1\".\"kunnr\" AS TEXT)), 10, '0')"
        )
    if want_industry and has_table("T016T") and has_table("KNA1") and has_column("KNA1", "brsch") and has_column("T016T", "brsch"):
        sql += (
            f'\nLEFT JOIN "T016T" ON '
            f"LPAD(TRIM(CAST(\"KNA1\".\"brsch\" AS TEXT)), 10, '0') = "
            f"LPAD(TRIM(CAST(\"T016T\".\"brsch\" AS TEXT)), 10, '0')"
        )

    where_parts: List[str] = []
    if want_customer and has_column(hdr, "kunag"):
        where_parts.append(f'NULLIF(TRIM(CAST("{hdr}"."kunag" AS TEXT)), \'\') IS NOT NULL')
    if where_parts:
        sql += f"\nWHERE {' AND '.join(where_parts)}"

    sql += f"\nGROUP BY {', '.join(gb)}"
    direction = "ASC" if re.search(r"\b(lowest|worst|smallest|minimum)\b", q) else "DESC"
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
    return "ASC" if _DESCENDING_EXCEPTIONS.search(question or "") else "DESC"


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
    """sales | quantity | invoice_count | purchase_value | vendor_invoice_value"""
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
    if not re.search(r"\b(top|bottom|highest|lowest|most|least|best|worst|largest|biggest|smallest|leading|rank|ranking|list)\b", q):
        return None

    dimension = detect_ranking_dimension(question, semantic)
    if not dimension:
        return None
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
    ranking = req.get("ranking") if isinstance(req.get("ranking"), dict) else None
    if ranking and ranking.get("partition_by"):
        return None  # partitioned Top-N owns this shape
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
    use_line = dimension == "material" or measure == "quantity"
    if use_line and not has_table("vbrp"):
        return None

    sel: List[str] = []
    gb: List[str] = []
    joins: List[str] = []
    where: List[str] = []

    if use_line:
        from_clause = f'FROM "{line}" p'
        joins.append(
            f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') '
            f'= LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')'
        )
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
            joins.append('LEFT JOIN "MAKT" m ON TRIM(p."matnr") = TRIM(m."matnr")')
            sel.append('TRIM(m."maktx") AS "material_name"')
            gb.append('TRIM(m."maktx")')
        where.append('NULLIF(TRIM(CAST(p."matnr" AS TEXT)), \'\') IS NOT NULL')
    else:
        return None

    if measure == "invoice_count":
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

    sql = f"SELECT {', '.join(sel)}\n{from_clause}"
    for j in joins:
        sql += f"\n{j}"
    if where:
        sql += "\nWHERE " + "\n  AND ".join(where)
    sql += f"\nGROUP BY {', '.join(gb)}"
    sql += f'\nORDER BY "{alias}" {direction} NULLS LAST'
    sql += f"\nLIMIT {max(1, min(int(limit), 500))}"
    return sql.strip()


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
    wants_month = bool(re.search(r"\b(month|monthly|per month|by month|each month)\b", q))
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


def build_period_compare_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generic period-change SQL from semantic period_compare (any year pair)."""
    from .semantic_requirements import required_semantics

    req = required_semantics(question, semantic)
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
    if not has_table("VBRK") or not has_column("VBRK", "netwr") or not has_column("VBRK", "fkdat"):
        return None

    hdr = resolve_table_name("VBRK") or "VBRK"
    net = f'CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), \'\') AS NUMERIC)'
    yexpr = 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4)'
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
        else:
            dims = ["customer"]

    sel: List[str] = []
    gb: List[str] = []
    joins: List[str]
    where: List[str]

    if "material" in dims and has_table("vbrp") and has_table("MAKT"):
        joins = [
            'FROM "vbrp" p',
            f'JOIN "{hdr}" k ON LPAD(TRIM(CAST(p."vbeln" AS TEXT)), 10, \'0\') = '
            f'LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')',
            'LEFT JOIN "MAKT" m ON LPAD(TRIM(CAST(p."matnr" AS TEXT)), 10, \'0\') = '
            'LPAD(TRIM(CAST(m."matnr" AS TEXT)), 10, \'0\')',
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
    period_a = f"SUM(CASE WHEN {yexpr} = '{y_a}' THEN {net} ELSE 0 END)"
    period_b = f"SUM(CASE WHEN {yexpr} = '{y_b}' THEN {net} ELSE 0 END)"
    change = f"({period_b} - {period_a})"
    sel.extend([
        f'{period_a} AS "period_a"',
        f'{period_b} AS "period_b"',
        f'{change} AS "change"',
    ])
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
    # "Largest decline" / "grew the most" → top-1 by |change| with matching sign.
    lim = 50
    if re.search(r"\b(largest|biggest|strongest|most)\b", ql) and re.search(
        r"\b(declin|decreas|growth|grew|increase)\b", ql
    ):
        lim = extract_ranking_limit(question, default=1)
    sql = (
        f"SELECT {', '.join(sel)}\n"
        + "\n".join(joins) + "\n"
        + "WHERE " + "\n  AND ".join(where) + "\n"
        + f"GROUP BY {', '.join(gb)}\n"
    )
    if having:
        sql += f"HAVING {having}\n"
    sql += f'ORDER BY "change" {order_dir}\nLIMIT {max(1, min(int(lim), 200))}'
    return sql


def build_partitioned_topn_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generic partitioned Top-N (e.g. top 5 customers in each country / plant)."""
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
            joins.append(
                'LEFT JOIN "MAKT" m ON LPAD(TRIM(CAST(p."matnr" AS TEXT)), 10, \'0\') = '
                'LPAD(TRIM(CAST(m."matnr" AS TEXT)), 10, \'0\')'
            )
            sel_parts.insert(2, 'TRIM(m."maktx") AS "material_name"')
            gb += ', TRIM(m."maktx")'
        inner = (
            f"SELECT {', '.join(sel_parts)}\n"
            + "\n".join(joins) + "\n"
            + "WHERE NULLIF(TRIM(CAST(p.\"werks\" AS TEXT)), '') IS NOT NULL\n"
            + f"  AND NULLIF(TRIM(CAST(p.\"matnr\" AS TEXT)), '') IS NOT NULL\n"
            + f"GROUP BY {gb}"
        )
        return (
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
            joins.append(
                'LEFT JOIN "MAKT" m ON LPAD(TRIM(CAST(p."matnr" AS TEXT)), 10, \'0\') = '
                'LPAD(TRIM(CAST(m."matnr" AS TEXT)), 10, \'0\')'
            )
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

    return (
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
    if not re.search(r"\b(total|sum of|how much|overall|altogether|combined)\b", q):
        return None
    if _SUPERLATIVE.search(q) or re.search(r"\btop\s+\d+\b", q):
        return None
    if re.search(
        r"\b(by |per |each |customer|customers|country|countries|industr|material|product|"
        r"year|month|quarter|vendor)\b",
        q,
    ):
        return None
    if not re.search(r"\b(sales|revenue|billing|billed|turnover)\b", q):
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

    return (
        f'SELECT SUM({net}) AS "total_sales", '
        f'COUNT(DISTINCT TRIM(CAST("{hdr}"."vbeln" AS TEXT))) AS "invoice_count"\n'
        f'FROM "{hdr}"\n'
        "WHERE " + "\n  AND ".join(where)
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
        if mcol and not any(
            pf.type == "column" and pf.table == mcol[0] and pf.column == mcol[1] for pf in plan.select
        ):
            plan.select.append(
                PlanField(type="column", table=mcol[0], column=mcol[1], purpose="measure")
            )
        dcol = _find_date_column(plan)
        if dcol and not any(
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
        if v is not None:
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
    if "percent" in calc or calc == "percentage_change":
        change = (
            f"CASE WHEN {period_a} <> 0 "
            f"THEN (({period_b} - {period_a}) / NULLIF({period_a}, 0)) * 100 END"
        )
        change_alias = "pct_change"
    else:
        change = f"({period_b} - {period_a})"
        change_alias = "change"

    # Keep dimension columns; replace measure aggregates with period compare fields.
    kept: List[PlanField] = []
    for pf in plan.select:
        is_measure = (
            pf.purpose == "measure"
            or (pf.type == "column" and (pf.column or "").lower() in {"netwr", "dmbtr", "wrbtr", "fkimg"})
            or (pf.type == "expression" and re.search(r"\b(SUM|AVG)\s*\(", pf.expression or "", re.I))
        )
        is_year = (pf.alias or "").lower() == "year" or (pf.purpose or "").lower() == "year"
        if is_measure or is_year:
            continue
        kept.append(pf)
    kept.append(PlanField(type="expression", expression=period_a, alias="period_a", purpose="measure"))
    kept.append(PlanField(type="expression", expression=period_b, alias="period_b", purpose="measure"))
    kept.append(PlanField(type="expression", expression=change, alias=change_alias, purpose="measure"))
    plan.select = kept

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

    # Scope years in WHERE so indexes / scanners stay bounded
    year_scope = f"{year_expr} IN ('{y_a}', '{y_b}')"
    if not any(year_scope in (f.expression or "") for f in plan.filters):
        plan.filters.append(PlanFilter(type="expression", expression=year_scope, operator="IN", value=None))

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
    if isinstance(tf, dict) and tf.get("value") is not None:
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
    if date_col and ("year" in group_by_dims or "year" in dimensions) and "month" not in group_by_dims:
        expr = year_filter_expression(date_col[0], date_col[1])
        if not any(s.alias == "year" for s in plan.select):
            plan.select.insert(0, PlanField(type="expression", expression=expr, alias="year", purpose="dimension"))
        if not any(g.alias == "year" for g in plan.group_by):
            plan.group_by.append(PlanField(type="expression", expression=expr, alias="year", purpose="dimension"))

    if agg == "COUNT":
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

    return errors[:15]


def _validate_expression_refs(expr: str, allowed_tables: List[str]) -> List[str]:
    """Ensure expression references only verified table.column pairs."""
    errors: List[str] = []
    allowed = {resolve_table_name(t) or t for t in allowed_tables}
    for tbl, col in re.findall(r'"([A-Za-z0-9_]+)"\s*\.\s*"([A-Za-z0-9_]+)"', expr):
        if tbl not in allowed and tbl.upper() not in {t.upper() for t in allowed}:
            errors.append(f"expression references unverified table {tbl}")
        elif not has_column(tbl, col):
            errors.append(f"expression references unknown column {tbl}.{col}")
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
            expr = f"SUM({numeric_cast_expr(pf.table, pf.column)})"
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
            field_name = str(ob.get("field") or ob.get("alias") or ob.get("column") or "")
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
    if not (plan.negation or (plan.semantic_requirements or {}).get("negation")):
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
    from .sql_generation_sanitizers import sanitize_netwr_sql, sanitize_sap_amount_columns_sql

    out = repair_quoted_expressions_as_columns(sql or "")
    out = repair_extract_on_text_dates(out)
    out = repair_bare_year_alias_in_case(out)
    out = repair_bare_time_grain_aliases(out)
    out = sanitize_sap_amount_columns_sql(out)
    out = sanitize_netwr_sql(out)
    if question:
        out = repair_absurd_question_literal_filters(out, question)
    return out


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
