import json
import uuid
import vercel_blob
import time
import trace
import asyncio
from typing import Optional
from ..models.invoice import ZodiacInvoiceSuccessEdi as SuccessModel, ZodiacInvoiceFailedEdi as FailedModel
from ..config.config import USE_BLOB_STORAGE
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from ..models.user import ZodiacUser
from ..schemas.invoice import InvoiceProcessingResponse, ProcessingStepResult, DetailedErrorInfo, StepStatus
import logging
from lxml import etree
from ..services.error_handlers import ErrorTracker
from ..services.ai_service import auto_correct_xml_with_ai, auto_fix_edi_with_ai
from ..services.correction_cache_service import CorrectionCacheService
from ..services.file_service import save_file_to_storage, read_file_from_storage
from ..services.database import check_customer_table, extract_supplier_info_from_string
from ..services.external_api_service import send_to_third_party_endpoint
from ..api.api_key_auth import get_client_ip
from ..utils.xml_validation import validate_xml,validate_edi_format
from ..utils.xml_to_x12 import convert_xml_to_x12
from ..utils.xml_to_edifact import convert_xml_to_edifact
from ..services.status_tracker import status_tracker
from ..services.format_router import get_processing_path, handle_embed_workflow
from ..utils.edination_validator import validate_x12_with_edination
# Set up logger
logger = logging.getLogger("zodiac-api.invoices")
error_tracker = ErrorTracker()
xml_errors = []

def add_processing_step(tracking_id: uuid.UUID, processing_steps: list, step: ProcessingStepResult) -> None:
    """Helper function to add a step to processing_steps and update status tracker"""
    processing_steps.append(step)
    status_tracker.update_step(tracking_id, step)

def convert_error_feedback_to_detail(error_feedback) -> DetailedErrorInfo:
    """Convert ErrorFeedback object to DetailedErrorInfo schema"""
    return DetailedErrorInfo(
        error_code=error_feedback.error_context.error_code,
        error_category=error_feedback.error_context.error_category,
        error_message=error_feedback.error_context.error_message,
        severity=error_feedback.error_context.severity,
        user_message=error_feedback.user_message,
        technical_details=error_feedback.technical_details,
        suggested_actions=error_feedback.suggested_actions,
        file_name=error_feedback.error_context.file_name,
        timestamp=error_feedback.error_context.timestamp,
        additional_context=error_feedback.error_context.additional_context,
        documentation_links=error_feedback.documentation_links,
        is_recoverable=error_feedback.is_recoverable,
        estimated_fix_time=error_feedback.estimated_fix_time
    )

async def validate_xml_parsing_with_timeout(xml_content: str, timeout_seconds: int = 5) -> tuple[bool, str, Optional[Exception]]:
    """
    Validate that XML can be parsed without hanging.
    Returns: (is_valid, error_message, exception)
    """
    try:
        # Run XML parsing with timeout to prevent hanging
        parser = etree.XMLParser(recover=False, resolve_entities=False, no_network=True)
        
        async def parse_xml():
            try:
                etree.fromstring(xml_content.encode('utf-8'), parser)
                return True, "XML is well-formed", None
            except etree.XMLSyntaxError as e:
                return False, f"XML syntax error: {str(e)}", e
            except Exception as e:
                return False, f"XML parsing error: {str(e)}", e
        
        # Apply timeout
        result = await asyncio.wait_for(parse_xml(), timeout=timeout_seconds)
        return result
        
    except asyncio.TimeoutError:
        error_msg = f"XML parsing timed out after {timeout_seconds} seconds - file may be too large or malformed"
        logger.error(f"⏱️ {error_msg}")
        return False, error_msg, TimeoutError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during XML validation: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg, e
async def process_invoice_internal(
    file: UploadFile,
    strict_validation: bool,
    db: Session,
    request: Request,
    current_user: ZodiacUser,
    request_type: str,
    tracking_id: Optional[uuid.UUID] = None
):
    """Process uploaded invoice file with XML validation and EDI conversion
    Supports both web authentication (JWT) and API key authentication

    Args:
        file: Uploaded XML file
        strict_validation: If True, performs strict XML content validation (default: False for old API compatibility)
        db: Database session
        request: HTTP request object
        current_user: Authenticated user
        request_type: Type of request ('api' or 'web')
        tracking_id: Optional tracking ID (if not provided, will generate a new one)
    """

    start_time = time.time()

    # Authentication method determined by caller
    if request_type == "api":
        client_ip = get_client_ip(request) if request else "unknown"
        # logger.info(f"🔑 API request from IP: {client_ip}, User: {current_user.id}")
    else:
        # logger.info(f"🌐 Web request, User: {current_user.id}")
        pass

    logger.info(f"🚀 ===== INVOICE PROCESSING STARTED =====")
    # logger.info(f"👤 User ID: {current_user.id}")
    logger.info(f"📋 Request Type: {request_type}")
    logger.info(
        f"📁 File details: filename={file.filename}, content_type={file.content_type}, size={file.size}")
    logger.info(f"🔍 Strict validation mode: {strict_validation}")
    logger.info(
        f"⏰ Start time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

    # Generate or use provided tracking ID
    if tracking_id is None:
        tracking_id = uuid.uuid4()
        logger.info(f"🆔 Generated new tracking ID: {tracking_id}")
    else:
        logger.info(f"🆔 Using provided tracking ID: {tracking_id}")
    
    logger.info(f"📋 Processing steps: 1) File Upload → 2) XML Validation → 3) EDI Conversion → 4) EDI Format Validation → 5) 3rd Party Endpoint → 6) Database Save")

    # Initialize status tracking for real-time updates (do this BEFORE any processing)
    # Only initialize if not already done by the caller
    current_status = status_tracker.get_status(tracking_id)
    if current_status is None:
        status_tracker.initialize_status(tracking_id)
        logger.info(f"📊 Status tracker initialized for tracking_id: {tracking_id}")
    else:
        logger.info(f"📊 Status tracker already initialized for tracking_id: {tracking_id}")

    # Initialize response with new simplified structure
    response = InvoiceProcessingResponse(
        tracking_id=tracking_id,
        processing_steps=[]
    )

    # Track processing steps
    processing_steps = []
    all_errors = []
    xml_errors = []  # Initialize early to avoid UnboundLocalError
    
    # Initialize variables that may or may not be set depending on processing path
    x12_filename = None
    step2_duration = 0.0
    step3_duration = 0.0
    step4_duration = 0.0
    step5_duration = 0.0
    step6_duration = 0.0
    # Track additional information for steps
    ai_correction_used = False
    customer_id = None
    customer_name = None

    try:
        # Step 1: File Upload
        step1_start = time.time()
        logger.info(f"📤 ===== STEP 1: FILE UPLOAD =====")
        logger.info(f"📁 Processing file: {file.filename}")
        logger.info(f"📊 File size: {file.size} bytes")
        logger.info(f"📋 Content type: {file.content_type}")

        # Validate content type - accept both text/xml and application/xml
        if file.content_type not in ["text/xml", "application/xml"]:
            error_feedback = error_tracker.create_file_upload_error(
                error_type="invalid_type",
                file_name=file.filename,
                content_type=file.content_type,
                tracking_id=tracking_id,
                user_id=current_user.id,
                timestamp=datetime.now()
            )
            logger.info(
                f"📤 Returning 400 Bad Request for tracking ID {tracking_id}")
            # Convert UUID to string for JSON serialization
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=response_dict)

        logger.info(f"🔍 Checking filename for tracking ID {tracking_id}")

        if not file.filename:
            error_feedback = error_tracker.create_file_upload_error(
                error_type="missing_filename",
                file_name=None,
                tracking_id=tracking_id,
                user_id=current_user.id,
                timestamp=datetime.now()
            )
            logger.error(
                f"❌ STEP 1 FAILED: No filename provided for tracking ID {tracking_id}")
            logger.info(
                f"📤 Returning 400 Bad Request for tracking ID {tracking_id}")
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            response_dict['detailed_error'] = error_feedback.to_dict()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=response_dict)

        logger.info(f"✅ Filename validation passed: {file.filename}")

        # Save uploaded file
        xml_filename = f"{tracking_id}_{file.filename}"
        logger.info(f"💾 Saving file: {xml_filename}")
        logger.info(f"📁 Target filename: {xml_filename}")

        # Read file content
        content = await file.read()
        logger.info(f"📊 File size: {len(content)} bytes")

        # Save to appropriate storage (local or Vercel Blob)
        xml_path = await save_file_to_storage(content, xml_filename, "uploads")
        logger.info(f"✅ File saved successfully!")
        logger.info(f"📁 Saved as: {xml_filename}")
        logger.info(f"📍 Storage path: {xml_path}")

        step1_duration = time.time() - step1_start
        logger.info(
            f"✅ STEP 1 COMPLETED: File upload successful (took {step1_duration:.3f}s)")

        # Record successful step
        step1_result = ProcessingStepResult(
            step_name="File Upload",
            step_number=1,
            success=True,
            duration_seconds=step1_duration,
            message="File uploaded successfully",
            status=StepStatus(
                file_upload_pass=True,
                file_upload_message="File uploaded successfully"
            )
        )
        add_processing_step(tracking_id, processing_steps, step1_result)

        logger.info(f"🔄 ===== CONTINUING PROCESSING =====")
        logger.info(f"📁 XML file saved at: {xml_path}")

        # Step 2: Early XML Parsing Check (Fast Fail for Bad XML)
        logger.info(f"🔍 ===== STEP 2: EARLY XML VALIDATION (PARSING CHECK) =====")
        early_check_start = time.time()
        
        # Read XML content for validation
        try:
            # Handle both local paths and blob storage
            if isinstance(xml_path, dict):
                # Blob storage - already has URL
                xml_content_bytes = await read_file_from_storage(xml_path, None, None)
            else:
                # Local path - pass as string
                xml_content_bytes = await read_file_from_storage(xml_path, None, None)
            xml_content_str = xml_content_bytes.decode('utf-8')
            logger.info(f"✅ Successfully read XML file ({len(xml_content_str)} bytes)")
        except Exception as read_err:
            logger.error(f"❌ Failed to read uploaded XML file: {read_err}")
            logger.exception(read_err)  # Log full stack trace
            error_feedback = error_tracker.create_xml_parsing_error(
                error_message=f"Failed to read uploaded file: {str(read_err)}",
                xml_preview=None,
                file_name=file.filename,
                tracking_id=str(tracking_id),
                user_id=current_user.id,
                timestamp=time.time()
            )
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="Early XML Check",
                step_number=2,
                success=False,
                duration_seconds=time.time() - early_check_start,
                message=f"Failed to read XML file: {str(read_err)}",
                error_details=[convert_error_feedback_to_detail(error_feedback)]
            ))
            status_tracker.mark_completed(tracking_id, success=False)
            response.processing_steps = processing_steps
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            return Response(
                content=json.dumps(response_dict),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
        
        # Validate XML parsing with timeout
        logger.info(f"🔍 Performing early XML parsing check (5 second timeout)...")
        is_parseable, parse_error_msg, parse_exception = await validate_xml_parsing_with_timeout(xml_content_str, timeout_seconds=5)
        early_check_duration = time.time() - early_check_start
        
        if not is_parseable:
            logger.error(f"❌ EARLY XML CHECK FAILED: {parse_error_msg}")
            logger.error(f"💥 XML file is malformed or cannot be parsed")
            
            # Create detailed error
            error_preview = xml_content_str[:500] if len(xml_content_str) > 500 else xml_content_str
            error_feedback = error_tracker.create_xml_parsing_error(
                error_message=parse_error_msg,
                xml_preview=error_preview,
                file_name=file.filename,
                tracking_id=str(tracking_id),
                user_id=current_user.id,
                timestamp=time.time()
            )
            
            # Record failed step
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="Early XML Check",
                step_number=2,
                success=False,
                duration_seconds=early_check_duration,
                message=f"XML parsing failed: {parse_error_msg}",
                error_details=[convert_error_feedback_to_detail(error_feedback)]
            ))
            
            # Mark as completed (failed) and return immediately
            status_tracker.mark_completed(tracking_id, success=False)
            logger.info(f"🚫 Processing cancelled due to unparseable XML")
            logger.info(f"⏱️ Total processing time: {time.time() - start_time:.3f}s")
            
            response.processing_steps = processing_steps
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            return Response(
                content=json.dumps(response_dict),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
        
        logger.info(f"✅ Early XML parsing check passed (took {early_check_duration:.3f}s)")
        
        try:
            logger.info(f"📊 About to add Step 2 to processing steps...")
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="Early XML Check",
                step_number=2,
                success=True,
                duration_seconds=early_check_duration,
                message="XML file is parseable"
            ))
            logger.info(f"✅ Step 2 added successfully to processing steps")
        except Exception as step2_error:
            logger.error(f"❌ ERROR adding Step 2 to processing steps: {step2_error}")
            logger.exception(step2_error)
            raise

        logger.info(f"🎯 CONTINUING AFTER STEP 2 - About to determine processing path")

        # Determine customer format to decide processing path
        logger.info(f"🔍 ===== DETERMINING PROCESSING PATH =====")
        logger.info(f"🔍 XML content loaded, length: {len(xml_content_str)} characters")
        
        # Initialize variables (xml_content already loaded from early validation)
        customer_format = None
        customer_id = None
        customer_name = None
        customer_validation_rules = None
        xml_content = xml_content_str  # Use already loaded content from early validation
        
        try:
            logger.info(f"🔍 Attempting to extract customer info from XML...")
            # Extract customer info from already-loaded XML content
            customer_id, customer_name = extract_supplier_info_from_string(xml_content)
            logger.info(f"✅ Customer info extracted - ID: {customer_id}, Name: {customer_name}")
            
            logger.info(f"🔍 Checking customer table in database...")
            customer_format, customer_validation_rules = check_customer_table(customer_id, customer_name, db)
            logger.info(f"✅ Customer format and validation rules retrieved from database")
            logger.info(f"📊 Customer ID: {customer_id}, Name: {customer_name}")
            logger.info(f"🎯 Target format from customer table: {customer_format}")
            logger.info(f"📋 Custom validation rules: {'Yes' if customer_validation_rules else 'No (using defaults)'}")
        except Exception as e:
            logger.error(f"❌ Error determining customer format: {e}")
            logger.exception(e)  # Log full exception for debugging
            customer_format = 'EDIFACT'  # Default to EDIFACT processing
            customer_validation_rules = None
            logger.info(f"🎯 Using default format: {customer_format}")
        
        # Try to at least get the XML content for later use (should already be loaded)
        try:
            if xml_content is None or xml_content == "":
                logger.warning(f"⚠️ XML content is None or empty, attempting to reload...")
                file_content_bytes = await read_file_from_storage(xml_path, None, None)
                xml_content = file_content_bytes.decode('utf-8')
                logger.info(f"✅ XML content reloaded, length: {len(xml_content)}")
            else:
                logger.info(f"✅ XML content already available, length: {len(xml_content)}")
        except Exception as xml_read_error:
            logger.error(f"❌ Could not read XML content: {xml_read_error}")
            logger.exception(xml_read_error)
            xml_content = ""  # Set to empty string as fallback
        
        # Get processing path based on customer format
        logger.info(f"🔍 Getting processing path for format: {customer_format}")
        try:
            processing_path = get_processing_path(customer_format)
            logger.info(f"✅ Processing path retrieved successfully")
            logger.info(f"📊 Format: {processing_path.format_name}")
            logger.info(f"📊 Needs XML validation: {processing_path.needs_xml_validation}")
            logger.info(f"📊 Needs conversion: {processing_path.needs_conversion}")
        except Exception as path_error:
            logger.error(f"❌ Error getting processing path: {path_error}")
            logger.exception(path_error)
            raise

        # Step 3: XML Validation (based on processing path)
        if not processing_path.needs_xml_validation:
            logger.info(f"⏭️ SKIPPING STEP 3: XML Validation (not required for {processing_path.format_name})")
            xml_valid = True
            xml_message = f"XML validation skipped for {processing_path.format_name} format"
            xml_warnings = []
            step2_duration = 0.0
        else:
            step2_start = time.time()
            logger.info(f"🔍 ===== STEP 3: XML VALIDATION =====")
            logger.info(f"📄 Validating XML file: {xml_path}")
            logger.info(f"🔍 Calling validate_xml function...")

            xml_valid, xml_message, xml_warnings = validate_xml(
                xml_path, strict_validation)
            
            # Step 3A: Customer-specific field validation
            if xml_valid and customer_validation_rules:
                logger.info(f"🔍 ===== STEP 3A: CUSTOMER-SPECIFIC FIELD VALIDATION =====")
                logger.info(f"📋 Validating customer-specific required fields...")
                
                try:
                    from ..services.customer_validation import customer_validation_service
                    
                    # Validate with customer rules and apply defaults if needed
                    fields_valid, fields_message, missing_fields, corrected_xml = customer_validation_service.validate_xml_with_customer_rules(
                        xml_content, customer_validation_rules, use_defaults=False, apply_defaults=True
                    )
                    
                    if not fields_valid:
                        logger.warning(f"⚠️ Customer-specific validation failed: {fields_message}")
                        missing_xpaths = [f['xpath'] for f in missing_fields]
                        logger.warning(f"Missing fields: {', '.join(missing_xpaths)}")
                        
                        # Add as warnings (non-blocking) or errors (blocking) based on strict mode
                        if strict_validation:
                            xml_valid = False
                            xml_message = f"Customer validation failed: {fields_message}"
                            logger.error(f"❌ Customer validation failed in strict mode")
                        else:
                            xml_warnings.append(f"Customer validation warning: {fields_message}")
                            logger.info(f"⚠️ Customer validation failed but continuing (non-strict mode)")
                    else:
                        logger.info(f"✅ Customer-specific validation passed: {fields_message}")
                        
                        # If defaults were applied, update xml_content
                        if corrected_xml:
                            logger.info(f"🔧 Applied default values to {len(missing_fields)} field(s)")
                            xml_content = corrected_xml
                            xml_warnings.append(f"Applied {len(missing_fields)} default value(s) to missing fields")
                            
                            # Update the XML file with corrected content
                            try:
                                if isinstance(xml_path, dict):
                                    # Blob storage - upload corrected XML
                                    from ..services.file_service import save_file_to_storage
                                    xml_path = await save_file_to_storage(
                                        corrected_xml.encode('utf-8'),
                                        f"corrected_{file.filename}",
                                        "text/xml"
                                    )
                                    logger.info(f"✅ Uploaded corrected XML to blob storage")
                                else:
                                    # Local storage - save corrected XML
                                    with open(xml_path, 'w', encoding='utf-8') as f:
                                        f.write(corrected_xml)
                                    logger.info(f"✅ Saved corrected XML to: {xml_path}")
                            except Exception as save_error:
                                logger.error(f"⚠️ Failed to save corrected XML: {save_error}")
                        
                except Exception as e:
                    logger.error(f"❌ Error during customer-specific validation: {e}")
                    logger.exception(e)
                    # Don't fail the whole process if customer validation has an error
                    xml_warnings.append(f"Customer validation error: {str(e)}")
            elif customer_validation_rules:
                logger.info(f"⏭️ Skipping customer-specific validation (XML validation already failed)")
            else:
                logger.info(f"ℹ️ No customer-specific validation rules defined")

            step2_duration = time.time() - step2_start
            logger.info(f"🔍 XML validation completed in {step2_duration:.3f}s")
            logger.info(f"📊 XML validation result: {xml_valid}")
            logger.info(f"📝 XML validation message: {xml_message}")

            # Log warnings if any (non-blocking)
            if xml_warnings:
                logger.info(f"⚠️ XML validation warnings ({len(xml_warnings)}):")
                for warning in xml_warnings:
                    logger.warning(f"   - {warning}")

            # Only fail if XML is not well-formed (parsing error) or strict validation fails
            if not xml_valid:
                logger.error(
                    f"❌ STEP 2 FAILED: XML validation failed for tracking ID {tracking_id}")
                logger.error(f"💥 Failure reason: {xml_message}")

                # Create error objects for the original validation failure
                # (These will be added to all_errors, and may be resolved by AI)
                original_xml_errors = []
                
                if "Sender/Receiver ID validation failed" in xml_message or "Sender ID" in xml_message or "Receiver ID" in xml_message:
                    error_type = "missing_sender_id" if "Sender" in xml_message else "missing_receiver_id"
                    error_feedback = error_tracker.create_xml_validation_error(
                        error_type=error_type,
                        error_message=xml_message,
                        file_name=file.filename,
                        xml_preview=xml_content[:1000] if xml_content else None,
                        tracking_id=str(tracking_id),
                        user_id=current_user.id,
                        timestamp=time.time()
                    )
                    original_xml_errors.append(error_feedback)
                elif "Strict validation failed" in xml_message:
                    if xml_warnings:
                        for warning in xml_warnings:
                            error_feedback = error_tracker.create_xml_validation_error(
                                error_type="strict_validation",
                                error_message=warning,
                                file_name=file.filename,
                                xml_preview=xml_content[:1000] if xml_content else None,
                                tracking_id=str(tracking_id),
                                user_id=current_user.id,
                                timestamp=time.time()
                            )
                            original_xml_errors.append(error_feedback)
                    else:
                        error_feedback = error_tracker.create_xml_validation_error(
                            error_type="strict_validation",
                            error_message=xml_message,
                            file_name=file.filename,
                            xml_preview=xml_content[:1000] if xml_content else None,
                            tracking_id=str(tracking_id),
                            user_id=current_user.id,
                            timestamp=time.time()
                        )
                        original_xml_errors.append(error_feedback)
                elif "date" in xml_message.lower():
                    error_feedback = error_tracker.create_xml_validation_error(
                        error_type="invalid_date",
                        error_message=xml_message,
                        file_name=file.filename,
                        xml_preview=xml_content[:1000] if xml_content else None,
                        tracking_id=str(tracking_id),
                        user_id=current_user.id,
                        timestamp=time.time()
                    )
                    original_xml_errors.append(error_feedback)
                elif "amount" in xml_message.lower():
                    error_feedback = error_tracker.create_xml_validation_error(
                        error_type="invalid_amount",
                        error_message=xml_message,
                        file_name=file.filename,
                        xml_preview=xml_content[:1000] if xml_content else None,
                        tracking_id=str(tracking_id),
                        user_id=current_user.id,
                        timestamp=time.time()
                    )
                    original_xml_errors.append(error_feedback)
                elif "malformed" in xml_message.lower() or "parsing" in xml_message.lower():
                    error_feedback = error_tracker.create_xml_validation_error(
                        error_type="malformed",
                        error_message=xml_message,
                        file_name=file.filename,
                        xml_preview=xml_content[:1000] if xml_content else None,
                        tracking_id=str(tracking_id),
                        user_id=current_user.id,
                        timestamp=time.time()
                    )
                    original_xml_errors.append(error_feedback)
                else:
                    error_feedback = error_tracker.create_xml_validation_error(
                        error_type="missing_element",
                        error_message=xml_message,
                        file_name=file.filename,
                        xml_preview=xml_content[:1000] if xml_content else None,
                        tracking_id=str(tracking_id),
                        user_id=current_user.id,
                        timestamp=time.time()
                    )
                    original_xml_errors.append(error_feedback)
                
                # Add original errors to tracking (they may be resolved by AI below)
                all_errors.extend(original_xml_errors)
                xml_errors.extend(original_xml_errors)

                # ======================================================
                # 🤖 INTELLIGENT CORRECTION (CACHE + AI FALLBACK)
                # ======================================================
                logger.info(f"🧠 ===== ATTEMPTING INTELLIGENT CORRECTION =====")
                ai_correction_used = False
                correction_applied = False
                correction_method = None
                
                try:
                    # Initialize correction cache service
                    cache_service = CorrectionCacheService(db)
                    
                    # Generate error signature
                    error_context = {
                        "error_type": error_type if 'error_type' in locals() else "validation_failed",
                        "message": xml_message
                    }
                    
                    # Try to extract more specific error context
                    if "Sender" in xml_message or "Receiver" in xml_message:
                        error_context["element"] = "EndpointID"
                        if "Sender" in xml_message:
                            error_context["xpath"] = "/Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
                    
                    error_signature = cache_service.generate_error_signature(
                        error_type=original_xml_errors[0].error_context.error_code if original_xml_errors else "XML_VALIDATION",
                        error_context=error_context
                    )
                    
                    logger.info(f"🔍 Error signature: {error_signature}")
                    
                    # Step 1: Check if we have a cached correction
                    cached_correction = cache_service.find_correction(
                        customer_id=customer_id or "UNKNOWN",
                        error_type=original_xml_errors[0].error_context.error_code if original_xml_errors else "XML_VALIDATION",
                        error_signature=error_signature,
                        correction_type="XML"
                    )
                    
                    if cached_correction:
                        logger.info(f"✅ Found cached correction (ID: {cached_correction.id})")
                        logger.info(f"   Success rate: {cached_correction.get_success_rate():.1f}%")
                        logger.info(f"   Used {cached_correction.success_count} times successfully")
                        
                        # Apply cached correction
                        transformation_rule = cached_correction.transformation_rule
                        
                        # Check if this is a full AI correction or a rule-based correction
                        if transformation_rule.get("action") == "ai_full_correction":
                            logger.info(f"📋 Cached correction requires full AI re-application")
                            # For full corrections, we need to call AI again but we know it worked before
                            # This provides guidance to the AI
                            logger.info(f"🤖 Calling AI with correction history context...")
                            xml_corrected, corrected_xml = await auto_correct_xml_with_ai(xml_content, strict_validation)
                            
                            if xml_corrected:
                                xml_content = corrected_xml
                                correction_applied = True
                                correction_method = "AI (guided by cache)"
                                ai_correction_used = True
                                
                                # Mark as success
                                cache_service.mark_success(str(cached_correction.id))
                        else:
                            # Apply rule-based correction
                            logger.info(f"🔧 Applying rule-based correction")
                            success, corrected_xml, message = cache_service.apply_xml_correction(
                                xml_content, transformation_rule
                            )
                            
                            if success:
                                xml_content = corrected_xml
                                correction_applied = True
                                correction_method = "Cached rule"
                                logger.info(f"✅ Cached correction applied: {message}")
                                
                                # Save corrected XML back to file
                                corrected_path = await save_file_to_storage(
                                    corrected_xml.encode('utf-8'),
                                    f"{tracking_id}_corrected.xml",
                                    "uploads"
                                )
                                xml_path = corrected_path
                                
                                # Mark as success
                                cache_service.mark_success(str(cached_correction.id))
                            else:
                                logger.warning(f"⚠️ Cached correction failed: {message}")
                                # Mark as failure
                                cache_service.mark_failure(str(cached_correction.id))
                    
                    # Step 2: If no cached correction or cache failed, try AI
                    if not correction_applied:
                        logger.info(f"🤖 No cached correction available - calling AI...")
                        logger.info(f"🔄 Attempting AI correction with timeout...")
                        
                        # Call AI correction
                        xml_corrected, corrected_xml = await auto_correct_xml_with_ai(xml_content, strict_validation)
                        
                        if xml_corrected:
                            logger.info(f"✅ AI correction successful")
                            
                            # Save the AI correction to cache for future use
                            logger.info(f"💾 Saving AI correction to cache...")
                            saved_correction = cache_service.save_correction_from_ai(
                                customer_id=customer_id or "UNKNOWN",
                                customer_name=customer_name,
                                error_type=original_xml_errors[0].error_context.error_code if original_xml_errors else "XML_VALIDATION",
                                error_signature=error_signature,
                                correction_type="XML",
                                original_content=xml_content[:2000],  # Store snippet
                                corrected_content=corrected_xml[:2000],  # Store snippet
                                ai_model="gpt-4o-mini",
                                user_id=current_user.id if current_user else None  # Pass UUID directly, not string
                            )
                            
                            if saved_correction:
                                logger.info(f"✅ Correction saved to cache (ID: {saved_correction.id})")
                                logger.info(f"   Future errors of this type will be fixed automatically!")
                            
                            xml_content = corrected_xml
                            correction_applied = True
                            correction_method = "AI (new)"
                            ai_correction_used = True
                            
                            # Save corrected XML
                            corrected_path = await save_file_to_storage(
                                corrected_xml.encode('utf-8'),
                                f"{tracking_id}_corrected.xml",
                                "uploads"
                            )
                            xml_path = corrected_path
                        else:
                            logger.warning(f"⚠️ AI correction did not produce changes")
                    
                    # Step 3: Re-validate if correction was applied
                    if correction_applied:
                        logger.info(f"🔍 Re-validating corrected XML...")
                        xml_valid, xml_message, xml_warnings = validate_xml(xml_path, strict_validation)
                        
                        if xml_valid:
                            logger.info(f"🎉 Correction successful! XML now valid.")
                            logger.info(f"   Correction method: {correction_method}")
                            # Clear errors since correction worked
                            xml_errors = []
                            all_errors = [e for e in all_errors if e not in original_xml_errors]
                        else:
                            logger.warning(f"⚠️ Correction applied but validation still fails")
                            logger.warning(f"   Correction method used: {correction_method}")
                            logger.warning(f"   New validation message: {xml_message}")
                    else:
                        logger.warning(f"⚠️ No correction could be applied")
                    
                except Exception as correction_error:
                    logger.error(f"❌ Error during intelligent correction: {correction_error}")
                    logger.exception(correction_error)
                    ai_correction_used = False
                
                logger.info(f"🧠 ===== INTELLIGENT CORRECTION COMPLETE =====")
                # ======================================================

                # If after retry it's still invalid, return failure response
                if not xml_valid:
                    # Build detailed message with validation errors
                    validation_details = []
                    if xml_errors:
                        for err in xml_errors:
                            if err.user_message:
                                validation_details.append(err.user_message)
                            elif err.error_message:
                                validation_details.append(err.error_message)
                    
                    detailed_message = xml_message
                    if validation_details:
                        detailed_message = f"Validation failed: {', '.join(validation_details[:3])}"  # Show first 3 errors
                    if ai_correction_used:
                        detailed_message += " (AI correction attempted)"
                    
                    # Record failed step with detailed error information
                    processing_steps.append(ProcessingStepResult(
                        step_name="XML Validation",
                        step_number=3,
                        success=False,
                        duration_seconds=step2_duration,
                        message=detailed_message,
                        status=StepStatus(
                            xml_validation_pass=False,
                            xml_convert_message=detailed_message
                        ),
                        error_details=[convert_error_feedback_to_detail(err) for err in xml_errors]
                    ))

                    logger.info(f"💾 Saving failed invoice to database...")

                    # Determine blob paths for XML file
                    blob_xml_path = None
                    if USE_BLOB_STORAGE and xml_path and isinstance(xml_path, dict):
                        blob_xml_path = xml_path.get('url')
                        logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
                    else:
                        logger.info(f"📁 Using local XML path: {xml_path}")

                    # Save to failed table
                    failed_invoice = FailedModel(
                        tracking_id=tracking_id,
                        user_id=current_user.id,
                        xml_path=str(xml_path) if isinstance(xml_path, str) else (xml_path.get('pathname', str(
                            xml_path)) if xml_path and isinstance(xml_path, dict) else str(xml_path)),
                        xml_validation_pass=False,
                        xml_convert_message=xml_message,
                        edi_convert_pass=False,
                        edi_convert_message="Skipped due to XML validation failure",
                        processing_steps=json.loads(json.dumps([error.to_dict() if hasattr(error, 'to_dict') else error.dict() for error in all_errors])),
                        blob_xml_path=blob_xml_path,
                        blob_edi_path=None,
                        request_type=request_type,
                        target_file_format=customer_format
                    )
                    try:
                        db.add(failed_invoice)
                        db.commit()
                        logger.info(
                            f"💾 Successfully saved failed invoice to database for tracking ID {tracking_id}")
                    except Exception as db_err:
                        db.rollback()
                        logger.error(f"❌ Failed to save failed invoice to database: {db_err}")

                    # Prepare response with new simplified structure
                    response.processing_steps = processing_steps

                    # Return 200 OK with structured error response (file upload succeeded, processing failed)
                    total_duration = time.time() - start_time
                    logger.info(
                        f"📤 Returning 200 OK for processing failure (file upload succeeded) for tracking ID {tracking_id}")
                    logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
                    logger.info(
                        f"🚫 ===== INVOICE PROCESSING FAILED (XML VALIDATION) =====")
                    # Convert UUID to string for JSON serialization
                    response_dict = response.dict()
                    response_dict['tracking_id'] = str(response_dict['tracking_id'])
                    return Response(
                        content=json.dumps(response_dict),
                        status_code=status.HTTP_200_OK,
                        media_type="application/json"
                    )

        # Record successful XML validation step with warning status
        if processing_path.needs_xml_validation:  # Only record if we actually validated
            if xml_warnings:
                message = f"XML validation passed with {len(xml_warnings)} warnings"
                logger.info(
                    f"⚠️ STEP 2 COMPLETED: XML validation passed with warnings (took {step2_duration:.3f}s)")
            else:
                message = "XML validation passed"
                logger.info(
                    f"✅ STEP 2 COMPLETED: XML validation passed cleanly (took {step2_duration:.3f}s)")

            # Build detailed message
            detailed_message = message
            if ai_correction_used:
                detailed_message = "XML validation passed (AI correction applied)"
            if xml_warnings:
                warning_summary = "; ".join(xml_warnings[:2])  # Show first 2 warnings
                detailed_message += f" - Warnings: {warning_summary}"
            
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="XML Validation",
                step_number=3,
                success=True,
                duration_seconds=step2_duration,
                message=detailed_message,
                status=StepStatus(
                    xml_validation_pass=True,
                    xml_convert_message=detailed_message
                ),
                error_details=[DetailedErrorInfo(
                    error_code="W0001",
                    error_category="XML_VALIDATION",
                    error_message=warning,
                    severity="WARNING",
                    user_message=warning,
                    technical_details="Non-blocking validation warning",
                    suggested_actions=["Review XML content for potential improvements"]
                ) for warning in xml_warnings] if xml_warnings else []
            ))
        else:
            # Record skipped step for xmlembed format customers
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="XML Validation",
                step_number=3,
                success=True,
                duration_seconds=0.0,
                message="XML validation skipped for xmlembed format customer",
                status=StepStatus(
                    xml_validation_pass=True,
                    xml_convert_message="XML validation skipped for xmlembed format customer"
                )
            ))

        # Step 3: Format Conversion (based on processing path)
        converted_content = None  # Store converted content for embed workflow
        
        if not processing_path.needs_conversion:
            logger.info(f"⏭️ SKIPPING STEP 3 & 4: Format Conversion (not required for {processing_path.format_name})")
            edi_success = True
            edi_message = f"Format conversion skipped for {processing_path.format_name}"
            x12_path = xml_path  # Use XML path directly
            logger.info(f"🔍 DEBUG - For passthrough format, set x12_path = xml_path")
            logger.info(f"🔍 DEBUG - xml_path type: {type(xml_path)}, is_dict: {isinstance(xml_path, dict)}")
            logger.info(f"🔍 DEBUG - x12_path type: {type(x12_path)}, is_dict: {isinstance(x12_path, dict)}")
            if isinstance(xml_path, dict):
                logger.info(f"🔍 DEBUG - xml_path keys: {xml_path.keys()}")
                logger.info(f"🔍 DEBUG - xml_path['url']: {xml_path.get('url')}")
            step3_duration = 0.0
            step4_duration = 0.0
            edi_format_valid = True
            
            # Record skipped steps
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="Format Conversion",
                step_number=4,
                success=True,
                duration_seconds=0.0,
                message=f"Format conversion skipped for {processing_path.format_name}",
                status=StepStatus(
                    edi_convert_pass=True,
                    edi_convert_message=f"Format conversion skipped for {processing_path.format_name}"
                )
            ))
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="Format Validation",
                step_number=4,
                success=True,
                duration_seconds=0.0,
                message=f"Format validation skipped for {processing_path.format_name}",
                status=StepStatus(
                    edi_convert_pass=True,
                    edi_convert_message=f"Format validation skipped for {processing_path.format_name}"
                )
            ))
            
        else:
            # Execute format conversion based on target format
            step3_start = time.time()
            logger.info(f"🔄 ===== STEP 4: FORMAT CONVERSION TO {processing_path.conversion_target} =====")
            x12_filename = f"{tracking_id}_converted.{processing_path.conversion_target.lower()}"
            logger.info(f"📄 Converting XML to {processing_path.conversion_target} format")
            logger.info(f"📁 Source XML: {xml_path}")
            logger.info(f"📁 Target filename: {x12_filename}")
            logger.info(f"🔍 Calling conversion function...")

            # Use appropriate converter based on target format
            if processing_path.conversion_target == "EDIFACT":
                logger.info(f"🔄 Using XML→EDIFACT converter")
                edi_success, edi_message, x12_path = await convert_xml_to_edifact(xml_path, x12_filename)
            else:
                logger.info(f"🔄 Using XML→X12 converter")
                edi_success, edi_message, x12_path = await convert_xml_to_x12(xml_path, x12_filename)
            
            # Store converted content for embed workflow (if needed later)
            if edi_success and processing_path.needs_embed:
                try:
                    converted_bytes = await read_file_from_storage(x12_path, None, None)
                    converted_content = converted_bytes.decode('utf-8')
                    logger.info(f"✅ Converted content stored for embed workflow")
                except Exception as e:
                    logger.warning(f"⚠️ Could not store converted content: {e}")

            step3_duration = time.time() - step3_start
            logger.info(f"🔄 EDI conversion completed in {step3_duration:.3f}s")
            logger.info(f"📊 EDI conversion result: {edi_success}")
            logger.info(f"📝 EDI conversion message: {edi_message}")

            if not edi_success:
                logger.error(
                    f"❌ STEP 3 FAILED: EDI conversion failed for tracking ID {tracking_id}")

                edi_errors = []
                
                # Read XML content safely
                try:
                    if isinstance(xml_path, str):
                        xml_content = Path(xml_path).read_text(encoding="utf-8")
                    else:
                        # xml_path is a blob response
                        xml_content_bytes = await read_file_from_storage(xml_path, None, None)
                        xml_content = xml_content_bytes.decode('utf-8')
                except Exception as read_err:
                    logger.error(f"❌ Could not read XML for error handling: {read_err}")
                    xml_content = ""
                
                # Read EDI content safely
                try:
                    if isinstance(x12_path, str) and Path(x12_path).exists():
                        edi_content = Path(x12_path).read_text(encoding="utf-8")
                    else:
                        edi_content = ""
                except Exception as read_err:
                    logger.error(f"❌ Could not read EDI for error handling: {read_err}")
                    edi_content = ""

                if "XML parsing error" in edi_message:
                    error_type = "conversion_failed"
                elif "missing" in edi_message or "required" in edi_message:
                    error_type = "missing_data"
                elif "party" in edi_message.lower():
                    error_type = "party_incomplete"
                elif "line" in edi_message.lower():
                    error_type = "line_item_error"
                else:
                    error_type = "conversion_failed"

                error_feedback = error_tracker.create_edi_conversion_error(
                    error_type=error_type,
                    error_message=edi_message,
                    file_name=file.filename,
                    tracking_id=str(tracking_id),
                    user_id=current_user.id,
                    timestamp=time.time()
                )
                edi_errors.append(error_feedback)

                # ======================================================
                # 🤖 INTELLIGENT EDI CORRECTION (CACHE + AI FALLBACK)
                # ======================================================
                logger.info(f"🧠 ===== ATTEMPTING INTELLIGENT EDI CORRECTION =====")
                edi_correction_applied = False
                edi_correction_method = None
                
                try:
                    # Initialize correction cache service
                    cache_service = CorrectionCacheService(db)
                    
                    # Generate error signature for EDI
                    error_context = {
                        "error_type": error_type,
                        "message": edi_message
                    }
                    
                    error_signature = cache_service.generate_error_signature(
                        error_type=error_type,
                        error_context=error_context
                    )
                    
                    # Check for cached EDI correction
                    cached_edi_correction = cache_service.find_correction(
                        customer_id=customer_id or "UNKNOWN",
                        error_type=error_type,
                        error_signature=error_signature,
                        correction_type="EDI"
                    )
                    
                    if cached_edi_correction:
                        logger.info(f"✅ Found cached EDI correction (ID: {cached_edi_correction.id})")
                        
                        # Apply cached EDI correction
                        transformation_rule = cached_edi_correction.transformation_rule
                        
                        if transformation_rule.get("action") == "ai_full_correction":
                            # Need AI for full correction
                            logger.info(f"🤖 Calling AI for EDI correction...")
                            edi_corrected, corrected_edi = await auto_fix_edi_with_ai(
                                xml_content, edi_content, edi_errors, strict_validation
                            )
                            
                            if edi_corrected:
                                edi_content = corrected_edi
                                edi_correction_applied = True
                                edi_correction_method = "AI (guided by cache)"
                                
                                # Save corrected EDI
                                corrected_edi_path = await save_file_to_storage(
                                    corrected_edi.encode('utf-8'),
                                    f"{tracking_id}_corrected.x12",
                                    "converted"
                                )
                                x12_path = corrected_edi_path
                                
                                cache_service.mark_success(str(cached_edi_correction.id))
                        else:
                            # Apply rule-based EDI correction
                            success, corrected_edi, message = cache_service.apply_edi_correction(
                                edi_content, transformation_rule
                            )
                            
                            if success:
                                edi_content = corrected_edi
                                edi_correction_applied = True
                                edi_correction_method = "Cached rule"
                                
                                # Save corrected EDI
                                corrected_edi_path = await save_file_to_storage(
                                    corrected_edi.encode('utf-8'),
                                    f"{tracking_id}_corrected.x12",
                                    "converted"
                                )
                                x12_path = corrected_edi_path
                                
                                cache_service.mark_success(str(cached_edi_correction.id))
                            else:
                                cache_service.mark_failure(str(cached_edi_correction.id))
                    
                    # If no cache or cache failed, try AI
                    if not edi_correction_applied:
                        logger.info(f"🤖 Calling AI for new EDI correction...")
                        edi_corrected, corrected_edi = await auto_fix_edi_with_ai(
                            xml_content, edi_content, edi_errors, strict_validation
                        )
                        
                        if edi_corrected:
                            logger.info(f"✅ AI EDI correction successful")
                            
                            # Save to cache
                            saved_correction = cache_service.save_correction_from_ai(
                                customer_id=customer_id or "UNKNOWN",
                                customer_name=customer_name,
                                error_type=error_type,
                                error_signature=error_signature,
                                correction_type="EDI",
                                original_content=edi_content[:2000],
                                corrected_content=corrected_edi[:2000],
                                ai_model="gpt-4o-mini",
                                user_id=current_user.id if current_user else None  # Pass UUID directly, not string
                            )
                            
                            if saved_correction:
                                logger.info(f"✅ EDI correction saved to cache (ID: {saved_correction.id})")
                            
                            edi_content = corrected_edi
                            edi_correction_applied = True
                            edi_correction_method = "AI (new)"
                            
                            # Save corrected EDI
                            corrected_edi_path = await save_file_to_storage(
                                corrected_edi.encode('utf-8'),
                                f"{tracking_id}_corrected.x12",
                                "converted"
                            )
                            x12_path = corrected_edi_path
                    
                    if edi_correction_applied:
                        logger.info(f"🎉 EDI correction successful! Method: {edi_correction_method}")
                        # Clear EDI errors
                        edi_errors = []
                        edi_success = True
                        edi_message = f"EDI conversion successful (corrected by {edi_correction_method})"
                    
                except Exception as edi_correction_error:
                    logger.error(f"❌ Error during EDI correction: {edi_correction_error}")
                    logger.exception(edi_correction_error)
                
                logger.info(f"🧠 ===== INTELLIGENT EDI CORRECTION COMPLETE =====")
                # ======================================================

                all_errors.extend(edi_errors)

                # Build detailed message for failed EDI conversion
                detailed_edi_message = edi_message
                if customer_id or customer_name:
                    customer_info = []
                    if customer_id:
                        customer_info.append(f"Customer ID: {customer_id}")
                    if customer_name:
                        customer_info.append(f"Customer: {customer_name}")
                    if customer_format:
                        customer_info.append(f"Format: {customer_format.upper()}")
                    detailed_edi_message = f"EDI conversion failed - {', '.join(customer_info)}. Error: {edi_message}"
                
                add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                    step_name="EDI Conversion",
                    step_number=4,
                    success=False,
                    duration_seconds=step3_duration,
                    message=detailed_edi_message,
                    status=StepStatus(
                        edi_convert_pass=False,
                        edi_convert_message=detailed_edi_message
                    ),
                    error_details=[convert_error_feedback_to_detail(err) for err in edi_errors]
                ))

                logger.warning(f"⚠️ EDI conversion failed, marking workflow as failed but continuing to next steps...")
                workflow_failed = True
                # Don't return here - let it continue to Steps 5 and 6 (skip Step 4 since no EDI file)
            else:
                # Record successful EDI conversion step with customer and format info
                edi_message = "EDI conversion completed successfully"
                if customer_id or customer_name:
                    customer_info = []
                    if customer_id:
                        customer_info.append(f"Customer ID: {customer_id}")
                    if customer_name:
                        customer_info.append(f"Customer: {customer_name}")
                if customer_format:
                    customer_info.append(f"Format: {customer_format.upper()}")
                edi_message = f"EDI conversion completed - {', '.join(customer_info)}"
            
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="EDI Conversion",
                step_number=4,
                success=True,
                duration_seconds=step3_duration,
                message=edi_message,
                status=StepStatus(
                    edi_convert_pass=True,
                    edi_convert_message=edi_message
                )
            ))

            logger.info(
                f"✅ STEP 3 COMPLETED: EDI conversion successful (took {step3_duration:.3f}s)")

            # Step 5: EDI Format Validation (only if Step 3 succeeded and format is X12)
            step4_start = time.time()
            
            # Skip format validation for EDIFACT (uses different segment structure)
            if processing_path.conversion_target == "EDIFACT":
                logger.info(f"⏭️ ===== STEP 5: EDI FORMAT VALIDATION (SKIPPED FOR EDIFACT) =====")
                logger.info(f"📄 EDIFACT uses different segment structure than X12 - skipping X12 validation")
                edi_format_valid = True
                edi_format_message = "Format validation skipped for EDIFACT (different segment structure)"
                edi_format_details = None
                step4_duration = time.time() - step4_start
            else:
                logger.info(f"🔍 ===== STEP 5: EDI FORMAT VALIDATION =====")
                logger.info(
                    f"📄 Validating EDI format fields for correct values, format, and length")
                logger.info(f"🔍 Calling validate_edi_format function...")

                edi_format_valid, edi_format_message, edi_format_details = await validate_edi_format(x12_path)

                step4_duration = time.time() - step4_start
                logger.info(
                    f"🔍 EDI format validation completed in {step4_duration:.3f}s")
                logger.info(f"📊 EDI format validation result: {edi_format_valid}")
                logger.info(f"📝 EDI format validation message: {edi_format_message}")

            if not edi_format_valid:
                # Only treat as error if it's not EDIFACT (EDIFACT validation is skipped)
                if processing_path.conversion_target == "EDIFACT":
                    # This shouldn't happen since we set edi_format_valid=True for EDIFACT above
                    logger.warning(f"⚠️ Unexpected: EDIFACT validation marked as invalid")
                else:
                    logger.error(
                        f"❌ STEP 4 FAILED: EDI format validation failed for tracking ID {tracking_id}")
                    logger.error(f"💥 Failure reason: {edi_format_message}")
        
                    edi_format_errors = []
                    if edi_format_details:
                        for segment_name, segment_data in edi_format_details.items():
                            if not segment_data['valid'] and segment_data['errors']:
                                error_feedback = error_tracker.create_edi_validation_error(
                                    segment_name=segment_name,
                                    field_errors=segment_data['errors'],
                                    edi_preview=edi_content[:1000] if 'edi_content' in locals() else None,
                                    file_name=file.filename,
                                    tracking_id=str(tracking_id),
                                    user_id=current_user.id,
                                    timestamp=time.time()
                                )
                                edi_format_errors.append(error_feedback)
                    else:
                        error_feedback = error_tracker.create_edi_validation_error(
                            segment_name="UNKNOWN",
                            field_errors=[edi_format_message],
                            edi_preview=edi_content[:1000] if 'edi_content' in locals() else None,
                            file_name=file.filename,
                            tracking_id=str(tracking_id),
                            user_id=current_user.id,
                            timestamp=time.time()
                        )
                        edi_format_errors.append(error_feedback)
        
                    all_errors.extend(edi_format_errors)
        
                    # ======================================================
                    # 🤖 INTELLIGENT EDI FORMAT CORRECTION
                    # ======================================================
                    logger.info(f"🧠 ===== ATTEMPTING EDI FORMAT CORRECTION =====")
                    format_correction_applied = False
                    
                    try:
                        cache_service = CorrectionCacheService(db)
                        
                        # Try to correct EDI format errors
                        for err in edi_format_errors:
                            error_context = {
                                "error_type": "edi_format_validation",
                                "message": edi_format_message
                            }
                            
                            error_signature = cache_service.generate_error_signature(
                                error_type="EDI_FORMAT",
                                error_context=error_context
                            )
                            
                            cached_format_correction = cache_service.find_correction(
                                customer_id=customer_id or "UNKNOWN",
                                error_type="EDI_FORMAT",
                                error_signature=error_signature,
                                correction_type="EDI"
                            )
                            
                            if cached_format_correction:
                                logger.info(f"✅ Found cached format correction")
                                # Apply format correction similar to above
                                transformation_rule = cached_format_correction.transformation_rule
                                
                                if transformation_rule.get("action") != "ai_full_correction":
                                    success, corrected_edi, message = cache_service.apply_edi_correction(
                                        edi_content if 'edi_content' in locals() else "",
                                        transformation_rule
                                    )
                                    
                                    if success:
                                        format_correction_applied = True
                                        logger.info(f"✅ Format correction applied: {message}")
                                        cache_service.mark_success(str(cached_format_correction.id))
                                        break
                        
                        if format_correction_applied:
                            logger.info(f"🎉 EDI format corrected successfully!")
                            edi_format_valid = True
                            edi_format_errors = []
                            
                    except Exception as format_correction_error:
                        logger.error(f"❌ Error during format correction: {format_correction_error}")
                    
                    logger.info(f"🧠 ===== EDI FORMAT CORRECTION COMPLETE =====")
                    # ======================================================
        
                    # 🧩 Record EDI format validation failure but continue processing
                    edi_format_message_display = f"EDI conversion completed but format validation failed: {edi_format_message}"

                    add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                        step_name="EDI Format Validation",
                        step_number=5,
                        success=False,
                        duration_seconds=step4_duration,
                        message=edi_format_message,
                        status=StepStatus(
                            edi_convert_pass=False,
                            edi_convert_message=edi_format_message_display
                        ),
                        error_details=[convert_error_feedback_to_detail(err) for err in edi_format_errors]
                    ))

                    logger.warning(f"⚠️ EDI format validation failed, marking workflow as failed but continuing to next steps...")
                    workflow_failed = True
            else:
                # Record successful EDI format validation step
                add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                    step_name="EDI Format Validation",
                    step_number=5,
                    success=True,
                    duration_seconds=step4_duration,
                    message=edi_format_message,
                    status=StepStatus(
                        edi_convert_pass=True,
                        edi_convert_message=edi_format_message
                    )
                ))

                logger.info(
                    f"✅ STEP 4 COMPLETED: EDI format validation successful (took {step4_duration:.3f}s)")
        
        # Step 4A: EDINation Validation (only for X12 format)
        if processing_path.needs_edination_validation:
            step4a_start = time.time()
            logger.info(f"🔍 ===== STEP 4A: EDINATION X12 VALIDATION =====")
            logger.info(f"📄 Validating X12 content with EDINation API")
            
            try:
                # Read X12 content
                x12_content_bytes = await read_file_from_storage(x12_path, None, None)
                x12_content_str = x12_content_bytes.decode('utf-8')
                
                # Validate with EDINation
                edination_valid, edination_message, edination_errors = await validate_x12_with_edination(x12_content_str)
                
                step4a_duration = time.time() - step4a_start
                
                if edination_valid:
                    logger.info(f"✅ EDINation validation passed")
                    add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                        step_name="EDINation X12 Validation",
                        step_number=5,  # Same step number as format validation
                        success=True,
                        duration_seconds=step4a_duration,
                        message=edination_message
                    ))
                else:
                    logger.warning(f"⚠️ EDINation validation failed: {edination_message}")
                    logger.warning(f"⚠️ Continuing processing despite EDINation validation failure")
                    add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                        step_name="EDINation X12 Validation",
                        step_number=5,
                        success=False,
                        duration_seconds=step4a_duration,
                        message=f"EDINation validation warning: {edination_message}"
                    ))
                    
            except Exception as e:
                logger.error(f"❌ EDINation validation error: {str(e)}")
                logger.warning(f"⚠️ Continuing processing despite EDINation error")
                add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                    step_name="EDINation X12 Validation",
                    step_number=4,
                    success=False,
                    duration_seconds=time.time() - step4a_start,
                    message=f"EDINation validation error: {str(e)}"
                ))
        
        # Step 4B: XML Embed Workflow (if needed)
        if processing_path.needs_embed:
            step4b_start = time.time()
            logger.info(f"📎 ===== STEP 4B: XML EMBED WORKFLOW ({processing_path.embed_type}) =====")
            
            try:
                # Ensure xml_content is available for embed workflow
                if xml_content is None or xml_content == "":
                    logger.info("📖 Reading XML content for embed workflow...")
                    file_content_bytes = await read_file_from_storage(xml_path, None, None)
                    xml_content = file_content_bytes.decode('utf-8')
                
                # Handle embed workflow
                embed_success, embed_message, modified_xml_path = await handle_embed_workflow(
                    xml_content=xml_content,
                    xml_path=xml_path,
                    tracking_id=str(tracking_id),
                    embed_type=processing_path.embed_type,
                    converted_content=converted_content
                )
                
                step4b_duration = time.time() - step4b_start
                
                if embed_success:
                    logger.info(f"✅ Embed workflow completed successfully")
                    # Update xml_path to point to modified XML with embedded content
                    xml_path = modified_xml_path
                    # IMPORTANT: Also update x12_path so blob_edi_path gets set correctly
                    # For XML_EMBED formats, the final file to send to API is the modified XML
                    x12_path = modified_xml_path
                    logger.info(f"📝 Updated x12_path to modified XML for blob_edi_path: {x12_path}")
                    add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                        step_name=f"{processing_path.embed_type} Embed",
                        step_number=5,
                        success=True,
                        duration_seconds=step4b_duration,
                        message=embed_message
                    ))
                else:
                    logger.error(f"❌ Embed workflow failed: {embed_message}")
                    add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                        step_name=f"{processing_path.embed_type} Embed",
                        step_number=5,
                        success=False,
                        duration_seconds=step4b_duration,
                        message=embed_message
                    ))
                    
            except Exception as e:
                logger.error(f"❌ Embed workflow error: {str(e)}")
                add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                    step_name=f"{processing_path.embed_type} Embed",
                    step_number=4,
                    success=False,
                    duration_seconds=time.time() - step4b_start,
                    message=f"Embed workflow error: {str(e)}"
                ))
        
        # Step 5: Send to Third Party Endpoint (conditional based on processing path)
        step5_start = time.time()
        third_party_success = False
        third_party_message = "Third party endpoint not called"
        third_party_response = {}
        
        if processing_path.needs_third_party:
            # Execute Step 5 for formats that need third party API
            logger.info(f"🌐 ===== STEP 6: THIRD PARTY ENDPOINT ({processing_path.format_name}) =====")
            logger.info(f"📄 Sending XML content to third party endpoint")
            
            third_party_errors = []
            try:
                # Read XML content to send
                if USE_BLOB_STORAGE and isinstance(xml_path, dict):
                    blob_xml_path_temp = xml_path.get('url')
                    xml_content_bytes = await read_file_from_storage(None, blob_xml_path_temp, None)
                    xml_content_to_send = xml_content_bytes.decode('utf-8')
                else:
                    xml_content_to_send = Path(xml_path).read_text(encoding='utf-8')
                    
                logger.info(f"📊 XML content loaded: {len(xml_content_to_send)} bytes")
                
                # Send XML to third party endpoint
                third_party_success, third_party_message, third_party_response = await send_to_third_party_endpoint(
                    xml_content_to_send, tracking_id
                )
                
                # If third party call failed, create error feedback with details
                if not third_party_success:
                    # Extract error code and message from response if available
                    response_code = third_party_response.get('code') if isinstance(third_party_response, dict) else None
                    response_msg = third_party_response.get('message') if isinstance(third_party_response, dict) else None
                    
                    # Determine error type based on response or message
                    if response_msg and 'customization' in response_msg.lower():
                        error_type = "rejected"
                        error_detail = f"XML Customization value issue: {response_msg}"
                    elif response_msg and 'validation' in response_msg.lower():
                        error_type = "rejected"
                        error_detail = f"XML Validation issue: {response_msg}"
                    elif response_code and str(response_code).startswith('4'):
                        error_type = "rejected"
                        error_detail = f"Request error (Code {response_code}): {response_msg or third_party_message}"
                    else:
                        error_type = "unavailable"
                        error_detail = third_party_message
                    
                    error_feedback = error_tracker.create_third_party_error(
                        error_type=error_type,
                        error_message=error_detail,
                        api_endpoint="https://dbnasender.cfdise.com/PeppolSoftDBNA/v1/xml/generateDocument",
                        status_code=int(response_code) if response_code and str(response_code).isdigit() else None,
                        response_body=str(third_party_response),
                        file_name=file.filename,
                        tracking_id=str(tracking_id),
                        user_id=current_user.id,
                        timestamp=time.time()
                    )
                    third_party_errors.append(convert_error_feedback_to_detail(error_feedback))
                    logger.warning(f"⚠️ Third party endpoint error: {error_detail}")
                    
            except Exception as e:
                if "auth" in str(e).lower() or "401" in str(e) or "403" in str(e):
                    error_type = "auth_failed"
                elif "timeout" in str(e).lower():
                    error_type = "timeout"
                elif "connect" in str(e).lower() or "unavailable" in str(e).lower():
                    error_type = "unavailable"
                else:
                    error_type = "rejected"
                
                error_feedback = error_tracker.create_third_party_error(
                    error_type=error_type,
                    error_message=str(e),
                    file_name=file.filename,
                    tracking_id=str(tracking_id),
                    user_id=current_user.id,
                    timestamp=time.time()
                )
                third_party_errors.append(convert_error_feedback_to_detail(error_feedback))
                logger.error(f"❌ Failed to send to third party endpoint: {e}")
                third_party_message = error_feedback.user_message
            
            step5_duration = time.time() - step5_start
            logger.info(f"🌐 Third party endpoint call completed in {step5_duration:.3f}s")
            logger.info(f"📊 Third party result: {third_party_success}")
            logger.info(f"📝 Third party message: {third_party_message}")
            
            # Record third party endpoint step with error details if applicable
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="3rd Party Endpoint",
                step_number=6,
                success=third_party_success,
                duration_seconds=step5_duration,
                message=third_party_message,
                error_details=third_party_errors if third_party_errors else None
            ))
            
            if third_party_success:
                logger.info(f"✅ STEP 5 COMPLETED: Third party endpoint successful (took {step5_duration:.3f}s)")
            else:
                logger.warning(f"⚠️ STEP 5 WARNING: Third party endpoint failed (took {step5_duration:.3f}s)")
                logger.warning(f"⚠️ Continuing with invoice processing despite third party failure")
        else:
            # Skip Step 5 for formats that don't need third party API
            logger.info(f"⏭️ SKIPPING STEP 6: Third Party Endpoint ({processing_path.format_name} doesn't require it)")
            step5_duration = 0.0
            
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="3rd Party Endpoint",
                step_number=6,
                success=True,
                duration_seconds=0.0,
                message=f"Third party endpoint skipped for {processing_path.format_name} format"
            ))

        # Step 6: Success - Save to database (success or failed table based on workflow status)
        step6_start = time.time()
        
        # Determine if the overall workflow was successful by checking all processing steps
        # A step is considered critical if it's not a skipped step
        workflow_failed = False
        failed_steps = []
        
        for step in processing_steps:
            # Check if step failed (success=False) and it's a critical step
            # Steps 1, 2, 3, 4 are critical for XML->EDI workflows
            # Step 5 is only critical for xmlembed format customers (otherwise it's skipped with success=True)
            if not step.success:
                # Step 6 (Third Party) can fail without being critical if it's skipped
                if step.step_number == 6 and step.success == False:
                    # For xmlembed customers, step 6 is critical; for others it's skipped (success=True)
                    if "not called" not in step.message and "skipped" not in step.message.lower():
                        logger.warning(f"⚠️ Step {step.step_number} ({step.step_name}) failed but processing continues")
                elif step.step_number in [1, 2, 3, 4, 5]:
                    # These are critical steps
                    workflow_failed = True
                    failed_steps.append(step.step_name)
        
        if workflow_failed:
            logger.warning(f"⚠️ ===== STEP 7: DATABASE SAVE (FAILED) =====")
            logger.warning(f"💾 Saving failed invoice to failed table due to: {', '.join(failed_steps)}")
        else:
            # Also check if third-party API failed for formats that need it
            if processing_path.needs_third_party and not third_party_success:
                logger.warning(f"⚠️ ===== STEP 7: DATABASE SAVE (FAILED) =====")
                logger.warning(f"💾 Saving invoice to failed table due to third-party API failure")
                workflow_failed = True
                failed_steps.append("3rd Party Endpoint")
            else:
                logger.info(f"🎉 ===== STEP 7: DATABASE SAVE (SUCCESS) =====")
                logger.info(f"💾 Saving successful invoice to database...")
        
        logger.info(f"📊 Creating record with tracking ID: {tracking_id}")
        
        # DEBUG: Log what we have before extracting blob paths
        logger.info(f"🔍 DEBUG - xml_path type: {type(xml_path)}, value: {xml_path}")
        logger.info(f"🔍 DEBUG - x12_path type: {type(x12_path)}, value: {x12_path}")
        logger.info(f"🔍 DEBUG - USE_BLOB_STORAGE: {USE_BLOB_STORAGE}")
        
        # Determine blob paths for XML and EDI files
        blob_xml_path = None
        blob_edi_path = None

        if USE_BLOB_STORAGE:
            if xml_path and isinstance(xml_path, dict):
                blob_xml_path = xml_path.get('url')
                logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
            else:
                logger.warning(f"⚠️ xml_path is not a dict or is None - type: {type(xml_path)}")
            
            if x12_path and isinstance(x12_path, dict):
                blob_edi_path = x12_path.get('url')
                logger.info(f"🔗 Extracted blob EDI URL: {blob_edi_path}")
            else:
                logger.warning(f"⚠️ x12_path is not a dict or is None - type: {type(x12_path)}")
        else:
            logger.info(f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")
        
        # Final values
        logger.info(f"✅ Final blob_xml_path: {blob_xml_path}")
        logger.info(f"✅ Final blob_edi_path: {blob_edi_path}")
        
        # Use already determined format from processing path
        format_type = processing_path.format_name
        logging.info(f"The format will be {format_type}")

        # Determine step success flags based on processing_steps
        xml_validation_pass = True
        xml_convert_message = "XML validation passed"
        edi_convert_pass = True
        edi_convert_message = "EDI conversion and format validation completed successfully"
        
        for step in processing_steps:
            if step.step_number == 3 and not step.success:  # XML Validation
                xml_validation_pass = False
                xml_convert_message = step.message
            elif step.step_number == 4 and not step.success:  # EDI Conversion
                edi_convert_pass = False
                edi_convert_message = step.message
            elif step.step_number == 5 and not step.success:  # EDI Format Validation
                edi_convert_pass = False
                edi_convert_message = step.message

        if workflow_failed:
            # Convert processing_steps to JSON-serializable format
            processing_steps_data = []
            for step in processing_steps:
                step_dict = {
                    "step_name": step.step_name,
                    "step_number": step.step_number,
                    "success": step.success,
                    "duration_seconds": step.duration_seconds,
                    "message": step.message,
                    "status": step.status.dict() if step.status else None,
                    "error_details": [err.dict() for err in step.error_details] if step.error_details else None
                }
                processing_steps_data.append(step_dict)
            
            # Create new failed record
            failed_invoice = FailedModel(
                tracking_id=tracking_id,
                user_id=current_user.id,
                xml_path=str(xml_path) if isinstance(xml_path, str) else xml_path.get('pathname', str(xml_path)),
                xml_validation_pass=xml_validation_pass,
                xml_convert_message=xml_convert_message,
                edi_path=str(x12_path) if isinstance(x12_path, str) else x12_path.get('pathname', str(x12_path)) if x12_path else None,
                edi_convert_pass=edi_convert_pass,
                edi_convert_message=edi_convert_message,
                blob_xml_path=blob_xml_path,
                blob_edi_path=blob_edi_path,
                request_type=request_type,
                target_file_format=format_type,
                processing_steps=processing_steps_data
            )
            try:
                db.add(failed_invoice)
                db.commit()
                step6_duration = time.time() - step6_start
                logger.warning(f"💾 Successfully saved failed invoice to database (took {step6_duration:.3f}s)")
                logger.warning(f"⚠️ STEP 6 COMPLETED: Database save to FAILED table (took {step6_duration:.3f}s)")
                
                # Add Step 6: Database Save
                step6_result = ProcessingStepResult(
                    step_name="Database Save",
                    step_number=7,
                    success=True,
                    duration_seconds=step6_duration,
                    message="Invoice saved to failed table"
                )
                add_processing_step(tracking_id, processing_steps, step6_result)
                status_tracker.mark_completed(tracking_id)
            except Exception as db_err:
                db.rollback()
                error_feedback = error_tracker.create_database_error(
                    operation="save to failed table",
                    error_message=str(db_err),
                    table_name="zodiac_invoice_failed_edi",
                    tracking_id=str(tracking_id),
                    user_id=current_user.id,
                    timestamp=time.time()
                )
                logger.error(f"❌ Database save to failed table failed: {db_err}")
        else:
            # Convert processing_steps to JSON-serializable format
            processing_steps_data = []
            for step in processing_steps:
                step_dict = {
                    "step_name": step.step_name,
                    "step_number": step.step_number,
                    "success": step.success,
                    "duration_seconds": step.duration_seconds,
                    "message": step.message,
                    "status": step.status.dict() if step.status else None,
                    "error_details": [err.dict() for err in step.error_details] if step.error_details else None
                }
                processing_steps_data.append(step_dict)
            
            # Save to SUCCESS table
            success_invoice = SuccessModel(
                tracking_id=tracking_id,
                user_id=current_user.id,
                xml_path=str(xml_path) if isinstance(xml_path, str) else xml_path.get('pathname', str(xml_path)),
                xml_validation_pass=xml_validation_pass,
                xml_convert_message=xml_convert_message,
                edi_path=str(x12_path) if isinstance(x12_path, str) else x12_path.get('pathname', str(x12_path)) if x12_path else None,
                edi_convert_pass=edi_convert_pass,
                edi_convert_message=edi_convert_message,
                blob_xml_path=blob_xml_path,
                blob_edi_path=blob_edi_path,
                request_type=request_type,
                external_status="success" if third_party_success else "failed",
                external_message=third_party_message,
                target_file_format=format_type,
                processing_steps=processing_steps_data
            )
            try:
                db.add(success_invoice)
                db.commit()

                step6_duration = time.time() - step6_start
                logger.info(f"💾 Successfully saved invoice to database (took {step6_duration:.3f}s)")
                logger.info(f"✅ STEP 6 COMPLETED: Database save to SUCCESS table (took {step6_duration:.3f}s)")
                
                # Add Step 6: Database Save
                step6_result = ProcessingStepResult(
                    step_name="Database Save",
                    step_number=7,
                    success=True,
                    duration_seconds=step6_duration,
                    message="Invoice saved to success table"
                )
                
                add_processing_step(tracking_id, processing_steps, step6_result)
                status_tracker.mark_completed(tracking_id)
            except Exception as db_err:
                db.rollback()
                error_feedback = error_tracker.create_database_error(
                    operation="save to success table",
                    error_message=str(db_err),
                    table_name="zodiac_invoice_success_edi",
                    tracking_id=str(tracking_id),
                    user_id=current_user.id,
                    timestamp=time.time()
                )
                logger.error(f"❌ Database save to success table failed: {db_err}")

        response.processing_steps = processing_steps
        total_duration = time.time() - start_time

        # Log warnings if any were found during processing
        if xml_warnings:
            logger.info(
                f"⚠️ Processing completed with {len(xml_warnings)} XML validation warnings")
            logger.info(f"📋 Warnings summary:")
            for warning in xml_warnings:
                logger.warning(f"   - {warning}")
        else:
            logger.info(f"✅ Processing completed cleanly with no warnings")

        logger.info(f"🎉 ===== INVOICE PROCESSING COMPLETED SUCCESSFULLY =====")
        logger.info(f"🆔 Tracking ID: {tracking_id}")
        logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
        logger.info(
            f"📊 Step timings: Upload={step1_duration:.3f}s, XML={step2_duration:.3f}s, EDI={step3_duration:.3f}s, EDI_Format={step4_duration:.3f}s, 3rdParty={step5_duration:.3f}s, DB={step6_duration:.3f}s")
        if x12_filename:
            logger.info(f"📁 Files created: XML={xml_filename}, X12={x12_filename}")
        else:
            logger.info(f"📁 Files created: XML={xml_filename}")

        # Return 201 Created for successful processing
        logger.info(f"📤 Returning 201 Created for tracking ID {tracking_id}")
        # Convert UUID to string for JSON serialization
        response_dict = response.dict()
        response_dict['tracking_id'] = str(response_dict['tracking_id'])
        return Response(
            content=json.dumps(response_dict),
            status_code=status.HTTP_201_CREATED,
            media_type="application/json"
        )

    except HTTPException:
        total_duration = time.time() - start_time
        logger.error(f"❌ ===== HTTP EXCEPTION RAISED =====")
        logger.error(f"🆔 Tracking ID: {tracking_id}")
        logger.error(
            f"⏱️ Processing time before failure: {total_duration:.3f}s")
        logger.error(f"💥 HTTP Exception raised for tracking ID {tracking_id}")
        raise
    except Exception as e:
        total_duration = time.time() - start_time
        logger.error(f"💥 ===== UNEXPECTED ERROR =====")
        logger.error(f"🆔 Tracking ID: {tracking_id}")
        logger.error(
            f"⏱️ Processing time before failure: {total_duration:.3f}s")
        logger.error(
            f"💥 Unexpected error during invoice processing for tracking ID {tracking_id}: {str(e)}")
        logger.error(f"🔍 Error type: {type(e).__name__}")
        logger.error(f"📝 Error details: {str(e)}")
        logger.exception(e)  # This prints the full stack trace
        
        # Log the number of steps completed before error
        if 'processing_steps' in locals():
            logger.error(f"📊 Processing steps completed before error: {len(processing_steps)}")
            for step in processing_steps:
                logger.error(f"   - Step {step.step_number}: {step.step_name} - Success: {step.success}")
        
        # Update status tracker with error
        if 'tracking_id' in locals() and 'status_tracker' in globals():
            try:
                status_tracker.update_step(tracking_id, ProcessingStepResult(
                    step_name="Unexpected Error",
                    step_number=99,
                    success=False,
                    duration_seconds=total_duration,
                    message=f"{type(e).__name__}: {str(e)}",
                    error_details=[DetailedErrorInfo(
                        error_code="E9999",
                        error_category="SYSTEM_ERROR",
                        error_message=str(e),
                        severity="CRITICAL",
                        user_message=f"A system error occurred: {str(e)}",
                        technical_details=f"{type(e).__name__}: {str(e)}",
                        suggested_actions=["Contact support", "Check server logs"],
                        file_name=file.filename if 'file' in locals() else "unknown",
                        timestamp=time.time()
                    )]
                ))
                status_tracker.mark_completed(tracking_id, success=False)
            except Exception as tracker_error:
                logger.error(f"❌ Could not update status tracker: {tracker_error}")

        if "blob storage" in str(e).lower():
            error_feedback = error_tracker.create_file_upload_error(
                error_type="storage_failed",
                file_name=file.filename if 'file' in locals() else None,
                tracking_id=str(tracking_id) if 'tracking_id' in locals() else None,
                user_id=current_user.id if 'current_user' in locals() else None,
                timestamp=time.time()
            )
        elif "xml" in str(e).lower():
            error_feedback = error_tracker.create_xml_validation_error(
                error_type="malformed",
                error_message=str(e),
                file_name=file.filename if 'file' in locals() else None,
                tracking_id=str(tracking_id) if 'tracking_id' in locals() else None,
                user_id=current_user.id if 'current_user' in locals() else None,
                timestamp=time.time()
            )
        elif "edi" in str(e).lower():
            error_feedback = error_tracker.create_edi_conversion_error(
                error_type="conversion_failed",
                error_message=str(e),
                file_name=file.filename if 'file' in locals() else None,
                tracking_id=str(tracking_id) if 'tracking_id' in locals() else None,
                user_id=current_user.id if 'current_user' in locals() else None,
                timestamp=time.time()
            )
        elif "database" in str(e).lower():
            error_feedback = error_tracker.create_database_error(
                operation="unknown",
                error_message=str(e),
                tracking_id=str(tracking_id) if 'tracking_id' in locals() else None,
                user_id=current_user.id if 'current_user' in locals() else None,
                timestamp=time.time()
            )
        else:
            error_feedback = error_tracker.create_file_upload_error(
                error_type="storage_failed",
                file_name=file.filename if 'file' in locals() else None,
                tracking_id=str(tracking_id) if 'tracking_id' in locals() else None,
                user_id=current_user.id if 'current_user' in locals() else None,
                timestamp=time.time()
            )

        # Build error response with new simplified structure
        error_step = ProcessingStepResult(
            step_name="Unexpected Error",
            step_number=len(processing_steps) + 1,
            success=False,
            duration_seconds=total_duration,
            message=error_feedback.user_message,
            error_details=[convert_error_feedback_to_detail(error_feedback)]
        )
        processing_steps.append(error_step)
        response.processing_steps = processing_steps

        response_dict = response.dict()
        response_dict['tracking_id'] = str(response_dict['tracking_id'])

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=response_dict)
