"""
Additive AI Operational Intelligence API (Phase 9).

Consumes monitoring facts only. Does not modify adaptive_query / dashboard AI.
Does not participate in the invoice processing pipeline.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..api.auth import get_current_user
from ..core.ai import (
    AiOpsAuditEvent,
    AiOpsSecurity,
    MonitoringOperationalDataSource,
    OperationalAnalytics,
    OperationalQueryService,
    OperationalSummarizer,
    RecommendationEngine,
    resolve_ai_workspace,
)
from ..database import get_db
from ..models.user import ZodiacUser
from ..schemas.ai_ops import AiAskRequest, AiCompareRequest, AiOpsHealthResponse

router = APIRouter(prefix="/ai", tags=["ai-ops"])
logger = logging.getLogger("zodiac-api.ai.api")

AI_OPS_API_ENV = "ENABLE_AI_OPS_API"
_security = AiOpsSecurity()


def ai_ops_api_enabled() -> bool:
    return os.getenv(AI_OPS_API_ENV, "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _require_ai_ops_api() -> None:
    if not ai_ops_api_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI Ops API is not enabled on this deployment",
        )


def _services(db: Session):
    source = MonitoringOperationalDataSource.from_db(db)
    analytics = OperationalAnalytics(source)
    recommendations = RecommendationEngine()
    summarizer = OperationalSummarizer(
        source, analytics=analytics, recommendations=recommendations
    )
    query = OperationalQueryService(
        source, analytics=analytics, recommendations=recommendations
    )
    return source, analytics, recommendations, summarizer, query


@router.get("/health", response_model=AiOpsHealthResponse)
def ai_ops_health():
    return AiOpsHealthResponse(
        enabled=ai_ops_api_enabled(),
        env=AI_OPS_API_ENV,
        message=(
            "AI Ops API is enabled"
            if ai_ops_api_enabled()
            else f"Set {AI_OPS_API_ENV}=true to enable"
        ),
    )


@router.get("/workspace/{workspace_id}/summary")
def workspace_ai_summary(
    workspace_id: str,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_ai_ops_api()
    resolve_ai_workspace(db, current_user, workspace_id, security=_security)
    _, _, _, summarizer, _ = _services(db)
    result = summarizer.summarize(workspace_id, limit=limit)
    _security.audit(
        AiOpsAuditEvent(
            action="summary",
            workspace_id=workspace_id,
            principal_id=getattr(current_user, "id", None),
        )
    )
    return result


@router.get("/workspace/{workspace_id}/analytics")
def workspace_ai_analytics(
    workspace_id: str,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_ai_ops_api()
    resolve_ai_workspace(db, current_user, workspace_id, security=_security)
    _, analytics, _, _, _ = _services(db)
    result = analytics.workspace_analytics(workspace_id, limit=limit)
    _security.audit(
        AiOpsAuditEvent(
            action="analytics",
            workspace_id=workspace_id,
            principal_id=getattr(current_user, "id", None),
        )
    )
    return result


@router.get("/workspace/{workspace_id}/recommendations")
def workspace_ai_recommendations(
    workspace_id: str,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_ai_ops_api()
    resolve_ai_workspace(db, current_user, workspace_id, security=_security)
    _, analytics, recommendations, _, _ = _services(db)
    facts = analytics.workspace_analytics(workspace_id, limit=limit)
    recs = recommendations.generate(facts)
    _security.audit(
        AiOpsAuditEvent(
            action="recommendations",
            workspace_id=workspace_id,
            principal_id=getattr(current_user, "id", None),
        )
    )
    return {
        "workspace_id": workspace_id,
        "customer_id": workspace_id,
        "recommendations": recs,
    }


@router.post("/workspace/{workspace_id}/ask")
def workspace_ai_ask(
    workspace_id: str,
    body: AiAskRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    _require_ai_ops_api()
    resolve_ai_workspace(db, current_user, workspace_id, security=_security)
    _, analytics, _, _, query = _services(db)

    compare = None
    cross = False
    intent_preview = OperationalQueryService.classify(body.question)
    if intent_preview in {"highest_failure_rate", "most_active_workspace"}:
        ids = list(body.workspace_ids or [])
        if workspace_id not in ids:
            ids.insert(0, workspace_id)
        allowed = _security.authorize_cross_workspace(
            db,
            current_user,
            ids,
            authorize_cross_workspace=body.authorize_cross_workspace,
        )
        compare = analytics.compare_workspaces(allowed, limit=body.limit)
        cross = True

    result = query.ask(
        workspace_id,
        body.question,
        limit=body.limit,
        compare=compare,
    )
    _security.audit(
        AiOpsAuditEvent(
            action="ask",
            workspace_id=workspace_id,
            principal_id=getattr(current_user, "id", None),
            question_class=result.get("intent"),
            cross_workspace=cross,
            workspace_ids=list(body.workspace_ids or [workspace_id]),
        )
    )
    return result


@router.post("/admin/compare")
def admin_compare_workspaces(
    body: AiCompareRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Explicit admin cross-workspace comparison (failure rates / activity)."""
    _require_ai_ops_api()
    allowed = _security.authorize_cross_workspace(
        db,
        current_user,
        body.workspace_ids,
        authorize_cross_workspace=body.authorize_cross_workspace,
    )
    _, analytics, _, _, _ = _services(db)
    result = analytics.compare_workspaces(allowed, limit=body.limit)
    _security.audit(
        AiOpsAuditEvent(
            action="admin_compare",
            workspace_id=allowed[0],
            principal_id=getattr(current_user, "id", None),
            cross_workspace=True,
            workspace_ids=allowed,
            question_class="compare_workspaces",
        )
    )
    return result
