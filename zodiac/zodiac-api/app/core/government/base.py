"""
Government Connector DTOs and Protocol (Phase 7).

See zodiac/GOVERNMENT_CONNECTOR_CONTRACT.md.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernmentOperation(str, Enum):
    SUBMIT = "submit"
    CANCEL = "cancel"
    STATUS = "status"
    DOWNLOAD = "download"


class GovernmentStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    RETRY = "RETRY"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


# Stable error codes
GOV_NOT_CONFIGURED = "GOV_NOT_CONFIGURED"
GOV_AUTH_FAILED = "GOV_AUTH_FAILED"
GOV_REJECTED = "GOV_REJECTED"
GOV_TIMEOUT = "GOV_TIMEOUT"
GOV_NETWORK_ERROR = "GOV_NETWORK_ERROR"
GOV_UNAVAILABLE = "GOV_UNAVAILABLE"
GOV_UPDATE_FAILED = "GOV_UPDATE_FAILED"
GOV_INVALID_REQUEST = "GOV_INVALID_REQUEST"
GOV_DUPLICATE = "GOV_DUPLICATE"
GOV_NOT_SUPPORTED = "GOV_NOT_SUPPORTED"

RETRYABLE_GOV_CODES = frozenset(
    {GOV_TIMEOUT, GOV_NETWORK_ERROR, GOV_UNAVAILABLE, GOV_UPDATE_FAILED}
)


@dataclass
class CanonicalGovernmentRequest:
    customer_id: str
    country_code: str
    operation: GovernmentOperation
    payload: Any
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    submission_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_type: Optional[str] = None
    content_type: str = "application/json"
    government_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    extensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "country_code": self.country_code,
            "operation": self.operation.value if isinstance(self.operation, GovernmentOperation) else self.operation,
            "submission_id": self.submission_id,
            "document_type": self.document_type,
            "content_type": self.content_type,
            "government_reference": self.government_reference,
            "metadata": dict(self.metadata),
            "extensions": dict(self.extensions),
        }


@dataclass
class CanonicalGovernmentResponse:
    status: GovernmentStatus
    submission_id: str
    correlation_id: str
    accepted: bool = False
    government_reference: Optional[str] = None
    message: Optional[str] = None
    raw_response: Any = None
    timestamp: str = field(default_factory=_utcnow_iso)
    http_status: Optional[int] = None
    retryable: bool = False
    error_code: Optional[str] = None
    latency_ms: Optional[float] = None
    extensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, GovernmentStatus) else self.status,
            "accepted": self.accepted,
            "government_reference": self.government_reference,
            "submission_id": self.submission_id,
            "correlation_id": self.correlation_id,
            "message": self.message,
            "raw_response": self.raw_response,
            "timestamp": self.timestamp,
            "http_status": self.http_status,
            "retryable": self.retryable,
            "error_code": self.error_code,
            "latency_ms": self.latency_ms,
            "extensions": dict(self.extensions),
        }

    @classmethod
    def of(
        cls,
        status: GovernmentStatus,
        request: CanonicalGovernmentRequest,
        *,
        government_reference: Optional[str] = None,
        message: Optional[str] = None,
        raw_response: Any = None,
        http_status: Optional[int] = None,
        error_code: Optional[str] = None,
        retryable: Optional[bool] = None,
        latency_ms: Optional[float] = None,
        **extensions: Any,
    ) -> "CanonicalGovernmentResponse":
        accepted = status in (GovernmentStatus.ACCEPTED, GovernmentStatus.PENDING)
        if retryable is None:
            retryable = status is GovernmentStatus.RETRY or (
                error_code in RETRYABLE_GOV_CODES if error_code else False
            )
        return cls(
            status=status,
            accepted=accepted,
            government_reference=government_reference,
            submission_id=request.submission_id,
            correlation_id=request.correlation_id,
            message=message,
            raw_response=raw_response,
            http_status=http_status,
            retryable=retryable,
            error_code=error_code,
            latency_ms=latency_ms,
            extensions=dict(extensions) if extensions else {},
        )


@dataclass
class GovernmentHealthResult:
    healthy: bool
    message: str = ""
    endpoint: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "message": self.message,
            "endpoint": self.endpoint,
            "details": dict(self.details),
        }


@dataclass
class GovernmentEndpointConfig:
    """Resolved workspace government endpoint settings (no secrets in plaintext required)."""

    customer_id: str
    country_code: str
    production_url: Optional[str] = None
    sandbox_url: Optional[str] = None
    environment: str = "sandbox"  # sandbox | production
    auth_type: str = "none"
    auth_secret_ref: Optional[str] = None
    client_id_ref: Optional[str] = None
    client_secret_ref: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def endpoint_url(self) -> Optional[str]:
        env = (self.environment or "sandbox").lower()
        if env == "production":
            return self.production_url or self.sandbox_url
        return self.sandbox_url or self.production_url

    @classmethod
    def from_workspace_adapter(
        cls,
        adapter_config: Any,
        *,
        customer_id: str,
        country_code: Optional[str] = None,
    ) -> "GovernmentEndpointConfig":
        if adapter_config is None:
            return cls(customer_id=customer_id, country_code=country_code or "")

        if isinstance(adapter_config, dict):
            get = adapter_config.get
            extra = adapter_config.get("extra_config") or {}
        else:
            get = lambda k, default=None: getattr(adapter_config, k, default)  # noqa: E731
            extra = getattr(adapter_config, "extra_config", None) or {}
        if not isinstance(extra, dict):
            extra = {}

        production = get("endpoint_url_ref") or extra.get("production_url") or extra.get("endpoint_url")
        sandbox = extra.get("sandbox_url") or extra.get("sandbox_url_ref")
        return cls(
            customer_id=customer_id,
            country_code=country_code or str(get("country_code") or ""),
            production_url=str(production) if production else None,
            sandbox_url=str(sandbox) if sandbox else None,
            environment=str(extra.get("environment") or "sandbox"),
            auth_type=str(get("auth_type") or extra.get("auth_type") or "none"),
            auth_secret_ref=get("auth_secret_ref") or extra.get("auth_secret_ref"),
            client_id_ref=extra.get("client_id_ref"),
            client_secret_ref=extra.get("client_secret_ref") or get("auth_secret_ref"),
            extra=extra,
        )


class GovernmentConnector(ABC):
    """Shared government communication port — no country business logic."""

    @abstractmethod
    async def submit(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse: ...

    @abstractmethod
    async def cancel(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse: ...

    @abstractmethod
    async def status(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse: ...

    @abstractmethod
    async def download(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse: ...

    @abstractmethod
    async def health(self) -> GovernmentHealthResult: ...
