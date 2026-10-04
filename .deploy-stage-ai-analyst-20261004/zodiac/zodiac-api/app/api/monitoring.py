"""
Opt-in Monitoring API (Phase 8).

Workspace-scoped pipeline observability. Does not alter SAT / invoice routes.
Observes data produced by PersistingAuditSink / PersistingMonitoringSink.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..api.auth import get_current_user
from ..core.workspace.context import require_workspace_access
from ..database import get_db
from ..models.user import ZodiacUser
from ..schemas.monitoring import (
    AlertRaiseRequest,
    MonitoringAlertsResponse,
    MonitoringHealthResponse,
    MonitoringSummaryResponse,
    MonitoringTimelineResponse,
)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])
logger = logging.getLogger("zodiac-api.monitoring.api")

MONITORING_API_ENV = "ENABLE_MONITORING_API"


def monitoring_api_enabled() -> bool:
    return os.getenv(MONITORING_API_ENV, "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _require_monitoring_api() -> None:
    if not monitoring_api_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitoring API is not enabled on this deployment",
        )


def _dashboard(db: Session):
    from ..core.monitoring import (
        AlertService,
        MetricsStore,
        MonitoringDashboard,
        TimelineStore,
    )

    timeline = TimelineStore(db=db)
    metrics = MetricsStore(db=db)
    alerts = AlertService(db=db)
    return MonitoringDashboard(timeline=timeline, metrics=metrics, alerts=alerts), alerts, timeline


@router.get("/health", response_model=MonitoringHealthResponse)
def monitoring_health():
    return MonitoringHealthResponse(
        enabled=monitoring_api_enabled(),
        env=MONITORING_API_ENV,
        message=(
            "Monitoring API is enabled"
            if monitoring_api_enabled()
            else f"Set {MONITORING_API_ENV}=true to enable"
        ),
    )


@router.get(
    "/workspaces/{customer_id}/summary",
    response_model=MonitoringSummaryResponse,
)
def workspace_monitoring_summary(
    customer_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Workspace dashboard aggregates — isolated to customer_id."""
    _require_monitoring_api()
    require_workspace_access(db, current_user, customer_id)
    dashboard, _, _ = _dashboard(db)
    payload = dashboard.summary(customer_id, limit=limit)
    return MonitoringSummaryResponse(**payload)


@router.get(
    "/workspaces/{customer_id}/timelines/{correlation_id}",
    response_model=MonitoringTimelineResponse,
)
def workspace_timeline(
    customer_id: str,
    correlation_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_monitoring_api()
    require_workspace_access(db, current_user, customer_id)
    _, _, timeline = _dashboard(db)
    tl = timeline.get_timeline(correlation_id, customer_id=customer_id)
    if tl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline not found")
    return MonitoringTimelineResponse(**tl.to_dict())


@router.get("/workspaces/{customer_id}/transactions")
def workspace_transactions(
    customer_id: str,
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_monitoring_api()
    require_workspace_access(db, current_user, customer_id)
    _, _, timeline = _dashboard(db)
    items = timeline.list_for_workspace(customer_id, limit=limit, status=status_filter)
    return {
        "customer_id": customer_id,
        "workspace_id": customer_id,
        "transactions": [t.to_dict() for t in items],
    }


@router.get(
    "/workspaces/{customer_id}/alerts",
    response_model=MonitoringAlertsResponse,
)
def workspace_alerts(
    customer_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_monitoring_api()
    require_workspace_access(db, current_user, customer_id)
    _, alerts, _ = _dashboard(db)
    return MonitoringAlertsResponse(
        customer_id=customer_id,
        workspace_id=customer_id,
        alerts=alerts.list_for_workspace(customer_id, limit=limit),
    )


@router.post("/workspaces/{customer_id}/alerts")
def raise_workspace_alert(
    customer_id: str,
    body: AlertRaiseRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Framework test hook — raises an alert through registered channels (log only)."""
    _require_monitoring_api()
    require_workspace_access(db, current_user, customer_id)
    from ..core.monitoring import Alert, AlertSeverity, AlertType

    try:
        alert_type = AlertType(body.alert_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown alert_type: {body.alert_type}",
        ) from exc

    try:
        severity = AlertSeverity(body.severity)
    except ValueError:
        severity = AlertSeverity.WARNING

    _, alerts, _ = _dashboard(db)
    return alerts.raise_alert(
        Alert(
            customer_id=customer_id,
            correlation_id=body.correlation_id,
            alert_type=alert_type,
            severity=severity,
            title=body.title,
            message=body.message,
            payload=dict(body.payload or {}),
        )
    )


@router.get("/workspaces/{customer_id}/ai-facts")
def workspace_ai_facts(
    customer_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Structured monitoring facts for future AI (Phase 9).
    Does not call or modify the AI stack.
    """
    _require_monitoring_api()
    require_workspace_access(db, current_user, customer_id)
    dashboard, _, _ = _dashboard(db)
    return {
        "customer_id": customer_id,
        "workspace_id": customer_id,
        "facts": dashboard.ai_facts(customer_id, limit=limit),
    }
