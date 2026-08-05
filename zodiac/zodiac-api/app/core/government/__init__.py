"""
BridgeEDI Core — Government Connector Framework (Phase 7).

Separates country business logic from government HTTP/auth/retry.
See zodiac/GOVERNMENT_CONNECTOR_CONTRACT.md.
"""
from .base import (
    CanonicalGovernmentRequest,
    CanonicalGovernmentResponse,
    GovernmentConnector,
    GovernmentEndpointConfig,
    GovernmentHealthResult,
    GovernmentOperation,
    GovernmentStatus,
)
from .connector import (
    AlreadyStampedGovernmentConnector,
    HttpGovernmentConnector,
    MockGovernmentConnector,
)
from .factory import build_government_connector
from .retry import DEFAULT_GOV_RETRY, NO_GOV_RETRY, GovernmentRetryPolicy

__all__ = [
    "GovernmentConnector",
    "CanonicalGovernmentRequest",
    "CanonicalGovernmentResponse",
    "GovernmentEndpointConfig",
    "GovernmentHealthResult",
    "GovernmentOperation",
    "GovernmentStatus",
    "MockGovernmentConnector",
    "AlreadyStampedGovernmentConnector",
    "HttpGovernmentConnector",
    "build_government_connector",
    "GovernmentRetryPolicy",
    "DEFAULT_GOV_RETRY",
    "NO_GOV_RETRY",
]
