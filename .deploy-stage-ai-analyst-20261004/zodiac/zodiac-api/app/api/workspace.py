"""
Customer Workspace API — additive routes (Phase 2, hardened review).

Does not modify invoices, SAT, dashboard, or auth routers.
workspace_id == customer_id.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.customer import Customer
from ..models.user import ZodiacUser
from ..models.workspace import (
    WorkspaceAdapterConfig,
    WorkspaceErpConnection,
    WorkspaceSettings,
)
from ..schemas.workspace import (
    WorkspaceAdapterResponse,
    WorkspaceAdapterUpsert,
    WorkspaceErpResponse,
    WorkspaceErpUpsert,
    WorkspaceListItem,
    WorkspaceListResponse,
    WorkspaceOnboardingStatusResponse,
    WorkspaceSettingsCreate,
    WorkspaceSettingsResponse,
    WorkspaceSettingsUpdate,
    WorkspaceSummaryResponse,
)
from ..api.auth import get_current_user
from ..core.workspace.context import (
    list_assigned_customer_ids,
    require_workspace_access,
    resolve_workspace,
    user_can_access_customer,
)
from ..core.workspace.onboarding import evaluate_onboarding

router = APIRouter(prefix="/workspace", tags=["workspace"])
logger = logging.getLogger("zodiac-api.workspace")


def _require_admin(user: ZodiacUser) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


def _settings_response(row: WorkspaceSettings) -> WorkspaceSettingsResponse:
    return WorkspaceSettingsResponse.model_validate(row)


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    List workspaces visible to the caller (paginated).
    Admin: all customers. Customer user: assigned only.
    """
    if current_user.is_admin:
        base_q = db.query(Customer)
    elif getattr(current_user, "is_customer_user", False):
        allowed = list_assigned_customer_ids(db, current_user)
        if not allowed:
            return WorkspaceListResponse(total=0, skip=skip, limit=limit, workspaces=[])
        base_q = db.query(Customer).filter(Customer.customer_id.in_(allowed))
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace access requires admin or customer-user role",
        )

    total = base_q.count()
    customers = (
        base_q.order_by(Customer.customer_id).offset(skip).limit(limit).all()
    )
    cids = [c.customer_id for c in customers]
    if not cids:
        return WorkspaceListResponse(total=total, skip=skip, limit=limit, workspaces=[])

    settings_by_cid = {
        s.customer_id: s
        for s in db.query(WorkspaceSettings)
        .filter(WorkspaceSettings.customer_id.in_(cids))
        .all()
    }
    adapters = (
        db.query(WorkspaceAdapterConfig)
        .filter(
            WorkspaceAdapterConfig.customer_id.in_(cids),
            WorkspaceAdapterConfig.enabled.is_(True),
        )
        .all()
    )
    adapters_by_cid: dict = {}
    for a in adapters:
        adapters_by_cid.setdefault(a.customer_id, []).append(a.country_code)

    items: List[WorkspaceListItem] = []
    for c in customers:
        s = settings_by_cid.get(c.customer_id)
        items.append(
            WorkspaceListItem(
                workspace_id=c.customer_id,
                customer_id=c.customer_id,
                display_name=(s.display_name if s else None) or c.customer_id,
                pipeline_enabled=bool(s.pipeline_enabled) if s else False,
                ai_scoped=bool(s.ai_scoped) if s else True,
                monitoring_enabled=bool(s.monitoring_enabled) if s else True,
                has_settings=s is not None,
                enabled_adapters=adapters_by_cid.get(c.customer_id, []),
            )
        )

    return WorkspaceListResponse(
        total=total, skip=skip, limit=limit, workspaces=items
    )


@router.post(
    "",
    response_model=WorkspaceSettingsResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_settings(
    body: WorkspaceSettingsCreate,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Create workspace settings for an existing customer. Admin only."""
    _require_admin(current_user)

    customer = (
        db.query(Customer).filter(Customer.customer_id == body.customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{body.customer_id}' not found — create customer first",
        )

    existing = (
        db.query(WorkspaceSettings)
        .filter(WorkspaceSettings.customer_id == body.customer_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workspace settings already exist for '{body.customer_id}'",
        )

    row = WorkspaceSettings(
        customer_id=body.customer_id,
        display_name=body.display_name or body.customer_id,
        pipeline_enabled=body.pipeline_enabled,
        ai_scoped=body.ai_scoped,
        monitoring_enabled=body.monitoring_enabled,
        flags=body.flags or {"erp_update_mode": "auto"},
        notes=body.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Workspace settings created for %s", body.customer_id)
    return _settings_response(row)


@router.get("/{customer_id}", response_model=WorkspaceSummaryResponse)
def get_workspace(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Full workspace summary (settings + ERP connections + adapters)."""
    ctx = resolve_workspace(db, current_user, customer_id, require_access=True)
    customer = (
        db.query(Customer).filter(Customer.customer_id == customer_id).first()
    )
    return WorkspaceSummaryResponse(
        workspace_id=ctx.workspace_id,
        customer_id=ctx.customer_id,
        display_name=ctx.display_name,
        pipeline_enabled=ctx.pipeline_enabled,
        ai_scoped=ctx.ai_scoped,
        monitoring_enabled=ctx.monitoring_enabled,
        flags=ctx.flags,
        has_settings=ctx.settings is not None,
        erp=WorkspaceErpResponse.model_validate(ctx.erp) if ctx.erp else None,
        erps=[WorkspaceErpResponse.model_validate(e) for e in ctx.erps],
        adapters=[WorkspaceAdapterResponse.model_validate(a) for a in ctx.adapters],
        target_format=getattr(customer, "target_format", None) if customer else None,
    )


@router.patch("/{customer_id}/settings", response_model=WorkspaceSettingsResponse)
def update_workspace_settings(
    customer_id: str,
    body: WorkspaceSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Update workspace settings. Admin only."""
    _require_admin(current_user)
    require_workspace_access(db, current_user, customer_id)

    row = (
        db.query(WorkspaceSettings)
        .filter(WorkspaceSettings.customer_id == customer_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace settings not found — create them first",
        )

    data = body.model_dump(exclude_unset=True)
    # Merge flags so partial updates (e.g. erp_update_mode) do not wipe others.
    if "flags" in data and data["flags"] is not None:
        merged = dict(row.flags or {})
        merged.update(data["flags"])
        data["flags"] = merged

    # Phase 12 — do not allow enabling pipeline until ERP/adapter/gov are configured.
    enabling_pipeline = data.get("pipeline_enabled") is True and not bool(
        row.pipeline_enabled
    )
    if enabling_pipeline:
        ctx = resolve_workspace(db, current_user, customer_id, require_access=True)
        check = evaluate_onboarding(
            customer_exists=True,
            has_settings=True,
            pipeline_enabled=False,
            ai_scoped=bool(
                data["ai_scoped"] if "ai_scoped" in data else row.ai_scoped
            ),
            monitoring_enabled=bool(
                data["monitoring_enabled"]
                if "monitoring_enabled" in data
                else row.monitoring_enabled
            ),
            flags=data.get("flags") if "flags" in data else (row.flags or {}),
            erp=ctx.erp,
            adapters=list(ctx.adapters or []),
            has_customer_user=True,  # not required to flip pipeline toggle
        )
        missing = list(check.get("pipeline_prerequisites_missing") or [])
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": (
                        "Cannot enable pipeline until workspace prerequisites "
                        "are complete"
                    ),
                    "missing": missing,
                },
            )

    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _settings_response(row)


@router.get(
    "/{customer_id}/onboarding-status",
    response_model=WorkspaceOnboardingStatusResponse,
)
def get_onboarding_status(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Readiness checklist for first-customer go-live configuration.
    Does not change SAT/V1/V2 or pipeline behavior — config visibility only.
    """
    require_workspace_access(db, current_user, customer_id)
    customer = (
        db.query(Customer).filter(Customer.customer_id == customer_id).first()
    )
    ctx = resolve_workspace(db, current_user, customer_id, require_access=True)

    from ..models.user_customer import UserCustomer

    has_customer_user = (
        db.query(UserCustomer)
        .filter(UserCustomer.customer_id == customer_id)
        .first()
        is not None
    )

    result = evaluate_onboarding(
        customer_exists=customer is not None,
        has_settings=ctx.settings is not None,
        pipeline_enabled=ctx.pipeline_enabled,
        ai_scoped=ctx.ai_scoped,
        monitoring_enabled=ctx.monitoring_enabled,
        flags=ctx.flags,
        erp=ctx.erp,
        adapters=list(ctx.adapters or []),
        has_customer_user=has_customer_user,
    )
    return WorkspaceOnboardingStatusResponse(
        customer_id=customer_id,
        workspace_id=ctx.workspace_id,
        ready=result["ready"],
        missing=result["missing"],
        steps=result["steps"],
        summary=result["summary"],
        pipeline_prerequisites_met=bool(result.get("pipeline_prerequisites_met")),
        pipeline_prerequisites_missing=list(
            result.get("pipeline_prerequisites_missing") or []
        ),
    )


@router.put("/{customer_id}/erp", response_model=WorkspaceErpResponse)
def upsert_erp_connection(
    customer_id: str,
    body: WorkspaceErpUpsert,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Create or update one ERP connection (by connection_key).
    Admin only. Multiple connections per workspace supported.
    """
    _require_admin(current_user)
    require_workspace_access(db, current_user, customer_id)

    if not db.query(Customer).filter(Customer.customer_id == customer_id).first():
        raise HTTPException(status_code=404, detail="Customer not found")

    key = body.connection_key
    row = (
        db.query(WorkspaceErpConnection)
        .filter(
            WorkspaceErpConnection.customer_id == customer_id,
            WorkspaceErpConnection.connection_key == key,
        )
        .first()
    )
    payload = body.model_dump()
    if row:
        for k, v in payload.items():
            setattr(row, k, v)
        row.updated_at = datetime.utcnow()
    else:
        row = WorkspaceErpConnection(customer_id=customer_id, **payload)
        db.add(row)
    db.commit()
    db.refresh(row)
    return WorkspaceErpResponse.model_validate(row)


@router.get("/{customer_id}/erp", response_model=List[WorkspaceErpResponse])
def list_erp_connections(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """List all ERP connections for the workspace (scoped)."""
    require_workspace_access(db, current_user, customer_id)
    rows = (
        db.query(WorkspaceErpConnection)
        .filter(WorkspaceErpConnection.customer_id == customer_id)
        .order_by(WorkspaceErpConnection.connection_key)
        .all()
    )
    return [WorkspaceErpResponse.model_validate(r) for r in rows]


@router.get(
    "/{customer_id}/erp/{connection_key}",
    response_model=Optional[WorkspaceErpResponse],
)
def get_erp_connection(
    customer_id: str,
    connection_key: str = "primary",
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    require_workspace_access(db, current_user, customer_id)
    row = (
        db.query(WorkspaceErpConnection)
        .filter(
            WorkspaceErpConnection.customer_id == customer_id,
            WorkspaceErpConnection.connection_key == connection_key.strip().lower(),
        )
        .first()
    )
    if not row:
        return None
    return WorkspaceErpResponse.model_validate(row)


@router.put("/{customer_id}/adapters", response_model=WorkspaceAdapterResponse)
def upsert_adapter_config(
    customer_id: str,
    body: WorkspaceAdapterUpsert,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Enable/configure a country adapter for the workspace. Admin only."""
    _require_admin(current_user)
    require_workspace_access(db, current_user, customer_id)

    if not db.query(Customer).filter(Customer.customer_id == customer_id).first():
        raise HTTPException(status_code=404, detail="Customer not found")

    country = body.country_code
    row = (
        db.query(WorkspaceAdapterConfig)
        .filter(
            WorkspaceAdapterConfig.customer_id == customer_id,
            WorkspaceAdapterConfig.country_code == country,
        )
        .first()
    )
    payload = body.model_dump()
    if row:
        for k, v in payload.items():
            setattr(row, k, v)
        row.updated_at = datetime.utcnow()
    else:
        row = WorkspaceAdapterConfig(customer_id=customer_id, **payload)
        db.add(row)
    db.commit()
    db.refresh(row)
    return WorkspaceAdapterResponse.model_validate(row)


@router.get(
    "/{customer_id}/adapters",
    response_model=List[WorkspaceAdapterResponse],
)
def list_adapter_configs(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    require_workspace_access(db, current_user, customer_id)
    rows = (
        db.query(WorkspaceAdapterConfig)
        .filter(WorkspaceAdapterConfig.customer_id == customer_id)
        .order_by(WorkspaceAdapterConfig.country_code)
        .all()
    )
    return [WorkspaceAdapterResponse.model_validate(r) for r in rows]


@router.get("/{customer_id}/access-check")
def access_check(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Lightweight membership probe for UI routing.
    Does not reveal whether an unauthorized customer_id exists.
    """
    allowed = user_can_access_customer(db, current_user, customer_id)
    return {
        "customer_id": customer_id if allowed else None,
        "workspace_id": customer_id if allowed else None,
        "allowed": allowed,
        "is_admin": bool(current_user.is_admin),
        "is_customer_user": bool(getattr(current_user, "is_customer_user", False)),
    }


@router.get("/{customer_id}/activity")
def workspace_activity(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Read-only activity counts for this workspace only.
    Never returns another customer's aggregates.
    """
    require_workspace_access(db, current_user, customer_id)

    activity = {
        "customer_id": customer_id,
        "workspace_id": customer_id,
        "v2_validated_count": None,
        "sat_document_count": None,
        "receiver_rfc_count": 0,
        "adapter_count": 0,
        "erp_connection_count": 0,
        "notes": [],
    }

    activity["adapter_count"] = (
        db.query(WorkspaceAdapterConfig)
        .filter(WorkspaceAdapterConfig.customer_id == customer_id)
        .count()
    )
    activity["erp_connection_count"] = (
        db.query(WorkspaceErpConnection)
        .filter(WorkspaceErpConnection.customer_id == customer_id)
        .count()
    )

    try:
        from ..models.invoice_v2_validated import InvoiceV2Validated

        activity["v2_validated_count"] = (
            db.query(InvoiceV2Validated)
            .filter(InvoiceV2Validated.invoice_data["customer_id"].astext == customer_id)
            .count()
        )
    except Exception as e:
        activity["notes"].append(f"v2_validated unavailable: {e}")

    try:
        from ..models.customer_receiver_rfc import CustomerReceiverRfc
        from ..models.sat_document import SATDocument

        rfcs = [
            r[0]
            for r in db.query(CustomerReceiverRfc.receiver_rfc)
            .filter(CustomerReceiverRfc.customer_id == customer_id)
            .all()
            if r[0]
        ]
        activity["receiver_rfc_count"] = len(rfcs)
        if rfcs:
            activity["sat_document_count"] = (
                db.query(SATDocument)
                .filter(SATDocument.receiver_rfc.in_(rfcs))
                .count()
            )
        else:
            activity["sat_document_count"] = 0
            activity["notes"].append(
                "No receiver RFCs mapped for this customer — SAT count is 0"
            )
    except Exception as e:
        activity["notes"].append(f"sat_documents unavailable: {e}")

    return activity
