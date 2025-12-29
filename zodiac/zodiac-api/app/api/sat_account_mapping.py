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

class AccountMappingCreate(BaseModel):
    """Schema for creating a single account mapping"""
    clave_prod_serv: str
    sap_gl_account: str
    code_group: str
    description: Optional[str] = None
    description_en: Optional[str] = None
    account_type: Optional[str] = None
    sat_category: Optional[str] = None
    notes: Optional[str] = None


class AccountMappingUpdate(BaseModel):
    """Schema for updating an account mapping"""
    sap_gl_account: Optional[str] = None
    code_group: Optional[str] = None
    description: Optional[str] = None
    description_en: Optional[str] = None
    account_type: Optional[str] = None
    sat_category: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class AccountMappingResponse(BaseModel):
    """Schema for account mapping response"""
    id: int
    clave_prod_serv: str
    sap_gl_account: str
    code_group: str
    description: Optional[str]
    description_en: Optional[str]
    account_type: Optional[str]
    sat_category: Optional[str]
    notes: Optional[str]
    is_active: bool
    is_default: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class BulkUploadResponse(BaseModel):
    """Response for bulk upload"""
    success: bool
    message: str
    inserted: int
    updated: int
    skipped: int
    total: int


class MappingLookupResponse(BaseModel):
    """Response for mapping lookup"""
    sap_gl_account: str
    code_group: str
    description: str
    account_type: Optional[str]
    found: bool
    original_clave: Optional[str] = None


# ============= API Endpoints =============

@router.post("/upload-excel", response_model=BulkUploadResponse)
async def upload_excel_mapping_file(
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Overwrite existing mappings"),
    sheet_name: Optional[str] = Query(None, description="Excel sheet name to read"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload Excel file containing SAT-SAP account mappings.
    
    **Excel file should contain columns:**
    - ClaveProdServ (SAT product/service code)
    - GL_Account or SAP_Account (SAP G/L account number)
    - Code_Group or Group (SAT code group)
    - Description (optional)
    - Description_EN (optional)
    - Account_Type (optional)
    
    **Parameters:**
    - overwrite: If True, update existing mappings. If False, skip duplicates.
    - sheet_name: Name of the Excel sheet to read (if not provided, reads first sheet)
    """
    try:
        # Validate file type
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")
        
        # Read file content
        content = await file.read()
        
        # Parse Excel file
        mapping_service = SATAccountMappingService(db)
        mappings = mapping_service.parse_excel_mapping_file(content, sheet_name)
        
        if not mappings:
            raise HTTPException(status_code=400, detail="No valid mappings found in Excel file")
        
        # Bulk upsert mappings
        result = mapping_service.bulk_upsert_mappings(mappings, overwrite=overwrite)
        
        return BulkUploadResponse(
            success=True,
            message=f"Successfully processed {result['total']} mappings",
            inserted=result['inserted'],
            updated=result['updated'],
            skipped=result['skipped'],
            total=result['total']
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")


@router.get("", response_model=dict)
async def list_account_mappings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None, description="Search by ClaveProdServ, GL Account, or Description"),
    account_type: Optional[str] = Query(None, description="Filter by account type"),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all account mappings with pagination and filters.
    """
    mapping_service = SATAccountMappingService(db)
    result = mapping_service.get_all_mappings(
        skip=skip,
        limit=limit,
        search=search,
        account_type=account_type
    )
    
    return result


@router.get("/lookup/{clave_prod_serv}", response_model=MappingLookupResponse)
async def lookup_mapping(
    clave_prod_serv: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lookup SAP G/L account for a given ClaveProdServ code.
    Returns default mapping if not found.
    """
    mapping_service = SATAccountMappingService(db)
    result = mapping_service.map_clave_to_gl_account(clave_prod_serv)
    
    return MappingLookupResponse(**result)


@router.post("", response_model=AccountMappingResponse)
async def create_account_mapping(
    mapping: AccountMappingCreate,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new account mapping manually.
    """
    # Check if mapping already exists
    existing = db.query(SATSAPAccountMapping).filter(
        SATSAPAccountMapping.clave_prod_serv == mapping.clave_prod_serv
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Mapping for ClaveProdServ '{mapping.clave_prod_serv}' already exists"
        )
    
    new_mapping = SATSAPAccountMapping(**mapping.dict())
    db.add(new_mapping)
    db.commit()
    db.refresh(new_mapping)
    
    return AccountMappingResponse(**new_mapping.to_dict())


@router.put("/{mapping_id}", response_model=AccountMappingResponse)
async def update_account_mapping(
    mapping_id: int,
    mapping_update: AccountMappingUpdate,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an existing account mapping.
    """
    existing = db.query(SATSAPAccountMapping).filter(
        SATSAPAccountMapping.id == mapping_id
    ).first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    # Update fields
    update_data = mapping_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    db.commit()
    db.refresh(existing)
    
    return AccountMappingResponse(**existing.to_dict())


@router.delete("/{mapping_id}")
async def delete_account_mapping(
    mapping_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete an account mapping.
    """
    mapping_service = SATAccountMappingService(db)
    
    if mapping_service.delete_mapping(mapping_id):
        return {"success": True, "message": "Mapping deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Mapping not found")


@router.get("/stats/summary")
async def get_mapping_stats(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about account mappings.
    """
    total_mappings = db.query(SATSAPAccountMapping).count()
    active_mappings = db.query(SATSAPAccountMapping).filter(
        SATSAPAccountMapping.is_active == True
    ).count()
    
    # Get count by account type
    account_types = db.query(
        SATSAPAccountMapping.account_type,
        func.count(SATSAPAccountMapping.id)
    ).group_by(SATSAPAccountMapping.account_type).all()
    
    # Get count by code group
    code_groups = db.query(
        SATSAPAccountMapping.code_group,
        func.count(SATSAPAccountMapping.id)
    ).group_by(SATSAPAccountMapping.code_group).all()
    
    return {
        "total_mappings": total_mappings,
        "active_mappings": active_mappings,
        "inactive_mappings": total_mappings - active_mappings,
        "unique_code_groups": len(code_groups),
        "by_account_type": [{"type": t[0] or "Unknown", "count": t[1]} for t in account_types],
        "by_code_group": [{"group": g[0], "count": g[1]} for g in code_groups]
    }

