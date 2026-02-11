"""
Invoice V2 API Router - New invoice management system with validation and correction cache
"""
import logging
import uuid
import asyncio
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime

from ..database import get_db
from ..api.auth import get_current_user
from ..models.user import ZodiacUser
from ..models.invoice_v2_document import InvoiceV2Document
from ..models.invoice_v2_validated import InvoiceV2Validated
from ..models.invoice_v2_correction_cache import InvoiceV2CorrectionCache
from ..services.invoice_v2_validation_service import InvoiceV2ValidationService
from ..services.invoice_v2_correction_service import InvoiceV2CorrectionService
from ..services.file_service import save_file_to_storage, read_file_from_storage

router = APIRouter(prefix="/invoices-v2", tags=["invoices-v2"])
logger = logging.getLogger("zodiac-api.invoices_v2")


# ==================== DOCUMENTS ENDPOINTS ====================

@router.post("/upload")
async def upload_manual_invoice(
    file: UploadFile = File(...),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload invoice manually from web UI.
    Source will be set to 'manual'.
    """
    logger.info(f"📤 Manual upload request from user {current_user.id}")
    logger.info(f"   Filename: {file.filename}")
    
    try:
        # Validate file type
        if not file.filename.lower().endswith('.xml'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only XML files are supported"
            )
        
        # Read file content
        xml_content = await file.read()
        
        if not xml_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file"
            )
        
        # Generate tracking ID
        tracking_id = uuid.uuid4()
        
        # Save file to storage
        filename = f"{tracking_id}_{file.filename}"
        storage_result = await save_file_to_storage(
            file_content=xml_content,
            filename=filename,
            subdirectory="invoices_v2"
        )
        
        logger.info(f"   Storage result type: {type(storage_result)}")
        logger.info(f"   Storage result: {storage_result}")
        
        # Handle storage result (can be string or dict)
        xml_path = None
        blob_xml_path = None
        
        if isinstance(storage_result, dict):
            # Blob storage dict format: {"url": "https://...", "pathname": "...", ...}
            logger.info(f"   Storage returned dict with keys: {list(storage_result.keys())}")
            
            if 'url' in storage_result:
                blob_xml_path = storage_result['url']
                xml_path = None
                logger.info(f"   ✅ Using blob URL: {blob_xml_path}")
            else:
                # Try to find any URL-like value
                for key, value in storage_result.items():
                    if isinstance(value, str) and value.startswith('http'):
                        blob_xml_path = value
                        logger.info(f"   ✅ Found URL in key '{key}': {blob_xml_path}")
                        break
        elif isinstance(storage_result, str):
            # String format: either local path or blob URL
            logger.info(f"   Storage returned string: {storage_result}")
            if storage_result.startswith('http'):
                xml_path = None
                blob_xml_path = storage_result
            else:
                xml_path = storage_result
                blob_xml_path = None
        else:
            raise ValueError(f"Unexpected storage result type: {type(storage_result)}")
        
        # Final check
        if not xml_path and not blob_xml_path:
            logger.error(f"   ❌ Both paths are None!")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file - no storage path returned"
            )
        
        # Log final paths before creating document
        logger.info(f"   ✅ File saved successfully!")
        logger.info(f"   Final xml_path: {xml_path}")
        logger.info(f"   Final blob_xml_path: {blob_xml_path}")
        
        # Create document record
        document = InvoiceV2Document(
            tracking_id=tracking_id,
            user_id=current_user.id,
            source='manual',
            filename=file.filename,
            xml_path=xml_path,
            blob_xml_path=blob_xml_path,
            validation_status='not_validated'
        )
        
        db.add(document)
        db.commit()
        db.refresh(document)
        
        logger.info(f"✅ Document uploaded successfully")
        logger.info(f"   Document ID: {document.id}")
        logger.info(f"   Tracking ID: {tracking_id}")
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "message": "Invoice uploaded successfully",
                "tracking_id": str(tracking_id),
                "document_id": document.id,
                "filename": file.filename,
                "source": "manual"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.post("/sap/receive")
async def receive_sap_invoice(
    file: UploadFile = File(...),
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Receive invoice from SAP system.
    SAP sends XML as a file upload (multipart/form-data).
    Source will be set to 'sap'.
    
    Authentication: Uses JWT authentication (same as /api/v1/invoices/sap/process)
    """
    logger.info(f"📥 SAP invoice receive request from user {current_user.id}")
    logger.info(f"   Original filename: {file.filename}")
    
    try:
        # Validate file extension
        if not file.filename or not file.filename.lower().endswith('.xml'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only XML files are supported"
            )
        
        # Read XML content from uploaded file
        xml_content = await file.read()
        
        if not xml_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file"
            )
        
        # Validate XML content
        try:
            xml_str = xml_content.decode('utf-8')
            logger.info(f"   XML size: {len(xml_content)} bytes")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid XML encoding"
            )
        
        # Generate tracking ID
        tracking_id = uuid.uuid4()
        
        # Generate filename (preserve original or use tracking ID)
        # Clean the filename to avoid issues with special characters
        import re
        clean_filename = re.sub(r'[^\w\s.-]', '_', file.filename)
        clean_filename = clean_filename.replace(' ', '_')
        filename = f"SAP_{tracking_id}_{clean_filename}"
        
        # Save file to storage
        logger.info(f"   Original filename: {file.filename}")
        logger.info(f"   Cleaned filename: {filename}")
        logger.info(f"   Saving file to storage...")
        logger.info(f"   Subdirectory: invoices_v2_sap")
        logger.info(f"   File size: {len(xml_content)} bytes")
        
        storage_result = await save_file_to_storage(
            file_content=xml_content,
            filename=filename,
            subdirectory="invoices_v2_sap"
        )
        
        logger.info(f"   Storage result type: {type(storage_result)}")
        logger.info(f"   Storage result: {storage_result}")
        
        # Check if storage_result is None or empty
        if not storage_result:
            logger.error(f"   ❌ Storage result is None or empty!")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save file to storage - storage function returned no result"
            )
        
        # Handle storage result (can be string or dict)
        xml_path = None
        blob_xml_path = None
        
        if isinstance(storage_result, dict):
            # Blob storage dict format: {"url": "https://...", "pathname": "...", ...}
            logger.info(f"   Storage returned dict with keys: {list(storage_result.keys())}")
            
            # Vercel Blob returns 'url' key
            if 'url' in storage_result:
                blob_xml_path = storage_result['url']
                xml_path = None
                logger.info(f"   ✅ Using blob URL: {blob_xml_path}")
            else:
                # Fallback: check for other possible keys
                logger.warning(f"   ⚠️ Dict doesn't have 'url' key, checking alternatives...")
                logger.info(f"   Available keys: {list(storage_result.keys())}")
                # Try to find any URL-like value
                for key, value in storage_result.items():
                    if isinstance(value, str) and value.startswith('http'):
                        blob_xml_path = value
                        logger.info(f"   ✅ Found URL in key '{key}': {blob_xml_path}")
                        break
        elif isinstance(storage_result, str):
            # String format: either local path or blob URL
            logger.info(f"   Storage returned string: {storage_result}")
            if storage_result.startswith('http'):
                xml_path = None
                blob_xml_path = storage_result
                logger.info(f"   ✅ String is blob URL")
            else:
                xml_path = storage_result
                blob_xml_path = None
                logger.info(f"   ✅ String is local path")
        else:
            logger.error(f"   ❌ Unexpected storage result type: {type(storage_result)}")
            raise ValueError(f"Unexpected storage result type: {type(storage_result)}")
        
        # Final check - make sure we have at least one path
        if not xml_path and not blob_xml_path:
            logger.error(f"   ❌ Both paths are None after processing storage result!")
            logger.error(f"   Storage result was: {storage_result}")
            logger.error(f"   Storage result type: {type(storage_result)}")
            if isinstance(storage_result, dict):
                logger.error(f"   Dict contents: {storage_result}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file - no storage path returned. Storage result: {storage_result}"
            )
        
        # Log final paths before creating document
        logger.info(f"   ✅ File saved successfully!")
        logger.info(f"   Final xml_path: {xml_path}")
        logger.info(f"   Final blob_xml_path: {blob_xml_path}")
        
        # Create document record
        document = InvoiceV2Document(
            tracking_id=tracking_id,
            user_id=current_user.id,
            source='sap',
            filename=file.filename,  # Use original filename, not cleaned one
            xml_path=xml_path,
            blob_xml_path=blob_xml_path,
            validation_status='not_validated'
        )
        
        db.add(document)
        db.commit()
        db.refresh(document)
        
        logger.info(f"✅ SAP invoice received successfully")
        logger.info(f"   Document ID: {document.id}")
        logger.info(f"   Tracking ID: {tracking_id}")
        logger.info(f"   XML Path: {document.xml_path}")
        logger.info(f"   Blob XML Path: {document.blob_xml_path}")
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "message": "SAP invoice received successfully",
                "tracking_id": str(tracking_id),
                "document_id": document.id,
                "filename": filename,
                "source": "sap"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ SAP receive failed: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SAP receive failed: {str(e)}"
        )


@router.get("/documents")
async def list_documents(
    source: Optional[str] = None,
    validation_status: Optional[str] = None,
    include_deleted: bool = False,
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all documents with optional filters.
    
    Filters:
    - source: 'manual', 'sap', or None for all
    - validation_status: 'not_validated', 'processing', 'validated', or None for all
    - include_deleted: Include soft-deleted documents
    """
    logger.info(f"📋 List documents request from user {current_user.id}")
    logger.info(f"   Filters: source={source}, status={validation_status}, deleted={include_deleted}")
    
    try:
        # Build query
        query = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.user_id == current_user.id
        )
        
        # Apply filters
        if source:
            query = query.filter(InvoiceV2Document.source == source)
        
        if validation_status:
            query = query.filter(InvoiceV2Document.validation_status == validation_status)
        
        if not include_deleted:
            query = query.filter(InvoiceV2Document.deleted_at.is_(None))
        
        # Count total
        total = query.count()
        
        # Get paginated results
        documents = query.order_by(
            InvoiceV2Document.uploaded_at.desc()
        ).offset(skip).limit(limit).all()
        
        logger.info(f"✅ Found {len(documents)} documents (total: {total})")
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "documents": [doc.to_dict() for doc in documents]
        }
        
    except Exception as e:
        logger.error(f"❌ List documents failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Soft delete a document.
    """
    logger.info(f"🗑️ Delete document request: {document_id}")
    
    try:
        document = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.id == document_id,
            InvoiceV2Document.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Soft delete
        document.deleted_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"✅ Document {document_id} deleted")
        
        return {"message": "Document deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Delete failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/documents/{document_id}/info")
async def get_document_info(
    document_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get document storage information for debugging.
    """
    document = db.query(InvoiceV2Document).filter(
        InvoiceV2Document.id == document_id,
        InvoiceV2Document.user_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    return {
        "id": document.id,
        "filename": document.filename,
        "xml_path": document.xml_path,
        "blob_xml_path": document.blob_xml_path,
        "has_xml_path": document.xml_path is not None,
        "has_blob_path": document.blob_xml_path is not None,
        "source": document.source
    }


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download the XML file for a document.
    """
    logger.info(f"📥 Download document request: {document_id}")
    
    try:
        document = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.id == document_id,
            InvoiceV2Document.user_id == current_user.id
        ).first()
        
        if not document:
            logger.error(f"Document {document_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        logger.info(f"   Filename: {document.filename}")
        logger.info(f"   XML Path: {document.xml_path}")
        logger.info(f"   Blob XML Path: {document.blob_xml_path}")
        logger.info(f"   Source: {document.source}")
        
        # Determine which path to use
        if not document.blob_xml_path and not document.xml_path:
            logger.error(f"No file path available for document {document_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No file path available for this document"
            )
        
        # Read XML content from storage
        try:
            # For blob storage, pass the blob URL directly
            if document.blob_xml_path:
                logger.info(f"   Reading from blob storage: {document.blob_xml_path}")
                xml_content = await read_file_from_storage(
                    file_path=document.blob_xml_path,
                    blob_xml_path=document.blob_xml_path
                )
            else:
                logger.info(f"   Reading from local storage: {document.xml_path}")
                xml_content = await read_file_from_storage(
                    file_path=document.xml_path,
                    blob_xml_path=None
                )
            
            logger.info(f"   Successfully read {len(xml_content)} bytes")
                
        except Exception as e:
            logger.error(f"Failed to read file from storage: {e}")
            logger.exception(e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read file from storage: {str(e)}"
            )
        
        # Return as downloadable file
        from fastapi.responses import Response
        
        logger.info(f"✅ Document {document_id} downloaded successfully")
        
        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{document.filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Download failed with unexpected error: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download failed: {str(e)}"
        )


# ==================== VALIDATION ENDPOINTS ====================

@router.get("/unvalidated")
async def list_unvalidated_invoices(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all invoices with validation_status='not_validated'.
    """
    logger.info(f"📋 List unvalidated invoices request from user {current_user.id}")
    
    try:
        documents = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.validation_status == 'not_validated',
            InvoiceV2Document.deleted_at.is_(None)
        ).order_by(
            InvoiceV2Document.uploaded_at.desc()
        ).all()
        
        logger.info(f"✅ Found {len(documents)} unvalidated invoices")
        
        return {
            "total": len(documents),
            "documents": [doc.to_dict() for doc in documents]
        }
        
    except Exception as e:
        logger.error(f"❌ List unvalidated failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


async def _validate_single_invoice(document_id: int, db_session: Session):
    """Background task to validate a single invoice"""
    try:
        # Get document
        document = db_session.query(InvoiceV2Document).filter(
            InvoiceV2Document.id == document_id
        ).first()
        
        if not document:
            logger.error(f"❌ Document {document_id} not found")
            return
        
        # Update status to processing
        document.validation_status = 'processing'
        db_session.commit()
        
        # Validate invoice
        validation_service = InvoiceV2ValidationService(db_session)
        validated = await validation_service.validate_invoice(document)
        
        logger.info(f"✅ Validation completed for document {document_id}: {validated.status}")
        
    except Exception as e:
        logger.error(f"❌ Validation failed for document {document_id}: {e}")
        logger.exception(e)
        
        # Reset validation status on error
        try:
            document = db_session.query(InvoiceV2Document).filter(
                InvoiceV2Document.id == document_id
            ).first()
            if document:
                document.validation_status = 'not_validated'
                db_session.commit()
        except:
            pass


@router.post("/validate")
async def validate_invoices(
    request: Dict,
    background_tasks: BackgroundTasks,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Process selected invoices for validation.
    Runs in background and returns immediately.
    """
    document_ids = request.get("document_ids", [])
    
    logger.info(f"🔍 Validation request for {len(document_ids)} documents")
    logger.info(f"   Document IDs: {document_ids}")
    
    try:
        # Verify documents exist and belong to user
        documents = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.id.in_(document_ids),
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.validation_status == 'not_validated'
        ).all()
        
        if not documents:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No valid documents found for validation"
            )
        
        logger.info(f"✅ Found {len(documents)} documents to validate")
        
        # Queue validation tasks
        for document in documents:
            # Add background task
            background_tasks.add_task(
                _validate_single_invoice,
                document.id,
                db
            )
        
        return {
            "message": f"Validation queued for {len(documents)} documents",
            "document_ids": [doc.id for doc in documents],
            "tracking_ids": [str(doc.tracking_id) for doc in documents]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Validation queue failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/validation-progress")
async def get_validation_progress(
    document_ids: str,  # Comma-separated IDs
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get validation progress for multiple documents.
    Returns status of each document (not_validated, processing, validated).
    """
    try:
        # Parse document IDs
        ids = [int(id.strip()) for id in document_ids.split(',')]
        
        # Get documents
        documents = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.id.in_(ids),
            InvoiceV2Document.user_id == current_user.id
        ).all()
        
        if not documents:
            return {
                "progress": [],
                "completed": 0,
                "total": 0,
                "all_done": True
            }
        
        # Build progress info
        progress = []
        completed_count = 0
        
        for doc in documents:
            doc_progress = {
                "document_id": doc.id,
                "filename": doc.filename,
                "validation_status": doc.validation_status,
                "is_complete": doc.validation_status == 'validated'
            }
            
            # If validated, get the result
            if doc.validation_status == 'validated' and doc.validated_invoice:
                doc_progress["result_status"] = doc.validated_invoice.status
                doc_progress["result_id"] = doc.validated_invoice.id
                completed_count += 1
            
            progress.append(doc_progress)
        
        return {
            "progress": progress,
            "completed": completed_count,
            "total": len(documents),
            "all_done": all(p["is_complete"] for p in progress)
        }
        
    except Exception as e:
        logger.error(f"❌ Get validation progress failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================== VALIDATED INVOICES ENDPOINTS ====================

@router.get("/validated")
async def list_validated_invoices(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List validated invoices with optional status filter.
    
    Filters:
    - status_filter: 'success' or 'failed'
    """
    logger.info(f"📋 List validated invoices request from user {current_user.id}")
    logger.info(f"   Filter: status={status_filter}")
    
    try:
        # Build query with join
        query = db.query(InvoiceV2Validated).join(
            InvoiceV2Document,
            InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Document.user_id == current_user.id,
            InvoiceV2Document.deleted_at.is_(None)
        )
        
        # Apply status filter
        if status_filter:
            query = query.filter(InvoiceV2Validated.status == status_filter)
        
        # Count total
        total = query.count()
        
        # Get paginated results
        validated = query.order_by(
            InvoiceV2Validated.validated_at.desc()
        ).offset(skip).limit(limit).all()
        
        logger.info(f"✅ Found {len(validated)} validated invoices (total: {total})")
        
        # Build response with document info
        results = []
        for v in validated:
            result = v.to_dict()
            result["document"] = v.document.to_dict() if v.document else None
            results.append(result)
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "validated_invoices": results
        }
        
    except Exception as e:
        logger.error(f"❌ List validated failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/validated/{validated_id}")
async def get_validated_invoice_details(
    validated_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed validation results for a specific invoice.
    """
    logger.info(f"📄 Get validated invoice details: {validated_id}")
    
    try:
        # Get validated invoice with document
        validated = db.query(InvoiceV2Validated).join(
            InvoiceV2Document,
            InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Validated.id == validated_id,
            InvoiceV2Document.user_id == current_user.id
        ).first()
        
        if not validated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validated invoice not found"
            )
        
        result = validated.to_dict()
        result["document"] = validated.document.to_dict()
        
        logger.info(f"✅ Retrieved validated invoice {validated_id}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get validated details failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/validated/{validated_id}/manual-fix")
async def manual_fix_invoice(
    validated_id: int,
    request: Dict,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually fix missing fields and save to correction cache.
    
    Request body: {"corrections": {"field_name": "field_value", ...}}
    """
    corrections = request.get("corrections", {})
    
    logger.info(f"🔧 Manual fix request for validated invoice {validated_id}")
    logger.info(f"   Corrections: {list(corrections.keys())}")
    
    try:
        # Get validated invoice
        validated = db.query(InvoiceV2Validated).join(
            InvoiceV2Document,
            InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Validated.id == validated_id,
            InvoiceV2Document.user_id == current_user.id
        ).first()
        
        if not validated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validated invoice not found"
            )
        
        # Update invoice data with corrections first
        for field_name, field_value in corrections.items():
            validated.invoice_data[field_name] = field_value
        
        # Mark as modified (important for SQLAlchemy to detect JSON changes)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(validated, "invoice_data")
        
        # Get customer ID from updated invoice data (after applying corrections)
        customer_id = validated.invoice_data.get("customer_id")
        customer_name = validated.invoice_data.get("customer_name")
        
        # Save corrections to cache only if we have a customer_id
        saved_corrections = []
        if customer_id:
            correction_service = InvoiceV2CorrectionService(db)
            saved_corrections = correction_service.save_multiple_corrections(
                customer_id=customer_id,
                customer_name=customer_name,
                corrections=corrections,
                user_id=current_user.id
            )
            logger.info(f"✅ Saved {len(saved_corrections)} corrections to cache for customer {customer_id}")
        else:
            logger.warning(f"⚠️ No customer_id available, skipping cache save for validated invoice {validated_id}")
        
        # Re-check for missing required fields after applying corrections
        from ..services.invoice_v2_validation_service import InvoiceV2ValidationService
        validation_service = InvoiceV2ValidationService(db)
        
        # Find missing fields
        missing_fields = validation_service._find_missing_fields(validated.invoice_data)
        
        # Validate field formats
        validation_errors = validation_service.validate_field_formats(validated.invoice_data)
        
        # Update status based on new data
        new_status = "success" if len(missing_fields) == 0 and len(validation_errors) == 0 else "failed"
        
        validated.missing_fields = missing_fields if missing_fields else None
        validated.validation_errors = validation_errors if validation_errors else None
        validated.status = new_status
        validated.correction_applied = True
        validated.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(validated)
        
        logger.info(f"✅ Manual fix applied successfully")
        logger.info(f"   New status: {new_status}")
        logger.info(f"   Remaining missing fields: {len(missing_fields)}")
        
        logger.info(f"✅ Manual fix applied successfully")
        
        return {
            "message": "Manual fix applied successfully",
            "corrections_saved": len(saved_corrections),
            "new_status": validated.status,
            "remaining_missing_fields": validated.missing_fields,
            "cached": len(saved_corrections) > 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Manual fix failed: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/validated/{validated_id}/reprocess")
async def reprocess_invoice(
    validated_id: int,
    background_tasks: BackgroundTasks,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reprocess a validated invoice by re-running validation on the original XML.
    This is useful after applying manual corrections to see if the invoice now passes validation.
    """
    logger.info(f"🔄 Reprocess request for validated invoice {validated_id}")
    
    try:
        # Get validated invoice with its document
        validated = db.query(InvoiceV2Validated).join(
            InvoiceV2Document,
            InvoiceV2Validated.document_id == InvoiceV2Document.id
        ).filter(
            InvoiceV2Validated.id == validated_id,
            InvoiceV2Document.user_id == current_user.id
        ).first()
        
        if not validated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validated invoice not found"
            )
        
        # Get the document
        document = db.query(InvoiceV2Document).filter(
            InvoiceV2Document.id == validated.document_id,
            InvoiceV2Document.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        logger.info(f"   Reprocessing document {document.id}: {document.filename}")
        
        # Delete the old validated record to allow re-validation
        db.delete(validated)
        
        # Set document back to not_validated
        document.validation_status = 'not_validated'
        db.commit()
        
        # Trigger validation in background
        def validate_task():
            from app.services.invoice_v2_validation_service import InvoiceV2ValidationService
            validation_service = InvoiceV2ValidationService(db)
            
            # Set to processing
            document.validation_status = 'processing'
            db.commit()
            
            try:
                # Run validation
                result = validation_service.validate_invoice(
                    document_id=document.id,
                    xml_path=document.xml_path,
                    blob_xml_path=document.blob_xml_path
                )
                
                # Mark as validated
                document.validation_status = 'validated'
                db.commit()
                
                logger.info(f"✅ Reprocess completed for document {document.id}: {result['status']}")
                
            except Exception as e:
                logger.error(f"❌ Reprocess failed for document {document.id}: {e}")
                document.validation_status = 'not_validated'
                db.commit()
        
        background_tasks.add_task(validate_task)
        
        logger.info(f"✅ Reprocess queued for document {document.id}")
        
        return {
            "message": "Invoice reprocessing started",
            "document_id": document.id,
            "validated_id": validated_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Reprocess failed: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/validated/{validated_id}/ai-fix")
async def ai_fix_invoice(
    validated_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Use AI to fix missing fields (placeholder for future implementation).
    """
    logger.info(f"🤖 AI fix request for validated invoice {validated_id}")
    
    # Placeholder for AI-powered correction
    # This would call an AI service to analyze the XML and suggest corrections
    
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="AI fix feature coming soon"
    )
