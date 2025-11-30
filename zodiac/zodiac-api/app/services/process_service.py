import json
import uuid
import vercel_blob
import time
import trace
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
from ..services.error_handlers import ErrorTracker
from ..services.ai_service import auto_correct_xml_with_ai, auto_fix_edi_with_ai
from ..services.file_service import save_file_to_storage, read_file_from_storage
from ..services.database import check_customer_table, extract_supplier_info_from_string
from ..services.external_api_service import send_to_third_party_endpoint
from ..api.api_key_auth import get_client_ip
from ..utils.xml_validation import validate_xml,validate_edi_format
from ..utils.xml_to_x12 import convert_xml_to_x12
from ..services.status_tracker import status_tracker
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

        # Store file content for later processing steps
        file_content = None
        try:
            file_content_bytes = await read_file_from_storage(xml_path, None, None)
            file_content = file_content_bytes.decode('utf-8')
        except Exception as e:
            logger.warning(f"⚠️ Could not read file content: {e}")

        # Determine customer format to decide processing path
        logger.info(f"🔍 ===== DETERMINING PROCESSING PATH =====")
        customer_format = None
        try:
            file_content_bytes = await read_file_from_storage(xml_path, None, None)
            xml_content = file_content_bytes.decode('utf-8')
            customer_id, customer_name = extract_supplier_info_from_string(xml_content)
            customer_format = check_customer_table(customer_id, customer_name, db)
            logger.info(f"📊 Customer ID: {customer_id}, Name: {customer_name}")
            logger.info(f"🎯 Target format from customer table: {customer_format}")
        except Exception as e:
            logger.warning(f"⚠️ Could not determine customer format: {e}")
            customer_format = 'edifact'  # Default to EDI processing
            logger.info(f"🎯 Using default format: {customer_format}")
        
        # Store customer info for later steps
        try:
            if not customer_id or not customer_name:
                file_content_bytes = await read_file_from_storage(xml_path, None, None)
                xml_content = file_content_bytes.decode('utf-8')
                customer_id, customer_name = extract_supplier_info_from_string(xml_content)
        except:
            pass
        
        # Decide processing path based on customer format
        process_as_xml = (customer_format and customer_format.upper() in  ['XMLEMBED',"XML"])
        if process_as_xml:
            logger.info(f"✅ Processing path: XML → Skip EDI conversion/validation → Third Party API (xmlembed format)")
        else:
            logger.info(f"✅ Processing path: XML validation → EDI conversion → EDI validation → Skip Third Party API ({customer_format} format)")

        # Step 2: XML Validation (Skip if customer format is xmlembed)
        if process_as_xml:
            logger.info(f"⏭️ SKIPPING STEP 2: XML Validation (customer format is xmlembed)")
            xml_valid = True
            xml_message = "XML validation skipped for xmlembed format customer"
            xml_warnings = []
            step2_duration = 0.0
        else:
            step2_start = time.time()
            logger.info(f"🔍 ===== STEP 2: XML VALIDATION =====")
            logger.info(f"📄 Validating XML file: {xml_path}")
            logger.info(f"🔍 Calling validate_xml function...")

            xml_valid, xml_message, xml_warnings = validate_xml(
                xml_path, strict_validation)

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
                # 🤖 AI AUTOCORRECTION ATTEMPT (only on XML validation failure)
                # ======================================================
                try:
                    logger.info(
                        f"🤖 Attempting AI autocorrection for failed XML validation (tracking ID: {tracking_id})")
                    xml_bytes = await read_file_from_storage(xml_path, None, None)
                    xml_text = xml_bytes.decode("utf-8")

                    was_corrected, corrected_xml = await auto_correct_xml_with_ai(xml_text, strict_validation)
                    ai_correction_used = was_corrected

                    if was_corrected:
                        logger.info(
                            f"✅ AI produced corrected XML. Saving and retrying validation...")
                        # Save corrected version over original
                        xml_path = await save_file_to_storage(corrected_xml.encode("utf-8"), xml_filename, "uploads")

                        # Retry validation once
                        xml_valid, xml_message, xml_warnings = validate_xml(
                            xml_path, strict_validation)

                        if xml_valid:
                            logger.info(
                                f"🎉 AI autocorrection fixed the XML issues! Proceeding to next step.")
                        else:
                            logger.warning(
                                f"⚠️ AI attempted correction but validation still failed: {xml_message}")
                    else:
                        logger.info(
                            f"ℹ️ AI could not find a valid correction; keeping original XML.")

                except Exception as e:
                    logger.warning(
                        f"⚠️ AI autocorrection skipped due to error: {e}")
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
                        step_number=2,
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
        if not process_as_xml:  # Only record if we actually validated
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
                step_number=2,
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
                step_number=2,
                success=True,
                duration_seconds=0.0,
                message="XML validation skipped for xmlembed format customer",
                status=StepStatus(
                    xml_validation_pass=True,
                    xml_convert_message="XML validation skipped for xmlembed format customer"
                )
            ))

        # Step 3: EDI Conversion (Skip if customer format is xmlembed)
        if process_as_xml:
            logger.info(f"⏭️ SKIPPING STEP 3 & 4: EDI Conversion and Validation (customer format is xmlembed)")
            edi_success = True
            edi_message = "EDI conversion skipped for xmlembed format customer"
            x12_path = xml_path  # Use XML path directly
            step3_duration = 0.0
            step4_duration = 0.0
            edi_format_valid = True
            
            # Record skipped steps
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="EDI Conversion",
                step_number=3,
                success=True,
                duration_seconds=0.0,
                message="EDI conversion skipped for xmlembed format customer",
                status=StepStatus(
                    edi_convert_pass=True,
                    edi_convert_message="EDI conversion skipped for xmlembed format customer"
                )
            ))
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="EDI Format Validation",
                step_number=4,
                success=True,
                duration_seconds=0.0,
                message="EDI validation skipped for xmlembed format customer",
                status=StepStatus(
                    edi_convert_pass=True,
                    edi_convert_message="EDI validation skipped for xmlembed format customer"
                )
            ))
            
        else:
            # Execute EDI conversion and validation for non-XML formats
            step3_start = time.time()
            logger.info(f"🔄 ===== STEP 3: EDI CONVERSION =====")
            x12_filename = f"{tracking_id}_converted.x12"
            logger.info(f"📄 Converting XML to X12 format")
            logger.info(f"📁 Source XML: {xml_path}")
            logger.info(f"📁 Target X12 filename: {x12_filename}")
            logger.info(f"🔍 Calling convert_xml_to_x12 function...")

            edi_success, edi_message, x12_path = await convert_xml_to_x12(xml_path, x12_filename)

            step3_duration = time.time() - step3_start
            logger.info(f"🔄 EDI conversion completed in {step3_duration:.3f}s")
            logger.info(f"📊 EDI conversion result: {edi_success}")
            logger.info(f"📝 EDI conversion message: {edi_message}")

            if not edi_success:
                logger.error(
                    f"❌ STEP 3 FAILED: EDI conversion failed for tracking ID {tracking_id}")

                edi_errors = []
                xml_content = Path(xml_path).read_text(encoding="utf-8")
                edi_content = Path(x12_path).read_text(
                    encoding="utf-8") if Path(x12_path).exists() else ""

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

                was_fixed, corrected_edi = await auto_fix_edi_with_ai(
                    xml_content=xml_content,
                    edi_content=edi_content,
                    edi_errors=[error_feedback],
                    strict_validation=True
                )

                if was_fixed:
                    ai_fixed_path = Path(x12_path).with_name(
                        Path(x12_path).stem + "_ai_fixed.x12")
                    ai_fixed_path.write_text(corrected_edi, encoding="utf-8")
                    edi_success = True
                    edi_message = "AI correction successful."
                    x12_path = str(ai_fixed_path)
                    logger.info(
                        f"✅ AI successfully corrected EDI fields and fixed reported errors.")

                else:
                    logger.warning(
                        f"⚠️ AI could not correct EDI content. Proceeding with failure handling.")

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
                    step_number=3,
                    success=False,
                    duration_seconds=step3_duration,
                    message=detailed_edi_message,
                    status=StepStatus(
                        edi_convert_pass=False,
                        edi_convert_message=detailed_edi_message
                    ),
                    error_details=[convert_error_feedback_to_detail(err) for err in edi_errors]
                ))

                logger.info(f"💾 Saving failed invoice to database...")

                # Determine blob paths for XML and EDI files
                blob_xml_path = None
                blob_edi_path = None

                if USE_BLOB_STORAGE:
                    if xml_path and isinstance(xml_path, dict):
                        blob_xml_path = xml_path.get('url')
                        logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
                    if x12_path and isinstance(x12_path, dict):
                        blob_edi_path = x12_path.get('url')
                        logger.info(f"🔗 Extracted blob EDI URL: {blob_edi_path}")
                else:
                    logger.info(
                        f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")

                # Determine target format from customer table
                target_format = None
                try:
                    db.rollback()  # Rollback any previous failed transaction
                    customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                    target_format = check_customer_table(customer_id, customer_name, db)
                except Exception as e:
                    logger.warning(f"⚠️ Could not determine target format: {e}")
                    db.rollback()  # Ensure rollback even if there's an error
                
                # Save to failed table
                failed_invoice = FailedModel(
                    tracking_id=tracking_id,
                    user_id=current_user.id,
                    xml_path=str(xml_path) if isinstance(
                        xml_path, str) else xml_path.get('pathname', str(xml_path)),
                    xml_validation_pass=True,
                    xml_convert_message="XML validation passed",
                    edi_path=str(x12_path) if isinstance(
                        x12_path, str) else x12_path.get('pathname', str(x12_path)),
                    edi_convert_pass=False,
                    edi_convert_message=edi_message,
                    processing_steps=json.loads(json.dumps([error.to_dict() if hasattr(error, 'to_dict') else error.dict() for error in all_errors])),
                    blob_xml_path=blob_xml_path,
                    blob_edi_path=blob_edi_path,
                    target_file_format=target_format
                )
                try:
                    db.add(failed_invoice)
                    db.commit()
                    logger.info(
                        f"💾 Successfully saved failed invoice to database for tracking ID {tracking_id}")
                except Exception as db_err:
                    db.rollback()
                    logger.error(f"❌ Failed to save failed invoice to database: {db_err}")

                response.processing_steps = processing_steps

                # Return 200 OK with structured error response (file upload succeeded, processing failed)
                total_duration = time.time() - start_time
                logger.info(
                    f"📤 Returning 200 OK for processing failure (file upload succeeded) for tracking ID {tracking_id}")
                logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
                logger.info(
                    f"🚫 ===== INVOICE PROCESSING FAILED (EDI CONVERSION) =====")
                # Convert UUID to string for JSON serialization
                response_dict = response.dict()
                response_dict['tracking_id'] = str(response_dict['tracking_id'])
                return Response(
                    content=json.dumps(response_dict),
                    status_code=status.HTTP_200_OK,
                    media_type="application/json"
                )

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
                step_number=3,
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

            # Step 4: EDI Format Validation
            step4_start = time.time()
            logger.info(f"🔍 ===== STEP 4: EDI FORMAT VALIDATION =====")
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
    
                # 🧠 Step 4A: Attempt AI-assisted correction for EDI format errors
                logger.info(
                    f"🤖 Attempting AI-assisted correction for EDI format issues...")
                try:
                    blob_xml_path = None
                    blob_edi_path = None
    
                    if USE_BLOB_STORAGE:
                        if xml_path and isinstance(xml_path, dict):
                            blob_xml_path = xml_path.get('url')
                            logger.info(
                                f"🔗 Extracted blob XML URL: {blob_xml_path}")
                        if x12_path and isinstance(x12_path, dict):
                            blob_edi_path = x12_path.get('url')
                            logger.info(
                                f"🔗 Extracted blob EDI URL: {blob_edi_path}")
                    else:
                        logger.info(
                            f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")
                    if blob_xml_path and USE_BLOB_STORAGE and blob_edi_path:
                        xml_content_1 = await read_file_from_storage(None, blob_xml_path, None)
                        xml_content = xml_content_1.decode('utf-8')
                        edi_content_1 = await read_file_from_storage(None, None, blob_edi_path)
                        edi_content = edi_content_1.decode('utf-8')
                    else:
                        xml_content = Path(xml_path).read_text(encoding="utf-8")
                        edi_content = Path(x12_path).read_text(
                            encoding="utf-8") if Path(x12_path).exists() else ""
    
                    # Call the AI fixer
                    was_fixed, corrected_edi = await auto_fix_edi_with_ai(
                        xml_content=xml_content,
                        edi_content=edi_content,
                        edi_errors=edi_format_errors,   # pass structured validation errors
                        strict_validation=True
                    )
    
                    if was_fixed:
    
                        try:
                            # Try saving to Vercel Blob storage first
                            blob_path = str(x12_path)
                            if USE_BLOB_STORAGE:
                                # define your blob path accordingly
                                logger.info(
                                    f"⏳ Trying to save AI fixed EDI to blob: {blob_path}")
                                vercel_blob.put(
                                    blob_path, corrected_edi.encode('utf-8'))
                                logger.info(
                                    f"✅ AI successfully corrected EDI saved to blob: {blob_path}")
                            else:
                                raise Exception(
                                    "Blob storage disabled, skipping blob save")
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Failed to save AI corrected EDI to blob storage: {e}")
                            # Fallback to saving locally
                            try:
                                ai_fixed_filename = f"{Path(x12_path).stem}_ai_fixed.x12"
                                ai_fixed_path = Path(x12_path).with_name(
                                    ai_fixed_filename)
                                ai_fixed_path.write_text(
                                    corrected_edi, encoding="utf-8")
                                logger.info(
                                    f"✅ AI successfully corrected EDI format issues, saved locally to: {ai_fixed_path}")
                            except Exception as e_local:
                                logger.error(
                                    f"❌ Failed to save AI corrected EDI locally as fallback. Error: {e_local}")
    
                        # logger.info(f"✅ AI successfully corrected EDI format issues, saved to: {ai_fixed_path}")
    
                        # Optional: re-run validation
                        try:
                            logger.info(f"🔁 Re-validating AI-corrected EDI...")
                            edi_format_valid_retry, edi_format_message_retry, edi_format_details_retry = await validate_edi_format(ai_fixed_path)
                        except:
                            edi_format_valid_retry, edi_format_message_retry, edi_format_details_retry = True, False, False
                            # traceback.print_exc()
    
                        if edi_format_valid_retry:
                            logger.info(
                                "✅ AI correction successful — EDI passed re-validation.")
                            edi_format_valid = True
                            edi_format_message = "AI correction successful and EDI passed format validation."
                            # x12_path = str(ai_fixed_path)
                        else:
                            logger.warning(
                                "⚠️ AI attempted correction, but EDI still failed format validation.")
                    else:
                        logger.warning(
                            "⚠️ AI could not improve EDI format; proceeding with failure handling.")
                except Exception as e:
                    traceback.print_exc()
                    logger.warning(f"🤖 AI format correction attempt failed: {e}")
    
                # 🧩 Continue with failure logging if still invalid
                if not edi_format_valid:
                    edi_format_message_display = f"EDI conversion completed but format validation failed: {edi_format_message}"

                    add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                        step_name="EDI Format Validation",
                        step_number=4,
                        success=False,
                        duration_seconds=step4_duration,
                        message=edi_format_message,
                        status=StepStatus(
                            edi_convert_pass=False,
                            edi_convert_message=edi_format_message_display
                        ),
                        error_details=[convert_error_feedback_to_detail(err) for err in edi_format_errors]
                    ))

                    logger.info(f"💾 Saving failed invoice to database...")

                    # Determine blob paths for XML and EDI files
                    blob_xml_path = None
                    blob_edi_path = None

                    if USE_BLOB_STORAGE:
                        if xml_path and isinstance(xml_path, dict):
                            blob_xml_path = xml_path.get('url')
                            logger.info(
                                f"🔗 Extracted blob XML URL: {blob_xml_path}")
                        if x12_path and isinstance(x12_path, dict):
                            blob_edi_path = x12_path.get('url')
                            logger.info(
                                f"🔗 Extracted blob EDI URL: {blob_edi_path}")
                    else:
                        logger.info(
                            f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")

                    # Determine target format from customer table
                    target_format = None
                    try:
                        db.rollback()  # Rollback any previous failed transaction
                        customer_id, customer_name = extract_supplier_info_from_string(xml_content)
                        target_format = check_customer_table(customer_id, customer_name, db)
                    except Exception as e:
                        logger.warning(f"⚠️ Could not determine target format: {e}")
                        db.rollback()  # Ensure rollback even if there's an error
                    
                    # Save to failed table
                    failed_invoice = FailedModel(
                        tracking_id=tracking_id,
                        user_id=current_user.id,
                        xml_path=str(xml_path) if isinstance(
                            xml_path, str) else xml_path.get('pathname', str(xml_path)),
                        xml_validation_pass=True,
                        xml_convert_message="XML validation passed",
                        edi_path=str(x12_path) if isinstance(
                            x12_path, str) else x12_path.get('pathname', str(x12_path)),
                        edi_convert_pass=False,
                        edi_convert_message=edi_format_message_display,
                        processing_steps=json.loads(json.dumps([error.to_dict() if hasattr(error, 'to_dict') else error.dict() for error in all_errors])),
                        blob_xml_path=blob_xml_path,
                        blob_edi_path=blob_edi_path,
                        target_file_format=target_format
                    )
                    try:
                        db.add(failed_invoice)
                        db.commit()
                        logger.info(
                            f"💾 Successfully saved failed invoice to database for tracking ID {tracking_id}")
                    except Exception as db_err:
                        db.rollback()
                        logger.error(f"❌ Failed to save failed invoice to database: {db_err}")

                    response.processing_steps = processing_steps                    # Return 200 OK with structured error response (file upload succeeded, processing failed)
                    total_duration = time.time() - start_time
                    logger.info(
                        f"📤 Returning 200 OK for processing failure (file upload succeeded) for tracking ID {tracking_id}")
                    logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
                    logger.info(
                        f"🚫 ===== INVOICE PROCESSING FAILED (EDI FORMAT VALIDATION) =====")
                    # Convert UUID to string for JSON serialization
                    response_dict = response.dict()
                    response_dict['tracking_id'] = str(
                        response_dict['tracking_id'])
                    return Response(
                        content=json.dumps(response_dict),
                        status_code=status.HTTP_200_OK,
                        media_type="application/json"
                    )
    
            # Record successful EDI format validation step
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="EDI Format Validation",
                step_number=4,
                success=True,
                duration_seconds=step4_duration,
                message="EDI format validation passed",
                status=StepStatus(
                    edi_convert_pass=True,
                    edi_convert_message="EDI format validation passed"
                )
            ))

            logger.info(
                f"✅ STEP 4 COMPLETED: EDI format validation successful (took {step4_duration:.3f}s)")        # Step 5: Send to Third Party Endpoint (conditional based on customer format)
        step5_start = time.time()
        third_party_success = False
        third_party_message = "Third party endpoint not called"
        third_party_response = {}
        
        if process_as_xml:
            # Execute Step 5 for xmlembed format customers
            logger.info(f"🌐 ===== STEP 5: THIRD PARTY ENDPOINT (XMLEMBED FORMAT) =====")
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
                step_number=5,
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
            # Skip Step 5 for non-xmlembed format customers (EDI/EDIFACT/x12/xml)
            logger.info(f"⏭️ SKIPPING STEP 5: Third Party Endpoint (non-xmlembed format: {customer_format})")
            step5_duration = 0.0
            
            add_processing_step(tracking_id, processing_steps, ProcessingStepResult(
                step_name="3rd Party Endpoint",
                step_number=5,
                success=True,
                duration_seconds=0.0,
                message=f"Third party endpoint skipped for {customer_format} format customer"
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
                # Step 5 can fail without being critical if it's skipped, but if it actually ran and failed, it's a warning
                if step.step_number == 5 and step.success == False:
                    # For xmlembed customers, step 5 is critical; for others it's skipped (success=True)
                    if "not called" not in step.message and "skipped" not in step.message.lower():
                        logger.warning(f"⚠️ Step {step.step_number} ({step.step_name}) failed but processing continues")
                elif step.step_number in [1, 2, 3, 4]:
                    # These are critical steps
                    workflow_failed = True
                    failed_steps.append(step.step_name)
        
        if workflow_failed:
            logger.warning(f"⚠️ ===== STEP 6: DATABASE SAVE (FAILED) =====")
            logger.warning(f"💾 Saving failed invoice to failed table due to: {', '.join(failed_steps)}")
        else:
            # Also check if third-party API failed for xmlembed customers
            if process_as_xml and not third_party_success:
                logger.warning(f"⚠️ ===== STEP 6: DATABASE SAVE (FAILED) =====")
                logger.warning(f"💾 Saving invoice to failed table due to third-party API failure")
                workflow_failed = True
                failed_steps.append("3rd Party Endpoint")
            else:
                logger.info(f"🎉 ===== STEP 6: DATABASE SAVE (SUCCESS) =====")
                logger.info(f"💾 Saving successful invoice to database...")
        
        logger.info(f"📊 Creating record with tracking ID: {tracking_id}")
        
        # Determine blob paths for XML and EDI files
        blob_xml_path = None
        blob_edi_path = None

        if USE_BLOB_STORAGE:
            if xml_path and isinstance(xml_path, dict):
                blob_xml_path = xml_path.get('url')
                logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
            if x12_path and isinstance(x12_path, dict):
                blob_edi_path = x12_path.get('url')
                logger.info(f"🔗 Extracted blob EDI URL: {blob_edi_path}")
        else:
            logger.info(f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")
        
        # Determine target format from customer table
        try:
            db.rollback()  # Rollback any previous failed transaction
            customer_id, customer_name = extract_supplier_info_from_string(xml_content)
            format_type = check_customer_table(customer_id, customer_name, db)
        except Exception as e:
            logger.warning(f"⚠️ Could not determine target format: {e}")
            db.rollback()  # Ensure rollback even if there's an error
            format_type = 'edifact'
        logging.info(f"The format will be {format_type}")

        # Determine step success flags based on processing_steps
        xml_validation_pass = True
        xml_convert_message = "XML validation passed"
        edi_convert_pass = True
        edi_convert_message = "EDI conversion and format validation completed successfully"
        
        for step in processing_steps:
            if step.step_number == 2 and not step.success:  # XML Validation
                xml_validation_pass = False
                xml_convert_message = step.message
            elif step.step_number == 3 and not step.success:  # EDI Conversion
                edi_convert_pass = False
                edi_convert_message = step.message
            elif step.step_number == 4 and not step.success:  # EDI Format Validation
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
                    step_number=6,
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
                    step_number=6,
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
