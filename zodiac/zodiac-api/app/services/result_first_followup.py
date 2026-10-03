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
_RESULT_RANK = re.compile(
    r"\b(?:which|what)\b.{0,70}\b(?:highest|lowest|largest|smallest|"
    r"top|bottom)\b.{0,70}\b(?:that|this|these|those)\s+"
    r"(?:result|list|rows?|countries?|customers?|products?|materials?)\b",
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
    if _RESULT_RANK.search(q):
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
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _rank_measure_column(rows: List[Dict[str, Any]]) -> Optional[str]:
    """Choose a numeric result measure from returned column names and values."""
    if not rows:
        return None
    keys = list(rows[0].keys())
    preferred = (
        "total billed sales", "total_sales", "billed_sales", "total_revenue",
        "revenue", "sales", "total_amount", "amount", "netwr", "total",
    )
    normalized = {str(key).lower().replace("_", " "): key for key in keys}
    for alias in preferred:
        actual = normalized.get(alias.replace("_", " "))
        if actual is not None and any(_to_float(row.get(actual)) is not None for row in rows):
            return str(actual)
    excluded = ("id", "number", "currency", "year", "month", "period", "rank", "pct", "percent")
    for key in keys:
        name = str(key).lower()
        if any(term in name for term in excluded):
            continue
        if any(_to_float(row.get(key)) is not None for row in rows):
            return str(key)
    return None


def _expand_billing_document_followup(
    question: str,
    rows: List[Dict[str, Any]],
    prior_plan: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Ground a document drill-down in the leading customer row and its scope."""
    q = question or ""
    if not re.search(r"\b(?:billing\s+documents?|invoices?)\b", q, re.I) or not re.search(
        r"\b(?:leading|top|highest|number[- ]one)\s+customer\b|\bcustomer'?s\s+(?:total|sales|revenue)\b",
        q,
        re.I,
    ):
        return None
    measure_col = _rank_measure_column(rows)
    ranked = _rank_by_column(rows, measure_col, descending=True) if measure_col else []
    keys = {str(key).lower(): key for key in (ranked[0].keys() if ranked else [])}
    id_col = next((keys[name] for name in ("customer_id", "kunag", "kunnr", "customer_number") if name in keys), None)
    if not ranked or not id_col or ranked[0].get(id_col) in (None, ""):
        return {
            "mode": "clarification",
            "status": "clarification",
            "answer_status": "CLARIFICATION",
            "sql": "",
            "sql_status": "not_generated",
            "sql_generation_method": "followup_missing_customer_anchor",
            "pipeline": "result_first_followup",
            "rowCount": 0,
            "data": [],
            "summary": (
                "The previous result does not include a customer ID, so I can't reliably "
                "link its leading customer to billing documents. Specify the customer or "
                "rerun the ranking with customer identifiers included."
            ),
            "answer": "Please specify the customer or rerun the ranking with customer identifiers included.",
            "charts": [],
            "query_plan": prior_plan or {},
            "meta": {"investigation_status": "clarification", "followup": "missing_customer_anchor"},
        }

    customer_id = str(ranked[0][id_col]).strip().replace("'", "''")
    if not customer_id:
        return None
    years: List[str] = []
    currency: Optional[str] = None
    plan = prior_plan if isinstance(prior_plan, dict) else {}
    verified = plan.get("verified_db_context") if isinstance(plan.get("verified_db_context"), dict) else {}
    if not verified and isinstance(plan.get("query_plan"), dict):
        verified = (plan["query_plan"].get("verified_db_context") or {})
    semantic = verified.get("semantic_requirements") if isinstance(verified, dict) else {}
    time_filter = (semantic or {}).get("time_filter") if isinstance(semantic, dict) else {}
    if isinstance(time_filter, dict) and time_filter.get("resolved_from_data") is True:
        years = [str(year) for year in (time_filter.get("years") or []) if re.fullmatch(r"\d{4}", str(year))]
    currency_col = keys.get("currency")
    if currency_col and ranked[0].get(currency_col) not in (None, ""):
        currency = str(ranked[0][currency_col]).strip()
    expanded = f"Show the top ten billing documents by billed amount for customer ID '{customer_id}'"
    if years:
        expanded += " in calendar year " + ", ".join(years)
    if currency and re.fullmatch(r"[A-Za-z]{3}", currency):
        expanded += f" in currency {currency}"
    expanded += ", including billing document number, customer, date, and amount."
    return {
        "needs_plan_expansion": True,
        "missing_concept": "billing_documents_for_leading_customer",
        "expanded_question": expanded,
        "query_plan": prior_plan or {},
    }


def _expand_entity_period_followup(
    question: str,
    rows: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Replace a demonstrative entity reference with its verified prior value."""
    q = question or ""
    if not re.search(r"\bthat\s+country\b", q, re.I) or not re.search(
        r"\b(?:sales|revenue|billing|billed)\b[\s\S]{0,80}\b(?:by|per|each)\s+year|\byearly\b",
        q,
        re.I,
    ):
        return None
    row = next((item for item in rows if isinstance(item, dict)), None)
    if not row:
        return None
    keys = {str(key).lower(): key for key in row}
    country_col = next((keys[name] for name in ("country", "land1", "country_code") if name in keys), None)
    if not country_col or row.get(country_col) in (None, ""):
        return None
    country = str(row[country_col]).strip().replace("'", "''")
    expanded = (
        f"Show billed sales by year for country code '{country}' "
        "for the last five complete years available in the data"
    )
    currency_col = keys.get("currency") or keys.get("waerk") or keys.get("waers")
    currency = str(row.get(currency_col) or "").strip() if currency_col else ""
    if re.fullmatch(r"[A-Za-z]{3}", currency):
        expanded += f" in currency {currency}"
    expanded += "."
    return {
        "needs_plan_expansion": True,
        "missing_concept": "verified_entity_period_series",
        "expanded_question": expanded,
    }


def _expand_linked_order_followup(
    question: str,
    rows: List[Dict[str, Any]],
    prior_plan: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Anchor a linked-order lookup to the billing-document IDs in prior rows."""
    q = question or ""
    if not re.search(r"\b(?:sales\s+orders?|orders?)\b", q, re.I) or not re.search(
        r"\b(?:same|those|these|above|previous|prior)\s+(?:billing\s+)?documents?\b|\bthem\b",
        q,
        re.I,
    ):
        return None
    ids: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = next((key for key in row if str(key).lower() in {"billing_document", "invoice_id", "invoice_number", "vbeln"}), None)
        value = str(row.get(key) or "").strip() if key is not None else ""
        if value and value not in ids:
            ids.append(value.replace("'", "''"))
        if len(ids) >= 50:
            break
    if not ids:
        return {
            "mode": "clarification",
            "status": "clarification",
            "answer_status": "CLARIFICATION",
            "sql": "",
            "sql_status": "not_generated",
            "pipeline": "result_first_followup",
            "rowCount": 0,
            "data": [],
            "summary": "The prior answer has no billing-document numbers to use for this link lookup. Run the document list again with document numbers included.",
            "answer": "Please rerun the document list with document numbers included.",
            "query_plan": prior_plan or {},
        }
    literal_ids = ", ".join(f"'{value}'" for value in ids)
    return {
        "needs_plan_expansion": True,
        "missing_concept": "verified_sales_order_links",
        "expanded_question": (
            "List sales orders linked through document flow to billing document IDs: "
            f"{literal_ids}. Return the billing document and linked sales order."
        ),
        "query_plan": prior_plan or {},
    }


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
    if rows:
        entity_period = _expand_entity_period_followup(question, rows)
        if entity_period:
            return entity_period
        linked_order = _expand_linked_order_followup(question, rows, prior_plan)
        if linked_order:
            return linked_order
        document_followup = _expand_billing_document_followup(question, rows, prior_plan)
        if document_followup:
            return document_followup
    if not is_result_scoped_followup(question, has_prior_rows=bool(rows)):
        return None
    # Explaining, summarizing, or asking why requires a model-grounded answer.
    # A reference to "this result" alone is not a frequency/count request.
    if (
        not _GROWTH_RANK.search(question or "")
        and not _APPEARS_MOST.search(question or "")
        and not _RESULT_RANK.search(question or "")
    ):
        return None
    artifact = (prior_plan or {}).get("result_artifact") or {}
    try:
        artifact_truncated = bool(artifact.get("truncated")) or int(artifact.get("row_count") or 0) > len(rows)
    except (TypeError, ValueError):
        artifact_truncated = bool(artifact.get("truncated"))
    if artifact_truncated:
        # A stored sample cannot establish the most frequent entity or largest
        # change across the full result. Re-query rather than claiming accuracy.
        return {
            "needs_plan_expansion": True,
            "missing_concept": "complete_prior_result",
            "query_plan": prior_plan or {},
        }

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

    if _RESULT_RANK.search(question or ""):
        concept = _detect_concept(question)
        labels = _matching_columns(rows, concept) if concept else []
        measure_col = _rank_measure_column(rows)
        if not labels or not measure_col:
            return {
                "needs_plan_expansion": True,
                "missing_concept": concept or "result_dimension_or_measure",
                "query_plan": prior_plan or {},
            }
        descending = not bool(re.search(r"\b(lowest|smallest|least|bottom)\b", question, re.I))
        ranked = _rank_by_column(rows, measure_col, descending=descending)
        if not ranked:
            return {
                "needs_plan_expansion": True,
                "missing_concept": measure_col,
                "query_plan": prior_plan or {},
            }
        label_col = labels[0]
        winner = ranked[0]
        value = winner.get(measure_col)
        summary = (
            f"{winner.get(label_col)} ranks highest in the prior result by {measure_col} ({value})."
            if descending
            else f"{winner.get(label_col)} ranks lowest in the prior result by {measure_col} ({value})."
        )
        return {
            "mode": "result_first",
            "status": "completed",
            "answer_status": "SUCCESS",
            "sql": prior_sql or "",
            "sql_generation_method": "result_first_rank",
            "pipeline": "result_first_followup",
            "rowCount": 1,
            "data": [winner],
            "summary": summary,
            "answer": summary,
            "charts": [],
            "query_plan": prior_plan or {"reused_prior_result": True},
            "meta": {"investigation_status": "completed", "followup": "result_rank"},
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
