from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, func
from ..database import Base


class ConvertedInvoice(Base):
    """Model for storing converted invoice files"""
    __tablename__ = "converted_invoices"

    id = Column(Integer, primary_key=True, index=True)
    # Note: Foreign key constraint exists at database level (see migration)
    # We don't define it here to avoid SQLAlchemy metadata resolution issues
    validated_invoice_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(String(255), nullable=True, index=True)  # For reference only
    target_format = Column(String(32), nullable=False)  # X12, EDIFACT, PDF, etc.
    converted_file_path = Column(String(1024), nullable=True)  # Local file path
    blob_converted_path = Column(String(1024), nullable=True)  # Blob storage URL
    conversion_status = Column(String(32), nullable=False, default="pending")  # success, failed, pending
    conversion_notes = Column(Text, nullable=True)  # Any warnings/info
    validation_overridden = Column(Boolean, default=False)  # Whether admin overrode validation mismatch
    converted_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<ConvertedInvoice(id={self.id}, validated_invoice_id={self.validated_invoice_id}, format='{self.target_format}', status='{self.conversion_status}')>"
