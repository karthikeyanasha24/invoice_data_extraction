"""Result-first follow-up: reuse prior rows/plan before rediscovering the schema.

If the user asks about "this result" and the needed dimension is already in
the previous rows, answer in memory. Otherwise expand the existing query
context instead of restarting from the full table catalog.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("zodiac-api.result_first_followup")

_THIS_RESULT = re.compile(
    r"\b(this result|these results|this list|these rows|in this result|from this result|"
    r"in the result|from the result|this data|from these)\b",
    re.I,
)
_APPEARS_MOST = re.compile(
    r"\b(appears? most|most (?:common|frequent)|highest (?:count|frequency)|most often)\b",
    re.I,
)
_FOLLOWUP_HINT = re.compile(
    r"\b(this|these|those|same|previous|prior|above|one|them)\b",
    re.I,
)
_GROWTH_RANK = re.compile(
    r"\b("
    r"which\s+one|"
    r"which\s+of\s+(them|these|those)|"
    r"grew\s+(the\s+)?(fastest|most)|"
    r"highest\s+growth|"
    r"fastest\s+growth|"
    r"largest\s+(increase|growth)|"
    r"biggest\s+(increase|growth)"
    r")\b",
    re.I,
)

_CONCEPT_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "supplier": ("supplier", "vendor", "lifnr", "name1", "supplier_name", "vendor_name"),
    "vendor": ("vendor", "supplier", "lifnr", "vendor_name", "supplier_name"),
    "customer": ("customer", "kunnr", "kunag", "name1", "customer_name", "customer_id", "payer"),
    "country": ("country", "land1", "landx", "nation", "region"),
    "industry": ("industry", "brsch", "brtxt", "sector"),
    "material": ("material", "matnr", "maktx", "product", "material_name", "material_id"),
    "product": ("product", "material", "matnr", "maktx"),
    "currency": ("currency", "waerk", "waers"),
    "type": ("type", "auart", "fkart", "vbtyp", "document_type"),
}

_CHANGE_KEYS = ("change", "growth", "delta", "diff", "pct_change", "contribution_pct", "growth_pct")


def is_result_scoped_followup(question: str, *, has_prior_rows: bool) -> bool:
    """True when the question refers to a prior result set (even if empty)."""
    q = question or ""
    if _THIS_RESULT.search(q):
        return True
    if _APPEARS_MOST.search(q) and _FOLLOWUP_HINT.search(q):
        return True
    if _APPEARS_MOST.search(q) and len(q.split()) <= 12:
        return True
    if has_prior_rows and _GROWTH_RANK.search(q):
        return True
    return False


def _detect_concept(question: str) -> Optional[str]:
    ql = (question or "").lower()
    for concept in ("supplier", "vendor", "customer", "country", "industry", "material", "product", "currency", "type"):
        if re.search(rf"\b{re.escape(concept)}s?\b", ql):
            return concept
    return None


def _matching_columns(rows: List[Dict[str, Any]], concept: str) -> List[str]:
    if not rows:
        return []
    keys = list(rows[0].keys())
    wanted = _CONCEPT_COLUMNS.get(concept, (concept,))
    matched: List[str] = []
    for key in keys:
        kl = str(key).lower()
        if any(w in kl for w in wanted):
            matched.append(str(key))
    return matched


def _find_numeric_column(rows: List[Dict[str, Any]], candidates: Tuple[str, ...]) -> Optional[str]:
    if not rows:
        return None
    keys = list(rows[0].keys())
    lower_map = {str(k).lower(): k for k in keys}
    for cand in candidates:
        if cand in lower_map:
            return lower_map[cand]
    for k in keys:
        kl = str(k).lower()
        if any(c in kl for c in candidates):
            return k
    return None


def _entity_label_column(rows: List[Dict[str, Any]]) -> Optional[str]:
    if not rows:
        return None
    for concept in ("customer", "material", "product", "country", "industry", "vendor", "supplier"):
        cols = _matching_columns(rows, concept)
        if cols:
            for c in cols:
                if "name" in str(c).lower() or concept in str(c).lower():
                    return c
            return cols[0]
    for k, v in rows[0].items():
        if isinstance(v, str) and str(k).lower() not in {"sql", "currency"}:
            return str(k)
    return None


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _rank_by_column(rows: List[Dict[str, Any]], col: str, *, descending: bool = True) -> List[Dict[str, Any]]:
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for row in rows:
        n = _to_float(row.get(col))
        if n is None:
            continue
        scored.append((n, row))
    scored.sort(key=lambda t: t[0], reverse=descending)
    return [r for _, r in scored]


def _prior_entity_names(rows: List[Dict[str, Any]], limit: int = 8) -> List[str]:
    col = _entity_label_column(rows)
    if not col:
        return []
    out: List[str] = []
    for row in rows:
        val = row.get(col)
        if val is None:
            continue
        s = str(val).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def expand_growth_followup_question(
    question: str,
    prior_rows: List[Dict[str, Any]],
    *,
    prior_question: str = "",
) -> Optional[str]:
    """Rewrite a growth follow-up into a standalone period-growth question scoped to prior entities."""
    if not _GROWTH_RANK.search(question or ""):
        return None
    names = _prior_entity_names(prior_rows)
    if not names:
        return None
    entity = "customers"
    keys = {str(k).lower() for k in prior_rows[0].keys()} if prior_rows else set()
    if any("material" in k or "product" in k or "matnr" in k for k in keys):
        entity = "materials"
    elif any("country" in k or "land1" in k for k in keys):
        entity = "countries"
    joined = ", ".join(names[:5])
    years = re.findall(r"\b((?:19|20)\d{2})\b", prior_question or "")
    year_bit = ""
    if len(set(years)) >= 2:
        ordered = sorted(set(years))
        year_bit = f" between {ordered[0]} and {ordered[-1]}"
    elif years:
        year_bit = f" vs the prior year relative to {years[-1]}"
    return (
        f"Which of these {entity} ({joined}) grew the fastest in revenue{year_bit}?"
    )


def _most_frequent(rows: List[Dict[str, Any]], columns: List[str]) -> List[Dict[str, Any]]:
    if not columns:
        return []
    primary = columns[0]
    counts: Counter[str] = Counter()
    samples: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        raw = row.get(primary)
        if raw is None:
            continue
        val = str(raw).strip()
        if not val:
            continue
        counts[val] += 1
        samples.setdefault(val, {c: row.get(c) for c in columns})
    if not counts:
        return []
    ranked = counts.most_common(10)
    out: List[Dict[str, Any]] = []
    for val, n in ranked:
        item = dict(samples.get(val) or {primary: val})
        item["occurrence_count"] = n
        out.append(item)
    return out


def try_answer_from_prior_rows(
    question: str,
    prior_rows: Optional[List[Dict[str, Any]]],
    *,
    prior_sql: str = "",
    prior_plan: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    rows = [r for r in (prior_rows or []) if isinstance(r, dict)]
    if not is_result_scoped_followup(question, has_prior_rows=bool(rows)):
        return None

    if not rows:
        return {
            "mode": "result_first",
            "status": "completed",
            "answer_status": "CANNOT_ANSWER",
            "sql": prior_sql or "",
            "sql_generation_method": "result_first_no_prior_rows",
            "pipeline": "result_first_followup",
            "rowCount": 0,
            "data": [],
            "summary": (
                "There is no prior validated result to analyze. Run a successful "
                "investigation first, then ask which entity appears most in that result."
            ),
            "answer": "No prior result is available for this follow-up.",
            "charts": [],
            "query_plan": prior_plan or {"reused_prior_result": False},
            "meta": {"investigation_status": "completed", "followup": "missing_prior_result"},
        }

    # Growth ranking on prior result: use change columns if present; else expand plan.
    if _GROWTH_RANK.search(question or ""):
        change_col = _find_numeric_column(rows, _CHANGE_KEYS)
        if change_col:
            ranked = _rank_by_column(rows, change_col, descending=True)
            if ranked:
                top = ranked[0]
                label_col = _entity_label_column(rows)
                label = top.get(label_col) if label_col else None
                val = top.get(change_col)
                summary = (
                    f"Among the previous result rows, '{label}' has the highest "
                    f"{change_col} ({val})."
                    if label is not None
                    else f"Among the previous result rows, the highest {change_col} is {val}."
                )
                return {
                    "mode": "result_first",
                    "status": "completed",
                    "answer_status": "SUCCESS",
                    "sql": "",
                    "sql_generation_method": "result_first_growth_rank",
                    "pipeline": "result_first_followup",
                    "rowCount": len(ranked),
                    "data": ranked[:20],
                    "summary": summary,
                    "answer": summary,
                    "charts": [],
                    "query_plan": prior_plan or {"reused_prior_result": True},
                    "meta": {"investigation_status": "completed", "followup": "growth_rank"},
                }
        prior_q = ""
        if isinstance(prior_plan, dict):
            inv = prior_plan.get("investigation_state") if isinstance(prior_plan.get("investigation_state"), dict) else {}
            prior_q = str(
                prior_plan.get("last_user_question")
                or inv.get("last_user_question")
                or ""
            )
        rewritten = expand_growth_followup_question(question, rows, prior_question=prior_q)
        return {
            "mode": "result_first_gap",
            "status": "completed",
            "answer_status": "SUCCESS",
            "sql": prior_sql or "",
            "sql_generation_method": "result_first_needs_growth_sql",
            "pipeline": "result_first_followup",
            "rowCount": 0,
            "data": [],
            "summary": (
                "The previous result has level metrics but not period growth. "
                "A follow-up query scoped to those entities is required."
            ),
            "answer": "Growth cannot be computed from the previous level-only result alone.",
            "charts": [],
            "needs_plan_expansion": True,
            "missing_concept": "period_change",
            "expanded_question": rewritten,
            "query_plan": prior_plan
            or {"reused_prior_result": True, "missing_concept": "period_change"},
            "meta": {"investigation_status": "completed", "followup": "needs_growth_sql"},
        }

    concept = _detect_concept(question)
    logger.info(
        "[followup] result-first question=%r concept=%s prior_rows=%d",
        (question or "")[:160],
        concept,
        len(rows),
    )
    if not concept:
        return {
            "mode": "result_first",
            "status": "completed",
            "answer_status": "SUCCESS",
            "sql": "",
            "sql_generation_method": "result_first_prior_rows",
            "pipeline": "result_first_followup",
            "rowCount": len(rows),
            "data": rows[:50],
            "summary": f"Reusing the previous result ({len(rows)} row(s)). No additional database query was required.",
            "answer": f"Reusing the previous result ({len(rows)} row(s)).",
            "charts": [],
            "query_plan": prior_plan or {"reused_prior_result": True},
            "meta": {"investigation_status": "completed", "followup": "result_reuse"},
        }

    cols = _matching_columns(rows, concept)
    if not cols:
        logger.info("[followup] concept %s not in prior columns %s", concept, list(rows[0].keys())[:12] if rows else [])
        return {
            "mode": "result_first_gap",
            "status": "completed",
            "answer_status": "SUCCESS",
            "sql": prior_sql or "",
            "sql_generation_method": "result_first_missing_dimension",
            "pipeline": "result_first_followup",
            "rowCount": 0,
            "data": [],
            "summary": (
                f"The previous result does not include {concept} information, so this question "
                f"cannot be answered from the current rows alone. A wider query is needed if "
                f"{concept} exists in the dataset."
            ),
            "answer": (
                f"The previous result does not include {concept} information."
            ),
            "charts": [],
            "needs_plan_expansion": True,
            "missing_concept": concept,
            "query_plan": prior_plan or {"reused_prior_result": True, "missing_concept": concept},
            "meta": {"investigation_status": "completed", "followup": "missing_dimension"},
        }

    ranked = _most_frequent(rows, cols)
    if not ranked:
        return None
    top = ranked[0]
    label = top.get(cols[0])
    count = top.get("occurrence_count")
    summary = (
        f"In the previous result, {concept} '{label}' appears most often "
        f"({count} occurrence(s))."
    )
    return {
        "mode": "result_first",
        "status": "completed",
        "answer_status": "SUCCESS",
        "sql": "",
        "sql_generation_method": "result_first_frequency",
        "pipeline": "result_first_followup",
        "rowCount": len(ranked),
        "data": ranked,
        "summary": summary,
        "answer": summary,
        "charts": [],
        "query_plan": prior_plan or {"reused_prior_result": True},
        "meta": {"investigation_status": "completed", "followup": "frequency"},
    }
