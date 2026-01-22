from sqlalchemy import Column, String, Integer, DateTime, Text, Numeric, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from ..database import Base

class SATSimpleMerged(Base):
    """
    Model for storing simple merged SAT documents.
    Unlike canonical merge which aggregates financial data,
    this stores the raw XML merge of multiple documents.
    """
    __tablename__ = "sat_simple_merged"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False)
    
    # Vendor information
    vendor_rfc = Column(String(13), nullable=False, index=True)
    vendor_name = Column(String(255), nullable=True)
    
    # Fiscal period
    fiscal_year = Column(Integer, nullable=False, index=True)
    fiscal_period = Column(Integer, nullable=False, index=True)  # 1-12 for months
    
    # Document information
    document_count = Column(Integer, nullable=False, default=0)
    document_types = Column(JSON, nullable=True)  # List of doc types included
    cfdi_uuids = Column(JSON, nullable=True)  # List of CFDI UUIDs included
    
    # Financial summary
    total_amount = Column(Numeric(15, 2), nullable=True)
    currency = Column(String(3), default='MXN')
    
    # Merged XML content
    merged_xml_content = Column(Text, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = relationship("ZodiacUser", back_populates="sat_simple_merged_documents")

    def __repr__(self):
        return f"<SATSimpleMerged(id={self.id}, vendor_rfc={self.vendor_rfc}, period={self.fiscal_year}-{self.fiscal_period})>"

