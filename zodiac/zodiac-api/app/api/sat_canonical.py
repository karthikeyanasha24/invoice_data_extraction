"""
SAT Canonical Merged Documents API
Handles merging of 3 SAT documents into 1 canonical format for SAP
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal

from app.database import get_db
from app.models.sat_canonical_merged import SATCanonicalMerged
from app.services.sat_canonical_merge_service import SATCanonicalMergeService
from app.services.sap_transformer import SAPTransformer
from app.services.sap_api_client import SAPAPIClient
from app.api.auth import get_current_user
from app.models.user import ZodiacUser

router = APIRouter(prefix="/sat/canonical", tags=["SAT Canonical"])


# ============= Pydantic Schemas =============

class CanonicalMergeRequest(BaseModel):
    """Request to merge documents into canonical format"""
    company_code: str = "MX01"
    fiscal_year: int
    fiscal_period: int  # 1-12
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_code": "MX01",
                "fiscal_year": 2025,
                "fiscal_period": 12
            }
        }


class CanonicalDocumentResponse(BaseModel):
    """Canonical document response"""
    id: str
    company_code: str
    fiscal_year: int
    fiscal_period: int
    vendor_rfc: str
    vendor_name: Optional[str]
    doc_type: str
    doc_date: Optional[datetime]
    currency: str
    total_invoices: Decimal
    total_credits: Decimal
    total_payments: Decimal
    net_amount: Decimal
    amount_signed: Decimal
    tax_base: Optional[Decimal]
    tax_amount: Optional[Decimal]
    payment_date: Optional[datetime]
    payment_method: Optional[str]
    status: str
    sap_document_number: Optional[str]
    merged_at: Optional[datetime]
    sent_to_sap_at: Optional[datetime]
    created_at: datetime
    linked_document_ids: Optional[List[str]] = None
    
    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: str
        }
    
    @classmethod
    def from_orm(cls, obj):
        """Custom ORM conversion to handle UUID"""
        data = {
            'id': str(obj.id),  # Convert UUID to string
            'company_code': obj.company_code,
            'fiscal_year': obj.fiscal_year,
            'fiscal_period': obj.fiscal_period,
            'vendor_rfc': obj.vendor_rfc,
            'vendor_name': obj.vendor_name,
            'doc_type': obj.doc_type,
            'doc_date': obj.doc_date,
            'currency': obj.currency,
            'total_invoices': obj.total_invoices,
            'total_credits': obj.total_credits,
            'total_payments': obj.total_payments,
            'net_amount': obj.net_amount,
            'amount_signed': obj.amount_signed,
            'tax_base': obj.tax_base,
            'tax_amount': obj.tax_amount,
            'payment_date': obj.payment_date,
            'payment_method': obj.payment_method,
            'status': obj.status,
            'sap_document_number': obj.sap_document_number,
            'merged_at': obj.merged_at,
            'sent_to_sap_at': obj.sent_to_sap_at,
            'created_at': obj.created_at,
            'linked_document_ids': obj.linked_document_ids if hasattr(obj, 'linked_document_ids') else None
        }
        return cls(**data)


class CanonicalListResponse(BaseModel):
    """List of canonical documents"""
    total: int
    documents: List[CanonicalDocumentResponse]


# ============= API Endpoints =============

@router.post("/merge", response_model=CanonicalListResponse)
async def merge_to_canonical(
    request: CanonicalMergeRequest,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Merge 3 SAT documents (INVOICE, PAYMENT, CREDIT_NOTE) into 1 canonical format.
    
    Creates ONE merged document per vendor for the specified period.
    This is what gets sent to SAP.
    """
    merge_service = SATCanonicalMergeService(db)
    
    try:
        canonical_docs = merge_service.merge_documents_for_period(
            user_id=current_user.id,
            company_code=request.company_code,
            fiscal_year=request.fiscal_year,
            fiscal_period=request.fiscal_period
        )
        
        # Convert ORM objects to response models
        documents_response = [CanonicalDocumentResponse.from_orm(doc) for doc in canonical_docs]
        
        return {
            "total": len(documents_response),
            "documents": documents_response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to merge: {str(e)}")


@router.get("", response_model=CanonicalListResponse)
async def list_canonical_documents(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    company_code: Optional[str] = Query(None),
    fiscal_year: Optional[int] = Query(None),
    fiscal_period: Optional[int] = Query(None),
    vendor_rfc: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0)
):
    """
    List all canonical merged documents.
    """
    merge_service = SATCanonicalMergeService(db)
    result = merge_service.get_canonical_documents(
        user_id=current_user.id,
        company_code=company_code,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        vendor_rfc=vendor_rfc,
        status=status,
        skip=offset,
        limit=limit
    )
    
    # Convert ORM objects to response models
    documents_response = [CanonicalDocumentResponse.from_orm(doc) for doc in result["documents"]]
    
    return {
        "total": result["total"],
        "documents": documents_response
    }


@router.get("/{canonical_id}", response_model=CanonicalDocumentResponse)
async def get_canonical_document(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a single canonical document by ID.
    """
    merge_service = SATCanonicalMergeService(db)
    canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
    
    if not canonical:
        raise HTTPException(status_code=404, detail="Canonical document not found")
    
    return CanonicalDocumentResponse.from_orm(canonical)


@router.get("/{canonical_id}/preview")
async def preview_sap_payload(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Preview the SAP XML payload before sending.
    Returns the exact structure and data that will be sent to SAP.
    """
    merge_service = SATCanonicalMergeService(db)
    canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
    
    if not canonical:
        raise HTTPException(status_code=404, detail="Canonical document not found")
    
    try:
        # Transform to SAP XML
        sap_transformer = SAPTransformer()
        sap_xml = sap_transformer.transform_canonical_to_sap_xml(canonical)
        
        # Prepare summary
        summary = {
            "vendor_rfc": canonical.vendor_rfc,
            "vendor_name": canonical.vendor_name or "N/A",
            "fiscal_year": canonical.fiscal_year,
            "fiscal_period": canonical.fiscal_period,
            "total_invoices": str(canonical.total_invoices),
            "total_credits": str(canonical.total_credits),
            "total_payments": str(canonical.total_payments),
            "net_amount": str(canonical.net_amount),
            "currency": canonical.currency,
            "sap_gl_account": canonical.sap_gl_account or "N/A",
            "documents_included": len(canonical.cfdi_uuids) if canonical.cfdi_uuids else 0,
            "status": canonical.status
        }
        
        return {
            "success": True,
            "canonical_id": str(canonical.id),
            "summary": summary,
            "sap_xml": sap_xml,
            "message": "This is the format that will be sent to SAP"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate preview: {str(e)}"
        )


@router.post("/{canonical_id}/send-to-sap")
async def send_canonical_to_sap(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a canonical merged document to SAP.
    This sends ONE unified XML containing all merged data.
    """
    merge_service = SATCanonicalMergeService(db)
    canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
    
    if not canonical:
        raise HTTPException(status_code=404, detail="Canonical document not found")
    
    if canonical.status not in ['READY', 'FAILED']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send canonical document with status {canonical.status}"
        )
    
    try:
        # Transform to SAP XML
        sap_transformer = SAPTransformer()
        sap_xml = sap_transformer.transform_canonical_to_sap_xml(canonical)
        
        # Send to SAP
        sap_client = SAPAPIClient()
        response = await sap_client.send_canonical_to_sap(
            canonical=canonical,
            xml_payload=sap_xml
        )
        
        # Update status
        if response.get('success'):
            merge_service.update_status(
                user_id=current_user.id,
                canonical_id=canonical_id,
                new_status='CONFIRMED',
                sap_response=response
            )
            
            return {
                "success": True,
                "message": "Canonical document sent to SAP successfully",
                "canonical_id": str(canonical.id),
                "sap_document_number": response.get('documentNumber'),
                "sap_response": response
            }
        else:
            merge_service.update_status(
                user_id=current_user.id,
                canonical_id=canonical_id,
                new_status='FAILED',
                sap_response=response
            )
            
            raise HTTPException(
                status_code=500,
                detail=f"SAP rejected document: {response.get('error_message', 'Unknown error')}"
            )
        
    except Exception as e:
        merge_service.update_status(
            user_id=current_user.id,
            canonical_id=canonical_id,
            new_status='FAILED',
            sap_response={"error": str(e)}
        )
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send to SAP: {str(e)}"
        )


@router.delete("/{canonical_id}")
async def delete_canonical_document(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a canonical document (only if not sent to SAP).
    """
    merge_service = SATCanonicalMergeService(db)
    canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
    
    if not canonical:
        raise HTTPException(status_code=404, detail="Canonical document not found")
    
    if canonical.status in ['SENT', 'CONFIRMED']:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete canonical document that has been sent to SAP"
        )
    
    db.delete(canonical)
    db.commit()
    
    return {
        "success": True,
        "message": "Canonical document deleted"
    }

