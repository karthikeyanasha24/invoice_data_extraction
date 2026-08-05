"""Workspace helpers for AI Ops (Phase 9)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from .security import AiOpsSecurity


@dataclass
class AiWorkspaceContext:
    workspace_id: str
    customer_id: str
    display_name: Optional[str]
    ai_scoped: bool
    monitoring_enabled: bool
    pipeline_enabled: bool
    principal: Any
    raw: Any


def resolve_ai_workspace(
    db: Session,
    user: Any,
    workspace_id: str,
    *,
    security: Optional[AiOpsSecurity] = None,
) -> AiWorkspaceContext:
    sec = security or AiOpsSecurity()
    ctx = sec.authorize_workspace(db, user, workspace_id)
    return AiWorkspaceContext(
        workspace_id=ctx.customer_id,
        customer_id=ctx.customer_id,
        display_name=getattr(ctx, "display_name", None),
        ai_scoped=bool(getattr(ctx, "ai_scoped", True)),
        monitoring_enabled=bool(getattr(ctx, "monitoring_enabled", True)),
        pipeline_enabled=bool(getattr(ctx, "pipeline_enabled", False)),
        principal=user,
        raw=ctx,
    )
