"""
Deterministic, intent-locked summaries (no generic filler).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,d}"
    return str(v)


def generate_summary(intent: Dict[str, Any], rows: List[Dict[str, Any]], validation: Dict[str, Any]) -> str:
    if not validation.get("valid"):
        return (
            "```json\n"
            + str(
                {
                    "error": "RESULT_MISMATCH",
                    "reason": "; ".join(validation.get("errors") or ["Result did not match intent"]),
                }
            )
            + "\n```"
        )
    it = str(intent.get("intent_type") or "")
    metric = intent.get("metric") or {}
    metric_alias = str(metric.get("alias") or metric.get("logical") or "value")
    dims = intent.get("dimensions") or []
    dim0 = dims[0] if dims else None
    dim_key = str((dim0 or {}).get("alias") or (dim0 or {}).get("logical") or "") if dim0 else ""

    if not rows:
        return "No rows returned for this query."

    # Raw inspection: factual
    if it == "raw_inspection":
        cols = list(rows[0].keys())
        return (
            f"Returned **{len(rows)}** row(s).\n\n"
            f"- **Columns**: {', '.join(cols[:16])}{'…' if len(cols) > 16 else ''}\n"
        )

    # Trend: mention peak
    if it == "trend" and dim_key and metric_alias in rows[0]:
        best = None
        best_v = None
        for r in rows:
            v = r.get(metric_alias)
            if isinstance(v, (int, float)):
                if best_v is None or float(v) > float(best_v):
                    best_v = float(v)
                    best = r
        if best is not None:
            return (
                f"**{metric.get('logical', metric_alias)} over {dim_key}** shows the peak in "
                f"**{best.get(dim_key)}** at **{_fmt(best_v)}**."
            )

    # Ranking
    if it == "ranking" and dim_key:
        top = rows[0]
        return (
            f"Top **{dim_key}** is **{top.get(dim_key)}** with **{_fmt(top.get(metric_alias))}** "
            f"{metric.get('logical', metric_alias)}."
        )

    # Comparison (assumes year/period dimension)
    if it == "comparison" and dim_key and len(rows) >= 2:
        a, b = rows[0], rows[1]
        va, vb = a.get(metric_alias), b.get(metric_alias)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            diff = float(vb) - float(va)
            pct = (diff / float(va) * 100.0) if float(va) != 0 else None
            pct_str = f" ({pct:.2f}%)" if pct is not None else ""
            return (
                f"**Comparison by {dim_key}**: **{a.get(dim_key)}** = **{_fmt(va)}**, "
                f"**{b.get(dim_key)}** = **{_fmt(vb)}**. "
                f"Change = **{_fmt(diff)}**{pct_str}."
            )

    # Distribution
    if it == "distribution" and dim_key:
        return f"Distribution of **{metric.get('logical', metric_alias)}** by **{dim_key}** across **{len(rows)}** categories."

    # Aggregate/lookup/breakdown default: direct statement
    if len(rows) == 1 and metric_alias in rows[0]:
        return f"**{metric.get('logical', metric_alias)}** = **{_fmt(rows[0].get(metric_alias))}**."
    return f"Returned **{len(rows)}** row(s) for intent **{it}**."

