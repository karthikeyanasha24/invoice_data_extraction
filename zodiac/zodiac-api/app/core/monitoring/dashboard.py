"""
Workspace monitoring dashboard aggregations (Phase 8).

Strictly scoped by customer_id — never crosses workspaces.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from .alerts import AlertService
from .metrics import MetricsStore
from .status import TransactionStatus
from .timeline import TimelineStore


class MonitoringDashboard:
    def __init__(
        self,
        timeline: Optional[TimelineStore] = None,
        metrics: Optional[MetricsStore] = None,
        alerts: Optional[AlertService] = None,
    ):
        self.timeline = timeline or TimelineStore()
        self.metrics = metrics or MetricsStore()
        self.alerts = alerts or AlertService()

    def summary(self, customer_id: str, *, limit: int = 100) -> Dict[str, Any]:
        txs = self.timeline.list_for_workspace(customer_id, limit=limit)
        counts = Counter(t.status for t in txs)
        latencies = [t.latency_ms for t in txs if t.latency_ms is not None]
        completed = counts.get(TransactionStatus.COMPLETED.value, 0)
        failed = counts.get(TransactionStatus.FAILED.value, 0)
        finished = completed + failed
        success_rate = (completed / finished * 100.0) if finished else None

        error_counter: Counter = Counter()
        for t in txs:
            if t.status == TransactionStatus.FAILED.value:
                key = t.failed_stage or t.failure_reason or "unknown"
                error_counter[key] += 1

        return {
            "workspace_id": customer_id,
            "customer_id": customer_id,
            "counts": {
                "running": counts.get(TransactionStatus.RUNNING.value, 0)
                + counts.get(TransactionStatus.RETRYING.value, 0),
                "completed": completed,
                "failed": failed,
                "pending": counts.get(TransactionStatus.PENDING.value, 0),
                "retrying": counts.get(TransactionStatus.RETRYING.value, 0),
                "dry_run": counts.get(TransactionStatus.DRY_RUN.value, 0),
                "total": len(txs),
            },
            "average_processing_time_ms": (sum(latencies) / len(latencies)) if latencies else None,
            "success_rate_percent": success_rate,
            "top_errors": [
                {"key": k, "count": c} for k, c in error_counter.most_common(10)
            ],
            "latest_transactions": [t.to_dict() for t in txs[:20]],
            "recent_alerts": self.alerts.list_for_workspace(customer_id, limit=20),
        }

    def ai_facts(self, customer_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Structured facts for future AI workspace queries (Phase 9)."""
        txs = self.timeline.list_for_workspace(customer_id, limit=limit)
        facts = [t.to_ai_fact() for t in txs]
        summary = self.summary(customer_id, limit=limit)
        facts.insert(
            0,
            {
                "type": "workspace_monitoring_summary",
                "workspace_id": customer_id,
                "counts": summary["counts"],
                "average_processing_time_ms": summary["average_processing_time_ms"],
                "success_rate_percent": summary["success_rate_percent"],
                "top_errors": summary["top_errors"],
            },
        )
        return facts
