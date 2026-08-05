"""
Opt-in Invoice Processing Pipeline API (Phase 4, Task 4.3).

Exposes the shared orchestrator without replacing `/api/v1/sat/*`.

Gates (both must pass):
1. Deployment flag `ENABLE_PIPELINE_API=true` (default off).
2. Workspace setting `pipeline_enabled=true` (enforced inside the orchestrator).

No country names appear in this module. The country code is opaque data that
flows into the Adapter Registry.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..api.auth import get_current_user
from ..database import get_db
from ..models.user import ZodiacUser
from ..schemas.pipeline import (
    PipelineAdapterInfo,
    PipelineAdaptersResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineStageInfo,
    PipelineStagesResponse,
    StageOutcomeResponse,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger("zodiac-api.pipeline.api")

#: Deployment-level kill switch. Workspace opt-in is a second, independent gate.
PIPELINE_API_ENV = "ENABLE_PIPELINE_API"


def pipeline_api_enabled() -> bool:
    return os.getenv(PIPELINE_API_ENV, "false").strip().lower() in ("1", "true", "yes", "on")


def _require_pipeline_api() -> None:
    if not pipeline_api_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline API is not enabled on this deployment",
        )


def _map_error_to_http(error_code: Optional[str]) -> int:
    """Translate stable pipeline codes into HTTP status without leaking internals."""
    mapping = {
        "UNAUTHENTICATED": status.HTTP_401_UNAUTHORIZED,
        "WORKSPACE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "WORKSPACE_ACCESS_DENIED": status.HTTP_403_FORBIDDEN,
        "PIPELINE_DISABLED": status.HTTP_403_FORBIDDEN,
        "COUNTRY_NOT_ENABLED": status.HTTP_403_FORBIDDEN,
        "ADAPTER_NOT_RESOLVED": status.HTTP_404_NOT_FOUND,
    }
    return mapping.get(error_code or "", status.HTTP_422_UNPROCESSABLE_ENTITY)


def _to_response(result: Any) -> PipelineRunResponse:
    payload: Dict[str, Any] = result.to_dict()
    return PipelineRunResponse(
        correlation_id=payload["correlation_id"],
        customer_id=payload["customer_id"],
        country_code=payload.get("country_code"),
        status=payload["status"],
        succeeded=payload["succeeded"],
        error=payload.get("error"),
        error_code=payload.get("error_code"),
        failed_stage=payload.get("failed_stage"),
        duration_ms=payload.get("duration_ms") or 0.0,
        stages=[StageOutcomeResponse(**s) for s in payload.get("stages", [])],
        confirmation=getattr(result, "confirmation", None),
        events=payload.get("events") or [],
    )


@router.get("/health")
def pipeline_health():
    """
    Lightweight probe — always available so operators can see whether the API
    flag is on, without running a document.
    """
    return {
        "enabled": pipeline_api_enabled(),
        "env": PIPELINE_API_ENV,
        "message": (
            "Pipeline API is enabled"
            if pipeline_api_enabled()
            else f"Set {PIPELINE_API_ENV}=true to enable"
        ),
    }


@router.get("/stages", response_model=PipelineStagesResponse)
def list_pipeline_stages(
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Describe the default stage plan (country-neutral)."""
    _require_pipeline_api()
    from ..core.pipeline import default_stage_plan

    plan = default_stage_plan()
    return PipelineStagesResponse(
        stages=[
            PipelineStageInfo(
                name=spec.name,
                always_run=spec.always_run,
                skip_on_dry_run=spec.skip_on_dry_run,
                max_attempts=spec.retry.max_attempts,
            )
            for spec in plan
        ]
    )


@router.get("/adapters", response_model=PipelineAdaptersResponse)
def list_registered_adapters(
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Catalog of adapters registered with the platform (from the registry)."""
    _require_pipeline_api()
    from ..adapters import ensure_builtin_adapters, registry

    ensure_builtin_adapters()
    catalog = registry.describe()
    return PipelineAdaptersResponse(
        adapters=[
            PipelineAdapterInfo(
                country_code=item.get("country_code", ""),
                display_name=item.get("display_name", ""),
                supported_document_types=list(item.get("supported_document_types") or []),
                capabilities=list(item.get("capabilities") or []),
                error=item.get("error"),
            )
            for item in catalog
        ]
    )


@router.post("/run", response_model=PipelineRunResponse)
async def run_pipeline(
    body: PipelineRunRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Run one document through the shared orchestrator.

    Does not touch `/api/v1/sat/*`. Requires:
    - `ENABLE_PIPELINE_API=true`
    - authenticated principal with workspace access
    - `workspace_settings.pipeline_enabled=true` for the target customer
    """
    _require_pipeline_api()

    from ..core.monitoring import build_default_monitoring_bundle
    from ..core.pipeline import (
        InvoicePipelineOrchestrator,
        PipelineRequest,
        PlatformServices,
    )

    request = PipelineRequest(
        customer_id=body.customer_id,
        payload=body.payload,
        country_code=body.country_code,
        document_type=body.document_type,
        user=current_user,
        db=db,
        dry_run=body.dry_run,
        metadata=dict(body.metadata or {}),
    )

    # Shared Phase 8 sinks so audit + finalize use the same DB-backed timeline.
    bundle = build_default_monitoring_bundle(db)
    services = PlatformServices(
        monitoring=bundle["monitoring"],
        audit=bundle["audit"],
    )
    orchestrator = InvoicePipelineOrchestrator(services=services)
    result = await orchestrator.run(request)

    # Auth / tenancy failures become HTTP errors so clients can react.
    # Processing failures (validation, mapping, …) stay in the 200 body —
    # the pipeline completed its job of reporting them.
    if result.error_code in {
        "UNAUTHENTICATED",
        "WORKSPACE_NOT_FOUND",
        "WORKSPACE_ACCESS_DENIED",
        "PIPELINE_DISABLED",
        "COUNTRY_NOT_ENABLED",
        "ADAPTER_NOT_RESOLVED",
    }:
        raise HTTPException(
            status_code=_map_error_to_http(result.error_code),
            detail={
                "error": result.error,
                "error_code": result.error_code,
                "failed_stage": result.failed_stage,
                "correlation_id": result.correlation_id,
            },
        )

    logger.info(
        "pipeline run %s customer=%s status=%s country=%s",
        result.correlation_id,
        result.customer_id,
        result.status.value,
        result.country_code,
    )
    return _to_response(result)
