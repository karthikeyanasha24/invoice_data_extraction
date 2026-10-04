"""
Pipeline types (Phase 4).

Data carried through the shared Invoice Processing Orchestrator. Nothing here
knows about any country — the only country-aware object is the `CountryAdapter`
held on the execution, and it is resolved from the registry.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PipelineStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DRY_RUN = "dry_run"


class StageStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageFailed(Exception):
    """Raised by a stage handler to fail the run with a stable code."""

    def __init__(self, message: str, error_code: str = "STAGE_FAILED", **meta: Any):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.meta = meta


class StageSkipped(Exception):
    """Raised by a stage handler when the stage does not apply to this run."""

    def __init__(self, reason: str, **meta: Any):
        super().__init__(reason)
        self.reason = reason
        self.meta = meta


@dataclass
class PipelineRequest:
    """One document submitted to the orchestrator."""

    customer_id: str
    payload: Any = None
    country_code: Optional[str] = None
    document_type: Optional[str] = None
    user: Any = None
    db: Any = None
    dry_run: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class StageOutcome:
    """Result of one stage, including retry accounting."""

    stage: str
    status: StageStatus
    attempts: int = 1
    duration_ms: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None
    detail: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status is StageStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "error_code": self.error_code,
            "detail": self.detail,
            "meta": self.meta,
        }


@dataclass
class PipelineExecution:
    """
    Mutable state for a single run.

    Stage handlers read and write this; the orchestrator owns its lifecycle.
    """

    request: PipelineRequest
    services: Any = None
    principal: Any = None
    workspace: Any = None
    adapter: Any = None
    adapter_config: Any = None
    adapter_ctx: Any = None
    country_code: Optional[str] = None
    stages: List[StageOutcome] = field(default_factory=list)

    @property
    def correlation_id(self) -> str:
        return self.request.correlation_id

    @property
    def customer_id(self) -> str:
        return self.request.customer_id

    @property
    def failed(self) -> bool:
        return any(s.status is StageStatus.FAILED for s in self.stages)

    def outcome_for(self, stage: str) -> Optional[StageOutcome]:
        return next((s for s in self.stages if s.stage == stage), None)

    def adapter_output(self, stage_enum) -> Any:
        """Read a stage output previously written to the AdapterContext."""
        if self.adapter_ctx is None:
            return None
        return self.adapter_ctx.get_output(stage_enum)


@dataclass
class PipelineResult:
    """Immutable summary handed back to the caller."""

    correlation_id: str
    customer_id: str
    status: PipelineStatus
    country_code: Optional[str] = None
    stages: List[StageOutcome] = field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[str] = None
    failed_stage: Optional[str] = None
    confirmation: Any = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None

    @property
    def succeeded(self) -> bool:
        return self.status in (PipelineStatus.COMPLETED, PipelineStatus.DRY_RUN)

    @property
    def duration_ms(self) -> float:
        if self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds() * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "country_code": self.country_code,
            "status": self.status.value,
            "succeeded": self.succeeded,
            "error": self.error,
            "error_code": self.error_code,
            "failed_stage": self.failed_stage,
            "duration_ms": round(self.duration_ms, 2),
            "stages": [s.to_dict() for s in self.stages],
            "events": self.events,
        }
