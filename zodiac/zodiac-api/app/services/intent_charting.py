"""
Intent-driven chart config (no generic fallbacks).

Produces chart specs compatible with AIChartRenderer:
{ chart_type, title, description, data, x_key, y_keys, name_key, value_key, ... }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def generate_chart_config(intent: Dict[str, Any], rows: List[Dict[str, Any]], validation: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not validation.get("valid"):
        return []
    it = str(intent.get("intent_type") or "")
    metric = intent.get("metric") or {}
    metric_alias = str(metric.get("alias") or metric.get("logical") or "value")
    dims = intent.get("dimensions") or []
    dim0 = dims[0] if dims else None
    x_key = str((dim0 or {}).get("alias") or (dim0 or {}).get("logical") or "") if dim0 else ""

    # Always support table chart as a safe representation
    def table_chart(title: str, desc: str) -> Dict[str, Any]:
        return {
            "chart_type": "table",
            "title": title,
            "description": desc,
            "data": rows[:80],
            "show_legend": False,
            "show_grid": False,
        }

    if it in ("raw_inspection", "lookup") or not x_key:
        return [table_chart("Query results", "Table view (intent does not require an analytic chart).")]

    if it == "trend":
        return [
            {
                "chart_type": "line",
                "title": f"{metric.get('logical', metric_alias)} over {x_key}",
                "description": "Intent-driven trend chart (time axis from intent).",
                "data": rows[:120],
                "x_key": x_key,
                "y_keys": [metric_alias],
                "show_legend": True,
                "show_grid": True,
            }
        ]

    if it == "ranking":
        return [
            {
                "chart_type": "bar",
                "title": f"{metric.get('logical', metric_alias)} by {x_key}",
                "description": "Intent-driven ranking chart.",
                "data": rows[:60],
                "x_key": x_key,
                "y_keys": [metric_alias],
                "show_legend": True,
                "show_grid": True,
            }
        ]

    if it == "comparison":
        return [
            {
                "chart_type": "bar",
                "title": f"{metric.get('logical', metric_alias)} by {x_key}",
                "description": "Intent-driven comparison chart (grouped by period).",
                "data": rows[:50],
                "x_key": x_key,
                "y_keys": [metric_alias],
                "show_legend": True,
                "show_grid": True,
            }
        ]

    if it == "distribution":
        # pie only if small categories; otherwise bar. (Still driven by distribution intent.)
        if len(rows) <= 8:
            return [
                {
                    "chart_type": "pie",
                    "title": f"{metric.get('logical', metric_alias)} distribution",
                    "description": "Intent-driven distribution chart.",
                    "data": rows[:12],
                    "name_key": x_key,
                    "value_key": metric_alias,
                    "show_legend": True,
                    "show_grid": False,
                }
            ]
        return [
            {
                "chart_type": "bar",
                "title": f"{metric.get('logical', metric_alias)} by {x_key}",
                "description": "Distribution intent; bar chart used because category count is large.",
                "data": rows[:60],
                "x_key": x_key,
                "y_keys": [metric_alias],
                "show_legend": True,
                "show_grid": True,
            }
        ]

    if it in ("aggregate", "breakdown"):
        if len(rows) == 1:
            return [table_chart("Summary", "Single-row aggregate (KPI-style table).")]
        return [
            {
                "chart_type": "bar",
                "title": f"{metric.get('logical', metric_alias)} by {x_key}",
                "description": "Intent-driven breakdown chart.",
                "data": rows[:60],
                "x_key": x_key,
                "y_keys": [metric_alias],
                "show_legend": True,
                "show_grid": True,
            }
        ]

    return [table_chart("Query results", "Table view (no chart mapping for this intent type).")]

