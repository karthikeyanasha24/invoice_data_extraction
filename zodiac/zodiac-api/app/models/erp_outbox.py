"""
ERP push outbox model (Phase 6) — expand-only.

Lives under app.models so database.init_models() can register it without
importing app.core.erp (avoids circular imports).
"""
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from ..database import Base


class ErpPushOutbox(Base):
    """One row per idempotency_key for confirmation → ERP pushes."""

    __tablename__ = "erp_push_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_erp_push_outbox_idempotency_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(128), nullable=False, unique=True, index=True)
    customer_id = Column(
        String(255),
        ForeignKey("zodiac_customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    correlation_id = Column(String(64), nullable=False, index=True)
    connection_key = Column(String(64), nullable=False, default="primary")
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    request_hash = Column(String(128), nullable=True)
    response_body = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())
