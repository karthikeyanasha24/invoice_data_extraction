"""
SAT Document API Endpoints
Handles Mexican Tax Documents (CFDI): INVOICE, PAYMENT, CREDIT_NOTE
"""
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import uuid as uuid_lib

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.sat_document import (
    SATDocument, 
    DocumentType, 
    ProcessingStatus,
    SATProcessingLog
)
from ..api.auth import get_current_user
from ..api.api_key_auth import get_api_user

router = APIRouter(prefix="/sat", tags=["SAT Documents"])
logger = logging.getLogger(__name__)


# ============================================================
# REQUEST/RESPONSE MODELS
# ============================================================

class SATIntakeRequest(BaseModel):
    """Request model for SAT document intake"""
    documentType: str = Field(..., description="Document type: INVOICE, PAYMENT, or CREDIT_NOTE")
    supplierId: str = Field(..., description="Supplier ID (e.g., SUPP001)")
    companyCode: str = Field(..., description="Company code (e.g., MX01)")
    xmlContent: str = Field(..., description="CFDI XML content")
    supplierName: Optional[str] = Field(None, description="Supplier name (optional)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "documentType": "INVOICE",
                "supplierId": "SUPP001",
                "companyCode": "MX01",
                "xmlContent": '<?xml version="1.0" encoding="UTF-8"?><cfdi:Comprobante...>',
                "supplierName": "Proveedor Ejemplo SA de CV"
            }
        }


class SATIntakeResponse(BaseModel):
    """Response model for SAT document intake"""
    success: bool
    portalReferenceId: str
    satDocumentId: str
    status: str
    message: str
    cfdiUuid: Optional[str] = None
    isDuplicate: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "portalReferenceId": "PRT-2025-000123",
                "satDocumentId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "RECEIVED",
                "message": "Document received and queued for processing",
                "cfdiUuid": "A1B2C3D4-E5F6-7890-ABCD-EF1234567890",
                "isDuplicate": False
            }
        }


class SATDocumentResponse(BaseModel):
    """Response model for SAT document details"""
    id: str
    portalReferenceId: str
    documentType: str
    cfdiUuid: str
    supplierId: str
    supplierName: Optional[str]
    supplierRfc: Optional[str]
    companyCode: str
    status: str
    isSchemaValid: Optional[bool]
    isDuplicate: bool
    sapDocumentNumber: Optional[str]
    createdAt: datetime
    updatedAt: datetime
    errorMessage: Optional[str]
    
    # CFDI Fields
    cfdiVersion: Optional[str]
    serie: Optional[str]
    folio: Optional[str]
    fecha: Optional[datetime]
    subtotal: Optional[str]
    total: Optional[str]
    moneda: Optional[str]
    tipoDeComprobante: Optional[str]
    
    # Customer Fields
    customerRfc: Optional[str]
    customerName: Optional[str]
    
    # SAP Fields
    sapFiscalYear: Optional[str]
    sapPostingDate: Optional[datetime]


class SATDocumentListResponse(BaseModel):
    """Response model for SAT document list"""
    total: int
    documents: List[SATDocumentResponse]


# ============================================================
# INTAKE ENDPOINT (Main Entry Point)
# ============================================================

@router.post("/intake", response_model=SATIntakeResponse)
async def intake_sat_document(
    request: SATIntakeRequest,
    current_user: ZodiacUser = Depends(get_current_user),  # Bearer token auth (web) or API key (suppliers)
    db: Session = Depends(get_db)
):
    """
    SAT Document Intake Endpoint
    
    Receives Mexican tax documents (CFDI) from suppliers.
    Supports 3 document types: INVOICE, PAYMENT, CREDIT_NOTE
    
    **Processing Steps:**
    1. Receive XML document
    2. Validate document type
    3. Generate portal reference ID
    4. Calculate XML hash
    5. Extract CFDI UUID
    6. Check for duplicates
    7. Store in database
    8. Return confirmation
    
    **Next Steps (Async):**
    - XML schema validation
    - Canonical normalization
    - Metadata enrichment
    - Send to SAP (when ready)
    """
    try:
        logger.info(f"📥 SAT Intake: Received {request.documentType} from supplier {request.supplierId}")
        
        # ============================================================
        # 1. VALIDATE DOCUMENT TYPE
        # ============================================================
        try:
            document_type = DocumentType[request.documentType.upper()]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document type: {request.documentType}. Must be INVOICE, PAYMENT, or CREDIT_NOTE"
            )
        
        # ============================================================
        # 2. GENERATE PORTAL REFERENCE ID
        # ============================================================
        from datetime import datetime as dt
        timestamp = dt.utcnow()
        year = timestamp.strftime("%Y")
        
        # Generate unique portal reference ID with timestamp component
        # Format: PRT-YYYY-MMDDHHMMSS-XXXX (last 4 chars of UUID for uniqueness)
        import uuid
        time_component = timestamp.strftime("%m%d%H%M%S")
        unique_suffix = str(uuid.uuid4())[:4].upper()
        portal_ref_id = f"PRT-{year}-{time_component}-{unique_suffix}"
        
        # ============================================================
        # 3. CALCULATE XML HASH (Integrity Check)
        # ============================================================
        import hashlib
        xml_hash = hashlib.sha256(request.xmlContent.encode('utf-8')).hexdigest()
        
        # ============================================================
        # 4. EXTRACT CFDI UUID (Quick extraction)
        # ============================================================
        cfdi_uuid = None
        try:
            # Quick extraction using regex (will do full parsing later)
            import re
            uuid_pattern = r'UUID=["\']([A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12})["\']'
            uuid_match = re.search(uuid_pattern, request.xmlContent, re.IGNORECASE)
            if uuid_match:
                cfdi_uuid = uuid_match.group(1).upper()
            else:
                # Try alternative pattern
                uuid_pattern2 = r'<tfd:TimbreFiscalDigital[^>]*UUID=["\']([A-F0-9-]+)["\']'
                uuid_match2 = re.search(uuid_pattern2, request.xmlContent, re.IGNORECASE)
                if uuid_match2:
                    cfdi_uuid = uuid_match2.group(1).upper()
        except Exception as e:
            logger.warning(f"Could not extract UUID: {e}")
        
        if not cfdi_uuid:
            # Generate a temporary UUID - will be extracted properly during validation
            cfdi_uuid = f"TEMP-{uuid_lib.uuid4()}"
            logger.warning(f"⚠️ Could not extract CFDI UUID, using temporary: {cfdi_uuid}")
        
        # ============================================================
        # 5. CHECK FOR DUPLICATES
        # ============================================================
        from ..models.sat_document import SATDuplicateCheck
        
        is_duplicate = False
        existing_doc = None
        
        if not cfdi_uuid.startswith("TEMP-"):
            # Check if UUID already exists
            existing_dup = db.query(SATDuplicateCheck).filter(
                SATDuplicateCheck.cfdi_uuid == cfdi_uuid,
                SATDuplicateCheck.user_id == current_user.id
            ).first()
            
            if existing_dup:
                is_duplicate = True
                existing_doc = db.query(SATDocument).filter(
                    SATDocument.id == existing_dup.sat_document_id
                ).first()
                
                logger.warning(f"⚠️ Duplicate document detected: UUID {cfdi_uuid}")
                
                return SATIntakeResponse(
                    success=False,
                    portalReferenceId=existing_doc.portal_reference_id,
                    satDocumentId=str(existing_doc.id),
                    status="DUPLICATE",
                    message=f"Duplicate document. Already received as {existing_doc.portal_reference_id}",
                    cfdiUuid=cfdi_uuid,
                    isDuplicate=True
                )
        
        # ============================================================
        # 6. CREATE SAT DOCUMENT RECORD
        # ============================================================
        sat_doc = SATDocument(
            portal_reference_id=portal_ref_id,
            document_type=document_type,
            cfdi_uuid=cfdi_uuid,
            supplier_id=request.supplierId,
            supplier_name=request.supplierName,
            company_code=request.companyCode,
            user_id=current_user.id,
            original_xml=request.xmlContent,
            original_xml_hash=xml_hash,
            processing_timestamp=timestamp,
            status=ProcessingStatus.RECEIVED,
            is_duplicate=False
        )
        
        db.add(sat_doc)
        db.flush()  # Get the ID without committing
        
        # ============================================================
        # 7. CREATE DUPLICATE CHECK RECORD
        # ============================================================
        if not cfdi_uuid.startswith("TEMP-"):
            dup_check = SATDuplicateCheck(
                cfdi_uuid=cfdi_uuid,
                sat_document_id=sat_doc.id,
                user_id=current_user.id,
                supplier_id=request.supplierId,
                document_type=document_type
            )
            db.add(dup_check)
        
        # ============================================================
        # 8. CREATE PROCESSING LOG
        # ============================================================
        log_entry = SATProcessingLog(
            sat_document_id=sat_doc.id,
            step_name="Document Received",
            step_status="SUCCESS",
            previous_status=None,
            new_status=ProcessingStatus.RECEIVED,
            message=f"Document received from supplier {request.supplierId} via API"
        )
        db.add(log_entry)
        
        # Commit all changes
        db.commit()
        db.refresh(sat_doc)
        
        logger.info(f"✅ SAT Document saved: {portal_ref_id} (ID: {sat_doc.id})")
        
        # ============================================================
        # 9. TRIGGER ASYNC PROCESSING
        # ============================================================
        # Process immediately (in future, use background task queue)
        from ..services.sat_processor import SATProcessor
        
        try:
            processor = SATProcessor(db)
            # Process in background (for now, sync - but fast)
            processing_result = await processor.process_document(str(sat_doc.id))
            
            if processing_result.get('success'):
                logger.info(f"✅ Document processed successfully: {portal_ref_id}")
            else:
                logger.warning(f"⚠️  Document processing had issues: {portal_ref_id}")
        except Exception as proc_error:
            logger.error(f"❌ Processing error (non-blocking): {proc_error}")
            # Don't fail the intake, just log the error
        
        # Refresh document to get updated status
        db.refresh(sat_doc)
        
        return SATIntakeResponse(
            success=True,
            portalReferenceId=portal_ref_id,
            satDocumentId=str(sat_doc.id),
            status="RECEIVED",
            message="Document received successfully and queued for processing",
            cfdiUuid=cfdi_uuid if not cfdi_uuid.startswith("TEMP-") else None,
            isDuplicate=False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing SAT document: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing document: {str(e)}"
        )


# ============================================================
# LIST DOCUMENTS ENDPOINT
# ============================================================

@router.get("/documents", response_model=SATDocumentListResponse)
async def list_sat_documents(
    document_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List SAT documents for the current user
    
    **Filters:**
    - document_type: INVOICE, PAYMENT, CREDIT_NOTE
    - status: RECEIVED, VALIDATED, COMPLETED, FAILED, etc.
    - limit: Max number of results (default 50)
    - offset: Pagination offset (default 0)
    """
    try:
        # Build query
        query = db.query(SATDocument).filter(
            SATDocument.user_id == current_user.id
        )
        
        # Apply filters
        if document_type:
            try:
                doc_type = DocumentType[document_type.upper()]
                query = query.filter(SATDocument.document_type == doc_type)
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid document type: {document_type}"
                )
        
        if status:
            try:
                proc_status = ProcessingStatus[status.upper()]
                query = query.filter(SATDocument.status == proc_status)
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status}"
                )
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        documents = query.order_by(
            SATDocument.created_at.desc()
        ).limit(limit).offset(offset).all()
        
        # Format response
        doc_list = []
        for doc in documents:
            doc_list.append(SATDocumentResponse(
                id=str(doc.id),
                portalReferenceId=doc.portal_reference_id,
                documentType=doc.document_type.value,
                cfdiUuid=doc.cfdi_uuid,
                supplierId=doc.supplier_id,
                supplierName=doc.supplier_name,
                supplierRfc=doc.supplier_rfc,
                companyCode=doc.company_code,
                status=doc.status.value,
                isSchemaValid=doc.is_schema_valid,
                isDuplicate=doc.is_duplicate,
                sapDocumentNumber=doc.sap_document_number,
                createdAt=doc.created_at,
                updatedAt=doc.updated_at,
                errorMessage=doc.error_message,
                # CFDI Fields
                cfdiVersion=doc.cfdi_version,
                serie=doc.serie,
                folio=doc.folio,
                fecha=doc.fecha,
                subtotal=doc.subtotal,
                total=doc.total,
                moneda=doc.moneda,
                tipoDeComprobante=doc.tipo_de_comprobante,
                # Customer Fields
                customerRfc=doc.customer_rfc,
                customerName=doc.customer_name,
                # SAP Fields
                sapFiscalYear=doc.sap_fiscal_year,
                sapPostingDate=doc.sap_posting_date
            ))
        
        return SATDocumentListResponse(
            total=total,
            documents=doc_list
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error listing SAT documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing documents: {str(e)}"
        )


# ============================================================
# GET DOCUMENT DETAILS ENDPOINT
# ============================================================

@router.get("/documents/{document_id}", response_model=SATDocumentResponse)
async def get_sat_document(
    document_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get details for a specific SAT document
    """
    try:
        # Find document
        doc = db.query(SATDocument).filter(
            SATDocument.id == document_id,
            SATDocument.user_id == current_user.id
        ).first()
        
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        return SATDocumentResponse(
            id=str(doc.id),
            portalReferenceId=doc.portal_reference_id,
            documentType=doc.document_type.value,
            cfdiUuid=doc.cfdi_uuid,
            supplierId=doc.supplier_id,
            supplierName=doc.supplier_name,
            supplierRfc=doc.supplier_rfc,
            companyCode=doc.company_code,
            status=doc.status.value,
            isSchemaValid=doc.is_schema_valid,
            isDuplicate=doc.is_duplicate,
            sapDocumentNumber=doc.sap_document_number,
            createdAt=doc.created_at,
            updatedAt=doc.updated_at,
            errorMessage=doc.error_message,
            # CFDI Fields
            cfdiVersion=doc.cfdi_version,
            serie=doc.serie,
            folio=doc.folio,
            fecha=doc.fecha,
            subtotal=doc.subtotal,
            total=doc.total,
            moneda=doc.moneda,
            tipoDeComprobante=doc.tipo_de_comprobante,
            # Customer Fields
            customerRfc=doc.customer_rfc,
            customerName=doc.customer_name,
            # SAP Fields
            sapFiscalYear=doc.sap_fiscal_year,
            sapPostingDate=doc.sap_posting_date
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting SAT document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting document: {str(e)}"
        )


# ============================================================
# PROCESS DOCUMENT ENDPOINT (Manual Trigger)
# ============================================================

class ProcessingResponse(BaseModel):
    """Response model for processing trigger"""
    success: bool
    message: str
    documentId: str
    portalReferenceId: str
    status: str
    validation: Optional[Dict] = None


@router.post("/documents/{document_id}/process", response_model=ProcessingResponse)
async def process_sat_document(
    document_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually trigger processing for a SAT document
    
    **Processing Steps:**
    1. Validate XML structure
    2. Extract CFDI fields
    3. Normalize to canonical format
    4. Mark as ready for SAP
    
    **Use this endpoint to:**
    - Reprocess failed documents
    - Process documents that were skipped
    - Re-validate after corrections
    """
    try:
        # Find document
        doc = db.query(SATDocument).filter(
            SATDocument.id == document_id,
            SATDocument.user_id == current_user.id
        ).first()
        
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        logger.info(f"🔄 Manual processing triggered for {doc.portal_reference_id}")
        
        # Process document
        from ..services.sat_processor import SATProcessor
        processor = SATProcessor(db)
        result = await processor.process_document(str(doc.id))
        
        # Refresh to get updated status
        db.refresh(doc)
        
        return ProcessingResponse(
            success=result.get('success', False),
            message=result.get('message', 'Processing complete'),
            documentId=str(doc.id),
            portalReferenceId=doc.portal_reference_id,
            status=doc.status.value,
            validation=result.get('validation')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing document: {str(e)}"
        )


# ============================================================
# GET PROCESSING LOGS ENDPOINT
# ============================================================

class ProcessingLogResponse(BaseModel):
    """Response model for processing log"""
    stepName: str
    stepStatus: str
    message: str
    previousStatus: Optional[str]
    newStatus: Optional[str]
    createdAt: datetime


@router.get("/documents/{document_id}/logs", response_model=List[ProcessingLogResponse])
async def get_processing_logs(
    document_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get processing logs for a SAT document
    
    **Shows:**
    - All processing steps
    - Status transitions
    - Errors and warnings
    - Timestamps
    """
    try:
        # Verify document ownership
        doc = db.query(SATDocument).filter(
            SATDocument.id == document_id,
            SATDocument.user_id == current_user.id
        ).first()
        
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Get logs
        logs = db.query(SATProcessingLog).filter(
            SATProcessingLog.sat_document_id == document_id
        ).order_by(SATProcessingLog.created_at).all()
        
        return [
            ProcessingLogResponse(
                stepName=log.step_name,
                stepStatus=log.step_status,
                message=log.message,
                previousStatus=log.previous_status.value if log.previous_status else None,
                newStatus=log.new_status.value if log.new_status else None,
                createdAt=log.created_at
            )
            for log in logs
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting processing logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting logs: {str(e)}"
        )

