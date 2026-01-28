"""
Supplier Token Model
Stores API tokens for suppliers to submit CFDI documents without user authentication.
Each supplier gets a unique token tied to their RFC.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime

from ..database import Base


class SupplierToken(Base):
    __tablename__ = "supplier_tokens"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Supplier identification
    supplier_rfc = Column(String(13), unique=True, nullable=False, index=True)
    supplier_name = Column(String(255), nullable=True)
    
    # Token data
    token = Column(String(255), unique=True, nullable=False, index=True)  # Plain token for quick lookup
    token_hash = Column(String(255), nullable=False)  # Hashed token for validation
    
    # Status and lifecycle
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Audit and security
    created_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    ip_whitelist = Column(JSON, nullable=True)  # Array of allowed IPs
    notes = Column(Text, nullable=True)  # Admin notes
    
    # Indexes
    __table_args__ = (
        Index('idx_supplier_token_active', 'is_active', 'supplier_rfc'),
        Index('idx_supplier_token_expires', 'expires_at'),
    )

    def __repr__(self):
        return f"<SupplierToken(rfc={self.supplier_rfc}, active={self.is_active})>"
