"""Generic analytical-language interpretation for the query plan.

Phrases such as "by month", "top 10", "highest", "share", "trend" become
structured operations on the semantic plan. This is not a question→SQL map.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..data_catalog.physical import column_names, has_column, has_table, resolve_table_name

_MEASURE_COLS = frozenset({
    "netwr", "dmbtr", "wrbtr", "rmwwr", "fkimg", "menge", "wavwr", "kwert", "kbetr",
})
_CURRENCY_COLS = frozenset({"waerk", "waers", "rtcur", "hwaer"})
_DATE_COLS = frozenset({
    "fkdat", "audat", "bedat", "budat", "erdat", "bldat", "wadat", "cpudt", "aedat",
})
_ID_COLS = frozenset({"vbeln", "kunnr", "kunag", "matnr", "lifnr", "ebeln", "belnr", "posnr"})
_MASTER_GRAIN_MARKERS = (
    "per customer", "per material", "per vendor", "one row per customer",
    "one row per material", "one row per vendor",
)
_TX_GRAIN_MARKERS = (
    "document", "billing", "invoice", "item", "order", "purchase",
)

_GROUP_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(?:one row per|by|per|each)\s+(?:billing\s+)?(?:documents?|invoices?)\b|"
        r"\b(?:top|bottom)\s+(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
        r"(?:billing\s+|billed\s+)?(?:documents?|invoices?)\b|"
        r"\b(?:highest|lowest)[- ]value\s+(?:billing\s+|billed\s+)?(?:documents?|invoices?)\b",
        "document",
    ),
    (r"\b(by|per|each|for each|and)\s+months?\b|\bmonthly\b", "month"),
    (r"\b(by|per|each|for each)\s+(?:(?:calendar|fiscal|full|complete)\s+)?years?\b|\byearly\b|\bannually\b|\bannual\b|\beach year\b", "year"),
    (r"\b(by|per|each|for each)\s+quarters?\b|\bquarterly\b", "quarter"),
    (r"\b(by|per|each|for each)\s+(?:customer\s+)?countr(?:y|ies)\b", "country"),
    (r"\b(by|per|each|for each|and)\s+customers?\b(?!\s+countr(?:y|ies))|"
     r"\bcustomer\s+names?\b", "customer"),
    (r"\b(by|per|each|for each)\s+(?:industr(?:y|ies)|sectors?)\b", "industry"),
    (r"\b(by|per|each|for each)\s+(?:materials?|products?)\b", "material"),
    (r"\b(by|per|each|for each)\s+(?:suppliers?|vendors?)\b", "vendor"),
    (r"\b(by|per|each|for each)\s+(?:plants?|werks)\b", "plant"),
    (r"\b(by|per|each|for each)\s+currenc(?:y|ies)\b", "currency"),
    (r"\b(by|per|each|for each)\s+(?:types?|document types?)\b", "type"),
]

_TOP_N = re.compile(
    r"\b(?:top|bottom|highest|lowest)\s+(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I,
)
_RANKED_SET_COUNT = re.compile(
    r"\b(\d{1,3})\s+(?:(?:[a-z][a-z-]*\s+){1,4})"
    r"(?:with|having)\s+(?:the\s+)?"
    r"(?:most|least|highest|lowest|largest|smallest|biggest|worst|best)\b",
    re.I,
)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_LATEST_DATA_YEARS = re.compile(
    r"\b(?:latest|most recent|last)\s+"
    r"(?:(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
    r"(?:full|complete)\s+(?:calendar\s+)?years?\b", re.I,
)
_PARTITION_RANK = re.compile(
    r"\b(?:top|bottom)\s+(\d{1,3})\s+\w+\s+(?:in each|per|for each|by each|within each)\s+(\w+)",
    re.I,
)
_PARTITION_EACH = re.compile(
    r"\b(?:top|bottom|highest|lowest|most|least|best|worst|largest|biggest)\b[\s\S]{0,80}?\b(?:in each|per|for each|within each)\s+(\w+)",
    re.I,
)
_WHICH_ENTITY = re.compile(
    r"\b(?:which|what)\s+(countries|country|customers?|clients?|buyers?|materials?|products?|"
    r"suppliers?|vendors?|industr(?:y|ies)|segments?|plants?)\b",
    re.I,
)
_CONTEXTUAL_SUPERLATIVE_ENTITY = re.compile(
    r"^\s*(?:for|within|among)\s+(?:the\s+)?"
    r"(?:higher|highest|lower|lowest|top|bottom|leading|best|worst|largest|smallest|most|least)"
    r"(?:[-\s]+(?:sales|revenue|billed|billing|value|amount|profit|profitable))?\s+"
    r"(?:sales\s+)?"
    r"(?:countr(?:y|ies)|customers?|clients?|buyers?|materials?|products?|suppliers?|vendors?|"
    r"industr(?:y|ies)|segments?|plants?|documents?|invoices?)\b",
    re.I,
)
_RELATIVE_PERIODS = [
    (r"\b(?:latest|most recent)\s+two\s+(?:(?:full|complete)\s+)?(?:calendar\s+)?years?\b", "latest_two_full_years"),
    (r"\b(?:latest|most recent)\s+(?:(?:full|complete)\s+)?(?:calendar\s+)?years?\b", "latest_full_year"),
    (r"\bthis week\b", "this_week"),
    (r"\blast week\b", "last_week"),
    (r"\bthis month\b", "this_month"),
    (r"\blast month\b", "last_month"),
    (r"\bthis quarter\b", "this_quarter"),
    (r"\blast quarter\b", "last_quarter"),
    (r"\bthis year\b", "this_year"),
    (r"\blast year\b", "last_year"),
    (r"\byear[- ]to[- ]date\b|\bytd\b", "ytd"),
    (r"\bmonth[- ]to[- ]date\b|\bmtd\b", "mtd"),
]
_NEGATION = re.compile(
    r"\b(without|with no|but no|that did not|who did not|never sold|not sold|"
    r"no invoices?|no (?:purchase )?orders?|did not purchase|had no)\b",
    re.I,
)
_ENTITY_WORDS = {
    "country": "country", "countries": "country",
    "customer": "customer", "customers": "customer",
    "client": "customer", "clients": "customer",
    "buyer": "customer", "account": "customer",
    "material": "material", "materials": "material",
    "product": "material", "products": "material",
    "supplier": "vendor", "suppliers": "vendor",
    "vendor": "vendor", "vendors": "vendor",
    "industry": "industry", "industries": "industry",
    "plant": "plant", "plants": "plant", "werks": "plant",
    "document": "document", "documents": "document",
    "invoice": "document", "invoices": "document",
}


def ranking_count_is_explicit(question: str) -> bool:
    """An inferred display default is not a user-requested exact row count."""
    q = (question or "").lower()
    return bool(_TOP_N.search(q) or _RANKED_SET_COUNT.search(q) or re.search(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
        r"(?:customers?|countries|products?|materials?|vendors?|suppliers?)\b.{0,80}"
        r"\b(?:most|least|highest|lowest|top|bottom)\b|"
        r"\bwhich\s+(?:country|customer|product|material|vendor|supplier)\b", q,
    ))


def classify_column_role(table: str, column: str) -> str:
    col = (column or "").lower()
    if col in _MEASURE_COLS:
        return "measure"
    if col in _CURRENCY_COLS:
        return "currency"
    if col in _DATE_COLS:
        return "date"
    if col in _ID_COLS:
        return "identifier"
    if col in {"name1", "name2", "maktx", "arktx", "brtxt", "ort01"}:
        return "attribute"
    if col in {"land1", "brsch", "waerk", "vkorg", "auart", "fkart", "spart"}:
        return "dimension"
    blob = col
    if any(x in blob for x in ("dat", "date")):
        return "date"
    if any(x in blob for x in ("wrb", "net", "amt", "amount", "wert")):
        return "measure"
    return "attribute"


def table_is_master(table: str) -> bool:
    # Hard fact/document tables — never treat as master even if grain text is ambiguous.
    _FACT = {
        "VBRK", "VBRP", "VBAK", "VBAP", "VBEP", "EKKO", "EKPO", "EBAN",
        "RBKP", "RSEG", "BKPF", "BSEG", "BSAD", "BSAK", "FAGLFLEXA", "COEP", "MKPF", "MSEG",
    }
    if (table or "").upper() in _FACT:
        return False
    try:
        from .schema_intelligence_registry import get_schema_registry

        meta = get_schema_registry().get_table(table)
        grain = (getattr(meta, "grain", "") or "").lower() if meta else ""
        desc = (getattr(meta, "description", "") or "").lower() if meta else ""
        blob = f"{grain} {desc} {table}".lower()
        # Transactional cues win over ambiguous master substrings
        # (e.g. grain "one row per vendor invoice" must not match "one row per vendor").
        if any(m in blob for m in _TX_GRAIN_MARKERS):
            return False
        if any(m in blob for m in _MASTER_GRAIN_MARKERS) or re.search(r"\bmaster\b", blob):
            return True
    except Exception:
        pass
    names = {c.lower() for c in (column_names(table) or [])}
    return not bool(names & _MEASURE_COLS)


def table_has_measure_columns(table: str, concept: str = "sales") -> bool:
    names = {c.lower() for c in (column_names(table) or [])}
    concept_l = (concept or "sales").lower()
    if any(k in concept_l for k in ("quant", "qty", "volume", "units")):
        return bool(names & {"fkimg", "menge", "kwmeng"})
    if any(k in concept_l for k in ("count", "how many", "number")):
        return bool(names & {"vbeln", "belnr", "ebeln"}) or not table_is_master(table)
    return bool(names & {"netwr", "dmbtr", "wrbtr", "rmwwr", "kwert"})


_NUM_MAG = r"(?:₹|rs\.?\s*)?(\d+(?:\.\d+)?)\s*(k|thousand|lakh|lakhs|crore|crores|million)?"
_MAGNITUDE = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "lakh": 100_000.0,
    "lakhs": 100_000.0,
    "crore": 10_000_000.0,
    "crores": 10_000_000.0,
    "million": 1_000_000.0,
}


def _threshold_value(match: re.Match[str]) -> float:
    n = float(match.group(1))
    mag = (match.group(2) or "").lower()
    return n * _MAGNITUDE.get(mag, 1.0)


def _extract_measure_comparison(ql: str) -> Optional[Dict[str, Any]]:
    """Language → comparison predicate on the selected numeric measure.

    Operators are generic (NEGATIVE/POSITIVE/ZERO/thresholds). Not a question map.
    """
    if re.search(r"\b(negative|negatives|below zero|less than zero|loss-making)\b", ql):
        return {"kind": "NEGATIVE", "operator": "<", "value": 0}
    if re.search(r"\b(positive|above zero|greater than zero)\b", ql):
        return {"kind": "POSITIVE", "operator": ">", "value": 0}
    if re.search(r"\b(zero[- ]value|equal to zero|amounts? of zero|zero amounts?)\b", ql):
        return {"kind": "ZERO", "operator": "=", "value": 0}
    if re.search(r"\bnon[- ]zero\b", ql):
        return {"kind": "NON_ZERO", "operator": "!=", "value": 0}
    # Distinct-entity language is not a measure threshold ("more than 1 country").
    if re.search(
        r"\bmore than\s+(?:one|1|two|2|three|3|\d+)\s+"
        r"(?:countr|customer|client|vendor|supplier|plant|material|product|different)",
        ql,
    ):
        return None
    m = re.search(
        rf"\b(?:greater than or equal to|at least|no less than)\s+{_NUM_MAG}\b",
        ql,
    )
    if m:
        return {"kind": "GREATER_OR_EQUAL", "operator": ">=", "value": _threshold_value(m)}
    m = re.search(
        rf"\b(?:less than or equal to|at most|no more than)\s+{_NUM_MAG}\b",
        ql,
    )
    if m:
        return {"kind": "LESS_OR_EQUAL", "operator": "<=", "value": _threshold_value(m)}
    m = re.search(rf"\b(?:below|under|less than|fewer than)\s+{_NUM_MAG}\b", ql)
    if m:
        return {"kind": "LESS_THAN", "operator": "<", "value": _threshold_value(m)}
    m = re.search(rf"\b(?:above|over|greater than|more than)\s+{_NUM_MAG}\b", ql)
    if m:
        return {"kind": "GREATER_THAN", "operator": ">", "value": _threshold_value(m)}
    return None


def extract_analytical_operations(question: str) -> Dict[str, Any]:
    """Language → structured operations. Independent of any specific question string."""
    q = (question or "").strip()
    # Recover common missing spaces before entity nouns (for example,
    # "theproduct") without changing user-visible text or SQL literals.
    ql = re.sub(
        r"\b(the|a|an)(?=(?:products?|materials?|customers?|clients?|countries?|invoices?|orders?)\b)",
        r"\1 ",
        q.lower(),
    )
    ops: Dict[str, Any] = {
        "group_by": [],
        "aggregation": None,
        "ranking": None,
        "limit": None,
        "order": None,
        "time_grain": None,
        "share": False,
        "growth": False,
        "trend": False,
        "compare": False,
        "measure_concept": None,
        "negative_measure": False,
        "negation": None,
        "period_compare": None,
        "relative_period": None,
        "partition_by": [],
    }

    group_by: List[str] = []
    # "Customer country" names an attribute, whereas "customer and country"
    # names two dimensions. Do not turn the possessive/qualifying noun into an
    # additional grouping key.
    group_ql = re.sub(r"\bcustomer(?:'s)?\s+(country|industry|region)\b", r"\1", ql)
    for pat, dim in _GROUP_PATTERNS:
        if re.search(pat, group_ql):
            if dim not in group_by:
                group_by.append(dim)
    # A coordinated dimension list must not stop at the first noun after "by".
    dimension_words = {**_ENTITY_WORDS, "sector": "industry", "sectors": "industry",
                       "month": "month", "months": "month", "year": "year", "years": "year",
                       "quarter": "quarter", "quarters": "quarter", "currency": "currency", "currencies": "currency"}
    entity_pattern = "(?:" + "|".join(sorted(dimension_words, key=len, reverse=True)) + ")"
    list_pattern = rf"\b(?:by|per|for each|with)\s+({entity_pattern}(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*|/\s*){entity_pattern})*)\b"
    for clause in re.finditer(list_pattern, group_ql):
        for word in re.findall(r"\b" + entity_pattern + r"\b", clause.group(1)):
            dim = dimension_words[word]
            if dim not in group_by:
                group_by.append(dim)
    which = _WHICH_ENTITY.search(q)
    if which:
        ent = _ENTITY_WORDS.get(which.group(1).lower())
        if ent and ent not in group_by and re.search(
            r"\b(most|highest|largest|top|lowest|least|best|worst|generated|contributed|increased|decreased)\b",
            ql,
        ):
            group_by.append(ent)
    # Generic noun-first ranking: "show the product with the highest profit"
    # expresses the same result grain as "which product is most profitable".
    ranked_entity = re.search(
        r"\b(?:show|list|find|display|identify)\s+(?:the\s+)?"
        r"(customers?|clients?|buyers?|countries?|materials?|products?|suppliers?|vendors?|industries?)\b"
        r"[\s\S]{0,100}\b(?:highest|lowest|largest|smallest|most|least|best|worst|top|bottom)\b",
        ql,
    )
    if ranked_entity:
        entity = _ENTITY_WORDS.get(ranked_entity.group(1).lower(), ranked_entity.group(1).lower().rstrip("s"))
        if entity not in group_by:
            group_by.append(entity)
    ops["group_by"] = group_by
    if "month" in group_by:
        ops["time_grain"] = "month"
    elif "quarter" in group_by:
        ops["time_grain"] = "quarter"
    elif "year" in group_by:
        ops["time_grain"] = "year"

    if re.search(r"\b(count|how many|number of)\b", ql):
        ops["aggregation"] = "COUNT"
    elif re.search(r"\b(average|avg|mean)\b", ql):
        ops["aggregation"] = "AVG"
    elif re.search(r"\b(sum of|grand total|overall total)\b", ql) or (
        re.search(r"\b(total|sum)\b", ql) and not re.search(r"\b(show|list|display|with)\b", ql)
    ):
        ops["aggregation"] = "SUM"

    if re.search(r"\b(gross\s+)?profits?\b|\bprofitability\b|\bgross\s+margin\b", ql):
        ops["measure_concept"] = "gross_profit"
    elif re.search(r"\b(revenue|turnover|billed amount|billing amount|billed value|invoice value|billed sales)\b", ql):
        ops["measure_concept"] = "revenue"
    elif re.search(
        r"\b((money|cash)\s+(generated|made|earned|brought in)|"
        r"brought in|business\s+generat\w+|generat\w+\s+during)\b",
        ql,
    ):
        ops["measure_concept"] = "revenue"
    elif re.search(r"\b(quantit(?:y|ies)|qty|billed quantity)\b", ql):
        ops["measure_concept"] = "quantity"
    elif re.search(r"\b(sales orders?|sales documents?)\b", ql) and ops["aggregation"] == "COUNT":
        ops["measure_concept"] = "sales_order"
    elif re.search(r"\b(sales|sold|sell|selling)\b", ql):
        ops["measure_concept"] = "sales"
    elif ops["aggregation"] == "COUNT":
        ops["measure_concept"] = "count"

    # A combined metric request needs both aggregates. A COUNT cue must not
    # replace the requested monetary/quantity total merely because it appears
    # in the same sentence.
    if (
        re.search(r"\b(count|how many|number of)\b", ql)
        and re.search(r"\b(total|sum|combined|aggregate)\b", ql)
        and ops.get("measure_concept") in {"sales", "revenue", "quantity"}
    ):
        ops["aggregation"] = "SUM"
        ops["aggregations"] = ["SUM", "COUNT"]

    part = _PARTITION_RANK.search(ql)
    if part:
        n = int(part.group(1))
        dim = _ENTITY_WORDS.get(part.group(2).lower(), part.group(2).lower())
        direction = "ASC" if re.search(r"\b(bottom|lowest|least|smallest|worst)\b", ql) else "DESC"
        ops["ranking"] = {"direction": direction, "limit": n, "partition_by": [dim]}
        ops["partition_by"] = [dim]
        ops["limit"] = n
        ops["order"] = direction
        if dim not in group_by:
            group_by.append(dim)
            ops["group_by"] = group_by
        if not ops["aggregation"]:
            ops["aggregation"] = "SUM"
    else:
        part2 = _PARTITION_EACH.search(ql)
        # "one row per X" describes result grain; it does not request a
        # top-N window inside each X. The broad wording on either side of the
        # ranking verb must not turn a later row-grain phrase into a partition.
        row_grain = re.search(r"\bone\s+row\s+per\s+(\w+)", ql)
        if part2 and row_grain:
            partition = _ENTITY_WORDS.get(part2.group(1).lower(), part2.group(1).lower())
            row_entity = _ENTITY_WORDS.get(
                row_grain.group(1).lower(), row_grain.group(1).lower().rstrip("s")
            )
            if partition == row_entity:
                part2 = None
        if part2:
            dim = _ENTITY_WORDS.get(part2.group(1).lower(), part2.group(1).lower())
            direction = "ASC" if re.search(r"\b(bottom|lowest|least|smallest|worst)\b", ql) else "DESC"
            # Unspecified N for "top X in each Y" defaults to a small per-partition window.
            lim = 5
            ops["ranking"] = {"direction": direction, "limit": lim, "partition_by": [dim]}
            ops["partition_by"] = [dim]
            ops["limit"] = lim
            ops["order"] = direction
            if dim not in group_by:
                group_by.append(dim)
                ops["group_by"] = group_by
            if not ops["aggregation"]:
                ops["aggregation"] = "SUM"

    m = _TOP_N.search(ql)
    if not m:
        m = _RANKED_SET_COUNT.search(ql)
    if m and not ops.get("ranking"):
        raw_n = m.group(1).lower()
        n = _NUMBER_WORDS.get(raw_n, int(raw_n) if raw_n.isdigit() else 10)
        most_negative = bool(re.search(r"\b(most|lowest|largest|biggest)\s+negative\b", ql))
        least_negative = bool(re.search(r"\b(least|highest|smallest|closest)\s+negative\b", ql))
        direction = (
            "DESC" if least_negative else
            "ASC" if most_negative or re.search(r"\b(bottom|lowest|least|smallest|worst)\b", ql) else
            "DESC"
        )
        ops["ranking"] = {"direction": direction, "limit": n}
        ops["limit"] = n
        ops["order"] = direction
        if not ops["aggregation"]:
            ops["aggregation"] = "SUM"
    elif not ops.get("ranking"):
        # Paraphrases: "five customers … most revenue", "biggest customers by sales"
        _WORD_N = {
            "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        wm = re.search(
            r"\b(two|three|four|five|six|seven|eight|nine|ten|\d{1,3})\s+"
            r"(?:(?:biggest|largest|top|best|highest)\s+)?"
            r"(customers?|clients?|buyers?|vendors?|suppliers?|products?|materials?|countries)\b",
            ql,
        )
        if wm and re.search(
            r"\b(most|biggest|largest|highest|brought in|revenue|sales|top)\b",
            ql,
        ):
            raw = wm.group(1)
            n = int(_WORD_N.get(raw, raw if str(raw).isdigit() else 5))
            ent = _ENTITY_WORDS.get(wm.group(2).lower(), wm.group(2).lower().rstrip("s"))
            if ent.endswith("ie"):  # countries → countr already mapped
                pass
            ops["ranking"] = {"direction": "DESC", "limit": n}
            ops["limit"] = n
            ops["order"] = "DESC"
            if ent in _ENTITY_WORDS.values() and ent not in group_by:
                group_by.append(ent)
                ops["group_by"] = group_by
            if not ops["aggregation"]:
                ops["aggregation"] = "SUM"
            if not ops.get("measure_concept"):
                ops["measure_concept"] = "sales"
        elif re.search(r"\b(biggest|largest)\s+(customers?|clients?|vendors?)\b", ql) and re.search(
            r"\b(sales|revenue|by)\b", ql
        ):
            ops["ranking"] = {"direction": "DESC", "limit": 10}
            ops["limit"] = 10
            ops["order"] = "DESC"
            if "customer" not in group_by and re.search(r"\b(customers?|clients?)\b", ql):
                group_by.append("customer")
                ops["group_by"] = group_by
            if not ops["aggregation"]:
                ops["aggregation"] = "SUM"
            if not ops.get("measure_concept"):
                ops["measure_concept"] = "sales"
        elif re.search(r"\b(highest|most|best|largest|top)\b", ql):
            # Singular "which X … most/highest" or "top country/customer" ⇒ top-1.
            singular = bool(
                re.search(
                    r"\bwhich\s+(country|customer|client|buyer|material|product|supplier|vendor|industry)\b",
                    ql,
                )
            ) or bool(
                re.search(
                    r"\btop\s+(country|customer|client|buyer|material|product|supplier|vendor|industry)\b",
                    ql,
                )
            )
            plural_list = bool(
                re.search(
                    r"\b(customers|clients|buyers|countries|materials|products|suppliers|vendors|industries)\b",
                    ql,
                )
            )
            lim = 10 if plural_list and not singular else (1 if singular else 10)
            ops["ranking"] = {"direction": "DESC", "limit": lim}
            ops["limit"] = lim
            ops["order"] = "DESC"
            if not ops["aggregation"]:
                ops["aggregation"] = "SUM"
        elif re.search(r"\b(lowest|least|smallest|worst|bottom)\b", ql):
            singular = bool(
                re.search(
                    r"\bwhich\s+(country|customer|client|buyer|material|product|supplier|vendor|industry)\b",
                    ql,
                )
            )
            lim = 1 if singular else 10
            ops["ranking"] = {"direction": "ASC", "limit": lim}
            ops["limit"] = lim
            ops["order"] = "ASC"

    # A request for the most negative values orders ascending on the measure:
    # the sign of the threshold alone does not determine ranking direction.
    if isinstance(ops.get("ranking"), dict):
        if re.search(r"\b(most|lowest|largest|biggest)\s+negative\b", ql):
            ops["ranking"]["direction"] = "ASC"
            ops["order"] = "ASC"
        elif re.search(r"\b(least|highest|smallest|closest)\s+negative\b", ql):
            ops["ranking"]["direction"] = "DESC"
            ops["order"] = "DESC"
        if re.search(r"\b(?:show|list|find|display|identify)\s+(?:the\s+)?(?:product|material|customer|client|country|vendor|supplier)\b", ql):
            # Singular noun phrase plus a superlative requests one entity.
            ops["ranking"]["limit"] = 1
            ops["limit"] = 1
        # The ranked noun determines the output grain. A customer named later
        # as a filter must not turn a document ranking into a customer total.
        if re.search(
            r"\b(?:top|bottom|highest|lowest|most|least|largest|smallest)\s+"
            r"(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?(?:negative\s+)?"
            r"(?:(?:billing|billed|sales|purchase)\s+)?(?:documents?|invoices?|orders?)\b",
            ql,
        ):
            ops["group_by"] = ["document"]
            group_by = ops["group_by"]

        # An explicit request for invoice/document identifiers is a row-grain
        # request even when the ranking words describe the amount ("lowest
        # negative sales") and the identifier appears later in the prompt.
        # Keep this separate from an invoice count or an aggregate by customer.
        asks_for_document_identifier = bool(
            re.search(
                r"\b(?:billing\s+)?(?:documents?|invoices?)\s+"
                r"(?:numbers?|ids?|identifiers?)\b|"
                r"\b(?:document|invoice)\s+(?:numbers?|ids?|identifiers?)\b",
                ql,
            )
        )
        if asks_for_document_identifier:
            ops["group_by"] = ["document"]
            group_by = ops["group_by"]

    # In a drill-down such as "For the higher-sales country, show monthly sales",
    # the superlative selects the antecedent entity; the requested monthly series
    # is not itself a ranking. Keep actual ranking requests (for example, "top 5
    # months for the highest-sales country") intact.
    if (
        _CONTEXTUAL_SUPERLATIVE_ENTITY.search(ql)
        and any(grain in group_by for grain in ("month", "quarter", "year"))
    ):
        # A leading superlative entity can act as a filter/anchor for the
        # requested time series ("for the highest-value invoice, show its
        # customer's monthly sales"). It is not another output grain.
        if ops.get("ranking"):
            ops["ranking"] = None
            ops["limit"] = None
            ops["order"] = None
            ops["partition_by"] = []
        if "document" in group_by:
            group_by = [grain for grain in group_by if grain != "document"]
            ops["group_by"] = group_by

    if ops.get("group_by") and ops.get("measure_concept") and not ops.get("aggregation"):
        ops["aggregation"] = "SUM"

    if re.search(r"\b(share|percentage of total|percent of total|% of)\b", ql):
        ops["share"] = True
    if re.search(
        r"\b(share of (the )?(revenue |sales )?(decline|decrease|drop|change)|"
        r"largest share|accounted for .{0,40}(decline|decrease|drop))\b",
        ql,
    ):
        ops["share"] = True
        ops["contribution"] = True
        ops["growth"] = True
    if re.search(r"\b(growth|increase|decrease|decline|change|difference|delta)\b", ql):
        ops["growth"] = True
    if re.search(
        r"\b(trend|month by month|monthly|how .{0,60} (moved|changed|evolved)|over (the )?years?|over time)\b",
        re.sub(r"\byear[- ]over[- ]year\b", "", ql),
    ):
        ops["trend"] = True
        if not ops["time_grain"]:
            ops["time_grain"] = "month"
            if "month" not in group_by:
                group_by.append("month")
                ops["group_by"] = group_by
    if re.search(r"\b(compar\w*|versus|vs\.?|better than|worse than)\b", ql):
        ops["compare"] = True
    # Polarity/threshold predicates are applied below as generic comparisons.

    years = _YEAR.findall(q)
    if years:
        ops["years"] = sorted(set(years))

    _decline_cue = r"\b(declin\w*|decreas\w*|drop(?:ped|s)?|reduc\w*|fell|falling|falls?|fallen|worse)\b"
    _growth_cue = r"\b(growth|increas\w*|grew|better)\b"
    _contribution_cue = bool(
        re.search(
            r"\b(contribut\w*|drove|driving|accounted for|responsible for|"
            r"why\s+did|what\s+caused|what\s+changed|that\s+caused|"
            r"drivers?\s+of|caused\s+the\s+(drop|decline|decrease))\b",
            ql,
        )
    )
    if _contribution_cue and (
        re.search(r"\b(revenue|sales|billing|invoice)\b", ql)
        or re.search(_decline_cue + r"|" + _growth_cue, ql)
        or re.search(r"\b(drop|decline|decrease|change)\b", ql)
    ):
        ops["contribution"] = True
        ops["growth"] = True
        if not group_by:
            # Default driver grain: customers unless another entity is named.
            if re.search(r"\b(materials?|products?)\b", ql):
                group_by.append("material")
            elif re.search(r"\bcountr", ql):
                group_by.append("country")
            else:
                group_by.append("customer")
            ops["group_by"] = group_by
        if not ops.get("measure_concept"):
            ops["measure_concept"] = "sales"
        if not ops.get("aggregation"):
            ops["aggregation"] = "SUM"

    from .comparison_scope import cross_source_years
    source_years = cross_source_years(question)
    if source_years:
        ops['cross_source_years'] = source_years
        ops['period_compare'] = None
        ops['growth'] = False
        if not group_by:
            group_by.append('year')
            ops['group_by'] = group_by
    explicit_year_series = bool(source_years) or bool(
        "year" in group_by
        and re.search(r"\b(?:by|per|each)\s+(?:(?:calendar|fiscal)\s+)?years?\b|\byearly\b", ql)
    )
    if years and len(set(years)) >= 2 and not explicit_year_series and (
        re.search(
            r"\b(growth|increas\w*|decreas\w*|declin\w*|between|versus|vs\.?|compar\w*|"
            r"difference|change|yoy|year[- ]over[- ]year|better|worse|contribut)\b",
            ql,
        )
        or ops.get("contribution")
    ):
        ordered = sorted(set(years))
        decline = bool(re.search(_decline_cue, ql)) and not re.search(
            r"\b(increas\w*|grew|growth)\b", ql
        )
        increase = bool(re.search(_growth_cue, ql)) and not decline
        direction = "decline" if decline else "growth" if increase else "compare"
        asks_for_both_changes = bool(
            re.search(r"\bboth\b", ql)
            and re.search(r"\babsolute\b", ql)
            and re.search(r"\b(percent|percentage|%)\b", ql)
        )
        ops["period_compare"] = {
            "type": "period_change",
            "base_period": {"year": ordered[0], "start": ordered[0], "end": ordered[0]},
            "comparison_period": {"year": ordered[-1], "start": ordered[-1], "end": ordered[-1]},
            "op": direction,
            "condition": "decreased" if decline else "increased" if increase else None,
            "calculation": (
                "both"
                if asks_for_both_changes
                else "percentage_change"
                if re.search(r"\b(percent|percentage|%|pct)\b", ql)
                else "difference"
            ),
            "contribution": bool(ops.get("contribution")),
        }
        ops["compare"] = True
        ops["growth"] = True
        if "year" in group_by and which:
            group_by = [g for g in group_by if g != "year"]
            ops["group_by"] = group_by
        if ops.get("contribution") and not ops.get("ranking"):
            ops["ranking"] = {
                "direction": "ASC" if decline else "DESC",
                "limit": int(ops.get("limit") or 10),
            }
        elif ops.get("contribution") and isinstance(ops.get("ranking"), dict):
            # Keep explicit top-N (e.g. three customers) but align sort to decline/growth.
            ops["ranking"]["direction"] = "ASC" if decline else "DESC"

    elif len(set(years)) == 1 and (
        ops.get("contribution")
        or re.search(r"\b(why\s+did|what\s+caused)\b", ql)
    ) and re.search(r"\b(revenue|sales)\b", ql) and re.search(
        _decline_cue + r"|" + _growth_cue, ql
    ):
        # "Why did revenue decrease in 2025?" → resolve prior year at plan time.
        decline = bool(re.search(_decline_cue, ql))
        y = sorted(set(years))[0]
        ops["period_compare"] = {
            "type": "period_change",
            "requires_two_periods": True,
            "comparison_period": {"year": y, "start": y, "end": y},
            "op": "decline" if decline else "growth",
            "condition": "decreased" if decline else "increased",
            "calculation": "difference",
            "contribution": True,
            "investigation": True,
            "anchor_year": y,
        }
        ops["compare"] = True
        ops["growth"] = True
        ops["contribution"] = True
        ops.pop("clarification", None)
        if not group_by:
            group_by.append("customer")
            ops["group_by"] = group_by
        if not ops.get("ranking"):
            ops["ranking"] = {"direction": "ASC" if decline else "DESC", "limit": 10}
        if not ops.get("measure_concept"):
            ops["measure_concept"] = "sales"
        if not ops.get("aggregation"):
            ops["aggregation"] = "SUM"

    elif not years and (
        re.search(r"\b(year[- ]over[- ]year|yoy)\b", ql)
        or (
            ops.get("contribution")
            or re.search(r"\b(why\s+did|what\s+caused)\b", ql)
        )
        and re.search(r"\b(revenue|sales)\b", ql)
        and re.search(_decline_cue + r"|" + _growth_cue, ql)
    ):
        # Explicit YoY OR clear investigation without years → resolve latest two years at plan time.
        decline = bool(re.search(_decline_cue, ql))
        ops["period_compare"] = {
            "type": "period_change",
            "requires_two_periods": True,
            "op": "decline" if decline else "growth",
            "condition": "decreased" if decline else "increased",
            "calculation": "difference",
            "contribution": bool(ops.get("contribution") or re.search(r"\b(why|caused|contribut)\b", ql)),
            "investigation": True,
        }
        ops["compare"] = True
        ops["growth"] = True
        ops["contribution"] = True
        ops.pop("clarification", None)
        if not group_by:
            group_by.append("customer")
            ops["group_by"] = group_by
        if not ops.get("ranking"):
            ops["ranking"] = {"direction": "ASC" if decline else "DESC", "limit": 10}
        if not ops.get("measure_concept"):
            ops["measure_concept"] = "sales"
        if not ops.get("aggregation"):
            ops["aggregation"] = "SUM"
    elif ops.get("growth") and not years and not ops.get("contribution") and re.search(
        r"\b(sales growth|revenue growth|highest sales growth|grew|growth)\b",
        ql,
    ):
        # Ambiguous comparison periods must not invent years — ask for clarification.
        ops["clarification"] = {
            "type": "comparison_period",
            "message": (
                "Which periods should I compare for growth "
                "(for example 2004 vs 2005, or the latest two calendar years)?"
            ),
        }
        ops["compare"] = True
        ops["period_compare"] = None
    elif (
        ops.get("compare")
        and years
        and len(set(years)) >= 2
        and not ops.get("period_compare")
        and not explicit_year_series
    ):
        ordered = sorted(set(years))
        ops["period_compare"] = {
            "type": "period_change",
            "base_period": {"year": ordered[0]},
            "comparison_period": {"year": ordered[-1]},
            "op": "growth",
            "condition": "increased",
            "calculation": "difference",
        }

    # A billing document is one dated fact. Comparing the same invoice rows
    # across two calendar years is undefined, so ask for a comparable business
    # grain instead of generating an unrelated customer-count query.
    period = ops.get("period_compare")
    if (
        isinstance(period, dict)
        and "document" in (ops.get("group_by") or [])
        and re.search(
            r"\bsame\s+(?:(?:billing|billed)\s+)?(?:documents?|invoices?)\s+"
            r"(?:in|for|during|across|between|from)\s+(?:the\s+)?(?:calendar\s+)?(?:year\s+)?(?:\d{4}|years?\b|periods?\b)",
            ql,
        )
    ):
        base = period.get("base_period") if isinstance(period.get("base_period"), dict) else {}
        compare = period.get("comparison_period") if isinstance(period.get("comparison_period"), dict) else {}
        year_a = str(base.get("year") or "the first year")
        year_b = str(compare.get("year") or "the second year")
        ops["clarification"] = {
            "type": "document_period_comparison",
            "entity_grain": "document",
            "message": (
                f"Each billing document has one billing date, so the same invoice cannot have separate "
                f"{year_a} and {year_b} amounts. Should I keep the negative invoice list from {year_a} "
                f"and compare billed totals for those customers across {year_a} and {year_b}?"
            ),
        }

    if re.search(r"\b(above|over|greater than|higher than)\s+(?:the\s+)?average\b", ql):
        ops["comparison_filter"] = {"type": "above_average"}
    elif re.search(r"\b(below|under|less than)\s+(?:the\s+)?average\b", ql):
        ops["comparison_filter"] = {"type": "below_average"}
    else:
        cmp = _extract_measure_comparison(ql)
        if cmp:
            ops["comparison"] = cmp
            ops["comparison_filter"] = {
                "type": "measure_predicate",
                "kind": cmp["kind"],
                "operator": cmp["operator"],
                "value": cmp["value"],
            }
            if cmp["operator"] == "<" and cmp["value"] == 0:
                ops["negative_measure"] = True
            # Row-level predicates are filters, not aggregations, unless ranked/totalled.
            if not re.search(r"\b(total|sum of|aggregate|combined|how many)\b", ql):
                if not ops.get("ranking") and not re.search(r"\b(top|bottom|highest|lowest|largest|smallest|least|best|worst|rank|most)\b", ql):
                    ops["aggregation"] = "none"
                    ops["ranking"] = None
                    ops["limit"] = None
                    ops["order"] = None

    # Generic multi-entity DISTINCT dimension filter (e.g. customers in >1 country).
    _having_m = re.search(
        r"\bmore than\s+(one|1|two|2|three|3|\d+)\b|\bmultiple\b",
        ql,
    )
    if _having_m or re.search(r"\b(across|different|more than one)\s+countr", ql):
        ent = None
        if re.search(r"\b(customers?|clients?|buyers?)\b", ql):
            ent = "customer"
        elif re.search(r"\b(vendors?|suppliers?)\b", ql):
            ent = "vendor"
        dim = None
        if re.search(r"\b(countr(?:y|ies)|nations?|markets?)\b", ql):
            dim = "country"
        if ent and dim:
            words = {"one": 1, "1": 1, "two": 2, "2": 2, "three": 3, "3": 3}
            thr = 1
            if _having_m:
                raw = (_having_m.group(1) or "1").lower()
                thr = int(words.get(raw, raw if str(raw).isdigit() else 1))
            grain = (
                "transaction"
                if re.search(
                    r"\b(bought|buy|purchased|sold|billed|invoice|order|shipped|delivered|activity)\b",
                    ql,
                )
                else "auto"
            )
            ops["having_distinct"] = {
                "entity": ent,
                "dimension": dim,
                "op": ">",
                "threshold": thr,
                "grain": grain,
            }
            if ent not in group_by:
                group_by.append(ent)
                ops["group_by"] = group_by
            # Do not treat as revenue ranking.
            if not re.search(r"\b(highest|lowest|most|least|top|bottom)\b", ql):
                ops["ranking"] = None
                ops["aggregation"] = "COUNT"

    # Undefined qualitative thresholds → structured clarification (never invent cutoffs).
    try:
        from .threshold_semantics import merge_threshold_ops

        merge_threshold_ops(ops, q)
    except Exception:
        pass

    # Retaining unmatched entities in a comparison is outer-join semantics,
    # not a request to filter the result down to absent relationships.
    inclusive_absence = re.search(
        r"\b(?:include|including|retain|retaining|preserve|preserving)\b[^.;]{0,100}"
        r"\b(?:no|without|missing)\b", ql
    )
    if _NEGATION.search(ql) and not inclusive_absence:
        neg = {"type": "anti_join"}
        if re.search(r"sales orders?.{0,60}(no|without|not|but no).{0,30}(billing|invoices?)", ql):
            neg.update({"required": "sales_order", "forbidden": "invoice"})
        elif re.search(r"invoices?.{0,60}(no|without|not|but no).{0,30}sales orders?", ql):
            neg.update({"required": "invoice", "forbidden": "sales_order"})
        elif re.search(r"purchase orders?.{0,60}(no|without|not|but no).{0,30}invoices?", ql) or re.search(
            r"\borders?\b.{0,40}\b(no|without|but no)\b.{0,30}\binvoices?\b", ql
        ):
            neg.update({"required": "purchase_order", "forbidden": "invoice"})
        elif re.search(r"invoices?.{0,60}(no|without|not|but no).{0,30}(orders?|payments?)", ql):
            neg.update({"required": "invoice", "forbidden": "purchase_order"})
        elif re.search(r"activity.{0,40}(without|no).{0,20}billing", ql):
            neg.update({"required": "purchase_order", "forbidden": "invoice"})
        ops["negation"] = neg

    for pat, name in _RELATIVE_PERIODS:
        if re.search(pat, ql):
            ops["relative_period"] = name
            break
    recent = _LATEST_DATA_YEARS.search(ql)
    if recent:
        raw_count = (recent.group(1) or "1").lower()
        count = _NUMBER_WORDS.get(raw_count, int(raw_count) if raw_count.isdigit() else 1)
        ops["relative_period"] = "latest_two_full_years" if count == 2 else "latest_full_year"
        ops["relative_period_count"] = max(1, min(count, 50))

    return ops


def merge_semantic_requirements(
    question: str, llm_req: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Fill gaps in LLM semantic JSON using generic analytical operations."""
    ql = (question or "").lower()
    req = dict(llm_req or {})
    ops = extract_analytical_operations(question)
    req["analytical_operations"] = ops

    dims = [str(d).lower() for d in (req.get("dimensions") or []) if str(d).strip()]
    for dim in ops.get("group_by") or []:
        if dim not in dims:
            dims.append(dim)
    explicit_groups = list(ops.get("group_by") or [])
    # The generic parser owns result grain when it found explicit grouping.
    # Otherwise an LLM default such as customer/year can silently turn a total
    # into a detailed breakdown, so clear dimensions for aggregate questions.
    if explicit_groups:
        dims = explicit_groups
    elif ops.get("period_compare") or ops.get("aggregation") in {"SUM", "COUNT", "AVG"}:
        dims = []
    req["dimensions"] = dims
    req["group_by"] = explicit_groups

    measure = req.get("measure") if isinstance(req.get("measure"), dict) else {}
    concept = str(ops.get("measure_concept") or measure.get("concept") or "").strip()
    agg = str(ops.get("aggregation") or measure.get("aggregation") or "").strip()
    if ops.get("aggregation") == "COUNT":
        agg = "COUNT"
        if not concept:
            concept = str(ops.get("measure_concept") or "count")
    req["measure"] = {"concept": concept or measure.get("concept") or "", "aggregation": agg}
    req["aggregations"] = list(ops.get("aggregations") or ([agg.upper()] if agg else []))

    ranking = req.get("ranking") if isinstance(req.get("ranking"), dict) else None
    if isinstance(ranking, dict) and not (
        ranking.get("limit") or ranking.get("direction") or ranking.get("partition_by")
    ):
        ranking = None
        req.pop("ranking", None)
    if ops.get("ranking") and not ranking:
        req["ranking"] = dict(ops["ranking"])
    elif ops.get("ranking") and ranking:
        # Explicitly parsed ranking words and counts are more reliable than an
        # LLM-inferred default such as top 10 for "five countries ... highest".
        ranking["direction"] = ops["ranking"]["direction"]
        ranking["limit"] = ops["ranking"]["limit"]
        if ops["ranking"].get("partition_by"):
            ranking["partition_by"] = list(ops["ranking"]["partition_by"])
        else:
            ranking.pop("partition_by", None)
        req["ranking"] = ranking
    elif not re.search(
        r"\b(highest|lowest|largest|smallest|top|bottom|most|least|best|worst)\b",
        ql,
    ):
        # Discard unsupported model-inferred ranking defaults (for example a
        # top-10 limit on an ungrouped year-over-year total).
        req.pop("ranking", None)

    if ops.get("partition_by"):
        req["partition_by"] = list(ops["partition_by"])
    if ops.get("negation"):
        req["negation"] = dict(ops["negation"])
    if ops.get("period_compare"):
        req["period_compare"] = dict(ops["period_compare"])
    elif ops.get('cross_source_years'):
        req.pop('period_compare', None)
    if ops.get("contribution"):
        req["contribution"] = True
        if isinstance(req.get("period_compare"), dict):
            req["period_compare"]["contribution"] = True
    if ops.get("clarification"):
        req["clarification"] = dict(ops["clarification"])
    if ops.get("having_distinct"):
        req["having_distinct"] = dict(ops["having_distinct"])
    if ops.get("threshold_definitions"):
        req["threshold_definitions"] = list(ops["threshold_definitions"])
    if ops.get("comparison_filter"):
        req["comparison_filter"] = dict(ops["comparison_filter"])
    if ops.get("comparison"):
        req["comparison"] = dict(ops["comparison"])
        condition = req.get("condition") if isinstance(req.get("condition"), dict) else {}
        condition.setdefault("measure_operator", ops["comparison"]["operator"])
        condition.setdefault("measure_value", ops["comparison"]["value"])
        req["condition"] = condition
        if str(ops.get("aggregation") or "").lower() == "none":
            req["measure"]["aggregation"] = "none"
            if not ops.get("ranking"):
                req.pop("ranking", None)
    if ops.get("relative_period"):
        tf = req.get("time_filter") if isinstance(req.get("time_filter"), dict) else {}
        same_period = tf.get("relative") == ops["relative_period"]
        tf["relative"] = ops["relative_period"]
        if ops.get("relative_period_count"):
            tf["count"] = ops["relative_period_count"]
        # Retain bounds produced by the database resolver when subsequent
        # validation merges the same requirement again. Unverified LLM bounds
        # still need to be discarded before resolving the period.
        if not (same_period and tf.get("resolved_from_data") is True):
            for k in ("start", "end", "start_yyyymmdd", "end_yyyymmdd", "value", "years"):
                tf.pop(k, None)
        req["time_filter"] = tf

    if ops.get("negative_measure"):
        condition = req.get("condition") if isinstance(req.get("condition"), dict) else {}
        condition.setdefault("measure_operator", "<")
        condition.setdefault("measure_value", 0)
        req["condition"] = condition
        req["measure"]["aggregation"] = req["measure"].get("aggregation") or "none"

    if ops.get("years") and not ops.get("period_compare") and len(ops.get("years") or []) == 1:
        req["time_filter"] = {
            "type": "calendar_year",
            "concept": "year",
            "grain": "year",
            "operator": "equals",
            "value": ops["years"][0],
            "years": list(ops["years"]),
        }

    if ops.get("time_grain") and not req.get("time_filter"):
        req["time_grain"] = ops["time_grain"]
    elif ops.get("time_grain"):
        req["time_grain"] = ops["time_grain"]

    # A date field used to derive a calendar grain is not an additional
    # grouping dimension. Remove date-shaped LLM guesses while retaining the
    # explicit entities that the generic phrase parser found.
    if ops.get("time_grain") in {"year", "month", "quarter"}:
        explicit = set(ops.get("group_by") or [])
        dimensions = [
            str(dim).lower() for dim in (req.get("dimensions") or [])
            if str(dim).lower() in explicit
            or not (
                str(dim).lower() in _DATE_COLS
                or re.search(r"\b(date|time|year|month|quarter)\b", str(dim).lower())
            )
        ]
        for dim in explicit:
            if dim not in dimensions:
                dimensions.append(dim)
        req["dimensions"] = dimensions

    # A comparison of two periods without a named entity is a company-level
    # comparison. Do not let an inferred default turn totals into a customer
    # or product breakdown.
    if ops.get("period_compare") and not ops.get("group_by") and not ops.get("contribution"):
        explicit_entities = any(
            re.search(rf"\b{re.escape(word)}\b", ql)
            for word in _ENTITY_WORDS
        )
        if not explicit_entities:
            req["dimensions"] = []
            req["group_by"] = []

    req["share"] = bool(ops.get("share"))
    req["growth"] = bool(ops.get("growth"))
    req["trend"] = bool(ops.get("trend"))
    return req


def find_measure_table(tables: List[str], concept: str) -> Optional[str]:
    for tbl in tables:
        if has_table(tbl) and table_has_measure_columns(tbl, concept) and not table_is_master(tbl):
            return resolve_table_name(tbl) or tbl
    return None


def find_date_column_in_tables(tables: List[str]) -> Optional[Tuple[str, str]]:
    for tbl in tables:
        if not has_table(tbl):
            continue
        for c in column_names(tbl) or []:
            if c.lower() in _DATE_COLS:
                return resolve_table_name(tbl) or tbl, c
    return None
