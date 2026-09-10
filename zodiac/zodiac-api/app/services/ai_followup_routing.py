"""
Heuristics for when a user message should run fresh SQL instead of a no-SQL follow-up.

Used by adaptive_query (Dashboard adaptive panel) and ai_analysis_orchestrator (thread follow-up).

R1: Prefer semantic QueryPlan deltas (ai_query_plan) over brittle token lists.
Legacy drill-down tokens remain as a safety net.

Turn classification (internal): previous context is an input, never proof of continuation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .ai_query_plan import QueryPlan, follow_up_needs_fresh_sql
from .adaptive_nl_sql_hardening import is_greeting_or_chitchat, is_supported_business_question


class TurnIntent:
    """Internal route labels — never shown in user-facing copy."""

    NEW_ANALYTICAL_QUERY = "NEW_ANALYTICAL_QUERY"
    FOLLOWUP_DELTA = "FOLLOWUP_DELTA"
    NEW_ANALYTICAL_QUERY_WITH_CONTEXT = "NEW_ANALYTICAL_QUERY_WITH_CONTEXT"
    NON_BUSINESS = "NON_BUSINESS"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


@dataclass
class TurnClassification:
    intent: str
    reason: str
    plan: Optional[QueryPlan] = None


_TRUE_DELTA_PREFIXES = (
    "add_filter:",
    "remove_filter:",
    "change_ranking:",
    "change_time:",
    "change_metric:",
    "change_grain:",
    "add_dimension:",
    "remove_dimension:",
    "ensure_dimension:",
)

_FOLLOWUP_UTTERANCE = re.compile(
    r"(?x)^\s*("
    r"(now\s+|then\s+)?(only|just)\b.*"
    r"|(now\s+|then\s+)?((show|give)\s+(me\s+)?)?(the\s+)?(top|bottom)\s+\d+\b.*"
    r"|compare\s+(with|to|vs|versus)\b.*"
    r"|(remove|clear|drop)\b.{0,40}\b(filter|trading|industry)\b.*"
    r"|.*\binstead\b.*"
    r"|(the\s+)?(top|bottom)\s+\d+(\s+(only|please))?"
    r"|trading"
    r"|count"
    r"|sales"
    r"|invoice\s+count"
    r"|highest\s+industry"
    r"|lowest\s+sales"
    r"|remove\s+trading"
    r"|(19|20)\d{2}"
    r"|filter\s+(to|by)\b.*"
    r")\s*\??\s*$",
    re.IGNORECASE,
)

_STANDALONE_VERB = re.compile(
    r"\b(show|what (are|were|is|was)|who|which|how many|list|give me)\b",
    re.IGNORECASE,
)
_STANDALONE_METRIC = re.compile(
    r"\b(sales|revenue|invoice count|invoices|customers?|products?)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_TURN = re.compile(
    r"(?x)^\s*("
    r"what\s+about\b(?!.*\b(trading|industry|customer|sales|invoice|year|20\d{2})\b).*"
    r"|(and|also)\s+(that|this|those)\??"
    r")\s*$",
    re.IGNORECASE,
)
_NON_ANALYTICAL_TOPIC = re.compile(
    r"(?x)"
    r"\bmeaning of life\b"
    r"|\btell me a joke\b"
    r"|\bfavorite color\b"
    r"|\bweather\b"
    r"|\bwho invented the telephone\b"
    r"|\bceo of microsoft\b"
    r"|^(explain(\s+what)?\s+sap(\s+is|\s+means)?)\s*\??$"
    r"|\bwho is the president\b",
    re.IGNORECASE,
)

_DRILL_DOWN_OR_FRESH_SQL = re.compile(
    r"\b("
    r"breakdown|break down|drill[\s-]?down|"
    r"deeper analysis|go deeper|dig deeper|deeper\b|"
    r"product level|line level|line item|line items|item level|"
    r"by product|per product|each product|every product|product name|product names|"
    r"material level|by material|per material|each material|"
    r"\bmatnr\b|\bsku\b|"
    r"billing items|billing lines|invoice lines|invoice items|"
    r"show (each |all )?items|list (each |all )?items|"
    r"granular|granularity|"
    r"split by|slice by|group by product|group by material|"
    r"for (these|those|the same) (invoice|invoices|rows|results?)|"
    r"same (invoice|invoices|billing)|"
    r"filter (to|down)|narrow (to|down)|subset|"
    r"run (a |the )?(query|sql)|fresh (query|sql|data)|new (query|sql)|"
    r"show (me )?the (lines|items)|at item level"
    r")\b",
    re.IGNORECASE,
)

_EXTRA_DRILL_TOKENS = (
    "breakdown", "by product", "by material", "product level", "line item", "line items",
    "item level", "per material", "per product", "each product", "each material", "matnr",
    "sku", "article number", "material number", " mara", " makt", " marc", " mvke", " mean",
    "ean", "barcode", "vbrp", "posnr", "billing item", "deeper", " drill", "drill ",
    "granular", "detail by", "split by", "for each sku", "plant-level", "valuation",
    "extend the query", "modify the query", "new query", "run sql", "different columns",
    "add columns", "also include", "join to", "join with", "which billing documents",
    "billing documents", "which products", "products are showing", "which industry",
    "industry are these products", "reason of negative sales", "reason for negative sales",
    "why negative sales", "profit margin", "margin of the products", "deeper analysis",
)

_INV_DOC_HEADER_TOKENS = (
    "zero invoice", "negative invoice", "invoice total", "header total",
    "billing document total", "document total", "vbrk",
)


def _has_token(text: str, token: str) -> bool:
    t = (token or "").strip().lower()
    if not t:
        return False
    if " " in t:
        return t in text
    return re.search(rf"\b{re.escape(t)}\b", text) is not None


def _legacy_follow_up_requires_fresh_sql(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()
    if _DRILL_DOWN_OR_FRESH_SQL.search(q):
        return True
    if any(_has_token(ql, t) for t in _EXTRA_DRILL_TOKENS):
        return True
    if any(_has_token(ql, t) for t in _INV_DOC_HEADER_TOKENS):
        return True
    if re.search(r"\b(select|from)\b.+\bwhere\b", q, re.I):
        return True
    if re.search(r"\b(19|20)\d{2}\b", q):
        return True
    if (
        re.search(r"\b(highest|lowest|top|bottom|best|worst|total|sum|average|show me)\b", ql)
        and re.search(
            r"\b(by|per)\s+(customer|customers|product|products|material|materials|"
            r"vendor|vendors|supplier|suppliers|country|countries|industry|industries|"
            r"year|month|plant|region)\b",
            ql,
        )
    ):
        return True
    return False


def resolve_follow_up_sql_need(
    question: str,
    previous_question: str = "",
    previous_sql: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, QueryPlan]:
    needs, plan = follow_up_needs_fresh_sql(
        followup_question=question,
        previous_question=previous_question,
        previous_sql=previous_sql,
        previous_plan=previous_plan,
    )
    if needs:
        return True, plan
    if _legacy_follow_up_requires_fresh_sql(question):
        plan.needs_fresh_sql = True
        if "legacy_drill_token" not in plan.delta_ops:
            plan.delta_ops = list(plan.delta_ops) + ["legacy_drill_token"]
        return True, plan
    return False, plan


def follow_up_requires_fresh_sql(
    question: str,
    previous_question: str = "",
    previous_sql: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when follow-up needs a new SELECT. Uses semantic plan when context is present."""
    if previous_question or previous_sql or previous_plan:
        needs, _plan = resolve_follow_up_sql_need(
            question, previous_question, previous_sql, previous_plan
        )
        return needs
    needs, _plan = follow_up_needs_fresh_sql(question, "", "", None)
    if needs:
        return True
    return _legacy_follow_up_requires_fresh_sql(question)


def looks_like_followup_utterance(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    # Complete "top N X by Y" rankings are standalone questions, not follow-up fragments.
    if re.search(
        r"^\s*top\s+\d+\s+(materials?|products?|customers?)\s+by\s+",
        q,
        re.I,
    ):
        return False
    return bool(_FOLLOWUP_UTTERANCE.match(q))


def looks_like_standalone_analytical(question: str) -> bool:
    """Complete restatement that must replace active analytical state, not patch it."""
    q = (question or "").strip()
    if not q or looks_like_followup_utterance(q):
        return False
    has_verb = bool(_STANDALONE_VERB.search(q))
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", q))
    has_metric = bool(_STANDALONE_METRIC.search(q))
    if has_verb and has_year and has_metric:
        return True
    if has_verb and has_metric and len(q) >= 24:
        return True
    # Canonical ranking form after the interrogative normalizer ("Who had the
    # highest sales in 2004?" → "top customers by sales in 2004").
    if re.search(
        r"\btop\s+(\d+\s+)?(customers?|countries|industries|products?)\s+by\s+(sales|revenue)\b",
        q,
        re.I,
    ):
        return True
    if re.search(
        r"^\s*top\s+\d+\s+(materials?|products?|customers?)\s+by\s+",
        q,
        re.I,
    ):
        return True
    if has_year and has_metric and re.search(r"\b(highest|who|which)\b", q, re.I):
        return True
    return False


def has_active_analysis_state(
    previous_sql: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
    previous_status: str = "",
) -> bool:
    """True when there is a prior successful analytical query to modify.

    CLARIFICATION / ERROR are not active analysis. CANNOT_ANSWER with preserved
    deep analytical_context still counts — data-gap turns must not break chains.
    """
    if isinstance(previous_plan, dict):
        ac = previous_plan.get("analytical_context")
        if isinstance(ac, dict) and ac.get("deep_analysis"):
            return True
        if previous_plan.get("deep_analysis"):
            return True
    status = (previous_status or "").strip().upper()
    if status in {"CLARIFICATION", "ERROR"}:
        return False
    if status == "CANNOT_ANSWER":
        return False
    sql = (previous_sql or "").strip()
    if sql and re.search(r"\bselect\b", sql, re.I):
        return True
    if isinstance(previous_plan, dict) and (
        previous_plan.get("delta_ops")
        or previous_plan.get("filters")
        or previous_plan.get("dimensions")
        or previous_plan.get("limit")
        or previous_plan.get("comparison_years")
    ):
        return True
    return False


def has_preserved_deep_context(
    previous_plan: Optional[Dict[str, Any]] = None,
    previous_status: str = "",
) -> bool:
    """Deep analytical context survives data-gap turns."""
    if not isinstance(previous_plan, dict):
        return False
    ac = previous_plan.get("analytical_context")
    if isinstance(ac, dict) and ac.get("deep_analysis"):
        return True
    return bool(previous_plan.get("deep_analysis"))


def _is_true_followup_delta(plan: QueryPlan) -> bool:
    for op in plan.delta_ops or []:
        if op in {"narrative", "initial"}:
            continue
        if op == "legacy_drill_token":
            return True
        if any(str(op).startswith(p) for p in _TRUE_DELTA_PREFIXES):
            return True
    return False


def is_prior_general_chat(
    previous_plan: Optional[Dict[str, Any]] = None,
    previous_status: str = "",
    previous_sql: str = "",
) -> bool:
    """True when the last turn was a general LLM reply (no SAP SQL)."""
    sql = (previous_sql or "").strip()
    if sql and re.search(r"\bselect\b", sql, re.I):
        return False
    if not isinstance(previous_plan, dict):
        return False
    if str(previous_plan.get("last_mode") or "").lower() == "general_chat":
        return True
    inv = previous_plan.get("investigation_state")
    if isinstance(inv, dict) and str(inv.get("mode") or "").lower() == "general_chat":
        return True
    p1 = previous_plan.get("pipeline1")
    if isinstance(p1, dict):
        qt = str(p1.get("question_type") or "").lower()
        if qt in {"greeting", "general_conversation", "general_knowledge"}:
            return True
    meta = previous_plan.get("meta")
    if isinstance(meta, dict) and str(meta.get("mode") or "").lower() == "general_chat":
        return True
    return False


def should_route_to_general_chat(
    question: str,
    turn: TurnClassification,
    *,
    previous_plan: Optional[Dict[str, Any]] = None,
    previous_status: str = "",
    previous_sql: str = "",
) -> bool:
    """Route to orchestrator Pipeline 1 general path (Gemini-style chat), not SQL compilers."""
    if is_prior_general_chat(previous_plan, previous_status, previous_sql):
        return True
    if is_greeting_or_chitchat(question):
        return True
    if turn.intent == TurnIntent.NON_BUSINESS and turn.reason != "unsafe_or_non_business":
        return True
    if turn.intent == TurnIntent.CLARIFICATION_REQUIRED and turn.reason == "no_business_signal":
        return True
    return False


def classify_turn(
    question: str,
    previous_question: str = "",
    previous_sql: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
    previous_status: str = "",
) -> TurnClassification:
    """Classify this user turn before any SQL, delta, narration, or chart path.

    Previous context informs the decision; it never forces FOLLOWUP_DELTA by itself.
    """
    q = (question or "").strip()
    ql = q.lower()
    has_active = has_active_analysis_state(previous_sql, previous_plan, previous_status)
    has_deep = has_preserved_deep_context(previous_plan, previous_status)

    if _NON_ANALYTICAL_TOPIC.search(ql):
        return TurnClassification(TurnIntent.NON_BUSINESS, "non_analytical_topic")

    allowed, gate_reason = is_supported_business_question(
        q, has_active_analysis=has_active or has_deep, previous_plan=previous_plan
    )
    if not allowed:
        if gate_reason in {"non_business", "unsafe_or_non_business", "greeting"}:
            return TurnClassification(TurnIntent.NON_BUSINESS, gate_reason)
        if _AMBIGUOUS_TURN.match(q):
            return TurnClassification(TurnIntent.CLARIFICATION_REQUIRED, "ambiguous")
        return TurnClassification(TurnIntent.CLARIFICATION_REQUIRED, gate_reason)

    if _AMBIGUOUS_TURN.match(q):
        return TurnClassification(TurnIntent.CLARIFICATION_REQUIRED, "ambiguous")

    if not has_active:
        return TurnClassification(TurnIntent.NEW_ANALYTICAL_QUERY, "fresh_turn")

    if looks_like_standalone_analytical(q):
        return TurnClassification(TurnIntent.NEW_ANALYTICAL_QUERY, "standalone_restatement")

    needs_sql, plan = resolve_follow_up_sql_need(
        q,
        previous_question=previous_question,
        previous_sql=previous_sql,
        previous_plan=previous_plan,
    )
    followup_shape = looks_like_followup_utterance(q)
    if followup_shape or (needs_sql and _is_true_followup_delta(plan)):
        return TurnClassification(TurnIntent.FOLLOWUP_DELTA, "recognized_delta", plan)

    return TurnClassification(
        TurnIntent.NEW_ANALYTICAL_QUERY_WITH_CONTEXT,
        "business_with_context_not_delta",
        plan,
    )
