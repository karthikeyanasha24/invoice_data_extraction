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
    Deactivates the old token and creates a new one.
    """
    try:
        old_token = db.query(SupplierToken).filter(SupplierToken.id == token_id).first()
        
        if not old_token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found"
            )
        
        # Deactivate old token
        old_token.is_active = False
        
        # Generate new token
        new_token_value = generate_api_key()
        new_token_hash = hash_api_key(new_token_value)
        
        # Calculate new expiration (same duration as original)
        expires_at = None
        if old_token.expires_at:
            # Extend by same duration from now
            original_duration = (old_token.expires_at - old_token.created_at).days
            expires_at = datetime.utcnow() + timedelta(days=original_duration)
        
        # Create new token record
        new_token = SupplierToken(
            supplier_rfc=old_token.supplier_rfc,
            supplier_name=old_token.supplier_name,
            token=new_token_value,
            token_hash=new_token_hash,
            is_active=True,
            expires_at=expires_at,
            created_by=current_user.id,
            ip_whitelist=old_token.ip_whitelist,
            notes=old_token.notes
        )
        
        db.add(new_token)
        db.commit()
        db.refresh(new_token)
        
        logger.info(f"✅ Refreshed supplier token for {old_token.supplier_rfc} by admin {current_user.id}")
        
        return GenerateTokenResponse(
            success=True,
            token=new_token_value,  # Return new plain token (only time it's shown!)
            supplier_rfc=new_token.supplier_rfc,
            supplier_name=new_token.supplier_name,
            expires_at=new_token.expires_at,
            message="New token generated successfully. Save this token securely - it will not be shown again!"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to refresh token: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh token"
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
