"""
SAT Supplier Account Mapping API
Admin endpoints for managing supplier RFC → SAP account mappings
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.models.user import ZodiacUser
from app.models.sat_supplier_account_mapping import SATSupplierAccountMapping
from app.services.sat_supplier_mapping_service import SATSupplierMappingService
from ..api.auth import get_current_user

router = APIRouter(prefix="/sat/supplier-mapping", tags=["SAT Supplier Mapping"])


# ============= Pydantic Models =============

class SupplierMappingCreate(BaseModel):
    """Schema for creating a supplier mapping"""
    supplier_rfc: str
    sap_gl_account: str
    account_description: str
    is_active: bool = True


class SupplierMappingUpdate(BaseModel):
    """Schema for updating a supplier mapping"""
    sap_gl_account: Optional[str] = None
    account_description: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierMappingResponse(BaseModel):
    """Schema for supplier mapping response"""
    id: int
    supplier_rfc: str
    sap_gl_account: str
    account_description: str
    is_active: bool
    is_default: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class BulkUploadResponse(BaseModel):
    """Response for bulk upload"""
    status: str
    message: str
    details: dict


class MappingLookupResponse(BaseModel):
    """Response for mapping lookup"""
    sap_gl_account: str
    account_description: str
    found: bool
    original_rfc: Optional[str] = None


# ============= API Endpoints =============

@router.post("/upload-excel")
async def upload_excel_mapping_file(
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Overwrite existing mappings"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload Excel file containing Supplier RFC → SAP account mappings.
    
    **Excel file should contain columns:**
    - RFC: Supplier RFC code (12-13 chars)
    - CTA: SAP G/L account number
    - CTAS: Account description
    - IS_ACTIVE: Yes/No (optional, defaults to Yes)
    
    **Example:**
    | RFC          | CTA    | CTAS                               | IS_ACTIVE |
    |--------------|--------|------------------------------------|-----------|
    | ABC123456789 | 210100 | Proveedores Nacionales - Materias  | Yes       |
    | XYZ987654321 | 210200 | Proveedores Extranjeros - Servicios| Yes       |
    """
    try:
        # Validate file type
        if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Please upload an Excel file (.xlsx, .xls) or CSV"
            )
        
        # Read file content
        content = await file.read()
        
        # Initialize service
        service = SATSupplierMappingService(db)
        
        # Parse Excel file
        mappings = service.parse_excel_mapping_file(content)
        
        if not mappings:
            raise HTTPException(
                status_code=400,
                detail="No valid mappings found in Excel file. Please check the format."
            )
        
        # Bulk upsert mappings
        result = service.bulk_upsert_mappings(mappings, overwrite=overwrite)
        
        return {
            "status": "success",
            "message": f"Uploaded {result['inserted'] + result['updated']} supplier mappings",
            "details": result
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("")
async def list_supplier_mappings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by RFC, account, or description"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all supplier account mappings with pagination and search.
    """
    service = SATSupplierMappingService(db)
    result = service.get_all_mappings(skip=skip, limit=limit, search=search)
    
    return {
        "total": result['total'],
        "skip": skip,
        "limit": limit,
        "mappings": result['mappings']
    }


@router.get("/stats/summary")
async def get_mapping_stats(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about supplier mappings.
    """
    service = SATSupplierMappingService(db)
    return service.get_mapping_stats()


@router.get("/{mapping_id}")
async def get_supplier_mapping(
    mapping_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific supplier mapping by ID.
    """
    mapping = db.query(SATSupplierAccountMapping).filter(
        SATSupplierAccountMapping.id == mapping_id
    ).first()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    return mapping.to_dict()


@router.post("", response_model=SupplierMappingResponse)
async def create_supplier_mapping(
    mapping: SupplierMappingCreate,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new supplier account mapping.
    """
    # Check if mapping already exists
    existing = db.query(SATSupplierAccountMapping).filter(
        SATSupplierAccountMapping.supplier_rfc == mapping.supplier_rfc.upper()
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Mapping for RFC {mapping.supplier_rfc} already exists"
        )
    
    # Create new mapping
    new_mapping = SATSupplierAccountMapping(
        supplier_rfc=mapping.supplier_rfc.upper(),
        sap_gl_account=mapping.sap_gl_account,
        account_description=mapping.account_description,
        is_active=mapping.is_active
    )
    
    db.add(new_mapping)
    db.commit()
    db.refresh(new_mapping)
    
    return SupplierMappingResponse(**new_mapping.to_dict())


@router.put("/{mapping_id}")
async def update_supplier_mapping(
    mapping_id: int,
    mapping_update: SupplierMappingUpdate,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an existing supplier account mapping.
    """
    existing = db.query(SATSupplierAccountMapping).filter(
        SATSupplierAccountMapping.id == mapping_id
    ).first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    # Update fields
    update_data = mapping_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    db.commit()
    db.refresh(existing)
    
    return existing.to_dict()


@router.delete("/{mapping_id}")
async def delete_supplier_mapping(
    mapping_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a supplier account mapping.
    """
    mapping = db.query(SATSupplierAccountMapping).filter(
        SATSupplierAccountMapping.id == mapping_id
    ).first()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    # Don't allow deleting default mapping
    if mapping.is_default:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete default mapping"
        )
    
    db.delete(mapping)
    db.commit()
    
    return {"status": "success", "message": "Mapping deleted"}


@router.get("/lookup/{supplier_rfc}", response_model=MappingLookupResponse)
async def lookup_supplier_account(
    supplier_rfc: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lookup SAP G/L account for a supplier RFC.
    Returns default mapping if no match found.
    """
    service = SATSupplierMappingService(db)
    result = service.lookup_gl_account(supplier_rfc)
    
    return MappingLookupResponse(**result)

