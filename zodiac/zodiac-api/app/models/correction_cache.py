"""
Correction Cache Model - Stores successful AI corrections for reuse

This model stores corrections that were successfully applied by AI to invoices,
allowing the system to reuse these corrections for similar errors without calling AI again.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, Index, Boolean
from sqlalchemy.dialects.postgresql import UUID
from ..database import Base


class CorrectionCache(Base):
    """
    Stores successful corrections for automatic reuse.
    
    When AI successfully corrects an XML/EDI error, we store:
    - The customer identifier
    - The type of error
    - The transformation applied
    - Success metrics
    
    This allows us to automatically fix similar errors without calling AI.
    """
    __tablename__ = "correction_cache"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Customer identification
    customer_id = Column(String(255), nullable=False, index=True)
    customer_name = Column(String(500), nullable=True)
    
    # Error identification
    error_type = Column(String(100), nullable=False, index=True)
    # Examples: "missing_sender_id", "invalid_date", "missing_receiver_id", etc.
    
    error_signature = Column(String(500), nullable=False)
    # A pattern or hash representing the specific error structure
    # e.g., "missing_element:/Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
    
    # Correction details
    correction_type = Column(String(50), nullable=False, index=True)
    # Values: "XML", "EDI", "XML_STRUCTURE", "EDI_FORMAT"
    
    transformation_rule = Column(JSON, nullable=False)
    # Stores the transformation logic as JSON
    # Examples:
    # - For XML: {"action": "add_element", "xpath": "/Invoice/...", "value": "..."}
    # - For EDI: {"action": "pad_field", "segment": "ISA", "field": 6, "length": 15}
    # - Can store multiple transformations as an array
    
    original_content_snippet = Column(Text, nullable=True)
    # Store a snippet of the original problematic content (first 1000 chars)
    
    corrected_content_snippet = Column(Text, nullable=True)
    # Store a snippet of the corrected content (first 1000 chars)
    
    # AI correction details (if this was originally from AI)
    ai_model_used = Column(String(100), nullable=True)
    # e.g., "gpt-4o-mini", "gpt-4"
    
    ai_prompt_hash = Column(String(100), nullable=True)
    # Hash of the AI prompt used, to track different correction strategies
    
    # Success tracking
    success_count = Column(Integer, default=0, nullable=False)
    # Number of times this correction was successfully applied
    
    failure_count = Column(Integer, default=0, nullable=False)
    # Number of times this correction failed when applied
    
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    # Can be disabled if correction stops working
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    
    # Metadata
    created_by_user_id = Column(Integer, nullable=True)
    # User who uploaded the invoice that led to this correction
    
    notes = Column(Text, nullable=True)
    # Optional notes about this correction
    
    # Indexes for fast lookup
    __table_args__ = (
        Index('idx_customer_error', 'customer_id', 'error_type'),
        Index('idx_error_signature', 'error_signature'),
        Index('idx_correction_type_active', 'correction_type', 'is_active'),
        Index('idx_success_rate', 'success_count', 'failure_count'),
    )
    
    def __repr__(self):
        return f"<CorrectionCache(id={self.id}, customer={self.customer_id}, error={self.error_type}, success={self.success_count})>"
    
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
            "error_type": self.error_type,
            "error_signature": self.error_signature,
            "correction_type": self.correction_type,
            "transformation_rule": self.transformation_rule,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.get_success_rate(),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "ai_model_used": self.ai_model_used,
        }

