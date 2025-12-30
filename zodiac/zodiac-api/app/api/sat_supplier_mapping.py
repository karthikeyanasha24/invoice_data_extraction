"""
SAT Supplier Account Mapping API Endpoints
Manages RFC to SAP G/L Account mappings
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging

from ..database import get_db
from ..api.auth import get_current_user
from ..models.user import ZodiacUser
from ..services.sat_supplier_mapping_service import SATSupplierMappingService

logger = logging.getLogger("zodiac-api.sat_supplier_mapping")

router = APIRouter(prefix="/sat/supplier-mapping", tags=["SAT Supplier Mapping"])


@router.post("/upload-excel")
async def upload_excel_mapping(
    file: UploadFile = File(...),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload Excel file with supplier RFC to G/L account mappings.
    Expected columns: RFC, CTA, CTAS, IS_ACTIVE
    """
    try:
        # Read file content
        content = await file.read()
        
        # Parse Excel
        mapping_service = SATSupplierMappingService(db)
        mappings = mapping_service.parse_excel_mapping_file(content)
        
        # Bulk upsert
        result = mapping_service.bulk_upsert_mappings(mappings)
        
        return {
            "success": True,
            "message": f"Successfully processed {len(mappings)} mappings",
            "stats": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse Excel file: {str(e)}"
        )
    except Exception as e:
        logger.error(f"❌ Failed to upload mappings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload mappings: {str(e)}"
        )


@router.get("/list")
async def list_supplier_mappings(
    active_only: bool = False,
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all supplier account mappings.
    """
    try:
        mapping_service = SATSupplierMappingService(db)
        result = mapping_service.get_all_mappings(
            active_only=active_only,
            skip=skip,
            limit=limit
        )
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to list mappings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list mappings: {str(e)}"
        )


@router.get("/lookup/{supplier_rfc}")
async def lookup_mapping(
    supplier_rfc: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lookup G/L account for a specific supplier RFC.
    """
    try:
        mapping_service = SATSupplierMappingService(db)
        mapping = mapping_service.get_mapping_by_rfc(supplier_rfc)
        
        if not mapping:
            # Return default mapping
            default = mapping_service.get_or_create_default_mapping()
            return {
                "found": False,
                "using_default": True,
                "supplier_rfc": supplier_rfc,
                "sap_gl_account": default.sap_gl_account,
                "account_description": "Default unmapped supplier account"
            }
        
        return {
            "found": True,
            "using_default": False,
            "supplier_rfc": mapping.supplier_rfc,
            "sap_gl_account": mapping.sap_gl_account,
            "account_description": mapping.account_description,
            "is_active": mapping.is_active
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to lookup mapping: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to lookup mapping: {str(e)}"
        )


@router.delete("/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a supplier account mapping.
    """
    try:
        mapping_service = SATSupplierMappingService(db)
        success = mapping_service.delete_mapping(mapping_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mapping not found"
            )
        
        return {"success": True, "message": "Mapping deleted successfully"}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete mapping: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete mapping: {str(e)}"
        )


@router.get("/stats/summary")
async def get_mapping_stats(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about supplier account mappings.
    """
    try:
        from sqlalchemy import func
        from ..models.sat_supplier_account_mapping import SATSupplierAccountMapping
        
        total = db.query(func.count(SATSupplierAccountMapping.id)).scalar() or 0
        active = db.query(func.count(SATSupplierAccountMapping.id)).filter(
            SATSupplierAccountMapping.is_active == True
        ).scalar() or 0
        inactive = total - active
        
        return {
            "total_mappings": total,
            "active_mappings": active,
            "inactive_mappings": inactive
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stats: {str(e)}"
        )

