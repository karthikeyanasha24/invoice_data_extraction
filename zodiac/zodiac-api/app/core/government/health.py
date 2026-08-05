"""Health check helpers for government connectors."""
from __future__ import annotations

from .auth import is_usable_http_url, redact_endpoint
from .base import GovernmentEndpointConfig, GovernmentHealthResult


def evaluate_endpoint_health(config: GovernmentEndpointConfig) -> GovernmentHealthResult:
    url = config.endpoint_url
    if not url:
        return GovernmentHealthResult(
            healthy=False,
            message="No government endpoint configured for workspace",
            endpoint=None,
            details={"environment": config.environment},
        )
    if not is_usable_http_url(url):
        return GovernmentHealthResult(
            healthy=False,
            message="Endpoint is not a usable http(s) URL (secret refs need a resolver)",
            endpoint=redact_endpoint(url),
            details={"auth_type": config.auth_type},
        )
    return GovernmentHealthResult(
        healthy=True,
        message="Endpoint configured",
        endpoint=redact_endpoint(url),
        details={"auth_type": config.auth_type, "environment": config.environment},
    )
