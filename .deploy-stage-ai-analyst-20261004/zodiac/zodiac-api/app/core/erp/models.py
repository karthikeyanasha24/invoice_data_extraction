"""
BridgeEDI Core — ERP integration types (Phase 6).

Implements the DTOs defined in zodiac/ERP_INTEGRATION_CONTRACT.md.
Country-neutral: no Mexico/India/SAP/Oracle conditionals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ERP_PENDING = "ERP_PENDING"
    ERP_ACKNOWLEDGED = "ERP_ACKNOWLEDGED"
    ERP_FAILED = "ERP_FAILED"


# Stable error codes from the contract.
ERP_NOT_CONFIGURED = "ERP_NOT_CONFIGURED"
ERP_AUTH_FAILED = "ERP_AUTH_FAILED"
ERP_REJECTED = "ERP_REJECTED"
ERP_TIMEOUT = "ERP_TIMEOUT"
ERP_UPDATE_FAILED = "ERP_UPDATE_FAILED"
ERP_DUPLICATE = "ERP_DUPLICATE"
ERP_INVALID_PAYLOAD = "ERP_INVALID_PAYLOAD"

RETRYABLE_ERP_CODES = frozenset(
    {ERP_UPDATE_FAILED, ERP_TIMEOUT, "TIMEOUT", "TRANSIENT"}
)


@dataclass
class ErpError:
    error_code: str
    message: str
    retryable: bool = False
    http_status: Optional[int] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "details": self.details or {},
        }

    @classmethod
    def of(
        cls,
        error_code: str,
        message: str,
        *,
        http_status: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        retryable: Optional[bool] = None,
    ) -> "ErpError":
        if retryable is None:
            retryable = error_code in RETRYABLE_ERP_CODES
        return cls(
            error_code=error_code,
            message=message,
            retryable=retryable,
            http_status=http_status,
            details=details,
        )


@dataclass
class CanonicalConfirmation:
    """Standard confirmation handoff from adapters → ERP connector."""

    correlation_id: str
    customer_id: str
    accepted: bool
    status: DocumentStatus
    idempotency_key: str
    document_id: Optional[str] = None
    external_document_number: Optional[str] = None
    received_at: str = field(default_factory=_utcnow_iso)
    country_code: Optional[str] = None
    raw_response: Any = None
    extensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "document_id": self.document_id,
            "external_document_number": self.external_document_number,
            "status": self.status.value if isinstance(self.status, DocumentStatus) else self.status,
            "accepted": self.accepted,
            "received_at": self.received_at,
            "idempotency_key": self.idempotency_key,
            "country_code": self.country_code,
            "raw_response": self.raw_response,
            "extensions": dict(self.extensions),
        }

    def erp_payload(self) -> Dict[str, Any]:
        """Body fields the connector may send — no country branching."""
        return {
            "correlation_id": self.correlation_id,
            "customer_id": self.customer_id,
            "document_id": self.document_id,
            "external_document_number": self.external_document_number,
            "status": self.status.value if isinstance(self.status, DocumentStatus) else self.status,
            "accepted": self.accepted,
            "received_at": self.received_at,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class ErpPushRequest:
    customer_id: str
    confirmation: CanonicalConfirmation
    connection_key: str = "primary"
    callback_url: Optional[str] = None
    base_url: Optional[str] = None
    auth_type: str = "none"
    client_id_ref: Optional[str] = None
    client_secret_ref: Optional[str] = None
    extra_config: Dict[str, Any] = field(default_factory=dict)

    @property
    def target_url(self) -> Optional[str]:
        return self.callback_url or self.base_url


@dataclass
class ErpPushResult:
    success: bool
    status: DocumentStatus
    idempotency_key: str
    error: Optional[ErpError] = None
    http_status: Optional[int] = None
    response_body: Any = None
    duplicate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "error": self.error.to_dict() if self.error else None,
            "http_status": self.http_status,
            "duplicate": self.duplicate,
        }
