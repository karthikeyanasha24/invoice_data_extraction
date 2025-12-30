"""
SAT Supplier to SAP G/L Account Mapping
Maps supplier RFC (Vendor) to SAP G/L Account number for canonical merged documents.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Index
from datetime import datetime

from ..database import Base


class SATSupplierAccountMapping(Base):
    __tablename__ = "sat_supplier_account_mapping"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Mapping fields
    supplier_rfc = Column(String(13), unique=True, nullable=False, index=True)
    sap_gl_account = Column(String(20), nullable=False, index=True)
    account_description = Column(String(255))
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_default = Column(Boolean, default=False, nullable=False)  # Default mapping for unmapped RFCs
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index('idx_supplier_mapping_active', 'is_active', 'supplier_rfc'),
    )

    def __repr__(self):
        return f"<SATSupplierAccountMapping(rfc={self.supplier_rfc}, gl={self.sap_gl_account}, active={self.is_active})>"

