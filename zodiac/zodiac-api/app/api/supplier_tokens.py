"""
Supplier Token Management API
Admin endpoints for managing supplier API tokens.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import logging

from ..database import get_db
from ..api.auth import get_current_user
from ..models.user import ZodiacUser, generate_api_key, hash_api_key
from ..models.supplier_token import SupplierToken

logger = logging.getLogger("zodiac-api.supplier_tokens")

router = APIRouter(prefix="/supplier-tokens", tags=["Supplier Tokens"])

# Request/Response Models

class GenerateTokenRequest(BaseModel):
    supplier_rfc: str
    supplier_name: str
    expires_in_days: Optional[int] = 365  # Default 1 year
    ip_whitelist: Optional[List[str]] = None
    notes: Optional[str] = None

class GenerateTokenResponse(BaseModel):
    success: bool
    token: str  # Plain token (shown only once!)
    supplier_rfc: str
    supplier_name: str
    expires_at: Optional[datetime]
    message: str

class SupplierTokenInfo(BaseModel):
    id: int
    supplier_rfc: str
    supplier_name: Optional[str]
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_by: Optional[int]
    has_ip_whitelist: bool
    notes: Optional[str]

class TokenListResponse(BaseModel):
    total: int
    tokens: List[SupplierTokenInfo]

class TokenStatsResponse(BaseModel):
    total_tokens: int
    active_tokens: int
    expired_tokens: int
    recently_used: int  # Used in last 7 days


# Helper function to check admin
def require_admin(current_user: ZodiacUser = Depends(get_current_user)) -> ZodiacUser:
    """Require user to be admin"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


@router.post("/generate", response_model=GenerateTokenResponse)
async def generate_supplier_token(
    req: GenerateTokenRequest,
    current_user: ZodiacUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Generate a new supplier token (Admin only).
    Returns the plain token - it will NOT be shown again!
    """
    try:
        # Check if token already exists for this RFC
        existing = db.query(SupplierToken).filter(
            SupplierToken.supplier_rfc == req.supplier_rfc.upper()
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Token already exists for RFC {req.supplier_rfc}. Use refresh endpoint to regenerate."
            )
        
        # Generate secure token
        token = generate_api_key()
        token_hash = hash_api_key(token)
        
        # Calculate expiration
        expires_at = None
        if req.expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=req.expires_in_days)
        
        # Create supplier token
        supplier_token = SupplierToken(
            supplier_rfc=req.supplier_rfc.upper(),
            supplier_name=req.supplier_name,
            token=token,
            token_hash=token_hash,
            is_active=True,
            expires_at=expires_at,
            created_by=current_user.id,
            ip_whitelist=req.ip_whitelist,
            notes=req.notes
        )
        
        db.add(supplier_token)
        db.commit()
        db.refresh(supplier_token)
        
        logger.info(f"✅ Generated supplier token for {req.supplier_rfc} by admin {current_user.id}")
        
        return GenerateTokenResponse(
            success=True,
            token=token,  # Return plain token (only time it's shown!)
            supplier_rfc=supplier_token.supplier_rfc,
            supplier_name=supplier_token.supplier_name,
            expires_at=supplier_token.expires_at,
            message="Token generated successfully. Save this token securely - it will not be shown again!"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate supplier token: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate token: {str(e)}"
        )


@router.get("/list", response_model=TokenListResponse)
async def list_supplier_tokens(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    current_user: ZodiacUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all supplier tokens (Admin only).
    Does NOT return actual token values for security.
    """
    try:
        query = db.query(SupplierToken)
        
        if active_only:
            query = query.filter(SupplierToken.is_active == True)
        
        total = query.count()
        
        tokens = query.order_by(
            SupplierToken.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return TokenListResponse(
            total=total,
            tokens=[
                SupplierTokenInfo(
                    id=t.id,
                    supplier_rfc=t.supplier_rfc,
                    supplier_name=t.supplier_name,
                    is_active=t.is_active,
                    created_at=t.created_at,
                    last_used_at=t.last_used_at,
                    expires_at=t.expires_at,
                    created_by=t.created_by,
                    has_ip_whitelist=bool(t.ip_whitelist),
                    notes=t.notes
                )
                for t in tokens
            ]
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to list supplier tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch tokens"
        )


@router.delete("/{token_id}")
async def revoke_supplier_token(
    token_id: int,
    current_user: ZodiacUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Revoke a supplier token (Admin only).
    Sets is_active to False.
    """
    try:
        token = db.query(SupplierToken).filter(SupplierToken.id == token_id).first()
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found"
            )
        
        token.is_active = False
        db.commit()
        
        logger.info(f"✅ Revoked supplier token {token_id} for RFC {token.supplier_rfc} by admin {current_user.id}")
        
        return {
            "success": True,
            "message": f"Token for {token.supplier_rfc} has been revoked"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to revoke token: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke token"
        )


@router.post("/{token_id}/refresh", response_model=GenerateTokenResponse)
async def refresh_supplier_token(
    token_id: int,
    current_user: ZodiacUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Generate a new token for an existing supplier (Admin only).
    Replaces the old token with a new one (in-place update).
    """
    try:
        token_record = db.query(SupplierToken).filter(SupplierToken.id == token_id).first()
        
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found"
            )
        
        # Store old values for logging
        old_rfc = token_record.supplier_rfc
        
        # Generate new token
        new_token_value = generate_api_key()
        new_token_hash = hash_api_key(new_token_value)
        
        # Calculate new expiration (same duration as original or 365 days if no expiration)
        expires_at = None
        if token_record.expires_at:
            # Extend by same duration from now
            original_duration = (token_record.expires_at - token_record.created_at).days
            expires_at = datetime.utcnow() + timedelta(days=original_duration)
        else:
            # If no expiration set, default to 365 days
            expires_at = datetime.utcnow() + timedelta(days=365)
        
        # Update the existing token record (in-place)
        token_record.token = new_token_value
        token_record.token_hash = new_token_hash
        token_record.is_active = True  # Reactivate if it was inactive
        token_record.expires_at = expires_at
        token_record.created_at = datetime.utcnow()  # Reset creation time
        token_record.last_used_at = None  # Reset last used
        # Keep supplier_rfc, supplier_name, ip_whitelist, and notes unchanged
        
        db.commit()
        db.refresh(token_record)
        
        logger.info(f"✅ Refreshed supplier token (ID: {token_id}) for {old_rfc} by admin {current_user.id}")
        
        return GenerateTokenResponse(
            success=True,
            token=new_token_value,  # Return new plain token (only time it's shown!)
            supplier_rfc=token_record.supplier_rfc,
            supplier_name=token_record.supplier_name,
            expires_at=token_record.expires_at,
            message="Token refreshed successfully. Save this token securely - it will not be shown again!"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to refresh token: {e}")
        logger.exception(e)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh token: {str(e)}"
        )


@router.get("/stats", response_model=TokenStatsResponse)
async def get_supplier_token_stats(
    current_user: ZodiacUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Get supplier token statistics (Admin only).
    """
    try:
        total = db.query(func.count(SupplierToken.id)).scalar() or 0
        active = db.query(func.count(SupplierToken.id)).filter(
            SupplierToken.is_active == True
        ).scalar() or 0
        
        # Count expired tokens
        now = datetime.utcnow()
        expired = db.query(func.count(SupplierToken.id)).filter(
            SupplierToken.expires_at < now,
            SupplierToken.is_active == True  # Active but expired
        ).scalar() or 0
        
        # Count recently used (last 7 days)
        seven_days_ago = now - timedelta(days=7)
        recently_used = db.query(func.count(SupplierToken.id)).filter(
            SupplierToken.last_used_at >= seven_days_ago
        ).scalar() or 0
        
        return TokenStatsResponse(
            total_tokens=total,
            active_tokens=active,
            expired_tokens=expired,
            recently_used=recently_used
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to get token stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get statistics"
        )


@router.get("/retrieve")
async def retrieve_supplier_token(
    supplier_rfc: str,
    db: Session = Depends(get_db)
):
    """
    PUBLIC endpoint for suppliers to retrieve their token.
    Requires only RFC.
    
    WARNING: Anyone with the RFC can retrieve the token.
    Consider implementing additional security (IP whitelist, rate limiting) if needed.
    
    Security features:
    - Logs all retrieval attempts with timestamp
    - Checks if token is active
    - Checks if token is expired
    
    Query params:
    - supplier_rfc: Supplier's RFC (e.g., IIA040805DZ4)
    """
    try:
        # Normalize RFC
        rfc = supplier_rfc.strip().upper()
        
        logger.info(f"🔍 Token retrieval attempt for RFC: {rfc}")
        
        # Find active token by RFC
        supplier_token = db.query(SupplierToken).filter(
            SupplierToken.supplier_rfc == rfc,
            SupplierToken.is_active == True
        ).first()
        
        if not supplier_token:
            logger.warning(f"❌ No active token found for RFC: {rfc}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active token found for this RFC. Please contact administrator."
            )
        
        # Check if token is expired
        if supplier_token.expires_at and supplier_token.expires_at < datetime.utcnow():
            logger.warning(f"❌ Expired token for RFC: {rfc}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your token has expired. Please contact administrator for a new token."
            )
        
        # Update last retrieval time (for monitoring)
        supplier_token.last_used_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"✅ Token retrieved successfully for RFC: {rfc}")
        
        return {
            "success": True,
            "token": supplier_token.token,
            "supplier_rfc": supplier_token.supplier_rfc,
            "supplier_name": supplier_token.supplier_name,
            "expires_at": supplier_token.expires_at.isoformat() if supplier_token.expires_at else None,
            "message": "Token retrieved successfully. Keep this secure!"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Token retrieval error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving token. Please contact support."
        )
