"""
Pipeline DI sinks that persist monitoring without changing business logic.

Implements the MonitoringSink / AuditSink protocols from core.pipeline.hooks.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .alerts import AlertService
from .audit import AuditRecorder
from .metrics import MetricsStore
from .timeline import TimelineStore

logger = logging.getLogger("zodiac-api.monitoring.sinks")


class PersistingAuditSink:
    """Replaces LoggingAuditSink as default — still logs, also persists stages."""

    def __init__(self, timeline: Optional[TimelineStore] = None, also_log: bool = True):
        self.recorder = AuditRecorder(timeline=timeline or TimelineStore())
        self.also_log = also_log

    def record(self, entry: Dict[str, Any]) -> None:
        if self.also_log:
            logger.info(
                "[audit] %s %s stage=%s status=%s attempts=%s",
                entry.get("correlation_id"),
                entry.get("customer_id"),
                entry.get("stage"),
                entry.get("status"),
                entry.get("attempts"),
            )
        self.recorder.record(entry)


class PersistingMonitoringSink:
    """
    Receives finalizer monitoring events + finalizes timelines / metrics / alerts.

    Observes only — never mutates pipeline outcomes.
    """

    def __init__(
        self,
        timeline: Optional[TimelineStore] = None,
        metrics: Optional[MetricsStore] = None,
        alerts: Optional[AlertService] = None,
        also_log: bool = True,
    ):
        self.timeline = timeline or TimelineStore()
        self.metrics = metrics or MetricsStore()
        self.alerts = alerts or AlertService()
        self.also_log = also_log

    def emit(self, event: Dict[str, Any]) -> None:
        if self.also_log:
            logger.info(
                "[monitoring] %s %s stage=%s status=%s",
                event.get("correlation_id"),
                event.get("customer_id"),
                event.get("stage"),
                event.get("status"),
            )

        # Stage timeline is owned by PersistingAuditSink to avoid duplicates.
        # Final run summaries (if any sink emits them) still finalize metrics.
        if "stages" in event and event.get("correlation_id"):
            self._finalize_from_summary(event)

    def finalize_pipeline_result(self, result: Any, *, adapter_name: Optional[str] = None) -> None:
        """Called optionally by API after orchestrator.run — safe observer."""
        try:
            status = result.status.value if hasattr(result.status, "value") else str(result.status)
            confirmation = getattr(result, "confirmation", None) or {}
            gov_ref = None
            erp_ref = None
            if isinstance(confirmation, dict):
                gov_ref = confirmation.get("document_number") or confirmation.get(
                    "government_reference"
                )
                erp_ref = confirmation.get("erp_document") or confirmation.get("erp_reference")

            retry_count = sum(
                max(0, (getattr(s, "attempts", 1) or 1) - 1) for s in (result.stages or [])
            )
            self.timeline.finalize(
                correlation_id=result.correlation_id,
                customer_id=result.customer_id,
                pipeline_status=status,
                latency_ms=getattr(result, "duration_ms", None),
                failure_reason=result.error,
                failed_stage=result.failed_stage,
                government_reference=gov_ref,
                erp_reference=erp_ref,
                country_code=result.country_code,
                adapter_name=adapter_name,
            )
            if result.duration_ms is not None:
                self.metrics.record(
                    customer_id=result.customer_id,
                    name="pipeline.latency_ms",
                    value=float(result.duration_ms),
                    unit="ms",
                    correlation_id=result.correlation_id,
                    tags={"status": status, "country_code": result.country_code},
                )
            self.metrics.record(
                customer_id=result.customer_id,
                name="pipeline.run",
                value=1.0,
                unit="count",
                correlation_id=result.correlation_id,
                tags={"status": status},
            )
            self.alerts.evaluate_pipeline_result(
                customer_id=result.customer_id,
                correlation_id=result.correlation_id,
                status=status,
                failed_stage=result.failed_stage,
                error=result.error,
                error_code=result.error_code,
                retry_count=retry_count,
                latency_ms=getattr(result, "duration_ms", None),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("finalize_pipeline_result failed: %s", exc)

    def _finalize_from_summary(self, event: Dict[str, Any]) -> None:
        status = str(event.get("status") or "SUCCESS")
        pipeline_status = "failed" if status.upper() == "FAILED" else "completed"
        if event.get("dry_run"):
            pipeline_status = "dry_run"
        stages = event.get("stages") or []
        retry_count = 0
        latency = 0.0
        for s in stages:
            if isinstance(s, dict):
                retry_count += max(0, int(s.get("attempts") or 1) - 1)
                latency += float(s.get("duration_ms") or 0)
        self.timeline.finalize(
            correlation_id=str(event["correlation_id"]),
            customer_id=str(event.get("customer_id") or ""),
            pipeline_status=pipeline_status,
            latency_ms=latency or None,
            failure_reason=None,
            failed_stage=event.get("failed_stage"),
            country_code=event.get("country_code"),
        )


def build_default_monitoring_bundle(db: Any = None):
    """Shared stores for audit + monitoring sinks (same timeline)."""
    timeline = TimelineStore(db=db)
    metrics = MetricsStore(db=db)
    alerts = AlertService(db=db)
    return {
        "timeline": timeline,
        "metrics": metrics,
        "alerts": alerts,
        "audit": PersistingAuditSink(timeline=timeline),
        "monitoring": PersistingMonitoringSink(
            timeline=timeline, metrics=metrics, alerts=alerts
        ),
    }
