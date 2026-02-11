"""
Invoice V2 Correction Cache Model - Stores corrections for automatic reuse
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Index, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from ..database import Base


class InvoiceV2CorrectionCache(Base):
    """
    Stores customer-specific corrections for automatic reuse.
    When a field is corrected (manually or via AI), we save it here
    to automatically fix similar errors for the same customer.
    """
    __tablename__ = "v2_correction_cache"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Customer identification
    customer_id = Column(String(255), nullable=False, index=True)
    customer_name = Column(String(500), nullable=True)
    
    # Missing field correction
    field_name = Column(String(100), nullable=False, index=True)
    # e.g., "supplier_id", "customer_id", "due_date"
    
    field_value = Column(Text, nullable=False)
    # The correction value to apply
    
    # Context for matching
    error_signature = Column(String(500), nullable=False, index=True)
    # Pattern to match similar errors (e.g., hash of customer_id + field_name)
    
    # Success tracking
    success_count = Column(Integer, default=1, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    
    # Metadata
    created_by_user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Indexes for fast lookup
    __table_args__ = (
        Index('idx_v2_customer_field', 'customer_id', 'field_name'),
        Index('idx_v2_error_signature', 'error_signature'),
        Index('idx_v2_active_corrections', 'is_active', 'customer_id'),
    )
    
    def __repr__(self):
        return f"<InvoiceV2CorrectionCache(id={self.id}, customer={self.customer_id}, field={self.field_name}, success={self.success_count})>"
    
    def get_success_rate(self) -> float:
        """Calculate success rate percentage"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return (self.success_count / total) * 100
    
    def mark_success(self):
        """Mark this correction as successfully applied"""
        self.success_count += 1
        self.last_used_at = datetime.utcnow()
        self.last_success_at = datetime.utcnow()
    
    def mark_failure(self):
        """Mark this correction as failed when applied"""
        self.failure_count += 1
        self.last_used_at = datetime.utcnow()
        self.last_failure_at = datetime.utcnow()
        
        # Auto-disable if failure rate is too high
        if self.get_success_rate() < 30 and (self.success_count + self.failure_count) >= 5:
            self.is_active = False
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": str(self.id),
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "field_name": self.field_name,
            "field_value": self.field_value,
            "error_signature": self.error_signature,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.get_success_rate(),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }
