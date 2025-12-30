"""
SAT Document API Endpoints
Handles intake, retrieval, and management of Mexican CFDI documents
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import logging

from ..database import get_db
from ..api.auth import get_current_user
from ..models.user import ZodiacUser
from ..services.sat_processor import SATDocumentProcessor

logger = logging.getLogger("zodiac-api.sat")

router = APIRouter(prefix="/sat", tags=["SAT Documents"])


class CFDIIntakeRequest(BaseModel):
    xml_content: str


class CFDIIntakeResponse(BaseModel):
    success: bool
    status: str
    document_id: Optional[str] = None
    portal_ref_id: Optional[str] = None
    cfdi_uuid: Optional[str] = None
    doc_type: Optional[str] = None
    supplier_rfc: Optional[str] = None
    total: Optional[str] = None
    currency: Optional[str] = None
    error: Optional[str] = None


@router.post("/intake", response_model=CFDIIntakeResponse)
async def intake_cfdi_document(
    request: CFDIIntakeRequest,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Intake a CFDI XML document.
    Validates, parses, and stores the document.
    """
    try:
        processor = SATDocumentProcessor(db)
        result = processor.process_cfdi_document(
            user_id=current_user.id,
            xml_content=request.xml_content
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get('error', 'Failed to process CFDI document')
            )
        
        return CFDIIntakeResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ CFDI intake failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process CFDI document: {str(e)}"
        )


@router.get("/documents")
async def list_sat_documents(
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[int] = None,
    doc_type: Optional[str] = None,
status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List SAT documents with optional filters.
    """
    try:
        processor = SATDocumentProcessor(db)
        result = processor.list_documents(
            user_id=current_user.id,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            doc_type=doc_type,
            status=status_filter,
            skip=skip,
            limit=limit
        )
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to list documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {str(e)}"
        )


@router.get("/documents/{document_id}")
async def get_sat_document(
    document_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific SAT document by ID.
    """
    try:
        processor = SATDocumentProcessor(db)
        document = processor.get_document_by_id(current_user.id, document_id)
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        return {
            "id": str(document.id),
            "portal_ref_id": document.portal_ref_id,
            "cfdi_uuid": document.cfdi_uuid,
            "doc_type": document.doc_type,
            "supplier_rfc": document.supplier_rfc,
            "supplier_name": document.supplier_name,
            "receiver_rfc": document.receiver_rfc,
            "receiver_name": document.receiver_name,
            "serie": document.serie,
            "folio": document.folio,
            "fecha": document.fecha.isoformat() if document.fecha else None,
            "subtotal": document.subtotal,
            "total": document.total,
            "moneda": document.moneda,
            "tipo_cambio": document.tipo_cambio,
            "forma_pago": document.forma_pago,
            "metodo_pago": document.metodo_pago,
            "related_cfdi_uuid": document.related_cfdi_uuid,
            "status": document.status,
            "fiscal_year": document.fiscal_year,
            "fiscal_period": document.fiscal_period,
            "received_at": document.received_at.isoformat() if document.received_at else None,
            "sap_document_number": document.sap_document_number,
            "sent_to_sap_at": document.sent_to_sap_at.isoformat() if document.sent_to_sap_at else None,
            "canonical_merged_id": str(document.canonical_merged_id) if document.canonical_merged_id else None,
            "merged_at": document.merged_at.isoformat() if document.merged_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}"
        )


@router.get("/documents/{document_id}/xml")
async def get_document_xml(
    document_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the original XML content of a SAT document.
    """
    try:
        processor = SATDocumentProcessor(db)
        document = processor.get_document_by_id(current_user.id, document_id)
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        if not document.xml_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="XML content not available"
            )
        
        return Response(
            content=document.xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="cfdi_{document.cfdi_uuid}.xml"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get document XML: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document XML: {str(e)}"
        )

