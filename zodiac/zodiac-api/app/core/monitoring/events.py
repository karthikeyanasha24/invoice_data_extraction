"""
Monitoring event shapes — AI-ready structured records (Phase 8).

Country / ERP / government agnostic. Observes the pipeline only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MonitoringEvent:
    correlation_id: str
    customer_id: str
    stage: str
    status: str
    country_code: Optional[str] = None
    adapter_name: Optional[str] = None
    document_type: Optional[str] = None
    message: Optional[str] = None
    duration_ms: Optional[float] = None
    attempt: int = 1
    error_code: Optional[str] = None
    government_reference: Optional[str] = None
    erp_reference: Optional[str] = None
    retry_count: int = 0
    occurred_at: datetime = field(default_factory=_utcnow)
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "workspace_id": self.customer_id,
            "country_code": self.country_code,
            "adapter_name": self.adapter_name,
            "document_type": self.document_type,
            "stage": self.stage,
            "status": self.status,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "attempt": self.attempt,
            "error_code": self.error_code,
            "government_reference": self.government_reference,
            "erp_reference": self.erp_reference,
            "retry_count": self.retry_count,
            "occurred_at": self.occurred_at.isoformat(),
            "extras": dict(self.extras),
        }

    @classmethod
    def from_audit_entry(cls, entry: Dict[str, Any]) -> "MonitoringEvent":
        return cls(
            correlation_id=str(entry.get("correlation_id") or ""),
            customer_id=str(entry.get("customer_id") or ""),
            country_code=entry.get("country_code"),
            adapter_name=entry.get("adapter_name"),
            document_type=entry.get("document_type"),
            stage=str(entry.get("stage") or "unknown"),
            status=str(entry.get("status") or "unknown"),
            message=entry.get("detail") or entry.get("error") or entry.get("message"),
            duration_ms=entry.get("duration_ms"),
            attempt=int(entry.get("attempts") or entry.get("attempt") or 1),
            error_code=entry.get("error_code"),
            government_reference=entry.get("government_reference"),
            erp_reference=entry.get("erp_reference"),
            extras={
                k: v
                for k, v in entry.items()
                if k
                not in {
                    "correlation_id",
                    "customer_id",
                    "country_code",
                    "adapter_name",
                    "document_type",
                    "stage",
                    "status",
                    "detail",
                    "error",
                    "message",
                    "duration_ms",
                    "attempts",
                    "attempt",
                    "error_code",
                    "government_reference",
                    "erp_reference",
                }
            },
        )


@dataclass
class TimelineStage:
    stage: str
    status: str
    timestamp: str
    duration_ms: Optional[float] = None
    message: Optional[str] = None
    attempt: int = 1
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "attempt": self.attempt,
            "error_code": self.error_code,
        }


@dataclass
class TransactionTimeline:
    correlation_id: str
    customer_id: str
    status: str
    stages: List[TimelineStage] = field(default_factory=list)
    country_code: Optional[str] = None
    adapter_name: Optional[str] = None
    document_type: Optional[str] = None
    current_stage: Optional[str] = None
    retry_count: int = 0
    latency_ms: Optional[float] = None
    failure_reason: Optional[str] = None
    failed_stage: Optional[str] = None
    government_reference: Optional[str] = None
    erp_reference: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "workspace_id": self.customer_id,
            "country_code": self.country_code,
            "adapter_name": self.adapter_name,
            "document_type": self.document_type,
            "status": self.status,
            "current_stage": self.current_stage,
            "retry_count": self.retry_count,
            "latency_ms": self.latency_ms,
            "failure_reason": self.failure_reason,
            "failed_stage": self.failed_stage,
            "government_reference": self.government_reference,
            "erp_reference": self.erp_reference,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stages": [s.to_dict() for s in self.stages],
        }

    def to_ai_fact(self) -> Dict[str, Any]:
        """Compact fact card for future AI workspace queries."""
        return {
            "type": "pipeline_transaction",
            "correlation_id": self.correlation_id,
            "workspace_id": self.customer_id,
            "country_code": self.country_code,
            "status": self.status,
            "failed_stage": self.failed_stage,
            "failure_reason": self.failure_reason,
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "government_reference": self.government_reference,
            "erp_reference": self.erp_reference,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stage_count": len(self.stages),
            "error_stages": [s.stage for s in self.stages if s.status == "failed"],
        }
