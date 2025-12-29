"""
SAT Document Model for Mexican Tax Documents (CFDI)
Supports: INVOICE, PAYMENT, CREDIT_NOTE
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Enum as SQLEnum, JSON, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from ..database import Base
import enum


class DocumentType(enum.Enum):
    """SAT Document Types"""
    INVOICE = "INVOICE"
    PAYMENT = "PAYMENT"
    CREDIT_NOTE = "CREDIT_NOTE"


class ProcessingStatus(enum.Enum):
    """Document Processing Status"""
    RECEIVED = "RECEIVED"                 # Just received from supplier
    VALIDATING = "VALIDATING"             # Schema validation in progress
    VALIDATED = "VALIDATED"               # Passed validation
    NORMALIZING = "NORMALIZING"           # Canonical normalization in progress
    NORMALIZED = "NORMALIZED"             # Normalized successfully
    ENRICHING = "ENRICHING"               # Adding metadata
    ENRICHED = "ENRICHED"                 # Metadata added
    READY_FOR_SAP = "READY_FOR_SAP"      # Ready to send to SAP
    SENDING_TO_SAP = "SENDING_TO_SAP"    # Sending to SAP API
    SENT_TO_SAP = "SENT_TO_SAP"          # Successfully sent to SAP
    SAP_CONFIRMED = "SAP_CONFIRMED"       # SAP confirmed receipt
    COMPLETED = "COMPLETED"               # Fully processed
    FAILED = "FAILED"                     # Processing failed
    DUPLICATE = "DUPLICATE"               # Duplicate document detected


class SATDocument(Base):
    """
    Main table for SAT documents (CFDI)
    Stores Mexican tax documents: Invoices, Payments, Credit Notes
    """
    __tablename__ = "sat_documents"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Portal Tracking
    portal_reference_id = Column(String(50), unique=True, nullable=False, index=True)  # PRT-2025-000123
    
    # Document Identification
    document_type = Column(SQLEnum(DocumentType), nullable=False, index=True)
    cfdi_uuid = Column(String(50), unique=True, nullable=False, index=True)  # SAT UUID (folio fiscal) - allows TEMP- prefix
    
    # Supplier & Company Information
    supplier_id = Column(String(100), nullable=False, index=True)  # SUPP001
    supplier_name = Column(String(500), nullable=True)
    supplier_rfc = Column(String(13), nullable=True, index=True)  # Mexican RFC (tax ID)
    company_code = Column(String(10), nullable=False, index=True)  # MX01
    
    # User Association
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False, index=True)
    
    # XML Content
    original_xml = Column(Text, nullable=False)  # Original XML from supplier
    canonical_xml = Column(Text, nullable=True)  # Normalized XML
    original_xml_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hash
    
    # CFDI Specific Fields (extracted from XML)
    cfdi_version = Column(String(10), nullable=True)  # 3.3 or 4.0
    serie = Column(String(25), nullable=True)  # Serie
    folio = Column(String(40), nullable=True)  # Folio
    fecha = Column(DateTime, nullable=True, index=True)  # Fecha (date)
    subtotal = Column(String(50), nullable=True)  # SubTotal
    total = Column(String(50), nullable=True)  # Total
    moneda = Column(String(10), nullable=True)  # Moneda (currency)
    tipo_de_comprobante = Column(String(1), nullable=True)  # I, E, T, N, P
    
    # Customer Information (from CFDI)
    customer_rfc = Column(String(13), nullable=True)  # Receptor RFC
    customer_name = Column(String(500), nullable=True)  # Receptor Nombre
    
    # Metadata
    processing_timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    schema_version = Column(String(10), default="1.0", nullable=False)
    
    # Processing Status
    status = Column(SQLEnum(ProcessingStatus), default=ProcessingStatus.RECEIVED, nullable=False, index=True)
    
    # Validation
    validation_report = Column(JSON, nullable=True)  # {"schemaValid": true, "duplicateCheckPassed": true, ...}
    is_schema_valid = Column(Boolean, default=None, nullable=True)
    is_duplicate = Column(Boolean, default=False, nullable=False, index=True)
    
    # SAP Integration
    sap_document_number = Column(String(50), nullable=True, index=True)  # SAP posting document number
    sap_fiscal_year = Column(String(4), nullable=True)
    sap_posting_date = Column(DateTime, nullable=True)
    sap_response = Column(JSON, nullable=True)  # Full SAP response
    sap_sent_at = Column(DateTime, nullable=True)
    sap_confirmed_at = Column(DateTime, nullable=True)
    
    # Error Handling
    error_message = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Audit Trail
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # File Storage (if saving to disk)
    original_file_path = Column(String(500), nullable=True)
    canonical_file_path = Column(String(500), nullable=True)
    
    __table_args__ = (
        Index('idx_sat_document_type_status', 'document_type', 'status'),
        Index('idx_sat_supplier_company', 'supplier_id', 'company_code'),
        Index('idx_sat_user_status', 'user_id', 'status'),
        Index('idx_sat_user_created', 'user_id', 'created_at'),
        Index('idx_sat_cfdi_uuid_unique', 'cfdi_uuid'),
        Index('idx_sat_portal_ref', 'portal_reference_id'),
    )


class SATProcessingLog(Base):
    """
    Audit log for SAT document processing
    Tracks every step in the pipeline
    """
    __tablename__ = "sat_processing_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sat_document_id = Column(UUID(as_uuid=True), ForeignKey("sat_documents.id"), nullable=False, index=True)
    
    # Processing Step
    step_name = Column(String(100), nullable=False)  # "XML Validation", "Deduplication", etc.
    step_status = Column(String(20), nullable=False)  # "SUCCESS", "FAILED", "SKIPPED"
    
    # Status Transition
    previous_status = Column(SQLEnum(ProcessingStatus), nullable=True)
    new_status = Column(SQLEnum(ProcessingStatus), nullable=True)
    
    # Step Details
    message = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    error_details = Column(JSON, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_sat_log_document', 'sat_document_id', 'created_at'),
    )


class SATDuplicateCheck(Base):
    """
    Fast duplicate check cache using CFDI UUID
    Prevents reprocessing of already-received documents
    """
    __tablename__ = "sat_duplicate_checks"
    
    cfdi_uuid = Column(String(50), primary_key=True, index=True)
    sat_document_id = Column(UUID(as_uuid=True), ForeignKey("sat_documents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False, index=True)
    supplier_id = Column(String(100), nullable=False, index=True)
    document_type = Column(SQLEnum(DocumentType), nullable=False)
    first_received_at = Column(DateTime, default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_sat_dup_uuid', 'cfdi_uuid'),
        Index('idx_sat_dup_user', 'user_id', 'cfdi_uuid'),
    )


class SATCompanyMapping(Base):
    """
    Company code mappings for SAP integration
    Maps supplier IDs to company codes
    """
    __tablename__ = "sat_company_mappings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False, index=True)
    
    supplier_id = Column(String(100), nullable=False, index=True)
    company_code = Column(String(10), nullable=False)
    
    # Mapping details
    supplier_name = Column(String(500), nullable=True)
    supplier_rfc = Column(String(13), nullable=True)
    
    # Configuration
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Audit
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_sat_mapping_user_supplier', 'user_id', 'supplier_id'),
    )

