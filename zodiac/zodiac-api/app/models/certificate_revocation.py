"""
Certificate Revocation List (CRL) Model
Tracks revoked certificates for security and audit purposes.
"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, Text
from datetime import datetime

from ..database import Base


class CertificateRevocation(Base):
    """Certificate Revocation List (CRL) entries"""
    __tablename__ = "certificate_revocation_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    certificate_id = Column(Integer, ForeignKey("customer_certificates.id"), nullable=False, index=True)
    customer_id = Column(String(255), nullable=False, index=True)
    
    # Revocation details
    serial_number = Column(String(255), nullable=False, index=True)
    fingerprint_sha256 = Column(String(64), nullable=False, index=True)
    revoked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    revoked_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    
    # Revocation reason codes (RFC 5280)
    reason = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    
    # CRL publication tracking
    published_in_crl_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_crl_serial", "serial_number"),
        Index("idx_crl_fingerprint", "fingerprint_sha256"),
        Index("idx_crl_customer", "customer_id", "revoked_at"),
    )

    def __repr__(self):
        return f"<CertificateRevocation(id={self.id}, cert_id={self.certificate_id}, serial={self.serial_number}, revoked_at={self.revoked_at})>"
