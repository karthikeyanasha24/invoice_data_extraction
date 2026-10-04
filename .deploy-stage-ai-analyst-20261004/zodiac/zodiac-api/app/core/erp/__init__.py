"""
BridgeEDI Core — ERP integration (Phase 6).

Country-neutral confirmation push. See zodiac/ERP_INTEGRATION_CONTRACT.md.
"""
from .connector import ErpConnector, HttpErpConnector, InMemoryOutboxStore
from .hooks import ERP_FULFILLED_IN_SUBMIT, ERP_UPDATE_MODE_FLAG, WorkspaceErpUpdater
from .models import (
    CanonicalConfirmation,
    DocumentStatus,
    ErpError,
    ErpPushRequest,
    ErpPushResult,
)
from .normalize import derive_idempotency_key, normalize_confirmation, try_normalize_confirmation

# Model re-export (defined under app.models to keep database.init_models clean).
from ...models.erp_outbox import ErpPushOutbox  # noqa: E402

__all__ = [
    "CanonicalConfirmation",
    "DocumentStatus",
    "ErpError",
    "ErpPushRequest",
    "ErpPushResult",
    "ErpConnector",
    "HttpErpConnector",
    "InMemoryOutboxStore",
    "WorkspaceErpUpdater",
    "ERP_FULFILLED_IN_SUBMIT",
    "ERP_UPDATE_MODE_FLAG",
    "ErpPushOutbox",
    "normalize_confirmation",
    "try_normalize_confirmation",
    "derive_idempotency_key",
]
