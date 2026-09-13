"""Diagnostic observability for adaptive analytical requests.

Never logs secrets or full customer PII dumps — only structural fields.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_analytical_diagnostics(
    *,
    question: str,
    route: str = "",
    semantic: Optional[Dict[str, Any]] = None,
    sql: str = "",
    row_count: int = 0,
    result_validation: Optional[Any] = None,
    pipeline_log: Optional[Dict[str, Any]] = None,
    presentation: Optional[Dict[str, Any]] = None,
    answer_status: str = "",
    failure_class: str = "",
) -> Dict[str, Any]:
    sem = semantic if isinstance(semantic, dict) else {}
    ops = sem.get("analytical_operations") if isinstance(sem.get("analytical_operations"), dict) else {}
    period = sem.get("period_compare") if isinstance(sem.get("period_compare"), dict) else {}
    log = pipeline_log if isinstance(pipeline_log, dict) else {}
    stages = log.get("stages") if isinstance(log.get("stages"), list) else []
    stage_names = []
    for s in stages[-20:]:
        if isinstance(s, dict) and s.get("name"):
            stage_names.append(str(s["name"]))
        elif isinstance(s, str):
            stage_names.append(s)

    return {
        "question": (question or "")[:240],
        "route": route or "",
        "semantic_plan": {
            "measure": sem.get("measure") or ops.get("measure_concept"),
            "aggregation": sem.get("aggregation") or ops.get("aggregation"),
            "entities": sem.get("group_by") or ops.get("group_by") or sem.get("dimensions"),
            "ranking": sem.get("ranking") or ops.get("ranking"),
            "period_compare": {
                "base": (period.get("base_period") or {}).get("year")
                if isinstance(period.get("base_period"), dict)
                else period.get("base_period"),
                "comparison": (period.get("comparison_period") or {}).get("year")
                if isinstance(period.get("comparison_period"), dict)
                else period.get("comparison_period"),
                "op": period.get("op") or period.get("condition"),
                "contribution": bool(period.get("contribution") or sem.get("contribution")),
                "investigation": bool(period.get("investigation")),
            }
            if period
            else None,
            "trend": bool(ops.get("trend") or sem.get("trend")),
            "time_grain": ops.get("time_grain") or sem.get("time_grain"),
            "years": ops.get("years") or sem.get("years"),
        },
        "schema_grounding": {
            "tables": (log.get("tables") or sem.get("tables") or [])[:12]
            if isinstance(log.get("tables") or sem.get("tables"), list)
            else [],
            "stage_names": stage_names,
        },
        "sql": {
            "generated": bool(sql),
            "preview": (sql or "")[:400],
            "length": len(sql or ""),
        },
        "execution": {
            "row_count": int(row_count or 0),
        },
        "result_validation": result_validation
        if isinstance(result_validation, (list, dict, str))
        else None,
        "replanning": {
            "investigation_confirm": log.get("investigation_confirm"),
            "investigation_grain": log.get("investigation_grain"),
            "investigation_queries": log.get("investigation_queries"),
            "investigation_sufficiency": log.get("investigation_sufficiency"),
            "investigation_answer_mode": log.get("investigation_answer_mode"),
        },
        "presentation": {
            "type": (presentation or {}).get("type") if isinstance(presentation, dict) else None,
            "chart_type": (presentation or {}).get("chart_type") if isinstance(presentation, dict) else None,
            "prefer_table": (presentation or {}).get("prefer_table") if isinstance(presentation, dict) else None,
            "prefer_chart": (presentation or {}).get("prefer_chart") if isinstance(presentation, dict) else None,
            "both": bool(
                isinstance(presentation, dict)
                and presentation.get("prefer_table")
                and presentation.get("prefer_chart")
            ),
        },
        "final_status": answer_status or failure_class or "",
        "failure_class": failure_class or "",
    }
