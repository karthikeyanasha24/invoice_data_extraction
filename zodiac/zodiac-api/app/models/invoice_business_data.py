"""
Invoice Business Intelligence Data Model

Stores extracted business intelligence from invoices for analytics:
- Customer information
- Supplier information
- Product details
- Industry classification
- Lifecycle stage tracking
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, DECIMAL, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from ..database import Base


class InvoiceBusinessData(Base):
    """
    Business intelligence data extracted from invoices.
    
    This table stores structured business data for analytics and reporting:
    - Customer/Supplier information
    - Product details and industry classification
    - E2E lifecycle stage tracking
    - Geographic and financial data
    """
    __tablename__ = "invoice_business_data"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Link to invoice (can be success or failed)
    success_invoice_id = Column(Integer, ForeignKey("zodiac_invoice_success_edi.id"), nullable=True, index=True)
    failed_invoice_id = Column(Integer, ForeignKey("zodiac_invoice_failed_edi.id"), nullable=True, index=True)
    tracking_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("zodiac_users.id"), nullable=False, index=True)
    
    # ============================================================
    # CUSTOMER DATA
    # ============================================================
    customer_id = Column(String(255), nullable=True, index=True)
    customer_name = Column(String(500), nullable=True, index=True)
    customer_country = Column(String(10), nullable=True, index=True)  # ISO country code
    customer_city = Column(String(255), nullable=True)
    customer_address = Column(Text, nullable=True)
    customer_tax_id = Column(String(100), nullable=True)
    
    # ============================================================
    # SUPPLIER DATA
    # ============================================================
    supplier_id = Column(String(255), nullable=True, index=True)
    supplier_name = Column(String(500), nullable=True)
    supplier_country = Column(String(10), nullable=True)
    
    # ============================================================
    # PRODUCT DATA
    # ============================================================
    products = Column(JSONB, nullable=True)
    # Structure: [
    #   {
    #     "name": "Product Name",
    #     "description": "Product Description",
    #     "quantity": 10,
    #     "unit_price": 100.00,
    #     "line_total": 1000.00,
    #     "currency": "USD"
    #   }
    # ]
    
    product_count = Column(Integer, default=0)  # Total number of line items
    
    # ============================================================
    # INDUSTRY CLASSIFICATION
    # ============================================================
    industry = Column(String(100), nullable=True, index=True)
    # Examples: Technology, Healthcare, Retail, Manufacturing, etc.
    
    industry_confidence = Column(String(20), default='medium')
    # Values: high, medium, low (based on keyword matching strength)
    
    industry_keywords_matched = Column(JSONB, nullable=True)
    # Store which keywords led to industry classification
    
    # ============================================================
    # FINANCIAL DATA
    # ============================================================
    invoice_number = Column(String(100), nullable=True, index=True)
    invoice_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    
    total_amount = Column(DECIMAL(15, 2), nullable=True)
    tax_amount = Column(DECIMAL(15, 2), nullable=True)
    currency = Column(String(10), default='USD')
    
    # ============================================================
    # E2E LIFECYCLE TRACKING
    # ============================================================
    current_stage = Column(String(50), nullable=False, index=True)
    # Values: RECEIVED, VALIDATED, CONVERTED, SENT, ACKNOWLEDGED, DELIVERED, CONFIRMED
    
    stage_status = Column(String(20), nullable=False, index=True)
    # Values: SUCCESS, FAILED, PENDING
    
    failed_at_stage = Column(String(50), nullable=True, index=True)
    # If failed, which stage did it fail at?
    
    failure_reason = Column(Text, nullable=True)
    # Detailed failure reason
    
    lifecycle_stages = Column(JSONB, nullable=True)
    # Structure: {
    #   "RECEIVED": {"status": "SUCCESS", "timestamp": "2024-01-01T00:00:00Z"},
    #   "VALIDATED": {"status": "SUCCESS", "timestamp": "2024-01-01T00:00:05Z"},
    #   "SENT": {"status": "FAILED", "timestamp": "2024-01-01T00:00:10Z", "error": "..."}
    # }
    
    # ============================================================
    # METADATA
    # ============================================================
    source_format = Column(String(20), nullable=True)  # XML, X12, EDIFACT
    target_format = Column(String(20), nullable=True)  # EDIFACT, X12, XML
    
    request_type = Column(String(20), default='web')  # web, api
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, onupdate=datetime.utcnow, nullable=True)
    
    # ============================================================
    # INDEXES FOR PERFORMANCE
    # ============================================================
    __table_args__ = (
        Index('idx_customer_analysis', 'user_id', 'customer_id', 'created_at'),
        Index('idx_country_analysis', 'user_id', 'customer_country', 'created_at'),
        Index('idx_industry_analysis', 'user_id', 'industry', 'created_at'),
        Index('idx_lifecycle_tracking', 'user_id', 'current_stage', 'stage_status'),
        Index('idx_supplier_analysis', 'user_id', 'supplier_id', 'created_at'),
    )
    
    def __repr__(self):
        return f"<InvoiceBusinessData(id={self.id}, customer={self.customer_name}, stage={self.current_stage})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": str(self.id),
            "tracking_id": str(self.tracking_id),
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "customer_country": self.customer_country,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "industry": self.industry,
            "total_amount": float(self.total_amount) if self.total_amount else None,
            "currency": self.currency,
            "current_stage": self.current_stage,
            "stage_status": self.stage_status,
            "failed_at_stage": self.failed_at_stage,
            "products": self.products,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

