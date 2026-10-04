"""
Correction Cache API Endpoints

Provides endpoints to view and manage the intelligent correction cache.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.correction_cache import CorrectionCache
from ..services.correction_cache_service import CorrectionCacheService
from ..api.auth import get_current_user

router = APIRouter(prefix="/api/v1/corrections", tags=["corrections"])
logger = logging.getLogger("zodiac-api.corrections")


# ===== Response Models =====

class CorrectionResponse(BaseModel):
    """Response model for a single correction"""
    id: str
    customer_id: str
    customer_name: Optional[str]
    error_type: str
    error_signature: str
    correction_type: str
    transformation_rule: dict
    success_count: int
    failure_count: int
    success_rate: float
    is_active: bool
    created_at: str
    last_used_at: Optional[str]
    ai_model_used: Optional[str]

    class Config:
        from_attributes = True


class CorrectionStatsResponse(BaseModel):
    """Response model for correction statistics"""
    total_corrections: int
    active_corrections: int
    inactive_corrections: int
    total_successful_applications: int
    top_customers: List[dict]
    top_error_types: List[dict]


class CorrectionListResponse(BaseModel):
    """Response model for list of corrections"""
    corrections: List[CorrectionResponse]
    total_count: int
    page: int
    page_size: int


# ===== Endpoints =====

@router.get("/stats", response_model=CorrectionStatsResponse)
async def get_correction_stats(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get overall correction cache statistics.
    
    Returns:
        - Total number of corrections
        - Active vs inactive corrections
        - Total successful applications
        - Top customers by corrections
        - Top error types
    """
    logger.info(f"📊 Fetching correction stats for user {current_user.id}")
    
    try:
        cache_service = CorrectionCacheService(db)
        stats = cache_service.get_correction_stats()
        
        # Get top customers
        top_customers_query = db.query(
            CorrectionCache.customer_id,
            CorrectionCache.customer_name
        ).filter(
            CorrectionCache.is_active == True
        ).group_by(
            CorrectionCache.customer_id,
            CorrectionCache.customer_name
        ).limit(10).all()
        
        top_customers = [
            {"customer_id": c[0], "customer_name": c[1] or "Unknown"}
            for c in top_customers_query
        ]
        
        # Get top error types
        top_errors_query = db.query(
            CorrectionCache.error_type
        ).filter(
            CorrectionCache.is_active == True
        ).group_by(
            CorrectionCache.error_type
        ).limit(10).all()
        
        top_error_types = [
            {"error_type": e[0]}
            for e in top_errors_query
        ]
        
        stats["top_customers"] = top_customers
        stats["top_error_types"] = top_error_types
        
        logger.info(f"✅ Stats retrieved: {stats['active_corrections']} active corrections")
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching statistics: {str(e)}")


@router.get("/", response_model=CorrectionListResponse)
async def list_corrections(
    customer_id: Optional[str] = Query(None, description="Filter by customer ID"),
    error_type: Optional[str] = Query(None, description="Filter by error type"),
    correction_type: Optional[str] = Query(None, description="Filter by correction type (XML/EDI)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all corrections with optional filtering and pagination.
    
    Query Parameters:
        - customer_id: Filter by customer
        - error_type: Filter by error type
        - correction_type: Filter by XML or EDI
        - is_active: Filter by active status
        - page: Page number (starts at 1)
        - page_size: Number of items per page
    """
    logger.info(f"📋 Listing corrections for user {current_user.id}")
    logger.info(f"   Filters: customer={customer_id}, error_type={error_type}, type={correction_type}, active={is_active}")
    
    try:
        # Build query
        query = db.query(CorrectionCache)
        
        if customer_id:
            query = query.filter(CorrectionCache.customer_id == customer_id)
        
        if error_type:
            query = query.filter(CorrectionCache.error_type == error_type)
        
        if correction_type:
            query = query.filter(CorrectionCache.correction_type == correction_type)
        
        if is_active is not None:
            query = query.filter(CorrectionCache.is_active == is_active)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        corrections = query.order_by(
            CorrectionCache.success_count.desc()
        ).offset(offset).limit(page_size).all()
        
        # Convert to response format
        correction_list = [
            CorrectionResponse(
                id=str(c.id),
                customer_id=c.customer_id,
                customer_name=c.customer_name,
                error_type=c.error_type,
                error_signature=c.error_signature,
                correction_type=c.correction_type,
                transformation_rule=c.transformation_rule,
                success_count=c.success_count,
                failure_count=c.failure_count,
                success_rate=c.get_success_rate(),
                is_active=c.is_active,
                created_at=c.created_at.isoformat() if c.created_at else "",
                last_used_at=c.last_used_at.isoformat() if c.last_used_at else None,
                ai_model_used=c.ai_model_used
            )
            for c in corrections
        ]
        
        logger.info(f"✅ Found {total_count} corrections, returning page {page}/{(total_count + page_size - 1) // page_size}")
        
        return CorrectionListResponse(
            corrections=correction_list,
            total_count=total_count,
            page=page,
            page_size=page_size
        )
        
    except Exception as e:
        logger.error(f"❌ Error listing corrections: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing corrections: {str(e)}")


@router.get("/customer/{customer_id}", response_model=List[CorrectionResponse])
async def get_customer_corrections(
    customer_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all corrections for a specific customer.
    
    Args:
        customer_id: Customer identifier
    
    Returns:
        List of all active corrections for this customer
    """
    logger.info(f"🔍 Fetching corrections for customer: {customer_id}")
    
    try:
        cache_service = CorrectionCacheService(db)
        corrections = cache_service.get_customer_corrections(customer_id)
        
        correction_list = [
            CorrectionResponse(
                id=str(c.id),
                customer_id=c.customer_id,
                customer_name=c.customer_name,
                error_type=c.error_type,
                error_signature=c.error_signature,
                correction_type=c.correction_type,
                transformation_rule=c.transformation_rule,
                success_count=c.success_count,
                failure_count=c.failure_count,
                success_rate=c.get_success_rate(),
                is_active=c.is_active,
                created_at=c.created_at.isoformat() if c.created_at else "",
                last_used_at=c.last_used_at.isoformat() if c.last_used_at else None,
                ai_model_used=c.ai_model_used
            )
            for c in corrections
        ]
        
        logger.info(f"✅ Found {len(correction_list)} corrections for customer {customer_id}")
        
        return correction_list
        
    except Exception as e:
        logger.error(f"❌ Error fetching customer corrections: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching customer corrections: {str(e)}")


@router.get("/{correction_id}", response_model=CorrectionResponse)
async def get_correction(
    correction_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get details of a specific correction.
    
    Args:
        correction_id: UUID of the correction
    """
    logger.info(f"🔍 Fetching correction: {correction_id}")
    
    try:
        correction = db.query(CorrectionCache).filter(
            CorrectionCache.id == correction_id
        ).first()
        
        if not correction:
            logger.warning(f"⚠️ Correction not found: {correction_id}")
            raise HTTPException(status_code=404, detail="Correction not found")
        
        return CorrectionResponse(
            id=str(correction.id),
            customer_id=correction.customer_id,
            customer_name=correction.customer_name,
            error_type=correction.error_type,
            error_signature=correction.error_signature,
            correction_type=correction.correction_type,
            transformation_rule=correction.transformation_rule,
            success_count=correction.success_count,
            failure_count=correction.failure_count,
            success_rate=correction.get_success_rate(),
            is_active=correction.is_active,
            created_at=correction.created_at.isoformat() if correction.created_at else "",
            last_used_at=correction.last_used_at.isoformat() if correction.last_used_at else None,
            ai_model_used=correction.ai_model_used
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching correction: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching correction: {str(e)}")


@router.patch("/{correction_id}/toggle")
async def toggle_correction(
    correction_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Toggle a correction's active status (enable/disable).
    
    Args:
        correction_id: UUID of the correction
    """
    logger.info(f"🔄 Toggling correction: {correction_id}")
    
    try:
        correction = db.query(CorrectionCache).filter(
            CorrectionCache.id == correction_id
        ).first()
        
        if not correction:
            raise HTTPException(status_code=404, detail="Correction not found")
        
        # Toggle active status
        correction.is_active = not correction.is_active
        db.commit()
        
        logger.info(f"✅ Correction {correction_id} is now {'active' if correction.is_active else 'inactive'}")
        
        return {
            "success": True,
            "correction_id": str(correction.id),
            "is_active": correction.is_active,
            "message": f"Correction {'activated' if correction.is_active else 'deactivated'} successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error toggling correction: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error toggling correction: {str(e)}")


@router.delete("/{correction_id}")
async def delete_correction(
    correction_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a correction from the cache.
    
    Args:
        correction_id: UUID of the correction
    """
    logger.info(f"🗑️ Deleting correction: {correction_id}")
    
    try:
        correction = db.query(CorrectionCache).filter(
            CorrectionCache.id == correction_id
        ).first()
        
        if not correction:
            raise HTTPException(status_code=404, detail="Correction not found")
        
        db.delete(correction)
        db.commit()
        
        logger.info(f"✅ Correction {correction_id} deleted successfully")
        
        return {
            "success": True,
            "correction_id": correction_id,
            "message": "Correction deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting correction: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting correction: {str(e)}")

