"""
Pipeline monitoring ORM models (Phase 8) — expand-only tables.

Does not alter SAT / invoice / workspace production tables.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    func,
    JSON,
)

from ..database import Base

JsonType = JSON


class PipelineTimeline(Base):
    """One row per pipeline correlation_id (transaction)."""

    __tablename__ = "pipeline_timelines"
    __table_args__ = (
        Index("ix_pipeline_timelines_customer_status", "customer_id", "status"),
        Index("ix_pipeline_timelines_customer_started", "customer_id", "started_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    correlation_id = Column(String(64), nullable=False, unique=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country_code = Column(String(64), nullable=True, index=True)
    adapter_name = Column(String(128), nullable=True)
    document_type = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="RUNNING", index=True)
    current_stage = Column(String(64), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Float, nullable=True)
    failure_reason = Column(Text, nullable=True)
    failed_stage = Column(String(64), nullable=True)
    government_reference = Column(String(255), nullable=True)
    erp_reference = Column(String(255), nullable=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    extra = Column(JsonType, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())


class PipelineEvent(Base):
    """Stage-level event for a timeline (append-only)."""

    __tablename__ = "pipeline_events"
    __table_args__ = (
        Index("ix_pipeline_events_corr_stage", "correlation_id", "stage"),
        Index("ix_pipeline_events_customer_at", "customer_id", "occurred_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    correlation_id = Column(String(64), nullable=False, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country_code = Column(String(64), nullable=True)
    stage = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    error_code = Column(String(64), nullable=True)
    payload = Column(JsonType, nullable=True)
    occurred_at = Column(DateTime, nullable=False, server_default=func.now())


class PipelineMetric(Base):
    """Aggregated / point metrics for dashboards and AI."""

    __tablename__ = "pipeline_metrics"
    __table_args__ = (
        Index("ix_pipeline_metrics_customer_name_at", "customer_id", "name", "recorded_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    correlation_id = Column(String(64), nullable=True, index=True)
    name = Column(String(128), nullable=False, index=True)
    value = Column(Float, nullable=False, default=0.0)
    unit = Column(String(32), nullable=True)
    tags = Column(JsonType, nullable=True)
    recorded_at = Column(DateTime, nullable=False, server_default=func.now())


class AlertHistory(Base):
    """Alert framework log — channels are stubs until integrations land."""

    __tablename__ = "alert_history"
    __table_args__ = (
        Index("ix_alert_history_customer_type", "customer_id", "alert_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    correlation_id = Column(String(64), nullable=True, index=True)
    alert_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(32), nullable=False, default="warning")
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    channel = Column(String(64), nullable=False, default="log")
    delivered = Column(Boolean, nullable=False, default=False)
    payload = Column(JsonType, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
