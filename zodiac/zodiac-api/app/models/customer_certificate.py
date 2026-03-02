"""
Customer Certificate Model
Stores X.509 client certificates for mTLS authentication.
Supports full certificate lifecycle: issuance, renewal, expiration tracking, revocation.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, ForeignKey, Index, Enum as SQLEnum
from datetime import datetime
import enum

from ..database import Base


class CertificateStatus(str, enum.Enum):
    """Certificate status lifecycle states"""
    PENDING = "pending"  # Certificate request created, not yet issued
    ACTIVE = "active"  # Certificate issued and valid
    EXPIRING_SOON = "expiring_soon"  # < 90 days until expiration
    EXPIRED = "expired"  # Past expiration date
    REVOKED = "revoked"  # Manually revoked
    RENEWED = "renewed"  # Replaced by a newer certificate


class CertificateType(str, enum.Enum):
    """Type of certificate"""
    CLIENT = "client"  # Client certificate for mTLS authentication
    SERVER = "server"  # Server certificate (less common for customers)


class CustomerCertificate(Base):
    """X.509 certificates for customer/supplier mTLS authentication"""
    __tablename__ = "customer_certificates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(255), nullable=False, index=True)
    
    # Certificate metadata
    certificate_type = Column(String(32), nullable=False, default="client")
    common_name = Column(String(255), nullable=False)
    organization = Column(String(255), nullable=True)
    organizational_unit = Column(String(255), nullable=True)
    country = Column(String(2), nullable=True)
    email = Column(String(255), nullable=True)
    
    # Certificate content (PEM format)
    certificate_pem = Column(Text, nullable=False)
    private_key_encrypted = Column(Text, nullable=True)
    
    # Certificate identifiers
    serial_number = Column(String(255), unique=True, nullable=False, index=True)
    fingerprint_sha256 = Column(String(64), unique=True, nullable=False, index=True)
    
    # Lifecycle dates
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    renewed_at = Column(DateTime, nullable=True)
    
    # Status tracking
    status = Column(String(32), nullable=False, default="pending", index=True)
    
    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    created_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    revoked_by = Column(Integer, ForeignKey("zodiac_users.id"), nullable=True)
    
    # Additional metadata
    notes = Column(Text, nullable=True)
    revocation_reason = Column(String(255), nullable=True)
    
    # Link to renewed certificate (if this cert was renewed)
    renewed_certificate_id = Column(Integer, ForeignKey("customer_certificates.id"), nullable=True)

    __table_args__ = (
        Index("idx_customer_cert_customer_status", "customer_id", "status"),
        Index("idx_customer_cert_active", "status", "expires_at"),
        Index("idx_customer_cert_expiring", "status", "expires_at"),
    )

    def __repr__(self):
        return f"<CustomerCertificate(id={self.id}, customer_id={self.customer_id!r}, cn={self.common_name!r}, status={self.status})>"
