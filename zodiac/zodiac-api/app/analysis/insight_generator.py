"""
Insight generator: LLM-produced executive summary, key metrics, and recommendations from query + data.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _waerk_mix_note(rows: List[Dict[str, Any]]) -> str:
    vals: set[str] = set()
    for r in (rows or [])[:400]:
        if not isinstance(r, dict):
            continue
        for k in r.keys():
            if str(k).lower() in ("waerk", "waers", "currency", "curr"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    vals.add(str(v).strip())
    if len(vals) <= 1:
        return ""
    return (
        "Sample rows include multiple currency codes ("
        + ", ".join(sorted(vals)[:6])
        + "); do not imply a single-currency total unless the query groups or filters by currency."
    )


try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None
    _OPENAI_AVAILABLE = False


def _get_client():
    """Get OpenAI client if available."""
    if not _OPENAI_AVAILABLE:
        return None
    try:
        from ..config.config import OPENAI_API_KEY
        if OPENAI_API_KEY:
            return OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        pass
    return None


def generate_analytics_insights(
    question: str,
    rows: List[Dict[str, Any]],
    metrics: Optional[Dict[str, Any]] = None,
    sql: str = "",
    model: str = "gpt-4o-mini",
    max_preview_rows: int = 15,
    global_stats: Optional[Dict[str, Any]] = None,
    representative_rows: Optional[List[Dict[str, Any]]] = None,
    result_scope: Optional[Dict[str, Any]] = None,
    binding_block: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Use LLM to produce:
    - executive_summary: 1–2 sentence summary
    - key_metrics: bullet list of main numbers
    - insights: 2–3 bullet insights
    - recommendations: 1–2 business recommendations

    Returns dict with these keys, or None on failure.
    """
    if not rows or not _OPENAI_AVAILABLE:
        return None
    client = _get_client()
    if not client:
        return None
    preview = representative_rows if representative_rows else rows[:max_preview_rows]
    columns = list(preview[0].keys()) if preview else []
    preview_str = json.dumps(preview, default=str, indent=0)[:3000]
    currency_mix_rule = _waerk_mix_note(preview)
    global_stats_str = json.dumps(global_stats, default=str, indent=2) if global_stats else ""
    result_scope_str = json.dumps(result_scope, default=str, indent=2) if result_scope else ""
    metrics_str = ""
    if metrics:
        parts = []
        for col, m in list(metrics.items())[:8]:
            if isinstance(m, dict):
                total = m.get("total")
                kpi = m.get("kpi_type", "")
                if total is not None:
                    parts.append(f"  {col}: total={total}, kpi={kpi}")
        metrics_str = "\n".join(parts) if parts else ""
    bind = (binding_block or "").strip()
    bind_section = f"\n{bind}\n" if bind else ""

    prompt = f"""You are a SAP analytics assistant. Based on the user's question and the query result, write a concise analytics summary.

User question:
{question}
{bind_section}
Query result columns: {columns}

Sample rows (first {len(preview)}):
{preview_str}

Computed metrics:
{metrics_str or ' (none)'}

GLOBAL_NUMERIC_STATS (source of truth for numeric claims):
{global_stats_str or '(not provided)'}

RESULT_SCOPE (scope of claims):
{result_scope_str or '(not provided)'}

CURRENCY NOTE (if applicable):
{currency_mix_rule or '(single currency or no WAERK in sample — no extra rule)'}

STRICT RULES:
- If GLOBAL_NUMERIC_STATS is provided, the executive_summary MUST agree with it.
- Forbidden: stating "all amounts are 0" (or similar) when GLOBAL_NUMERIC_STATS.count_positive + count_negative > 0.
- Forbidden: claiming "all rows in the dataset/year/table" when RESULT_SCOPE.kind == "limited".
- Required: when RESULT_SCOPE.kind == "limited", explicitly state that findings are based on the returned limited rows.
- If GLOBAL_NUMERIC_STATS.count_negative == 0, say explicitly that there are no net line amounts < 0 in this SQL result set for the filters used.
- If CURRENCY NOTE above lists multiple currencies, the executive_summary MUST state that revenue/amount totals mix currencies and are not additive in one currency unless broken down by WAERK/currency.
- Forbidden: claiming years or periods are "not in the data" or "not available" when sample rows or GLOBAL_NUMERIC_STATS contain year-like columns or 4-digit year values that match the user's question.
- If the user asked about specific years and those years appear in the result, state the numeric outcome for those periods using only values from GLOBAL_NUMERIC_STATS and the sample rows.
- Avoid generic business filler (e.g. unrelated "focus on top customers") unless the question or result columns clearly support it.

Write a JSON object with exactly these keys (no other text):
- executive_summary: 1-2 sentences summarizing the main finding.
- key_metrics: array of 2-5 short strings, each one key metric (e.g. "Total Revenue: $2.7B").
- insights: array of 2-4 short insight bullets.
- recommendations: array of 1-2 short business recommendations.

Return only the JSON object."""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Strip markdown code block if present
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        data = json.loads(text)
        if isinstance(data, dict):
            return {
                "executive_summary": data.get("executive_summary", ""),
                "key_metrics": data.get("key_metrics") or [],
                "insights": data.get("insights") or [],
                "recommendations": data.get("recommendations") or [],
            }
    except Exception as e:
        logger.warning("insight_generator: LLM call failed: %s", e)
    return None
