"""
Certificate Management API
Endpoints for certificate lifecycle management: issue, renew, revoke, list, download.
Admin-only operations for managing customer/supplier certificates.
"""
import logging
import io
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import ZodiacUser
from ..api.auth import get_current_user
from ..models.customer_certificate import CustomerCertificate, CertificateStatus
from ..models.certificate_renewal_request import CertificateRenewalRequest
from ..schemas.certificate import (
    CertificateIssueRequest,
    CertificateIssueResponse,
    CertificateRenewalRequest as CertRenewalReq,
    CertificateRenewalResponse,
    CertificateRevocationRequest,
    CertificateRevocationResponse,
    CertificateInfoResponse,
    CertificateListResponse,
    CertificateDownloadResponse,
    RenewalRequestCreateRequest,
    RenewalRequestResponse,
    RenewalRequestApprovalRequest,
)
from ..services.certificate_service import (
    issue_client_certificate,
    renew_certificate,
    revoke_certificate,
    get_certificate_pem_bundle,
    get_customer_active_certificate,
)
from ..services.certificate_validation import validate_client_certificate
from ..services.certificate_lifecycle import (
    create_renewal_request,
    get_certificate_health_summary,
)
from ..utils.certificate_crypto import (
    create_pkcs12_bundle,
    load_certificate_from_pem,
    load_private_key_from_pem,
    days_until_expiry,
    generate_strong_password,
)

router = APIRouter(prefix="/certificates", tags=["certificates"])
logger = logging.getLogger("zodiac-api.certificates")


# ========== Certificate CRUD ==========

@router.post("/issue", response_model=CertificateIssueResponse)
def issue_certificate(
    body: CertificateIssueRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Issue a new client certificate for a customer.
    Admin only. Certificate and private key are returned as P12 bundle.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        cert_record, p12_password, p12_bytes, common_name = issue_client_certificate(
            db=db,
            customer_id=body.customer_id,
            organization=body.organization,
            organizational_unit=body.organizational_unit,
            country=body.country,
            email=body.email,
            validity_days=body.validity_days,
            created_by_user_id=current_user.id,
            notes=body.notes,
        )
        
        # Store P12 temporarily for download (in production, use secure temporary storage)
        # For now, return download instructions
        download_url = f"/api/certificates/{cert_record.id}/download-p12"
        
        return CertificateIssueResponse(
            success=True,
            message="Certificate issued successfully. Download the P12 file and store the password securely.",
            certificate_id=cert_record.id,
            customer_id=cert_record.customer_id,
            serial_number=cert_record.serial_number,
            fingerprint_sha256=cert_record.fingerprint_sha256,
            common_name=common_name,
            issued_at=cert_record.issued_at,
            expires_at=cert_record.expires_at,
            p12_password=p12_password,
            download_url=download_url,
        )
    
    except Exception as e:
        logger.error(f"Failed to issue certificate: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to issue certificate: {str(e)}"
        )


@router.get("/", response_model=CertificateListResponse)
def list_certificates(
    customer_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    List all certificates with optional filters.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    query = db.query(CustomerCertificate)
    
    if customer_id:
        query = query.filter(CustomerCertificate.customer_id == customer_id)
    
    if status_filter:
        query = query.filter(CustomerCertificate.status == status_filter)
    
    total = query.count()
    certs = query.order_by(CustomerCertificate.created_at.desc()).offset(skip).limit(limit).all()
    
    # Convert to response format
    cert_responses = []
    for cert in certs:
        try:
            cert_obj = load_certificate_from_pem(cert.certificate_pem)
            days_left = days_until_expiry(cert_obj)
        except Exception:
            days_left = None
        
        cert_responses.append(CertificateInfoResponse(
            id=cert.id,
            customer_id=cert.customer_id,
            certificate_type=cert.certificate_type,
            common_name=cert.common_name,
            organization=cert.organization,
            organizational_unit=cert.organizational_unit,
            country=cert.country,
            email=cert.email,
            serial_number=cert.serial_number,
            fingerprint_sha256=cert.fingerprint_sha256,
            issued_at=cert.issued_at,
            expires_at=cert.expires_at,
            status=cert.status,
            revoked_at=cert.revoked_at,
            revoked_by=cert.revoked_by,
            revocation_reason=cert.revocation_reason,
            renewed_at=cert.renewed_at,
            renewed_certificate_id=cert.renewed_certificate_id,
            created_at=cert.created_at,
            updated_at=cert.updated_at,
            created_by=cert.created_by,
            notes=cert.notes,
            days_until_expiry=days_left,
        ))
    
    return CertificateListResponse(certificates=cert_responses, total=total)


@router.get("/{certificate_id}", response_model=CertificateInfoResponse)
def get_certificate(
    certificate_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Get certificate details by ID.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    cert = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate not found"
        )
    
    try:
        cert_obj = load_certificate_from_pem(cert.certificate_pem)
        days_left = days_until_expiry(cert_obj)
    except Exception:
        days_left = None
    
    return CertificateInfoResponse(
        id=cert.id,
        customer_id=cert.customer_id,
        certificate_type=cert.certificate_type,
        common_name=cert.common_name,
        organization=cert.organization,
        organizational_unit=cert.organizational_unit,
        country=cert.country,
        email=cert.email,
        serial_number=cert.serial_number,
        fingerprint_sha256=cert.fingerprint_sha256,
        issued_at=cert.issued_at,
        expires_at=cert.expires_at,
        status=cert.status,
        revoked_at=cert.revoked_at,
        revoked_by=cert.revoked_by,
        revocation_reason=cert.revocation_reason,
        renewed_at=cert.renewed_at,
        renewed_certificate_id=cert.renewed_certificate_id,
        created_at=cert.created_at,
        updated_at=cert.updated_at,
        created_by=cert.created_by,
        notes=cert.notes,
        days_until_expiry=days_left,
    )


@router.get("/customer/{customer_id}/active", response_model=CertificateInfoResponse)
def get_customer_certificate(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Get active certificate for a customer.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    cert = get_customer_active_certificate(db, customer_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active certificate found for customer {customer_id}"
        )
    
    try:
        cert_obj = load_certificate_from_pem(cert.certificate_pem)
        days_left = days_until_expiry(cert_obj)
    except Exception:
        days_left = None
    
    return CertificateInfoResponse(
        id=cert.id,
        customer_id=cert.customer_id,
        certificate_type=cert.certificate_type,
        common_name=cert.common_name,
        organization=cert.organization,
        organizational_unit=cert.organizational_unit,
        country=cert.country,
        email=cert.email,
        serial_number=cert.serial_number,
        fingerprint_sha256=cert.fingerprint_sha256,
        issued_at=cert.issued_at,
        expires_at=cert.expires_at,
        status=cert.status,
        revoked_at=cert.revoked_at,
        revoked_by=cert.revoked_by,
        revocation_reason=cert.revocation_reason,
        renewed_at=cert.renewed_at,
        renewed_certificate_id=cert.renewed_certificate_id,
        created_at=cert.created_at,
        updated_at=cert.updated_at,
        created_by=cert.created_by,
        notes=cert.notes,
        days_until_expiry=days_left,
    )


@router.post("/{certificate_id}/renew", response_model=CertificateRenewalResponse)
def renew_certificate_endpoint(
    certificate_id: int,
    body: CertRenewalReq,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Renew an existing certificate.
    Admin only. Returns new certificate as P12 bundle.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        new_cert, p12_password, p12_bytes = renew_certificate(
            db=db,
            certificate_id=certificate_id,
            validity_days=body.validity_days,
            renewed_by_user_id=current_user.id,
        )
        
        download_url = f"/api/certificates/{new_cert.id}/download-p12"
        
        return CertificateRenewalResponse(
            success=True,
            message="Certificate renewed successfully. Download the new P12 file.",
            old_certificate_id=certificate_id,
            new_certificate_id=new_cert.id,
            customer_id=new_cert.customer_id,
            serial_number=new_cert.serial_number,
            fingerprint_sha256=new_cert.fingerprint_sha256,
            expires_at=new_cert.expires_at,
            p12_password=p12_password,
            download_url=download_url,
        )
    
    except Exception as e:
        logger.error(f"Failed to renew certificate {certificate_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to renew certificate: {str(e)}"
        )


@router.post("/{certificate_id}/revoke", response_model=CertificateRevocationResponse)
def revoke_certificate_endpoint(
    certificate_id: int,
    body: CertificateRevocationRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Revoke a certificate immediately.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        cert = revoke_certificate(
            db=db,
            certificate_id=certificate_id,
            reason=body.reason,
            revoked_by_user_id=current_user.id,
        )
        
        return CertificateRevocationResponse(
            success=True,
            message="Certificate revoked successfully",
            certificate_id=cert.id,
            customer_id=cert.customer_id,
            revoked_at=cert.revoked_at,
        )
    
    except Exception as e:
        logger.error(f"Failed to revoke certificate {certificate_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke certificate: {str(e)}"
        )


@router.get("/{certificate_id}/download-pem", response_model=CertificateDownloadResponse)
def download_certificate_pem(
    certificate_id: int,
    include_private_key: bool = False,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Download certificate and CA certificate as PEM files.
    Admin only. Private key only included if explicitly requested.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        bundle = get_certificate_pem_bundle(db, certificate_id)
        
        return CertificateDownloadResponse(
            certificate_pem=bundle["certificate"],
            ca_certificate_pem=bundle["ca_certificate"],
            private_key_pem=bundle.get("private_key") if include_private_key else None,
        )
    
    except Exception as e:
        logger.error(f"Failed to download certificate {certificate_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download certificate: {str(e)}"
        )


@router.get("/{certificate_id}/download-crt")
def download_certificate_crt(
    certificate_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Download ONLY the public certificate as .crt file (for SAP STRUST SSL Client import).
    This is the certificate WITHOUT the private key - safe to import into SSL client list.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        cert = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
        if not cert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificate not found"
            )
        
        # Get ONLY the public certificate (no private key)
        cert_pem = cert.certificate_pem
        
        # Create filename
        filename = f"{cert.customer_id}-client-cert.crt"
        
        # Return as downloadable file
        return Response(
            content=cert_pem.encode('utf-8'),
            media_type="application/x-x509-ca-cert",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Certificate-Type": "public-only",
                "X-Customer-ID": cert.customer_id,
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download CRT for certificate {certificate_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download certificate: {str(e)}"
        )


@router.get("/{certificate_id}/download-p12")
def download_certificate_p12(
    certificate_id: int,
    password: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Download certificate as P12/PFX bundle (includes private key - for full authentication setup).
    Admin only. If no password provided, generates a random one (included in response header).
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        cert = db.query(CustomerCertificate).filter(CustomerCertificate.id == certificate_id).first()
        if not cert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificate not found"
            )
        
        # Get certificate bundle
        bundle = get_certificate_pem_bundle(db, certificate_id)
        
        # Load certificate and private key
        cert_obj = load_certificate_from_pem(bundle["certificate"])
        private_key = load_private_key_from_pem(bundle["private_key"])
        
        # Load CA certificate
        from ..services.certificate_service import get_or_create_ca
        ca_cert, _ = get_or_create_ca()
        
        # Generate P12 password if not provided
        if not password:
            password = generate_strong_password(16)
        
        # Create P12 bundle
        p12_bytes = create_pkcs12_bundle(
            cert=cert_obj,
            private_key=private_key,
            ca_cert=ca_cert,
            password=password,
            friendly_name=f"{cert.customer_id} - Zodiac Portal",
        )
        
        # Return as downloadable file
        filename = f"{cert.customer_id}-zodiac-certificate.p12"
        
        response = Response(
            content=p12_bytes,
            media_type="application/x-pkcs12",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-P12-Password": password,
            }
        )
        
        logger.info(f"Certificate {certificate_id} downloaded by user {current_user.id}")
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download P12 for certificate {certificate_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download P12: {str(e)}"
        )


# ========== Renewal Requests ==========

@router.post("/renewal-requests", response_model=RenewalRequestResponse)
def create_renewal_request_endpoint(
    body: RenewalRequestCreateRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Create a renewal request for a certificate.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        renewal = create_renewal_request(
            db=db,
            certificate_id=body.certificate_id,
            requested_by_user_id=current_user.id,
            notes=body.notes,
        )
        
        return RenewalRequestResponse(
            id=renewal.id,
            certificate_id=renewal.certificate_id,
            customer_id=renewal.customer_id,
            request_status=renewal.request_status,
            requested_at=renewal.requested_at,
            requested_by=renewal.requested_by,
            processed_at=renewal.processed_at,
            processed_by=renewal.processed_by,
            new_certificate_id=renewal.new_certificate_id,
            notes=renewal.notes,
            rejection_reason=renewal.rejection_reason,
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to create renewal request: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create renewal request: {str(e)}"
        )


@router.get("/renewal-requests")
def list_renewal_requests(
    status_filter: Optional[str] = None,
    customer_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    List renewal requests with optional filters.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    query = db.query(CertificateRenewalRequest)
    
    if status_filter:
        query = query.filter(CertificateRenewalRequest.request_status == status_filter)
    
    if customer_id:
        query = query.filter(CertificateRenewalRequest.customer_id == customer_id)
    
    total = query.count()
    requests = query.order_by(CertificateRenewalRequest.requested_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "renewal_requests": [
            RenewalRequestResponse(
                id=r.id,
                certificate_id=r.certificate_id,
                customer_id=r.customer_id,
                request_status=r.request_status,
                requested_at=r.requested_at,
                requested_by=r.requested_by,
                processed_at=r.processed_at,
                processed_by=r.processed_by,
                new_certificate_id=r.new_certificate_id,
                notes=r.notes,
                rejection_reason=r.rejection_reason,
            )
            for r in requests
        ],
        "total": total,
    }


@router.post("/renewal-requests/{request_id}/process", response_model=CertificateRenewalResponse)
def process_renewal_request(
    request_id: int,
    body: RenewalRequestApprovalRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Approve or reject a renewal request.
    Admin only. If approved, issues new certificate.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        renewal = db.query(CertificateRenewalRequest).filter(
            CertificateRenewalRequest.id == request_id
        ).first()
        
        if not renewal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Renewal request not found"
            )
        
        if renewal.request_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Renewal request already processed (status: {renewal.request_status})"
            )
        
        if body.approved:
            # Approve and renew
            new_cert, p12_password, p12_bytes = renew_certificate(
                db=db,
                certificate_id=renewal.certificate_id,
                validity_days=body.validity_days,
                renewed_by_user_id=current_user.id,
            )
            
            renewal.request_status = "completed"
            renewal.processed_at = datetime.utcnow()
            renewal.processed_by = current_user.id
            renewal.new_certificate_id = new_cert.id
            if body.notes:
                renewal.notes = body.notes
            db.commit()
            
            return CertificateRenewalResponse(
                success=True,
                message="Renewal approved. Certificate renewed successfully.",
                old_certificate_id=renewal.certificate_id,
                new_certificate_id=new_cert.id,
                customer_id=new_cert.customer_id,
                serial_number=new_cert.serial_number,
                fingerprint_sha256=new_cert.fingerprint_sha256,
                expires_at=new_cert.expires_at,
                p12_password=p12_password,
                download_url=f"/api/certificates/{new_cert.id}/download-p12",
            )
        else:
            # Reject
            renewal.request_status = "rejected"
            renewal.processed_at = datetime.utcnow()
            renewal.processed_by = current_user.id
            renewal.rejection_reason = body.rejection_reason
            if body.notes:
                renewal.notes = body.notes
            db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_200_OK,
                detail="Renewal request rejected"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process renewal request {request_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process renewal request: {str(e)}"
        )


# ========== Health & Status ==========

@router.get("/health/summary")
def get_certificate_health(
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Get certificate health summary for dashboard.
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        summary = get_certificate_health_summary(db)
        return summary
    except Exception as e:
        logger.error(f"Failed to get certificate health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get certificate health: {str(e)}"
        )


@router.post("/maintenance/update-statuses")
def update_statuses_endpoint(
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """
    Manually trigger certificate status updates (normally runs via cron).
    Admin only.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        from ..services.certificate_service import update_certificate_statuses
        stats = update_certificate_statuses(db)
        return {
            "success": True,
            "message": "Certificate statuses updated",
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Failed to update certificate statuses: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update statuses: {str(e)}"
        )
