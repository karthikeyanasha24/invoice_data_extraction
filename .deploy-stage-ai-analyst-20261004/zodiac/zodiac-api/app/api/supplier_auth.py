"""
Supplier Token Authentication Middleware
Handles API token validation for supplier CFDI document submission.
"""
import logging
from typing import Optional
from fastapi import HTTPException, status, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..models.supplier_token import SupplierToken
from ..models.user import verify_api_key

logger = logging.getLogger("zodiac-api.supplier_auth")

# Security scheme for Bearer token
security = HTTPBearer(auto_error=False)

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request"""
    # Check for forwarded headers first (for reverse proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct connection IP
    if hasattr(request, "client") and request.client:
        return request.client.host
    
    return "unknown"

def validate_ip_whitelist(client_ip: str, whitelist: Optional[list]) -> bool:
    """Validate if client IP is in the whitelist"""
    if not whitelist or len(whitelist) == 0:
        # No whitelist means all IPs are allowed
        return True
    
    return client_ip in whitelist

async def get_supplier_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_supplier_token: Optional[str] = Header(None, alias="X-Supplier-Token"),
    db: Session = Depends(get_db)
) -> SupplierToken:
    """
    Authenticate supplier using token from header.
    Supports both X-Supplier-Token header and Bearer token.
    """
    try:
        # Try to get token from X-Supplier-Token header first
        token = x_supplier_token
        
        # If not found, try Bearer token
        if not token and credentials:
            token = credentials.credentials
        
        if not token:
            logger.warning("❌ No supplier token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Supplier token is required. Provide X-Supplier-Token header or Authorization: Bearer token."
            )
        
        # Get client IP for logging and whitelist check
        client_ip = get_client_ip(request)
        logger.info(f"🔑 Supplier token authentication attempt from IP: {client_ip}")
        
        # Find token in database (using plain token for quick lookup)
        supplier_token = db.query(SupplierToken).filter(
            SupplierToken.token == token,
            SupplierToken.is_active == True
        ).first()
        
        if not supplier_token:
            logger.warning(f"❌ Invalid supplier token from IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive supplier token"
            )
        
        # Validate token hash (double security check)
        if not verify_api_key(token, supplier_token.token_hash):
            logger.warning(f"❌ Token hash validation failed for RFC: {supplier_token.supplier_rfc}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token validation failed"
            )
        
        # Check if token is expired
        if supplier_token.expires_at and supplier_token.expires_at < datetime.utcnow():
            logger.warning(f"❌ Expired token used by RFC: {supplier_token.supplier_rfc}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Supplier token has expired. Please contact administrator for a new token."
            )
        
        # Check IP whitelist
        if not validate_ip_whitelist(client_ip, supplier_token.ip_whitelist):
            logger.warning(f"❌ IP {client_ip} not whitelisted for RFC: {supplier_token.supplier_rfc}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="IP address not authorized for this supplier token"
            )
        
        # Update last used timestamp
        supplier_token.last_used_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"✅ Supplier token authenticated: RFC={supplier_token.supplier_rfc}, IP={client_ip}")
        
        return supplier_token
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Supplier token authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )

async def get_supplier_token_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    x_supplier_token: Optional[str] = Header(None, alias="X-Supplier-Token"),
    db: Session = Depends(get_db)
) -> Optional[SupplierToken]:
    """
    Optional supplier token authentication.
    Returns None if no token provided, otherwise validates token.
    """
    if not x_supplier_token and not credentials:
        return None
    
    try:
        return await get_supplier_token(request, credentials, x_supplier_token, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Optional supplier token authentication error: {e}")
        return None
