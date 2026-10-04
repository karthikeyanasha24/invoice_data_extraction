"""
Pipeline ERP updater — bridges orchestrator ErpUpdater → HttpErpConnector.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .connector import HttpErpConnector
from .models import (
    ERP_NOT_CONFIGURED,
    ERP_UPDATE_FAILED,
    ErpPushRequest,
)
from .normalize import try_normalize_confirmation

logger = logging.getLogger("zodiac-api.erp.hooks")

# Confirmation / metadata marker: adapter submit already performed the ERP write.
ERP_FULFILLED_IN_SUBMIT = "erp_fulfilled_in_submit"
# workspace_settings.flags key — see ERP_INTEGRATION_CONTRACT.md §9
ERP_UPDATE_MODE_FLAG = "erp_update_mode"


class WorkspaceErpUpdater:
    """
    Default PlatformServices.erp_updater for Phase 6.

    - No active ERP connection → NotImplementedError (stage SKIPPED, same as before).
    - Configured → normalize confirmation → HttpErpConnector.push_confirmation.
    - Skips HTTP when submit already fulfilled ERP (unless erp_update_mode=always).
    """

    def __init__(
        self,
        connector: Optional[HttpErpConnector] = None,
        secret_resolver: Any = None,
    ):
        self.connector = connector
        self.secret_resolver = secret_resolver

    def update(self, execution: Any, confirmation: Any) -> Dict[str, Any]:
        workspace = getattr(execution, "workspace", None)
        request = getattr(execution, "request", None)
        db = getattr(request, "db", None) if request is not None else None

        mode = _erp_update_mode(workspace, execution)
        if mode == "never":
            raise NotImplementedError("erp_update_mode=never — platform ERP push disabled")

        fulfilled = _erp_fulfilled_in_submit(confirmation, execution)
        if fulfilled and mode in ("auto", "skip_if_submit_did_erp"):
            raise NotImplementedError(
                "ERP already fulfilled during adapter submit; skipping platform erp_update"
            )

        connection = _select_erp_connection(workspace, execution)
        if connection is None:
            raise NotImplementedError("No active ERP connection configured for this workspace")

        customer_id = getattr(execution, "customer_id", None) or getattr(workspace, "customer_id", "")
        correlation_id = getattr(execution, "correlation_id", "") or ""
        country_code = getattr(execution, "country_code", None)

        canonical, err = try_normalize_confirmation(
            confirmation,
            customer_id=customer_id,
            correlation_id=correlation_id,
            country_code=country_code,
        )
        if err is not None or canonical is None:
            from ..pipeline.types import StageFailed

            raise StageFailed(
                err.message if err else "Invalid confirmation",
                err.error_code if err else "ERP_INVALID_PAYLOAD",
            )

        if not canonical.accepted:
            # Contract: rejected government confirmations are not pushed as success;
            # still notify ERP with accepted=false when configured.
            pass

        push_req = ErpPushRequest(
            customer_id=customer_id,
            connection_key=getattr(connection, "connection_key", None) or "primary",
            confirmation=canonical,
            callback_url=getattr(connection, "callback_url", None),
            base_url=getattr(connection, "base_url", None),
            auth_type=getattr(connection, "auth_type", None) or "none",
            client_id_ref=getattr(connection, "client_id_ref", None),
            client_secret_ref=getattr(connection, "client_secret_ref", None),
            extra_config=dict(getattr(connection, "extra_config", None) or {}),
        )

        if self.connector is not None:
            connector = self.connector
        else:
            from ..secrets import get_default_secret_resolver

            connector = HttpErpConnector(
                db=db,
                secret_resolver=self.secret_resolver or get_default_secret_resolver(),
            )
        # Allow tests to inject memory store via connector; for DB-less runs use memory.
        if connector.db is None and connector.memory_store is None:
            from .connector import InMemoryOutboxStore

            connector.memory_store = InMemoryOutboxStore()

        result = connector.push_confirmation(push_req)

        if result.success:
            return result.to_dict()

        from ..pipeline.types import StageFailed

        code = result.error.error_code if result.error else ERP_UPDATE_FAILED
        message = result.error.message if result.error else "ERP update failed"
        # Map NOT_CONFIGURED to skip when URL missing after connection row exists.
        if code == ERP_NOT_CONFIGURED:
            raise NotImplementedError(message)
        raise StageFailed(message, code, http_status=result.http_status, duplicate=result.duplicate)


def _erp_update_mode(workspace: Any, execution: Any) -> str:
    """
    Resolve erp_update_mode without country branching.

    Precedence: request.metadata → workspace.flags → auto
    """
    raw = None
    request = getattr(execution, "request", None)
    if request is not None:
        meta = getattr(request, "metadata", None) or {}
        raw = meta.get(ERP_UPDATE_MODE_FLAG)
    if raw is None and workspace is not None:
        flags = getattr(workspace, "flags", None) or {}
        if isinstance(flags, dict):
            raw = flags.get(ERP_UPDATE_MODE_FLAG)
    mode = str(raw or "auto").strip().lower()
    if mode in ("auto", "skip_if_submit_did_erp", "always", "never"):
        return mode
    return "auto"


def _erp_fulfilled_in_submit(confirmation: Any, execution: Any) -> bool:
    """True when adapter marked that submit already wrote to the customer ERP."""
    if isinstance(confirmation, dict):
        if confirmation.get(ERP_FULFILLED_IN_SUBMIT) is True:
            return True
        ext = confirmation.get("extensions")
        if isinstance(ext, dict) and ext.get(ERP_FULFILLED_IN_SUBMIT) is True:
            return True
    ctx = getattr(execution, "adapter_ctx", None)
    if ctx is not None:
        meta = getattr(ctx, "metadata", None) or {}
        if meta.get(ERP_FULFILLED_IN_SUBMIT) is True:
            return True
    return False


def _select_erp_connection(workspace: Any, execution: Any) -> Any:
    if workspace is None:
        return None

    preferred = None
    if getattr(execution, "request", None) is not None:
        preferred = (execution.request.metadata or {}).get("erp_connection_key")

    erps = list(getattr(workspace, "erps", None) or [])
    if not erps and getattr(workspace, "erp", None) is not None:
        erps = [workspace.erp]

    active = [e for e in erps if getattr(e, "is_active", True)]
    if not active:
        return None

    if preferred:
        for conn in active:
            if getattr(conn, "connection_key", None) == preferred:
                return conn

    for conn in active:
        if getattr(conn, "connection_key", None) == "primary":
            return conn
    return active[0]
