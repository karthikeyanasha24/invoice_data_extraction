"""Generic semantic requirements for plan/SQL/result validation.

No question-specific handlers. Language → structured requirements used by:
  plan completeness checks
  SQL-plan satisfaction
  result-vs-plan hard gates
  semantic repair diagnosis
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .analytical_operations import extract_analytical_operations, merge_semantic_requirements

_ENTITY_WHICH = re.compile(
    r"\b(?:which|what|top|bottom|highest|lowest|most|least)\s+"
    r"(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
    r"(countries|country|customers?|clients?|buyers?|materials?|products?|"
    r"suppliers?|vendors?|industr(?:y|ies)|segments?)\b",
    re.I,
)
_ENTITY_MAP = {
    "country": "country", "countries": "country",
    "customer": "customer", "customers": "customer",
    "client": "customer", "clients": "customer", "buyer": "customer", "buyers": "customer",
    "material": "material", "materials": "material",
    "product": "material", "products": "material",
    "supplier": "vendor", "suppliers": "vendor",
    "vendor": "vendor", "vendors": "vendor",
    "industry": "industry", "industries": "industry",
    "segment": "industry", "segments": "industry",
}
_DIM_RESULT_KEYS = {
    "country": ("country", "land1", "landx"),
    "customer": ("customer", "customer_id", "customer_name", "kunnr", "kunag", "name1"),
    "material": ("material", "material_id", "matnr", "maktx", "product", "product_id"),
    "vendor": ("vendor", "supplier", "supplier_id", "lifnr", "name1"),
    "industry": ("industry", "brsch", "brtxt", "sector", "segment"),
    "month": ("month", "yyyymm", "period", "ym"),
    "year": ("year", "yyyy", "gjahr", "fiscal_year"),
    "currency": ("currency", "waerk", "waers"),
}


def required_semantics(question: str, semantic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Derive the minimum semantic contract the investigation must satisfy."""
    sem = merge_semantic_requirements(question, semantic or {})
    ops = sem.get("analytical_operations") or extract_analytical_operations(question)
    ql = (question or "").lower()

    dims = [str(d).lower() for d in (sem.get("dimensions") or []) if str(d).strip()]
    group_by = [str(g).lower() for g in (sem.get("group_by") or ops.get("group_by") or [])]
    for g in group_by:
        if g not in dims:
            dims.append(g)

    # "Which country/customer/..." implies that entity is a ranking/group dimension.
    m = _ENTITY_WHICH.search(question or "")
    if m:
        ent = _ENTITY_MAP.get(m.group(1).lower())
        if ent and ent not in dims:
            dims.append(ent)
        if ent and ent not in group_by and (
            ops.get("ranking") or re.search(r"\b(most|highest|largest|top|lowest|least)\b", ql)
        ):
            group_by.append(ent)

    ranking = sem.get("ranking") if isinstance(sem.get("ranking"), dict) else ops.get("ranking")
    if isinstance(ranking, dict) and not (
        ranking.get("limit") or ranking.get("direction") or ranking.get("partition_by")
    ):
        ranking = None
    # Plural entity questions must not collapse to top-1 when the LLM/sem layer
    # emits singular limits. Explicit "top N" always wins.
    if isinstance(ranking, dict):
        explicit_n = re.search(r"\b(?:top|bottom)\s+(\d+)\b", ql)
        plural_entity = bool(
            re.search(
                r"\b(countries|customers|clients|buyers|materials|products|"
                r"suppliers|vendors|industries|segments)\b",
                ql,
            )
        )
        ops_rank = ops.get("ranking") if isinstance(ops.get("ranking"), dict) else {}
        if explicit_n:
            ranking = {**ranking, "limit": int(explicit_n.group(1))}
        elif plural_entity and int(ranking.get("limit") or 0) == 1:
            ranking = {**ranking, "limit": int(ops_rank.get("limit") or 10)}
        elif (
            ops_rank.get("limit")
            and int(ranking.get("limit") or 0) == 1
            and int(ops_rank.get("limit") or 0) > 1
            and not re.search(
                r"\bwhich\s+(country|customer|client|buyer|material|product|"
                r"supplier|vendor|industry)\b",
                ql,
            )
        ):
            ranking = {**ranking, "limit": int(ops_rank["limit"])}
    partition_by = [
        str(p).lower()
        for p in (
            (ranking or {}).get("partition_by")
            if isinstance(ranking, dict)
            else []
        )
        or sem.get("partition_by")
        or ops.get("partition_by")
        or []
    ]
    for p in partition_by:
        if p not in group_by:
            group_by.append(p)
        if p not in dims:
            dims.append(p)

    measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    concept = str(measure.get("concept") or ops.get("measure_concept") or "").lower()
    agg = str(measure.get("aggregation") or ops.get("aggregation") or "").upper()
    if ranking and not agg:
        agg = "SUM"

    period = sem.get("period_compare") if isinstance(sem.get("period_compare"), dict) else ops.get("period_compare")
    # LLM sometimes emits {"type": null, "base_period": null, ...} — treat as absent.
    if isinstance(period, dict) and not (
        period.get("base_period")
        or period.get("comparison_period")
        or period.get("requires_two_periods")
        or period.get("year_a")
        or period.get("year_b")
    ):
        period = None
    # Question language wins over LLM pollution for growth vs decline direction.
    _decline_cue = r"\b(declin\w*|decreas\w*|drop(?:ped|s)?|reduc\w*)\b"
    if isinstance(period, dict) and re.search(_decline_cue, ql):
        period = {**period, "op": "decline", "condition": "decreased"}
    clarification = sem.get("clarification") if isinstance(sem.get("clarification"), dict) else ops.get("clarification")
    if not period and (ops.get("growth") or ops.get("compare")) and not clarification:
        years = list(ops.get("years") or [])
        if len(years) >= 2:
            period = {
                "type": "period_change",
                "base_period": {"year": years[0]},
                "comparison_period": {"year": years[-1]},
                "op": "decline" if re.search(_decline_cue, ql) else "growth",
                "condition": "decreased" if re.search(_decline_cue, ql) else "increased",
            }
        # Without explicit years, do not invent periods — clarification is preferred.
    # Explicit YoY with deferred year resolution must keep period_compare.
    if period and period.get("requires_two_periods"):
        clarification = None
    if clarification and clarification.get("type") == "comparison_period" and not (
        isinstance(period, dict) and period.get("requires_two_periods")
    ):
        period = None

    negation = sem.get("negation") if isinstance(sem.get("negation"), dict) else ops.get("negation")
    if isinstance(negation, dict) and not (negation.get("required") or negation.get("forbidden") or negation.get("type")):
        negation = None
    # LLM often emits {"required": "purchase_order", "forbidden": null} for PO ranking
    # questions — that is not an anti-join. Keep negation only with absence language.
    _absence_lang = bool(
        re.search(
            r"\b(no|without|excluding|exclude|never|missing|absent|but no|not having)\b",
            ql,
        )
    )
    if isinstance(negation, dict) and not _absence_lang and not negation.get("forbidden"):
        negation = None
    if negation and not negation.get("forbidden") and _absence_lang:
        # Infer positive/negative entities from language when possible.
        if re.search(r"purchase orders?.{0,40}(no|without|not).{0,20}invoices?", ql) or re.search(
            r"orders?.{0,40}(no|without).{0,20}invoices?", ql
        ):
            negation = {
                "type": "anti_join",
                "required": "purchase_order",
                "forbidden": "invoice",
            }
        elif re.search(r"activity.{0,40}(without|no).{0,20}billing", ql):
            negation = {
                "type": "anti_join",
                "required": "purchase_order",
                "forbidden": "invoice",
            }
        elif not negation.get("forbidden"):
            negation = None

    tf = sem.get("time_filter") if isinstance(sem.get("time_filter"), dict) else {}
    relative = tf.get("relative") or ops.get("relative_period")
    # LLM sometimes sets relative=true (boolean) — resolve via named period instead.
    if relative is True or str(relative).lower() in {"true", "1", "yes"}:
        relative = (
            ops.get("relative_period")
            or (str(tf.get("value") or "").strip() if str(tf.get("concept") or "").lower() in {"month", "week", "year", "quarter", "date", "period"} else "")
            or None
        )
        if isinstance(relative, str) and relative.lower() in {"last_month", "last month"}:
            relative = "last_month"
        elif isinstance(relative, str) and " " in relative:
            relative = relative.lower().replace(" ", "_")
    date_filter = None
    if relative and str(relative).lower() not in {"true", "false", "none", ""}:
        start, end = resolve_relative_period_bounds(str(relative))
        date_filter = {
            "type": "relative_period",
            "period": str(relative),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "start_yyyymmdd": start.strftime("%Y%m%d"),
            "end_yyyymmdd": end.strftime("%Y%m%d"),
        }

    having_distinct = (
        sem.get("having_distinct")
        if isinstance(sem.get("having_distinct"), dict)
        else ops.get("having_distinct")
    )
    if isinstance(having_distinct, dict) and not (
        having_distinct.get("entity") and having_distinct.get("dimension")
    ):
        having_distinct = None

    return {
        "dimensions": dims,
        "group_by": group_by,
        "measure": {"concept": concept, "aggregation": agg},
        "ranking": None if having_distinct else ranking,
        "partition_by": partition_by,
        "period_compare": period,
        "negation": negation,
        "date_filter": date_filter,
        "clarification": clarification,
        "having_distinct": having_distinct,
        "growth": bool(ops.get("growth") or period),
        "share": bool(ops.get("share") or sem.get("share")),
        "question": question,
        "semantic": sem,
    }


def resolve_relative_period_bounds(relative: str, today: Optional[date] = None) -> Tuple[date, date]:
    """Deterministic calendar bounds for relative periods. Exclusive end."""
    today = today or date.today()
    rel = (relative or "").lower().strip()

    def month_start(d: date) -> date:
        return d.replace(day=1)

    def add_months(d: date, n: int) -> date:
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        return date(y, m, 1)

    if rel == "this_month":
        start = month_start(today)
        end = add_months(start, 1)
    elif rel == "last_month":
        end = month_start(today)
        start = add_months(end, -1)
    elif rel == "this_year":
        start = date(today.year, 1, 1)
        end = date(today.year + 1, 1, 1)
    elif rel == "last_year":
        start = date(today.year - 1, 1, 1)
        end = date(today.year, 1, 1)
    elif rel == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif rel == "last_week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    elif rel == "this_quarter":
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        end = add_months(start, 3)
    elif rel == "last_quarter":
        q = (today.month - 1) // 3
        end = date(today.year, q * 3 + 1, 1)
        start = add_months(end, -3)
    elif rel == "ytd":
        start = date(today.year, 1, 1)
        end = today + timedelta(days=1)
    elif rel == "mtd":
        start = month_start(today)
        end = today + timedelta(days=1)
    else:
        start = month_start(today)
        end = add_months(start, 1)
    return start, end


def enrich_semantic_with_requirements(
    question: str, semantic: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Merge required semantics back into the working semantic dict used by the planner."""
    req = required_semantics(question, semantic)
    sem = dict(req.get("semantic") or {})
    sem["dimensions"] = list(req["dimensions"])
    sem["group_by"] = list(req["group_by"])
    if req.get("ranking"):
        sem["ranking"] = dict(req["ranking"])
    if req.get("partition_by"):
        sem["partition_by"] = list(req["partition_by"])
    if req.get("period_compare"):
        sem["period_compare"] = dict(req["period_compare"])
    elif req.get("clarification"):
        sem["clarification"] = dict(req["clarification"])
        sem.pop("period_compare", None)
    if req.get("negation"):
        sem["negation"] = dict(req["negation"])
    if req.get("date_filter"):
        # Always overwrite invented absolute bounds with deterministic calendar resolution.
        sem["time_filter"] = {
            "relative": req["date_filter"].get("period"),
            "start": req["date_filter"].get("start"),
            "end": req["date_filter"].get("end"),
            "start_yyyymmdd": req["date_filter"].get("start_yyyymmdd"),
            "end_yyyymmdd": req["date_filter"].get("end_yyyymmdd"),
            "type": "relative_period",
            "concept": "relative_period",
            "value": req["date_filter"].get("period"),
        }
    measure = sem.get("measure") if isinstance(sem.get("measure"), dict) else {}
    measure["concept"] = req["measure"]["concept"] or measure.get("concept") or ""
    measure["aggregation"] = req["measure"]["aggregation"] or measure.get("aggregation") or ""
    sem["measure"] = measure
    sem["growth"] = bool(req.get("growth"))
    sem["required_semantics"] = {
        k: v for k, v in req.items() if k not in {"semantic", "question"}
    }
    return sem


def plan_missing_requirements(plan: Dict[str, Any], requirements: Dict[str, Any]) -> List[str]:
    """Plan-level completeness before SQL generation."""
    missing: List[str] = []
    if not plan:
        return ["empty plan"]

    select = plan.get("select") or []
    group_by = plan.get("group_by") or []
    ranking = plan.get("ranking") or (plan.get("semantic_requirements") or {}).get("ranking")
    period = requirements.get("period_compare")
    negation = requirements.get("negation")
    date_filter = requirements.get("date_filter")
    dims = requirements.get("group_by") or requirements.get("dimensions") or []
    sem = plan.get("semantic_requirements") if isinstance(plan.get("semantic_requirements"), dict) else {}

    if period:
        has_period = bool(plan.get("period_compare") or sem.get("period_compare"))
        has_compare_fields = any(
            any(tok in str(s).lower() for tok in ("period_a", "period_b", "change", "growth", "pct_change"))
            for s in select
        )
        if not has_period and not has_compare_fields:
            missing.append("period comparison operation missing from plan")

    if requirements.get("partition_by") or (
        isinstance(requirements.get("ranking"), dict) and (requirements.get("ranking") or {}).get("partition_by")
    ):
        rk = ranking if isinstance(ranking, dict) else {}
        parts = rk.get("partition_by") or requirements.get("partition_by") or []
        if not parts:
            missing.append("partitioned ranking missing partition_by")
        if not (rk.get("limit") or (requirements.get("ranking") or {}).get("limit")):
            missing.append("partitioned ranking missing limit")

    if negation:
        if not (plan.get("negation") or sem.get("negation")):
            missing.append("negation operation missing from plan")

    if date_filter:
        tf = sem.get("time_filter") if isinstance(sem.get("time_filter"), dict) else {}
        if not (tf.get("relative") or tf.get("start_yyyymmdd") or date_filter.get("start_yyyymmdd")):
            missing.append("relative date filter missing from plan")

    return missing


def result_has_dimension(keys: List[str], dim: str) -> bool:
    keys_l = [str(k).lower() for k in keys]
    aliases = _DIM_RESULT_KEYS.get(dim, (dim,))
    return any(any(a == k or a in k for a in aliases) for k in keys_l)


def parse_result_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" and len(s) >= 10 else s[:8] if fmt == "%Y%m%d" else s, fmt).date()
        except Exception:
            continue
    if re.fullmatch(r"\d{8}", s):
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except Exception:
            return None
    if re.fullmatch(r"\d{6}", s):
        try:
            return datetime.strptime(s + "01", "%Y%m%d").date()
        except Exception:
            return None
    return None
