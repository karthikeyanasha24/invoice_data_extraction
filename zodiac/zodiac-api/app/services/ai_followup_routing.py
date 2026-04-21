"""
Heuristics for when a user message should run fresh SQL instead of a no-SQL follow-up.

Used by adaptive_query (Dashboard adaptive panel) and ai_analysis_orchestrator (thread follow-up).
"""
from __future__ import annotations

import re

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

# Substrings (lowercased question) — high recall for ERP drill-down phrasing
_EXTRA_DRILL_TOKENS = (
    "breakdown",
    "by product",
    "by material",
    "product level",
    "line item",
    "line items",
    "item level",
    "per material",
    "per product",
    "each product",
    "each material",
    "matnr",
    "sku",
    "article number",
    "material number",
    " mara",
    " makt",
    " marc",
    " mvke",
    " mean",
    "ean",
    "barcode",
    "vbrp",
    "posnr",
    "billing item",
    "deeper",
    " drill",
    "drill ",
    "granular",
    "detail by",
    "split by",
    "for each sku",
    "plant-level",
    "valuation",
    "extend the query",
    "modify the query",
    "new query",
    "run sql",
    "different columns",
    "add columns",
    "also include",
    "join to",
    "join with",
    "which billing documents",
    "billing documents",
    "which products",
    "products are showing",
    "which industry",
    "industry are these products",
    "reason of negative sales",
    "reason for negative sales",
    "why negative sales",
    "profit margin",
    "margin of the products",
    "deeper analysis",
)

_INV_DOC_HEADER_TOKENS = (
    "zero invoice",
    "negative invoice",
    "invoice total",
    "header total",
    "billing document total",
    "document total",
    "vbrk",
)


def _has_token(text: str, token: str) -> bool:
    """
    Safer token check than plain substring:
    - single-word tokens use word boundaries (avoid false positives like "means" -> "mean")
    - multi-word tokens keep phrase matching
    """
    t = (token or "").strip().lower()
    if not t:
        return False
    if " " in t:
        return t in text
    return re.search(rf"\b{re.escape(t)}\b", text) is not None


def follow_up_requires_fresh_sql(question: str) -> bool:
    """True when the user is asking for data the prior result set cannot answer without a new SELECT."""
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
    return False
