"""
SAT Canonical Merged Document
Aggregates multiple SAT documents (INVOICE, PAYMENT, CREDIT_NOTE) into a single canonical format
for a given vendor, fiscal year, and fiscal period.
"""
from sqlalchemy import Column, String, Integer, DateTime, Text, Numeric, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from datetime import datetime
import uuid

from ..database import Base


class SATCanonicalMerged(Base):
    __tablename__ = "sat_canonical_merged"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # User and company
    user_id = Column(Integer, nullable=False, index=True)
    company_code = Column(String(10), nullable=False, default='MX01')
    
    # Grouping criteria (vendor + period)
    vendor_rfc = Column(String(13), nullable=False, index=True)
    vendor_name = Column(String(255))
    fiscal_year = Column(Integer, nullable=False, index=True)
    fiscal_period = Column(Integer, nullable=False, index=True)  # Month (1-12)
    
    # Aggregated amounts (signed)
    total_invoices = Column(Numeric(15, 2), default=0)  # Sum of INVOICE amounts (+)
    total_credits = Column(Numeric(15, 2), default=0)   # Sum of CREDIT_NOTE amounts (+, applied as -)
    total_payments = Column(Numeric(15, 2), default=0)  # Sum of PAYMENT amounts (+, applied as -)
    net_amount = Column(Numeric(15, 2), default=0)      # total_invoices - total_credits - total_payments
    
    # Currency
    currency = Column(String(3), default='MXN')
    
    # Payment method
    payment_method = Column(String(50))
    
    # Document references
    cfdi_uuids = Column(ARRAY(String), default=[])  # All UUIDs involved
    related_cfdi_uuids = Column(ARRAY(String), default=[])  # Related document UUIDs
    linked_document_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])  # SATDocument IDs
    
    # SAP G/L Account mapping
    sap_gl_account = Column(String(20), nullable=True, index=True)
    
    # Status tracking
    status = Column(String(20), default='MERGED', index=True)
    # MERGED -> SAP_SENT -> SAP_CONFIRMED
    
    # SAP integration
    sap_document_number = Column(String(50))
    sent_to_sap_at = Column(DateTime)
    sap_response = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_canonical_vendor_period', 'vendor_rfc', 'fiscal_year', 'fiscal_period'),
        Index('idx_canonical_user_status', 'user_id', 'status'),
        Index('idx_canonical_sap_gl', 'sap_gl_account'),
    )

    def __repr__(self):
        return f"<SATCanonicalMerged(id={self.id}, vendor={self.vendor_rfc}, period={self.fiscal_year}-{self.fiscal_period}, net={self.net_amount})>"

