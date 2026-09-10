"""Deterministic normalizer for interrogative sales/revenue ranking questions.

Business users phrase a ranking request many ways ("which customer had the
highest sales?", "who generated the most revenue?"). The governed engine already
answers the canonical form ("top customers by sales with country and industry"),
so this module rewrites the interrogative/indirect phrasings into that canonical
form BEFORE classification. It never invents data, never bypasses governance, and
is intentionally narrow: it only fires on sales/revenue ranking questions and
leaves profit/margin/COGS/count/inventory/supplier questions untouched so the
frozen R3-R4-4 contracts are unaffected.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Metric words that this normalizer is allowed to handle. Anything else
# (profit, margin, cogs, cost, count, quantity, inventory, supplier ...) is a
# different governed intent and must NOT be rewritten here.
_SALES_METRIC = re.compile(r"\b(sales|revenue|turnover|billings?)\b", re.I)

# Presence of any of these means a different governed intent owns the question.
_EXCLUDE = re.compile(
    r"\b(profit|margin|cogs|cost|costs|count|counts|quantity|qty|inventory|stock|"
    r"supplier|suppliers|purchase|purchasing|concentration|aging|expiry|expiring|"
    r"logistics|freight|hhi|net\s+profit|"
    r"sales\s+orders?|sales-order|vbak|vbap|vbed|vbep)\b",
    re.I,
)

# Advanced analytical shapes must NEVER be rewritten into a plain ranking —
# doing so strips period comparison / partition / negation / relative-date semantics
# and can cause wrong SUCCESS answers.
_ADVANCED_SEMANTICS = re.compile(
    r"\b(growth|increase[sd]?|decrease[sd]?|decline[sd]?|change|difference|delta|"
    r"year[- ]over[- ]year|yoy|between\s+(?:19|20)\d{2}|"
    r"in each|per country|per customer|for each|within each|"
    r"without|with no|no invoices?|not exist|never|"
    r"last month|last week|last quarter|last year|this month|this week|ytd|mtd|"
    r"above average|below average|share|percent(?:age)? of)\b",
    re.I,
)

# Interrogative / indirect-question markers.
_INTERROGATIVE = re.compile(
    r"(^|\b)(which|what|who|whom)\b|\b(show me which|can you show me which|"
    r"tell me which|identify which|find which)\b",
    re.I,
)

# Ranking words.
_RANK = re.compile(
    r"\b(highest|most|largest|biggest|greatest|top|leading|maximum|max|"
    r"best[- ]selling|highest[- ]value)\b",
    re.I,
)

# Dimension synonyms -> canonical plural noun the engine understands.
_DIM_SYNONYMS = [
    ("customers", r"\b(customers?|clients?|buyers?|accounts?)\b"),
    ("products", r"\b(products?|materials?|skus?|items?)\b"),
    ("countries", r"\b(countr(?:y|ies)|nations?|markets?|regions?|geograph\w*)\b"),
    ("industries", r"\b(industr(?:y|ies)|sectors?)\b"),
]

# Priority for choosing the PRIMARY dimension being ranked. Only dimensions whose
# canonical "top <dim> by sales" form returns the CORRECT dimension are allowed as
# a primary; "industries"/"products" as a primary currently route to a different
# dimension in the governed engine, so we do NOT rewrite those (an honest failure
# is better than a wrong-dimension answer). They may still appear as attributes.
_PRIMARY_ORDER = ["customers", "countries"]


def _extract_years(q: str) -> List[str]:
    return re.findall(r"\b(?:19|20)\d{2}\b", q)


def _extract_limit(q: str) -> Optional[int]:
    m = re.search(r"\btop\s+(\d{1,3})\b", q, re.I)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _dims_present(q: str) -> List[str]:
    out: List[str] = []
    for canon, pat in _DIM_SYNONYMS:
        if re.search(pat, q, re.I) and canon not in out:
            out.append(canon)
    return out


def is_sales_ranking_question(q: str) -> bool:
    q = q or ""
    if not _SALES_METRIC.search(q):
        return False
    if _EXCLUDE.search(q):
        return False
    if _ADVANCED_SEMANTICS.search(q):
        return False
    if not _RANK.search(q):
        return False
    if not _INTERROGATIVE.search(q):
        return False
    return True


def normalize_ranking_question(question: str) -> str:
    """Return a canonical 'top <dim> by sales [with ...] [in ...]' rewrite when the
    input is an interrogative sales/revenue ranking question; otherwise return the
    original string unchanged."""
    q = (question or "").strip()
    if not q or not is_sales_ranking_question(q):
        return question

    dims = _dims_present(q)
    who_only = bool(re.search(r"\bwho(m)?\b", q, re.I)) and not dims
    if who_only:
        dims = ["customers"]  # "who had the highest sales" -> customers
    if not dims:
        return question  # ranking metric but no recognizable dimension -> leave it

    # Primary = highest-priority ALLOWED dimension mentioned; the rest become
    # attributes. If no allowed primary is present (e.g. industry-only or
    # product-only ranking), leave the question unchanged rather than risk a
    # wrong-dimension answer.
    primary = next((d for d in _PRIMARY_ORDER if d in dims), None)
    if primary is None:
        return question
    extras = [d for d in dims if d != primary]

    limit = _extract_limit(q)
    # Singular superlative ("which country generated the most…") must stay top-1.
    # Rewriting to plural "top countries" invents a default top-10 and fails the
    # original-question hard gate ("ranking limit was not applied").
    singular_superlative = bool(
        not limit
        and re.search(r"\b(which|what|who)\b", q, re.I)
        and re.search(r"\b(highest|most|largest|biggest|greatest|best|lowest|least|worst|smallest)\b", q, re.I)
        and not re.search(r"\btop\s+\d+\b", q, re.I)
        and (
            re.search(r"\b(country|customer|client|buyer|product|material|industry|nation|market)\b", q, re.I)
            or who_only
        )
    )
    # Multi-dimensional superlative (country + customer + industry) — keep original
    # phrasing so the multidim template can return LIMIT 1 with all dimensions.
    if (
        not limit
        and re.search(r"\b(highest|most|best|largest|biggest|lowest|worst)\b", q, re.I)
        and {"countries", "industries"}.issubset(set(extras))
    ):
        return question
    if singular_superlative:
        # Canonical singular form preserves LIMIT 1 via extract_ranking_limit / ops.
        singular_map = {
            "customers": "customer",
            "countries": "country",
            "products": "product",
            "industries": "industry",
        }
        dim_s = singular_map.get(primary, primary.rstrip("s"))
        metric = "revenue" if re.search(r"\brevenue\b", q, re.I) else "sales"
        years = _extract_years(q)
        parts = [f"top {dim_s} by {metric}"]
        if years:
            parts.append("in " + " and ".join(sorted(set(years))))
        return " ".join(parts)

    metric = "revenue" if re.search(r"\brevenue\b", q, re.I) else "sales"
    years = _extract_years(q)

    parts = ["top"]
    if limit:
        parts.append(str(limit))
    parts.append(primary)
    parts.append("by")
    parts.append(metric)
    if extras:
        parts.append("with " + " and ".join(extras))
    if years:
        uniq = sorted(set(years))
        parts.append("in " + " and ".join(uniq))
    return " ".join(parts)
