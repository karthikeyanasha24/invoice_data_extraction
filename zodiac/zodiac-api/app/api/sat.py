"""
SAT Document API Endpoints
Handles intake, retrieval, and management of Mexican CFDI documents
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import logging

from ..database import get_db
from ..api.auth import get_current_user
from ..api.supplier_auth import get_supplier_token
from ..models.user import ZodiacUser
from ..models.supplier_token import SupplierToken
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
    Requires user authentication (JWT token).
    """
    try:
        processor = SATDocumentProcessor(db)
        result = processor.process_cfdi_document(
            user_id=current_user.id,
            xml_content=request.xml_content,
            source='admin'  # Mark as admin upload
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


@router.post("/supplier-intake", response_model=CFDIIntakeResponse)
async def supplier_intake_cfdi_document(
    request: CFDIIntakeRequest,
    supplier_token: SupplierToken = Depends(get_supplier_token),
    db: Session = Depends(get_db)
):
    """
    Public endpoint for suppliers to submit CFDI documents (JSON method).
    Uses supplier token authentication (X-Supplier-Token header or Bearer token).
    
    Authentication: X-Supplier-Token: <token> or Authorization: Bearer <token>
    Body: {"xml_content": "<?xml version='1.0'?>..."}
    
    DEPRECATED: Use /supplier-intake-files for file upload method.
    """
    try:
        logger.info(f"📨 Supplier intake request (JSON) from RFC: {supplier_token.supplier_rfc}")
        
        processor = SATDocumentProcessor(db)
        
        # Process document linked to admin user who created the token
        result = processor.process_cfdi_document(
            user_id=supplier_token.created_by,
            xml_content=request.xml_content
        )
        
        # Validate supplier RFC in XML matches the token's RFC
        if result.get('success') and result.get('supplier_rfc'):
            xml_supplier_rfc = result['supplier_rfc']
            if xml_supplier_rfc != supplier_token.supplier_rfc:
                logger.warning(f"⚠️ RFC mismatch: Token={supplier_token.supplier_rfc}, XML={xml_supplier_rfc}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Supplier RFC mismatch. Token is for {supplier_token.supplier_rfc}, but document is from {xml_supplier_rfc}"
                )
        
        if not result['success']:
            logger.warning(f"❌ Supplier intake failed for {supplier_token.supplier_rfc}: {result.get('error')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get('error', 'Failed to process CFDI document')
            )
        
        logger.info(f"✅ Supplier intake successful for {supplier_token.supplier_rfc}: UUID={result.get('cfdi_uuid')}")
        
        return CFDIIntakeResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Supplier CFDI intake failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document processing error. Please contact support if this persists."
        )


@router.post("/supplier-intake-files")
async def supplier_intake_files(
    files: List[UploadFile] = File(...),
    supplier_token: SupplierToken = Depends(get_supplier_token),
    db: Session = Depends(get_db)
):
    """
    Public endpoint for suppliers to submit multiple CFDI XML files at once.
    Uses supplier token authentication (X-Supplier-Token header or Bearer token).
    
    Recommended method for suppliers - upload actual XML files.
    
    Authentication: X-Supplier-Token: <token> or Authorization: Bearer <token>
    Content-Type: multipart/form-data
    Body: 
      - files: Multiple XML files (e.g., invoice.xml, credit.xml, payment.xml)
    """
    try:
        logger.info(f"📨 Supplier batch intake from RFC: {supplier_token.supplier_rfc}, Files: {len(files)}")
        
        processor = SATDocumentProcessor(db)
        results = []
        
        for uploaded_file in files:
            try:
                logger.info(f"   Reading file: {uploaded_file.filename}")
                
                # Read file content
                xml_content = await uploaded_file.read()
                
                if not xml_content:
                    logger.error(f"   ❌ Empty file: {uploaded_file.filename}")
                    results.append({
                        'success': False,
                        'status': 'EMPTY_FILE',
                        'error': 'File is empty',
                        'filename': uploaded_file.filename
                    })
                    continue
                
                xml_content = xml_content.decode('utf-8')
                
                logger.info(f"   Processing file: {uploaded_file.filename} ({len(xml_content)} bytes)")
                
                # Process document (mark as supplier source)
                result = processor.process_cfdi_document(
                    user_id=supplier_token.created_by,
                    xml_content=xml_content,
                    source='supplier'  # Track as supplier upload
                )
                
                # Validate RFC matches token (normalize for comparison)
                if result.get('success') and result.get('supplier_rfc'):
                    xml_supplier_rfc = result['supplier_rfc'].strip().upper()
                    token_supplier_rfc = supplier_token.supplier_rfc.strip().upper()
                    
                    if xml_supplier_rfc != token_supplier_rfc:
                        logger.warning(f"⚠️ RFC mismatch in {uploaded_file.filename}: Token='{token_supplier_rfc}' vs XML='{xml_supplier_rfc}'")
                        result = {
                            'success': False,
                            'status': 'RFC_MISMATCH',
                            'error': f"Supplier RFC mismatch. Token is for {token_supplier_rfc}, but document is from {xml_supplier_rfc}",
                            'filename': uploaded_file.filename
                        }
                
                # Add filename to result
                result['filename'] = uploaded_file.filename
                results.append(result)
                
                if result['success']:
                    logger.info(f"   ✅ {uploaded_file.filename}: UUID={result.get('cfdi_uuid')}")
                else:
                    logger.warning(f"   ❌ {uploaded_file.filename}: {result.get('error')}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error processing {uploaded_file.filename}: {e}")
                results.append({
                    'success': False,
                    'status': 'ERROR',
                    'error': str(e),
                    'filename': uploaded_file.filename
                })
        
        # Calculate summary
        successful = len([r for r in results if r.get('success')])
        failed = len(results) - successful
        
        logger.info(f"✅ Batch complete: {successful} successful, {failed} failed out of {len(results)} files")
        
        return {
            'success': successful > 0,
            'message': f'Processed {len(results)} files: {successful} successful, {failed} failed',
            'total_files': len(results),
            'successful_count': successful,
            'failed_count': failed,
            'results': results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Supplier batch intake failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File processing error. Please contact support if this persists."
        )


@router.post("/upload-files")
async def upload_sat_files(
    files: List[UploadFile] = File(...),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload multiple CFDI XML files (admin upload).
    Similar to supplier intake but for internal/admin use.
    """
    try:
        logger.info(f"📤 Admin batch upload from user {current_user.id}, Files: {len(files)}")
        
        processor = SATDocumentProcessor(db)
        results = []
        
        for uploaded_file in files:
            try:
                # Read file content
                xml_content = await uploaded_file.read()
                xml_content = xml_content.decode('utf-8')
                
                logger.info(f"   Processing file: {uploaded_file.filename} ({len(xml_content)} bytes)")
                
                # Process document (mark as admin upload)
                result = processor.process_cfdi_document(
                    user_id=current_user.id,
                    xml_content=xml_content,
                    source='admin'  # Mark as admin upload
                )
                
                # Add filename to result
                result['filename'] = uploaded_file.filename
                results.append(result)
                
                if result['success']:
                    logger.info(f"   ✅ {uploaded_file.filename}: UUID={result.get('cfdi_uuid')}")
                else:
                    logger.warning(f"   ❌ {uploaded_file.filename}: {result.get('error')}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error processing {uploaded_file.filename}: {e}")
                results.append({
                    'success': False,
                    'status': 'ERROR',
                    'error': str(e),
                    'filename': uploaded_file.filename
                })
        
        # Calculate summary
        successful = len([r for r in results if r.get('success')])
        failed = len(results) - successful
        
        logger.info(f"✅ Admin upload complete: {successful} successful, {failed} failed out of {len(results)} files")
        
        return {
            'success': successful > 0,
            'message': f'Processed {len(results)} files: {successful} successful, {failed} failed',
            'total_files': len(results),
            'successful_count': successful,
            'failed_count': failed,
            'results': results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Admin batch upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File upload error. Please try again."
        )


@router.get("/documents")
async def list_sat_documents(
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[int] = None,
    doc_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    source_filter: Optional[str] = None,  # New: filter by source
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List SAT documents with optional filters.
    Now includes source filter (admin/supplier).
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


@router.post("/send-all-to-sap")
async def send_all_documents_to_sap(
    request: Request,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send ALL pending documents (canonical + simple merge) to SAP in one batch.
    Follows client's format: array of documents sent together.
    """
    try:
        body = await request.json()
        fiscal_year = body.get('fiscal_year')
        fiscal_period = body.get('fiscal_period')
        
        if not fiscal_year or not fiscal_period:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fiscal_year and fiscal_period are required"
            )
        
        logger.info(f"📤 Sending all documents to SAP for period {fiscal_year}-{fiscal_period:02d}")
        
        # Import here to avoid circular imports
        from ..services.sap_send_all import SAPBulkSender
        
        sender = SAPBulkSender(db)
        result = await sender.send_all_to_sap(
            user_id=current_user.id,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to send all to SAP: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send all documents to SAP: {str(e)}"
        )

