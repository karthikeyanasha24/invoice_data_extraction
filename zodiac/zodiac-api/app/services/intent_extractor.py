"""
Intent extraction (single authoritative interpretation step).

Produces strict JSON intent which downstream stages must follow exactly.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
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


@lru_cache(maxsize=1)
def _build_dim_semantic_index() -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Build a reverse semantic index from table_mapping/*.json files.

    Each file maps SAP_COLUMN → "human readable description".
    We tokenise every description and build:
      token → [(TABLE, COLUMN, full_description), ...]

    This lets us resolve ANY logical dimension name to the best-matching
    SAP column without hardcoding anything.

    Returns: {token: [(table_upper, col_upper, description), ...]}
    """
    mapping_dir = Path(__file__).resolve().parent.parent / "table_mapping"
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    if not mapping_dir.exists():
        return index
    for fpath in sorted(mapping_dir.glob("*.json")):
        table = fpath.stem.upper()
        try:
            cols: Dict[str, str] = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        for col, desc in cols.items():
            if not desc or desc.startswith("["):
                continue
            desc_norm = desc.lower().replace("_", " ")
            col_upper = col.upper()
            for token in re.split(r"[\s_\-/]+", desc_norm):
                token = token.strip()
                if len(token) > 2:
                    index.setdefault(token, []).append((table, col_upper, desc_norm))
    return index


def _resolve_dim_semantically(
    logical: str,
    schema_u: Dict[str, List[str]],
    preferred_tables: List[str],
) -> Optional[Tuple[str, str]]:
    """
    Given a logical dimension name (e.g. "sales_org", "billing_type", "plant"),
    scan the semantic index to find the best matching (table, column) that:
      1. Exists in the current schema (schema_u)
      2. Prefers tables in preferred_tables
      3. Scores by how many tokens of the logical name appear in the description

    Returns (table_upper, column_upper) or None.
    """
    index = _build_dim_semantic_index()
    tokens = re.split(r"[\s_\-]+", logical.lower())
    tokens = [t for t in tokens if len(t) > 2]
    if not tokens:
        return None

    # Score: (table, col) → number of matching tokens
    scores: Dict[Tuple[str, str], int] = {}
    for token in tokens:
        for tbl, col, _desc in index.get(token, []):
            # Only consider if this table+col is in current schema
            cols_in_schema = schema_u.get(tbl, [])
            if not any(str(c).upper() == col for c in cols_in_schema):
                continue
            scores[(tbl, col)] = scores.get((tbl, col), 0) + 1

    if not scores:
        return None

    max_score = max(scores.values())
    # Among max-score matches, prefer preferred_tables, then VBRK/VBRP
    preferred_upper = [t.upper() for t in preferred_tables]
    billing_preferred = preferred_upper + ["VBRK", "VBRP", "VBAK", "VBAP"]

    best = None
    for (tbl, col), score in scores.items():
        if score < max_score:
            continue
        if best is None:
            best = (tbl, col)
        else:
            # Prefer tables in billing_preferred order
            best_rank = next(
                (i for i, t in enumerate(billing_preferred) if t == best[0]), 999
            )
            this_rank = next(
                (i for i, t in enumerate(billing_preferred) if t == tbl), 999
            )
            if this_rank < best_rank:
                best = (tbl, col)
    return best


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
    # "profit center" is an organisational dimension (prctr), not a profit metric
    if "profit" in q and "profit center" not in q and "profit centre" not in q:
        return "profit"
    if "revenue" in q or "sales" in q or "turnover" in q:
        return "revenue"
    if re.search(r"\b(count|how\s+many|number\s+of)\b", q):
        return "count"
    if "amount" in q or "netwr" in q:
        return "amount"
    return "revenue"


def _dimension_logicals_from_question(question: str, intent_type: str) -> List[str]:
    """
    Extract logical dimension names from a natural-language question.

    Each entry maps to a logical name that _map_logical_dimension_to_column()
    resolves against the live schema — no SAP field names are hardcoded here.
    Adding a new dimension is a one-line regex; the schema resolver handles the rest.
    """
    q = (question or "").lower()
    dims: List[str] = []

    # ── Time dimensions ──────────────────────────────────────────────────────────
    if re.search(r"\bwhich\s+years?\b|\bby\s+year\b|\bper\s+year\b|\byear[-\s]wise\b|\bannual(ly)?\b", q):
        dims.append("year")
    if re.search(r"\bby\s+month\b|\bmonthly\b|\bper\s+month\b", q):
        dims.append("month")
    if re.search(r"\bby\s+quarter\b|\bquarterly\b|\bper\s+quarter\b", q):
        dims.append("quarter")

    # ── SD / Billing dimensions ──────────────────────────────────────────────────
    if re.search(r"\bcustomer(s)?\b|\bsold[-\s]to\b", q):
        dims.append("customer")
    if re.search(r"\bproduct(s)?\b|\bmaterial(s)?\b", q):
        dims.append("product")
    if re.search(r"\bcountry\b|\bcountries\b", q):
        dims.append("country")
    if re.search(r"\bregion(s)?\b|\bterritor(y|ies)\b", q):
        dims.append("region")
    if re.search(r"\bindustry\b|\bsector\b|\bbranche?\b", q):
        dims.append("industry")
    if re.search(r"\bcurrenc(y|ies)\b|\bwaerk\b|\bwaers\b", q):
        dims.append("currency")
    if re.search(r"\bsales\s+org(anization)?\b|\bvkorg\b", q):
        dims.append("sales_org")
    if re.search(r"\bdistribution\s+channel\b|\bvtweg\b|\bchannel\b", q):
        dims.append("distribution_channel")
    if re.search(r"\bdivision\b|\bspart\b", q):
        dims.append("division")
    if re.search(r"\bplant(s)?\b|\bwerks\b", q):
        dims.append("plant")
    if re.search(r"\bbilling\s+type\b|\bdocument\s+type\b|\bfkart\b", q):
        dims.append("billing_type")
    if re.search(r"\bcompany\s+code\b|\bbukrs\b", q):
        dims.append("company_code")
    if re.search(r"\bsales\s+district\b|\bbzirk\b|\bdistrict\b", q):
        dims.append("sales_district")
    if re.search(r"\bmaterial\s+group\b|\bmatkl\b", q):
        dims.append("material_group")

    # ── Purchasing / Vendor dimensions ───────────────────────────────────────────
    if re.search(r"\bvendor(s)?\b|\bsupplier(s)?\b|\blifnr\b", q):
        dims.append("vendor")
    if re.search(r"\bpurchasing\s+org(anization)?\b|\bekorg\b", q):
        dims.append("purchasing_org")
    if re.search(r"\border\s+type\b|\bauart\b", q):
        dims.append("order_type")

    # ── If trend/comparison without explicit time dim but years mentioned ─────────
    if intent_type in ("trend", "comparison") and "year" not in dims and re.search(r"\b(?:19|20)\d{2}\b", q):
        dims.append("year")

    return list(dict.fromkeys(dims))  # deduplicate, preserve order


def _map_logical_dimension_to_column(
    schema: Dict[str, List[str]], logical: str, metric_table: Optional[str]
) -> Optional[DimensionSpec]:
    """
    Map a logical dimension name to the best SAP column in the current schema.

    Resolution order (no hardcoding beyond the core time-grain logic):
      1. Time dimensions (year/month/quarter): always use a date column + YEAR/MONTH transform.
         Prefer FKDAT in VBRK for billing context; fall back to any date column.
      2. Known SAP field synonyms: a small lookup of (logical → [candidate_SAP_fields])
         tried in preferred-table order.  This covers the most common dimensions
         (customer, product, country, currency, sales_org, plant, …) with known SAP names.
      3. Semantic index fallback: scan all table_mapping/ descriptions for tokens that
         match the logical name.  Works for ANY dimension we haven't explicitly named.
    """
    logical = (logical or "").lower()
    schema_u = _lower_set(schema)
    preferred_tables: List[str] = []
    if metric_table:
        preferred_tables.append(metric_table.upper())

    # ── 1. Time dimensions ───────────────────────────────────────────────────────
    if logical in ("year", "month", "quarter"):
        # Billing context: prefer FKDAT on VBRK; generic fallback to BUDAT/BLDAT
        billing_date_tables = ["VBRK", "VBAK"] + preferred_tables
        tbl = (
            _find_table_with_column(schema_u, "FKDAT", billing_date_tables)
            or _find_table_with_column(schema_u, "BUDAT", preferred_tables)
            or _find_table_with_column(schema_u, "BLDAT", preferred_tables)
        )
        if not tbl:
            return None
        if any(str(c).upper() == "FKDAT" for c in schema_u.get(tbl, [])):
            col = "FKDAT"
        elif any(str(c).upper() == "BUDAT" for c in schema_u.get(tbl, [])):
            col = "BUDAT"
        else:
            col = "BLDAT"
        transform = {"year": "YEAR", "month": "MONTH", "quarter": "QUARTER"}[logical]
        return DimensionSpec(
            logical=logical,
            column_ref=ColumnRef(table=tbl, column=col),
            transform=transform,
            alias=logical,
        )

    # ── 2. SAP field synonym map ─────────────────────────────────────────────────
    # Maps logical_name → ordered list of (preferred_table_order, [candidate_SAP_fields])
    # The first candidate found in the current schema wins.
    _SYNONYM_MAP: Dict[str, Tuple[List[str], List[str]]] = {
        "customer":          (["VBRK", "KNA1", "BSAD", "BSEG"],  ["KUNAG", "KUNNR"]),
        "sold_to":           (["VBRK", "KNA1"],                   ["KUNAG", "KUNNR"]),
        "product":           (["VBRP", "VBAP", "LIPS", "EKPO"],   ["MATNR"]),
        "material":          (["VBRP", "VBAP", "LIPS", "MARA"],   ["MATNR"]),
        "country":           (["VBRK", "KNA1", "LFA1"],           ["LAND1"]),
        "region":            (["VBRK", "KNA1"],                   ["REGIO", "LAND1"]),
        "currency":          (["VBRK", "VBAK", "BSEG"],           ["WAERK", "WAERS"]),
        "industry":          (["KNA1"],                           ["BRSCH"]),
        "sales_org":         (["VBRK", "VBAK", "LIKP", "MVKE"],  ["VKORG"]),
        "sales_organization":(["VBRK", "VBAK", "LIKP"],          ["VKORG"]),
        "distribution_channel":(["VBRK", "VBAK", "LIPS"],        ["VTWEG"]),
        "dist_channel":      (["VBRK", "VBAK"],                  ["VTWEG"]),
        "division":          (["VBRK", "VBAK", "VBAP"],          ["SPART"]),
        "plant":             (["VBRP", "LIPS", "EKPO", "AUFK"],  ["WERKS"]),
        "billing_type":      (["VBRK"],                          ["FKART"]),
        "document_type":     (["VBRK", "VBAK", "BKPF"],         ["FKART", "AUART", "BLART"]),
        "company_code":      (["VBRK", "BKPF", "AUFK"],         ["BUKRS"]),
        "sales_district":    (["VBRK", "KNA1"],                  ["BZIRK"]),
        "material_group":    (["VBRP", "LIPS", "MARA"],          ["MATKL"]),
        "vendor":            (["LFA1", "EKKO"],                   ["LIFNR"]),
        "supplier":          (["LFA1", "EKKO"],                   ["LIFNR"]),
        "purchasing_org":    (["EKKO"],                           ["EKORG"]),
        "purch_org":         (["EKKO"],                           ["EKORG"]),
        "profit_center":     (["VBRP", "AUFK", "COEP"],          ["PRCTR"]),
        "cost_center":       (["AUFK", "CSKS", "COEP"],          ["KOSTL"]),
        "fiscal_year":       (["BKPF", "COEP"],                  ["GJAHR"]),
        "order_type":        (["VBAK", "AUFK"],                  ["AUART"]),
    }

    if logical in _SYNONYM_MAP:
        pref_tbls, candidates = _SYNONYM_MAP[logical]
        for col in candidates:
            tbl = _find_table_with_column(schema_u, col, pref_tbls + preferred_tables)
            if tbl:
                return DimensionSpec(
                    logical=logical,
                    column_ref=ColumnRef(table=tbl, column=col),
                    transform="NONE",
                    alias=logical,
                )

    # ── 3. Semantic index fallback (works for any dimension not in the map above) ─
    result = _resolve_dim_semantically(logical, schema_u, preferred_tables)
    if result:
        tbl, col = result
        return DimensionSpec(
            logical=logical,
            column_ref=ColumnRef(table=tbl, column=col),
            transform="NONE",
            alias=logical,
        )

    return None


def _map_metric(schema: Dict[str, List[str]], logical_metric: str) -> MetricSpec:
    schema_u = _lower_set(schema)
    lm = (logical_metric or "revenue").lower()
    # Revenue/sales for SAP billing: prefer VBRP.NETWR (line net value)
    if lm in ("revenue", "sales", "amount"):
        if "VBRP" in schema_u and any(str(c).upper() == "NETWR" for c in schema_u["VBRP"]):
            return MetricSpec(logical="revenue", aggregation="SUM", column_ref=ColumnRef(table="VBRP", column="NETWR"), alias="total_sales")
        if "VBRK" in schema_u and any(str(c).upper() == "NETWR" for c in schema_u["VBRK"]):
            return MetricSpec(logical="revenue", aggregation="SUM", column_ref=ColumnRef(table="VBRK", column="NETWR"), alias="total_sales")
        # fallback to common money columns
        for col in ("RMWWR", "WRBTR", "DMBTR", "BRTWR"):
            t = _find_table_with_column(schema_u, col, ["VBRP", "VBRK", "FAGLFLEXA", "BSAD", "BSEG"])
            if t:
                return MetricSpec(logical=lm, aggregation="SUM", column_ref=ColumnRef(table=t, column=col), alias="total_sales")
        return MetricSpec(logical=lm, aggregation="SUM", column_ref=None, alias="total_sales")
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



def is_intent_pipeline_appropriate(question: str) -> bool:
    """
    DISABLED: The rule-based intent pipeline is bypassed for all queries.

    With 118 tables and unpredictable user questions, every query is routed
    to the LLM SQL agent (GPT-4o → Claude → Gemini) which generates correct,
    adaptive SQL without any hardcoded rules.

    The LLM handles:
      • "show sales for year 2000"  → correctly adds WHERE year filter
      • "top 10 customers by revenue" → correct GROUP BY
      • "cost trend for profit center X" → correct CO tables
      • Any other natural-language question over 118 tables

    Returns False always so every query goes to run_sap_sql_agent.
    """
    return False  # all queries → LLM SQL agent (gpt-4o / claude / gemini)

    # ── DEAD CODE BELOW — kept for reference only ─────────────────────────────
    q = (question or "").lower()  # noqa: F841

    # ── 0. Hard always-exclude: domains the intent pipeline has NO tables for ──
    # These win even over analytics signals because returning wrong data (e.g.
    # VBRP revenue when CO cost is requested) is worse than falling through.
    hard_exclusions = [
        r'\bprofit\s+cent(er|re)\b',       # CO Controlling — CEPC/CSKS
        r'\bcost\s+cent(er|re)\b',         # CO Controlling — CSKS
        r'\binternal\s+order\b',            # CO internal orders — AUFK
        r'\b(coss|cosp|coep|aufk|csks|cepc|cobk)\b',  # CO table names
        r'\bcontrolling\b',
        r'\bgeneral\s+ledger\b',            # FI-GL — BKPF/BSEG
        r'\bjournal\s+(entr|posting)',
        r'\b(bkpf|bseg|bsad|bsak|bsas|faglflexa)\b',
        r'\bgl\s+(account|posting|doc)',
        r'\bstock\b',                       # MM Inventory — MARD
        r'\binventor(y|ies)\b',
        r'\b(mard|marc|marm)\b',
    ]
    if any(re.search(p, q) for p in hard_exclusions):
        return False  # always route to sap_sql_agent regardless of analytics signals

    # ── 1. Analytics patterns (checked first — these override soft exclusions) ──
    analytics_patterns = [
        r'\brevenue\b',
        r'\bsales\b',
        r'\bturnover\b',
        r'\b(netwr|waerk)\b',
        r'\bprofit(?!\s+cent(er|re))\b',  # "profit" but NOT "profit center/centre"
        # "top N by dimension"
        r'\btop\b.{0,30}\b(customers?|products?|materials?|countr|region|vendor|supplier)',
        r'\b(customers?|products?|materials?|countr|region|vendor|supplier).{0,30}\btop\b',
        # "by <dimension>" — the key analytics grouping signal
        r'\bby\s+(customers?|countr|products?|materials?|year|month|region|currency|vendor|supplier)\b',
        # superlatives on billing amounts
        r'\b(highest|lowest|best|worst).{0,25}\b(sale|revenue|amount|billing|invoice)',
        # totals / sums
        r'\btotal\s+(revenue|sales|billing|invoice|amount)',
        r'\bsum\s+of\s+(revenue|sales|netwr|amount)\b',
        r'\b(invoice|billing)\s+(total|amount|value|sum)\b',
        # trends
        r'\brevenue\s+by\b',   r'\bsales\s+by\b',
        r'\bsales\s+trend\b',  r'\brevenue\s+trend\b',
        # counts
        r'\bnumber\s+of\s+(invoices?|billing|orders?)',
        r'\binvoice\s+(count|volume|value)\b',
        # "by currency" alone is a strong analytics signal
        r'\bby\s+currenc',
        r'\bper\s+currenc',
        r'\bgrouped?\s+by\b',
    ]
    analytics_match = any(re.search(p, q) for p in analytics_patterns)
    if analytics_match:
        return True  # analytics intent overrides any exclusion keyword

    # ── 2. Hard operational exclusions (only reached when NO analytics signal) ─
    exclusion_patterns = [
        # Purchasing / procurement — non-analytics operational queries
        r'\bpurchase\s+(order|requisition)',
        r'\b(po|pos)\b(?!\s*box)',
        r'\bprocur',
        r'\b(ekko|ekpo|ekbe|ekes|eket|eban)\b',
        # Deliveries / logistics
        r'\bdeliver(y|ies)\b',
        r'\bshipment',
        r'\b(likp|lips)\b',
        # Vendor/supplier lookup (master data, not analytics — only excluded when no analytics signal)
        r'\bvendor\s+(master|list|detail|record|profile|number|id)\b',
        r'\bsupplier\s+(master|list|detail|record|profile)\b',
        r'\b(lfa1|lfb1|lfm1|lfm2)\b',
        # EDI / operational system queries
        r'\bedi\b',
        r'\b(cfdi|sat)\b',
        r'\bzodiac\b',
        r'\binbound\b',
        # GL / accounting entries
        r'\bgeneral\s+ledger\b',
        r'\bjournal\s+(entr|posting)',
        r'\b(bkpf|bseg|bsad|bsak|bsas|faglflexa)\b',
        r'\bgl\s+(account|posting|doc)',
        # Inventory / material master lookups
        r'\bstock\b',
        r'\binventor(y|ies)\b',
        r'\b(mard|marc|marm)\b',
        # Invoice status / list queries (not aggregations)
        r'\b(open|overdue|pending|blocked|unprocessed)\b.{0,40}\b(invoice|document|billing)\b',
        r'\b(invoice|document|billing).{0,40}\b(open|overdue|pending|status|blocked)\b',
        r'\bfailed\b.{0,30}\b(invoice|document|edi|posting)\b',
        # List/show queries with no aggregation intent
        r'\b(list|show|display|find|get)\s+(me\s+)?(all\s+)?(vendor|supplier|purchase|delivery)',
        # CO / Controlling module — cost centers, profit centers, internal orders
        # These need CO tables (COSS, COSP, COEP, AUFK, CSKS) not VBRK/VBRP
        r'\bprofit\s+cent(er|re)\b',
        r'\bcost\s+cent(er|re)\b',
        r'\binternal\s+order\b',
        r'\b(coss|cosp|coep|aufk|csks|cepc|cobk)\b',
        r'\bcontrolling\b',
        r'\bco\s+(module|object|area)\b',
        # Cost metrics (not in VBRK/VBRP)
        r'\b(cost|expense|spend)\s+(trend|by|per|breakdown)\b',
        r'\bactual\s+(cost|spend)\b',
        r'\bplan(ned)?\s+(cost|budget)\b',
    ]
    if any(re.search(p, q) for p in exclusion_patterns):
        return False

    # ── 3. Default: route to LLM SQL agent ────────────────────────────────────
    return False
