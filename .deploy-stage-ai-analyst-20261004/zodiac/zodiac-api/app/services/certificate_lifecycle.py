"""
Certificate Lifecycle Service
High-level orchestration of certificate lifecycle workflows.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from ..models.customer_certificate import CustomerCertificate, CertificateStatus
from ..models.certificate_renewal_request import CertificateRenewalRequest
from ..models.certificate_revocation import CertificateRevocation
from ..services.certificate_service import (
    update_certificate_statuses,
    get_certificates_expiring_soon,
)
from ..utils.certificate_crypto import days_until_expiry, load_certificate_from_pem

logger = logging.getLogger("zodiac.certificate_lifecycle")


def create_renewal_request(
    db: Session,
    certificate_id: int,
    requested_by_user_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> CertificateRenewalRequest:
    """
    Create a renewal request for a certificate.
    
    Args:
        db: Database session
        certificate_id: Certificate to renew
        requested_by_user_id: User requesting renewal
        notes: Optional notes
    
    Returns:
        Renewal request record
    """
    # Verify certificate exists
    cert = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
    if not cert:
        raise ValueError(f"Certificate {certificate_id} not found")
    
    if cert.status == CertificateStatus.REVOKED.value:
        raise ValueError("Cannot renew a revoked certificate")
    
    # Check if there's already a pending renewal request
    existing = db.query(CertificateRenewalRequest).filter(
        CertificateRenewalRequest.certificate_id == certificate_id,
        CertificateRenewalRequest.request_status == "pending"
    ).first()
    
    if existing:
        raise ValueError(f"Renewal request already exists (id={existing.id})")
    
    # Create renewal request
    renewal = CertificateRenewalRequest(
        certificate_id=certificate_id,
        customer_id=cert.customer_id,
        request_status="pending",
        requested_by=requested_by_user_id,
        notes=notes,
    )
    
    db.add(renewal)
    db.commit()
    db.refresh(renewal)
    
    logger.info(f"✅ Created renewal request {renewal.id} for certificate {certificate_id}")
    
    return renewal


def auto_create_renewal_requests(db: Session, days_threshold: int = 30) -> List[CertificateRenewalRequest]:
    """
    Automatically create renewal requests for certificates expiring soon.
    Call this from a daily cron job.
    
    Args:
        db: Database session
        days_threshold: Create renewal requests for certs expiring within this many days
    
    Returns:
        List of created renewal requests
    """
    # Get certificates expiring soon without pending renewal requests
    expiring_certs = get_certificates_expiring_soon(db, days_threshold)
    
    created_requests = []
    for cert in expiring_certs:
        # Check if renewal request already exists
        existing = db.query(CertificateRenewalRequest).filter(
            CertificateRenewalRequest.certificate_id == cert.id,
            CertificateRenewalRequest.request_status.in_(["pending", "approved"])
        ).first()
        
        if existing:
            continue
        
        try:
            renewal = CertificateRenewalRequest(
                certificate_id=cert.id,
                customer_id=cert.customer_id,
                request_status="pending",
                notes=f"Auto-generated: Certificate expires in {days_until_expiry(load_certificate_from_pem(cert.certificate_pem))} days"
            )
            db.add(renewal)
            created_requests.append(renewal)
        except Exception as e:
            logger.error(f"Failed to create auto-renewal for cert {cert.id}: {e}")
    
    if created_requests:
        db.commit()
        logger.info(f"✅ Auto-created {len(created_requests)} renewal requests")
    
    return created_requests


def get_certificate_health_summary(db: Session) -> Dict[str, Any]:
    """
    Get overall certificate health summary for dashboard.
    
    Returns:
        Dict with certificate statistics
    """
    total = db.query(CustomerCertificate).count()
    active = db.query(CustomerCertificate).filter(
        CustomerCertificate.status == CertificateStatus.ACTIVE.value
    ).count()
    expiring_soon = db.query(CustomerCertificate).filter(
        CustomerCertificate.status == CertificateStatus.EXPIRING_SOON.value
    ).count()
    expired = db.query(CustomerCertificate).filter(
        CustomerCertificate.status == CertificateStatus.EXPIRED.value
    ).count()
    revoked = db.query(CustomerCertificate).filter(
        CustomerCertificate.status == CertificateStatus.REVOKED.value
    ).count()
    
    # Pending renewal requests
    pending_renewals = db.query(CertificateRenewalRequest).filter(
        CertificateRenewalRequest.request_status == "pending"
    ).count()
    
    # Certificates expiring in next 7, 30, 90 days
    now = datetime.utcnow()
    expiring_7d = db.query(CustomerCertificate).filter(
        CustomerCertificate.status.in_([CertificateStatus.ACTIVE.value, CertificateStatus.EXPIRING_SOON.value]),
        CustomerCertificate.expires_at <= now + timedelta(days=7),
        CustomerCertificate.expires_at >= now
    ).count()
    
    expiring_30d = db.query(CustomerCertificate).filter(
        CustomerCertificate.status.in_([CertificateStatus.ACTIVE.value, CertificateStatus.EXPIRING_SOON.value]),
        CustomerCertificate.expires_at <= now + timedelta(days=30),
        CustomerCertificate.expires_at >= now
    ).count()
    
    expiring_90d = db.query(CustomerCertificate).filter(
        CustomerCertificate.status.in_([CertificateStatus.ACTIVE.value, CertificateStatus.EXPIRING_SOON.value]),
        CustomerCertificate.expires_at <= now + timedelta(days=90),
        CustomerCertificate.expires_at >= now
    ).count()
    
    return {
        "total_certificates": total,
        "active": active,
        "expiring_soon": expiring_soon,
        "expired": expired,
        "revoked": revoked,
        "pending_renewal_requests": pending_renewals,
        "expiring_within": {
            "7_days": expiring_7d,
            "30_days": expiring_30d,
            "90_days": expiring_90d,
        }
    }
