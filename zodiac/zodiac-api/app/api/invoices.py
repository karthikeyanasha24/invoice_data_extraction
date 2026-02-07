from .utils import extract_invoice_info
import re
import time
from ..api.auth import get_current_user
from ..api.api_key_auth import get_api_user
from ..schemas.invoice import InvoiceProcessingResponse, ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi, InvoiceResponse, ProcessingStepResult, StepStatus, DetailedErrorInfo
from ..models.invoice import ZodiacInvoiceSuccessEdi as SuccessModel, ZodiacInvoiceFailedEdi as FailedModel
from ..models.user import ZodiacUser, generate_api_key, hash_api_key, encode_api_key_for_transport
from ..database import get_db, SessionLocal
from enum import Enum
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from typing import Optional, Union
import uuid
import os
import logging
import json
import xml.etree.ElementTree as ET
from lxml import etree
from datetime import datetime
from ..services.error_handlers import ErrorTracker
from ..services.process_service import process_invoice_internal
from ..services.status_tracker import status_tracker
from ..services.file_service import save_file_to_storage, read_file_from_storage
from ..config.config import USE_BLOB_STORAGE

router = APIRouter(prefix="/invoices", tags=["invoice-processing"])
# Set up logger
logger = logging.getLogger("zodiac-api.invoices")

# Error tracker instance
error_tracker = ErrorTracker()


def extract_invoice_number_from_xml(xml_content: str) -> Optional[str]:
    """Extract invoice number from XML content (supports both UBL and SAT CFDI formats)"""
    try:
        root = etree.fromstring(xml_content.encode('utf-8'))
        
        # Try UBL format first (cbc:ID element)
        ubl_namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        }
        invoice_id_elem = root.find('.//cbc:ID', ubl_namespaces)
        if invoice_id_elem is not None and invoice_id_elem.text:
            invoice_number = invoice_id_elem.text.strip().upper()
            logger.debug(f"   Extracted UBL invoice ID: {invoice_number}")
            return invoice_number
        
        # Try SAT CFDI format (Serie + Folio attributes)
        cfdi_namespaces = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'cfdi3': 'http://www.sat.gob.mx/cfd/3',
        }
        
        # Try CFDI 4.0
        comprobante = root if root.tag.endswith('Comprobante') else root.find('.//cfdi:Comprobante', cfdi_namespaces)
        
        # Try CFDI 3.3 if 4.0 not found
        if comprobante is None:
            comprobante = root.find('.//cfdi3:Comprobante', cfdi_namespaces)
        
        if comprobante is not None:
            serie = comprobante.get('Serie', '')
            folio = comprobante.get('Folio', '')
            
            if serie and folio:
                invoice_number = f"{serie}-{folio}".upper()
                logger.debug(f"   Extracted SAT CFDI invoice ID: {invoice_number}")
                return invoice_number
            elif folio:
                invoice_number = folio.upper()
                logger.debug(f"   Extracted SAT CFDI folio: {invoice_number}")
                return invoice_number
        
        # Try to find any ID element without namespace
        any_id = root.find('.//{*}ID')
        if any_id is not None and any_id.text:
            invoice_number = any_id.text.strip().upper()
            logger.debug(f"   Extracted generic ID: {invoice_number}")
            return invoice_number
        
        logger.warning(f"⚠️ Could not extract invoice number from XML (no UBL ID or SAT Serie/Folio found)")
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to extract invoice number: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


# In-memory cache for duplicate checks (TTL: 5 minutes)
_duplicate_check_cache = {}
_cache_ttl = 300  # 5 minutes in seconds

# In-memory tracking of invoices currently being processed (prevents race condition)
_processing_invoices = {}  # Format: {(user_id, invoice_number): timestamp}

async def check_invoice_already_processed(
    db: Session, 
    invoice_number: str, 
    user_id: int,
    check_failed: bool = False,
    source: str = "manual"
) -> tuple[bool, Optional[int]]:
    """
    Check if invoice with this number has already been processed
    
    Args:
        db: Database session
        invoice_number: Invoice number to check
        user_id: User ID to scope the check
        check_failed: If True, also check failed invoices (for SAP API uploads)
        source: Upload source ('manual' or 'api')
    
    Returns:
        (already_exists, invoice_id) tuple
    """
    if not invoice_number:
        return False, None
    
    try:
        # Check in-memory cache first
        cache_key = f"{user_id}:{invoice_number.upper()}:{check_failed}"
        current_time = time.time()
        
        if cache_key in _duplicate_check_cache:
            cached_result, cached_time = _duplicate_check_cache[cache_key]
            if current_time - cached_time < _cache_ttl:
                logger.info(f"🔍 ============ DUPLICATE CHECK (CACHE HIT) ============")
                logger.info(f"   Invoice Number: {invoice_number}")
                logger.info(f"   User ID: {user_id}")
                logger.info(f"   Cached result: {'DUPLICATE' if cached_result[0] else 'NOT DUPLICATE'}")
                logger.info(f"   Cache age: {int(current_time - cached_time)}s (TTL: {_cache_ttl}s)")
                logger.info(f"🔍 ============ RETURNING CACHED RESULT ============")
                return cached_result
            else:
                # Cache expired, remove it
                logger.info(f"   Cache expired for invoice #{invoice_number} (age: {int(current_time - cached_time)}s)")
                del _duplicate_check_cache[cache_key]
        
        logger.info(f"🔍 ============ DUPLICATE CHECK START ============")
        logger.info(f"   Invoice Number: {invoice_number}")
        logger.info(f"   User ID: {user_id}")
        logger.info(f"   Source: {source}")
        logger.info(f"   Check Failed Invoices: {check_failed}")
        
        # RACE CONDITION CHECK: Check if invoice is currently being processed
        processing_key = (user_id, invoice_number.upper())
        if processing_key in _processing_invoices:
            processing_time = _processing_invoices[processing_key]
            elapsed = current_time - processing_time
            
            # Clean up stuck items (processing for more than 5 minutes = likely crashed)
            if elapsed > 300:  # 5 minutes
                logger.warning(f"⚠️ Invoice #{invoice_number} has been processing for {elapsed:.1f}s (>5 min) - removing from queue")
                del _processing_invoices[processing_key]
            else:
                # Still actively processing - block the duplicate
                logger.warning(f"🚫🚫🚫 DUPLICATE - INVOICE CURRENTLY BEING PROCESSED! 🚫🚫🚫")
                logger.warning(f"   Invoice Number: {invoice_number}")
                logger.warning(f"   User ID: {user_id}")
                logger.warning(f"   Currently processing for: {elapsed:.1f} seconds")
                logger.warning(f"   BLOCKING this duplicate upload attempt!")
                result = (True, None)
                _duplicate_check_cache[cache_key] = (result, current_time)
                return result
        
        logger.info(f"   ✅ Invoice not currently being processed")
        
        # FAST PATH: Check database column first (much faster than reading files)
        logger.info(f"   🚀 FAST PATH: Checking invoice_number column in database...")
        duplicate_in_db = db.query(SuccessModel).filter(
            SuccessModel.user_id == user_id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.invoice_number == invoice_number.upper()
        ).first()
        
        if duplicate_in_db:
            logger.warning(f"🚫🚫🚫 DUPLICATE FOUND IN DATABASE (FAST PATH)! 🚫🚫🚫")
            logger.warning(f"   Invoice Number: {invoice_number}")
            logger.warning(f"   Existing Invoice ID: {duplicate_in_db.id}")
            logger.warning(f"   Existing Tracking ID: {duplicate_in_db.tracking_id}")
            logger.warning(f"   Existing Upload Date: {duplicate_in_db.uploaded_at}")
            logger.warning(f"   USER ATTEMPTED TO UPLOAD DUPLICATE - BLOCKING!")
            result = (True, duplicate_in_db.id)
            _duplicate_check_cache[cache_key] = (result, current_time)
            return result
        
        logger.info(f"   ✅ No duplicate found in database (fast path)")
        
        # SLOW PATH: For backwards compatibility, also check invoices without invoice_number column
        # (This handles old records that were created before we added the column)
        logger.info(f"   🐢 SLOW PATH: Checking legacy invoices without invoice_number column...")
        success_invoices = db.query(SuccessModel).filter(
            SuccessModel.user_id == user_id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.invoice_number.is_(None)  # Only check records without invoice_number
        ).order_by(SuccessModel.uploaded_at.desc()).limit(500).all()
        
        logger.info(f"   Found {len(success_invoices)} legacy successful invoices to check against")
        if len(success_invoices) == 0:
            logger.info(f"   No legacy invoices found - all invoices have invoice_number column!")
        
        # Check each successful invoice's XML content for matching invoice number
        checked_count = 0
        errors_count = 0
        for invoice in success_invoices:
            try:
                checked_count += 1
                # Get XML path (blob or local)
                xml_path = invoice.blob_xml_path or invoice.xml_path
                
                if not xml_path:
                    logger.warning(f"   [{checked_count}/{len(success_invoices)}] Invoice {invoice.id} has no XML path - this shouldn't happen!")
                    errors_count += 1
                    continue
                
                # Read XML content (async)
                xml_content_bytes = await read_file_from_storage(xml_path, None, None)
                
                if not xml_content_bytes:
                    logger.warning(f"   [{checked_count}/{len(success_invoices)}] Invoice {invoice.id} XML file could not be read from {xml_path}")
                    errors_count += 1
                    continue
                
                xml_content = xml_content_bytes.decode('utf-8')
                # Extract invoice number from this invoice
                existing_invoice_number = extract_invoice_number_from_xml(xml_content)
                
                if not existing_invoice_number:
                    logger.warning(f"   [{checked_count}/{len(success_invoices)}] Invoice {invoice.id} has no extractable invoice number - this shouldn't happen!")
                    errors_count += 1
                    continue
                
                # Compare invoice numbers (case-insensitive)
                if existing_invoice_number.upper() == invoice_number.upper():
                    logger.warning(f"🚫🚫🚫 DUPLICATE FOUND IN SUCCESS TABLE! 🚫🚫🚫")
                    logger.warning(f"   New Invoice Number: {invoice_number}")
                    logger.warning(f"   Existing Invoice Number: {existing_invoice_number}")
                    logger.warning(f"   Existing Invoice ID: {invoice.id}")
                    logger.warning(f"   Existing Tracking ID: {invoice.tracking_id}")
                    logger.warning(f"   Existing Upload Date: {invoice.uploaded_at}")
                    logger.warning(f"   Existing Source: {invoice.request_type or 'web'}")
                    logger.warning(f"   USER ATTEMPTED TO UPLOAD DUPLICATE - BLOCKING!")
                    result = (True, invoice.id)
                    # Cache the result
                    _duplicate_check_cache[cache_key] = (result, current_time)
                    return result
                else:
                    logger.debug(f"   [{checked_count}/{len(success_invoices)}] Invoice {invoice.id} #{existing_invoice_number} - not a match")
                    
            except Exception as read_err:
                logger.error(f"   [{checked_count}/{len(success_invoices)}] ERROR checking invoice {invoice.id}: {read_err}")
                import traceback
                logger.error(traceback.format_exc())
                errors_count += 1
                continue
        
        logger.info(f"   Checked {checked_count} successful invoices - no duplicates found")
        if errors_count > 0:
            logger.error(f"   ⚠️  WARNING: {errors_count} invoices could not be checked due to errors!")
            logger.error(f"   This means duplicate detection may not be reliable!")
        
        # If check_failed is True (for SAP API), also check failed invoices
        if check_failed:
            failed_invoices = db.query(FailedModel).filter(
                FailedModel.user_id == user_id,
                FailedModel.deleted_at.is_(None)
            ).order_by(FailedModel.uploaded_at.desc()).limit(500).all()
            
            logger.info(f"   Found {len(failed_invoices)} failed invoices to check against")
            if len(failed_invoices) == 0:
                logger.info(f"   No failed invoices found")
            
            failed_checked_count = 0
            for invoice in failed_invoices:
                failed_checked_count += 1
                try:
                    # Get XML path (blob or local)
                    xml_path = invoice.blob_xml_path or invoice.xml_path
                    
                    if not xml_path:
                        logger.debug(f"   [FAILED {failed_checked_count}/{len(failed_invoices)}] Invoice {invoice.id} has no XML path - skipping")
                        continue
                    
                    # Read XML content (async)
                    xml_content_bytes = await read_file_from_storage(xml_path, None, None)
                    
                    if not xml_content_bytes:
                        logger.debug(f"   [FAILED {failed_checked_count}/{len(failed_invoices)}] Invoice {invoice.id} XML file could not be read - skipping")
                        continue
                    
                    xml_content = xml_content_bytes.decode('utf-8')
                    # Extract invoice number from this invoice
                    existing_invoice_number = extract_invoice_number_from_xml(xml_content)
                    
                    if not existing_invoice_number:
                        logger.debug(f"   [FAILED {failed_checked_count}/{len(failed_invoices)}] Invoice {invoice.id} has no extractable invoice number - skipping")
                        continue
                    
                    # Compare invoice numbers (case-insensitive)
                    if existing_invoice_number.upper() == invoice_number.upper():
                        logger.warning(f"🚫🚫🚫 DUPLICATE FOUND IN FAILED TABLE! 🚫🚫🚫")
                        logger.warning(f"   New Invoice Number: {invoice_number}")
                        logger.warning(f"   Existing Invoice Number: {existing_invoice_number}")
                        logger.warning(f"   Existing Invoice ID: {invoice.id}")
                        logger.warning(f"   Existing Tracking ID: {invoice.tracking_id}")
                        logger.warning(f"   Existing Upload Date: {invoice.uploaded_at}")
                        logger.warning(f"   Existing Source: {invoice.request_type or 'web'}")
                        logger.warning(f"   This prevents duplicate processing (from SAP API)")
                        result = (True, invoice.id)
                        # Cache the result
                        _duplicate_check_cache[cache_key] = (result, current_time)
                        return result
                    else:
                        logger.debug(f"   [FAILED {failed_checked_count}/{len(failed_invoices)}] Invoice {invoice.id} #{existing_invoice_number} - not a match")
                        
                except Exception as read_err:
                    logger.warning(f"   [FAILED {failed_checked_count}/{len(failed_invoices)}] Error checking invoice {invoice.id}: {read_err}")
                    continue
            
            logger.info(f"   Checked {failed_checked_count} failed invoices - no duplicates found")
        
        logger.info(f"✅✅✅ NO DUPLICATE FOUND - Invoice #{invoice_number} is UNIQUE!")
        logger.info(f"   Total invoices checked: {checked_count} successful" + (f" + {failed_checked_count} failed" if check_failed else ""))
        logger.info(f"🔍 ============ DUPLICATE CHECK END ============")
        result = (False, None)
        # 🚫 DO NOT cache negative results! The state can change - an invoice that's not a duplicate now
        # will become a duplicate after it's successfully uploaded. Only cache positive (duplicate found) results.
        # _duplicate_check_cache[cache_key] = (result, current_time)  # REMOVED - don't cache negatives
        return result
        
    except Exception as e:
        logger.error(f"❌ Error checking invoice duplication: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # If check fails, allow upload to proceed (fail open for safety)
        return False, None

class FormatEnum(str, Enum):
    xml = "xml"
    x12 = "x12"
    x12embed = "x12_embed"
    edifact = "edifact"

# X12 modules will be used for OUTPUT validation, not input processing

async def send_file_to_external(
    file_content: str,
    invoice_id: str,
    format_type: str = "xml"
) -> dict:
    """
    Send a single file (XML, X12, etc.) to an external API.

    Args:
        file_content: The file content as a string.
        invoice_id: The invoice identifier for tracking/logging.
        format_type: One of ['xml', 'x12', 'x12embed', 'edifact'].

    Returns:
        dict: {
            "invoice_id": str,
            "status": "success" | "error",
            "akt_id": Optional[str],
            "error": Optional[str]
        }
    """
    AUTH_URL = "http://dbnasender.cfdise.com/PeppolSoftDBNA/auth/login"
    EXTERNAL_ENDPOINTS = {
        "xml": "http://dbnasender.cfdise.com/PeppolSoftDBNA/generateDocument",
        "x12": "http://dbnasender.cfdise.com/PeppolSoftDBNA/generateDocument",
        "x12embed": "http://dbnasender.cfdise.com/PeppolSoftDBNA/generateDocument",
        "edifact": "http://dbnasender.cfdise.com/PeppolSoftDBNA/generateDocument",
    }
    USERNAME = "peppolsoft"
    PASSWORD = "t3st2025"

    # 🧾 Supported formats and MIME types
    FORMAT_MIME = {
        "xml": "application/xml",
        "x12": "application/edi-x12",
        "x12embed": "application/edi-x12",
        "edifact": "application/edifact"
    }
    try:
        format_type = format_type.lower()
        if format_type not in FORMAT_MIME:
            raise ValueError(f"Unsupported format: {format_type}")

        mime_type = FORMAT_MIME[format_type]
        endpoint = EXTERNAL_ENDPOINTS.get(format_type)

        if not endpoint:
            raise ValueError(
                f"No endpoint configured for format '{format_type}'")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1️⃣ Authenticate
            auth_resp = await client.post(AUTH_URL, json={"user": USERNAME, "password": PASSWORD})
            if auth_resp.status_code != 200:
                return {
                    "invoice_id": invoice_id,
                    "status": "error",
                    "akt_id": None,
                    "error": "Authentication with external service failed"
                }

            token = auth_resp.json().get("accessToken")
            if not token:
                return {
                    "invoice_id": invoice_id,
                    "status": "error",
                    "akt_id": None,
                    "error": "No access token received from external service"
                }

            # 2️⃣ Send file
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": mime_type
            }

            send_resp = await client.post(endpoint, content=file_content.encode("utf-8"), headers=headers)
            response_text = send_resp.text

            # 3️⃣ Parse response (simple XML parsing using regex)
            code_match = re.search(r"<code>(\d+)</code>", response_text)
            akt_id = code_match.group(1) if code_match else "unknown"

            message_match = re.search(
                r"<message>(.*?)</message>", response_text, re.DOTALL)
            error_list_match = re.search(
                r"<errorList>(.*?)</errorList>", response_text, re.DOTALL)

            message = message_match.group(1).strip() if message_match else ""
            error_list = error_list_match.group(
                1).strip() if error_list_match else ""

            # 4️⃣ Handle response status
            if send_resp.status_code >= 400:
                return {
                    "invoice_id": invoice_id,
                    "status": "error",
                    "akt_id": akt_id,
                    "error": f"Upload failed: {message or error_list or response_text}"
                }

            return {
                "invoice_id": invoice_id,
                "status": "success",
                "akt_id": akt_id,
                "error": None
            }

    except Exception as e:
        logger.error(f"❌ Error sending invoice {invoice_id}: {e}")
        return {
            "invoice_id": invoice_id,
            "status": "error",
            "akt_id": None,
            "error": str(e)
        }

@router.post("/process", response_model=InvoiceProcessingResponse)
async def process_invoice(
    file: UploadFile = File(...),
    strict_validation: bool = False,
    db: Session = Depends(get_db),
    request: Request = None,
    current_user: ZodiacUser = Depends(get_current_user)
):
    """Process uploaded invoice file with XML validation and EDI conversion (Web UI)
    Returns tracking_id immediately for real-time status tracking, then processes in background"""
    # Read file content first (needed before processing)
    file_content = await file.read()
    original_filename = file.filename
    
    # Check for duplicate invoice number before processing
    try:
        invoice_number = extract_invoice_number_from_xml(file_content.decode('utf-8'))
        logger.info(f"📄 Extracted invoice number from upload: {invoice_number}")
        
        if not invoice_number:
            # CRITICAL FIX: Require invoice number extraction to succeed
            # This prevents duplicates from slipping through when extraction fails
            logger.error(f"❌ INVOICE NUMBER EXTRACTION FAILED - Cannot validate for duplicates")
            logger.error(f"   File: {original_filename}")
            logger.error(f"   User: {current_user.id}")
            logger.error(f"   This upload is REJECTED to prevent duplicate invoices")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "Invoice number extraction failed",
                    "message": "Could not extract invoice number from XML. The file may be in an unsupported format or missing required invoice number fields (cbc:ID for UBL, Serie/Folio for SAT CFDI).",
                    "supported_formats": ["UBL 2.1 (cbc:ID)", "SAT CFDI (Serie-Folio)"],
                    "action": "Check that your XML file contains a valid invoice number field"
                }
            )
        
        # For manual uploads, only check successful invoices (allow retrying failed ones)
        already_exists, existing_id = await check_invoice_already_processed(
            db, 
            invoice_number, 
            current_user.id,
            check_failed=False,
            source="manual"
        )
        if already_exists:
            logger.error(f"🚫 DUPLICATE DETECTED - Invoice #{invoice_number} already exists!")
            logger.error(f"   Existing invoice ID: {existing_id}")
            logger.error(f"   User: {current_user.id}")
            logger.error(f"   This upload is REJECTED")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "Duplicate invoice detected",
                    "invoice_number": invoice_number,
                    "existing_invoice_id": existing_id,
                    "message": f"Invoice #{invoice_number} has already been successfully processed and cannot be uploaded again.",
                    "action": "view_existing",
                    "suggestion": "View the existing invoice in your invoices list, or retry only if the previous upload failed."
                }
            )
        logger.info(f"✅ Invoice #{invoice_number} is new, proceeding with processing")
        
        # CRITICAL: Mark this invoice as being processed to prevent race conditions
        processing_key = (current_user.id, invoice_number.upper())
        _processing_invoices[processing_key] = time.time()
        logger.info(f"🔒 Marked invoice #{invoice_number} as PROCESSING (prevents concurrent duplicates)")
        logger.info(f"   Current processing queue size: {len(_processing_invoices)}")
        
    except HTTPException:
        # Re-raise HTTP exceptions (duplicate or extraction failure)
        raise
    except Exception as e:
        # Unexpected errors should also block upload for safety
        logger.error(f"❌ UNEXPECTED ERROR during duplicate check: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Duplicate check failed",
                "message": "An unexpected error occurred while checking for duplicate invoices. Upload blocked for safety.",
                "technical_details": str(e)
            }
        )
    
    # Generate tracking ID and initialize status tracker immediately
    tracking_id = uuid.uuid4()
    status_tracker.initialize_status(tracking_id)
    logger.info(f"🆔 Generated tracking ID: {tracking_id} (returning immediately for real-time tracking)")
    
    # Store invoice_number with tracking_id for cleanup later
    stored_invoice_number = invoice_number
    
    # Create a new file-like object from the content for background processing
    from io import BytesIO
    import asyncio
    
    # Process in background - create new DB session for background task
    async def process_background():
        db_session = SessionLocal()
        try:
            logger.info(f"🔄 ===== BACKGROUND PROCESSING STARTED =====")
            logger.info(f"🆔 Background task for tracking_id: {tracking_id}")
            
            # Create new UploadFile for background task with proper headers
            from starlette.datastructures import Headers
            content_type = file.content_type if file.content_type else "application/xml"
            headers = Headers({"content-type": content_type})
            background_file = UploadFile(
                filename=original_filename,
                file=BytesIO(file_content),
                headers=headers
            )
            
            logger.info(f"📄 Background task - calling process_invoice_internal...")
            
            # Pass the tracking_id to process_invoice_internal so it uses the same one
            result = await process_invoice_internal(background_file, strict_validation, db_session, request, current_user, "web", tracking_id)
            
            logger.info(f"✅ Background processing completed for tracking_id {tracking_id}")
            
        except ImportError as import_err:
            logger.error(f"❌❌❌ IMPORT ERROR in background task: {str(import_err)}")
            import traceback
            logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
            # Update status tracker with error
            from ..schemas.invoice import ProcessingStepResult
            error_step = ProcessingStepResult(
                step_name="Import Error",
                step_number=2,
                success=False,
                duration_seconds=0,
                message=f"Module import failed: {str(import_err)}"
            )
            status_tracker.update_step(tracking_id, error_step)
        except Exception as e:
            logger.error(f"❌❌❌ BACKGROUND PROCESSING ERROR for tracking_id {tracking_id}: {str(e)}")
            import traceback
            logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
            # Update status tracker with error
            from ..schemas.invoice import ProcessingStepResult
            error_step = ProcessingStepResult(
                step_name="Processing Error",
                step_number=2,
                success=False,
                duration_seconds=0,
                message=f"Error: {str(e)}"
            )
            status_tracker.update_step(tracking_id, error_step)
        finally:
            # CRITICAL: Remove from processing queue after completion/failure
            processing_key = (current_user.id, stored_invoice_number.upper())
            if processing_key in _processing_invoices:
                del _processing_invoices[processing_key]
                logger.info(f"🔓 Removed invoice #{stored_invoice_number} from processing queue")
            
            logger.info(f"🔚 Background task finished for tracking_id {tracking_id}")
            db_session.close()
    
    # Start background processing (non-blocking)
    logger.info(f"🚀 Starting background task for tracking_id {tracking_id}")
    asyncio.create_task(process_background())
    logger.info(f"✅ Background task created, returning 202 to frontend")
    
    # Return immediately with tracking_id so frontend can start polling
    initial_response = InvoiceProcessingResponse(
        tracking_id=tracking_id,
        processing_steps=[]
    )
    response_dict = initial_response.dict()
    response_dict['tracking_id'] = str(response_dict['tracking_id'])
    # Return dict directly - JSONResponse will handle serialization
    return JSONResponse(
        content=response_dict,
        status_code=status.HTTP_202_ACCEPTED  # 202 Accepted - processing started
    )


@router.get("/api/health-check")
async def sap_health_check(
    db: Session = Depends(get_db),
    api_user: ZodiacUser = Depends(get_api_user)
):
    """
    Health check endpoint for SAP integration - tests authentication and connectivity.
    
    This endpoint allows SAP to verify:
    - API key authentication is working
    - Network connectivity is established
    - User account is active
    - System is ready to receive invoices
    
    Returns:
        - status: "ok" if healthy
        - authenticated: True if API key is valid
        - user_id: ID of the authenticated user
        - username: Username of the authenticated user
        - timestamp: Current server time
        - version: API version
    """
    logger.info(f"🏥 ===== SAP HEALTH CHECK =====")
    logger.info(f"   User ID: {api_user.id}")
    logger.info(f"   Username: {api_user.username}")
    logger.info(f"   Email: {api_user.email}")
    logger.info(f"   Account Active: {api_user.is_active}")
    logger.info(f"   Health check SUCCESSFUL")
    
    return {
        "status": "ok",
        "authenticated": True,
        "user_id": api_user.id,
        "username": api_user.username,
        "email": api_user.email,
        "is_active": api_user.is_active,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "message": "SAP integration is ready to receive invoices",
        "endpoints": {
            "health_check": "/api/v1/invoices/api/health-check",
            "upload_invoice": "/api/v1/invoices/api/process",
            "check_status": "/api/v1/invoices/status/{tracking_id}"
        }
    }


@router.post("/api/process", response_model=InvoiceProcessingResponse)
async def process_invoice_api(
    file: UploadFile = File(...),
    strict_validation: bool = False,
    db: Session = Depends(get_db),
    request: Request = None,
    api_user: ZodiacUser = Depends(get_api_user)
    # api_user:str = "DEMO"
):
    """
    Process uploaded invoice file with XML validation and EDI conversion (SAP API Key endpoint).
    
    This endpoint is for SAP and other external systems using API key authentication.
    Returns processing results synchronously (unlike web endpoint which returns tracking_id immediately).
    """
    logger.info(f"🔑 ===== SAP API ENDPOINT CALLED =====")
    logger.info(f"👤 API User ID: {api_user.id}")
    logger.info(f"👤 API Username: {api_user.username}")
    logger.info(f"📄 Filename: {file.filename}")
    logger.info(f"📄 Content Type: {file.content_type}")
    logger.info(f"   request_type will be set to: 'api'")
    
    # Wrap entire processing in try-catch to ensure SAP always gets a response
    try:
        # Check for duplicate invoice number before processing
        try:
            file_content = await file.read()
            invoice_number = extract_invoice_number_from_xml(file_content.decode('utf-8'))
            logger.info(f"📄 [SAP] Extracted invoice number from upload: {invoice_number}")
            
            if not invoice_number:
                # For SAP API, require invoice number extraction (prevents duplicates)
                logger.error(f"❌ [SAP] INVOICE NUMBER EXTRACTION FAILED")
                logger.error(f"   Filename: {file.filename}")
                logger.error(f"   User: {api_user.id}")
                logger.error(f"   This upload is REJECTED to prevent duplicate invoices")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "Invoice number extraction failed",
                        "message": "Could not extract invoice number from XML. The file may be in an unsupported format or missing required invoice number fields.",
                        "supported_formats": ["UBL 2.1 (cbc:ID)", "SAT CFDI (Serie-Folio)"],
                        "filename": file.filename,
                        "source": "sap_api"
                    }
                )
            
            # For SAP API, only check successful invoices (allow retrying failed ones)
            # This matches web UI behavior: successful invoices blocked, failed invoices can be retried
            already_exists, existing_id = await check_invoice_already_processed(
                db, 
                invoice_number, 
                api_user.id,
                check_failed=False,  # Only check successful, allow retry of failed
                source="api"
            )
            if already_exists:
                logger.error(f"🚫 [SAP] DUPLICATE DETECTED - Invoice #{invoice_number} already exists!")
                logger.error(f"   Existing invoice ID: {existing_id}")
                logger.error(f"   This upload is REJECTED")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "Duplicate invoice detected",
                        "invoice_number": invoice_number,
                        "existing_invoice_id": existing_id,
                        "message": f"Invoice #{invoice_number} has already been successfully processed and cannot be uploaded again.",
                        "source": "sap_api",
                        "action": "This invoice was previously uploaded and processed successfully. You can only retry failed invoices."
                    }
                )
            logger.info(f"✅ [SAP] Invoice #{invoice_number} is new, proceeding with processing")
            
            # Reset file pointer for processing
            from io import BytesIO
            from starlette.datastructures import Headers
            file = UploadFile(
                filename=file.filename,
                file=BytesIO(file_content),
                headers=Headers({"content-type": file.content_type})
            )
        except HTTPException:
            # Re-raise HTTP exceptions (duplicate or extraction failure)
            raise
        except Exception as e:
            # Unexpected errors during duplicate check - block upload for safety
            logger.error(f"❌ [SAP] UNEXPECTED ERROR during duplicate check: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "Duplicate check failed",
                    "message": "An unexpected error occurred while checking for duplicate invoices. Upload blocked for safety.",
                    "technical_details": str(e),
                    "source": "sap_api"
                }
            )
        
        # Process the invoice
        logger.info(f"🔄 [SAP] Calling process_invoice_internal...")
        result = await process_invoice_internal(file, strict_validation, db, request, api_user, "api")
        logger.info(f"✅ [SAP] Processing completed successfully")
        logger.info(f"🔑 ===== SAP API ENDPOINT FINISHED =====")
        return result
        
    except HTTPException as http_err:
        # Log and re-raise HTTP exceptions
        logger.error(f"❌ [SAP] HTTP Exception: {http_err.status_code} - {http_err.detail}")
        logger.error(f"🔑 ===== SAP API ENDPOINT FAILED (HTTP {http_err.status_code}) =====")
        raise
    except Exception as e:
        # Catch any unexpected errors and return structured response to SAP
        logger.error(f"❌❌❌ [SAP] UNEXPECTED ERROR: {e}")
        import traceback
        logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
        logger.error(f"🔑 ===== SAP API ENDPOINT FAILED (UNEXPECTED ERROR) =====")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Processing failed",
                "message": "An unexpected error occurred while processing the invoice.",
                "technical_details": str(e),
                "source": "sap_api",
                "action": "Please contact support with this error message."
            }
        )

@router.get("/api-key")
async def get_api_key(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's API key information"""
    try:
        logger.info(f"🔑 API Key request for user {current_user.id}")

        # Check if user has API access
        if not current_user.api_user_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API access is not allowed for this user"
            )

        # Check if user has an API key
        if not current_user.api_key_hashed:
            return {
                "has_key": False,
                "message": "No API key generated yet"
            }

        # Check if key is deactivated
        if current_user.api_key_deactivated_at:
            return {
                "has_key": True,
                "is_active": False,
                "deactivated_at": current_user.api_key_deactivated_at.isoformat(),
                "message": "API key is deactivated"
            }

        return {
            "has_key": True,
            "is_active": True,
            "api_user_identifier": current_user.api_user_identifier,
            "created_at": current_user.api_key_created_at.isoformat() if current_user.api_key_created_at else None,
            "updated_at": current_user.api_key_updated_at.isoformat() if current_user.api_key_updated_at else None,
            "allow_list": current_user.api_key_allow_list or [],
            "message": "API key is active"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get API key: {str(e)}"
        )


@router.post("/api-key/generate")
async def generate_new_api_key(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a new API key for the current user"""
    try:
        logger.info(f"🔑 Generating new API key for user {current_user.id}")

        # Check if user has API access
        if not current_user.api_user_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API access is not allowed for this user"
            )

        # Generate new API key
        new_api_key = generate_api_key()
        hashed_key = hash_api_key(new_api_key)

        # Update user record
        current_user.api_key_hashed = hashed_key
        current_user.api_key_created_at = datetime.utcnow()
        current_user.api_key_updated_at = datetime.utcnow()
        # Reactivate if previously deactivated
        current_user.api_key_deactivated_at = None

        db.commit()
        db.refresh(current_user)

        logger.info(f"✅ New API key generated for user {current_user.id}")

        return {
            "success": True,
            "api_key": encode_api_key_for_transport(new_api_key),
            "api_user_identifier": current_user.api_user_identifier,
            "created_at": current_user.api_key_created_at.isoformat(),
            "message": "New API key generated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate API key: {str(e)}"
        )


@router.post("/api-key/regenerate")
async def regenerate_api_key(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Regenerate API key for the current user (confirmation required)"""
    try:
        logger.info(f"🔑 Regenerating API key for user {current_user.id}")

        # Check if user has API access
        if not current_user.api_user_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API access is not allowed for this user"
            )

        # Generate new API key
        new_api_key = generate_api_key()
        hashed_key = hash_api_key(new_api_key)

        # Update user record
        current_user.api_key_hashed = hashed_key
        current_user.api_key_updated_at = datetime.utcnow()
        # Reactivate if previously deactivated
        current_user.api_key_deactivated_at = None

        db.commit()
        db.refresh(current_user)

        logger.info(f"✅ API key regenerated for user {current_user.id}")

        return {
            "success": True,
            "api_key": encode_api_key_for_transport(new_api_key),
            "api_user_identifier": current_user.api_user_identifier,
            "updated_at": current_user.api_key_updated_at.isoformat(),
            "message": "API key regenerated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to regenerate API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate API key: {str(e)}"
        )


@router.post("/api-key/suspend")
async def suspend_api_key(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Suspend the current user's API key"""
    try:
        logger.info(f"🔑 Suspending API key for user {current_user.id}")

        # Check if user has an API key
        if not current_user.api_key_hashed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No API key found to suspend"
            )

        # Suspend the API key
        current_user.api_key_deactivated_at = datetime.utcnow()
        current_user.api_key_updated_at = datetime.utcnow()

        db.commit()
        db.refresh(current_user)

        logger.info(f"✅ API key suspended for user {current_user.id}")

        return {
            "success": True,
            "deactivated_at": current_user.api_key_deactivated_at.isoformat(),
            "message": "API key suspended successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to suspend API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to suspend API key: {str(e)}"
        )


@router.post("/api-key/activate")
async def activate_api_key(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Activate the current user's API key"""
    try:
        logger.info(f"🔑 Activating API key for user {current_user.id}")

        # Check if user has an API key
        if not current_user.api_key_hashed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No API key found to activate"
            )

        # Activate the API key
        current_user.api_key_deactivated_at = None
        current_user.api_key_updated_at = datetime.utcnow()

        db.commit()
        db.refresh(current_user)

        logger.info(f"✅ API key activated for user {current_user.id}")

        return {
            "success": True,
            "updated_at": current_user.api_key_updated_at.isoformat(),
            "message": "API key activated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to activate API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate API key: {str(e)}"
        )


@router.post("/api-key/allow-list")
async def update_api_key_allow_list(
    allow_list: list[str],
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update the API key allow list (IP addresses)"""
    try:
        logger.info(
            f"🔑 Updating API key allow list for user {current_user.id}")

        # Check if user has an API key
        if not current_user.api_key_hashed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No API key found to update"
            )

        # Validate IP addresses (basic validation)
        import re
        ip_pattern = re.compile(
            r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')

        for ip in allow_list:
            if not ip_pattern.match(ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid IP address format: {ip}"
                )

        # Update allow list
        current_user.api_key_allow_list = allow_list
        current_user.api_key_updated_at = datetime.utcnow()

        db.commit()
        db.refresh(current_user)

        logger.info(
            f"✅ API key allow list updated for user {current_user.id}: {allow_list}")

        return {
            "success": True,
            "allow_list": current_user.api_key_allow_list,
            "updated_at": current_user.api_key_updated_at.isoformat(),
            "message": "API key allow list updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to update API key allow list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update API key allow list: {str(e)}"
        )


@router.get("/counts")
async def get_invoice_counts(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get invoice counts for the current user"""
    try:
        # Get counts for the current user
        successful_count = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).count()

        failed_count = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).count()

        deleted_count = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.isnot(None)
        ).count()

        # Also count deleted successful invoices
        deleted_success_count = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.isnot(None)
        ).count()

        total_deleted = deleted_count + deleted_success_count
        total_files = successful_count + failed_count

        logger.info(f"📊 Invoice counts for user {current_user.id}:")
        logger.info(f"📊 - Successful: {successful_count}")
        logger.info(f"📊 - Failed: {failed_count}")
        logger.info(f"📊 - Deleted: {total_deleted}")
        logger.info(f"📊 - Total: {total_files}")

        return {
            "successful": successful_count,
            "failed": failed_count,
            "deleted": total_deleted,
            "total": total_files,
            "processing": 0  # We don't track processing state currently
        }
    except Exception as e:
        logger.error(f"❌ Failed to get invoice counts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get invoice counts: {str(e)}"
        )


@router.get("/test")
async def get_dashboard_statistics(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 30  # Default to last 30 days
):
    """Get comprehensive dashboard statistics including timeline, customer distribution, and format breakdown"""
    try:
        logger.info(f"📊 Fetching dashboard statistics for user {current_user.id} (last {days} days)")
        
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # 1. Overall Statistics
        successful_count = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).count()
        
        failed_count = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).count()
        
        total_count = successful_count + failed_count
        success_rate = (successful_count / total_count * 100) if total_count > 0 else 0
        
        # 2. Timeline Data (invoices per day for the last N days)
        # Successful invoices timeline
        success_timeline = db.query(
            cast(SuccessModel.uploaded_at, Date).label('date'),
            func.count(SuccessModel.id).label('count')
        ).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.uploaded_at >= start_date
        ).group_by(cast(SuccessModel.uploaded_at, Date)).all()
        
        # Failed invoices timeline
        failed_timeline = db.query(
            cast(FailedModel.uploaded_at, Date).label('date'),
            func.count(FailedModel.id).label('count')
        ).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None),
            FailedModel.uploaded_at >= start_date
        ).group_by(cast(FailedModel.uploaded_at, Date)).all()
        
        # Merge timelines
        timeline_dict = defaultdict(lambda: {"date": None, "successful": 0, "failed": 0, "total": 0})
        
        for item in success_timeline:
            date_str = item.date.strftime('%Y-%m-%d')
            timeline_dict[date_str]["date"] = date_str
            timeline_dict[date_str]["successful"] = item.count
            timeline_dict[date_str]["total"] += item.count
        
        for item in failed_timeline:
            date_str = item.date.strftime('%Y-%m-%d')
            timeline_dict[date_str]["date"] = date_str
            timeline_dict[date_str]["failed"] = item.count
            timeline_dict[date_str]["total"] += item.count
        
        # Convert to sorted list
        timeline_data = sorted(timeline_dict.values(), key=lambda x: x["date"])
        
        # 3. Format Distribution (from successful invoices)
        format_distribution_query = db.query(
            SuccessModel.target_file_format,
            func.count(SuccessModel.id).label('count')
        ).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None),
            SuccessModel.target_file_format.isnot(None)
        ).group_by(SuccessModel.target_file_format).all()
        
        format_distribution = [
            {"format": item.target_file_format or "Unknown", "count": item.count}
            for item in format_distribution_query
        ]
        
        # 4. Top Customers (extract from processing_steps if available)
        # This is a simplified version - you may need to adjust based on how customer info is stored
        success_invoices = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).limit(1000).all()  # Limit for performance
        
        customer_stats = defaultdict(lambda: {"successful": 0, "failed": 0})
        
        # Extract customer from file paths or processing steps
        for invoice in success_invoices:
            # Try to extract customer ID from processing steps or use a placeholder
            customer_id = "Unknown"
            if invoice.processing_steps:
                # Look for customer info in processing steps
                for step in invoice.processing_steps:
                    if isinstance(step, dict) and 'message' in step:
                        # You might have customer info in messages
                        pass
            
            # For now, use a generic approach - you can enhance this
            # Extract from xml_path if it contains customer info
            if invoice.xml_path:
                # Example: uploads/tracking_id_customer.xml
                parts = invoice.xml_path.split('/')
                if len(parts) > 1:
                    filename = parts[-1]
                    # Try to extract customer from filename
                    customer_id = filename.split('_')[0] if '_' in filename else "Unknown"
            
            customer_stats[customer_id]["successful"] += 1
        
        # Convert to list and get top 10
        customer_distribution = [
            {"customer": customer, "successful": stats["successful"], "failed": stats["failed"], "total": stats["successful"] + stats["failed"]}
            for customer, stats in customer_stats.items()
        ]
        customer_distribution = sorted(customer_distribution, key=lambda x: x["total"], reverse=True)[:10]
        
        # 5. Request Type Distribution (Web vs API)
        request_type_query = db.query(
            SuccessModel.request_type,
            func.count(SuccessModel.id).label('count')
        ).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).group_by(SuccessModel.request_type).all()
        
        request_type_distribution = [
            {"type": item.request_type or "web", "count": item.count}
            for item in request_type_query
        ]
        
        # 6. Recent Activity (last 10 invoices)
        recent_success = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)
        ).order_by(SuccessModel.uploaded_at.desc()).limit(5).all()
        
        recent_failed = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)
        ).order_by(FailedModel.uploaded_at.desc()).limit(5).all()
        
        recent_activity = []
        for inv in recent_success:
            recent_activity.append({
                "id": inv.id,
                "tracking_id": str(inv.tracking_id),
                "status": "successful",
                "format": inv.target_file_format,
                "uploaded_at": inv.uploaded_at.isoformat() if inv.uploaded_at else None,
                "request_type": inv.request_type
            })
        
        for inv in recent_failed:
            recent_activity.append({
                "id": inv.id,
                "tracking_id": str(inv.tracking_id),
                "status": "failed",
                "format": inv.target_file_format,
                "uploaded_at": inv.uploaded_at.isoformat() if inv.uploaded_at else None,
                "request_type": inv.request_type
            })
        
        # Sort by date
        recent_activity = sorted(recent_activity, key=lambda x: x["uploaded_at"] or "", reverse=True)[:10]
        
        logger.info(f"✅ Dashboard statistics calculated successfully")
        
        return {
            "overview": {
                "total": total_count,
                "successful": successful_count,
                "failed": failed_count,
                "success_rate": round(success_rate, 2)
            },
            "timeline": timeline_data,
            "format_distribution": format_distribution,
            "customer_distribution": customer_distribution,
            "request_type_distribution": request_type_distribution,
            "recent_activity": recent_activity,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get dashboard statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dashboard statistics: {str(e)}"
        )


@router.get("/test")
def test_endpoint(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test endpoint to check database connection and data"""
    try:
        logger.info(f"🧪 Test endpoint called for user {current_user.id}")

        # Test basic database query
        user_count = db.query(ZodiacUser).count()
        logger.info(f"📊 Total users in DB: {user_count}")

        # Test failed invoices table with raw SQL to avoid schema issues
        try:
            failed_count = db.execute(
                text("SELECT COUNT(*) FROM zodiac_invoice_failed_edi")).scalar()
            logger.info(f"📊 Total failed invoices in DB: {failed_count}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to count failed invoices: {e}")
            failed_count = 0

        # Test success invoices table with raw SQL
        try:
            success_count = db.execute(
                text("SELECT COUNT(*) FROM zodiac_invoice_success_edi")).scalar()
            logger.info(f"📊 Total success invoices in DB: {success_count}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to count success invoices: {e}")
            success_count = 0

        return {
            "user_id": current_user.id,
            "total_users": user_count,
            "total_failed": failed_count,
            "total_success": success_count
        }

    except Exception as e:
        logger.error(f"❌ Test endpoint error: {str(e)}")
        return {"error": str(e)}


@router.get("/success")
def get_successful_invoices(
    skip: int = 0,
    limit: int = 50,  # Reduced default limit for better performance
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get successfully processed invoices for current user"""
    try:
        # Cache column inspection results for better performance
        if not hasattr(get_successful_invoices, '_column_cache'):
            inspector = inspect(db.bind)
            columns = [col["name"]
                       for col in inspector.get_columns("zodiac_invoice_success_edi")]
            
            # Cache the results
            get_successful_invoices._column_cache = {
                'has_external_status': "external_status" in columns,
                'has_external_message': "external_message" in columns,
                'has_target_file_format': "target_file_format" in columns,
                'has_request_type': "request_type" in columns
            }
        
        # Use cached values
        cache = get_successful_invoices._column_cache
        has_external_status = cache['has_external_status']
        has_external_message = cache['has_external_message']
        has_target_file_format = cache['has_target_file_format']
        has_request_type = cache['has_request_type']

        # Build query dynamically
        query = f"""
            SELECT id, tracking_id, user_id, uploaded_at, xml_path, 
                xml_validation_pass, xml_convert_message, edi_path, 
                edi_convert_pass, edi_convert_message, processing_steps,
                blob_xml_path, blob_edi_path,
                {"external_status" if has_external_status else "'False' AS external_status"},
                {"external_message" if has_external_message else "'No msg' AS external_message"},
                {"target_file_format" if has_target_file_format else "'X12' AS target_file_format"},
                {"request_type" if has_request_type else "'web' AS request_type"}
            FROM zodiac_invoice_success_edi 
            WHERE user_id = :user_id AND deleted_at IS NULL
            ORDER BY uploaded_at DESC 
            LIMIT :limit OFFSET :offset
        """
        
        result = db.execute(text(query), {
            "user_id": current_user.id,
            "limit": limit,
            "offset": skip
        }).fetchall()

        # Convert to model instances
        invoices = []
        for row in result:
            invoice = SuccessModel(
                id=row.id,
                tracking_id=row.tracking_id,
                user_id=row.user_id,
                uploaded_at=row.uploaded_at,
                xml_path=row.blob_xml_path if row.blob_xml_path else row.xml_path,
                xml_validation_pass=row.xml_validation_pass,
                xml_convert_message=row.xml_convert_message,
                edi_path=row.blob_edi_path if row.blob_edi_path else row.edi_path,
                edi_convert_pass=row.edi_convert_pass,
                edi_convert_message=row.edi_convert_message,
                processing_steps=row.processing_steps,
                blob_xml_path=row.blob_xml_path,
                blob_edi_path=row.blob_edi_path,
                external_status=row.external_status,
                external_message=row.external_message,
                target_file_format=getattr(row, 'target_file_format', 'X12')
            )

            # Add computed fields after model creation
            invoice.xml_content = ""
            invoice.edi_content = ""
            invoice.info = {}
            data = vars(invoice).copy()
            data.pop("_sa_instance_state", None)

            # Safely extract and merge invoice info
            try:
                # Determine which file to extract from based on format
                target_format = getattr(row, 'target_file_format', 'X12') or 'X12'
                
                # For XML format, extract from XML file
                if target_format.upper() in ['XML', 'XML_EMBED_PDF', 'XML_EMBED_X12', 'XML_EMBED_EDIFACT']:
                    xml_path_to_extract = row.blob_xml_path or row.xml_path
                    
                    if xml_path_to_extract:
                        logger.info(f"🔍 Extracting info from XML file: {xml_path_to_extract}")
                        
                        # Read XML content
                        try:
                            if xml_path_to_extract.startswith('http://') or xml_path_to_extract.startswith('https://'):
                                # Blob storage URL
                                import requests
                                response = requests.get(xml_path_to_extract)
                                response.raise_for_status()
                                xml_content = response.text
                            else:
                                # Local file
                                import os
                                if os.path.exists(xml_path_to_extract):
                                    with open(xml_path_to_extract, 'r', encoding='utf-8') as f:
                                        xml_content = f.read()
                                else:
                                    logger.warning(f"⚠️ XML file not found: {xml_path_to_extract}")
                                    xml_content = None
                            
                            if xml_content:
                                # Use existing XML extraction function
                                from ..services.database import extract_supplier_info_from_string
                                customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                                
                                # Also try to get invoice ID from XML
                                from lxml import etree
                                root = etree.fromstring(xml_content.encode('utf-8'))
                                namespaces = {
                                    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                                }
                                invoice_id_elem = root.find('.//cbc:ID', namespaces)
                                invoice_id = invoice_id_elem.text.strip() if invoice_id_elem is not None and invoice_id_elem.text else None
                                
                                # Use invoice_id if available, otherwise use customer_id
                                data['customerId'] = invoice_id or customer_id
                                data['customerName'] = customer_name
                                
                                logger.info(f"✅ Extracted from XML - customerId: {data['customerId']}, customerName: {data['customerName']}")
                            else:
                                data['customerId'] = None
                                data['customerName'] = None
                        except Exception as xml_err:
                            logger.error(f"❌ Error reading/parsing XML: {xml_err}")
                            data['customerId'] = None
                            data['customerName'] = None
                    else:
                        logger.warning(f"⚠️ No XML path for {row.tracking_id}")
                        data['customerId'] = None
                        data['customerName'] = None
                
                # For EDI formats (X12, EDIFACT), extract from EDI file
                else:
                    edi_path_to_extract = row.blob_edi_path or row.edi_path
                    
                    if edi_path_to_extract:
                        logger.info(f"🔍 Extracting info from EDI file: {edi_path_to_extract}")
                        info = extract_invoice_info(edi_path_to_extract)
                        logger.info(f"📊 Extracted info: {info}")
                        
                        if info and isinstance(info, dict):
                            # Map invoice_id -> customerId and customer_name -> customerName for frontend
                            data['customerId'] = info.get('invoice_id')
                            data['customerName'] = info.get('customer_name')
                            
                            logger.info(f"✅ customerId: {data['customerId']}, customerName: {data['customerName']}")
                        else:
                            logger.warning(f"⚠️ No valid info extracted for {row.tracking_id}")
                            data['customerId'] = None
                            data['customerName'] = None
                    else:
                        logger.warning(f"⚠️ No EDI path for {row.tracking_id}")
                        data['customerId'] = None
                        data['customerName'] = None

            except Exception as info_err:
                logger.error(f"❌ Failed to extract invoice info for {row.tracking_id}: {info_err}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                data['customerId'] = None
                data['customerName'] = None

            # Set the format from target_file_format or default to X12
            data['formate'] = getattr(row, 'target_file_format', 'X12') or 'X12'
            
            # Set source type (web or api/SAP)
            data['request_type'] = getattr(row, 'request_type', 'web') or 'web'
            
            # Set status for frontend
            data['status'] = 'successful'
            
            invoices.append(data)
            
        logger.info(f"✅ Returning {len(invoices)} successful invoices")
        if invoices:
            logger.info(f"📊 Sample invoice: customerId={invoices[0].get('customerId')}, customerName={invoices[0].get('customerName')}, formate={invoices[0].get('formate')}, request_type={invoices[0].get('request_type')}")
            
            # Log how many are api vs web
            api_count = sum(1 for inv in invoices if inv.get('request_type') == 'api')
            web_count = sum(1 for inv in invoices if inv.get('request_type') == 'web' or not inv.get('request_type'))
            logger.info(f"📊 Source breakdown: {api_count} from API/SAP, {web_count} from Web/Manual")
        
        return invoices
        
    except Exception as e:
        logger.error(f"❌ Error getting successful invoices: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Error getting successful invoices: {str(e)}")

@router.get("/failed")
async def get_failed_invoices(
    skip: int = 0,
    limit: int = 50,  # Reduced default limit for better performance
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get failed invoices for current user"""
    try:
        # Cache column inspection results for better performance
        if not hasattr(get_failed_invoices, '_column_cache'):
            inspector = inspect(db.bind)
            columns = [col["name"] for col in inspector.get_columns("zodiac_invoice_failed_edi")]
            get_failed_invoices._column_cache = {
                'has_request_type': "request_type" in columns
            }
        
        # Use cached value
        has_request_type = get_failed_invoices._column_cache['has_request_type']
        
        # Use raw SQL to avoid schema issues
        query = f"""
        SELECT id, tracking_id, user_id, uploaded_at, xml_path, 
               xml_validation_pass, xml_convert_message, edi_path, 
               edi_convert_pass, edi_convert_message, processing_steps,
               blob_xml_path, blob_edi_path, target_file_format,
               {"request_type" if has_request_type else "'web' AS request_type"}
        FROM zodiac_invoice_failed_edi 
        WHERE user_id = :user_id AND deleted_at IS NULL
        ORDER BY uploaded_at DESC 
        LIMIT :limit OFFSET :offset
        """
        result = db.execute(text(query), {
            "user_id": current_user.id,
            "limit": limit,
            "offset": skip
        }).fetchall()

        # Convert to model instances
        invoices = []
        for row in result:
            # Parse the JSON data if it's stored as a string
            processing_steps = row.processing_steps
            if isinstance(processing_steps, str):
                try:
                    import json
                    processing_steps = json.loads(processing_steps)
                except (json.JSONDecodeError, TypeError):
                    processing_steps = None

            # Read file contents
            xml_content = ""
            edi_content = ""

            try:
                # Use blob path if available, otherwise fall back to local path
                if row.blob_xml_path and USE_BLOB_STORAGE:
                    logger.info(
                        f"🔍 Reading XML file from blob: {row.blob_xml_path}")
                    xml_content_bytes = await read_file_from_storage(None, row.blob_xml_path, None)
                    xml_content = xml_content_bytes.decode('utf-8')
                    logger.info(
                        f"✅ XML content read from blob successfully, length: {len(xml_content)}")
                else:
                    # Try to resolve the local path - it might be relative or have issues
                    xml_file_path = row.xml_path
                    if xml_file_path:
                        # Convert to absolute path if it's relative
                        if not os.path.isabs(xml_file_path):
                            xml_file_path = os.path.abspath(xml_file_path)

                        logger.info(
                            f"🔍 Reading XML file from local storage: {xml_file_path}")
                        logger.info(
                            f"🔍 File exists: {os.path.exists(xml_file_path)}")

                        if os.path.exists(xml_file_path):
                            xml_content_bytes = await read_file_from_storage(xml_file_path, None, None)
                            xml_content = xml_content_bytes.decode('utf-8')
                            logger.info(
                                f"✅ XML content read from local storage successfully, length: {len(xml_content)}")
                        else:
                            logger.warning(
                                f"⚠️ XML file not found: {xml_file_path}")
                    else:
                        logger.warning(f"⚠️ XML path is None")
            except Exception as e:
                logger.error(f"❌ Could not read XML file: {e}")

            try:
                # Use blob path if available, otherwise fall back to local path
                if row.blob_edi_path and USE_BLOB_STORAGE:
                    logger.info(
                        f"🔍 Reading EDI file from blob: {row.blob_edi_path}")
                    edi_content_bytes = await read_file_from_storage(None, None, row.blob_edi_path)
                    edi_content = edi_content_bytes.decode('utf-8')
                    logger.info(
                        f"✅ EDI content read from blob successfully, length: {len(edi_content)}")
                elif row.edi_path and (os.path.exists(row.edi_path) or USE_BLOB_STORAGE):
                    logger.info(
                        f"🔍 Reading EDI file from local storage: {row.edi_path}")
                    edi_content_bytes = await read_file_from_storage(row.edi_path, None, None)
                    edi_content = edi_content_bytes.decode('utf-8')
                    logger.info(
                        f"✅ EDI content read from local storage successfully, length: {len(edi_content)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not read EDI file: {e}")

            invoice = FailedModel(
                id=row.id,
                tracking_id=row.tracking_id,
                user_id=row.user_id,
                uploaded_at=row.uploaded_at,
                xml_path=row.blob_xml_path if row.blob_xml_path else row.xml_path,
                xml_validation_pass=row.xml_validation_pass,
                xml_convert_message=row.xml_convert_message,
                edi_path=row.blob_edi_path if row.blob_edi_path else row.edi_path,
                edi_convert_pass=row.edi_convert_pass,
                edi_convert_message=row.edi_convert_message,
                processing_steps=processing_steps,
                blob_xml_path=row.blob_xml_path,
                blob_edi_path=row.blob_edi_path,
                target_file_format=getattr(row, 'target_file_format', None)
            )

            # Add computed fields after model creation
            invoice.xml_content = xml_content
            invoice.edi_content = edi_content
            
            # Convert to dict and extract invoice info
            data = vars(invoice).copy()
            data.pop("_sa_instance_state", None)
            
            # Extract invoice info based on format
            try:
                target_format = getattr(row, 'target_file_format', 'X12') or 'X12'
                
                # For XML format, extract from XML file
                if target_format.upper() in ['XML', 'XML_EMBED_PDF', 'XML_EMBED_X12', 'XML_EMBED_EDIFACT']:
                    xml_path_to_extract = row.blob_xml_path or row.xml_path
                    
                    if xml_path_to_extract:
                        logger.info(f"🔍 Extracting info from failed XML file: {xml_path_to_extract}")
                        
                        # Read XML content (use already loaded xml_content if available)
                        try:
                            if xml_content:
                                xml_content_to_parse = xml_content
                            elif xml_path_to_extract.startswith('http://') or xml_path_to_extract.startswith('https://'):
                                # Blob storage URL
                                import requests
                                response = requests.get(xml_path_to_extract)
                                response.raise_for_status()
                                xml_content_to_parse = response.text
                            else:
                                # Local file
                                import os
                                xml_file_path = xml_path_to_extract
                                if not os.path.isabs(xml_file_path):
                                    xml_file_path = os.path.abspath(xml_file_path)
                                
                                if os.path.exists(xml_file_path):
                                    with open(xml_file_path, 'r', encoding='utf-8') as f:
                                        xml_content_to_parse = f.read()
                                else:
                                    logger.warning(f"⚠️ XML file not found: {xml_file_path}")
                                    xml_content_to_parse = None
                            
                            if xml_content_to_parse:
                                # Use existing XML extraction function
                                from ..services.database import extract_supplier_info_from_string
                                customer_id, customer_name = extract_supplier_info_from_string(xml_content_to_parse)
                                
                                # Also try to get invoice ID from XML
                                from lxml import etree
                                root = etree.fromstring(xml_content_to_parse.encode('utf-8'))
                                namespaces = {
                                    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                                }
                                invoice_id_elem = root.find('.//cbc:ID', namespaces)
                                invoice_id = invoice_id_elem.text.strip() if invoice_id_elem is not None and invoice_id_elem.text else None
                                
                                # Use invoice_id if available, otherwise use customer_id
                                data['customerId'] = invoice_id or customer_id
                                data['customerName'] = customer_name
                                
                                logger.info(f"✅ Extracted from XML - customerId: {data['customerId']}, customerName: {data['customerName']}")
                            else:
                                # Fallback: use tracking_id
                                data['customerId'] = str(row.tracking_id)[:8]
                                data['customerName'] = 'Unknown'
                        except Exception as xml_err:
                            logger.error(f"❌ Error reading/parsing XML: {xml_err}")
                            # Fallback: use tracking_id
                            data['customerId'] = str(row.tracking_id)[:8]
                            data['customerName'] = 'Unknown'
                    else:
                        logger.warning(f"⚠️ No XML path for failed invoice {row.tracking_id}")
                        # Fallback: use tracking_id
                        data['customerId'] = str(row.tracking_id)[:8]
                        data['customerName'] = 'Unknown'
                
                # For EDI formats, extract from EDI file
                else:
                    edi_path_to_extract = row.blob_edi_path or row.edi_path
                    
                    if edi_path_to_extract:
                        logger.info(f"🔍 Extracting info from failed EDI file: {edi_path_to_extract}")
                        info = extract_invoice_info(edi_path_to_extract)
                        logger.info(f"📊 Extracted info: {info}")
                        
                        if info and isinstance(info, dict):
                            # Map invoice_id -> customerId and customer_name -> customerName for frontend
                            data['customerId'] = info.get('invoice_id')
                            data['customerName'] = info.get('customer_name')
                            logger.info(f"✅ customerId: {data['customerId']}, customerName: {data['customerName']}")
                        else:
                            # Fallback: use tracking_id
                            data['customerId'] = str(row.tracking_id)[:8]
                            data['customerName'] = 'Unknown'
                    else:
                        logger.info(f"⚠️ No EDI path for failed invoice {row.tracking_id}")
                        # Fallback: use tracking_id
                        data['customerId'] = str(row.tracking_id)[:8]
                        data['customerName'] = 'Unknown'
            except Exception as info_err:
                logger.error(f"❌ Failed to extract invoice info: {info_err}")
                # Fallback: use tracking_id
                data['customerId'] = str(row.tracking_id)[:8]
                data['customerName'] = 'Unknown'
            
            # Set format
            data['formate'] = getattr(row, 'target_file_format', 'X12') or 'X12'
            
            # Set source type (web or api/SAP)
            data['request_type'] = getattr(row, 'request_type', 'web') or 'web'
            
            # Set status for frontend
            data['status'] = 'failed'
            
            invoices.append(data)

        logger.info(f"✅ Returning {len(invoices)} failed invoices")
        if invoices:
            logger.info(f"📊 Sample failed invoice: customerId={invoices[0].get('customerId')}, customerName={invoices[0].get('customerName')}, formate={invoices[0].get('formate')}, request_type={invoices[0].get('request_type')}")
        
        return invoices
    except Exception as e:
        logger.error(f"❌ Error getting failed invoices: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        # Return empty list instead of throwing error to ensure page loads
        logger.warning("⚠️ Returning empty list due to error - page will still load")
        return []


@router.get("/failed/{tracking_id}", response_model=ZodiacInvoiceFailedEdi)
async def get_failed_invoice_by_tracking_id(
    tracking_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific failed invoice by tracking ID"""
    try:
        logger.info(f"🔍 Getting failed invoice by tracking ID: {tracking_id}")

        # Use raw SQL to find the failed invoice by tracking ID
        query = """
        SELECT id, tracking_id, user_id, uploaded_at, xml_path, 
               xml_validation_pass, xml_convert_message, edi_path, 
               edi_convert_pass, edi_convert_message, processing_steps,
               blob_xml_path, blob_edi_path, target_file_format
        FROM zodiac_invoice_failed_edi 
        WHERE tracking_id = :tracking_id AND user_id = :user_id
        """
        result = db.execute(text(query), {
            "tracking_id": tracking_id,
            "user_id": current_user.id
        }).fetchone()

        if not result:
            logger.warning(
                f"⚠️ Failed invoice not found for tracking ID: {tracking_id}")
            logger.warning(f"⚠️ User ID: {current_user.id}")
            logger.warning(f"⚠️ Tracking ID type: {type(tracking_id)}")
            logger.warning(f"⚠️ User ID type: {type(current_user.id)}")
            raise HTTPException(
                status_code=404, detail="Failed invoice not found")

        # Convert to model instance
        invoice = FailedModel(
            id=result.id,
            tracking_id=result.tracking_id,
            user_id=result.user_id,
            uploaded_at=result.uploaded_at,
            xml_path=result.xml_path,
            xml_validation_pass=result.xml_validation_pass,
            xml_convert_message=result.xml_convert_message,
            edi_path=result.edi_path,
            edi_convert_pass=result.edi_convert_pass,
            edi_convert_message=result.edi_convert_message,
            processing_steps=result.processing_steps,
            blob_xml_path=result.blob_xml_path,
            blob_edi_path=result.blob_edi_path,
            target_file_format=getattr(result, 'target_file_format', None)
        )

        logger.info(f"✅ Found failed invoice for tracking ID: {tracking_id}")
        logger.info(
            f"🔍 Processing steps from DB (raw): {result.processing_steps}")
        logger.info(
            f"🔍 Processing steps type: {type(result.processing_steps)}")
        logger.info(
            f"🔍 Processing steps is None: {result.processing_steps is None}")

        # Parse the JSON data if it's stored as a string
        processing_steps = result.processing_steps
        if isinstance(processing_steps, str):
            try:
                import json
                processing_steps = json.loads(processing_steps)
                logger.info(
                    f"🔍 Parsed JSON processing steps: {processing_steps}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(
                    f"❌ Failed to parse processing_steps JSON: {e}")
                processing_steps = None

        # Read file contents
        xml_content = ""
        edi_content = ""

        logger.info(
            f"🔍 File content reading - USE_BLOB_STORAGE: {USE_BLOB_STORAGE}")
        logger.info(
            f"🔍 File content reading - blob_xml_path: {invoice.blob_xml_path}")
        logger.info(
            f"🔍 File content reading - blob_edi_path: {invoice.blob_edi_path}")

        try:
            # Use blob path if available, otherwise fall back to local path
            if invoice.blob_xml_path and USE_BLOB_STORAGE:
                logger.info(
                    f"🔍 Reading XML file from blob: {invoice.blob_xml_path}")
                xml_content_bytes = await read_file_from_storage(None, invoice.blob_xml_path, None)
                xml_content = xml_content_bytes.decode('utf-8')
                logger.info(
                    f"✅ XML content read from blob successfully, length: {len(xml_content)}")
            else:
                logger.info(f"🔍 Using local XML path fallback")
                # Try to resolve the local path - it might be relative or have issues
                xml_file_path = invoice.xml_path
                if xml_file_path:
                    # Convert to absolute path if it's relative
                    if not os.path.isabs(xml_file_path):
                        xml_file_path = os.path.abspath(xml_file_path)

                    logger.info(
                        f"🔍 Reading XML file from local storage: {xml_file_path}")
                    logger.info(
                        f"🔍 File exists: {os.path.exists(xml_file_path)}")

                    if os.path.exists(xml_file_path):
                        with open(xml_file_path, 'r', encoding='utf-8') as f:
                            xml_content = f.read()
                        logger.info(
                            f"✅ XML content read from local storage successfully, length: {len(xml_content)}")
                    else:
                        logger.warning(
                            f"⚠️ XML file not found: {xml_file_path}")
                else:
                    logger.warning(f"⚠️ XML path is None")
        except Exception as e:
            logger.error(f"❌ Could not read XML file: {e}")

        try:
            # Use blob path if available, otherwise fall back to local path
            if invoice.blob_edi_path and USE_BLOB_STORAGE:
                logger.info(
                    f"🔍 Reading EDI file from blob: {invoice.blob_edi_path}")
                edi_content_bytes = await read_file_from_storage(None, None, invoice.blob_edi_path)
                edi_content = edi_content_bytes.decode('utf-8')
                logger.info(
                    f"✅ EDI content read from blob successfully, length: {len(edi_content)}")
            else:
                logger.info(f"🔍 Using local EDI path fallback")
                if invoice.edi_path and (os.path.exists(invoice.edi_path) or USE_BLOB_STORAGE):
                    logger.info(
                        f"🔍 Reading EDI file from local storage: {invoice.edi_path}")
                    edi_content_bytes = await read_file_from_storage(invoice.edi_path, None, None)
                    edi_content = edi_content_bytes.decode('utf-8')
                    logger.info(
                        f"✅ EDI content read from local storage successfully, length: {len(edi_content)}")
        except Exception as e:
            logger.warning(f"⚠️ Could not read EDI file: {e}")

        logger.info(
            f"🔍 Final content lengths - XML: {len(xml_content)}, EDI: {len(edi_content)}")

        # Add file content as additional attributes (not part of the model)
        invoice.xml_content = xml_content
        invoice.edi_content = edi_content

        # Create a response object that includes stored error details and file contents
        logger.info(
            f"🔍 Response construction - USE_BLOB_STORAGE: {USE_BLOB_STORAGE}")
        logger.info(
            f"🔍 Response construction - blob_xml_path: {invoice.blob_xml_path}")
        logger.info(
            f"🔍 Response construction - blob_edi_path: {invoice.blob_edi_path}")
        logger.info(f"🔍 Response construction - xml_path: {invoice.xml_path}")
        logger.info(f"🔍 Response construction - edi_path: {invoice.edi_path}")

        response_data = {
            "id": invoice.id,
            "tracking_id": str(invoice.tracking_id),
            "user_id": invoice.user_id,
            "uploaded_at": invoice.uploaded_at.isoformat(),
            "xml_path": invoice.blob_xml_path if invoice.blob_xml_path else invoice.xml_path,
            "xml_validation_pass": invoice.xml_validation_pass,
            "xml_convert_message": invoice.xml_convert_message,
            "xml_content": xml_content,
            "edi_path": invoice.blob_edi_path if invoice.blob_edi_path else invoice.edi_path,
            "edi_convert_pass": invoice.edi_convert_pass,
            "edi_convert_message": invoice.edi_convert_message,
            "edi_content": edi_content,
            "processing_steps": processing_steps,
            "blob_xml_path": invoice.blob_xml_path,
            "blob_edi_path": invoice.blob_edi_path,
            "local_xml_path": invoice.xml_path,
            "local_edi_path": invoice.edi_path,
            "use_blob_storage": USE_BLOB_STORAGE
        }

        logger.info(
            f"🔍 Final response - xml_path: {response_data['xml_path']}")
        logger.info(
            f"🔍 Final response - edi_path: {response_data['edi_path']}")

        # Ensure processing_steps is JSON serializable
        try:
            import json
            json.dumps(response_data['processing_steps'])
            logger.info("✅ Processing steps is JSON serializable")
        except (TypeError, ValueError) as e:
            logger.error(
                f"❌ Processing steps is not JSON serializable: {e}")
            # Convert to a safe format
            if response_data['processing_steps']:
                response_data['processing_steps'] = json.loads(
                    json.dumps(response_data['processing_steps'], default=str))

        logger.info(
            f"🔍 Response data includes processing_steps: {'processing_steps' in response_data}")
        logger.info(
            f"🔍 Processing steps value: {response_data.get('processing_steps')}")
        logger.info(f"🔍 Full response data keys: {list(response_data.keys())}")

        # Ensure processing_steps is properly serialized
        if response_data.get('processing_steps'):
            logger.info(
                f"🔍 Processing steps before return: {response_data['processing_steps']}")
            logger.info(
                f"🔍 Processing steps type: {type(response_data['processing_steps'])}")
        else:
            logger.warning(
                "⚠️ Processing steps is missing from response_data!")

        # Return as JSONResponse to ensure proper serialization
        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"❌ Error getting failed invoice by tracking ID {tracking_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting failed invoice: {str(e)}")


@router.get("/deleted", response_model=list[InvoiceResponse])
async def get_deleted_invoices(
    skip: int = 0,
    limit: int = 50,  # Reduced default limit for better performance
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get deleted invoices for current user"""
    logger.info(f"🗑️ Getting deleted invoices for user: {current_user.id}")

    try:
        # Cache column inspection results for better performance
        if not hasattr(get_deleted_invoices, '_column_cache'):
            inspector = inspect(db.bind)
            success_columns = [col["name"] for col in inspector.get_columns("zodiac_invoice_success_edi")]
            failed_columns = [col["name"] for col in inspector.get_columns("zodiac_invoice_failed_edi")]
            get_deleted_invoices._column_cache = {
                'success_has_target_file_format': "target_file_format" in success_columns,
                'success_has_request_type': "request_type" in success_columns,
                'failed_has_target_file_format': "target_file_format" in failed_columns,
                'failed_has_request_type': "request_type" in failed_columns
            }
        
        # Use cached values
        cache = get_deleted_invoices._column_cache
        
        success_query = f"""
        SELECT id, tracking_id, user_id, uploaded_at, deleted_at,
               blob_xml_path, blob_edi_path, xml_path, edi_path,
               {"target_file_format" if cache['success_has_target_file_format'] else "'X12' AS target_file_format"},
               {"request_type" if cache['success_has_request_type'] else "'web' AS request_type"}
        FROM zodiac_invoice_success_edi
        WHERE user_id = :user_id AND deleted_at IS NOT NULL
        ORDER BY deleted_at DESC
        LIMIT :limit OFFSET :offset
        """
        
        deleted_success_result = db.execute(text(success_query), {
            "user_id": current_user.id,
            "limit": limit,
            "offset": skip
        }).fetchall()

        # Get deleted failed invoices
        failed_query = f"""
        SELECT id, tracking_id, user_id, uploaded_at, deleted_at,
               blob_xml_path, blob_edi_path, xml_path, edi_path,
               {"target_file_format" if cache['failed_has_target_file_format'] else "'X12' AS target_file_format"},
               {"request_type" if cache['failed_has_request_type'] else "'web' AS request_type"}
        FROM zodiac_invoice_failed_edi
        WHERE user_id = :user_id AND deleted_at IS NOT NULL
        ORDER BY deleted_at DESC
        LIMIT :limit OFFSET :offset
        """
        
        deleted_failed_result = db.execute(text(failed_query), {
            "user_id": current_user.id,
            "limit": limit,
            "offset": skip
        }).fetchall()

        deleted_invoices = []

        # Process successful invoices
        for row in deleted_success_result:
            # Extract invoice info
            invoice_id = None
            customer_name = None
            
            try:
                target_format = getattr(row, 'target_file_format', 'X12') or 'X12'
                
                # For XML format, extract from XML file
                if target_format.upper() in ['XML', 'XML_EMBED_PDF', 'XML_EMBED_X12', 'XML_EMBED_EDIFACT']:
                    xml_path = row.blob_xml_path or row.xml_path
                    if xml_path:
                        logger.info(f"🔍 Extracting info from deleted XML invoice: {xml_path}")
                        try:
                            if xml_path.startswith('http://') or xml_path.startswith('https://'):
                                import requests
                                response = requests.get(xml_path)
                                response.raise_for_status()
                                xml_content = response.text
                            else:
                                import os
                                if os.path.exists(xml_path):
                                    with open(xml_path, 'r', encoding='utf-8') as f:
                                        xml_content = f.read()
                                else:
                                    xml_content = None
                            
                            if xml_content:
                                from ..services.database import extract_supplier_info_from_string
                                customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                                
                                from lxml import etree
                                root = etree.fromstring(xml_content.encode('utf-8'))
                                namespaces = {'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}
                                invoice_id_elem = root.find('.//cbc:ID', namespaces)
                                invoice_id = invoice_id_elem.text.strip() if invoice_id_elem is not None and invoice_id_elem.text else customer_id
                                
                                logger.info(f"✅ Extracted from XML - invoice_id: {invoice_id}, customer_name: {customer_name}")
                        except Exception as xml_err:
                            logger.warning(f"⚠️ Could not extract from XML: {xml_err}")
                
                # For EDI formats, extract from EDI file
                else:
                    edi_path = row.blob_edi_path or row.edi_path
                    if edi_path:
                        logger.info(f"🔍 Extracting info from deleted EDI invoice: {edi_path}")
                        info = extract_invoice_info(edi_path)
                        if info and isinstance(info, dict):
                            invoice_id = info.get('invoice_id')
                            customer_name = info.get('customer_name')
                            logger.info(f"✅ Extracted - invoice_id: {invoice_id}, customer_name: {customer_name}")
            except Exception as e:
                logger.warning(f"⚠️ Could not extract info: {e}")
            
            deleted_invoices.append(InvoiceResponse(
                id=row.id,
                filename=f"{row.tracking_id}_invoice.xml",
                customerId=invoice_id,  # Use customerId field
                customerName=customer_name or "N/A",
                status="successful",
                accepted=1,
                rejected=0,
                formate=getattr(row, 'target_file_format', 'X12') or 'X12',
                export=False,
                uploaded_at=row.uploaded_at.isoformat() if row.uploaded_at else None,
                tracking_id=str(row.tracking_id),
                deleted_at=row.deleted_at.isoformat() if row.deleted_at else None,
                request_type=getattr(row, 'request_type', 'web') or 'web'
            ))

        # Process failed invoices
        for row in deleted_failed_result:
            # Extract invoice info
            invoice_id = None
            customer_name = None
            
            try:
                target_format = getattr(row, 'target_file_format', 'X12') or 'X12'
                
                # For XML format, extract from XML file
                if target_format.upper() in ['XML', 'XML_EMBED_PDF', 'XML_EMBED_X12', 'XML_EMBED_EDIFACT']:
                    xml_path = row.blob_xml_path or row.xml_path
                    if xml_path:
                        logger.info(f"🔍 Extracting info from deleted failed XML invoice: {xml_path}")
                        try:
                            if xml_path.startswith('http://') or xml_path.startswith('https://'):
                                import requests
                                response = requests.get(xml_path)
                                response.raise_for_status()
                                xml_content = response.text
                            else:
                                import os
                                if os.path.exists(xml_path):
                                    with open(xml_path, 'r', encoding='utf-8') as f:
                                        xml_content = f.read()
                                else:
                                    xml_content = None
                            
                            if xml_content:
                                from ..services.database import extract_supplier_info_from_string
                                customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                                
                                from lxml import etree
                                root = etree.fromstring(xml_content.encode('utf-8'))
                                namespaces = {'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}
                                invoice_id_elem = root.find('.//cbc:ID', namespaces)
                                invoice_id = invoice_id_elem.text.strip() if invoice_id_elem is not None and invoice_id_elem.text else customer_id
                                
                                logger.info(f"✅ Extracted from XML - invoice_id: {invoice_id}, customer_name: {customer_name}")
                        except Exception as xml_err:
                            logger.warning(f"⚠️ Could not extract from XML: {xml_err}")
                
                # For EDI formats, extract from EDI file
                else:
                    edi_path = row.blob_edi_path or row.edi_path
                    if edi_path:
                        logger.info(f"🔍 Extracting info from deleted failed EDI invoice: {edi_path}")
                        info = extract_invoice_info(edi_path)
                        if info and isinstance(info, dict):
                            invoice_id = info.get('invoice_id')
                            customer_name = info.get('customer_name')
                            logger.info(f"✅ Extracted - invoice_id: {invoice_id}, customer_name: {customer_name}")
            except Exception as e:
                logger.warning(f"⚠️ Could not extract info: {e}")
            
            deleted_invoices.append(InvoiceResponse(
                id=row.id,
                filename=f"{row.tracking_id}_invoice.xml",
                customerId=invoice_id,  # Use customerId field
                customerName=customer_name or "N/A",
                status="failed",
                accepted=0,
                rejected=1,
                formate=getattr(row, 'target_file_format', 'X12') or 'X12',
                export=False,
                uploaded_at=row.uploaded_at.isoformat() if row.uploaded_at else None,
                tracking_id=str(row.tracking_id),
                deleted_at=row.deleted_at.isoformat() if row.deleted_at else None,
                request_type=getattr(row, 'request_type', 'web') or 'web'
            ))

        # Sort by deleted_at descending
        deleted_invoices.sort(key=lambda x: x.deleted_at or "", reverse=True)

        logger.info(f"✅ Found {len(deleted_invoices)} deleted invoices")
        return deleted_invoices

    except Exception as e:
        logger.error(f"❌ Error getting deleted invoices: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Error getting deleted invoices: {str(e)}")

@router.get("/status/{tracking_id}", response_model=InvoiceProcessingResponse)
async def get_processing_status(
    tracking_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get real-time processing status by tracking ID"""
    try:
        # Convert string to UUID
        tracking_uuid = uuid.UUID(tracking_id)
        logger.info(f"🔍 Getting processing status for tracking_id: {tracking_id}, user: {current_user.id}")
        
        # Get status from tracker (in-memory, real-time updates)
        status = status_tracker.get_status(tracking_uuid)
        
        if status:
            logger.info(f"✅ Found status in tracker with {len(status.processing_steps or [])} steps")
            if status.processing_steps:
                logger.info(f"📊 Steps: {[f'Step {s.step_number} ({s.step_name}) - Success: {s.success}' for s in status.processing_steps]}")
            return status
        
        logger.info(f"⏳ Status not in tracker, checking database for completed processing...")
        
        # Check if it's in the database (completed processing)
        # Try success table first
        success_invoice = db.query(SuccessModel).filter(
            SuccessModel.tracking_id == tracking_uuid,
            SuccessModel.user_id == current_user.id
        ).first()
        
        if success_invoice:
            logger.info(f"✅ Found in SUCCESS table with processing_steps: {success_invoice.processing_steps is not None}")
            if success_invoice.processing_steps:
                # Parse JSON if stored as string
                processing_steps = success_invoice.processing_steps
                if isinstance(processing_steps, str):
                    try:
                        import json
                        processing_steps = json.loads(processing_steps)
                        logger.info(f"📊 Parsed {len(processing_steps)} steps from database JSON")
                    except:
                        processing_steps = None
                
                if processing_steps:
                    # Convert database JSON to response objects
                    response_steps = []
                    for step_dict in processing_steps:
                        from ..schemas.invoice import ProcessingStepResult, StepStatus, DetailedErrorInfo
                        step_status = None
                        if step_dict.get('status'):
                            step_status = StepStatus(**step_dict['status'])
                        
                        error_details = None
                        if step_dict.get('error_details'):
                            error_details = [DetailedErrorInfo(**err) for err in step_dict['error_details']]
                        
                        response_steps.append(ProcessingStepResult(
                            step_name=step_dict['step_name'],
                            step_number=step_dict['step_number'],
                            success=step_dict['success'],
                            duration_seconds=step_dict.get('duration_seconds'),
                            message=step_dict.get('message'),
                            status=step_status,
                            error_details=error_details
                        ))
                    logger.info(f"📊 Returning {len(response_steps)} steps from SUCCESS table")
                    return InvoiceProcessingResponse(
                        tracking_id=tracking_uuid,
                        processing_steps=response_steps
                    )
        
        # Try failed table
        failed_invoice = db.query(FailedModel).filter(
            FailedModel.tracking_id == tracking_uuid,
            FailedModel.user_id == current_user.id
        ).first()
        
        if failed_invoice:
            logger.info(f"⚠️ Found in FAILED table with processing_steps: {failed_invoice.processing_steps is not None}")
            if failed_invoice.processing_steps:
                # Parse JSON if stored as string
                processing_steps = failed_invoice.processing_steps
                if isinstance(processing_steps, str):
                    try:
                        import json
                        processing_steps = json.loads(processing_steps)
                        logger.info(f"📊 Parsed {len(processing_steps)} steps from database JSON")
                    except:
                        processing_steps = None
                
                if processing_steps:
                    # Convert database JSON to response objects
                    response_steps = []
                    for step_dict in processing_steps:
                        from ..schemas.invoice import ProcessingStepResult, StepStatus, DetailedErrorInfo
                        step_status = None
                        if step_dict.get('status'):
                            step_status = StepStatus(**step_dict['status'])
                        
                        error_details = None
                        if step_dict.get('error_details'):
                            error_details = [DetailedErrorInfo(**err) for err in step_dict['error_details']]
                        
                        response_steps.append(ProcessingStepResult(
                            step_name=step_dict['step_name'],
                            step_number=step_dict['step_number'],
                            success=step_dict['success'],
                            duration_seconds=step_dict.get('duration_seconds'),
                            message=step_dict.get('message'),
                            status=step_status,
                            error_details=error_details
                        ))
                    logger.info(f"📊 Returning {len(response_steps)} steps from FAILED table")
                    return InvoiceProcessingResponse(
                        tracking_id=tracking_uuid,
                        processing_steps=response_steps
                    )
        
        logger.warning(f"⚠️ Processing status not found anywhere for tracking_id: {tracking_id}")
        raise HTTPException(
            status_code=404, 
            detail="Processing status not found. The invoice may not exist or processing may not have started."
        )
        
    except ValueError:
        logger.error(f"❌ Invalid UUID format: {tracking_id}")
        raise HTTPException(status_code=400, detail="Invalid tracking ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting processing status: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting processing status: {str(e)}")


@router.post("/{tracking_id}/save-xml")
async def save_edited_xml(
    tracking_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """
    Save edited XML content to the actual file for a failed invoice.
    
    Args:
        tracking_id: The tracking ID of the failed invoice
        file: The edited XML file to save
        db: Database session
        current_user: Current authenticated user
    
    Returns:
        Success response with file path
    """
    try:
        logger.info(f"💾 Save edited XML request for tracking ID: {tracking_id}")
        logger.info(f"👤 User: {current_user.id}")
        
        # Validate that the invoice exists and belongs to the current user
        failed_invoice = db.query(FailedModel).filter(
            FailedModel.tracking_id == tracking_id,
            FailedModel.user_id == current_user.id
        ).first()
        
        if not failed_invoice:
            logger.warning(f"⚠️ Failed invoice not found for tracking_id: {tracking_id}, User: {current_user.id}")
            raise HTTPException(
                status_code=404,
                detail="Failed invoice not found or you don't have permission to access it"
            )
        
        logger.info(f"✅ Found failed invoice: {failed_invoice.id}")
        
        # Read the uploaded file content
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(
                status_code=400,
                detail="File content is empty"
            )
        
        logger.info(f"📄 File size: {len(file_content)} bytes")
        
        # Decode the content
        try:
            xml_content = file_content.decode('utf-8')
            logger.info(f"✅ Successfully decoded XML content")
        except UnicodeDecodeError as e:
            logger.error(f"❌ Failed to decode file as UTF-8: {e}")
            raise HTTPException(
                status_code=400,
                detail="File must be valid UTF-8 encoded XML"
            )
        
        # Determine where to save the file
        save_path = None
        
        # Try to use blob storage if available
        if USE_BLOB_STORAGE and failed_invoice.blob_xml_path:
            logger.info(f"💾 Saving to blob storage: {failed_invoice.blob_xml_path}")
            try:
                # Save to blob storage
                await save_file_to_storage(None, xml_content, failed_invoice.blob_xml_path)
                save_path = failed_invoice.blob_xml_path
                logger.info(f"✅ Successfully saved to blob storage")
            except Exception as blob_err:
                logger.error(f"❌ Failed to save to blob storage: {blob_err}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to save to blob storage: {str(blob_err)}"
                )
        else:
            # Fall back to local file storage
            local_path = failed_invoice.xml_path
            if not local_path:
                logger.error(f"❌ No file path found for invoice {failed_invoice.id}")
                raise HTTPException(
                    status_code=400,
                    detail="No file path found for this invoice"
                )
            
            logger.info(f"💾 Saving to local path: {local_path}")
            
            # Ensure the path is absolute
            if not os.path.isabs(local_path):
                local_path = os.path.abspath(local_path)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            try:
                # Write the XML content to the file
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
                
                save_path = local_path
                logger.info(f"✅ Successfully saved XML to: {local_path}")
            except Exception as file_err:
                logger.error(f"❌ Failed to write file: {file_err}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to save file: {str(file_err)}"
                )
        
        # Update the database record with the new timestamp
        try:
            failed_invoice.updated_at = datetime.utcnow()
            db.commit()
            logger.info(f"✅ Updated database record timestamp")
        except Exception as db_err:
            db.rollback()
            logger.error(f"❌ Failed to update database: {db_err}")
            # Don't fail the whole operation if just the timestamp update fails
        
        logger.info(f"✅ XML file saved successfully")
        
        # 🧠 LEARN FROM MANUAL FIX - Compare original vs edited and save to cache
        logger.info(f"🧠 ===== LEARNING FROM MANUAL FIX =====")
        try:
            # Read the original XML from the failed invoice
            original_xml_path = failed_invoice.blob_xml_path or failed_invoice.xml_path
            if original_xml_path:
                logger.info(f"📄 Reading original XML to compare with edited version...")
                try:
                    # Read original XML content
                    original_xml_bytes = await read_file_from_storage(original_xml_path, None, None)
                    original_xml_content = original_xml_bytes.decode('utf-8')
                    logger.info(f"✅ Original XML read successfully ({len(original_xml_content)} bytes)")
                    
                    # Use XML diff service to analyze changes
                    from ..services.xml_diff_service import XMLDiffService
                    diff_service = XMLDiffService()
                    
                    diff_result = diff_service.compare_xml(original_xml_content, xml_content)
                    changes = diff_result.get("changes", [])
                    change_summary = diff_result.get("change_summary", "")
                    transformation_rules = diff_result.get("transformation_rules", [])
                    
                    logger.info(f"📊 Manual fix analysis:")
                    logger.info(f"   Changes detected: {len(changes)}")
                    logger.info(f"   Summary: {change_summary}")
                    
                    if changes and transformation_rules:
                        # Extract customer ID from XML
                        customer_id = diff_service.extract_customer_id(xml_content) or "UNKNOWN"
                        
                        # Extract customer name if available
                        customer_name = None
                        try:
                            from ..services.database import extract_supplier_info_from_string
                            cust_id, cust_name = extract_supplier_info_from_string(xml_content)
                            customer_name = cust_name
                        except Exception as name_err:
                            logger.debug(f"Could not extract customer name: {name_err}")
                        
                        # Get error type from original failure
                        error_type = "MANUAL_FIX"
                        if failed_invoice.xml_convert_message:
                            if "EndpointID" in failed_invoice.xml_convert_message:
                                error_type = "MISSING_ENDPOINT_ID"
                            elif "validation" in failed_invoice.xml_convert_message.lower():
                                error_type = "XML_VALIDATION"
                            elif "schema" in failed_invoice.xml_convert_message.lower():
                                error_type = "XML_SCHEMA"
                        
                        # Generate error signature
                        error_signature = diff_service.generate_error_signature(changes, error_type)
                        
                        logger.info(f"💾 Saving manual fix to correction cache...")
                        logger.info(f"   Customer: {customer_id}")
                        logger.info(f"   Error type: {error_type}")
                        logger.info(f"   Error signature: {error_signature}")
                        
                        # Save to correction cache
                        from ..services.correction_cache_service import CorrectionCacheService
                        cache_service = CorrectionCacheService(db)
                        
                        saved_correction = cache_service.save_correction_from_ai(
                            customer_id=customer_id,
                            customer_name=customer_name,
                            error_type=error_type,
                            error_signature=error_signature,
                            correction_type="XML",
                            original_content=original_xml_content[:2000],
                            corrected_content=xml_content[:2000],
                            ai_model="manual_fix",  # Mark as manual fix
                            user_id=current_user.id
                        )
                        
                        if saved_correction:
                            logger.info(f"✅ Manual fix saved to correction cache (ID: {saved_correction.id})")
                            logger.info(f"🎓 Future invoices with similar errors will be auto-fixed!")
                        else:
                            logger.warning(f"⚠️ Failed to save manual fix to correction cache")
                    else:
                        logger.info(f"ℹ️ No significant changes detected or unable to generate rules")
                
                except Exception as read_err:
                    logger.warning(f"⚠️ Could not read original XML for comparison: {read_err}")
            else:
                logger.warning(f"⚠️ No original XML path available for comparison")
        
        except Exception as learn_err:
            logger.warning(f"⚠️ Failed to learn from manual fix: {learn_err}")
            import traceback
            logger.warning(f"   Traceback: {traceback.format_exc()}")
            # Don't fail the whole operation if learning fails
        
        logger.info(f"🔄 Now triggering reprocessing...")
        
        # 🔄 Automatically trigger reprocessing after saving
        try:
            # Create UploadFile from saved content for reprocessing
            from io import BytesIO
            from starlette.datastructures import Headers
            
            xml_file = UploadFile(
                filename=f"{tracking_id}_edited.xml",
                file=BytesIO(file_content),
                headers=Headers({"content-type": "application/xml"})
            )
            
            # Call process_invoice_internal for reprocessing
            logger.info(f"🔄 Calling process_invoice_internal for full reprocessing...")
            result = await process_invoice_internal(
                xml_file,           # file
                False,              # strict_validation
                db,                 # db session
                None,               # request
                current_user,       # current_user
                "reprocess",        # source
                uuid.UUID(tracking_id)  # tracking_id (reuse existing)
            )
            
            logger.info(f"🔄 Reprocessing completed, checking result...")
            
            # Refresh the database session to see latest data
            db.expire_all()
            
            # Check if invoice moved to success table
            success_invoice = db.query(SuccessModel).filter(
                SuccessModel.tracking_id == tracking_id,
                SuccessModel.user_id == current_user.id
            ).first()
            
            if success_invoice:
                # Successfully moved to success table, delete from failed table
                logger.info(f"✅ Invoice successfully moved to success table! Deleting from failed table...")
                
                # Check if failed invoice still exists before deleting
                failed_check = db.query(FailedModel).filter(
                    FailedModel.tracking_id == tracking_id,
                    FailedModel.user_id == current_user.id
                ).first()
                
                if failed_check:
                    db.delete(failed_check)
                    db.commit()
                    logger.info(f"✅ Deleted from failed table")
                
                return JSONResponse(
                    content={
                        "success": True,
                        "message": "✅ File saved and reprocessed successfully! Invoice moved to successful invoices.",
                        "tracking_id": tracking_id,
                        "file_path": save_path,
                        "saved_at": datetime.utcnow().isoformat(),
                        "status": "successful",
                        "moved_to_success": True,
                        "invoice_id": success_invoice.id
                    },
                    status_code=status.HTTP_200_OK
                )
            else:
                # Still in failed state - check for updated error messages
                logger.info(f"⚠️ Invoice reprocessed but still contains errors")
                
                updated_failed = db.query(FailedModel).filter(
                    FailedModel.tracking_id == tracking_id,
                    FailedModel.user_id == current_user.id
                ).first()
                
                error_message = "Invoice still contains validation errors"
                if updated_failed and updated_failed.xml_convert_message:
                    error_message = updated_failed.xml_convert_message
                elif updated_failed and updated_failed.edi_convert_message:
                    error_message = updated_failed.edi_convert_message
                
                return JSONResponse(
                    content={
                        "success": True,
                        "message": f"File saved and reprocessed, but {error_message}",
                        "tracking_id": tracking_id,
                        "file_path": save_path,
                        "saved_at": datetime.utcnow().isoformat(),
                        "status": "failed",
                        "moved_to_success": False,
                        "error_message": error_message
                    },
                    status_code=status.HTTP_200_OK
                )
                
        except Exception as reprocess_err:
            logger.error(f"⚠️ Reprocessing failed: {reprocess_err}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            
            # File was saved but reprocessing failed
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"File saved but reprocessing failed: {str(reprocess_err)}",
                    "tracking_id": tracking_id,
                    "file_path": save_path,
                    "saved_at": datetime.utcnow().isoformat(),
                    "status": "failed",
                    "moved_to_success": False
                },
                status_code=status.HTTP_200_OK
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error saving XML file: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving XML file: {str(e)}"
        )


@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark an invoice as deleted (soft delete)"""
    logger.info(
        f"🗑️ Delete invoice request for ID: {invoice_id}, User: {current_user.id}")

    try:
        # First check if it's a successful invoice
        success_invoice = db.query(SuccessModel).filter(
            SuccessModel.id == invoice_id,
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)  # Only non-deleted invoices
        ).first()

        if success_invoice:
            logger.info(
                f"🗑️ Found successful invoice to delete: {success_invoice.tracking_id}")
            success_invoice.deleted_at = datetime.utcnow()
            db.commit()
            logger.info(
                f"✅ Successfully soft-deleted successful invoice: {invoice_id}")
            return {"success": True, "message": "Invoice deleted successfully"}

        # Check if it's a failed invoice
        failed_invoice = db.query(FailedModel).filter(
            FailedModel.id == invoice_id,
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)  # Only non-deleted invoices
        ).first()

        if failed_invoice:
            logger.info(
                f"🗑️ Found failed invoice to delete: {failed_invoice.tracking_id}")
            failed_invoice.deleted_at = datetime.utcnow()
            db.commit()
            logger.info(
                f"✅ Successfully soft-deleted failed invoice: {invoice_id}")
            return {"success": True, "message": "Invoice deleted successfully"}

        # Invoice not found or already deleted
        logger.warning(
            f"⚠️ Invoice not found or already deleted: {invoice_id}")
        raise HTTPException(
            status_code=404, detail="Invoice not found or already deleted")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting invoice {invoice_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error deleting invoice: {str(e)}")


@router.post("/{invoice_id}/restore")
def restore_invoice(
    invoice_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a soft-deleted invoice"""
    logger.info(
        f"🔄 Restore invoice request for ID: {invoice_id}, User: {current_user.id}")

    try:
        # First check if it's a successful invoice
        success_invoice = db.query(SuccessModel).filter(
            SuccessModel.id == invoice_id,
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.isnot(None)  # Only deleted invoices
        ).first()

        if success_invoice:
            logger.info(
                f"🔄 Found deleted successful invoice to restore: {success_invoice.tracking_id}")
            success_invoice.deleted_at = None
            db.commit()
            logger.info(
                f"✅ Successfully restored successful invoice: {invoice_id}")
            return {"success": True, "message": "Invoice restored successfully"}

        # Check if it's a failed invoice
        failed_invoice = db.query(FailedModel).filter(
            FailedModel.id == invoice_id,
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.isnot(None)  # Only deleted invoices
        ).first()

        if failed_invoice:
            logger.info(
                f"🔄 Found deleted failed invoice to restore: {failed_invoice.tracking_id}")
            failed_invoice.deleted_at = None
            db.commit()
            logger.info(
                f"✅ Successfully restored failed invoice: {invoice_id}")
            return {"success": True, "message": "Invoice restored successfully"}

        # Invoice not found or not deleted
        logger.warning(f"⚠️ Invoice not found or not deleted: {invoice_id}")
        raise HTTPException(
            status_code=404, detail="Invoice not found or not deleted")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error restoring invoice {invoice_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error restoring invoice: {str(e)}")


@router.get("/{tracking_id}/download")
async def download_invoice_file(
    tracking_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download the processed invoice file (works with local storage)
    Returns the converted/processed file that was sent to third-party API
    """
    logger.info(f"📥 Download request for tracking_id: {tracking_id}")
    
    try:
        # Try to find in success table first
        invoice = db.query(SuccessModel).filter(
            SuccessModel.tracking_id == tracking_id,
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at == None
        ).first()
        
        if not invoice:
            # Try failed table
            invoice = db.query(FailedModel).filter(
                FailedModel.tracking_id == tracking_id,
                FailedModel.user_id == current_user.id,
                FailedModel.deleted_at == None
            ).first()
        
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Determine file path - prioritize blob paths, fallback to local paths
        file_path = None
        filename = None
        
        # For local storage, use edi_path or xml_path
        if not USE_BLOB_STORAGE:
            # Try edi_path first (converted file), then xml_path (original)
            file_path = invoice.edi_path or invoice.xml_path
            
            if not file_path:
                raise HTTPException(
                    status_code=404, 
                    detail="File path not found in database"
                )
            
            # Check if file exists
            from pathlib import Path
            full_path = Path(file_path)
            if not full_path.exists():
                logger.error(f"❌ File not found at path: {full_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"File not found on server: {file_path}"
                )
            
            # Determine filename and media type based on format
            format_type = invoice.target_file_format or 'unknown'
            customer_id = tracking_id[:8]  # Use first 8 chars of tracking_id
            
            # Map format to extension
            if format_type.upper() == 'X12':
                extension = 'x12'
                media_type = 'application/x12'
            elif format_type.upper() == 'EDIFACT':
                extension = 'edi'
                media_type = 'application/edifact'
            elif format_type.upper().startswith('XML'):
                extension = 'xml'
                media_type = 'application/xml'
            else:
                extension = 'txt'
                media_type = 'text/plain'
            
            filename = f"{customer_id}_{format_type}.{extension}"
            
            logger.info(f"✅ Serving file: {full_path}")
            logger.info(f"📁 Filename: {filename}")
            logger.info(f"📋 Media type: {media_type}")
            
            # Return file with proper Content-Disposition header
            from fastapi.responses import FileResponse
            response = FileResponse(
                path=str(full_path),
                media_type=media_type,
                filename=filename
            )
            # Ensure Content-Disposition header is set
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            # Expose Content-Disposition header for CORS
            response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
            return response
        else:
            # For blob storage, redirect to blob URL
            blob_url = invoice.blob_edi_path or invoice.blob_xml_path
            if not blob_url:
                raise HTTPException(
                    status_code=404,
                    detail="Blob URL not found in database"
                )
            
            # Return redirect to blob URL
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=blob_url)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error downloading file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error downloading file: {str(e)}"
        )

