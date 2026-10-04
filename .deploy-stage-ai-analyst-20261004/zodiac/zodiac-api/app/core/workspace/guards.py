"""
Workspace guards used as FastAPI dependencies (Phase 2).
"""
from __future__ import annotations

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import ZodiacUser
from ...api.auth import get_current_user
from .context import WorkspaceContext, resolve_workspace, require_workspace_access


def get_workspace_context(
    customer_id: str = Path(..., description="Workspace id (= customer_id)"),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
) -> WorkspaceContext:
    """Resolve workspace and enforce membership / admin access."""
    return resolve_workspace(db, current_user, customer_id, require_access=True)


def ensure_workspace_path_access(
    customer_id: str,
    db: Session,
    current_user: ZodiacUser,
) -> None:
    """Explicit guard for handlers that resolve context manually."""
    require_workspace_access(db, current_user, customer_id)
