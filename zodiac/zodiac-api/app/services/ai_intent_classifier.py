"""
Lightweight intent classification for SAP / Zodiac AI SQL paths.

Maps natural-language questions to intent tags and SQL-shape hints so prompts stay
schema-grounded (no unrelated templates). Optionally returns short clarification prompts
when explicit filters are referenced but underspecified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from .ai_analysis_constraint_validator import extract_user_constraints


@dataclass
class IntentClassification:
    """Intent tags + guidance for LLM SQL generation."""

    tags: List[str] = field(default_factory=list)
    shape_hint: str = ""
    clarification_questions: List[str] = field(default_factory=list)
    time_bucket: Optional[str] = None

    def tag_set(self) -> Set[str]:
        return set(self.tags)


def classify_intent(question: str) -> IntentClassification:
    """
    Classify the question into coarse intent tags (list/detail, aggregate, rank, time,
    billing facets, entities, industry, compare, clarification, etc.).
    """
    q_raw = question or ""
    q = q_raw.strip().lower()
    tags: List[str] = []

    if not q:
        return IntentClassification(tags=[], shape_hint="Ask a specific business question.")

    if re.search(r"\b(list|show\s+all|details|line\s*items|rows)\b", q):
        tags.append("list_detail")
    if re.search(r"\b(sum|total|aggregate|average|avg|revenue|sales\s+value|amount)\b", q):
        tags.append("aggregate")
    if re.search(r"\b(count|how\s+many|number\s+of)\b", q):
        tags.append("count")
    if re.search(r"\b(top|bottom|rank|largest|smallest|highest|lowest|best|worst)\b", q):
        tags.append("rank")
    if re.search(r"\b(year|month|quarter|fkdat|fiscal|calendar)\b", q) or re.search(
        r"\b(19|20)\d{2}\b", q
    ):
        tags.append("time_filter")
    time_bucket: Optional[str] = None
    if re.search(r"\bmonth|monthly|per\s+month|by\s+month\b", q):
        tags.append("time_bucket_month")
        time_bucket = "month"
    if re.search(r"\b(negative|credit\s+memo|returns?)\b", q):
        tags.append("negative_credit_lines")
    if re.search(r"\b(billing\s*category|fktyp)\b", q):
        tags.append("billing_category")
    if re.search(r"\b(billing\s*type|fkart)\b", q):
        tags.append("billing_type")
    if re.search(r"\b(currency|waerk|waers)\b", q):
        tags.append("currency")
    if re.search(r"\b(customer|sold-?to|kunnr|account)\b", q):
        tags.append("customer")
    if re.search(r"\b(product|material|matnr|sku)\b", q):
        tags.append("product_material")
    if re.search(r"\b(industry|sector|brsch|t016)\b", q):
        tags.append("industry")
    if re.search(r"\b(compare|versus| vs |difference\b)", q):
        tags.append("compare")

    # SQL shape guidance for the LLM (short)
    shape_parts: List[str] = []
    if "count" in tags and "aggregate" not in tags:
        shape_parts.append("Prefer COUNT(DISTINCT billing document) or COUNT(*) as appropriate; do not use only SUM(amount) unless the user asks for value.")
    if "negative_credit_lines" in tags:
        shape_parts.append("Use VBRP line amounts; filter netwr_numeric < 0 only if the user asked for negative lines; otherwise ORDER BY amount ASC.")
    if "rank" in tags:
        shape_parts.append("Use ORDER BY ... DESC/ASC with LIMIT N; ensure the ORDER BY uses the same numeric expression as the SELECT list.")
    if "time_filter" in tags:
        shape_parts.append("For SAP billing calendar year, filter on VBRK.fkdat (YYYYMMDD text), not gjahr.")
    if "time_bucket_month" in tags:
        shape_parts.append("Month intent requires monthly bucketed SQL: derive month from VBRK.fkdat (YYYY-MM or YYYYMM), GROUP BY that bucket, and aggregate values per month.")
    if "industry" in tags:
        shape_parts.append("Join KNA1 to T016T for industry text only when the user asked for industry / sector breakdown.")

    shape_hint = " ".join(shape_parts) if shape_parts else "Follow the user question literally; do not substitute a different breakdown dimension."

    clar: List[str] = []
    uc = extract_user_constraints(q_raw)
    if ("billing_category" in tags or re.search(r"\bbilling\s+category\b|\bfktyp\b", q)) and not uc.billing_category:
        if not re.search(r"\b(list|distinct|values|possible|categories)\b", q):
            clar.append(
                "Which **billing category code** (VBRK.FKTYP, e.g. M/O/P) should I filter on?"
            )
    if ("billing_type" in tags or re.search(r"\bbilling\s+type\b|\bfkart\b", q)) and not uc.billing_type:
        if not re.search(r"\b(list|distinct|values|possible|types)\b", q):
            clar.append(
                "Which **billing type** (VBRK.FKART) should I filter on?"
            )

    return IntentClassification(
        tags=tags,
        shape_hint=shape_hint,
        clarification_questions=clar,
        time_bucket=time_bucket,
    )


def build_intent_sql_prompt_block(question: str) -> str:
    """Compact block appended to schema-driven SQL prompts."""
    c = classify_intent(question)
    tags = ", ".join(c.tags) if c.tags else "(general)"
    lines = [
        "Intent classification (follow these; do not answer a different question):",
        f"- Tags: {tags}",
        f"- SQL shape: {c.shape_hint}",
        "- Use only columns present in the schema excerpt. Use CAST(NULLIF(TRIM(CAST(v.\"netwr\" AS TEXT)), '') AS NUMERIC) for VBRP netwr when aggregating or sorting.",
        "- For calendar year on billing, filter with SUBSTRING(TRIM(\"VBRK\".\"fkdat\"),1,4) = 'YYYY' (never rely on gjahr='0000').",
        "- Join VBRP to VBRK: LPAD(TRIM(v.\"vbeln\"),10,'0') = LPAD(TRIM(r.\"vbeln\"),10,'0').",
    ]
    if c.time_bucket == "month":
        lines.append(
            "- Month bucket is mandatory: SELECT month_bucket from VBRK.fkdat and GROUP BY month_bucket (do not return raw line-level fkdat rows for 'by month' questions)."
        )
    return "\n".join(lines)


def maybe_clarification_reply(question: str) -> Optional[str]:
    """
    If the question references underspecified filters, return 1–3 short questions.
    Otherwise None (caller can run SQL).
    """
    c = classify_intent(question)
    if not c.clarification_questions:
        return None
    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(c.clarification_questions[:3]))
    return (
        "I need a bit more detail before running SQL:\n\n"
        f"{numbered}\n\n"
        "Reply with the values you want (or say **list categories** to see distinct FKTYP/FKART values)."
    )
