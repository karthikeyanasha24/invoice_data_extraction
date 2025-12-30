"""
SAT Canonical Merged API Endpoints
Handles merging of SAT documents into canonical format
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging

from ..database import get_db
from ..api.auth import get_current_user
from ..models.user import ZodiacUser
from ..services.sat_canonical_merge_service import SATCanonicalMergeService

logger = logging.getLogger("zodiac-api.sat_canonical")

router = APIRouter(prefix="/sat/canonical", tags=["SAT Canonical"])


class MergeRequest(BaseModel):
    company_code: str = 'MX01'
    fiscal_year: int
    fiscal_period: int


@router.post("/merge")
async def merge_documents(
    request: MergeRequest,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Merge SAT documents for a given fiscal period into canonical format.
    Groups by vendor RFC.
    """
    try:
        merge_service = SATCanonicalMergeService(db)
        result = merge_service.merge_documents_for_period(
            user_id=current_user.id,
            company_code=request.company_code,
            fiscal_year=request.fiscal_year,
            fiscal_period=request.fiscal_period
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to merge documents: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to merge: {str(e)}"
        )


@router.get("")
async def list_canonical_documents(
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List canonical merged documents.
    """
    try:
        merge_service = SATCanonicalMergeService(db)
        result = merge_service.get_canonical_documents(
            user_id=current_user.id,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            skip=skip,
            limit=limit
        )
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to list canonical documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list canonical documents: {str(e)}"
        )


@router.get("/{canonical_id}")
async def get_canonical_document(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific canonical merged document.
    """
    try:
        merge_service = SATCanonicalMergeService(db)
        canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
        
        if not canonical:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical document not found"
            )
        
        return {
            "id": str(canonical.id),
            "vendor_rfc": canonical.vendor_rfc,
            "vendor_name": canonical.vendor_name,
            "company_code": canonical.company_code,
            "fiscal_year": canonical.fiscal_year,
            "fiscal_period": canonical.fiscal_period,
            "total_invoices": float(canonical.total_invoices or 0),
            "total_credits": float(canonical.total_credits or 0),
            "total_payments": float(canonical.total_payments or 0),
            "net_amount": float(canonical.net_amount or 0),
            "currency": canonical.currency,
            "payment_method": canonical.payment_method,
            "cfdi_uuids": canonical.cfdi_uuids,
            "related_cfdi_uuids": canonical.related_cfdi_uuids,
            "linked_document_ids": canonical.linked_document_ids,
            "sap_gl_account": canonical.sap_gl_account,
            "status": canonical.status,
            "sap_document_number": canonical.sap_document_number,
            "sent_to_sap_at": canonical.sent_to_sap_at.isoformat() if canonical.sent_to_sap_at else None,
            "created_at": canonical.created_at.isoformat() if canonical.created_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get canonical document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get canonical document: {str(e)}"
        )


@router.get("/{canonical_id}/preview-sap-json")
async def preview_sap_json(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate and return the SAP JSON payload for preview before sending.
    """
    try:
        merge_service = SATCanonicalMergeService(db)
        canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
        
        if not canonical:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical document not found"
            )
        
        # Build JSON payload for SAP
        sap_payload = {
            "COMPANY_CODE": canonical.company_code or 'MX01',
            "VENDOR_RFC": canonical.vendor_rfc,
            "VENDOR_NAME": canonical.vendor_name or '',
            "FISCAL_YEAR": canonical.fiscal_year,
            "FISCAL_PERIOD": canonical.fiscal_period,
            "CURRENCY": canonical.currency or 'MXN',
            "TOTAL_INVOICES": float(canonical.total_invoices or 0),
            "TOTAL_CREDITS": float(canonical.total_credits or 0),
            "TOTAL_PAYMENTS": float(canonical.total_payments or 0),
            "NET_AMOUNT": float(canonical.net_amount or 0),
            "GL_ACCOUNT": canonical.sap_gl_account or 'NO MAPPING',
            "PAYMENT_METHOD": canonical.payment_method or 'PPD',
            "CFDI_UUIDS": canonical.cfdi_uuids or [],
            "RELATED_UUIDS": canonical.related_cfdi_uuids or [],
            "DOCUMENT_COUNT": len(canonical.linked_document_ids or []),
            "PORTAL_REF_ID": str(canonical.id)
        }
        
        return {"json_payload": sap_payload}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate preview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    """
    try:
        merge_service = SATCanonicalMergeService(db)
        canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
        
        if not canonical:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical document not found"
            )
        
        # Generate SAP XML
        from ..services.sap_transformer import SAPTransformer
        sap_transformer = SAPTransformer()
        sap_xml = sap_transformer.transform_canonical_to_sap_xml(canonical)
        
        # Mock SAP send (replace with actual SAP API call)
        import random
        from datetime import datetime
        
        canonical.sap_document_number = f"TB{random.randint(1000000, 9999999)}"
        canonical.sent_to_sap_at = datetime.utcnow()
        canonical.status = "SAP_SENT"
        canonical.sap_response = f"Mock: Document posted successfully. XML size: {len(sap_xml)} bytes"
        
        db.commit()
        db.refresh(canonical)
        
        return {
            "success": True,
            "sap_document_number": canonical.sap_document_number,
            "sent_at": canonical.sent_to_sap_at.isoformat(),
            "message": "Document sent to SAP successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to send to SAP: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send to SAP: {str(e)}"
        )

