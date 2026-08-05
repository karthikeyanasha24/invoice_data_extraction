"""Pydantic schemas for Monitoring API (Phase 8)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MonitoringHealthResponse(BaseModel):
    enabled: bool
    env: str
    message: str


class TimelineStageResponse(BaseModel):
    stage: str
    status: str
    timestamp: str
    duration_ms: Optional[float] = None
    message: Optional[str] = None
    attempt: int = 1
    error_code: Optional[str] = None


class MonitoringTimelineResponse(BaseModel):
    correlation_id: str
    customer_id: str
    workspace_id: Optional[str] = None
    country_code: Optional[str] = None
    adapter_name: Optional[str] = None
    document_type: Optional[str] = None
    status: str
    current_stage: Optional[str] = None
    retry_count: int = 0
    latency_ms: Optional[float] = None
    failure_reason: Optional[str] = None
    failed_stage: Optional[str] = None
    government_reference: Optional[str] = None
    erp_reference: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    stages: List[TimelineStageResponse] = Field(default_factory=list)


class MonitoringCounts(BaseModel):
    running: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0
    retrying: int = 0
    dry_run: int = 0
    total: int = 0


class TopErrorItem(BaseModel):
    key: str
    count: int


class MonitoringSummaryResponse(BaseModel):
    workspace_id: str
    customer_id: str
    counts: MonitoringCounts
    average_processing_time_ms: Optional[float] = None
    success_rate_percent: Optional[float] = None
    top_errors: List[TopErrorItem] = Field(default_factory=list)
    latest_transactions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_alerts: List[Dict[str, Any]] = Field(default_factory=list)


class MonitoringAlertsResponse(BaseModel):
    customer_id: str
    workspace_id: str
    alerts: List[Dict[str, Any]] = Field(default_factory=list)


class AlertRaiseRequest(BaseModel):
    alert_type: str
    title: str
    message: str = ""
    severity: str = "warning"
    correlation_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
