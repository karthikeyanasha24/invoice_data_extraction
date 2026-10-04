"""
BridgeEDI Core — Workspace context resolution and access guards (Phase 2).

Additive module: does not change existing auth or invoice/SAT services.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ...models.customer import Customer
from ...models.user import ZodiacUser
from ...models.user_customer import UserCustomer
from ...models.workspace import (
    WorkspaceAdapterConfig,
    WorkspaceErpConnection,
    WorkspaceSettings,
)


@dataclass
class WorkspaceContext:
    """Resolved workspace for a request. workspace_id == customer_id."""

    customer_id: str
    display_name: Optional[str] = None
    pipeline_enabled: bool = False
    ai_scoped: bool = True
    monitoring_enabled: bool = True
    flags: Optional[dict] = None
    settings: Optional[WorkspaceSettings] = None
    erp: Optional[WorkspaceErpConnection] = None  # primary (or first) connection
    erps: List[WorkspaceErpConnection] = field(default_factory=list)
    adapters: List[WorkspaceAdapterConfig] = field(default_factory=list)

    @property
    def workspace_id(self) -> str:
        return self.customer_id

    def enabled_country_codes(self) -> List[str]:
        return [a.country_code for a in self.adapters if a.enabled]


def list_assigned_customer_ids(db: Session, user: ZodiacUser) -> List[str]:
    """Customer IDs assigned to a customer-user via user_customers."""
    rows = (
        db.query(UserCustomer.customer_id)
        .filter(UserCustomer.user_id == user.id)
        .all()
    )
    return [r[0] for r in rows]


def user_can_access_customer(db: Session, user: ZodiacUser, customer_id: str) -> bool:
    """
    Access rules:
    - Admin: any existing customer
    - Customer user: only assigned customer_ids
    - Other authenticated users: denied for workspace APIs
    """
    if not customer_id:
        return False
    if getattr(user, "is_admin", False):
        exists = (
            db.query(Customer.id)
            .filter(Customer.customer_id == customer_id)
            .first()
        )
        return exists is not None
    if getattr(user, "is_customer_user", False):
        return customer_id in list_assigned_customer_ids(db, user)
    return False


def require_workspace_access(
    db: Session,
    user: ZodiacUser,
    customer_id: str,
    *,
    hide_existence: bool = True,
) -> None:
    """
    Enforce workspace membership.

    For non-admin callers, prefer HTTP 404 over 403 so unauthorized users
    cannot probe whether a customer_id exists (IDOR hardening).
    """
    if user_can_access_customer(db, user, customer_id):
        return
    if hide_existence and not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Not authorized for workspace '{customer_id}'",
    )


def get_or_none_settings(db: Session, customer_id: str) -> Optional[WorkspaceSettings]:
    return (
        db.query(WorkspaceSettings)
        .filter(WorkspaceSettings.customer_id == customer_id)
        .first()
    )


def resolve_workspace(
    db: Session,
    user: ZodiacUser,
    customer_id: str,
    *,
    require_access: bool = True,
) -> WorkspaceContext:
    """
    Load workspace settings (+ ERP connections + adapters).
    Raises 403/404 if require_access and user cannot access customer.
    Raises 404 if customer does not exist (after access check for admins).
    """
    if require_access:
        require_workspace_access(db, user, customer_id)

    customer = (
        db.query(Customer).filter(Customer.customer_id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found",
        )

    settings = get_or_none_settings(db, customer_id)
    erps = (
        db.query(WorkspaceErpConnection)
        .filter(WorkspaceErpConnection.customer_id == customer_id)
        .order_by(WorkspaceErpConnection.connection_key)
        .all()
    )
    primary = next((e for e in erps if e.connection_key == "primary"), None)
    if primary is None and erps:
        primary = erps[0]

    adapters = (
        db.query(WorkspaceAdapterConfig)
        .filter(WorkspaceAdapterConfig.customer_id == customer_id)
        .order_by(WorkspaceAdapterConfig.country_code)
        .all()
    )

    return WorkspaceContext(
        customer_id=customer_id,
        display_name=(settings.display_name if settings else None) or customer_id,
        pipeline_enabled=bool(settings.pipeline_enabled) if settings else False,
        ai_scoped=bool(settings.ai_scoped) if settings else True,
        monitoring_enabled=bool(settings.monitoring_enabled) if settings else True,
        flags=settings.flags if settings else None,
        settings=settings,
        erp=primary,
        erps=list(erps),
        adapters=list(adapters),
    )


def assert_ai_workspace_scope(ctx: WorkspaceContext) -> None:
    """
    Phase 9 readiness: call before executing workspace-mode AI queries.
    Does not change adaptive_query yet — provides the extension point.
    """
    if not ctx.ai_scoped:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI is not scoped for this workspace (ai_scoped=false)",
        )


def apply_customer_id_filter(query, column, customer_id: str):
    """Helper for workspace-scoped queries (composition for later phases)."""
    return query.filter(column == customer_id)


def apply_customer_ids_filter(query, column, customer_ids: Sequence[str]):
    """Filter to a set of allowed customer_ids (empty → no rows)."""
    ids = list(customer_ids or [])
    if not ids:
        return query.filter(False)
    return query.filter(column.in_(ids))


# Accepted prefixes for secret references (never store raw credentials)
SECRET_REF_PREFIXES = ("vault:", "env:", "secret:", "arn:", "kms:", "ref:")


def is_valid_secret_ref(value: Optional[str]) -> bool:
    if value is None or value == "":
        return True
    v = value.strip()
    return any(v.startswith(p) for p in SECRET_REF_PREFIXES)


def validate_secret_ref_or_raise(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    v = value.strip()
    if not is_valid_secret_ref(v):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{field_name} must be a secret reference "
                f"(prefixes: {', '.join(SECRET_REF_PREFIXES)}), not a plaintext secret"
            ),
        )
    return v
