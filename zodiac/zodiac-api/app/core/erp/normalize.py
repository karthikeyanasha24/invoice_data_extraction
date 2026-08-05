"""
Acknowledgement normalization (Phase 6).

Turns loosely shaped adapter confirmation dicts into CanonicalConfirmation
without any country-specific branching — only field aliases.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .models import (
    ERP_INVALID_PAYLOAD,
    CanonicalConfirmation,
    DocumentStatus,
    ErpError,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


KNOWN_KEYS = frozenset(
    {
        "correlation_id",
        "customer_id",
        "document_id",
        "external_document_number",
        "document_number",
        "ack_number",
        "sap_document_number",
        "status",
        "accepted",
        "success",
        "received_at",
        "idempotency_key",
        "country_code",
        "raw_response",
        "extensions",
        "error",
        "irn",
        "mode",
        "status_code",
    }
)


def derive_idempotency_key(customer_id: str, correlation_id: str) -> str:
    material = f"{customer_id}:{correlation_id}:erp_push"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_confirmation(
    value: Any,
    *,
    customer_id: str,
    correlation_id: str,
    country_code: Optional[str] = None,
    document_id: Optional[str] = None,
) -> CanonicalConfirmation:
    """
    Normalize adapter output into CanonicalConfirmation.

    Accepts CanonicalConfirmation (passthrough with fills), dicts with legacy
    aliases, or raises ValueError / returns via ErpError helpers for callers.
    """
    if isinstance(value, CanonicalConfirmation):
        conf = value
        if not conf.customer_id:
            conf.customer_id = customer_id
        if not conf.correlation_id:
            conf.correlation_id = correlation_id
        if not conf.idempotency_key:
            conf.idempotency_key = derive_idempotency_key(conf.customer_id, conf.correlation_id)
        if country_code and not conf.country_code:
            conf.country_code = country_code
        return conf

    if value is None:
        raise ValueError("Confirmation payload is missing")

    if not isinstance(value, dict):
        raise ValueError(f"Confirmation must be a dict, got {type(value)!r}")

    data = dict(value)
    accepted = _coerce_accepted(data)
    external = (
        data.get("external_document_number")
        or data.get("document_number")
        or data.get("ack_number")
        or data.get("sap_document_number")
    )
    status = _coerce_status(data, accepted)
    idem = data.get("idempotency_key") or derive_idempotency_key(customer_id, correlation_id)

    extensions = dict(data.get("extensions") or {})
    for key, val in data.items():
        if key not in KNOWN_KEYS and key not in extensions:
            extensions[key] = val
    # Preserve useful opaque fields that are known but country-private.
    for key in ("irn", "mode", "status_code", "error"):
        if key in data and key not in extensions:
            extensions[key] = data[key]

    return CanonicalConfirmation(
        correlation_id=str(data.get("correlation_id") or correlation_id),
        customer_id=str(data.get("customer_id") or customer_id),
        document_id=data.get("document_id") or document_id,
        external_document_number=str(external) if external is not None else None,
        status=status,
        accepted=accepted,
        received_at=str(data.get("received_at") or _utcnow_iso()),
        idempotency_key=str(idem),
        country_code=data.get("country_code") or country_code,
        raw_response=data.get("raw_response", data.get("raw")),
        extensions=extensions,
    )


def try_normalize_confirmation(
    value: Any,
    *,
    customer_id: str,
    correlation_id: str,
    country_code: Optional[str] = None,
    document_id: Optional[str] = None,
) -> tuple[Optional[CanonicalConfirmation], Optional[ErpError]]:
    try:
        return (
            normalize_confirmation(
                value,
                customer_id=customer_id,
                correlation_id=correlation_id,
                country_code=country_code,
                document_id=document_id,
            ),
            None,
        )
    except ValueError as exc:
        return None, ErpError.of(ERP_INVALID_PAYLOAD, str(exc), retryable=False)


def _coerce_accepted(data: Dict[str, Any]) -> bool:
    if "accepted" in data:
        return bool(data["accepted"])
    if "success" in data:
        return bool(data["success"])
    # Nested SAP-style envelope
    raw = data.get("raw_response")
    if isinstance(raw, dict) and "success" in raw:
        return bool(raw["success"])
    return False


def _coerce_status(data: Dict[str, Any], accepted: bool) -> DocumentStatus:
    raw_status = data.get("status")
    if isinstance(raw_status, DocumentStatus):
        return raw_status
    if isinstance(raw_status, str):
        try:
            return DocumentStatus(raw_status.upper())
        except ValueError:
            pass
    return DocumentStatus.ACCEPTED if accepted else DocumentStatus.REJECTED
