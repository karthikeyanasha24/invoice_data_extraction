"""
Mutual TLS (mTLS) Authentication Middleware
Validates client certificates from TLS handshake for enterprise B2B security.
Integrates with existing token-based authentication for dual-factor security.
"""
import logging
from typing import Optional, Tuple
from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.certificate_validation import validate_client_certificate
from ..models.customer_certificate import CustomerCertificate

logger = logging.getLogger("zodiac.mtls_auth")


async def extract_client_certificate_from_request(request: Request) -> Optional[str]:
    """
    Extract client certificate from TLS handshake.
    
    The certificate is provided by the reverse proxy (nginx/Apache) in headers:
    - X-Client-Cert: Full certificate in PEM format (URL-encoded)
    - X-Client-Cert-Subject: Certificate subject DN
    - X-Client-Cert-Serial: Certificate serial number
    
    In development, certificates may not be available.
    
    Args:
        request: FastAPI request object
    
    Returns:
        Client certificate in PEM format, or None if not present
    """
    # Check for client certificate from reverse proxy
    cert_header = request.headers.get("X-Client-Cert") or request.headers.get("X-SSL-Client-Cert")
    
    if cert_header:
        # Nginx/Apache typically URL-encodes the certificate
        import urllib.parse
        try:
            cert_pem = urllib.parse.unquote(cert_header)
            # Ensure proper PEM format
            if not cert_pem.startswith("-----BEGIN CERTIFICATE-----"):
                cert_pem = f"-----BEGIN CERTIFICATE-----\n{cert_pem}\n-----END CERTIFICATE-----"
            return cert_pem
        except Exception as e:
            logger.warning(f"Failed to decode client certificate header: {e}")
            return None
    
    # Alternative: Check if running behind a proxy that puts cert in custom header
    ssl_client_cert = request.headers.get("SSL-Client-Cert")
    if ssl_client_cert:
        return ssl_client_cert
    
    return None


async def validate_mtls_request(
    request: Request,
    db: Session,
    require_certificate: bool = False,
) -> Tuple[bool, Optional[str], Optional[CustomerCertificate], Optional[str]]:
    """
    Validate mTLS authentication for a request.
    
    Args:
        request: FastAPI request
        db: Database session
        require_certificate: If True, reject requests without valid client certificate
    
    Returns:
        Tuple of (is_authenticated, customer_id, certificate_record, error_message)
    """
    # Extract client certificate
    cert_pem = await extract_client_certificate_from_request(request)
    
    if not cert_pem:
        if require_certificate:
            return False, None, None, "Client certificate required for this endpoint"
        # No certificate, but not required
        return False, None, None, None
    
    # Validate certificate
    is_valid, customer_id, cert_record, validation_details = validate_client_certificate(
        db=db,
        cert_pem=cert_pem,
        check_crl=True,
    )
    
    if not is_valid:
        failures = validation_details.get("failures", [])
        error_msg = "; ".join(failures) if failures else "Certificate validation failed"
        logger.warning(f"mTLS validation failed: {error_msg}")
        return False, customer_id, cert_record, error_msg
    
    logger.info(f"✅ mTLS authenticated: customer_id={customer_id}, cert_id={cert_record.id}")
    
    return True, customer_id, cert_record, None


async def get_mtls_customer_id(
    request: Request,
    db: Session,
) -> Optional[str]:
    """
    Dependency function to extract customer_id from validated client certificate.
    Use this as a FastAPI dependency in endpoints that support mTLS.
    
    Returns:
        customer_id if certificate is valid, None otherwise
    """
    is_valid, customer_id, cert_record, error = await validate_mtls_request(
        request=request,
        db=db,
        require_certificate=False,
    )
    
    return customer_id if is_valid else None


async def require_mtls_auth(
    request: Request,
    db: Session,
) -> Tuple[str, CustomerCertificate]:
    """
    Dependency function that REQUIRES valid mTLS authentication.
    Use this for endpoints that mandate client certificate authentication.
    
    Returns:
        Tuple of (customer_id, certificate_record)
    
    Raises:
        HTTPException if certificate is invalid or missing
    """
    is_valid, customer_id, cert_record, error = await validate_mtls_request(
        request=request,
        db=db,
        require_certificate=True,
    )
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error or "Invalid or missing client certificate",
            headers={"WWW-Authenticate": "Certificate"},
        )
    
    return customer_id, cert_record


# ========== Hybrid Authentication (mTLS + Token) ==========

async def get_authenticated_customer_id_hybrid(
    request: Request,
    db: Session,
    x_customer_token: Optional[str] = None,
) -> Optional[str]:
    """
    Hybrid authentication: Try mTLS first, fall back to token.
    Supports gradual migration from token-only to mTLS.
    
    Args:
        request: FastAPI request
        db: Database session
        x_customer_token: Optional customer token header
    
    Returns:
        customer_id if authenticated via mTLS or token, None otherwise
    """
    # Try mTLS first
    is_valid, customer_id, cert_record, error = await validate_mtls_request(
        request=request,
        db=db,
        require_certificate=False,
    )
    
    if is_valid and customer_id:
        logger.info(f"Authenticated via mTLS: customer_id={customer_id}")
        return customer_id
    
    # Fall back to token authentication
    if x_customer_token:
        from ..models.customer_token import CustomerToken
        from ..models.user import verify_api_key
        from datetime import datetime
        
        record = db.query(CustomerToken).filter(
            CustomerToken.token == x_customer_token,
            CustomerToken.is_active == True,
        ).first()
        
        if record and verify_api_key(x_customer_token, record.token_hash):
            if not record.expires_at or record.expires_at >= datetime.utcnow():
                record.last_used_at = datetime.utcnow()
                db.commit()
                logger.info(f"Authenticated via token: customer_id={record.customer_id}")
                return record.customer_id
    
    return None
