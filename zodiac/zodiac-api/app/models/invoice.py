from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, UUID, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from ..database import Base

class ZodiacInvoiceSuccessEdi(Base):
    __tablename__ = "zodiac_invoice_success_edi"
    
    id = Column(Integer, primary_key=True, index=True)
    tracking_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    xml_path = Column(Text, nullable=True)
    xml_validation_pass = Column(Boolean, default=False)
    xml_convert_message = Column(Text, nullable=True)
    edi_path = Column(Text, nullable=True)
    edi_convert_pass = Column(Boolean, default=False)
    edi_convert_message = Column(Text, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # Store detailed error information
    processing_steps_error = Column(JSON, nullable=True)
    # Store blob paths for blob-stored files
    blob_xml_path = Column(Text, nullable=True)
    blob_edi_path = Column(Text, nullable=True)
    # Request type: 'web' or 'api'
    request_type = Column(String, default='web', nullable=False)
    
    # Relationships
    user = relationship("ZodiacUser", back_populates="successful_invoices")

class ZodiacInvoiceFailedEdi(Base):
    __tablename__ = "zodiac_invoice_failed_edi"
    
    id = Column(Integer, primary_key=True, index=True)
    tracking_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    xml_path = Column(Text, nullable=True)
    xml_validation_pass = Column(Boolean, default=False)
    xml_convert_message = Column(Text, nullable=True)
    edi_path = Column(Text, nullable=True)
    edi_convert_pass = Column(Boolean, default=False)
    edi_convert_message = Column(Text, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # Store detailed error information
    processing_steps_error = Column(JSON, nullable=True)
    # Store blob paths for blob-stored files
    blob_xml_path = Column(Text, nullable=True)
    blob_edi_path = Column(Text, nullable=True)
    # Request type: 'web' or 'api'
    request_type = Column(String, default='web', nullable=False)
    
    # Relationships
    user = relationship("ZodiacUser", back_populates="failed_invoices")