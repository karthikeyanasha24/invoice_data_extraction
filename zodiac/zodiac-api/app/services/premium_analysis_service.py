"""
Premium analysis service: pre-built queries with full joins + LLM adaptation.
Supports profit margin analysis and other deep-dive analyses.
Can be triggered by button (action) or by intent detection.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PREMIUM_QUERIES: Optional[Dict[str, Any]] = None


def load_premium_queries() -> Dict[str, Any]:
    """Load premium_analysis_queries.json."""
    global _PREMIUM_QUERIES
    if _PREMIUM_QUERIES is not None:
        return _PREMIUM_QUERIES
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "premium_analysis_queries.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _PREMIUM_QUERIES = json.load(f)
            return _PREMIUM_QUERIES or {}
    except Exception as e:
        logger.debug("premium_analysis: could not load: %s", e)
    _PREMIUM_QUERIES = {}
    return {}


def is_margin_or_profitability_question(question: str) -> bool:
    """Detect if the question asks for margin/profitability analysis."""
    q = (question or "").strip().lower()
    keywords = [
        "profit margin", "margin analysis", "margin by product", "product margin",
        "profitability", "revenue vs cost", "gross margin", "contribution margin",
        "how are profit margins calculated", "margin report", "profit margin report",
        "deeper analysis", "product data analysis", "margin by customer",
    ]
    return any(kw in q for kw in keywords)


def get_margin_semantic_context() -> str:
    """Return semantic context for margin/profitability for LLM prompt injection."""
    data = load_premium_queries()
    ctx = data.get("margin_semantic_context") or ""
    if ctx:
        return f"**Profit margin context:** {ctx}"
    return (
        "**Profit margin:** Revenue from VBRP.NETWR, cost from CKIS.WERTN (cost estimate) or EKPO. "
        "Join VBRP to VBRK on VBELN; VBRP to MAKT on MATNR; VBRP to CKIS via MATNR. "
        "Margin = Revenue - COGS. Margin % = (Revenue - COGS)/Revenue*100."
    )


def get_premium_query_for_question(
    question: str,
    available_tables: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Find a premium analysis that matches the question.
    Returns analysis dict with base_sql, or None.
    """
    if not question or not question.strip():
        return None
    q = (question or "").strip().lower()
    data = load_premium_queries()
    analyses = data.get("analyses") or []
    avail = {t.upper().strip('"') for t in (available_tables or [])} if available_tables else None

    for a in analyses:
        keywords = a.get("trigger_keywords") or []
        patterns = a.get("trigger_patterns") or []
        tables = a.get("tables") or []
        if avail:
            missing = [t for t in tables if (t or "").upper().strip('"') not in avail]
            if missing:
                continue
        if any(kw in q for kw in keywords):
            return a
        if any(p in q for p in patterns):
            return a
    return None


def get_base_sql_for_premium(
    question: str,
    available_tables: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Return the base SQL for a matching premium analysis.
    Used when user triggers via button or intent.
    """
    analysis = get_premium_query_for_question(question, available_tables)
    if analysis:
        return analysis.get("base_sql")
    return None


def adapt_premium_query_with_llm(
    base_sql: str,
    user_question: str,
    analysis_meta: Dict[str, Any],
    client: Any,
) -> Optional[str]:
    """
    Use LLM to adapt the base SQL to the user's specific question.
    E.g. add "top 20", "by year", "filter by product X", etc.
    """
    if not base_sql or not client:
        return base_sql

    prompt = f"""You are an SAP SQL expert. Adapt this base query to better answer the user's question.

**Base query (profit margin by product):**
```sql
{base_sql[:2000]}
```

**User question:** {user_question}

**Rules:**
- Keep the core margin logic (revenue, cost, margin, margin_pct)
- You MAY add: LIMIT N (e.g. top 20), WHERE filters (year, product name), ORDER BY changes
- You MAY change GROUP BY to add customer, year, plant if the question asks for it
- Use ONLY tables/columns that exist in the base query
- Return ONLY valid PostgreSQL SQL, no explanation
- If the question is generic ("profit margin"), return the base query unchanged
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=800,
        )
        text = (resp.choices[0].message.content or "").strip()
        if "```" in text:
            m = re.search(r"```(?:\w*)\n?([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        if text.upper().startswith("SELECT"):
            return text if text.endswith(";") else text + ";"
    except Exception as e:
        logger.warning("premium_analysis: LLM adapt failed: %s", e)
    return base_sql
