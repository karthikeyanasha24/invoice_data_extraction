"""
Country Adapter contract (Phase 3, Task 3.1).

Defines the generic interface every country implementation must satisfy, plus
the context and result types the shared pipeline passes between stages.

Design rules:
- The adapter owns country-specific behaviour only.
- The adapter never performs auth, tenancy, storage, queueing or AI work.
- Stages return `StageResult` instead of raising, so the platform can decide
  whether to stop, retry, or route to a dead-letter queue.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class AdapterStage(str, Enum):
    """Ordered stages of a country pipeline."""

    PARSE = "parse"
    VALIDATE = "validate"
    MAP = "map"
    BUSINESS_RULES = "apply_business_rules"
    TRANSFORM = "transform"
    FORMAT = "format"
    SUBMIT = "submit"
    CONFIRMATION = "receive_confirmation"
    ERP_UPDATE = "update_erp"
    MONITORING = "generate_monitoring_event"


class AdapterCapability(str, Enum):
    """
    Declares what an adapter can actually do today.

    Lets the platform reason about partial implementations without any
    country-specific conditionals in the pipeline.
    """

    PARSE = "parse"
    VALIDATE = "validate"
    MAP = "map"
    BUSINESS_RULES = "business_rules"
    TRANSFORM = "transform"
    FORMAT = "format"
    SUBMIT = "submit"
    CONFIRMATION = "confirmation"
    ERP_UPDATE = "erp_update"
    GOVERNMENT_API = "government_api"


# Stable error codes so the platform can classify failures generically.
ERROR_VALIDATION = "VALIDATION_FAILED"
ERROR_PARSING = "PARSING_FAILED"
ERROR_MAPPING = "MAPPING_FAILED"
ERROR_BUSINESS_RULES = "BUSINESS_RULES_FAILED"
ERROR_TRANSFORM = "TRANSFORM_FAILED"
ERROR_FORMAT = "FORMAT_FAILED"
ERROR_SUBMIT = "SUBMIT_FAILED"
ERROR_CONFIRMATION = "CONFIRMATION_FAILED"
ERROR_NOT_SUPPORTED = "NOT_SUPPORTED"
ERROR_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AdapterContext:
    """
    Carries one document through the country pipeline.

    Owned by the platform; adapters read inputs and write stage outputs.
    `db` is the existing SQLAlchemy session so adapters can reuse production
    services without opening their own connections.
    """

    customer_id: str
    country_code: str
    payload: Any = None
    document_type: Optional[str] = None
    user_id: Optional[int] = None
    db: Any = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def workspace_id(self) -> str:
        return self.customer_id

    def set_output(self, stage: AdapterStage, value: Any) -> None:
        self.outputs[stage.value] = value

    def get_output(self, stage: AdapterStage, default: Any = None) -> Any:
        return self.outputs.get(stage.value, default)

    def record_event(
        self,
        stage: AdapterStage,
        status: str,
        detail: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        event = {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "country_code": self.country_code,
            "stage": stage.value,
            "status": status,
            "detail": detail,
            "at": _utcnow().isoformat(),
            **extra,
        }
        self.events.append(event)
        return event


@dataclass
class StageResult:
    """Uniform outcome of a single adapter stage."""

    stage: AdapterStage
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, stage: AdapterStage, data: Any = None, **meta: Any) -> "StageResult":
        return cls(stage=stage, success=True, data=data, meta=dict(meta))

    @classmethod
    def fail(
        cls,
        stage: AdapterStage,
        error: str,
        error_code: str = ERROR_NOT_SUPPORTED,
        **meta: Any,
    ) -> "StageResult":
        return cls(
            stage=stage,
            success=False,
            error=error,
            error_code=error_code,
            meta=dict(meta),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "success": self.success,
            "error": self.error,
            "error_code": self.error_code,
            "meta": self.meta,
        }


class CountryAdapter(ABC):
    """
    Complete processing contract for one country's invoice exchange.

    Country-owned (abstract): parse, validate, map, apply_business_rules,
    transform, format, submit, receive_confirmation.

    Platform-owned with adapter override (concrete defaults): update_erp and
    generate_monitoring_event — ERP connectivity and monitoring are shared
    services, so most adapters supply payload mapping only.
    """

    #: Registry key, e.g. "mx_cfdi", "india".
    country_code: str = ""
    #: Human readable name for UI/config screens.
    display_name: str = ""
    #: Document types this adapter accepts (e.g. INVOICE, CREDIT_NOTE).
    supported_document_types: Sequence[str] = ()

    def capabilities(self) -> List[AdapterCapability]:
        """What this adapter really supports today."""
        return []

    def describe(self) -> Dict[str, Any]:
        return {
            "country_code": self.country_code,
            "display_name": self.display_name,
            "supported_document_types": list(self.supported_document_types),
            "capabilities": [c.value for c in self.capabilities()],
        }

    # ---------------------------------------------------------------- stages

    @abstractmethod
    def parse(self, ctx: AdapterContext) -> StageResult:
        """Country document format → normalized dict."""

    @abstractmethod
    def validate(self, ctx: AdapterContext) -> StageResult:
        """Structural / fiscal validation for this country."""

    @abstractmethod
    def map(self, ctx: AdapterContext) -> StageResult:
        """Party, account and code mapping for this country."""

    @abstractmethod
    def apply_business_rules(self, ctx: AdapterContext) -> StageResult:
        """Country business rules: merge, grouping, dedupe, accept/reject."""

    @abstractmethod
    def transform(self, ctx: AdapterContext) -> StageResult:
        """Internal model → target system structure."""

    @abstractmethod
    def format(self, ctx: AdapterContext) -> StageResult:
        """Target structure → exact wire payload."""

    @abstractmethod
    async def submit(self, ctx: AdapterContext) -> StageResult:
        """Send the formatted payload to the government/target endpoint."""

    @abstractmethod
    def receive_confirmation(self, ctx: AdapterContext, response: Any) -> StageResult:
        """Normalize an endpoint response into a canonical confirmation."""

    # --------------------------------------------- platform-owned defaults

    def update_erp(self, ctx: AdapterContext) -> StageResult:
        """
        Push the confirmation back to the customer ERP.

        Default defers to the shared Core ERP connector (Phase 6). Adapters
        override only when a country needs a bespoke ERP contract.
        """
        return StageResult.fail(
            AdapterStage.ERP_UPDATE,
            "ERP update is handled by the Core ERP connector (Phase 6)",
            ERROR_NOT_IMPLEMENTED,
        )

    def generate_monitoring_event(
        self,
        ctx: AdapterContext,
        stage: AdapterStage,
        status: str,
        detail: Optional[str] = None,
        **extra: Any,
    ) -> StageResult:
        """
        Build a monitoring event for the shared monitoring layer (Phase 8).

        Returns the event; it does not persist anything — persistence is a
        platform concern.
        """
        event = ctx.record_event(stage, status, detail, **extra)
        return StageResult.ok(AdapterStage.MONITORING, event)
