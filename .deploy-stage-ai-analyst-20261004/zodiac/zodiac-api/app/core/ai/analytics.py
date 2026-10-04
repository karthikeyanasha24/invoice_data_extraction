"""
Operational analytics derived solely from monitoring facts (Phase 9).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .datasource import OperationalDataSource


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def _is_today(ts: Optional[datetime], now: datetime) -> bool:
    if ts is None:
        return False
    return ts.astimezone(timezone.utc).date() == now.astimezone(timezone.utc).date()


def _within_hours(ts: Optional[datetime], now: datetime, hours: float) -> bool:
    if ts is None:
        return False
    return ts >= now - timedelta(hours=hours)


class OperationalAnalytics:
    def __init__(self, source: OperationalDataSource):
        self.source = source

    def workspace_analytics(
        self, workspace_id: str, *, limit: int = 200, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        summary = self.source.get_summary(workspace_id, limit=limit)
        timelines = self.source.list_timelines(workspace_id, limit=limit)
        alerts = self.source.list_alerts(workspace_id, limit=limit)
        metrics = self.source.list_metrics(workspace_id, limit=limit)

        failed_today = [
            t
            for t in timelines
            if (t.get("status") or "").upper() == "FAILED"
            and _is_today(_parse_ts(t.get("completed_at") or t.get("started_at")), now)
        ]
        changed_24h = [
            t
            for t in timelines
            if _within_hours(
                _parse_ts(t.get("completed_at") or t.get("started_at")), now, 24
            )
        ]

        validation_failures = Counter()
        for t in timelines:
            if (t.get("status") or "").upper() != "FAILED":
                continue
            stage = (t.get("failed_stage") or "").lower()
            if "valid" in stage:
                key = t.get("failure_reason") or t.get("failed_stage") or "validate"
                validation_failures[key] += 1

        gov_alerts = [
            a
            for a in alerts
            if (a.get("alert_type") or "") == "government_unavailable"
            or "GOV" in (a.get("title") or "").upper()
        ]
        erp_alerts = [
            a
            for a in alerts
            if (a.get("alert_type") or "") == "erp_unavailable"
            or "ERP" in (a.get("title") or "").upper()
        ]
        # Also treat failed_stage erp_update as ERP delay signal
        erp_failures = [
            t
            for t in timelines
            if (t.get("failed_stage") or "").lower() in {"erp_update", "erp"}
            or "erp" in (t.get("failure_reason") or "").lower()
        ]
        high_latency = [
            a for a in alerts if (a.get("alert_type") or "") == "high_latency"
        ]

        retries = [int(t.get("retry_count") or 0) for t in timelines]
        retry_total = sum(retries)
        retrying_now = sum(
            1 for t in timelines if (t.get("status") or "").upper() == "RETRYING"
        )

        latencies = [
            float(t["latency_ms"])
            for t in timelines
            if t.get("latency_ms") is not None
        ]
        avg_latency = (sum(latencies) / len(latencies)) if latencies else None

        metric_latency = [
            float(m["value"])
            for m in metrics
            if m.get("name") == "pipeline.latency_ms"
        ]
        if avg_latency is None and metric_latency:
            avg_latency = sum(metric_latency) / len(metric_latency)

        return {
            "workspace_id": workspace_id,
            "customer_id": workspace_id,
            "generated_at": now.isoformat(),
            "summary_counts": summary.get("counts") or {},
            "success_rate_percent": summary.get("success_rate_percent"),
            "average_processing_time_ms": avg_latency
            if avg_latency is not None
            else summary.get("average_processing_time_ms"),
            "failures_today": [
                {
                    "correlation_id": t.get("correlation_id"),
                    "failed_stage": t.get("failed_stage"),
                    "failure_reason": t.get("failure_reason"),
                    "completed_at": t.get("completed_at"),
                }
                for t in failed_today
            ],
            "top_validation_failures": [
                {"key": k, "count": c} for k, c in validation_failures.most_common(10)
            ],
            "top_errors": summary.get("top_errors") or [],
            "government_outages": gov_alerts[:20],
            "erp_delays": {
                "alerts": erp_alerts[:20],
                "failed_transactions": [
                    {
                        "correlation_id": t.get("correlation_id"),
                        "failure_reason": t.get("failure_reason"),
                        "latency_ms": t.get("latency_ms"),
                    }
                    for t in erp_failures[:20]
                ],
            },
            "retry_statistics": {
                "total_retries": retry_total,
                "transactions_with_retries": sum(1 for r in retries if r > 0),
                "retrying_now": retrying_now,
                "max_retry_count": max(retries) if retries else 0,
            },
            "high_latency_alerts": high_latency[:20],
            "changed_last_24h": {
                "count": len(changed_24h),
                "completed": sum(
                    1
                    for t in changed_24h
                    if (t.get("status") or "").upper() == "COMPLETED"
                ),
                "failed": sum(
                    1 for t in changed_24h if (t.get("status") or "").upper() == "FAILED"
                ),
                "sample": [
                    {
                        "correlation_id": t.get("correlation_id"),
                        "status": t.get("status"),
                        "failed_stage": t.get("failed_stage"),
                        "latency_ms": t.get("latency_ms"),
                    }
                    for t in changed_24h[:20]
                ],
            },
            "facts_available": len(self.source.get_ai_facts(workspace_id, limit=limit)),
        }

    def compare_workspaces(
        self, workspace_ids: List[str], *, limit: int = 100
    ) -> Dict[str, Any]:
        """Admin cross-workspace comparison — caller must authorize first."""
        rows = []
        for wid in workspace_ids:
            summary = self.source.get_summary(wid, limit=limit)
            counts = summary.get("counts") or {}
            completed = int(counts.get("completed") or 0)
            failed = int(counts.get("failed") or 0)
            finished = completed + failed
            failure_rate = (failed / finished * 100.0) if finished else None
            rows.append(
                {
                    "workspace_id": wid,
                    "counts": counts,
                    "failure_rate_percent": failure_rate,
                    "success_rate_percent": summary.get("success_rate_percent"),
                    "average_processing_time_ms": summary.get(
                        "average_processing_time_ms"
                    ),
                    "activity": int(counts.get("total") or 0),
                }
            )
        highest_failure = max(
            (r for r in rows if r["failure_rate_percent"] is not None),
            key=lambda r: r["failure_rate_percent"],
            default=None,
        )
        most_active = max(rows, key=lambda r: r["activity"], default=None)
        return {
            "workspaces": rows,
            "highest_failure_rate": highest_failure,
            "most_active_workspace": most_active,
        }
