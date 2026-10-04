"""Pydantic schemas for the opt-in Invoice Processing Pipeline API (Phase 4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class PipelineRunRequest(BaseModel):
    """Body for POST /api/v1/pipeline/run."""

    customer_id: str = Field(..., min_length=1, max_length=255)
    payload: str = Field(..., min_length=1, description="Document content (e.g. CFDI XML)")
    country_code: Optional[str] = Field(
        None,
        description="Opaque registry key. Required when the workspace has multiple enabled adapters.",
    )
    document_type: Optional[str] = None
    dry_run: bool = Field(
        False,
        description="Run local stages only; skip submit / confirmation / ERP update.",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("customer_id")
    @classmethod
    def _strip_customer_id(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("customer_id is required")
        return v

    @field_validator("country_code")
    @classmethod
    def _normalize_country(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


class StageOutcomeResponse(BaseModel):
    stage: str
    status: str
    attempts: int = 1
    duration_ms: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None
    detail: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class PipelineRunResponse(BaseModel):
    correlation_id: str
    customer_id: str
    country_code: Optional[str] = None
    status: str
    succeeded: bool
    error: Optional[str] = None
    error_code: Optional[str] = None
    failed_stage: Optional[str] = None
    duration_ms: float = 0.0
    stages: List[StageOutcomeResponse] = Field(default_factory=list)
    confirmation: Optional[Any] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


class PipelineStageInfo(BaseModel):
    name: str
    always_run: bool = False
    skip_on_dry_run: bool = False
    max_attempts: int = 1


class PipelineStagesResponse(BaseModel):
    stages: List[PipelineStageInfo]


class PipelineAdapterInfo(BaseModel):
    country_code: str
    display_name: str = ""
    supported_document_types: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class PipelineAdaptersResponse(BaseModel):
    adapters: List[PipelineAdapterInfo]
