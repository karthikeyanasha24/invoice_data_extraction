"""
Universal Business Intent Classifier: maps natural-language questions to domains.
Deterministic keyword-based classification before SQL generation.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Intent keywords: domain -> list of keywords that indicate that domain
INTENT_KEYWORDS: dict[str, list[str]] = {
    "sales": [
        "sales", "revenue", "product", "customer", "highest sales", "lowest sales",
        "top sales", "top products", "top customers", "revenue by", "sales by",
        "order value", "order quantity", "invoice value", "invoice quantity",
    ],
    "billing": [
        "invoice", "invoices", "billing", "billed", "invoice value", "invoice by",
        "invoice value by customer", "invoice amount",
    ],
    "purchasing": [
        "vendor", "vendors", "supplier", "suppliers", "purchase", "purchasing",
        "purchase order", "PO", "procurement", "vendor spend", "vendor invoice",
        "top vendors", "vendor invoice totals",
    ],
    "logistics": [
        "delivery", "deliveries", "delivered", "shipped", "delivery quantity",
        "delivery value", "deliveries by customer", "delivery by material",
        "route", "stock movement", "goods movement",
    ],
    "finance": [
        "cost", "profit center", "cost center", "GL", "general ledger",
        "posting", "expense", "balance", "cost by profit center",
    ],
    "pricing": [
        "discount", "price", "condition", "pricing", "margin",
    ],
    "inventory": [
        "stock", "inventory", "warehouse", "movement", "reservation",
        "stock quantity", "inventory quantity",
    ],
    "margin": [
        "margin", "revenue vs cost", "compare sales vs", "compare revenue",
        "profitability", "revenue vs invoice",
    ],
]


def classify_intent(question: str) -> Tuple[str, List[str]]:
    """
    Classify question into one or more intent domains.
    Returns (primary_intent, all_matched_intents).
    """
    q = (question or "").strip().lower()
    if not q:
        return "sales", []

    matched: List[str] = []
    for domain, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                matched.append(domain)
                break

    # Deduplicate while preserving order
    seen = set()
    ordered: List[str] = []
    for d in matched:
        if d not in seen:
            seen.add(d)
            ordered.append(d)

    # Primary: first match, or "sales" as default for business queries
    primary = ordered[0] if ordered else "sales"

    logger.debug("intent_classifier: question=%r -> primary=%s, matched=%s", q[:80], primary, ordered)
    return primary, ordered


def get_intent_for_resolver(question: str) -> Optional[str]:
    """
    Return the primary intent for use in semantic resolution.
    Used to narrow metric/dimension lookup when multiple matches exist.
    """
    primary, _ = classify_intent(question)
    return primary


def is_comparison_query(question: str) -> bool:
    """Detect if the question asks to compare two or more metrics/datasets."""
    q = (question or "").strip().lower()
    comparison_phrases = [
        "compare", "versus", "vs", "vs ", " and ", "difference between",
        "sales vs", "revenue vs", "invoice vs", "order vs",
    ]
    return any(p in q for p in comparison_phrases)


def extract_top_n(question: str) -> Optional[int]:
    """Extract 'top N' or 'top N' from question. Returns N or None."""
    q = (question or "").strip().lower()
    m = re.search(r"\btop\s+(\d+)\b", q)
    if m:
        return int(m.group(1))
    m = re.search(r"\bhighest\s+(\d+)\b", q)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s+top\b", q)
    if m:
        return int(m.group(1))
    return None
