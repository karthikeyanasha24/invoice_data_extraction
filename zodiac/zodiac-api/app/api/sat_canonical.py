"""
SAT Canonical Merged API Endpoints
Handles merging of SAT documents into canonical format
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
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


# =====================
# Helper Functions
# =====================

def safe_float_conversion(value, default=0.0):
    """
    Safely convert a value to float, handling comma separators and Decimal types.
    
    Args:
        value: The value to convert (string, int, float, Decimal, or None)
        default: Default value if conversion fails (default: 0.0)
    
    Returns:
        float: The converted value or default
    
    Examples:
        safe_float_conversion("1,000") -> 1000.0
        safe_float_conversion("1,000.50") -> 1000.5
        safe_float_conversion("1000") -> 1000.0
        safe_float_conversion(Decimal("100.50")) -> 100.5
        safe_float_conversion(None) -> 0.0
    """
    if value is None:
        return default
    
    # Handle numeric types (int, float, Decimal)
    if isinstance(value, (int, float)):
        return float(value)
    
    # Handle Decimal from SQLAlchemy
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
    except ImportError:
        pass
    
    # Handle string
    if isinstance(value, str):
        # Remove commas and whitespace
        cleaned = value.replace(',', '').strip()
        
        if not cleaned or cleaned == '':
            return default
        
        try:
            return float(cleaned)
        except ValueError:
            logger.warning(f"Could not convert '{value}' to float, using default {default}")
            return default
    
    # Try to convert any other type
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(f"Could not convert '{value}' (type: {type(value)}) to float, using default {default}")
        return default


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
            "total_invoices": safe_float_conversion(canonical.total_invoices, 0.0),
            "total_credits": safe_float_conversion(canonical.total_credits, 0.0),
            "total_payments": safe_float_conversion(canonical.total_payments, 0.0),
            "net_amount": safe_float_conversion(canonical.net_amount, 0.0),
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
        
        # Fetch linked documents to get detailed CFDI information with types
        cfdi_details = []
        if canonical.linked_document_ids:
            from ..models.sat_document import SATDocument
            linked_docs = db.query(SATDocument).filter(
                SATDocument.id.in_([str(doc_id) for doc_id in canonical.linked_document_ids])
            ).all()
            
            # Build detailed CFDI list with types
            for doc in linked_docs:
                cfdi_details.append({
                    "uuid": doc.cfdi_uuid,
                    "type": doc.doc_type,
                    "total": safe_float_conversion(doc.total, 0.0),
                    "currency": doc.moneda or 'MXN',
                    "date": doc.fecha.isoformat() if doc.fecha else None
                })
        
        # Build JSON payload for SAP
        sap_payload = {
            "COMPANY_CODE": canonical.company_code or 'MX01',
            "VENDOR_RFC": canonical.vendor_rfc,
            "VENDOR_NAME": canonical.vendor_name or '',
            "FISCAL_YEAR": canonical.fiscal_year,
            "FISCAL_PERIOD": canonical.fiscal_period,
            "CURRENCY": canonical.currency or 'MXN',
            "TOTAL_INVOICES": safe_float_conversion(canonical.total_invoices, 0.0),
            "TOTAL_CREDITS": safe_float_conversion(canonical.total_credits, 0.0),
            "TOTAL_PAYMENTS": safe_float_conversion(canonical.total_payments, 0.0),
            "NET_AMOUNT": safe_float_conversion(canonical.net_amount, 0.0),
            "GL_ACCOUNT": canonical.sap_gl_account or 'NO MAPPING',
            "PAYMENT_METHOD": canonical.payment_method or 'PPD',
            "CFDI_UUIDS": canonical.cfdi_uuids or [],  # Keep for backward compatibility
            "CFDI_DETAILS": cfdi_details,  # NEW: Detailed info with types
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
    Uses real SAP endpoint provided by client.
    """
    try:
        from ..services.sap_api_client import sap_client
        from datetime import datetime
        
        merge_service = SATCanonicalMergeService(db)
        canonical = merge_service.get_canonical_by_id(current_user.id, canonical_id)
        
        if not canonical:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical document not found"
            )
        
        # Check if already sent
        if canonical.status == "SAP_SENT" or canonical.sap_document_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document already sent to SAP. SAP Doc #: {canonical.sap_document_number}"
            )
        
        logger.info(f"📤 Sending canonical document {canonical_id} to SAP...")
        
        # Fetch linked documents to get CFDI details
        cfdi_details = []
        if canonical.linked_document_ids:
            linked_docs = db.query(SATDocument).filter(
                SATDocument.id.in_([str(doc_id) for doc_id in canonical.linked_document_ids])
            ).all()
            
            # Build detailed CFDI list with types
            for doc in linked_docs:
                # Map document type to SAP format
                sap_doc_type = {
                    'INVOICE': 'I',
                    'CREDIT_NOTE': 'C',
                    'PAYMENT': 'P'
                }.get(doc.doc_type, 'I')
                
                cfdi_details.append({
                    'DS_UUID': doc.cfdi_uuid,
                    'DOCUMENT_TYPE': sap_doc_type,
                    'DOC_NUMBER': doc.folio or str(doc.id),
                    'TOTAL_AMOUNT': safe_float_conversion(doc.total, 0.0),
                    'CURRENCY': doc.moneda or 'MXN',
                    'ISSUER_TAX_ID': doc.supplier_rfc,
                    'ISSUER_NAME': doc.supplier_name or doc.supplier_rfc,
                    'RECEIVER_TAX_ID': doc.receiver_rfc,
                    'RECEIVER_NAME': doc.receiver_name or doc.receiver_rfc,
                })
        
        # Build JSON payload matching client's format
        sap_payload = {
            "DS_UUID": str(canonical.id),
            "DOCUMENT_TYPE": "C",  # Canonical
            "DOC_NUMBER": f"CANONICAL_{canonical.fiscal_year}_{str(canonical.fiscal_period).zfill(2)}",
            "VERSION": "4.0",
            "FISCAL_YEAR": canonical.fiscal_year,
            "FISCAL_PERIOD": canonical.fiscal_period,
            "CURRENCY": canonical.currency or 'MXN',
            "SUBTOTAL_AMOUNT": safe_float_conversion(canonical.total_invoices, 0.0),
            "TOTAL_AMOUNT": safe_float_conversion(canonical.net_amount, 0.0),
            "ISSUER_NAME": canonical.vendor_name or canonical.vendor_rfc,
            "ISSUER_TAX_ID": canonical.vendor_rfc,
            "TOTAL_INVOICES": safe_float_conversion(canonical.total_invoices, 0.0),
            "TOTAL_CREDITS": safe_float_conversion(canonical.total_credits, 0.0),
            "TOTAL_PAYMENTS": safe_float_conversion(canonical.total_payments, 0.0),
            "NET_AMOUNT": safe_float_conversion(canonical.net_amount, 0.0),
            "GL_ACCOUNT": canonical.sap_gl_account or "",
            "PAYMENT_METHOD": canonical.payment_method or "PPD",
            "ITEMS": cfdi_details  # Individual CFDIs
        }
        
        logger.info(f"   Prepared payload with {len(cfdi_details)} CFDI document(s)")
        
        # Send to SAP using the new client
        sap_response = await sap_client.send_json_to_sap(
            payload=sap_payload,
            document_type="CANONICAL",
            portal_reference=str(canonical_id)
        )
        
        if sap_response.get('success'):
            # Update document status
            canonical.sent_to_sap_at = datetime.utcnow()
            canonical.status = "SAP_SENT"
            
            # Try to extract SAP document number from response
            sap_doc_number = None
            if isinstance(sap_response.get('sap_response'), dict):
                sap_doc_number = sap_response['sap_response'].get('document_number') or sap_response['sap_response'].get('sap_document_number')
            
            # If no document number, generate a reference
            if not sap_doc_number:
                import random
                sap_doc_number = f"TB{random.randint(1000000, 9999999)}"
            
            canonical.sap_document_number = sap_doc_number
            canonical.sap_response = str(sap_response)
            
            db.commit()
            db.refresh(canonical)
            
            logger.info(f"✅ Canonical {canonical_id} sent to SAP successfully. SAP Doc #: {sap_doc_number}")
            
            return {
                "success": True,
                "sap_document_number": sap_doc_number,
                "sent_at": canonical.sent_to_sap_at.isoformat(),
                "message": "Document sent to SAP successfully",
                "sap_response": sap_response
            }
        else:
            logger.error(f"❌ Failed to send to SAP: {sap_response.get('error')}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SAP returned error: {sap_response.get('error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to send to SAP: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send to SAP: {str(e)}"
        )


@router.get("/{canonical_id}/download-xml", response_class=Response)
async def download_canonical_xml(
    canonical_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download the canonical merged document as SAP XML.
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
        sap_transformer = SAPTransformer(db)
        sap_xml = sap_transformer.transform_canonical_to_sap_xml(canonical)
        
        filename = f"canonical_merged_{canonical.vendor_rfc}_{canonical.fiscal_year}_{str(canonical.fiscal_period).zfill(2)}.xml"
        
        return Response(
            content=sap_xml,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to download canonical XML: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download XML: {str(e)}"
        )

