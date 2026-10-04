"""
Customer Token Model
Stores API tokens for customers (e.g. to submit delivery SFTP key without using supplier token).
One token per customer_id; used with X-Customer-Token header for delivery-settings API.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, ForeignKey, Index
from datetime import datetime

from ..database import Base


class CustomerToken(Base):
    __tablename__ = "customer_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(255), unique=True, nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    token_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_customer_token_active", "is_active", "customer_id"),
        Index("idx_customer_token_expires", "expires_at"),
    )

    def __repr__(self):
        return f"<CustomerToken(customer_id={self.customer_id!r}, active={self.is_active})>"
