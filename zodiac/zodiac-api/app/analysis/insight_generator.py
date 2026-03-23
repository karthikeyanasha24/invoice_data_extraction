"""
Insight generator: LLM-produced executive summary, key metrics, and recommendations from query + data.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
    global_stats_str = json.dumps(global_stats, default=str, indent=2) if global_stats else ""
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
    prompt = f"""You are a SAP analytics assistant. Based on the user's question and the query result, write a concise analytics summary.

User question:
{question}

Query result columns: {columns}

Sample rows (first {len(preview)}):
{preview_str}

Computed metrics:
{metrics_str or ' (none)'}

GLOBAL_NUMERIC_STATS (source of truth for numeric claims):
{global_stats_str or '(not provided)'}

STRICT RULES:
- If GLOBAL_NUMERIC_STATS is provided, the executive_summary MUST agree with it.
- Forbidden: stating "all amounts are 0" (or similar) when GLOBAL_NUMERIC_STATS.count_positive + count_negative > 0.
- If GLOBAL_NUMERIC_STATS.count_negative == 0, say explicitly that there are no net line amounts < 0 in this SQL result set for the filters used.

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
