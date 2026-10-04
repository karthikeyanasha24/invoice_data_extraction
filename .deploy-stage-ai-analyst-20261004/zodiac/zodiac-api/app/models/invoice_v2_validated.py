"""
Invoice V2 Validated Model - Stores validation results with extracted fields
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from ..database import Base


class InvoiceV2Validated(Base):
    """
    Stores validation results for processed invoices.
    Contains extracted invoice data and validation status.
    """
    __tablename__ = "v2_validated_invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("v2_invoice_documents.id"), unique=True, nullable=False, index=True)
    
    # Validation result
    status = Column(String(50), nullable=False, index=True)
    # Values: 'success' or 'failed'
    
    # Extracted invoice fields (JSONB for flexibility and performance)
    invoice_data = Column(JSONB, nullable=False)
    # Structure: {
    #   "invoice_number": "...",
    #   "issue_date": "...",
    #   "due_date": "...",
    #   "currency": "...",
    #   "customer_id": "...",
    #   "customer_name": "...",
    #   "customer_tax_id": "...",
    #   "supplier_id": "...",
    #   "supplier_name": "...",
    #   "supplier_tax_id": "...",
    #   "tax_amount": "...",
    #   "subtotal": "...",
    #   "total": "...",
    #   "line_items": [...]
    # }
    
    # Missing fields (for failed status)
    missing_fields = Column(JSONB, nullable=True)
    # Array of field names: ["supplier_id", "customer_id"]
    
    # Validation details
    validation_errors = Column(JSONB, nullable=True)
    # Array of error objects: [{"field": "...", "message": "..."}]
    
    validation_notes = Column(Text, nullable=True)
    # Additional notes about the validation
    
    # Correction tracking
    correction_applied = Column(Boolean, default=False)
    correction_cache_id = Column(UUID(as_uuid=True), ForeignKey("v2_correction_cache.id"), nullable=True)
    
    # Timestamps
    validated_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    
    # Relationships
    document = relationship("InvoiceV2Document", back_populates="validated_invoice")
    correction_used = relationship("InvoiceV2CorrectionCache")
    
    def __repr__(self):
        return f"<InvoiceV2Validated(id={self.id}, document_id={self.document_id}, status={self.status})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "status": self.status,
            "invoice_data": self.invoice_data,
            "missing_fields": self.missing_fields,
            "validation_errors": self.validation_errors,
            "validation_notes": self.validation_notes,
            "correction_applied": self.correction_applied,
            "correction_cache_id": str(self.correction_cache_id) if self.correction_cache_id else None,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
