"""Workspace operational summarizer (Phase 9)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .analytics import OperationalAnalytics
from .datasource import OperationalDataSource
from .recommendations import RecommendationEngine


class OperationalSummarizer:
    def __init__(
        self,
        source: OperationalDataSource,
        analytics: Optional[OperationalAnalytics] = None,
        recommendations: Optional[RecommendationEngine] = None,
    ):
        self.source = source
        self.analytics = analytics or OperationalAnalytics(source)
        self.recommendations = recommendations or RecommendationEngine()

    def summarize(self, workspace_id: str, *, limit: int = 200) -> Dict[str, Any]:
        analytics = self.analytics.workspace_analytics(workspace_id, limit=limit)
        counts = analytics.get("summary_counts") or {}
        narrative_parts = [
            f"Workspace {workspace_id} has {counts.get('total', 0)} recent monitored transactions "
            f"({counts.get('completed', 0)} completed, {counts.get('failed', 0)} failed, "
            f"{counts.get('running', 0)} running).",
        ]
        sr = analytics.get("success_rate_percent")
        if sr is not None:
            narrative_parts.append(f"Success rate is {sr:.1f}%.")
        avg = analytics.get("average_processing_time_ms")
        if avg is not None:
            narrative_parts.append(f"Average processing time is {avg:.0f} ms.")
        failures_today = analytics.get("failures_today") or []
        if failures_today:
            narrative_parts.append(
                f"{len(failures_today)} failure(s) recorded today."
            )
        else:
            narrative_parts.append("No failures recorded today in the recent window.")

        recs = self.recommendations.generate(analytics)
        return {
            "workspace_id": workspace_id,
            "customer_id": workspace_id,
            "narrative": " ".join(narrative_parts),
            "counts": counts,
            "success_rate_percent": sr,
            "average_processing_time_ms": avg,
            "failures_today_count": len(failures_today),
            "retry_statistics": analytics.get("retry_statistics"),
            "top_errors": analytics.get("top_errors"),
            "changed_last_24h": analytics.get("changed_last_24h"),
            "recommendation_codes": [r["code"] for r in recs[:5]],
            "ai_facts_preview": self.source.get_ai_facts(workspace_id, limit=min(limit, 20)),
        }
