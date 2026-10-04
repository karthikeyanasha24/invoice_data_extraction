"""
Certificate API Schemas
Request/response models for certificate lifecycle management APIs.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CertificateIssueRequest(BaseModel):
    """Request to issue a new client certificate"""
    customer_id: str = Field(..., description="Customer identifier")
    organization: Optional[str] = Field(None, description="Organization name")
    organizational_unit: Optional[str] = Field(None, description="Department/unit name")
    country: Optional[str] = Field(None, max_length=2, description="Two-letter country code (e.g., US, MX, DE)")
    email: Optional[str] = Field(None, description="Contact email")
    validity_days: int = Field(365, ge=30, le=1825, description="Certificate validity in days (30-1825)")
    notes: Optional[str] = Field(None, description="Optional notes about this certificate")


class CertificateIssueResponse(BaseModel):
    """Response after issuing a certificate"""
    success: bool
    message: str
    certificate_id: int
    customer_id: str
    serial_number: str
    fingerprint_sha256: str
    common_name: str
    issued_at: datetime
    expires_at: datetime
    p12_password: str = Field(..., description="Password for P12 file - STORE SECURELY, shown only once")
    download_url: Optional[str] = Field(None, description="One-time download URL for P12 file")


class CertificateRenewalRequest(BaseModel):
    """Request to renew a certificate"""
    validity_days: int = Field(365, ge=30, le=1825, description="New certificate validity in days")
    notes: Optional[str] = Field(None, description="Optional notes about renewal")


class CertificateRenewalResponse(BaseModel):
    """Response after renewing a certificate"""
    success: bool
    message: str
    old_certificate_id: int
    new_certificate_id: int
    customer_id: str
    serial_number: str
    fingerprint_sha256: str
    expires_at: datetime
    p12_password: str = Field(..., description="Password for new P12 file - STORE SECURELY")
    download_url: Optional[str] = Field(None, description="One-time download URL for P12 file")


class CertificateRevocationRequest(BaseModel):
    """Request to revoke a certificate"""
    reason: Optional[str] = Field(None, description="Reason for revocation")


class CertificateRevocationResponse(BaseModel):
    """Response after revoking a certificate"""
    success: bool
    message: str
    certificate_id: int
    customer_id: str
    revoked_at: datetime


class CertificateInfoResponse(BaseModel):
    """Certificate information (without private key)"""
    id: int
    customer_id: str
    certificate_type: str
    common_name: str
    organization: Optional[str]
    organizational_unit: Optional[str]
    country: Optional[str]
    email: Optional[str]
    serial_number: str
    fingerprint_sha256: str
    issued_at: datetime
    expires_at: datetime
    status: str
    revoked_at: Optional[datetime]
    revoked_by: Optional[int]
    revocation_reason: Optional[str]
    renewed_at: Optional[datetime]
    renewed_certificate_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    created_by: Optional[int]
    notes: Optional[str]
    days_until_expiry: Optional[int] = Field(None, description="Days until expiration (negative if expired)")


class CertificateListResponse(BaseModel):
    """List of certificates"""
    certificates: list[CertificateInfoResponse]
    total: int


class CertificateDownloadResponse(BaseModel):
    """Certificate download data"""
    certificate_pem: str
    ca_certificate_pem: str
    private_key_pem: Optional[str] = Field(None, description="Only included for initial download")


class CertificateStatusUpdate(BaseModel):
    """Update certificate status"""
    status: str = Field(..., description="New status: active, expiring_soon, expired, revoked")
    notes: Optional[str] = None


class RenewalRequestCreateRequest(BaseModel):
    """Create a renewal request"""
    certificate_id: int
    notes: Optional[str] = None


class RenewalRequestResponse(BaseModel):
    """Renewal request information"""
    id: int
    certificate_id: int
    customer_id: str
    request_status: str
    requested_at: datetime
    requested_by: Optional[int]
    processed_at: Optional[datetime]
    processed_by: Optional[int]
    new_certificate_id: Optional[int]
    notes: Optional[str]
    rejection_reason: Optional[str]


class RenewalRequestApprovalRequest(BaseModel):
    """Approve or reject a renewal request"""
    approved: bool
    validity_days: int = Field(365, ge=30, le=1825)
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
