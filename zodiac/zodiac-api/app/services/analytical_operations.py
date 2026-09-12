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
    (r"\b(by|per|each|for each)\s+months?\b|\bmonthly\b", "month"),
    (r"\b(by|per|each|for each)\s+years?\b|\byearly\b|\bannually\b|\bannual\b|\beach year\b", "year"),
    (r"\b(by|per|each|for each)\s+quarters?\b|\bquarterly\b", "quarter"),
    (r"\b(by|per|each|for each)\s+countr(?:y|ies)\b", "country"),
    (r"\b(by|per|each|for each)\s+customers?\b", "customer"),
    (r"\b(by|per|each|for each)\s+(?:industr(?:y|ies)|sectors?)\b", "industry"),
    (r"\b(by|per|each|for each)\s+(?:materials?|products?)\b", "material"),
    (r"\b(by|per|each|for each)\s+(?:suppliers?|vendors?)\b", "vendor"),
    (r"\b(by|per|each|for each)\s+(?:plants?|werks)\b", "plant"),
    (r"\b(by|per|each|for each)\s+currenc(?:y|ies)\b", "currency"),
    (r"\b(by|per|each|for each)\s+(?:types?|document types?)\b", "type"),
]

_TOP_N = re.compile(r"\b(?:top|bottom|highest|lowest)\s+(\d{1,3})\b", re.I)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
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
_RELATIVE_PERIODS = [
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
}


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
    ql = q.lower()
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
    for pat, dim in _GROUP_PATTERNS:
        if re.search(pat, ql):
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

    if re.search(r"\b(revenue|turnover|billed amount|billing amount|billed value|invoice value|billed sales)\b", ql):
        ops["measure_concept"] = "revenue"
    elif re.search(r"\b(quantit(?:y|ies)|qty|billed quantity)\b", ql):
        ops["measure_concept"] = "quantity"
    elif re.search(r"\b(sales order|sales document)\b", ql) and ops["aggregation"] == "COUNT":
        ops["measure_concept"] = "sales_order"
    elif re.search(r"\bsales\b", ql):
        ops["measure_concept"] = "sales"
    elif ops["aggregation"] == "COUNT":
        ops["measure_concept"] = "count"

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
    if m and not ops.get("ranking"):
        n = int(m.group(1))
        direction = "ASC" if re.search(r"\b(bottom|lowest|least|smallest|worst)\b", ql) else "DESC"
        ops["ranking"] = {"direction": direction, "limit": n}
        ops["limit"] = n
        ops["order"] = direction
        if not ops["aggregation"]:
            ops["aggregation"] = "SUM"
    elif not ops.get("ranking") and re.search(r"\b(highest|most|best|largest|top)\b", ql) and not re.search(r"\b(show|list|display)\b.{0,40}\b(with|and)\b", ql):
        # Singular "which X … most/highest" or "top country/customer" ⇒ top-1.
        # Plural entities ("which customers…highest") keep a short default list.
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
    elif not ops.get("ranking") and re.search(r"\b(lowest|least|smallest|worst|bottom)\b", ql):
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

    if ops.get("group_by") and ops.get("measure_concept") and not ops.get("aggregation"):
        ops["aggregation"] = "SUM"

    if re.search(r"\b(share|percentage of total|percent of total|% of)\b", ql):
        ops["share"] = True
    if re.search(r"\b(growth|increase|decrease|decline|change|difference|delta)\b", ql):
        ops["growth"] = True
    if re.search(r"\btrend\b", ql):
        ops["trend"] = True
        if not ops["time_grain"]:
            ops["time_grain"] = "month"
            if "month" not in group_by:
                group_by.append("month")
                ops["group_by"] = group_by
    if re.search(r"\b(compare|versus|vs\.?)\b", ql):
        ops["compare"] = True
    # Polarity/threshold predicates are applied below as generic comparisons.

    years = _YEAR.findall(q)
    if years:
        ops["years"] = sorted(set(years))

    _decline_cue = r"\b(declin\w*|decreas\w*|drop(?:ped|s)?|reduc\w*)\b"
    if years and len(set(years)) >= 2 and re.search(
        r"\b(growth|increas\w*|decreas\w*|declin\w*|between|versus|vs\.?|compared|difference|change|yoy|year[- ]over[- ]year)\b",
        ql,
    ):
        ordered = sorted(set(years))
        ops["period_compare"] = {
            "type": "period_change",
            "base_period": {"year": ordered[0], "start": ordered[0], "end": ordered[0]},
            "comparison_period": {"year": ordered[-1], "start": ordered[-1], "end": ordered[-1]},
            "op": "decline" if re.search(_decline_cue, ql) else "growth",
            "condition": "decreased" if re.search(_decline_cue, ql) else "increased",
            "calculation": "percentage_change" if re.search(r"\b(percent|percentage|%|pct)\b", ql) else "difference",
        }
        ops["compare"] = True
        ops["growth"] = True
        # Dimension for period compare is the entity, not year as a group grain of the output.
        if "year" in group_by and which:
            group_by = [g for g in group_by if g != "year"]
            ops["group_by"] = group_by

    elif not years and re.search(r"\b(year[- ]over[- ]year|yoy)\b", ql):
        # Explicit YoY without years → resolve latest two calendar years at planning time.
        ops["period_compare"] = {
            "type": "period_change",
            "requires_two_periods": True,
            "op": "decline" if re.search(_decline_cue, ql) else "growth",
            "condition": "decreased" if re.search(_decline_cue, ql) else "increased",
            "calculation": "difference",
        }
        ops["compare"] = True
        ops["growth"] = True
    elif ops.get("growth") and not years and re.search(
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
        # Keep growth flag for validators, but do not fabricate period_compare years.
        ops["period_compare"] = None

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
                if not re.search(r"\b(top|highest|lowest|best|worst|rank|most)\b", ql):
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

    if _NEGATION.search(ql):
        neg = {"type": "anti_join"}
        if re.search(r"purchase orders?.{0,60}(no|without|not|but no).{0,30}invoices?", ql) or re.search(
            r"\borders?\b.{0,40}\b(no|without|but no)\b.{0,30}\binvoices?\b", ql
        ):
            neg.update({"required": "purchase_order", "forbidden": "invoice"})
        elif re.search(r"invoices?.{0,60}(no|without|not|but no).{0,30}(orders?|payments?)", ql):
            neg.update({"required": "invoice", "forbidden": "purchase_order"})
        elif re.search(r"sales orders?.{0,60}(no|without|not|but no).{0,30}(billing|invoices?)", ql):
            neg.update({"required": "sales_order", "forbidden": "invoice"})
        elif re.search(r"invoices?.{0,60}(no|without|not|but no).{0,30}sales orders?", ql):
            neg.update({"required": "invoice", "forbidden": "sales_order"})
        elif re.search(r"activity.{0,40}(without|no).{0,20}billing", ql):
            neg.update({"required": "purchase_order", "forbidden": "invoice"})
        ops["negation"] = neg

    for pat, name in _RELATIVE_PERIODS:
        if re.search(pat, ql):
            ops["relative_period"] = name
            break

    return ops


def merge_semantic_requirements(
    question: str, llm_req: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Fill gaps in LLM semantic JSON using generic analytical operations."""
    req = dict(llm_req or {})
    ops = extract_analytical_operations(question)
    req["analytical_operations"] = ops

    dims = [str(d).lower() for d in (req.get("dimensions") or []) if str(d).strip()]
    for dim in ops.get("group_by") or []:
        if dim not in dims:
            dims.append(dim)
    req["dimensions"] = dims
    req["group_by"] = list(ops.get("group_by") or [])

    measure = req.get("measure") if isinstance(req.get("measure"), dict) else {}
    concept = str(measure.get("concept") or ops.get("measure_concept") or "").strip()
    agg = str(measure.get("aggregation") or ops.get("aggregation") or "").strip()
    if ops.get("measure_concept") and not concept:
        concept = str(ops["measure_concept"])
    if ops.get("aggregation") and (not agg or agg.lower() in {"", "none", "null"}):
        if not ops.get("negative_measure"):
            agg = str(ops["aggregation"])
    if ops.get("aggregation") == "COUNT":
        agg = "COUNT"
        if not concept:
            concept = str(ops.get("measure_concept") or "count")
    req["measure"] = {"concept": concept or measure.get("concept") or "", "aggregation": agg}

    ranking = req.get("ranking") if isinstance(req.get("ranking"), dict) else None
    if isinstance(ranking, dict) and not (
        ranking.get("limit") or ranking.get("direction") or ranking.get("partition_by")
    ):
        ranking = None
        req.pop("ranking", None)
    if ops.get("ranking") and not ranking:
        req["ranking"] = dict(ops["ranking"])
    elif ops.get("ranking") and ranking:
        ranking.setdefault("direction", ops["ranking"]["direction"])
        ranking.setdefault("limit", ops["ranking"]["limit"])
        if ops["ranking"].get("partition_by"):
            ranking["partition_by"] = list(ops["ranking"]["partition_by"])
        req["ranking"] = ranking

    if ops.get("partition_by"):
        req["partition_by"] = list(ops["partition_by"])
    if ops.get("negation"):
        req["negation"] = dict(ops["negation"])
    if ops.get("period_compare"):
        req["period_compare"] = dict(ops["period_compare"])
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
        tf["relative"] = ops["relative_period"]
        # Clear any LLM-invented absolute bounds; resolver fills them later.
        for k in ("start", "end", "start_yyyymmdd", "end_yyyymmdd", "value"):
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
