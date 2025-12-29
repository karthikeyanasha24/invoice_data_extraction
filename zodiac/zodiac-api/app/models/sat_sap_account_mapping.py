"""
SAT-SAP Account Mapping Model
Maps Mexican SAT ClaveProdServ codes to SAP G/L Account numbers
Required for SAT Trial Balance generation
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.sql import func
from ..database import Base


class SATSAPAccountMapping(Base):
    """
    Maps SAT product/service codes (ClaveProdServ) to SAP G/L account numbers.
    
    This mapping is essential for:
    1. Converting SAT CFDI line items to SAP posting entries
    2. Generating SAT Trial Balance reports with correct account numbers
    3. Ensuring proper account classification in SAP
    
    Example:
        ClaveProdServ = "43211503" (Mobile phones) → SAP G/L Account = "400100"
    """
    __tablename__ = "sat_sap_account_mapping"

    # Primary Key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # SAT Product/Service Code (unique)
    clave_prod_serv = Column(String(10), nullable=False, unique=True, index=True)
    
    # SAP G/L Account Number
    sap_gl_account = Column(String(20), nullable=False, index=True)
    
    # SAT Code Group (01, 02, 99, etc.)
    code_group = Column(String(5), nullable=False, index=True)
    
    # Description (in Spanish/English)
    description = Column(String(255), nullable=True)
    description_en = Column(String(255), nullable=True)
    
    # Account Type Classification
    account_type = Column(String(50), nullable=True)  # Asset, Liability, Revenue, Expense, etc.
    
    # Additional Metadata
    sat_category = Column(String(100), nullable=True)  # SAT category name
    notes = Column(Text, nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)  # Mark default/fallback mappings
    
    # Audit Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('ix_sat_sap_mapping_active', 'is_active'),
        Index('ix_sat_sap_mapping_account_type', 'account_type'),
    )

    def __repr__(self):
        return (f"<SATSAPAccountMapping(clave='{self.clave_prod_serv}', "
                f"gl_account='{self.sap_gl_account}', group='{self.code_group}')>")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'clave_prod_serv': self.clave_prod_serv,
            'sap_gl_account': self.sap_gl_account,
            'code_group': self.code_group,
            'description': self.description,
            'description_en': self.description_en,
            'account_type': self.account_type,
            'sat_category': self.sat_category,
            'notes': self.notes,
            'is_active': self.is_active,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

