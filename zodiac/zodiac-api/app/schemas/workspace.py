"""Pydantic schemas for Customer Workspace APIs (Phase 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

SECRET_REF_PREFIXES = ("vault:", "env:", "secret:", "arn:", "kms:", "ref:")


def _check_secret_ref(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    v = v.strip()
    if not any(v.startswith(p) for p in SECRET_REF_PREFIXES):
        raise ValueError(
            f"Must be a secret reference with prefix "
            f"{', '.join(SECRET_REF_PREFIXES)} — plaintext secrets are rejected"
        )
    return v


class WorkspaceSettingsCreate(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=255)
    display_name: Optional[str] = None
    pipeline_enabled: bool = False
    ai_scoped: bool = True
    monitoring_enabled: bool = True
    flags: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class WorkspaceSettingsUpdate(BaseModel):
    display_name: Optional[str] = None
    pipeline_enabled: Optional[bool] = None
    ai_scoped: Optional[bool] = None
    monitoring_enabled: Optional[bool] = None
    flags: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class WorkspaceSettingsResponse(BaseModel):
    id: int
    customer_id: str
    display_name: Optional[str] = None
    pipeline_enabled: bool
    ai_scoped: bool
    monitoring_enabled: bool = True
    flags: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkspaceErpUpsert(BaseModel):
    connection_key: str = Field(default="primary", min_length=1, max_length=64)
    label: Optional[str] = None
    base_url: Optional[str] = None
    callback_url: Optional[str] = None
    auth_type: str = "none"
    client_id_ref: Optional[str] = None
    client_secret_ref: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None
    is_active: bool = True

    @field_validator("client_id_ref", "client_secret_ref")
    @classmethod
    def refs_only(cls, v: Optional[str]) -> Optional[str]:
        return _check_secret_ref(v)

    @field_validator("connection_key")
    @classmethod
    def normalize_key(cls, v: str) -> str:
        return (v or "primary").strip().lower().replace(" ", "_")


class WorkspaceErpResponse(BaseModel):
    id: int
    customer_id: str
    connection_key: str = "primary"
    label: Optional[str] = None
    base_url: Optional[str] = None
    callback_url: Optional[str] = None
    auth_type: str
    client_id_ref: Optional[str] = None
    client_secret_ref: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkspaceAdapterUpsert(BaseModel):
    country_code: str = Field(..., min_length=1, max_length=32)
    enabled: bool = False
    endpoint_url_ref: Optional[str] = None
    auth_type: Optional[str] = None
    auth_secret_ref: Optional[str] = None
    document_types: Optional[List[str]] = None
    rules_version: Optional[str] = None
    mapping_ref: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None

    @field_validator("auth_secret_ref")
    @classmethod
    def auth_ref_only(cls, v: Optional[str]) -> Optional[str]:
        return _check_secret_ref(v)

    @field_validator("endpoint_url_ref")
    @classmethod
    def endpoint_https_or_ref(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if v.startswith("http://") or v.startswith("https://"):
            return v
        return _check_secret_ref(v)

    @field_validator("country_code")
    @classmethod
    def normalize_country(cls, v: str) -> str:
        return v.strip().lower()


class WorkspaceAdapterResponse(BaseModel):
    id: int
    customer_id: str
    country_code: str
    enabled: bool
    endpoint_url_ref: Optional[str] = None
    auth_type: Optional[str] = None
    auth_secret_ref: Optional[str] = None
    document_types: Optional[List[str]] = None
    rules_version: Optional[str] = None
    mapping_ref: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkspaceSummaryResponse(BaseModel):
    workspace_id: str
    customer_id: str
    display_name: Optional[str] = None
    pipeline_enabled: bool = False
    ai_scoped: bool = True
    monitoring_enabled: bool = True
    flags: Optional[Dict[str, Any]] = None
    has_settings: bool = False
    erp: Optional[WorkspaceErpResponse] = None
    erps: List[WorkspaceErpResponse] = []
    adapters: List[WorkspaceAdapterResponse] = []
    target_format: Optional[str] = None


class WorkspaceListItem(BaseModel):
    workspace_id: str
    customer_id: str
    display_name: Optional[str] = None
    pipeline_enabled: bool = False
    ai_scoped: bool = True
    monitoring_enabled: bool = True
    has_settings: bool = False
    enabled_adapters: List[str] = []


class WorkspaceListResponse(BaseModel):
    total: int
    skip: int = 0
    limit: int = 100
    workspaces: List[WorkspaceListItem]


class OnboardingStep(BaseModel):
    key: str
    label: str
    ok: bool
    required: bool = True
    detail: Optional[str] = None


class WorkspaceOnboardingStatusResponse(BaseModel):
    """First-customer readiness checklist for a workspace."""

    customer_id: str
    workspace_id: str
    ready: bool
    missing: List[str] = []
    steps: List[OnboardingStep] = []
    summary: Dict[str, Any] = {}
    pipeline_prerequisites_met: bool = False
    pipeline_prerequisites_missing: List[str] = []
