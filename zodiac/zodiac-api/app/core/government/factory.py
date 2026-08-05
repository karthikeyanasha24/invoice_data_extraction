"""
Build a GovernmentConnector from workspace adapter configuration (Phase 7).
"""
from __future__ import annotations

from typing import Any, Optional

from .auth import is_usable_http_url
from .base import GovernmentConnector, GovernmentEndpointConfig
from .connector import (
    AlreadyStampedGovernmentConnector,
    HttpGovernmentConnector,
    MockGovernmentConnector,
)
from ..secrets import SecretResolver, get_default_secret_resolver


def build_government_connector(
    adapter_config: Any = None,
    *,
    customer_id: str = "",
    country_code: str = "",
    prefer_mock: Optional[bool] = None,
    already_stamped: bool = False,
    http_client: Any = None,
    secret_resolver: Optional[SecretResolver] = None,
) -> GovernmentConnector:
    """
    Factory used by adapters / tests.

    - already_stamped=True → AlreadyStampedGovernmentConnector (Mexico)
    - prefer_mock / no usable URL → MockGovernmentConnector
    - usable http(s) URL → HttpGovernmentConnector
    """
    if already_stamped:
        return AlreadyStampedGovernmentConnector()

    config = GovernmentEndpointConfig.from_workspace_adapter(
        adapter_config, customer_id=customer_id, country_code=country_code
    )

    extra = config.extra or {}
    if prefer_mock is None:
        prefer_mock = bool(extra.get("prefer_mock", True)) and not bool(extra.get("live_submit"))

    if prefer_mock or not is_usable_http_url(config.endpoint_url):
        prefix = str(extra.get("mock_ack_prefix") or "MOCK-ACK")
        return MockGovernmentConnector(prefix=prefix)

    return HttpGovernmentConnector(
        config,
        http_client=http_client,
        secret_resolver=secret_resolver or get_default_secret_resolver(),
    )
