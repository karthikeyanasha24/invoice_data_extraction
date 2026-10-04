"""AI Ops security & audit helpers (Phase 9)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..workspace.context import (
    assert_ai_workspace_scope,
    require_workspace_access,
    resolve_workspace,
    user_can_access_customer,
)

logger = logging.getLogger("zodiac-api.ai.security")


@dataclass
class AiOpsAuditEvent:
    action: str
    workspace_id: str
    principal_id: Optional[Any] = None
    question_class: Optional[str] = None
    cross_workspace: bool = False
    workspace_ids: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "principal_id": self.principal_id,
            "workspace_id": self.workspace_id,
            "workspace_ids": list(self.workspace_ids or [self.workspace_id]),
            "action": self.action,
            "question_class": self.question_class,
            "cross_workspace": self.cross_workspace,
            "meta": dict(self.meta),
        }


class AiOpsSecurity:
    """Enforces workspace isolation and optional admin cross-workspace access."""

    def __init__(self) -> None:
        self._audit_log: List[Dict[str, Any]] = []

    def authorize_workspace(
        self,
        db: Session,
        user: Any,
        workspace_id: str,
    ):
        """Access + ai_scoped. Returns WorkspaceContext."""
        require_workspace_access(db, user, workspace_id)
        ctx = resolve_workspace(db, user, workspace_id, require_access=False)
        assert_ai_workspace_scope(ctx)
        return ctx

    def authorize_cross_workspace(
        self,
        db: Session,
        user: Any,
        workspace_ids: Sequence[str],
        *,
        authorize_cross_workspace: bool,
    ) -> List[str]:
        """
        Explicit cross-workspace authorization.

        Requires admin + authorize_cross_workspace=true. Each id must be accessible.
        """
        if not authorize_cross_workspace:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-workspace AI access requires authorize_cross_workspace=true",
            )
        if not getattr(user, "is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-workspace AI access requires administrative privileges",
            )
        allowed: List[str] = []
        for wid in workspace_ids:
            if not wid:
                continue
            if not user_can_access_customer(db, user, wid):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Not authorized for workspace '{wid}'",
                )
            # ai_scoped per workspace
            ctx = resolve_workspace(db, user, wid, require_access=False)
            assert_ai_workspace_scope(ctx)
            allowed.append(wid)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No workspaces provided for cross-workspace analytics",
            )
        return allowed

    def audit(self, event: AiOpsAuditEvent) -> Dict[str, Any]:
        payload = event.to_dict()
        self._audit_log.append(payload)
        logger.info(
            "[ai-ops-audit] action=%s workspace=%s principal=%s cross=%s class=%s",
            event.action,
            event.workspace_id,
            event.principal_id,
            event.cross_workspace,
            event.question_class,
        )
        return payload

    @property
    def audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit_log)
