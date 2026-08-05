"""
Workspace models — additive tables for Customer Workspace (Phase 2).

workspace_id == customer_id by design (seeded from zodiac_customers).
Does not alter existing customer / invoice / SAT tables.

Supports:
- N customers (one settings row each)
- N ERP connections per customer (keyed by connection_key)
- N country adapters per customer (keyed by country_code)
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    JSON,
)

from ..database import Base

JsonType = JSON


class WorkspaceSettings(Base):
    """Per-customer workspace feature flags and display settings (1:1 with customer)."""

    __tablename__ = "workspace_settings"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    display_name = Column(String(255), nullable=True)
    pipeline_enabled = Column(Boolean, nullable=False, default=False)
    ai_scoped = Column(Boolean, nullable=False, default=True)
    monitoring_enabled = Column(Boolean, nullable=False, default=True)
    flags = Column(JsonType, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())
    created_by = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<WorkspaceSettings(customer_id={self.customer_id!r})>"


class WorkspaceErpConnection(Base):
    """
    ERP connection config for a workspace.
    Multiple connections per customer via connection_key (e.g. primary, billing, legacy).
    Secrets stored as refs only — never plaintext values.
    """

    __tablename__ = "workspace_erp_connections"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "connection_key", name="uq_workspace_erp_customer_key"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_key = Column(String(64), nullable=False, default="primary", index=True)
    label = Column(String(255), nullable=True)
    base_url = Column(String(1024), nullable=True)
    callback_url = Column(String(1024), nullable=True)
    auth_type = Column(String(64), nullable=False, default="none")
    client_id_ref = Column(String(512), nullable=True)
    client_secret_ref = Column(String(512), nullable=True)
    extra_config = Column(JsonType, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    def __repr__(self):
        return (
            f"<WorkspaceErpConnection(customer_id={self.customer_id!r}, "
            f"connection_key={self.connection_key!r})>"
        )


class WorkspaceAdapterConfig(Base):
    """
    Enabled country adapters and government endpoint refs for a workspace.
    Multiple adapters per customer via country_code (mx_cfdi, india, …).
    """

    __tablename__ = "workspace_adapter_config"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "country_code", name="uq_workspace_adapter_country"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country_code = Column(String(32), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    endpoint_url_ref = Column(String(512), nullable=True)
    auth_type = Column(String(64), nullable=True)  # api_key|oauth2|mtls|…
    auth_secret_ref = Column(String(512), nullable=True)  # vault/env ref only
    document_types = Column(JsonType, nullable=True)
    rules_version = Column(String(64), nullable=True)
    mapping_ref = Column(String(512), nullable=True)
    extra_config = Column(JsonType, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    def __repr__(self):
        return (
            f"<WorkspaceAdapterConfig(customer_id={self.customer_id!r}, "
            f"country_code={self.country_code!r})>"
        )
