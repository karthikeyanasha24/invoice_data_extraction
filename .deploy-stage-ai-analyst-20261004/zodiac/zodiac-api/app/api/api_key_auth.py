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
        logger.info(f"🔑 ===== API KEY AUTHENTICATION START =====")
        
        # Extract API key from Authorization header
        api_key_encoded = credentials.credentials
        logger.info(f"   Encoded API key length: {len(api_key_encoded)} characters")
        logger.info(f"   Encoded API key (first 20 chars): {api_key_encoded[:20]}...")
        
        # Decode the API key
        api_key = decode_api_key_from_transport(api_key_encoded)
        if not api_key:
            logger.error("❌ API KEY DECODE FAILED")
            logger.error(f"   Invalid API key format - could not decode")
            logger.error(f"   This typically means the API key is not properly base64 encoded")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "Invalid API key format",
                    "message": "API key could not be decoded. Ensure it is properly base64 encoded.",
                    "hint": "Check that you're using the exact API key from the generation response"
                }
            )
        
        logger.info(f"   ✅ API key decoded successfully")
        
        # Get client IP
        client_ip = get_client_ip(request) if request else "unknown"
        logger.info(f"   Client IP: {client_ip}")
        
        # Log request headers for debugging
        if request:
            logger.info(f"   X-Forwarded-For: {request.headers.get('X-Forwarded-For', 'not set')}")
            logger.info(f"   X-Real-IP: {request.headers.get('X-Real-IP', 'not set')}")
            logger.info(f"   User-Agent: {request.headers.get('User-Agent', 'not set')}")
        
        logger.info(f"🔍 Searching for matching API key in database...")
        
        # Find user by API key hash
        # We need to check all users since we can't reverse the hash
        users = db.query(ZodiacUser).filter(
            ZodiacUser.api_key_hashed.isnot(None),
            ZodiacUser.api_user_allowed == True
        ).all()
        
        logger.info(f"   Found {len(users)} users with API keys to check")
        
        authenticated_user = None
        for user in users:
            if verify_api_key(api_key, user.api_key_hashed):
                authenticated_user = user
                logger.info(f"   ✅ API key matched for user ID: {user.id}")
                break
        
        if not authenticated_user:
            logger.error(f"❌ API KEY NOT FOUND IN DATABASE")
            logger.error(f"   IP: {client_ip}")
            logger.error(f"   Checked {len(users)} users with API keys")
            logger.error(f"   No matching API key found")
            logger.error(f"   Possible causes:")
            logger.error(f"     1. API key was regenerated and old key is being used")
            logger.error(f"     2. API key was never generated for this user")
            logger.error(f"     3. API key format is incorrect")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "Invalid API key",
                    "message": "API key not found or invalid",
                    "hint": "Verify you're using the latest API key. If recently regenerated, use the new key."
                }
            )
        
        # Check if API key is deactivated
        logger.info(f"🔍 Checking if API key is active...")
        if authenticated_user.api_key_deactivated_at:
            logger.error(f"❌ API KEY IS DEACTIVATED")
            logger.error(f"   User ID: {authenticated_user.id}")
            logger.error(f"   IP: {client_ip}")
            logger.error(f"   Deactivated at: {authenticated_user.api_key_deactivated_at}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "API key is deactivated",
                    "message": "This API key has been deactivated and can no longer be used",
                    "deactivated_at": authenticated_user.api_key_deactivated_at.isoformat(),
                    "action": "Contact administrator to reactivate or generate a new API key"
                }
            )
        logger.info(f"   ✅ API key is active")
        
        # Check IP whitelist
        logger.info(f"🔍 Checking IP whitelist...")
        allow_list = authenticated_user.api_key_allow_list
        logger.info(f"   Configured allow list: {allow_list if allow_list else 'None (all IPs allowed)'}")
        logger.info(f"   Client IP: {client_ip}")
        
        if not validate_ip_whitelist(client_ip, allow_list):
            logger.error(f"❌ IP ADDRESS NOT IN WHITELIST")
            logger.error(f"   User ID: {authenticated_user.id}")
            logger.error(f"   Client IP: {client_ip}")
            logger.error(f"   Allowed IPs: {allow_list}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "IP address not allowed",
                    "message": f"IP address {client_ip} is not in the whitelist for this API key",
                    "client_ip": client_ip,
                    "action": "Add this IP to the API key whitelist or remove whitelist restrictions"
                }
            )
        logger.info(f"   ✅ IP address is allowed")
        
        # Check if user is active
        logger.info(f"🔍 Checking user account status...")
        if not authenticated_user.is_active:
            logger.error(f"❌ USER ACCOUNT IS INACTIVE")
            logger.error(f"   User ID: {authenticated_user.id}")
            logger.error(f"   IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "User account is inactive",
                    "message": "This user account has been deactivated",
                    "action": "Contact administrator to reactivate account"
                }
            )
        logger.info(f"   ✅ User account is active")
        
        logger.info(f"✅✅✅ API KEY AUTHENTICATION SUCCESSFUL!")
        logger.info(f"   User ID: {authenticated_user.id}")
        logger.info(f"   Username: {authenticated_user.username}")
        logger.info(f"   Email: {authenticated_user.email}")
        logger.info(f"   IP: {client_ip}")
        logger.info(f"🔑 ===== API KEY AUTHENTICATION END =====")
        
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

