"""Presentation planning from semantics + validated result shape.

Never invents chart values — only chooses how to display executed rows.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..analytical_operations import extract_analytical_operations
from ..semantic_requirements import required_semantics


def plan_presentation(
    question: str,
    rows: List[Dict[str, Any]],
    *,
    semantic: Optional[Dict[str, Any]] = None,
    charts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a structured presentation contract for the AI Analyst UI."""
    q = (question or "").strip()
    ql = q.lower()
    req = required_semantics(q, semantic)
    ops = extract_analytical_operations(q)
    force_table = bool(re.search(r"\bas a table\b|\bin (a )?table\b|\btabular\b", ql))
    force_chart = bool(
        re.search(r"\bas a chart\b|\bas a graph\b|\bchart\b|\bgraph\b|\bplot\b", ql)
    )
    force_both = bool(
        re.search(
            r"\b(both|chart and table|table and chart|chart\s*\+\s*table|table\s*\+\s*chart)\b",
            ql,
        )
    )

    keys = [str(k).lower() for k in (rows[0].keys() if rows else [])]
    has_month = any("month" in k or k in {"yyyymm", "period", "ym"} for k in keys)
    has_change = any(k in {"change", "growth", "diff", "delta", "contribution_pct"} for k in keys)
    has_period_pair = any(k.startswith("period_") for k in keys) or (
        "period_a" in keys and "period_b" in keys
    )

    preferred = "table"
    chart_type = None
    if not rows:
        preferred = "none"
    elif force_both:
        preferred = "chart_table"
        chart_type = "line" if has_month or ops.get("trend") else "bar"
    elif force_table and not force_chart:
        preferred = "table"
    elif has_period_pair or has_change or req.get("period_compare") or ops.get("contribution"):
        preferred = "chart"
        chart_type = "bar"
    elif has_month or ops.get("trend") or str(ops.get("time_grain") or "") == "month":
        preferred = "chart"
        chart_type = "line"
    elif ops.get("ranking") or req.get("ranking"):
        preferred = "chart"
        chart_type = "bar"
    elif len(rows) == 1:
        preferred = "kpi"
    elif force_chart:
        preferred = "chart"
        chart_type = "bar" if len(rows) <= 20 else "line"

    if force_chart and preferred == "table":
        preferred = "chart"
        chart_type = chart_type or ("line" if has_month else "bar")
    if force_both:
        preferred = "chart_table"
        chart_type = chart_type or ("line" if has_month else "bar")

    # Prefer existing row-grounded charts; never synthesize numeric series here.
    grounded = [c for c in (charts or []) if isinstance(c, dict) and c.get("data")]
    if force_table and not force_both:
        table_only = [c for c in grounded if str(c.get("chart_type") or "").lower() == "table"]
        grounded = table_only or grounded
    elif preferred in {"chart", "chart_table"} and chart_type and grounded:
        aligned: List[Dict[str, Any]] = []
        for c in grounded:
            ct = str(c.get("chart_type") or "").lower()
            if ct in {"table", "kpi_card"}:
                aligned.append(c)
                continue
            if chart_type in {"line", "bar"} and c.get("data"):
                aligned.append({**c, "chart_type": chart_type})
            else:
                aligned.append(c)
        grounded = aligned

    # Ensure a table companion when both requested and charts lack a table view.
    if force_both and rows:
        has_table_view = any(str(c.get("chart_type") or "").lower() == "table" for c in grounded)
        if not has_table_view:
            grounded = list(grounded) + [
                {
                    "chart_type": "table",
                    "title": "Data Table",
                    "data": rows[:100],
                    "description": f"{len(rows)} row(s) from validated query results",
                }
            ]

    return {
        "type": preferred,
        "chart_type": chart_type,
        "prefer_table": force_table or force_both,
        "prefer_chart": force_chart or force_both,
        "prefer_both": force_both,
        "row_count": len(rows),
        "has_charts": bool(grounded or charts),
        "charts": grounded[:4] if grounded else [],
        "title": q[:120],
        "data_from_rows_only": True,
    }
