"""
SAT Supplier Account Mapping Model
Maps Mexican supplier RFC codes to SAP G/L vendor account numbers
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.sql import func
from ..database import Base


class SATSupplierAccountMapping(Base):
    """
    Maps supplier RFC codes to SAP G/L vendor account numbers.
    
    This mapping is essential for:
    1. Posting supplier invoices to correct vendor accounts in SAP
    2. Generating SAT Trial Balance with correct vendor accounts
    3. Ensuring proper vendor classification
    
    Example:
        RFC = "ABC123456789" → SAP G/L Account = "210100" (Proveedores Nacionales)
    """
    __tablename__ = "sat_supplier_account_mapping"

    # Primary Key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Supplier RFC (unique)
    supplier_rfc = Column(String(13), nullable=False, unique=True, index=True)
    
    # SAP G/L Account Number (vendor account)
    sap_gl_account = Column(String(20), nullable=False, index=True)
    
    # Account Description (from Excel CTAS column)
    account_description = Column(String(255), nullable=False)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Audit Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('ix_sat_supplier_mapping_active', 'is_active'),
        Index('ix_sat_supplier_mapping_account', 'sap_gl_account'),
    )

    def __repr__(self):
        return (f"<SATSupplierAccountMapping(rfc='{self.supplier_rfc}', "
                f"gl_account='{self.sap_gl_account}')>")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'supplier_rfc': self.supplier_rfc,
            'sap_gl_account': self.sap_gl_account,
            'account_description': self.account_description,
            'is_active': self.is_active,
            'is_default': self.is_default,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

