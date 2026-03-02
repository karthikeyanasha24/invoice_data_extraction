"""
Certificate Renewal Request Model
Tracks certificate renewal requests and approval workflows.
"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, Text
from datetime import datetime

from ..database import Base


class CertificateRenewalRequest(Base):
    """Certificate renewal requests and approval workflow"""
    __tablename__ = "certificate_renewal_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    certificate_id = Column(Integer, ForeignKey("customer_certificates.id"), nullable=False, index=True)
    customer_id = Column(String(255), nullable=False, index=True)
    
    # Renewal request details
    request_status = Column(String(32), nullable=False, default="pending", index=True)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    requested_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    
    # Processing
    processed_at = Column(DateTime, nullable=True)
    processed_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    
    # New certificate reference (after approval)
    new_certificate_id = Column(Integer, ForeignKey("customer_certificates.id"), nullable=True)
    
    # Additional metadata
    notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_renewal_customer_status", "customer_id", "request_status"),
        Index("idx_renewal_status_date", "request_status", "requested_at"),
    )

    def __repr__(self):
        return f"<CertificateRenewalRequest(id={self.id}, cert_id={self.certificate_id}, status={self.request_status})>"
