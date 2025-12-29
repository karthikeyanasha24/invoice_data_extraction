"""
SAT Canonical Merged Document Model
Stores the MERGED canonical format combining INVOICE + PAYMENT + CREDIT_NOTE
This is what gets sent to SAP
"""
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..database import Base


class SATCanonicalMerged(Base):
    """
    Canonical Merged Document - combines multiple SAT documents into ONE payload for SAP
    
    Following client's canonical table structure:
    - MANDT, EXTERNAL_DOC_ID, CFDI_UUID, DOC_TYPE, DOC_NUMBER, DOC_DATE, POSTING_DATE
    - CURRENCY, EXCHANGE_RATE, VENDOR_RFC, VENDOR_NAME, AMOUNT, AMOUNT_SIGNED
    - TAX_BASE, TAX_AMOUNT, RELATED_CFDI_UUID, PAYMENT_DATE, PAYMENT_METHOD
    - STATUS, RECEIVED_TS
    """
    __tablename__ = "sat_canonical_merged"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # User reference
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False)

    # Grouping Keys (what defines this merge)
    company_code = Column(String(10), nullable=False, index=True)  # MANDT equivalent
    fiscal_year = Column(Integer, nullable=False, index=True)
    fiscal_period = Column(Integer, nullable=False, index=True)  # 1-12 (month)
    vendor_rfc = Column(String(20), nullable=False, index=True)
    vendor_name = Column(String(255), nullable=True)

    # Canonical Fields (as specified by client)
    external_doc_id = Column(String(50), nullable=True)  # EXTERNAL_DOC_ID
    
    # Aggregated CFDIs (JSON array of all UUIDs included)
    cfdi_uuids = Column(JSONB, nullable=True)  # List of all CFDI_UUIDs merged
    
    # Document Type (merged type indicator)
    doc_type = Column(String(10), nullable=False, default='MERGED')  # I/E/P or MERGED
    
    # Document Dates
    doc_date = Column(DateTime, nullable=True)  # DOC_DATE (earliest document date)
    posting_date = Column(DateTime, nullable=True)  # POSTING_DATE
    
    # Financial Data
    currency = Column(String(3), nullable=False, default='MXN')  # CURRENCY
    exchange_rate = Column(Numeric(10, 6), nullable=True, default=1.0)  # EXCHANGE_RATE
    
    # Aggregated Amounts
    total_invoices = Column(Numeric(15, 2), nullable=False, default=0)  # Sum of invoices
    total_credits = Column(Numeric(15, 2), nullable=False, default=0)   # Sum of credits
    total_payments = Column(Numeric(15, 2), nullable=False, default=0)  # Sum of payments
    net_amount = Column(Numeric(15, 2), nullable=False, default=0)      # AMOUNT (net)
    amount_signed = Column(Numeric(15, 2), nullable=False, default=0)   # AMOUNT_SIGNED
    
    # Tax Information
    tax_base = Column(Numeric(15, 2), nullable=True)    # TAX_BASE (subtotal)
    tax_amount = Column(Numeric(15, 2), nullable=True)  # TAX_AMOUNT (IVA)
    
    # Related Documents
    related_cfdi_uuids = Column(JSONB, nullable=True)  # RELATED_CFDI_UUID (payment refs)
    linked_document_ids = Column(JSONB, nullable=True)  # List of sat_document IDs
    
    # Payment Information
    payment_date = Column(DateTime, nullable=True)      # PAYMENT_DATE
    payment_method = Column(String(50), nullable=True)  # PAYMENT_METHOD (03, 99, etc.)
    
    # Status & Metadata
    status = Column(String(50), nullable=False, default='DRAFT')  # DRAFT, READY, SENT, CONFIRMED, FAILED
    received_ts = Column(DateTime(timezone=True), server_default=func.now())  # RECEIVED_TS
    
    # SAP Integration
    sap_gl_account = Column(String(20), nullable=True, index=True)  # Mapped GL Account from supplier mapping
    sap_document_number = Column(String(50), nullable=True)
    sap_fiscal_year = Column(Integer, nullable=True)
    sap_response = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Line Items (detailed breakdown)
    line_items = Column(JSONB, nullable=True)  # Detailed CONCEPTOS from all documents
    
    # Audit Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    merged_at = Column(DateTime(timezone=True), nullable=True)
    sent_to_sap_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("ZodiacUser", foreign_keys=[user_id])

    # Indexes
    __table_args__ = (
        Index('ix_sat_canonical_vendor_period', 'vendor_rfc', 'fiscal_year', 'fiscal_period'),
        Index('ix_sat_canonical_company', 'company_code'),
        Index('ix_sat_canonical_status', 'status'),
    )

    def __repr__(self):
        return (f"<SATCanonicalMerged(vendor_rfc='{self.vendor_rfc}', "
                f"period={self.fiscal_year}-{self.fiscal_period:02d}, "
                f"net_amount={self.net_amount}, status='{self.status}')>")

