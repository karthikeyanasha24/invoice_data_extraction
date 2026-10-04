"""
Sample GST — thin government bridge (Phase 7).

HTTP/auth/retry live in app.core.government. This module only builds a
CanonicalGovernmentRequest and maps CanonicalGovernmentResponse back to the
legacy dict shape expected by SampleGstAdapter.receive_confirmation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...core.government import (
    CanonicalGovernmentRequest,
    CanonicalGovernmentResponse,
    GovernmentConnector,
    GovernmentOperation,
    build_government_connector,
)
from .config import SampleGstConfig

logger = logging.getLogger("zodiac-api.adapters.sample_gst.connector")


def get_government_connector(
    config: SampleGstConfig,
    *,
    customer_id: str = "",
    connector: Optional[GovernmentConnector] = None,
) -> GovernmentConnector:
    if connector is not None:
        return connector
    # Reuse workspace-shaped dict so the factory can read endpoint/auth.
    adapter_config = {
        "endpoint_url_ref": config.endpoint_url_ref,
        "auth_secret_ref": config.auth_secret_ref,
        "auth_type": config.extra.get("auth_type") or "none",
        "country_code": "sample_gst",
        "extra_config": {
            **config.extra,
            "live_submit": config.live_submit,
            "prefer_mock": not config.live_submit,
            "sandbox_url": config.extra.get("sandbox_url"),
            "environment": config.extra.get("environment", "sandbox"),
            "mock_ack_prefix": config.extra.get("mock_ack_prefix") or "SAMPLE-ACK",
        },
    }
    return build_government_connector(
        adapter_config,
        customer_id=customer_id,
        country_code="sample_gst",
    )


async def submit_payload(
    payload: Dict[str, Any],
    config: SampleGstConfig,
    *,
    customer_id: str = "",
    correlation_id: str = "",
    submission_id: Optional[str] = None,
    connector: Optional[GovernmentConnector] = None,
) -> Dict[str, Any]:
    """Submit via GovernmentConnector; returns a dict compatible with receive_confirmation."""
    gov = get_government_connector(config, customer_id=customer_id, connector=connector)
    request = CanonicalGovernmentRequest(
        customer_id=customer_id or "unknown",
        country_code="sample_gst",
        operation=GovernmentOperation.SUBMIT,
        payload=payload,
        correlation_id=correlation_id or payload.get("correlationId") or "",
        submission_id=submission_id or correlation_id or "",
        content_type="application/json",
        document_type="TAX_INVOICE",
    )
    if not request.correlation_id:
        import uuid

        request.correlation_id = str(uuid.uuid4())
    if not request.submission_id:
        request.submission_id = request.correlation_id

    response = await gov.submit(request)
    return canonical_to_legacy_dict(response)


def canonical_to_legacy_dict(response: CanonicalGovernmentResponse) -> Dict[str, Any]:
    """Map canonical government response → prior sample_gst confirmation shape."""
    return {
        "success": response.accepted and response.status.value in ("ACCEPTED", "PENDING"),
        "mode": (response.raw_response or {}).get("mode")
        if isinstance(response.raw_response, dict)
        else "government",
        "ack_number": response.government_reference,
        "irn": (response.raw_response or {}).get("irn")
        if isinstance(response.raw_response, dict)
        else None,
        "status": response.status.value,
        "raw": response.raw_response,
        "error": None if response.accepted else (response.message or response.error_code),
        "canonical": response.to_dict(),
    }


def normalize_confirmation(response: Any) -> Dict[str, Any]:
    """Legacy entry used by SampleGstAdapter.receive_confirmation."""
    if isinstance(response, CanonicalGovernmentResponse):
        response = canonical_to_legacy_dict(response)
    if not isinstance(response, dict):
        return {
            "accepted": False,
            "document_number": None,
            "error": "No government response available",
            "raw_response": response,
        }
    return {
        "accepted": bool(response.get("success")),
        "document_number": response.get("ack_number"),
        "irn": response.get("irn"),
        "status": response.get("status"),
        "mode": response.get("mode"),
        "status_code": response.get("status_code"),
        "error": response.get("error"),
        "raw_response": response,
    }
