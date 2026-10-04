"""
Invoice V2 Business Data Model
Stores extracted business intelligence from validated invoices
"""
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Numeric, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class InvoiceV2BusinessData(Base):
    """
    Business intelligence data extracted from Invoice V2 validated invoices.
    Used for dashboard analytics, reporting, and insights.
    """
    __tablename__ = "invoice_v2_business_data"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign Keys
    validated_invoice_id = Column(Integer, index=True)  # No FK to avoid ORM issues
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False, index=True)
    
    # Customer Information
    customer_id = Column(String(100), index=True)
    customer_name = Column(String(255), index=True)
    customer_country = Column(String(100), index=True)
    
    # Supplier Information
    supplier_id = Column(String(100), index=True)
    supplier_name = Column(String(255), index=True)
    
    # Products (JSONB for flexible product data)
    products = Column(JSON, nullable=True)  # [{name, quantity, price, revenue, unit_code, ids, ...}]
    total_products_count = Column(Integer, default=0)
    
    # Financial Data
    total_amount = Column(Numeric(15, 2))
    tax_amount = Column(Numeric(15, 2))
    currency = Column(String(10))
    
    # Industry Classification
    industry = Column(String(100), index=True)  # Auto-inferred from products/customer
    industry_confidence = Column(Float)  # 0.0 to 1.0 confidence score
    industry_keywords_matched = Column(JSON)  # Keywords that triggered classification
    
    # Temporal Fields (for time-series analysis)
    invoice_date = Column(Date, index=True)
    fiscal_quarter = Column(String(10), index=True)  # Q1, Q2, Q3, Q4
    fiscal_year = Column(Integer, index=True)
    season = Column(String(20))  # Spring, Summer, Fall, Winter
    
    # Lifecycle Tracking (for E2E funnel)
    current_stage = Column(String(50), index=True)  # VALIDATED, CONVERTED, SENT, etc.
    stage_status = Column(String(20))  # SUCCESS, FAILED, PENDING
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("ZodiacUser", foreign_keys=[user_id])
    
    def __repr__(self):
        return f"<InvoiceV2BusinessData(id={self.id}, customer={self.customer_name}, industry={self.industry}, date={self.invoice_date})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "validated_invoice_id": self.validated_invoice_id,
            "user_id": self.user_id,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "customer_country": self.customer_country,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "products": self.products,
            "total_products_count": self.total_products_count,
            "total_amount": float(self.total_amount) if self.total_amount else None,
            "tax_amount": float(self.tax_amount) if self.tax_amount else None,
            "currency": self.currency,
            "industry": self.industry,
            "industry_confidence": self.industry_confidence,
            "industry_keywords_matched": self.industry_keywords_matched,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "fiscal_quarter": self.fiscal_quarter,
            "fiscal_year": self.fiscal_year,
            "season": self.season,
            "current_stage": self.current_stage,
            "stage_status": self.stage_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
