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
    r"\b(this|these|those|same|previous|prior|above)\b",
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


def is_result_scoped_followup(question: str, *, has_prior_rows: bool) -> bool:
    """True when the question refers to a prior result set (even if empty)."""
    q = question or ""
    if _THIS_RESULT.search(q):
        return True
    if _APPEARS_MOST.search(q) and _FOLLOWUP_HINT.search(q):
        return True
    if _APPEARS_MOST.search(q) and len(q.split()) <= 12:
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
        "query_plan": prior_plan or {"reused_prior_result": True, "frequency_concept": concept},
        "meta": {"investigation_status": "completed", "followup": "frequency"},
    }
