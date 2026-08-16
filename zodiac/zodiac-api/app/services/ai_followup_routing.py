"""
Heuristics for when a user message should run fresh SQL instead of a no-SQL follow-up.

Used by adaptive_query (Dashboard adaptive panel) and ai_analysis_orchestrator (thread follow-up).

R1: Prefer semantic QueryPlan deltas (ai_query_plan) over brittle token lists.
Legacy drill-down tokens remain as a safety net.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from .ai_query_plan import QueryPlan, follow_up_needs_fresh_sql

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
