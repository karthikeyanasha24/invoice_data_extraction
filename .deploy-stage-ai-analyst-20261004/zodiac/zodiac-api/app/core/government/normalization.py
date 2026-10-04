"""Normalize raw HTTP / mock payloads into CanonicalGovernmentResponse."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import (
    GOV_AUTH_FAILED,
    GOV_NETWORK_ERROR,
    GOV_REJECTED,
    GOV_TIMEOUT,
    GOV_UNAVAILABLE,
    GOV_UPDATE_FAILED,
    CanonicalGovernmentRequest,
    CanonicalGovernmentResponse,
    GovernmentStatus,
)


def normalize_http_response(
    request: CanonicalGovernmentRequest,
    *,
    http_status: int,
    body: Any,
    latency_ms: Optional[float] = None,
) -> CanonicalGovernmentResponse:
    if 200 <= http_status < 300:
        ref = _extract_reference(body)
        status = GovernmentStatus.PENDING if _looks_pending(body) else GovernmentStatus.ACCEPTED
        return CanonicalGovernmentResponse.of(
            status,
            request,
            government_reference=ref,
            message=_extract_message(body) or "Government accepted",
            raw_response=body,
            http_status=http_status,
            latency_ms=latency_ms,
            retryable=False,
        )

    if http_status in (401, 403):
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.REJECTED,
            request,
            message=f"Government auth failed ({http_status})",
            raw_response=body,
            http_status=http_status,
            error_code=GOV_AUTH_FAILED,
            retryable=False,
            latency_ms=latency_ms,
        )

    if http_status == 408 or http_status == 429:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.RETRY,
            request,
            message=f"Government asked to retry ({http_status})",
            raw_response=body,
            http_status=http_status,
            error_code=GOV_UNAVAILABLE if http_status == 429 else GOV_TIMEOUT,
            retryable=True,
            latency_ms=latency_ms,
        )

    if 400 <= http_status < 500:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.REJECTED,
            request,
            message=f"Government rejected ({http_status})",
            raw_response=body,
            http_status=http_status,
            error_code=GOV_REJECTED,
            retryable=False,
            latency_ms=latency_ms,
        )

    if http_status >= 500:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.RETRY,
            request,
            message=f"Government unavailable ({http_status})",
            raw_response=body,
            http_status=http_status,
            error_code=GOV_UNAVAILABLE,
            retryable=True,
            latency_ms=latency_ms,
        )

    return CanonicalGovernmentResponse.of(
        GovernmentStatus.UNKNOWN,
        request,
        message=f"Unexpected HTTP status {http_status}",
        raw_response=body,
        http_status=http_status,
        error_code=GOV_UPDATE_FAILED,
        retryable=True,
        latency_ms=latency_ms,
    )


def normalize_exception(
    request: CanonicalGovernmentRequest,
    exc: BaseException,
    *,
    latency_ms: Optional[float] = None,
) -> CanonicalGovernmentResponse:
    name = type(exc).__name__.lower()
    msg = str(exc) or name
    if "timeout" in name or "timeout" in msg.lower():
        code, status = GOV_TIMEOUT, GovernmentStatus.RETRY
    elif "connect" in name or "network" in msg.lower():
        code, status = GOV_NETWORK_ERROR, GovernmentStatus.RETRY
    else:
        code, status = GOV_UPDATE_FAILED, GovernmentStatus.RETRY
    return CanonicalGovernmentResponse.of(
        status,
        request,
        message=msg,
        error_code=code,
        retryable=True,
        latency_ms=latency_ms,
        raw_response={"exception": type(exc).__name__, "message": msg},
    )


def _extract_reference(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    for key in (
        "government_reference",
        "ack_number",
        "ackNumber",
        "irn",
        "reference",
        "document_number",
        "uuid",
    ):
        if body.get(key):
            return str(body[key])
    nested = body.get("data") if isinstance(body.get("data"), dict) else None
    if nested:
        return _extract_reference(nested)
    return None


def _extract_message(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    for key in ("message", "detail", "status_message"):
        if body.get(key):
            return str(body[key])
    return None


def _looks_pending(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    status = str(body.get("status") or body.get("state") or "").upper()
    return status in ("PENDING", "QUEUED", "PROCESSING", "IN_PROGRESS")
