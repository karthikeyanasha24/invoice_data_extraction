"""
API Key Authentication Middleware
Handles API key validation for API-based requests
"""

import os
import logging
from typing import Optional
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.user import ZodiacUser, verify_api_key, decode_api_key_from_transport

logger = logging.getLogger(__name__)

# Security scheme for API key authentication
security = HTTPBearer()

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request"""
    # Check for forwarded headers first (for reverse proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP if multiple are present
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct connection IP
    if hasattr(request, "client") and request.client:
        return request.client.host
    
    return "unknown"

def validate_ip_whitelist(user_ip: str, allow_list: Optional[list]) -> bool:
    """Validate if user IP is in the allow list"""
    if not allow_list or len(allow_list) == 0:
        # No whitelist means all IPs are allowed
        return True
    
    return user_ip in allow_list

async def get_api_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    request: Request = None
) -> ZodiacUser:
    """
    Authenticate user using API key
    This function validates the API key and returns the authenticated user
    """
    try:
        # Extract API key from Authorization header
        api_key_encoded = credentials.credentials
        
        # Decode the API key
        api_key = decode_api_key_from_transport(api_key_encoded)
        if not api_key:
            logger.warning("❌ Invalid API key format")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key format"
            )
        
        # Get client IP
        client_ip = get_client_ip(request) if request else "unknown"
        logger.info(f"🔑 API key authentication attempt from IP: {client_ip}")
        
        # Find user by API key hash
        # We need to check all users since we can't reverse the hash
        users = db.query(ZodiacUser).filter(
            ZodiacUser.api_key_hashed.isnot(None),
            ZodiacUser.api_user_allowed == True
        ).all()
        
        authenticated_user = None
        for user in users:
            if verify_api_key(api_key, user.api_key_hashed):
                authenticated_user = user
                break
        
        if not authenticated_user:
            logger.warning(f"❌ Invalid API key from IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )
        
        # Check if API key is deactivated
        if authenticated_user.api_key_deactivated_at:
            logger.warning(f"❌ Deactivated API key used from IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key is deactivated"
            )
        
        # Check IP whitelist
        if not validate_ip_whitelist(client_ip, authenticated_user.api_key_allow_list):
            logger.warning(f"❌ IP {client_ip} not in allow list for user {authenticated_user.id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="IP address not allowed"
            )
        
        # Check if user is active
        if not authenticated_user.is_active:
            logger.warning(f"❌ Inactive user attempted API access: {authenticated_user.id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive"
            )
        
        logger.info(f"✅ API key authentication successful for user {authenticated_user.id} from IP: {client_ip}")
        
        return authenticated_user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ API key authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )

async def get_api_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
    request: Request = None
) -> Optional[ZodiacUser]:
    """
    Optional API key authentication
    Returns None if no credentials provided, otherwise validates the API key
    Distinguishes between JWT tokens and API keys
    """
    if not credentials:
        return None
    
    try:
        # Check if this looks like a JWT token (starts with eyJ)
        token = credentials.credentials
        if token.startswith('eyJ'):
            # This is a JWT token, not an API key - return None to allow JWT auth
            logger.debug("🔍 JWT token detected, skipping API key validation")
            return None
        
        # This looks like an API key, try to validate it
        return await get_api_user(credentials, db, request)
    except HTTPException:
        # Re-raise authentication errors
        raise
    except Exception as e:
        logger.error(f"❌ Optional API key authentication error: {e}")
        return None

def require_api_key():
    """
    Dependency that requires API key authentication
    Use this for API endpoints that should only be accessible via API key
    """
    return Depends(get_api_user)

def optional_api_key():
    """
    Dependency that allows optional API key authentication
    Use this for endpoints that can work with both web and API authentication
    """
    return Depends(get_api_user_optional)

