"""
Operational question routing (Phase 9).

Maps natural-language ops questions to analytics answers.
Does not call production invoice SQL agents or the global NL-to-SQL API.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .analytics import OperationalAnalytics
from .datasource import OperationalDataSource
from .recommendations import RecommendationEngine


class OperationalQueryService:
    """Keyword / intent classifier over monitoring-backed analytics."""

    def __init__(
        self,
        source: OperationalDataSource,
        analytics: Optional[OperationalAnalytics] = None,
        recommendations: Optional[RecommendationEngine] = None,
    ):
        self.source = source
        self.analytics = analytics or OperationalAnalytics(source)
        self.recommendations = recommendations or RecommendationEngine()

    def ask(
        self,
        workspace_id: str,
        question: str,
        *,
        limit: int = 200,
        compare: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        q = (question or "").strip()
        intent = self.classify(q)
        analytics = self.analytics.workspace_analytics(workspace_id, limit=limit)
        answer: Any
        facts: Dict[str, Any] = {}

        if intent == "failures_today":
            answer = analytics["failures_today"]
            facts = {"count": len(answer)}
        elif intent == "average_processing_time":
            answer = analytics["average_processing_time_ms"]
            facts = {"unit": "ms"}
        elif intent == "top_validation_failures":
            answer = analytics["top_validation_failures"] or analytics["top_errors"]
            facts = {"count": len(answer)}
        elif intent == "government_outages":
            answer = analytics["government_outages"]
            facts = {"count": len(answer)}
        elif intent == "erp_delays":
            answer = analytics["erp_delays"]
            facts = {
                "alert_count": len(answer.get("alerts") or []),
                "transaction_count": len(answer.get("failed_transactions") or []),
            }
        elif intent == "retry_statistics":
            answer = analytics["retry_statistics"]
            facts = dict(answer)
        elif intent == "changed_last_24h":
            answer = analytics["changed_last_24h"]
            facts = {"count": answer.get("count")}
        elif intent == "success_rate":
            answer = analytics["success_rate_percent"]
            facts = {"counts": analytics["summary_counts"]}
        elif intent == "highest_failure_rate":
            if not compare:
                answer = {
                    "error": "cross_workspace_required",
                    "message": (
                        "This question needs admin cross-workspace authorization "
                        "and a workspace list."
                    ),
                }
            else:
                answer = compare.get("highest_failure_rate")
                facts = {"workspaces_compared": len(compare.get("workspaces") or [])}
        elif intent == "most_active_workspace":
            if not compare:
                answer = {
                    "error": "cross_workspace_required",
                    "message": (
                        "This question needs admin cross-workspace authorization "
                        "and a workspace list."
                    ),
                }
            else:
                answer = compare.get("most_active_workspace")
                facts = {"workspaces_compared": len(compare.get("workspaces") or [])}
        elif intent == "recommendations":
            answer = self.recommendations.generate(analytics)
            facts = {"count": len(answer)}
        else:
            # Generic operational brief
            answer = {
                "counts": analytics["summary_counts"],
                "success_rate_percent": analytics["success_rate_percent"],
                "average_processing_time_ms": analytics["average_processing_time_ms"],
                "failures_today": analytics["failures_today"][:10],
                "retry_statistics": analytics["retry_statistics"],
            }
            facts = {"intent": "general_ops"}

        return {
            "workspace_id": workspace_id,
            "question": q,
            "intent": intent,
            "answer": answer,
            "facts": facts,
            "source": "monitoring_operational_datasource",
        }

    @staticmethod
    def classify(question: str) -> str:
        q = question.lower().strip()
        rules = [
            (r"fail(ed|ures)?\s+today|what\s+failed\s+today", "failures_today"),
            (r"highest\s+failure|most\s+errors|failure\s+rate", "highest_failure_rate"),
            (r"average\s+processing|avg\s+(latency|time)|processing\s+time", "average_processing_time"),
            (r"validation\s+fail|top\s+validation", "top_validation_failures"),
            (r"government\s+outage|gov(ernment)?\s+(down|unavailable)", "government_outages"),
            (r"erp\s+(delay|slow|fail|unavailable)", "erp_delays"),
            (r"most\s+active\s+workspace|busiest\s+workspace", "most_active_workspace"),
            (r"retry\s+stat", "retry_statistics"),
            (r"last\s+24\s+hours|what\s+changed|past\s+day", "changed_last_24h"),
            (r"success\s+rate", "success_rate"),
            (r"recommend", "recommendations"),
        ]
        for pattern, intent in rules:
            if re.search(pattern, q):
                return intent
        return "general_ops"
