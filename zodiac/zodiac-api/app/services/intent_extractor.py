"""
Intent extraction (single authoritative interpretation step).

Produces strict JSON intent which downstream stages must follow exactly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .explicit_table_sql import extract_explicit_table_identifiers
from .schema_loader import load_schema_from_mapping_file
from .intent_contract import (
    ColumnRef,
    ComparisonSpec,
    DimensionSpec,
    FilterSpec,
    Intent,
    MetricSpec,
    RankingSpec,
)


def _lower_set(schema: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {t.upper(): [c for c in cols] for t, cols in (schema or {}).items()}


def _find_table_with_column(schema: Dict[str, List[str]], column_upper: str, preferred: List[str]) -> Optional[str]:
    for t in preferred:
        cols = schema.get(t.upper()) or []
        if any(str(c).upper() == column_upper for c in cols):
            return t.upper()
    for t, cols in schema.items():
        if any(str(c).upper() == column_upper for c in cols):
            return t.upper()
    return None


def _extract_years(question: str) -> List[str]:
    return list(dict.fromkeys(re.findall(r"\b((?:19|20)\d{2})\b", question or "")))


def _extract_top_n(question: str, default: int = 5) -> int:
    q = (question or "").lower()
    m = re.search(r"\btop\s+(\d+)\b", q)
    if m:
        try:
            v = int(m.group(1))
            if 1 <= v <= 200:
                return v
        except Exception:
            pass
    m2 = re.search(r"\bfirst\s+(\d+)\b", q)
    if m2:
        try:
            v = int(m2.group(1))
            if 1 <= v <= 200:
                return v
        except Exception:
            pass
    return default


def _detect_intent_type(question: str) -> str:
    q = (question or "").lower()
    # Highest sales by year / "which years" is a time-series question (trend over year),
    # not a product ranking question.
    if re.search(r"\bwhich\s+years?\b", q):
        return "trend"
    if re.search(r"\b(last|first|top)\s+\d+\s+rows?\b", q) or re.search(r"\b(raw|rows?)\b", q):
        # Compare/ranking override
        if re.search(r"\b(compare|vs\.?|versus)\b", q):
            return "comparison"
        return "raw_inspection"
    if re.search(r"\b(compare|vs\.?|versus|difference|changed?\b|from\b.+?\bto\b)\b", q) or len(_extract_years(q)) >= 2:
        return "comparison"
    if re.search(r"\b(top|bottom|highest|lowest|largest|smallest|rank|best|worst)\b", q):
        return "ranking"
    if re.search(r"\b(trend|over\s+time|time\s*series|by\s+month|monthly|by\s+year|yearly)\b", q):
        return "trend"
    if re.search(r"\b(share|distribution|proportion|percent|percentage|breakdown)\b", q):
        return "distribution"
    if re.search(r"\b(total|sum|average|avg|count|how\s+many)\b", q):
        return "aggregate"
    return "lookup"


def _detect_time_grain(question: str) -> str:
    q = (question or "").lower()
    if re.search(r"\b(month|monthly|per\s+month|by\s+month)\b", q):
        return "month"
    if re.search(r"\b(quarter|quarterly|per\s+quarter|by\s+quarter)\b", q):
        return "quarter"
    if re.search(r"\b(year|yearly|per\s+year|by\s+year)\b", q) or re.search(r"\b(?:19|20)\d{2}\b", q):
        return "year"
    return "none"


def _metric_from_question(question: str) -> str:
    q = (question or "").lower()
    if "profit margin" in q or "margin" in q:
        return "profit_margin"
    if "profit" in q:
        return "profit"
    if "revenue" in q or "sales" in q or "turnover" in q:
        return "revenue"
    if re.search(r"\b(count|how\s+many|number\s+of)\b", q):
        return "count"
    if "amount" in q or "netwr" in q:
        return "amount"
    return "revenue"


def _dimension_logicals_from_question(question: str, intent_type: str) -> List[str]:
    q = (question or "").lower()
    dims: List[str] = []
    # time dims
    if re.search(r"\bwhich years\b", q) or re.search(r"\bby\s+year\b", q) or re.search(r"\byear-wise\b", q):
        dims.append("year")
    if re.search(r"\bby\s+month\b|\bmonthly\b", q):
        dims.append("month")
    # entities
    if re.search(r"\bcustomer(s)?\b|\bsold-?to\b", q):
        dims.append("customer")
    if re.search(r"\bproduct(s)?\b|\bmaterial(s)?\b", q):
        dims.append("product")
    if re.search(r"\bcountry\b|\bregion\b", q):
        dims.append("country")
    if re.search(r"\bindustry\b|\bsector\b", q):
        dims.append("industry")
    if re.search(r"\bcurrency\b|\bwaerk\b|\bwaers\b", q):
        dims.append("currency")
    # If compare/trend without explicit breakdown but years are present, force year
    if intent_type in ("trend", "comparison") and "year" not in dims and re.search(r"\b(?:19|20)\d{2}\b", q):
        dims.append("year")
    return list(dict.fromkeys(dims))


def _map_logical_dimension_to_column(schema: Dict[str, List[str]], logical: str, metric_table: Optional[str]) -> Optional[DimensionSpec]:
    logical = (logical or "").lower()
    schema_u = _lower_set(schema)
    preferred_tables: List[str] = []
    if metric_table:
        preferred_tables.append(metric_table.upper())
    # SAP billing defaults
    if logical in ("year", "month"):
        # Prefer billing date FKDAT for billing context when VBRK exists
        if "VBRK" in schema_u:
            preferred_tables = ["VBRK"] + preferred_tables
        tbl = _find_table_with_column(schema_u, "FKDAT", preferred_tables) or _find_table_with_column(schema_u, "BUDAT", preferred_tables)
        if not tbl:
            return None
        col = "FKDAT" if any(str(c).upper() == "FKDAT" for c in schema_u.get(tbl, [])) else "BUDAT"
        transform = "YEAR" if logical == "year" else "MONTH"
        alias = "year" if logical == "year" else "month"
        return DimensionSpec(logical=logical, column_ref=ColumnRef(table=tbl, column=col), transform=transform, alias=alias)
    if logical == "customer":
        # Prefer VBRK.KUNAG for billing customer context (per schema hints)
        if "VBRK" in schema_u and any(str(c).upper() == "KUNAG" for c in schema_u["VBRK"]):
            return DimensionSpec(logical="customer", column_ref=ColumnRef(table="VBRK", column="KUNAG"), transform="NONE", alias="customer")
        tbl = _find_table_with_column(schema_u, "KUNNR", ["KNA1", "VBRK", "BSAD", "BSEG"] + preferred_tables)
        if not tbl:
            return None
        return DimensionSpec(logical="customer", column_ref=ColumnRef(table=tbl, column="KUNNR"), transform="NONE", alias="customer")
    if logical == "product":
        tbl = _find_table_with_column(schema_u, "MATNR", ["VBRP", "VBAP", "LIPS", "EKPO", "MAKT"] + preferred_tables)
        if not tbl:
            return None
        return DimensionSpec(logical="product", column_ref=ColumnRef(table=tbl, column="MATNR"), transform="NONE", alias="product")
    if logical == "country":
        # Prefer VBRK.LAND1 if present (schema hint)
        if "VBRK" in schema_u and any(str(c).upper() == "LAND1" for c in schema_u["VBRK"]):
            return DimensionSpec(logical="country", column_ref=ColumnRef(table="VBRK", column="LAND1"), transform="NONE", alias="country")
        tbl = _find_table_with_column(schema_u, "LAND1", ["KNA1"] + preferred_tables)
        if not tbl:
            return None
        return DimensionSpec(logical="country", column_ref=ColumnRef(table=tbl, column="LAND1"), transform="NONE", alias="country")
    if logical == "currency":
        # Billing currency is WAERK in VBRK
        if "VBRK" in schema_u and any(str(c).upper() == "WAERK" for c in schema_u["VBRK"]):
            return DimensionSpec(logical="currency", column_ref=ColumnRef(table="VBRK", column="WAERK"), transform="NONE", alias="currency")
        tbl = _find_table_with_column(schema_u, "WAERS", preferred_tables) or _find_table_with_column(schema_u, "WAERK", preferred_tables)
        if not tbl:
            return None
        col = "WAERS" if any(str(c).upper() == "WAERS" for c in schema_u.get(tbl, [])) else "WAERK"
        return DimensionSpec(logical="currency", column_ref=ColumnRef(table=tbl, column=col), transform="NONE", alias="currency")
    if logical == "industry":
        tbl = _find_table_with_column(schema_u, "BRSCH", ["KNA1"] + preferred_tables)
        if not tbl:
            return None
        return DimensionSpec(logical="industry", column_ref=ColumnRef(table=tbl, column="BRSCH"), transform="NONE", alias="industry")
    return None


def _map_metric(schema: Dict[str, List[str]], logical_metric: str) -> MetricSpec:
    schema_u = _lower_set(schema)
    lm = (logical_metric or "revenue").lower()
    # Revenue/sales for SAP billing: prefer VBRP.NETWR (line net value)
    if lm in ("revenue", "sales", "amount"):
        if "VBRP" in schema_u and any(str(c).upper() == "NETWR" for c in schema_u["VBRP"]):
            return MetricSpec(logical="revenue", aggregation="SUM", column_ref=ColumnRef(table="VBRP", column="NETWR"), alias="value")
        if "VBRK" in schema_u and any(str(c).upper() == "NETWR" for c in schema_u["VBRK"]):
            return MetricSpec(logical="revenue", aggregation="SUM", column_ref=ColumnRef(table="VBRK", column="NETWR"), alias="value")
        # fallback to common money columns
        for col in ("RMWWR", "WRBTR", "DMBTR", "BRTWR"):
            t = _find_table_with_column(schema_u, col, ["VBRP", "VBRK", "FAGLFLEXA", "BSAD", "BSEG"])
            if t:
                return MetricSpec(logical=lm, aggregation="SUM", column_ref=ColumnRef(table=t, column=col), alias="value")
        return MetricSpec(logical=lm, aggregation="SUM", column_ref=None, alias="value")
    if lm == "count":
        # Default count: billing documents if VBRK exists, otherwise rows
        if "VBRK" in schema_u and any(str(c).upper() == "VBELN" for c in schema_u["VBRK"]):
            return MetricSpec(logical="count", aggregation="COUNT_DISTINCT", column_ref=ColumnRef(table="VBRK", column="VBELN"), alias="count")
        return MetricSpec(logical="count", aggregation="COUNT", column_ref=None, alias="count")
    if lm in ("profit_margin", "profit"):
        # Derived; planner will attempt to map components if available
        return MetricSpec(logical=lm, aggregation="NONE", column_ref=None, alias=lm, derived=True)
    return MetricSpec(logical=lm, aggregation="SUM", column_ref=None, alias="value")


def extract_intent(question: str, schema: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """
    Returns strict intent JSON (no free text).
    """
    schema = schema or load_schema_from_mapping_file()
    q = question or ""
    intent_type = _detect_intent_type(q)
    metric_logical = _metric_from_question(q)
    metric = _map_metric(schema, metric_logical)
    metric_table = metric.column_ref.table if metric.column_ref else None
    dims_logical = _dimension_logicals_from_question(q, intent_type)
    dims: List[DimensionSpec] = []
    for dl in dims_logical:
        dspec = _map_logical_dimension_to_column(schema, dl, metric_table)
        if dspec:
            dims.append(dspec)
    # Filters: calendar years requested become FKDAT year filters when user specifies years
    years = _extract_years(q)
    filters: List[FilterSpec] = []
    if years:
        date_dim = _map_logical_dimension_to_column(schema, "year", metric_table)
        if date_dim:
            filters.append(FilterSpec(column_ref=date_dim.column_ref, operator="IN_YEAR", value=years))

    # Ranking spec
    ranking = RankingSpec()
    if intent_type == "ranking":
        ranking = RankingSpec(enabled=True, order="desc", limit=_extract_top_n(q))
        if re.search(r"\b(bottom|lowest|smallest)\b", q.lower()):
            ranking = RankingSpec(enabled=True, order="asc", limit=_extract_top_n(q))

    # Comparison spec
    comparison = ComparisonSpec(enabled=(intent_type == "comparison"), periods=years[:6])

    time_granularity = _detect_time_grain(q)
    explicit_tables = extract_explicit_table_identifiers(q)

    domain = "sap"
    if explicit_tables:
        # If an explicit table looks like an app table, allow app domain
        if any(t.lower().startswith("ai_") or t.lower().startswith("zodiac_") for t in explicit_tables):
            domain = "app"

    # Ensure year dimension is present when user asks "which years" or compare includes years
    if (re.search(r"\bwhich years\b", q.lower()) or (intent_type == "comparison" and years)) and not any(d.logical == "year" for d in dims):
        yd = _map_logical_dimension_to_column(schema, "year", metric_table)
        if yd:
            dims.insert(0, yd)

    # Never leave dimensions empty for trend/comparison (must have time axis)
    if intent_type in ("trend", "comparison") and not dims:
        yd = _map_logical_dimension_to_column(schema, "year", metric_table)
        if yd:
            dims.append(yd)

    intent = Intent(
        intent_type=intent_type,  # type: ignore[arg-type]
        metric=metric,
        dimensions=dims,
        filters=filters,
        time_granularity=time_granularity,  # type: ignore[arg-type]
        ranking=ranking,
        comparison=comparison,
        explicit_tables=explicit_tables[:12],
        domain=domain,  # type: ignore[arg-type]
        debug={"years": years, "dimension_logicals": dims_logical, "metric_logical": metric_logical},
    )
    return intent.to_json()

