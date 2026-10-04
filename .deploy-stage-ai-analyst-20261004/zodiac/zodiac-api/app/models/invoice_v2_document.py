"""
Invoice V2 Document Model - Primary table for uploaded invoices before validation
"""
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..database import Base


class InvoiceV2Document(Base):
    """
    Stores all uploaded invoices (manual and SAP) before validation.
    This is the entry point for all V2 invoices.
    """
    __tablename__ = "v2_invoice_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    tracking_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False)
    
    # Source tracking
    source = Column(String(50), nullable=False, index=True)
    # Values: 'manual' or 'sap'
    
    # File storage
    filename = Column(String(500), nullable=False)
    xml_path = Column(Text, nullable=True)  # Local path
    blob_xml_path = Column(Text, nullable=True)  # Blob storage path
    
    # Status tracking
    validation_status = Column(String(50), default='not_validated', index=True)
    # Values: 'not_validated', 'processing', 'validated'
    
    # Timestamps
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("ZodiacUser")
    validated_invoice = relationship("InvoiceV2Validated", back_populates="document", uselist=False)
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_v2_user_source', 'user_id', 'source'),
        Index('idx_v2_validation_status', 'validation_status', 'deleted_at'),
    )
    
    def __repr__(self):
        return f"<InvoiceV2Document(id={self.id}, filename={self.filename}, source={self.source}, status={self.validation_status})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "tracking_id": str(self.tracking_id),
            "user_id": self.user_id,
            "source": self.source,
            "filename": self.filename,
            "xml_path": self.xml_path,
            "blob_xml_path": self.blob_xml_path,
            "validation_status": self.validation_status,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
