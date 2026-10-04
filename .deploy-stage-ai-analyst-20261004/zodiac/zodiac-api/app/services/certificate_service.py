"""
Certificate Service
High-level service for certificate lifecycle operations: issue, renew, export.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session

from ..models.customer_certificate import CustomerCertificate, CertificateStatus
from ..models.customer import Customer
from ..utils.certificate_crypto import (
    create_ca_certificate,
    create_client_certificate,
    certificate_to_pem,
    private_key_to_pem,
    create_pkcs12_bundle,
    load_certificate_from_pem,
    load_private_key_from_pem,
    get_certificate_fingerprint,
    get_certificate_serial,
    generate_strong_password,
)
from ..utils.encryption_utils import encrypt_secret, decrypt_secret

logger = logging.getLogger("zodiac.certificate_service")

# CA certificate storage (in production, use HSM or secure vault)
CA_CERT_PATH = os.getenv("CA_CERT_PATH", "ca_cert.pem")
CA_KEY_PATH = os.getenv("CA_KEY_PATH", "ca_key.pem")
CA_KEY_PASSWORD = os.getenv("CA_KEY_PASSWORD", None)


def get_or_create_ca() -> Tuple[Any, Any]:
    """
    Get existing CA certificate and key, or create new ones.
    
    Returns:
        Tuple of (CA certificate, CA private key)
    """
    # Check if CA exists
    if os.path.exists(CA_CERT_PATH) and os.path.exists(CA_KEY_PATH):
        try:
            with open(CA_CERT_PATH, 'r') as f:
                ca_cert = load_certificate_from_pem(f.read())
            with open(CA_KEY_PATH, 'r') as f:
                ca_key = load_private_key_from_pem(f.read(), CA_KEY_PASSWORD)
            logger.info("✅ Loaded existing CA certificate")
            return ca_cert, ca_key
        except Exception as e:
            logger.error(f"Failed to load CA certificate: {e}")
            raise
    
    # Create new CA
    logger.warning("⚠️ CA certificate not found. Creating new CA...")
    ca_cert, ca_key = create_ca_certificate(
        common_name="Zodiac Invoice Portal CA",
        organization="Zodiac Systems",
        country="US",
        validity_years=10,
    )
    
    # Save CA certificate and key
    try:
        os.makedirs(os.path.dirname(CA_CERT_PATH) or ".", exist_ok=True)
        
        with open(CA_CERT_PATH, 'w') as f:
            f.write(certificate_to_pem(ca_cert))
        
        with open(CA_KEY_PATH, 'w') as f:
            f.write(private_key_to_pem(ca_key, CA_KEY_PASSWORD))
        
        # Secure the private key file (Unix only)
        try:
            os.chmod(CA_KEY_PATH, 0o600)
        except Exception:
            pass
        
        logger.info("✅ Created and saved new CA certificate")
        logger.warning("🔐 IMPORTANT: Backup and secure the CA private key file!")
    except Exception as e:
        logger.error(f"Failed to save CA certificate: {e}")
        raise
    
    return ca_cert, ca_key


def issue_client_certificate(
    db: Session,
    customer_id: str,
    organization: Optional[str] = None,
    organizational_unit: Optional[str] = None,
    country: Optional[str] = None,
    email: Optional[str] = None,
    validity_days: int = 365,
    created_by_user_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> Tuple[CustomerCertificate, str, bytes, str]:
    """
    Issue a new client certificate for a customer.
    
    Args:
        db: Database session
        customer_id: Customer identifier
        organization: Organization name
        organizational_unit: Department name
        country: Two-letter country code
        email: Contact email
        validity_days: Certificate validity in days
        created_by_user_id: Admin user who issued the certificate
        notes: Optional notes
    
    Returns:
        Tuple of (certificate_record, p12_password, p12_bytes, download_instructions)
    """
    # Verify customer exists
    customer = db.query(Customer).filter(Customer.customer_id == customer_id).first()
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")
    
    # Check if customer already has an active certificate
    existing = db.query(CustomerCertificate).filter(
        CustomerCertificate.customer_id == customer_id,
        CustomerCertificate.status.in_([CertificateStatus.ACTIVE, CertificateStatus.EXPIRING_SOON])
    ).first()
    
    if existing:
        logger.warning(f"Customer {customer_id} already has an active certificate (id={existing.id}). Consider renewal instead.")
    
    # Get or create CA
    ca_cert, ca_key = get_or_create_ca()
    
    # Generate common name
    common_name = f"{customer_id}.zodiac-portal.local"
    
    # Create client certificate
    client_cert, client_key, serial, fingerprint = create_client_certificate(
        customer_id=customer_id,
        common_name=common_name,
        ca_cert=ca_cert,
        ca_private_key=ca_key,
        organization=organization,
        organizational_unit=organizational_unit,
        country=country,
        email=email,
        validity_days=validity_days,
    )
    
    # Convert to PEM
    cert_pem = certificate_to_pem(client_cert)
    key_pem = private_key_to_pem(client_key)
    
    # Encrypt private key for database storage
    encrypted_key = encrypt_secret(key_pem)
    
    # Store in database
    cert_record = CustomerCertificate(
        customer_id=customer_id,
        certificate_type="client",
        common_name=common_name,
        organization=organization,
        organizational_unit=organizational_unit,
        country=country,
        email=email,
        certificate_pem=cert_pem,
        private_key_encrypted=encrypted_key,
        serial_number=serial,
        fingerprint_sha256=fingerprint,
        issued_at=client_cert.not_valid_before,
        expires_at=client_cert.not_valid_after,
        status=CertificateStatus.ACTIVE.value,
        created_by=created_by_user_id,
        notes=notes,
    )
    
    db.add(cert_record)
    db.commit()
    db.refresh(cert_record)
    
    # Generate P12 bundle with random password
    p12_password = generate_strong_password(16)
    p12_bytes = create_pkcs12_bundle(
        cert=client_cert,
        private_key=client_key,
        ca_cert=ca_cert,
        password=p12_password,
        friendly_name=f"{customer_id} - Zodiac Portal Client Certificate",
    )
    
    logger.info(f"✅ Issued client certificate for {customer_id} (cert_id={cert_record.id}, serial={serial})")
    
    return cert_record, p12_password, p12_bytes, common_name


def renew_certificate(
    db: Session,
    certificate_id: int,
    validity_days: int = 365,
    renewed_by_user_id: Optional[int] = None,
) -> Tuple[CustomerCertificate, str, bytes]:
    """
    Renew an existing certificate (creates a new certificate with same details).
    
    Args:
        db: Database session
        certificate_id: ID of certificate to renew
        validity_days: New certificate validity period
        renewed_by_user_id: Admin user who approved renewal
    
    Returns:
        Tuple of (new_certificate_record, p12_password, p12_bytes)
    """
    # Get old certificate
    old_cert = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
    if not old_cert:
        raise ValueError(f"Certificate {certificate_id} not found")
    
    # Issue new certificate with same details
    new_cert, p12_password, p12_bytes, _ = issue_client_certificate(
        db=db,
        customer_id=old_cert.customer_id,
        organization=old_cert.organization,
        organizational_unit=old_cert.organizational_unit,
        country=old_cert.country,
        email=old_cert.email,
        validity_days=validity_days,
        created_by_user_id=renewed_by_user_id,
        notes=f"Renewed from certificate ID {certificate_id}",
    )
    
    # Mark old certificate as renewed
    old_cert.status = CertificateStatus.RENEWED.value
    old_cert.renewed_at = datetime.utcnow()
    old_cert.renewed_certificate_id = new_cert.id
    old_cert.updated_at = datetime.utcnow()
    db.commit()
    
    logger.info(f"✅ Renewed certificate {certificate_id} → new certificate {new_cert.id}")
    
    return new_cert, p12_password, p12_bytes


def get_certificate_pem_bundle(db: Session, certificate_id: int) -> Dict[str, str]:
    """
    Get certificate and CA certificate as PEM bundle for download.
    
    Args:
        db: Database session
        certificate_id: Certificate ID
    
    Returns:
        Dict with 'certificate', 'ca_certificate', 'private_key' (if available)
    """
    cert_record = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
    if not cert_record:
        raise ValueError(f"Certificate {certificate_id} not found")
    
    ca_cert, _ = get_or_create_ca()
    ca_pem = certificate_to_pem(ca_cert)
    
    result = {
        "certificate": cert_record.certificate_pem,
        "ca_certificate": ca_pem,
    }
    
    # Include private key if available (decrypted)
    if cert_record.private_key_encrypted:
        decrypted_key = decrypt_secret(cert_record.private_key_encrypted)
        result["private_key"] = decrypted_key
    
    return result


def revoke_certificate(
    db: Session,
    certificate_id: int,
    reason: Optional[str] = None,
    revoked_by_user_id: Optional[int] = None,
) -> CustomerCertificate:
    """
    Revoke a certificate immediately.
    
    Args:
        db: Database session
        certificate_id: Certificate ID to revoke
        reason: Revocation reason
        revoked_by_user_id: Admin user who revoked the certificate
    
    Returns:
        Updated certificate record
    """
    cert = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
    if not cert:
        raise ValueError(f"Certificate {certificate_id} not found")
    
    if cert.status == CertificateStatus.REVOKED.value:
        raise ValueError(f"Certificate {certificate_id} is already revoked")
    
    # Update certificate status
    cert.status = CertificateStatus.REVOKED.value
    cert.revoked_at = datetime.utcnow()
    cert.revoked_by = revoked_by_user_id
    cert.revocation_reason = reason
    cert.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(cert)
    
    # Add to CRL (done in separate function)
    from ..models.certificate_revocation import CertificateRevocation
    crl_entry = CertificateRevocation(
        certificate_id=cert.id,
        customer_id=cert.customer_id,
        serial_number=cert.serial_number,
        fingerprint_sha256=cert.fingerprint_sha256,
        revoked_at=cert.revoked_at,
        revoked_by=revoked_by_user_id,
        reason=reason,
    )
    db.add(crl_entry)
    db.commit()
    
    logger.info(f"✅ Revoked certificate {certificate_id} for customer {cert.customer_id}")
    
    return cert


def update_certificate_statuses(db: Session) -> Dict[str, int]:
    """
    Update certificate statuses based on expiration dates.
    Call this periodically (e.g., daily cron job).
    
    Returns:
        Dict with counts of status updates
    """
    now = datetime.utcnow()
    expiring_threshold = now + timedelta(days=90)
    
    stats = {
        "marked_expired": 0,
        "marked_expiring_soon": 0,
        "marked_active": 0,
    }
    
    # Mark expired certificates
    expired = db.query(CustomerCertificate).filter(
        CustomerCertificate.status.in_([CertificateStatus.ACTIVE.value, CertificateStatus.EXPIRING_SOON.value]),
        CustomerCertificate.expires_at < now,
    ).all()
    
    for cert in expired:
        cert.status = CertificateStatus.EXPIRED.value
        cert.updated_at = now
        stats["marked_expired"] += 1
    
    # Mark expiring soon
    expiring = db.query(CustomerCertificate).filter(
        CustomerCertificate.status == CertificateStatus.ACTIVE.value,
        CustomerCertificate.expires_at >= now,
        CustomerCertificate.expires_at < expiring_threshold,
    ).all()
    
    for cert in expiring:
        cert.status = CertificateStatus.EXPIRING_SOON.value
        cert.updated_at = now
        stats["marked_expiring_soon"] += 1
    
    # Mark as active if previously expiring_soon but now > 90 days (e.g., after renewal)
    back_to_active = db.query(CustomerCertificate).filter(
        CustomerCertificate.status == CertificateStatus.EXPIRING_SOON.value,
        CustomerCertificate.expires_at >= expiring_threshold,
    ).all()
    
    for cert in back_to_active:
        cert.status = CertificateStatus.ACTIVE.value
        cert.updated_at = now
        stats["marked_active"] += 1
    
    if any(stats.values()):
        db.commit()
        logger.info(f"Certificate status update: {stats}")
    
    return stats


def get_certificates_expiring_soon(
    db: Session,
    days_threshold: int = 90,
) -> list[CustomerCertificate]:
    """
    Get certificates that will expire within the specified number of days.
    
    Args:
        db: Database session
        days_threshold: Number of days threshold (e.g., 90, 60, 30, 7)
    
    Returns:
        List of certificates expiring soon
    """
    threshold_date = datetime.utcnow() + timedelta(days=days_threshold)
    
    certs = db.query(CustomerCertificate).filter(
        CustomerCertificate.status.in_([
            CertificateStatus.ACTIVE.value,
            CertificateStatus.EXPIRING_SOON.value
        ]),
        CustomerCertificate.expires_at <= threshold_date,
        CustomerCertificate.expires_at >= datetime.utcnow(),
    ).order_by(CustomerCertificate.expires_at).all()
    
    return certs


def get_customer_active_certificate(
    db: Session,
    customer_id: str,
) -> Optional[CustomerCertificate]:
    """
    Get the active certificate for a customer.
    
    Args:
        db: Database session
        customer_id: Customer identifier
    
    Returns:
        Active certificate or None
    """
    cert = db.query(CustomerCertificate).filter(
        CustomerCertificate.customer_id == customer_id,
        CustomerCertificate.status.in_([
            CertificateStatus.ACTIVE.value,
            CertificateStatus.EXPIRING_SOON.value
        ])
    ).order_by(CustomerCertificate.expires_at.desc()).first()
    
    return cert


def validate_certificate_by_fingerprint(
    db: Session,
    fingerprint: str,
) -> Tuple[bool, Optional[CustomerCertificate], Optional[str]]:
    """
    Validate a certificate by its SHA-256 fingerprint.
    
    Args:
        db: Database session
        fingerprint: SHA-256 fingerprint (hex string)
    
    Returns:
        Tuple of (is_valid, certificate_record, error_message)
    """
    cert = db.query(CustomerCertificate).filter(
        CustomerCertificate.fingerprint_sha256 == fingerprint.lower()
    ).first()
    
    if not cert:
        return False, None, "Certificate not found"
    
    if cert.status == CertificateStatus.REVOKED.value:
        return False, cert, f"Certificate revoked on {cert.revoked_at}"
    
    if cert.status == CertificateStatus.EXPIRED.value:
        return False, cert, f"Certificate expired on {cert.expires_at}"
    
    if datetime.utcnow() > cert.expires_at:
        return False, cert, "Certificate has expired"
    
    if cert.status not in [CertificateStatus.ACTIVE.value, CertificateStatus.EXPIRING_SOON.value]:
        return False, cert, f"Certificate status is {cert.status}"
    
    return True, cert, None


def validate_certificate_by_serial(
    db: Session,
    serial_number: str,
) -> Tuple[bool, Optional[CustomerCertificate], Optional[str]]:
    """
    Validate a certificate by its serial number.
    
    Args:
        db: Database session
        serial_number: Certificate serial number
    
    Returns:
        Tuple of (is_valid, certificate_record, error_message)
    """
    cert = db.query(CustomerCertificate).filter(
        CustomerCertificate.serial_number == serial_number
    ).first()
    
    if not cert:
        return False, None, "Certificate not found"
    
    # Use fingerprint validation logic
    return validate_certificate_by_fingerprint(db, cert.fingerprint_sha256)
