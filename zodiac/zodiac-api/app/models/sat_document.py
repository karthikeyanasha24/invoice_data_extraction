"""
SAT Document model for Mexican CFDI (Comprobante Fiscal Digital por Internet)
Supports INVOICE (I), PAYMENT (P), and CREDIT_NOTE (E) document types.
"""
from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

from ..database import Base


class SATDocument(Base):
    __tablename__ = "sat_documents"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # User and tracking
    user_id = Column(Integer, nullable=False)
    portal_ref_id = Column(String(100), unique=True, nullable=False)
    
    # CFDI Core fields
    cfdi_uuid = Column(String(36), unique=True, nullable=False)
    doc_type = Column(String(20), nullable=False)  # INVOICE, PAYMENT, CREDIT_NOTE
    
    # Supplier (Emisor)
    supplier_rfc = Column(String(13), nullable=False)
    supplier_name = Column(String(255))
    
    # Receiver (Receptor)
    receiver_rfc = Column(String(13), nullable=False)
    receiver_name = Column(String(255))
    
    # Document details
    serie = Column(String(25))
    folio = Column(String(40))
    fecha = Column(DateTime, nullable=False)
    
    # Financial
    subtotal = Column(String(50))
    total = Column(String(50))
    moneda = Column(String(3), default='MXN')
    tipo_cambio = Column(String(20))
    
    # Payment info
    forma_pago = Column(String(50))
    metodo_pago = Column(String(50))
    
    # Related documents
    related_cfdi_uuid = Column(String(36))
    
    # Status tracking
    status = Column(String(20), default='RECEIVED')
    validation_errors = Column(Text)
    
    # SAP integration
    sap_document_number = Column(String(50))
    sent_to_sap_at = Column(DateTime)
    sap_response = Column(Text)
    
    # Canonical merge tracking
    canonical_merged_id = Column(UUID(as_uuid=True))
    merged_at = Column(DateTime)
    
    # Metadata
    xml_content = Column(Text)
    xml_hash = Column(String(64))
    file_size = Column(Integer)
    
    # Fiscal period
    fiscal_year = Column(Integer)
    fiscal_period = Column(Integer)
    
    # Source tracking (must be explicitly set - no default)
    source = Column(String(20), nullable=False)  # 'admin' or 'supplier' - MUST be provided
    
    # Timestamps
    received_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SATDocument(id={self.id}, type={self.doc_type}, uuid={self.cfdi_uuid}, source={self.source})>"

