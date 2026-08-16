"""
Lightweight semantic query plan for Generative AI (System A).

Used by:
  - adaptive follow-up (R1): previous plan + follow-up delta → new plan → fresh SQL
  - sales grain / currency / industry directives (R3)
  - SQL memory fingerprint matching (R5)

This is NOT a hard-coded question dictionary and NOT a parallel AI stack.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple


_DIMENSION_TERMS: Dict[str, Tuple[str, ...]] = {
    "customer": ("customer", "customers", "client", "clients", "payer", "sold-to", "kunnr", "kunag", "name1"),
    "industry": ("industry", "industries", "sector", "sectors", "brsch", "brtxt"),
    "product": ("product", "products", "material", "materials", "matnr", "sku", "item", "items", "line item", "line items"),
    "currency": ("currency", "currencies", "waerk", "waers", "eur", "usd", "cad", "gbp"),
    "country": ("country", "countries", "nation", "region"),
    "vendor": ("vendor", "vendors", "supplier", "suppliers", "lifnr"),
    "year": ("year", "years", "annual", "yearly"),
    "month": ("month", "months", "monthly"),
    "plant": ("plant", "plants", "werks"),
}

_METRIC_TERMS: Dict[str, Tuple[str, ...]] = {
    "sales": ("sales", "revenue", "turnover", "billing value", "invoice value", "netwr"),
    "count": ("count", "number of", "how many", "volume of invoices", "invoice count"),
    "average": ("average", "avg", "mean"),
    "quantity": ("quantity", "qty", "quantities"),
    "profit": ("profit", "margin", "profitability"),
    "cost": ("cost", "cogs", "spend", "expense"),
}

_OP_TOP = ("highest", "top", "best", "largest", "most", "maximum", "max")
_OP_BOTTOM = ("lowest", "bottom", "worst", "least", "smallest", "minimum", "min")
_OP_TOTAL = ("total", "sum", "overall", "grand total")
_OP_COMPARE = ("compare", "versus", "vs", "difference", "against")

_LINE_GRAIN_CUES = (
    "line item", "line items", "item level", "product level", "material level",
    "by product", "per product", "by material", "per material", "vbrp", "posnr",
    "quantit", "sku",
)

_HEADER_SALES_CUES = (
    "sales", "revenue", "turnover", "highest sales", "lowest sales",
    "total sales", "billing", "invoice value",
)

_ADD_DIM_CUES = (
    r"\b(show|include|add|with|also|give me|tell me)\b.{0,40}\b(industry|customer|product|material|currency|country|vendor)\b",
    r"\b(the|their|its)\s+(industry|customer|product|currency)\b",
    r"\bindustry\b",
    r"\bcurrency\b",
)

_REMOVE_DIM_CUES = (
    r"\b(remove|without|drop|exclude)\b.{0,30}\b(industry|customer|product|currency|country)\b",
    r"\bonly\s+show\s+(customer|totals?|sales)\b",
    r"\bjust\s+(give|show)\s+(me\s+)?(the\s+)?totals?\b",
)

_FILTER_INDUSTRY = re.compile(
    r"\b(?:only|just|filter(?:\s+to)?|for|in)\s+(?:the\s+)?([A-Za-z][A-Za-z &/-]{1,40}?)\s+industry\b",
    re.I,
)
_FILTER_ONLY = re.compile(
    r"\bonly\s+(?:the\s+)?([A-Za-z][A-Za-z &/-]{1,40})\b",
    re.I,
)
_TOP_N = re.compile(r"\b(?:top|bottom|highest|lowest)\s+(\d{1,3})\b", re.I)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass
class QueryPlan:
    metric: str = "sales"
    dimensions: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    grain: str = "header"
    operation: str = "total"
    limit: Optional[int] = None
    comparison_years: List[str] = field(default_factory=list)
    needs_fresh_sql: bool = True
    delta_ops: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def fingerprint(self) -> str:
        dims = ",".join(sorted({d for d in self.dimensions if d}))
        years = self.filters.get("years") or []
        if isinstance(years, (list, set, tuple)):
            y = ",".join(sorted(str(x) for x in years))
        else:
            y = str(years)
        industry = str(self.filters.get("industry") or "").strip().lower()
        currency = str(self.filters.get("currency") or "").strip().lower()
        customer = str(self.filters.get("customer") or "").strip().lower()
        lim = str(self.limit or "")
        return (
            f"metric={self.metric}|dimensions={dims}|years={y}|"
            f"industry={industry}|currency={currency}|customer={customer}|"
            f"grain={self.grain}|operation={self.operation}|limit={lim}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "QueryPlan":
        if not data or not isinstance(data, dict):
            return cls()
        dims = data.get("dimensions") or []
        if isinstance(dims, str):
            dims = [d.strip() for d in dims.split(",") if d.strip()]
        return cls(
            metric=str(data.get("metric") or "sales"),
            dimensions=list(dims),
            filters=dict(data.get("filters") or {}),
            grain=str(data.get("grain") or "header"),
            operation=str(data.get("operation") or "total"),
            limit=data.get("limit"),
            comparison_years=list(data.get("comparison_years") or []),
            needs_fresh_sql=bool(data.get("needs_fresh_sql", True)),
            delta_ops=list(data.get("delta_ops") or []),
            notes=list(data.get("notes") or []),
        )


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _hits_dimension(ql: str) -> Set[str]:
    found: Set[str] = set()
    for dim, terms in _DIMENSION_TERMS.items():
        if any(t in ql for t in terms):
            found.add(dim)
    return found


def _infer_metric(ql: str) -> str:
    for metric in ("profit", "cost", "quantity", "average", "count", "sales"):
        if any(t in ql for t in _METRIC_TERMS[metric]):
            return metric
    if any(t in ql for t in ("invoice", "billing", "document")):
        return "count" if "how many" in ql or "number of" in ql else "sales"
    return "sales"


def _infer_operation(ql: str) -> str:
    if any(t in ql for t in _OP_COMPARE):
        return "compare"
    if any(t in ql for t in _OP_TOP):
        return "top"
    if any(t in ql for t in _OP_BOTTOM):
        return "bottom"
    if any(t in ql for t in ("average", "avg", "mean")):
        return "average"
    if any(t in ql for t in ("how many", "number of", "count")):
        return "count"
    if any(t in ql for t in _OP_TOTAL):
        return "total"
    if any(t in ql for t in ("show", "list", "display", "give")):
        return "top"
    return "total"


def _infer_grain(ql: str, dimensions: Set[str], metric: str) -> str:
    if any(c in ql for c in _LINE_GRAIN_CUES) or "product" in dimensions:
        return "line"
    if metric in {"sales", "average"} and any(c in ql for c in _HEADER_SALES_CUES):
        return "header"
    if metric == "sales":
        return "header"
    return "header"


def _extract_filters(ql: str, original: str) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    years = _YEAR.findall(original or ql)
    if years:
        filters["years"] = sorted(set(years))

    m = _FILTER_INDUSTRY.search(original or "")
    if m:
        filters["industry"] = m.group(1).strip()
    elif re.search(r"\btrading\b", ql) and ("industry" in ql or "filter" in ql or "only" in ql):
        filters["industry"] = "Trading"

    for cur in ("eur", "usd", "cad", "gbp", "dem", "jpy"):
        if re.search(rf"\b{cur}\b", ql):
            filters["currency"] = cur.upper()
            break

    if "industry" not in filters:
        m2 = _FILTER_ONLY.search(original or "")
        if m2:
            cand = m2.group(1).strip()
            cl = cand.lower()
            if cl not in {
                "show", "the", "customer", "customers", "sales", "revenue",
                "product", "products", "year", "years", "top", "bottom",
            } and len(cl) >= 3:
                if "industry" in ql or cl in {"trading", "manufacturing", "electronics", "automotive"}:
                    filters["industry"] = cand

    if "industry" not in filters:
        m3 = re.search(
            r"\bfilter(?:\s+to)?\s+(?:the\s+)?([A-Za-z][A-Za-z &/-]{1,40})\b",
            original or "",
            re.I,
        )
        if m3:
            cand = m3.group(1).strip()
            if cand.lower() not in {"to", "the", "by", "for", "on"}:
                filters["industry"] = cand

    return filters


def _extract_limit(ql: str, operation: str) -> Optional[int]:
    m = _TOP_N.search(ql)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    if operation in {"top", "bottom"} and not m:
        # Customer+industry rankings must return a list (currency-safe), not LIMIT 1.
        if "customer" in ql and "industry" in ql:
            return 10
        # Plural "top customers" → small ranking; singular "top customer" → 1
        if re.search(r"\b(top|highest|best|lowest|worst)\s+(customers|vendors|products|industries)\b", ql):
            return 5
        if re.search(r"\b(top|highest|best|lowest|worst)\s+(customer|vendor|product|industry)\b", ql):
            return 1
        if any(w in ql for w in ("highest", "lowest", "best", "worst")) and "top" not in ql and "bottom" not in ql:
            if "customer" in ql or "industry" in ql:
                return 5
            return 1
    return None


def extract_query_plan(question: str, previous_sql: str = "") -> QueryPlan:
    """Build a QueryPlan from a standalone (or first-turn) natural-language question."""
    original = (question or "").strip()
    ql = _norm(original)
    if not ql:
        return QueryPlan(needs_fresh_sql=False)

    dims = _hits_dimension(ql)
    metric = _infer_metric(ql)
    operation = _infer_operation(ql)
    if operation in {"top", "bottom"} and not (dims & {"customer", "product", "vendor", "industry", "country"}):
        dims.add("customer")

    filters = _extract_filters(ql, original)
    grain = _infer_grain(ql, dims, metric)
    limit = _extract_limit(ql, operation)
    comparison_years = list(filters.get("years") or []) if operation == "compare" else []

    ps = (previous_sql or "").lower()
    if "vbrp" in ps and any(t in ql for t in ("product", "material", "line")):
        grain = "line"

    notes: List[str] = [
        "Use VBRK header netwr for sales/revenue unless line/product explicitly requested.",
        "Filter billing year with SUBSTRING(TRIM(VBRK.fkdat),1,4); never VBRK.gjahr.",
        "Industry via VBRK→KNA1→T016T (brsch/brtxt); never MARA.mbrsh.",
        "Rank/aggregate per currency (waerk); do not sum EUR+USD.",
    ]

    return QueryPlan(
        metric=metric,
        dimensions=sorted(dims),
        filters=filters,
        grain=grain,
        operation=operation,
        limit=limit,
        comparison_years=comparison_years,
        needs_fresh_sql=True,
        delta_ops=["initial"],
        notes=notes,
    )


def _is_narrative_only(ql: str) -> bool:
    if not ql or len(ql) < 2:
        return True
    narrative = (
        r"^(thanks|thank you|ok|okay|got it|great|perfect|yes|no|cool)\.?$",
        r"^(explain|why|what does|what do|how come|clarify)\b",
        r"\b(in plain english|summarize (that|this|it)|explain (that|this|the result))\b",
    )
    return any(re.search(p, ql) for p in narrative)


def apply_followup_delta(previous: QueryPlan, followup_question: str) -> QueryPlan:
    """Merge follow-up intent into previous plan."""
    original = (followup_question or "").strip()
    ql = _norm(original)
    base = QueryPlan(
        metric=previous.metric,
        dimensions=list(previous.dimensions),
        filters=dict(previous.filters or {}),
        grain=previous.grain,
        operation=previous.operation,
        limit=previous.limit,
        comparison_years=list(previous.comparison_years or []),
        needs_fresh_sql=False,
        delta_ops=[],
        notes=list(previous.notes or []),
    )
    if not ql:
        return base

    if _is_narrative_only(ql):
        base.delta_ops = ["narrative"]
        base.needs_fresh_sql = False
        return base

    changed = False
    dims = set(base.dimensions)
    add_dims = _hits_dimension(ql)

    if any(re.search(p, ql) for p in _ADD_DIM_CUES) or add_dims:
        for d in add_dims:
            if d in {"year", "month"}:
                continue
            if d not in dims:
                dims.add(d)
                changed = True
                base.delta_ops.append(f"add_dimension:{d}")
        for bare in ("industry", "currency", "customer", "product", "country"):
            if re.search(rf"\b{bare}\b", ql) and bare not in dims:
                dims.add(bare)
                changed = True
                if f"add_dimension:{bare}" not in base.delta_ops:
                    base.delta_ops.append(f"add_dimension:{bare}")

    if any(re.search(p, ql) for p in _REMOVE_DIM_CUES):
        for d in list(dims):
            if d in ql and any(w in ql for w in ("remove", "without", "drop", "exclude")):
                dims.discard(d)
                changed = True
                base.delta_ops.append(f"remove_dimension:{d}")
        if re.search(r"\bjust\s+(give|show)\s+(me\s+)?(the\s+)?totals?\b", ql) or re.search(
            r"\bonly\s+show\s+totals?\b", ql
        ):
            if dims:
                dims.clear()
                changed = True
                base.delta_ops.append("remove_dimension:all")

    new_filters = _extract_filters(ql, original)
    for k, v in new_filters.items():
        if k == "years" and (any(t in ql for t in _OP_COMPARE) or "compare" in ql):
            # Defer year merge to the compare block below
            continue
        if base.filters.get(k) != v:
            base.filters[k] = v
            changed = True
            base.delta_ops.append(f"add_filter:{k}={v}")
            if k == "industry" and "industry" not in dims:
                dims.add("industry")

    if re.search(r"\b(remove|clear|drop)\b.{0,20}\b(trading|industry)\b", ql) or re.search(
        r"\b(all customers|all industries|all years|include all)\b", ql
    ):
        if "industry" in base.filters and ("industry" in ql or "trading" in ql or "all industries" in ql):
            base.filters.pop("industry", None)
            changed = True
            base.delta_ops.append("remove_filter:industry")
        if "years" in base.filters and ("all years" in ql or "include all years" in ql):
            base.filters.pop("years", None)
            changed = True
            base.delta_ops.append("remove_filter:years")
        if "all customers" in ql:
            base.filters.pop("customer", None)
            changed = True
            base.delta_ops.append("remove_filter:customer")

    years = _YEAR.findall(original)
    if years:
        if any(t in ql for t in _OP_COMPARE) or "compare" in ql:
            prev_years = list(base.filters.get("years") or [])
            merged = sorted(set(prev_years) | set(years))
            base.filters["years"] = merged
            base.comparison_years = merged
            base.operation = "compare"
            changed = True
            base.delta_ops.append(f"change_time:compare:{','.join(merged)}")
        elif list(base.filters.get("years") or []) != sorted(set(years)):
            base.filters["years"] = sorted(set(years))
            changed = True
            base.delta_ops.append(f"change_time:{','.join(sorted(set(years)))}")

    new_op = _infer_operation(ql)
    lim = _extract_limit(ql, new_op)
    if lim is not None:
        if lim != base.limit:
            base.limit = lim
            changed = True
            base.delta_ops.append(f"change_ranking:limit={lim}")
        elif _TOP_N.search(ql) or re.search(r"\b(now\s+)?(show|give)\s+(me\s+)?(the\s+)?top\b", ql):
            # Explicit top-N follow-up even when limit already matches (must re-run SQL)
            base.limit = lim
            changed = True
            base.delta_ops.append(f"change_ranking:limit={lim}")
    if new_op in {"top", "bottom"} and (
        new_op != base.operation
        or lim is not None
        or any(t in ql for t in ("top", "bottom", "highest", "lowest"))
    ):
        if new_op != base.operation:
            base.operation = new_op
            changed = True
            base.delta_ops.append(f"change_ranking:op={new_op}")
        elif lim is not None:
            base.operation = new_op

    if any(t in ql for t in ("instead", "rather", "switch to", "change to")) or any(
        t in ql for t in ("invoice count", "average sales", "total revenue", "show count", "how many")
    ):
        new_metric = _infer_metric(ql)
        if new_metric != base.metric:
            base.metric = new_metric
            changed = True
            base.delta_ops.append(f"change_metric:{new_metric}")
            if new_metric == "count":
                base.operation = "count"

    if any(c in ql for c in _LINE_GRAIN_CUES):
        if base.grain != "line":
            base.grain = "line"
            changed = True
            base.delta_ops.append("change_grain:line")

    base.dimensions = sorted(dims)

    if not changed:
        # "by customer" / "per industry" restates a dimension — still needs fresh SQL
        # when confirming or re-applying a breakdown after a metric/filter change.
        by_dim = re.search(
            r"\b(by|per)\s+(customer|customers|industry|product|products|currency|country|vendor)\b",
            ql,
        )
        if by_dim:
            d = by_dim.group(2).rstrip("s")
            if d == "currencie":
                d = "currency"
            if d not in dims:
                dims.add(d)
            changed = True
            base.delta_ops.append(f"ensure_dimension:{d}")
        else:
            businessish = bool(
                add_dims
                or years
                or lim
                or any(
                    t in ql
                    for t in (
                        "sales", "revenue", "customer", "industry", "trading", "top",
                        "bottom", "filter", "only", "compare", "currency", "invoice",
                        "show", "list",
                    )
                )
            )
            if businessish and not _is_narrative_only(ql):
                overlay = extract_query_plan(original)
                for d in overlay.dimensions:
                    if d not in base.dimensions:
                        base.dimensions.append(d)
                        changed = True
                        base.delta_ops.append(f"add_dimension:{d}")
                for k, v in (overlay.filters or {}).items():
                    if base.filters.get(k) != v:
                        base.filters[k] = v
                        changed = True
                        base.delta_ops.append(f"add_filter:{k}")
                if overlay.limit and overlay.limit != base.limit:
                    base.limit = overlay.limit
                    changed = True
                if overlay.operation in {"top", "bottom", "compare"} and overlay.operation != base.operation:
                    base.operation = overlay.operation
                    changed = True

    base.dimensions = sorted(set(dims) | set(base.dimensions))
    base.needs_fresh_sql = changed or bool(base.delta_ops)
    if base.needs_fresh_sql and "narrative" in base.delta_ops:
        base.delta_ops = [d for d in base.delta_ops if d != "narrative"]

    base.notes = [
        "Use VBRK header netwr for sales/revenue unless grain=line.",
        "Year filters: SUBSTRING(TRIM(VBRK.fkdat),1,4); never gjahr.",
        "Industry: VBRK→KNA1→T016T only.",
        "Group/rank by currency (waerk); never mix EUR+USD into one total.",
        "Missing customer/industry → label Unknown / Not available — do not invent.",
    ]
    return base


def merge_followup_plan(
    previous_question: str,
    followup_question: str,
    previous_sql: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
) -> QueryPlan:
    if previous_plan:
        prev = QueryPlan.from_dict(previous_plan)
    else:
        prev = extract_query_plan(previous_question or "", previous_sql or "")
    return apply_followup_delta(prev, followup_question or "")


def fingerprints_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True

    def _parse(fp: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for part in (fp or "").split("|"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    pa, pb = _parse(a), _parse(b)
    for key in ("metric", "grain", "operation"):
        if pa.get(key) and pb.get(key) and pa.get(key) != pb.get(key):
            return False
    for key in ("dimensions", "years", "industry", "currency", "customer", "limit"):
        if (pa.get(key) or "") != (pb.get(key) or ""):
            return False
    return True


def plan_prompt_directive(plan: QueryPlan) -> str:
    years = plan.filters.get("years") or []
    ytxt = ", ".join(years) if isinstance(years, list) else str(years)
    industry = plan.filters.get("industry")
    lines = [
        "SEMANTIC QUERY PLAN (mandatory — generate SQL that satisfies this plan):",
        f"- metric: {plan.metric}",
        f"- dimensions: {', '.join(plan.dimensions) or '(none — aggregate only)'}",
        f"- operation: {plan.operation}",
        f"- limit: {plan.limit if plan.limit is not None else '(default)'}",
        f"- grain: {plan.grain} "
        + ("→ SUM/filter on VBRK.netwr (header)" if plan.grain == "header" else "→ line-level vbrp as needed"),
        f"- years: {ytxt or '(none)'} → use SUBSTRING(TRIM(\"VBRK\".\"fkdat\"),1,4); NEVER \"gjahr\"",
    ]
    if industry:
        lines.append(f"- industry filter: {industry} via KNA1.brsch → T016T.brtxt (ILIKE)")
    if plan.filters.get("currency"):
        lines.append(f"- currency filter: {plan.filters['currency']} on VBRK.waerk")
    lines.append("- ALWAYS include waerk/currency and GROUP BY currency for monetary aggregates")
    lines.append("- For customer names use VBRK.kunag → KNA1.kunnr; COALESCE(name1,'Unknown / unmapped')")
    if "customer" in plan.dimensions:
        lines.append(
            "- When ranking highest/top customers: require mapped customers "
            "(TRIM(COALESCE(c.\"name1\",'')) <> '') so unmapped payer keys do not win the ranking; "
            "still GROUP BY currency; use LIMIT from the plan (not LIMIT 1 across currencies)."
        )
    if "industry" in plan.dimensions:
        lines.append("- For industry use LEFT JOIN T016T on brsch only; add spras='E' ONLY if spras exists in schema")
        lines.append("- COALESCE(brtxt,'Not available') — never invent industry; never MARA.mbrsh")
    if plan.delta_ops:
        lines.append(f"- follow-up deltas applied: {', '.join(plan.delta_ops)}")
    for n in plan.notes:
        lines.append(f"- note: {n}")
    return "\n".join(lines)


def follow_up_needs_fresh_sql(
    followup_question: str,
    previous_question: str = "",
    previous_sql: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, QueryPlan]:
    plan = merge_followup_plan(previous_question, followup_question, previous_sql, previous_plan)
    return bool(plan.needs_fresh_sql), plan
