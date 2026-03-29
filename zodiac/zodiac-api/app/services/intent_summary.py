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
    dim_logical = str((dim0 or {}).get("alias") or (dim0 or {}).get("logical") or "") if dim0 else ""

    def _resolve_dim_key(logical: str, row: dict) -> str:
        """
        Adaptively find the actual column name in `row` for a logical dimension.
        No hardcoded map — works for any column name the SQL happens to generate:
          1. Exact match:          "product"   → "product"
          2. Prefixed match:       "product"   → "product_name", "product_id"
          3. Suffixed match:       "customer"  → "top_customer"
          4. First non-metric col: last resort fallback
        """
        if not logical or not row:
            return logical
        keys = list(row.keys())
        # Exact match
        if logical in keys:
            return logical
        # Prefix match (e.g. "product" matches "product_name", "product_id")
        for k in keys:
            if k.startswith(logical + "_") or k.endswith("_" + logical):
                return k
        # First non-numeric column as last resort (the dimension is usually text)
        for k in keys:
            if not isinstance(row[k], (int, float)):
                return k
        return logical

    dim_key = dim_logical  # default; overridden per-row below

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
    if it == "trend" and dim_logical and metric_alias in rows[0]:
        best = None
        best_v = None
        for r in rows:
            v = r.get(metric_alias)
            if isinstance(v, (int, float)):
                if best_v is None or float(v) > float(best_v):
                    best_v = float(v)
                    best = r
        if best is not None:
            best_dim_key = _resolve_dim_key(dim_logical, best)
            return (
                f"**{metric.get('logical', metric_alias)} over {dim_logical}** shows the peak in "
                f"**{best.get(best_dim_key)}** at **{_fmt(best_v)}**."
            )

    # Ranking
    if it == "ranking" and dim_logical:
        top = rows[0]
        top_dim_key = _resolve_dim_key(dim_logical, top)
        top_val = top.get(top_dim_key)
        return (
            f"Top **{dim_logical}** is **{top_val}** with **{_fmt(top.get(metric_alias))}** "
            f"{metric.get('logical', metric_alias)}."
        )

    # Comparison (assumes year/period dimension)
    if it == "comparison" and dim_logical and len(rows) >= 2:
        a, b = rows[0], rows[1]
        a_dim_key = _resolve_dim_key(dim_logical, a)
        b_dim_key = _resolve_dim_key(dim_logical, b)
        va, vb = a.get(metric_alias), b.get(metric_alias)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            diff = float(vb) - float(va)
            pct = (diff / float(va) * 100.0) if float(va) != 0 else None
            pct_str = f" ({pct:.2f}%)" if pct is not None else ""
            return (
                f"**Comparison by {dim_logical}**: **{a.get(a_dim_key)}** = **{_fmt(va)}**, "
                f"**{b.get(b_dim_key)}** = **{_fmt(vb)}**. "
                f"Change = **{_fmt(diff)}**{pct_str}."
            )

    # Distribution
    if it == "distribution" and dim_logical:
        return f"Distribution of **{metric.get('logical', metric_alias)}** by **{dim_logical}** across **{len(rows)}** categories."

    # Aggregate/lookup/breakdown default: direct statement
    if len(rows) == 1 and metric_alias in rows[0]:
        return f"**{metric.get('logical', metric_alias)}** = **{_fmt(rows[0].get(metric_alias))}**."
    return f"Returned **{len(rows)}** row(s) for intent **{it}**."

