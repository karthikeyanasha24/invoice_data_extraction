import vercel_blob
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Union
import uuid
import os
import logging
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.invoice import ZodiacInvoiceSuccessEdi as SuccessModel, ZodiacInvoiceFailedEdi as FailedModel
from ..schemas.invoice import InvoiceProcessingResponse, ErrorDetail, ProcessingStepResult, ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi, InvoiceResponse
from ..api.auth import get_current_user

router = APIRouter(prefix="/invoices", tags=["invoice-processing"])

# Set up logger
logger = logging.getLogger("zodiac-api.invoices")

# Import Vercel Blob for production file storage
try:
    import vercel_blob
    VERCEL_BLOB_AVAILABLE = True
    logger.info("✅ Vercel Blob package imported successfully")
except ImportError:
    VERCEL_BLOB_AVAILABLE = False

if not VERCEL_BLOB_AVAILABLE:
    logger.warning("⚠️ Vercel Blob not available - will use local storage only")

# Environment configuration
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "DEV")
BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")

# Determine if we MUST use blob storage (PROD + token provided)
MUST_USE_BLOB_STORAGE = DEPLOY_ENV == "PROD" and BLOB_READ_WRITE_TOKEN is not None
USE_BLOB_STORAGE = MUST_USE_BLOB_STORAGE and VERCEL_BLOB_AVAILABLE

# Detailed logging for file storage selection
logger.info("=" * 60)
logger.info("🗂️ FILE STORAGE CONFIGURATION")
logger.info("=" * 60)
logger.info(f"🌍 DEPLOY_ENV: {DEPLOY_ENV}")
logger.info(f"🔑 BLOB_READ_WRITE_TOKEN: {'✅ Set' if BLOB_READ_WRITE_TOKEN else '❌ Not set'}")
logger.info(f"📦 VERCEL_BLOB_AVAILABLE: {VERCEL_BLOB_AVAILABLE}")
logger.info(f"🎯 DEPLOY_ENV == 'PROD': {DEPLOY_ENV == 'PROD'}")
logger.info(f"🔑 BLOB_READ_WRITE_TOKEN is not None: {BLOB_READ_WRITE_TOKEN is not None}")
logger.info(f"📦 VERCEL_BLOB_AVAILABLE: {VERCEL_BLOB_AVAILABLE}")
logger.info(f"🚨 MUST_USE_BLOB_STORAGE: {MUST_USE_BLOB_STORAGE}")
logger.info(f"✅ FINAL DECISION - USE_BLOB_STORAGE: {USE_BLOB_STORAGE}")

if MUST_USE_BLOB_STORAGE:
    logger.info("🚨 MANDATORY BLOB STORAGE REQUIRED")
    logger.info("📋 Reason: DEPLOY_ENV=PROD and BLOB_READ_WRITE_TOKEN provided")
    if not VERCEL_BLOB_AVAILABLE:
        logger.error("❌ CRITICAL ERROR: Vercel Blob package not available!")
        logger.error("💥 Cannot proceed - blob storage is mandatory in PROD mode")
        raise RuntimeError("Vercel Blob package not available but required for PROD deployment")
else:
    logger.info("📁 OPTIONAL BLOB STORAGE")
    logger.info("ℹ️ Local storage is acceptable for this environment")

if USE_BLOB_STORAGE:
    logger.info("🚀 STORAGE MODE: VERCEL BLOB STORAGE")
    logger.info("📦 All files will be stored in Vercel Blob storage")
    logger.info("🌐 Files will be accessible via blob URLs")
else:
    logger.info("📁 STORAGE MODE: LOCAL FILE STORAGE")
    logger.info("💾 All files will be stored locally in uploads/ and converted/ directories")
    if DEPLOY_ENV == "PROD":
        logger.warning("⚠️ WARNING: Running in PROD mode but using local storage!")
        if not BLOB_READ_WRITE_TOKEN:
            logger.warning("⚠️ REASON: BLOB_READ_WRITE_TOKEN not provided")
        if not VERCEL_BLOB_AVAILABLE:
            logger.warning("⚠️ REASON: Vercel Blob package not available")
    else:
        logger.info("ℹ️ Development mode - local storage is appropriate")
logger.info("=" * 60)

# Initialize Vercel Blob API if needed
if USE_BLOB_STORAGE:
    try:
        logger.info("🔧 Initializing Vercel Blob API...")
        # Set the token for vercel_blob
        # vercel_blob.set_token(BLOB_READ_WRITE_TOKEN)
        logger.info("✅ Vercel Blob API initialized successfully")
        logger.info(f"🔑 Token length: {len(BLOB_READ_WRITE_TOKEN)} characters")
        logger.info("🚀 Ready to use Vercel Blob storage for file operations")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Vercel Blob API: {e}")
        logger.error(f"🔍 Error type: {type(e).__name__}")
        logger.error(f"📝 Error details: {str(e)}")
        
        if MUST_USE_BLOB_STORAGE:
            logger.error("💥 CRITICAL ERROR: Blob storage is mandatory but initialization failed!")
            logger.error("🚨 Cannot proceed - blob storage is required for PROD deployment")
            raise RuntimeError(f"Failed to initialize mandatory Vercel Blob API: {str(e)}")
        else:
            logger.error("🔄 Falling back to local file storage")
            USE_BLOB_STORAGE = False
else:
    logger.info("📁 Skipping Vercel Blob API initialization (not needed)")

# Final startup confirmation
logger.info("=" * 60)
logger.info("🚀 FILE STORAGE SYSTEM READY")
logger.info("=" * 60)
if USE_BLOB_STORAGE:
    logger.info("✅ VERCEL BLOB STORAGE ACTIVE")
    logger.info("🌐 All file operations will use Vercel Blob storage")
    logger.info("📦 Files will be accessible via blob URLs")
    logger.info("🔧 Vercel Blob module ready for use")
    if MUST_USE_BLOB_STORAGE:
        logger.info("🚨 MANDATORY MODE: Blob storage is required for this deployment")
else:
    logger.info("✅ LOCAL FILE STORAGE ACTIVE")
    logger.info("📁 All file operations will use local file system")
    logger.info("💾 Files will be stored in uploads/ and converted/ directories")
    logger.info("📂 Local directories created and ready")
    if MUST_USE_BLOB_STORAGE:
        logger.error("💥 CRITICAL ERROR: Should be using blob storage but it's not available!")
logger.info("=" * 60)

# Create upload directories (only for local storage)
UPLOAD_DIR = Path("uploads")
EDI_DIR = Path("converted")
if not USE_BLOB_STORAGE:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EDI_DIR.mkdir(parents=True, exist_ok=True)

# File storage helper functions
async def save_file_to_storage(file_content: bytes, filename: str, subdirectory: str = "uploads") -> str:
    """Save file content to appropriate storage (local or Vercel Blob)"""
    logger.info("=" * 50)
    logger.info("💾 FILE SAVE OPERATION")
    logger.info("=" * 50)
    logger.info(f"📁 Filename: {filename}")
    logger.info(f"📂 Subdirectory: {subdirectory}")
    logger.info(f"📊 File size: {len(file_content)} bytes")
    logger.info(f"🎯 Storage mode: {'Vercel Blob' if USE_BLOB_STORAGE else 'Local'}")
    logger.info(f"🚨 Mandatory blob storage: {MUST_USE_BLOB_STORAGE}")
    
    # Validate mandatory blob storage requirement
    if MUST_USE_BLOB_STORAGE and not USE_BLOB_STORAGE:
        logger.error("💥 CRITICAL ERROR: Blob storage is mandatory but not available!")
        logger.error("🚨 Cannot save file - blob storage is required for PROD deployment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Blob storage is mandatory but not available"
        )
    
    if USE_BLOB_STORAGE:
        try:
            # Use Vercel Blob storage
            blob_path = f"{subdirectory}/{filename}"
            logger.info(f"📦 Saving to Vercel Blob: {blob_path}")
            logger.info(f"🔧 Using vercel_blob module: {vercel_blob is not None}")
            
            # Use vercel_blob.put to upload file
            blob_response = vercel_blob.put(blob_path, file_content)
            logger.info(f"✅ File saved to Vercel Blob successfully!")
            logger.info(f"🌐 Blob Response: {blob_response}")
            logger.info(f"📊 Uploaded {len(file_content)} bytes")
            
            # Return the full blob response for URL extraction
            if isinstance(blob_response, dict):
                logger.info(f"✅ File saved successfully!")
                logger.info(f"📁 Saved as: {filename}")
                logger.info(f"📍 Storage path: {blob_response}")
                return blob_response
            else:
                logger.info(f"✅ File saved successfully!")
                logger.info(f"📁 Saved as: {filename}")
                logger.info(f"📍 Storage path: {str(blob_response)}")
                return str(blob_response)
        except Exception as e:
            logger.error(f"❌ Failed to save to Vercel Blob: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")
            
            # Provide more specific error messages
            if "token" in str(e).lower():
                error_detail = "Blob storage authentication failed: Invalid or missing token"
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                error_detail = "Blob storage network error: Unable to connect to cloud storage"
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                error_detail = "Blob storage permission error: Insufficient access rights"
            else:
                error_detail = f"Failed to save file to blob storage: {str(e)}"
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail
            )
    else:
        # Use local file storage
        try:
            target_dir = UPLOAD_DIR if subdirectory == "uploads" else EDI_DIR
            file_path = target_dir / filename
            logger.info(f"📁 Saving to local storage: {file_path}")
            logger.info(f"📂 Target directory: {target_dir}")
            logger.info(f"📄 Full path: {file_path}")
            
            with open(file_path, "wb") as buffer:
                buffer.write(file_content)
            
            logger.info(f"✅ File saved locally successfully!")
            logger.info(f"📊 Written {len(file_content)} bytes")
            logger.info(f"📍 Local path: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"❌ Failed to save locally: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file locally: {str(e)}"
            )

async def read_file_from_storage(file_path: Union[str, dict], blob_xml_path: str = None, blob_edi_path: str = None) -> bytes:
    """Read file content from appropriate storage (local or Vercel Blob)
    
    Args:
        file_path: Path to the file (local path or blob pathname)
        blob_xml_path: Blob URL for XML file from database (if available)
        blob_edi_path: Blob URL for EDI file from database (if available)
    """
    logger.info("=" * 50)
    logger.info("📖 FILE READ OPERATION")
    logger.info("=" * 50)
    logger.info(f"📁 File path: {file_path}")
    logger.info(f"🌐 Blob XML path: {blob_xml_path}")
    logger.info(f"🌐 Blob EDI path: {blob_edi_path}")
    logger.info(f"🎯 Storage mode: {'Vercel Blob' if USE_BLOB_STORAGE else 'Local'}")
    logger.info(f"🚨 Mandatory blob storage: {MUST_USE_BLOB_STORAGE}")
    
    # Validate mandatory blob storage requirement
    if MUST_USE_BLOB_STORAGE and not USE_BLOB_STORAGE:
        logger.error("💥 CRITICAL ERROR: Blob storage is mandatory but not available!")
        logger.error("🚨 Cannot read file - blob storage is required for PROD deployment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Blob storage is mandatory but not available"
        )
    
    if USE_BLOB_STORAGE:
        try:
            # Read from Vercel Blob storage
            logger.info(f"📦 Reading from Vercel Blob")
            logger.info(f"🔧 Using vercel_blob module: {vercel_blob is not None}")
            
            # Determine which blob path to use based on file type
            download_url = None
            if blob_xml_path and ("xml" in str(file_path).lower() or "uploads" in str(file_path)):
                download_url = blob_xml_path
                logger.info(f"🌐 Using blob XML path from database: {download_url}")
            elif blob_edi_path and ("edi" in str(file_path).lower() or "x12" in str(file_path).lower() or "converted" in str(file_path)):
                download_url = blob_edi_path
                logger.info(f"🌐 Using blob EDI path from database: {download_url}")
            else:
                # Fallback to constructing URL from file path
                if isinstance(file_path, dict):
                    blob_path = file_path.get('pathname', file_path.get('url', str(file_path)))
                    logger.info(f"🔍 Extracted blob path: {blob_path}")
                else:
                    blob_path = file_path
                
                if isinstance(file_path, dict) and 'url' in file_path:
                    download_url = file_path['url']
                else:
                    # Construct URL if we only have pathname
                    download_url = f"https://jdwai1wj6716hbub.public.blob.vercel-storage.com/{blob_path}"
                
                logger.info(f"🌐 Constructed blob URL: {download_url}")
            
            # Use requests to download the file from the blob URL
            import requests
            logger.info(f"🌐 Downloading from URL: {download_url}")
            response = requests.get(download_url)
            response.raise_for_status()
            
            file_content = response.content
            logger.info(f"✅ File read from Vercel Blob successfully!")
            logger.info(f"📊 Retrieved {len(file_content)} bytes")
            return file_content
        except Exception as e:
            logger.error(f"❌ Failed to read from Vercel Blob: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")
            
            # Provide more specific error messages
            if "404" in str(e) or "not found" in str(e).lower():
                error_detail = "File not found in blob storage: File may have been deleted or moved"
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                error_detail = "Blob storage network error: Unable to connect to cloud storage"
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                error_detail = "Blob storage permission error: Insufficient access rights to read file"
            else:
                error_detail = f"Failed to read file from blob storage: {str(e)}"
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail
            )
    else:
        # Read from local file storage
        try:
            # Handle blob response in local storage mode
            if isinstance(file_path, dict):
                logger.warning(f"⚠️ Received blob response in local storage mode - this shouldn't happen")
                logger.warning(f"⚠️ Blob response: {file_path}")
                # Extract the pathname for local file access
                local_path = file_path.get('pathname', str(file_path))
                logger.info(f"📁 Using extracted pathname: {local_path}")
            else:
                local_path = file_path
            
            logger.info(f"📁 Reading from local storage: {local_path}")
            logger.info(f"🔍 File exists: {os.path.exists(local_path)}")
            
            with open(local_path, "rb") as buffer:
                file_content = buffer.read()
            
            logger.info(f"✅ File read locally successfully!")
            logger.info(f"📊 Retrieved {len(file_content)} bytes")
            return file_content
        except Exception as e:
            logger.error(f"❌ Failed to read locally: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read file locally: {str(e)}"
            )

def validate_xml(file_path: Union[str, dict], strict_validation: bool = False) -> tuple[bool, Optional[str], list[str]]:
    """Validate XML file structure - core well-formed check + optional enhanced validation with warnings
    
    Args:
        file_path: Path to the XML file to validate
        strict_validation: If True, treats validation issues as errors (default: False, issues are warnings only)
    
    Returns:
        Tuple of (is_valid, message, warnings)
    """
    logger.info(f"🔍 validate_xml: Starting XML validation for {file_path}")
    logger.info(f"📊 validate_xml: Strict validation mode: {strict_validation}")
    warnings = []
    
    try:
        logger.info(f"📄 validate_xml: Reading and parsing XML file...")
        
        # Handle blob storage vs local storage
        if isinstance(file_path, dict):
            # This is a blob response, we need to read the content differently
            logger.info(f"🔍 validate_xml: Detected blob storage response")
            try:
                # Use requests to download the file content
                import requests
                download_url = file_path.get('url', str(file_path))
                logger.info(f"🌐 validate_xml: Downloading from blob URL: {download_url}")
                response = requests.get(download_url)
                response.raise_for_status()
                file_content = response.content
                logger.info(f"✅ validate_xml: Downloaded {len(file_content)} bytes from blob")
                
                if len(file_content) == 0:
                    error_msg = "XML file is empty"
                    logger.error(f"❌ validate_xml: {error_msg}")
                    return False, error_msg, warnings
                
                # Parse XML from content
                root = ET.fromstring(file_content)
                logger.info(f"✅ validate_xml: Core XML parsing successful - file is well-formed")
                
            except Exception as e:
                logger.error(f"❌ validate_xml: Failed to download/parse from blob: {e}")
                return False, f"Failed to download/parse XML from blob storage: {str(e)}", warnings
        else:
            # This is a local file path
            logger.info(f"🔍 validate_xml: Detected local file path")
            import os
            if not os.path.exists(file_path):
                error_msg = f"XML file not found: {file_path}"
                logger.error(f"❌ validate_xml: {error_msg}")
                return False, error_msg, warnings
            
            file_size = os.path.getsize(file_path)
            logger.info(f"📊 validate_xml: File size: {file_size} bytes")
            
            if file_size == 0:
                error_msg = "XML file is empty"
                logger.error(f"❌ validate_xml: {error_msg}")
                return False, error_msg, warnings
            
            # CORE VALIDATION: Check if XML is well-formed (matches old API behavior)
            tree = ET.parse(file_path)
            root = tree.getroot()
            logger.info(f"✅ validate_xml: Core XML parsing successful - file is well-formed")
        
        # ENHANCED VALIDATION: Always run optional checks (warnings only, non-blocking)
        logger.info(f"🔍 validate_xml: Running optional enhanced validation checks...")
        validation_warnings = _perform_enhanced_xml_validation(root, strict_validation)
        warnings.extend(validation_warnings)
        
        # If strict validation is enabled and there are validation warnings, treat them as errors
        if strict_validation and validation_warnings:
            error_msg = f"Strict validation failed: {'; '.join(validation_warnings)}"
            logger.error(f"❌ validate_xml: {error_msg}")
            return False, error_msg, warnings
        
        logger.info(f"✅ validate_xml: XML validation completed with {len(warnings)} warnings")
        return True, "XML validation passed - file is well-formed", warnings
        
    except ET.ParseError as e:
        error_msg = f"XML parsing error: {str(e)}"
        logger.error(f"❌ validate_xml: Parse error - {error_msg}")
        return False, error_msg, []
    except Exception as e:
        error_msg = f"XML validation error: {str(e)}"
        logger.error(f"❌ validate_xml: Unexpected error - {error_msg}")
        return False, error_msg, []

def _perform_enhanced_xml_validation(root, strict_validation: bool = False) -> list[str]:
    """Perform enhanced XML validation and return warnings (non-blocking)
    
    Args:
        root: XML root element
        strict_validation: If True, performs additional strict content validation
    
    Returns:
        List of validation warning messages
    """
    warnings = []
    
    try:
        # Check for UBL namespace elements (optional warning)
        namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }
        
        # Check for common UBL invoice elements
        invoice_id = root.find('.//cbc:ID', namespaces)
        if invoice_id is None:
            warnings.append("⚠️ No UBL Invoice ID (cbc:ID) found - may affect conversion")
        
        issue_date = root.find('.//cbc:IssueDate', namespaces)
        if issue_date is None:
            warnings.append("⚠️ No UBL Issue Date (cbc:IssueDate) found - may affect conversion")
        
        payable_amount = root.find('.//cac:LegalMonetaryTotal/cbc:PayableAmount', namespaces)
        if payable_amount is None:
            warnings.append("⚠️ No UBL Payable Amount found - may affect conversion")
        
        supplier_party = root.find('.//cac:AccountingSupplierParty', namespaces)
        if supplier_party is None:
            warnings.append("⚠️ No UBL Supplier Party found - may affect conversion")
        
        customer_party = root.find('.//cac:AccountingCustomerParty', namespaces)
        if customer_party is None:
            warnings.append("⚠️ No UBL Customer Party found - may affect conversion")
        
        # Check for invoice lines
        invoice_lines = root.findall('.//cac:InvoiceLine', namespaces)
        if not invoice_lines:
            warnings.append("⚠️ No UBL Invoice Lines found - may affect conversion")
        
        # STRICT VALIDATION: Always run strict content validation, return as warnings
        logger.info(f"🔍 Enhanced validation: Running strict content validation...")
        strict_warnings = _perform_strict_content_validation(root, namespaces)
        warnings.extend(strict_warnings)
        logger.info(f"🔍 Enhanced validation: Strict validation completed with {len(strict_warnings)} warnings")
        
        logger.info(f"🔍 Enhanced validation completed with {len(warnings)} warnings")
        
    except Exception as e:
        logger.warning(f"⚠️ Enhanced validation error: {e}")
        warnings.append(f"⚠️ Enhanced validation error: {e}")
    
    return warnings

def _perform_strict_content_validation(root, namespaces) -> list[str]:
    """Perform strict content validation on XML elements (warnings only)
    
    Args:
        root: XML root element
        namespaces: XML namespace mapping
    
    Returns:
        List of strict validation warning messages
    """
    warnings = []
    
    try:
        logger.info(f"🔍 Strict validation: Checking element content and data types...")
        
        # Check Invoice ID content
        invoice_id = root.find('.//cbc:ID', namespaces)
        if invoice_id is not None and invoice_id.text:
            id_value = invoice_id.text.strip()
            if len(id_value) < 1:
                warnings.append("⚠️ Invoice ID is empty")
            elif len(id_value) > 100:
                warnings.append("⚠️ Invoice ID is too long (>100 characters)")
        
        # Check Issue Date content
        issue_date = root.find('.//cbc:IssueDate', namespaces)
        if issue_date is not None and issue_date.text:
            date_value = issue_date.text.strip()
            if len(date_value) < 1:
                warnings.append("⚠️ Issue Date is empty")
            else:
                # Try to parse as date
                try:
                    from datetime import datetime
                    datetime.strptime(date_value, "%Y-%m-%d")
                except ValueError:
                    warnings.append("⚠️ Issue Date format may be invalid (expected YYYY-MM-DD)")
        
        # Check Payable Amount content
        payable_amount = root.find('.//cac:LegalMonetaryTotal/cbc:PayableAmount', namespaces)
        if payable_amount is not None and payable_amount.text:
            amount_value = payable_amount.text.strip()
            if len(amount_value) < 1:
                warnings.append("⚠️ Payable Amount is empty")
            else:
                # Try to parse as decimal
                try:
                    float(amount_value)
                except ValueError:
                    warnings.append("⚠️ Payable Amount format may be invalid (expected decimal number)")
        
        # Check Supplier Name content
        supplier_name = root.find('.//cac:AccountingSupplierParty//cbc:Name', namespaces)
        if supplier_name is not None and supplier_name.text:
            name_value = supplier_name.text.strip()
            if len(name_value) < 1:
                warnings.append("⚠️ Supplier Name is empty")
            elif len(name_value) > 255:
                warnings.append("⚠️ Supplier Name is too long (>255 characters)")
        
        # Check Customer Name content
        customer_name = root.find('.//cac:AccountingCustomerParty//cbc:Name', namespaces)
        if customer_name is not None and customer_name.text:
            name_value = customer_name.text.strip()
            if len(name_value) < 1:
                warnings.append("⚠️ Customer Name is empty")
            elif len(name_value) > 255:
                warnings.append("⚠️ Customer Name is too long (>255 characters)")
        
        # Check Invoice Lines content
        invoice_lines = root.findall('.//cac:InvoiceLine', namespaces)
        for i, line in enumerate(invoice_lines, 1):
            line_id = line.find('cbc:ID', namespaces)
            if line_id is not None and line_id.text:
                line_id_value = line_id.text.strip()
                if len(line_id_value) < 1:
                    warnings.append(f"⚠️ Invoice Line {i} ID is empty")
            
            quantity = line.find('cbc:InvoicedQuantity', namespaces)
            if quantity is not None and quantity.text:
                qty_value = quantity.text.strip()
                try:
                    float(qty_value)
                except ValueError:
                    warnings.append(f"⚠️ Invoice Line {i} quantity format may be invalid")
            
            price = line.find('.//cac:Price/cbc:PriceAmount', namespaces)
            if price is not None and price.text:
                price_value = price.text.strip()
                try:
                    float(price_value)
                except ValueError:
                    warnings.append(f"⚠️ Invoice Line {i} price format may be invalid")
        
        logger.info(f"🔍 Strict validation: Completed with {len(warnings)} warnings")
        
    except Exception as e:
        logger.warning(f"⚠️ Strict validation error: {e}")
        warnings.append(f"⚠️ Strict validation error: {e}")
    
    return warnings

async def validate_edi_format(edi_path: Union[str, dict]) -> tuple[bool, Optional[str], Optional[dict]]:
    """Validate EDI format fields for correct values, format, and length"""
    logger.info(f"🔍 validate_edi_format: Starting EDI format validation for {edi_path}")
    
    try:
        logger.info(f"📄 validate_edi_format: Reading EDI file...")
        edi_content_bytes = await read_file_from_storage(edi_path, None, None)
        edi_content = edi_content_bytes.decode('utf-8')
        
        logger.info(f"✅ validate_edi_format: EDI file read successfully ({len(edi_content)} characters)")
        
        # Split into segments
        segments = [seg.strip() for seg in edi_content.split('~') if seg.strip()]
        logger.info(f"📊 validate_edi_format: Found {len(segments)} segments")
        
        validation_results = {
            'isa_segment': {'valid': False, 'errors': []},
            'gs_segment': {'valid': False, 'errors': []},
            'st_segment': {'valid': False, 'errors': []},
            'big_segment': {'valid': False, 'errors': []},
            'n1_segments': {'valid': False, 'errors': []},
            'it1_segment': {'valid': False, 'errors': []},
            'tds_segment': {'valid': False, 'errors': []},
            'trailer_segments': {'valid': False, 'errors': []}
        }
        
        logger.info(f"🔍 validate_edi_format: Validating each segment...")
        
        # Validate ISA Segment (Interchange Control Header)
        isa_segment = next((seg for seg in segments if seg.startswith('ISA')), None)
        if isa_segment:
            logger.info(f"   - ISA Segment: {isa_segment}")
            isa_fields = isa_segment.split('*')
            if len(isa_fields) >= 16:
                # Check ISA field lengths and formats
                if len(isa_fields[1]) != 2:  # Authorization Information Qualifier
                    validation_results['isa_segment']['errors'].append("ISA02: Authorization Info Qualifier must be 2 characters")
                if len(isa_fields[2]) != 10:  # Authorization Information
                    validation_results['isa_segment']['errors'].append("ISA03: Authorization Info must be 10 characters")
                if len(isa_fields[3]) != 2:  # Security Information Qualifier
                    validation_results['isa_segment']['errors'].append("ISA04: Security Info Qualifier must be 2 characters")
                if len(isa_fields[4]) != 10:  # Security Information
                    validation_results['isa_segment']['errors'].append("ISA05: Security Info must be 10 characters")
                if len(isa_fields[5]) != 2:  # Interchange ID Qualifier
                    validation_results['isa_segment']['errors'].append("ISA06: Interchange ID Qualifier must be 2 characters")
                if len(isa_fields[6]) != 15:  # Interchange Sender ID
                    validation_results['isa_segment']['errors'].append("ISA07: Sender ID must be 15 characters")
                if len(isa_fields[7]) != 2:  # Interchange ID Qualifier
                    validation_results['isa_segment']['errors'].append("ISA08: Interchange ID Qualifier must be 2 characters")
                if len(isa_fields[8]) != 15:  # Interchange Receiver ID
                    validation_results['isa_segment']['errors'].append("ISA09: Receiver ID must be 15 characters")
                
                validation_results['isa_segment']['valid'] = len(validation_results['isa_segment']['errors']) == 0
                logger.info(f"     ISA Validation: {'✅ PASS' if validation_results['isa_segment']['valid'] else '❌ FAIL'}")
                if validation_results['isa_segment']['errors']:
                    for error in validation_results['isa_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['isa_segment']['errors'].append("ISA segment must have at least 16 fields")
                logger.error(f"     ISA Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['isa_segment']['errors'].append("ISA segment not found")
            logger.error(f"     ISA Validation: ❌ FAIL - Segment not found")
        
        # Validate GS Segment (Functional Group Header)
        gs_segment = next((seg for seg in segments if seg.startswith('GS')), None)
        if gs_segment:
            logger.info(f"   - GS Segment: {gs_segment}")
            gs_fields = gs_segment.split('*')
            if len(gs_fields) >= 8:
                # Check GS field formats
                if gs_fields[1] != 'IN':  # Functional Identifier Code
                    validation_results['gs_segment']['errors'].append("GS02: Functional Identifier must be 'IN' for Invoice")
                if len(gs_fields[2]) != 2:  # Application Sender's Code
                    validation_results['gs_segment']['errors'].append("GS03: Application Sender Code must be 2 characters")
                if len(gs_fields[3]) != 2:  # Application Receiver's Code
                    validation_results['gs_segment']['errors'].append("GS04: Application Receiver Code must be 2 characters")
                
                validation_results['gs_segment']['valid'] = len(validation_results['gs_segment']['errors']) == 0
                logger.info(f"     GS Validation: {'✅ PASS' if validation_results['gs_segment']['valid'] else '❌ FAIL'}")
                if validation_results['gs_segment']['errors']:
                    for error in validation_results['gs_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['gs_segment']['errors'].append("GS segment must have at least 8 fields")
                logger.error(f"     GS Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['gs_segment']['errors'].append("GS segment not found")
            logger.error(f"     GS Validation: ❌ FAIL - Segment not found")
        
        # Validate ST Segment (Transaction Set Header)
        st_segment = next((seg for seg in segments if seg.startswith('ST')), None)
        if st_segment:
            logger.info(f"   - ST Segment: {st_segment}")
            st_fields = st_segment.split('*')
            if len(st_fields) >= 2:
                if st_fields[1] != '810':  # Transaction Set Identifier Code
                    validation_results['st_segment']['errors'].append("ST02: Transaction Set Identifier must be '810' for Invoice")
                
                validation_results['st_segment']['valid'] = len(validation_results['st_segment']['errors']) == 0
                logger.info(f"     ST Validation: {'✅ PASS' if validation_results['st_segment']['valid'] else '❌ FAIL'}")
                if validation_results['st_segment']['errors']:
                    for error in validation_results['st_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['st_segment']['errors'].append("ST segment must have at least 2 fields")
                logger.error(f"     ST Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['st_segment']['errors'].append("ST segment not found")
            logger.error(f"     ST Validation: ❌ FAIL - Segment not found")
        
        # Validate BIG Segment (Beginning Segment for Invoice)
        big_segment = next((seg for seg in segments if seg.startswith('BIG')), None)
        if big_segment:
            logger.info(f"   - BIG Segment: {big_segment}")
            big_fields = big_segment.split('*')
            if len(big_fields) >= 3:
                # Check date format (should be YYYYMMDD)
                if big_fields[1] and len(big_fields[1]) == 8:
                    try:
                        # Validate date format
                        year = int(big_fields[1][:4])
                        month = int(big_fields[1][4:6])
                        day = int(big_fields[1][6:8])
                        if not (1 <= month <= 12 and 1 <= day <= 31):
                            validation_results['big_segment']['errors'].append("BIG02: Invalid date format")
                    except ValueError:
                        validation_results['big_segment']['errors'].append("BIG02: Date must be numeric YYYYMMDD format")
                else:
                    validation_results['big_segment']['errors'].append("BIG02: Invoice date must be 8 characters (YYYYMMDD)")
                
                # Check invoice number
                if not big_fields[2] or len(big_fields[2]) == 0:
                    validation_results['big_segment']['errors'].append("BIG03: Invoice number cannot be empty")
                
                validation_results['big_segment']['valid'] = len(validation_results['big_segment']['errors']) == 0
                logger.info(f"     BIG Validation: {'✅ PASS' if validation_results['big_segment']['valid'] else '❌ FAIL'}")
                if validation_results['big_segment']['errors']:
                    for error in validation_results['big_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['big_segment']['errors'].append("BIG segment must have at least 3 fields")
                logger.error(f"     BIG Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['big_segment']['errors'].append("BIG segment not found")
            logger.error(f"     BIG Validation: ❌ FAIL - Segment not found")
        
        # Validate N1 Segments (Name/Address Information)
        n1_segments = [seg for seg in segments if seg.startswith('N1')]
        if len(n1_segments) >= 2:
            logger.info(f"   - N1 Segments: Found {len(n1_segments)} segments")
            for i, n1_seg in enumerate(n1_segments):
                logger.info(f"     N1-{i+1}: {n1_seg}")
                n1_fields = n1_seg.split('*')
                if len(n1_fields) >= 2:
                    if n1_fields[1] not in ['BY', 'SE']:  # Entity Identifier Code
                        validation_results['n1_segments']['errors'].append(f"N1-{i+1}: Entity Identifier must be 'BY' or 'SE'")
                else:
                    validation_results['n1_segments']['errors'].append(f"N1-{i+1}: Segment must have at least 2 fields")
            
            validation_results['n1_segments']['valid'] = len(validation_results['n1_segments']['errors']) == 0
            logger.info(f"     N1 Validation: {'✅ PASS' if validation_results['n1_segments']['valid'] else '❌ FAIL'}")
            if validation_results['n1_segments']['errors']:
                for error in validation_results['n1_segments']['errors']:
                    logger.error(f"       {error}")
        else:
            validation_results['n1_segments']['errors'].append("Must have at least 2 N1 segments (Buyer and Seller)")
            logger.error(f"     N1 Validation: ❌ FAIL - Insufficient N1 segments")
        
        # Validate IT1 Segment (Baseline Item Data)
        it1_segment = next((seg for seg in segments if seg.startswith('IT1')), None)
        if it1_segment:
            logger.info(f"   - IT1 Segment: {it1_segment}")
            it1_fields = it1_segment.split('*')
            if len(it1_fields) >= 6:
                # Check quantity and amount fields
                try:
                    quantity = float(it1_fields[2]) if it1_fields[2] else 0
                    if quantity <= 0:
                        validation_results['it1_segment']['errors'].append("IT103: Quantity must be greater than 0")
                except ValueError:
                    validation_results['it1_segment']['errors'].append("IT103: Quantity must be numeric")
                
                validation_results['it1_segment']['valid'] = len(validation_results['it1_segment']['errors']) == 0
                logger.info(f"     IT1 Validation: {'✅ PASS' if validation_results['it1_segment']['valid'] else '❌ FAIL'}")
                if validation_results['it1_segment']['errors']:
                    for error in validation_results['it1_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['it1_segment']['errors'].append("IT1 segment must have at least 6 fields")
                logger.error(f"     IT1 Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['it1_segment']['errors'].append("IT1 segment not found")
            logger.error(f"     IT1 Validation: ❌ FAIL - Segment not found")
        
        # Validate TDS Segment (Total Monetary Value Summary)
        tds_segment = next((seg for seg in segments if seg.startswith('TDS')), None)
        if tds_segment:
            logger.info(f"   - TDS Segment: {tds_segment}")
            tds_fields = tds_segment.split('*')
            if len(tds_fields) >= 2:
                try:
                    amount = float(tds_fields[1]) if tds_fields[1] else 0
                    if amount <= 0:
                        validation_results['tds_segment']['errors'].append("TDS02: Total amount must be greater than 0")
                except ValueError:
                    validation_results['tds_segment']['errors'].append("TDS02: Total amount must be numeric")
                
                validation_results['tds_segment']['valid'] = len(validation_results['tds_segment']['errors']) == 0
                logger.info(f"     TDS Validation: {'✅ PASS' if validation_results['tds_segment']['valid'] else '❌ FAIL'}")
                if validation_results['tds_segment']['errors']:
                    for error in validation_results['tds_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['tds_segment']['errors'].append("TDS segment must have at least 2 fields")
                logger.error(f"     TDS Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['tds_segment']['errors'].append("TDS segment not found")
            logger.error(f"     TDS Validation: ❌ FAIL - Segment not found")
        
        # Validate Trailer Segments (CTT, SE, GE, IEA)
        ctt_segment = next((seg for seg in segments if seg.startswith('CTT')), None)
        se_segment = next((seg for seg in segments if seg.startswith('SE')), None)
        ge_segment = next((seg for seg in segments if seg.startswith('GE')), None)
        iea_segment = next((seg for seg in segments if seg.startswith('IEA')), None)
        
        trailer_segments = [ctt_segment, se_segment, ge_segment, iea_segment]
        trailer_names = ['CTT', 'SE', 'GE', 'IEA']
        
        for i, (seg, name) in enumerate(zip(trailer_segments, trailer_names)):
            if seg:
                logger.info(f"   - {name} Segment: {seg}")
            else:
                validation_results['trailer_segments']['errors'].append(f"{name} segment not found")
                logger.error(f"     {name} Validation: ❌ FAIL - Segment not found")
        
        validation_results['trailer_segments']['valid'] = len(validation_results['trailer_segments']['errors']) == 0
        logger.info(f"     Trailer Validation: {'✅ PASS' if validation_results['trailer_segments']['valid'] else '❌ FAIL'}")
        
        # Summary of validation results
        all_valid = all(result['valid'] for result in validation_results.values())
        total_errors = sum(len(result['errors']) for result in validation_results.values())
        
        logger.info(f"📊 validate_edi_format: EDI Format Validation Results Summary:")
        logger.info(f"   - Total Segments Found: {len(segments)}")
        logger.info(f"   - ISA Segment: {'✅ VALID' if validation_results['isa_segment']['valid'] else '❌ INVALID'}")
        logger.info(f"   - GS Segment: {'✅ VALID' if validation_results['gs_segment']['valid'] else '❌ INVALID'}")
        logger.info(f"   - ST Segment: {'✅ VALID' if validation_results['st_segment']['valid'] else '❌ INVALID'}")
        logger.info(f"   - BIG Segment: {'✅ VALID' if validation_results['big_segment']['valid'] else '❌ INVALID'}")
        logger.info(f"   - N1 Segments: {'✅ VALID' if validation_results['n1_segments']['valid'] else '❌ INVALID'}")
        logger.info(f"   - IT1 Segment: {'✅ VALID' if validation_results['it1_segment']['valid'] else '❌ INVALID'}")
        logger.info(f"   - TDS Segment: {'✅ VALID' if validation_results['tds_segment']['valid'] else '❌ INVALID'}")
        logger.info(f"   - Trailer Segments: {'✅ VALID' if validation_results['trailer_segments']['valid'] else '❌ INVALID'}")
        logger.info(f"   - Total Validation Errors: {total_errors}")
        logger.info(f"   - Overall Validation: {'✅ PASS' if all_valid else '❌ FAIL'}")
        
        if all_valid:
            logger.info(f"✅ validate_edi_format: EDI format validation passed")
            return True, "EDI format validation passed", None
        else:
            error_msg = f"EDI format validation failed with {total_errors} errors"
            logger.error(f"❌ validate_edi_format: {error_msg}")
            return False, error_msg, validation_results
        
    except FileNotFoundError:
        error_msg = f"EDI file not found: {edi_path}"
        logger.error(f"❌ validate_edi_format: {error_msg}")
        return False, error_msg, None
    except Exception as e:
        error_msg = f"EDI format validation error: {str(e)}"
        logger.error(f"❌ validate_edi_format: Unexpected error - {error_msg}")
        return False, error_msg, None

# Helper classes and functions from old API (exact same implementation)
class _X12ControlNumbers:
    def __init__(self, root, ns):
        invoice_id = root.find(".//cbc:ID", ns)
        self.interchange_control = (invoice_id.text[:9] if invoice_id else "000000000").zfill(9)
        order_ref = root.find(".//cac:OrderReference/cbc:ID", ns)
        self.group_control = (order_ref.text[:6] if order_ref else "000000").zfill(6)
        originator_ref = root.find(".//cac:OriginatorDocumentReference/cbc:ID", ns)
        self.transaction_control = (originator_ref.text[:4] if originator_ref else "0000").zfill(4)

def _format_number(number_str, decimal_places=2):
    try:
        number = float(number_str)
        return str(int(round(number * (10 ** decimal_places))))
    except (ValueError, TypeError):
        return "0"

def _extract_party_info(root, party_path, ns):
    party = root.find(party_path, ns)
    if party is not None:
        name_elem = party.find(".//cbc:Name", ns)
        endpoint_elem = party.find(".//cbc:EndpointID", ns)
        qualifier = "ZZ"
        endpoint_id = "UNKNOWN"
        if endpoint_elem is not None:
            scheme_id = endpoint_elem.get('schemeID')
            qualifier_map = {
                '0002': '01',
                '0007': '14',
                '0009': '33',
                '0037': '94',
                '0060': 'N1',
                '0088': '12',
                '0160': '98',
                '9930': '93',
                '0096': '24',
            }
            if scheme_id:
                qualifier = qualifier_map.get(scheme_id, 'ZZ')
            endpoint_id = endpoint_elem.text.strip() if endpoint_elem.text else "UNKNOWN"
        endpoint_id = endpoint_id.ljust(15)[:15]
        return {
            'name': name_elem.text.strip() if name_elem is not None and name_elem.text else "UNKNOWN",
            'id': endpoint_id,
            'qualifier': qualifier
        }
    return {'name': "UNKNOWN", 'id': "UNKNOWN".ljust(15), 'qualifier': "ZZ"}

def _extract_postal_address(root, party_path, ns):
    address = root.find(f"{party_path}/cac:PostalAddress", ns)
    if address is not None:
        street_elem = address.find("cbc:StreetName", ns)
        city_elem = address.find("cbc:CityName", ns)
        postal_elem = address.find("cbc:PostalZone", ns)
        country_elem = address.find("cac:Country/cbc:IdentificationCode", ns)
        return {
            "street": street_elem.text.strip() if street_elem is not None and street_elem.text else "",
            "city": city_elem.text.strip() if city_elem is not None and city_elem.text else "",
            "postal": postal_elem.text.strip() if postal_elem is not None and postal_elem.text else "",
            "country": country_elem.text.strip() if country_elem is not None and country_elem.text else ""
        }
    return {"street": "", "city": "", "postal": "", "country": ""}

def _map_address(address):
    city = address.get("city", "")
    postal = address.get("postal", "")
    country = address.get("country", "")
    state = "XX"
    if city.lower() == "north sydney":
        state = "NS"
    elif city.lower() == "port lincoln":
        state = "SA"
    if country.upper() == "AU":
        country = "AUS"
    return state, postal, country

def _create_ISA_segment(supplier, customer, control_numbers, current_time):
    # Build each data element with fixed width:
    isa01 = "00"  # 2 characters
    isa02 = " " * 10  # 10 characters
    isa03 = "00"  # 2 characters
    isa04 = " " * 10  # 10 characters
    isa05 = supplier['qualifier'][:2].ljust(2)  # 2 characters
    isa06 = supplier['id'][:15].ljust(15)  # 15 characters
    isa07 = customer['qualifier'][:2].ljust(2)  # 2 characters
    isa08 = customer['id'][:15].ljust(15)  # 15 characters
    isa09 = current_time.strftime("%y%m%d")  # 6 characters
    isa10 = current_time.strftime("%H%M")  # 4 characters
    isa11 = "U"  # 1 character
    isa12 = "00401"  # 5 characters
    isa13 = control_numbers.interchange_control.zfill(9)  # 9 characters
    isa14 = "0"  # 1 character
    isa15 = "P"  # 1 character
    isa16 = ">"  # 1 character; must be exactly one character

    # Build ISA segment using "*" delimiters without additional padding afterwards.
    # Do NOT pad the complete segment to 106 characters as that can overwrite ISA16.
    isa_elements = [
        "ISA", isa01, isa02, isa03, isa04,
        isa05, isa06, isa07, isa08, isa09,
        isa10, isa11, isa12, isa13, isa14, isa15, isa16
    ]
    return "*".join(isa_elements) + "~"

async def convert_xml_to_x12(xml_path: Union[str, dict], x12_filename: str) -> tuple[bool, Optional[str], Optional[str]]:
    """Convert XML to X12 format using exact same logic as old API's convert_xml_to_x12"""
    logger.info(f"🔄 convert_xml_to_x12: Starting X12 conversion (matching old API logic)")
    logger.info(f"📁 Source XML: {xml_path}")
    logger.info(f"📁 Target X12 filename: {x12_filename}")
    
    try:
        logger.info(f"📄 convert_xml_to_x12: Reading XML content...")
        
        # Read XML content from storage
        xml_content = await read_file_from_storage(xml_path, None, None)
        
        logger.info(f"✅ convert_xml_to_x12: XML content read ({len(xml_content)} bytes)")
        
        # Use exact same conversion logic as old API
        x12_content = _convert_xml_to_x12_content(xml_content)
        
        if not x12_content:
            logger.error(f"❌ convert_xml_to_x12: No X12 content generated")
            return False, "No X12 content generated", None
        
        logger.info(f"📝 convert_xml_to_x12: X12 content generated ({len(x12_content)} characters)")
        
        # Save X12 content to storage
        x12_path = await save_file_to_storage(x12_content.encode('utf-8'), x12_filename, "converted")
        
        logger.info(f"✅ convert_xml_to_x12: X12 file saved successfully")
        logger.info(f"📊 convert_xml_to_x12: Conversion completed successfully")
        
        return True, "X12 conversion completed successfully", x12_path
        
    except Exception as e:
        error_msg = f"X12 conversion error: {str(e)}"
        logger.error(f"❌ convert_xml_to_x12: {error_msg}")
        return False, error_msg, None

def _convert_xml_to_x12_content(xml_content: bytes) -> Optional[str]:
    """Convert XML content to X12 format using exact same logic as old API"""
    logger.info(f"🔧 _convert_xml_to_x12_content: Starting X12 conversion")
    
    try:
        # Parse XML using same approach as old API
        root = ET.fromstring(xml_content)
        
        # Define namespaces exactly as in old API
        ns = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }
        
        logger.info(f"✅ _convert_xml_to_x12_content: XML parsing successful")
        
        # Initialize control numbers (exact same logic as old API)
        control_numbers = _X12ControlNumbers(root, ns)
        
        # Extract party information (exact same logic as old API)
        supplier = _extract_party_info(root, ".//cac:AccountingSupplierParty/cac:Party", ns)
        customer = _extract_party_info(root, ".//cac:AccountingCustomerParty/cac:Party", ns)
        
        # Set defaults if unknown (exact same logic as old API)
        if supplier["id"].strip() == "UNKNOWN":
            supplier["id"] = "SENDERID".ljust(15)
        if customer["id"].strip() == "UNKNOWN":
            customer["id"] = "RECEIVERID".ljust(15)
        
        logger.info(f"📊 _convert_xml_to_x12_content: Supplier: {supplier['name']} ({supplier['id'].strip()})")
        logger.info(f"📊 _convert_xml_to_x12_content: Customer: {customer['name']} ({customer['id'].strip()})")
        
        # Build X12 segments (exact same logic as old API)
        x12_segments = []
        current_time = datetime.now()
        
        # Create ISA segment (exact same logic as old API)
        isa_segment = _create_ISA_segment(supplier, customer, control_numbers, current_time)
        x12_segments.append(isa_segment)
        logger.info(f"✅ _convert_xml_to_x12_content: ISA segment created")
        
        # Create GS segment (exact same logic as old API)
        gs = (
            f"GS*IN*{supplier['id'].strip()}*{customer['id'].strip()}*"
            f"{current_time.strftime('%Y%m%d')}*{current_time.strftime('%H%M')}*"
            f"{control_numbers.group_control}*X*004010~"
        )
        x12_segments.append(gs)
        logger.info(f"✅ _convert_xml_to_x12_content: GS segment created")
        
        # Create ST segment (exact same logic as old API)
        st = f"ST*810*{control_numbers.transaction_control}~"
        x12_segments.append(st)
        logger.info(f"✅ _convert_xml_to_x12_content: ST segment created")
        
        # Extract invoice data (exact same logic as old API)
        invoice_date_elem = root.find(".//cbc:IssueDate", ns)
        invoice_number_elem = root.find(".//cbc:ID", ns)
        purchase_order_elem = root.find(".//cac:OrderReference/cbc:ID", ns)
        
        invoice_date = invoice_date_elem.text.strip() if invoice_date_elem is not None and invoice_date_elem.text else ""
        logger.info(f"📊 _convert_xml_to_x12_content: Invoice date: {invoice_date}")
        
        # Format date (exact same logic as old API)
        if invoice_date == "0000-00-00":
            formatted_date = ""
        else:
            formatted_date = datetime.strptime(invoice_date, "%Y-%m-%d").strftime("%Y%m%d") if invoice_date else ""
        
        # Format purchase order (exact same logic as old API)
        purchase_order = ""
        if purchase_order_elem is not None and purchase_order_elem.text:
            po = purchase_order_elem.text.strip()
            purchase_order = po[:8] if len(po) >= 8 else po.zfill(8)
        
        # Create BIG segment (exact same logic as old API)
        big = (
            f"BIG*{formatted_date}*"
            f"{invoice_number_elem.text.strip() if invoice_number_elem is not None and invoice_number_elem.text else ''}~"
        )
        x12_segments.append(big)
        logger.info(f"✅ _convert_xml_to_x12_content: BIG segment created")
        
        # Add optional segments (exact same logic as old API)
        
        # Note segment
        note_elem = root.find(".//cbc:Note", ns)
        if note_elem is not None and note_elem.text and note_elem.text.strip() not in [".", ""]:
            x12_segments.append(f"NTE*GEN*{note_elem.text.strip()}~")
            logger.info(f"✅ _convert_xml_to_x12_content: NTE segment added")
        
        # Currency segment
        currency_elem = root.find(".//cbc:DocumentCurrencyCode", ns)
        if currency_elem is not None and currency_elem.text:
            x12_segments.append(f"CUR*BY*{currency_elem.text.strip()}~")
            logger.info(f"✅ _convert_xml_to_x12_content: CUR segment added")
        
        # Contract reference segment
        contract_ref = root.find(".//cac:ContractDocumentReference/cbc:ID", ns)
        if contract_ref is not None and contract_ref.text:
            x12_segments.append(f"REF*CT*{contract_ref.text.strip()}~")
            logger.info(f"✅ _convert_xml_to_x12_content: REF segment added")
        
        # Contact segment
        contact = root.find(".//cac:AccountingSupplierParty//cac:Contact", ns)
        if contact is not None:
            contact_name = contact.find("cbc:Name", ns)
            contact_phone = contact.find("cbc:Telephone", ns)
            if contact_name is not None and contact_phone is not None and contact_name.text and contact_phone.text:
                x12_segments.append(f"PER*IC*{contact_name.text.strip()}*TE*{contact_phone.text.strip()}~")
                logger.info(f"✅ _convert_xml_to_x12_content: PER segment added")
        
        # Supplier N1 segment (exact same logic as old API)
        x12_segments.append(f"N1*SU*{supplier['name']}*{supplier['qualifier']}*{supplier['id'].strip()}~")
        logger.info(f"✅ _convert_xml_to_x12_content: Supplier N1 segment added")
        
        # Supplier address segments (exact same logic as old API)
        supplier_address = _extract_postal_address(root, ".//cac:AccountingSupplierParty/cac:Party", ns)
        if supplier_address["street"]:
            x12_segments.append(f"N3*{supplier_address['street']}~")
        state, postal, country = _map_address(supplier_address)
        if supplier_address["city"] or postal or country:
            x12_segments.append(f"N4*{supplier_address['city']}*{state}*{postal}*{country}~")
        logger.info(f"✅ _convert_xml_to_x12_content: Supplier address segments added")
        
        # Customer N1 segment (exact same logic as old API)
        x12_segments.append(f"N1*BY*{customer['name']}*{customer['qualifier']}*{customer['id'].strip()}~")
        logger.info(f"✅ _convert_xml_to_x12_content: Customer N1 segment added")
        
        # Customer address segments (exact same logic as old API)
        customer_address = _extract_postal_address(root, ".//cac:AccountingCustomerParty/cac:Party", ns)
        if customer_address["street"]:
            x12_segments.append(f"N3*{customer_address['street']}~")
        state, postal, country = _map_address(customer_address)
        if customer_address["city"] or postal or country:
            x12_segments.append(f"N4*{customer_address['city']}*{state}*{postal}*{country}~")
        logger.info(f"✅ _convert_xml_to_x12_content: Customer address segments added")
        
        # Payment terms segment (exact same logic as old API)
        payment_terms_elem = root.find(".//cac:PaymentTerms/cbc:Note", ns)
        if payment_terms_elem is not None and payment_terms_elem.text:
            term = payment_terms_elem.text.strip()
            if term.lower().startswith("pay immediately"):
                term = "1"
            x12_segments.append(f"ITD*01*{term}~")
            logger.info(f"✅ _convert_xml_to_x12_content: ITD segment added")
        
        # Due date segment (exact same logic as old API)
        due_date_elem = root.find(".//cbc:DueDate", ns)
        if due_date_elem is not None and due_date_elem.text:
            due_date = datetime.strptime(due_date_elem.text.strip(), "%Y-%m-%d").strftime("%Y%m%d")
            x12_segments.append(f"DTM*011*{due_date}~")
            logger.info(f"✅ _convert_xml_to_x12_content: DTM segment added")
        
        # Delivery segment (exact same logic as old API)
        delivery = root.find(".//cac:Delivery", ns)
        if delivery is not None:
            x12_segments.append("FOB*CC~")
            logger.info(f"✅ _convert_xml_to_x12_content: FOB segment added")
        
        # Invoice lines (exact same logic as old API)
        invoice_lines = root.findall(".//cac:InvoiceLine", ns)
        logger.info(f"📊 _convert_xml_to_x12_content: Processing {len(invoice_lines)} invoice lines")
        
        for idx, line in enumerate(invoice_lines, 1):
            quantity_elem = line.find("cbc:InvoicedQuantity", ns)
            price_elem = line.find(".//cac:Price/cbc:PriceAmount", ns)
            product_elem = line.find(".//cac:Item/cac:SellersItemIdentification/cbc:ID", ns)
            
            quantity_val = quantity_elem.text.strip() if quantity_elem is not None and quantity_elem.text else "0"
            price_val = _format_number(price_elem.text) if price_elem is not None and price_elem.text else "0"
            product_code = product_elem.text.strip() if product_elem is not None and product_elem.text else ""
            
            x12_segments.append(f"IT1*{idx}*{quantity_val}*EA*{price_val}*CP*VP*{product_code}~")
        
        logger.info(f"✅ _convert_xml_to_x12_content: {len(invoice_lines)} IT1 segments added")
        
        # Total amount segment (exact same logic as old API)
        total_amount_elem = root.find(".//cac:LegalMonetaryTotal/cbc:PayableAmount", ns)
        if total_amount_elem is not None and total_amount_elem.text:
            formatted_total = _format_number(total_amount_elem.text)
            x12_segments.append(f"TDS*{formatted_total}~")
            logger.info(f"✅ _convert_xml_to_x12_content: TDS segment added")
        
        # Transaction totals segment (exact same logic as old API)
        hash_total = sum(int(line.find("cbc:ID", ns).text.lstrip("0") or "0") for line in invoice_lines)
        x12_segments.append(f"CTT*{len(invoice_lines)}*{hash_total}~")
        logger.info(f"✅ _convert_xml_to_x12_content: CTT segment added")
        
        # Transaction set trailer (exact same logic as old API)
        st_index = next(i for i, seg in enumerate(x12_segments) if seg.startswith("ST"))
        transaction_segment_count = len(x12_segments) - st_index + 1
        x12_segments.append(f"SE*{transaction_segment_count}*{control_numbers.transaction_control}~")
        logger.info(f"✅ _convert_xml_to_x12_content: SE segment added")
        
        # Functional group trailer (exact same logic as old API)
        x12_segments.append(f"GE*1*{control_numbers.group_control}~")
        logger.info(f"✅ _convert_xml_to_x12_content: GE segment added")
        
        # Interchange control trailer (exact same logic as old API)
        x12_segments.append(f"IEA*1*{control_numbers.interchange_control}~")
        logger.info(f"✅ _convert_xml_to_x12_content: IEA segment added")
        
        # Join segments with newlines (exact same logic as old API)
        result = "\n".join(x12_segments)
        
        logger.info(f"✅ _convert_xml_to_x12_content: X12 conversion completed successfully")
        logger.info(f"📊 _convert_xml_to_x12_content: Generated {len(x12_segments)} segments")
        logger.info(f"📊 _convert_xml_to_x12_content: Total content length: {len(result)} characters")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ _convert_xml_to_x12_content: Conversion error: {str(e)}")
        return None

@router.post("/process", response_model=InvoiceProcessingResponse)
async def process_invoice(
    file: UploadFile = File(...),
    strict_validation: bool = False,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process uploaded invoice file with XML validation and EDI conversion
    
    Args:
        file: Uploaded XML file
        strict_validation: If True, performs strict XML content validation (default: False for old API compatibility)
        current_user: Authenticated user
        db: Database session
    """
    
    import time
    start_time = time.time()
    
    logger.info(f"🚀 ===== INVOICE PROCESSING STARTED =====")
    logger.info(f"👤 User ID: {current_user.id}")
    logger.info(f"📁 File details: filename={file.filename}, content_type={file.content_type}, size={file.size}")
    logger.info(f"🔍 Strict validation mode: {strict_validation}")
    logger.info(f"⏰ Start time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
    
    # Generate tracking ID
    tracking_id = uuid.uuid4()
    logger.info(f"🆔 Generated tracking ID: {tracking_id}")
    logger.info(f"📋 Processing steps: 1) File Upload → 2) XML Validation → 3) EDI Conversion → 4) EDI Format Validation → 5) Database Save")
    
    # Initialize response with enhanced error tracking
    response = InvoiceProcessingResponse(
        invoice_operation_success=False,
        file_upload_pass=False,
        xml_validation_pass=False,
        edi_convert_pass=False,
        tracking_id=tracking_id,
        processing_steps=[],
        error_summary={},
        file_content_preview=None,
        suggested_actions=[],
        warnings=[]
    )
    
    # Track processing steps
    processing_steps = []
    all_errors = []
    
    try:
        # Step 1: File Upload
        step1_start = time.time()
        logger.info(f"📤 ===== STEP 1: FILE UPLOAD =====")
        logger.info(f"📁 Processing file: {file.filename}")
        logger.info(f"📊 File size: {file.size} bytes")
        logger.info(f"📋 Content type: {file.content_type}")
        
        # Validate content type to match old API behavior
        if file.content_type != "text/xml":
            error_msg = f"Only XML files are accepted. Received: {file.content_type}"
            logger.error(f"❌ STEP 1 FAILED: {error_msg}")
            response.file_upload_message = error_msg
            logger.info(f"📤 Returning 400 Bad Request for tracking ID {tracking_id}")
            # Convert UUID to string for JSON serialization
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=response_dict)
        
        logger.info(f"🔍 Checking filename for tracking ID {tracking_id}")
        
        if not file.filename:
            logger.error(f"❌ STEP 1 FAILED: No filename provided for tracking ID {tracking_id}")
            response.file_upload_message = "No filename provided"
            logger.info(f"📤 Returning 400 Bad Request for tracking ID {tracking_id}")
            # Convert UUID to string for JSON serialization
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=response_dict)
        
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
        response.file_upload_pass = True
        response.file_upload_message = "File uploaded successfully"
        logger.info(f"✅ STEP 1 COMPLETED: File upload successful (took {step1_duration:.3f}s)")
        
        # Record successful step
        processing_steps.append(ProcessingStepResult(
            step_name="File Upload",
            step_number=1,
            success=True,
            duration_seconds=step1_duration,
            message="File uploaded successfully"
        ))
        
        # Add file content preview for error context
        try:
            file_content_bytes = await read_file_from_storage(xml_path, None, None)
            file_content = file_content_bytes.decode('utf-8')
            response.file_content_preview = file_content[:500] + "..." if len(file_content) > 500 else file_content
        except Exception as e:
            logger.warning(f"⚠️ Could not read file content for preview: {e}")
            response.file_content_preview = "Unable to read file content"
        
        # Step 2: XML Validation
        step2_start = time.time()
        logger.info(f"🔍 ===== STEP 2: XML VALIDATION =====")
        logger.info(f"📄 Validating XML file: {xml_path}")
        logger.info(f"🔍 Calling validate_xml function...")
        
        xml_valid, xml_message, xml_warnings = validate_xml(xml_path, strict_validation)
        response.xml_validation_pass = xml_valid
        response.xml_convert_message = xml_message
        response.warnings.extend(xml_warnings)  # Add warnings to response
        
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
            logger.error(f"❌ STEP 2 FAILED: XML validation failed for tracking ID {tracking_id}")
            logger.error(f"💥 Failure reason: {xml_message}")
            
            # Check if this is a strict validation failure or parsing error
            xml_errors = []
            if "Strict validation failed" in xml_message:
                # This is a strict validation failure - include detailed warnings as errors
                if xml_warnings:
                    for warning in xml_warnings:
                        xml_errors.append(ErrorDetail(
                            step="XML_VALIDATION",
                            error_type="STRICT_VALIDATION_ERROR",
                            error_message=warning,
                            suggestions=[
                                "Review XML content for missing or invalid elements",
                                "Check data formats and field lengths",
                                "Ensure all required UBL elements are present",
                                "Use AI assistant for detailed correction guidance"
                            ]
                        ))
                else:
                    xml_errors.append(ErrorDetail(
                        step="XML_VALIDATION",
                        error_type="STRICT_VALIDATION_ERROR",
                        error_message=xml_message,
                        suggestions=[
                            "Review XML content for missing or invalid elements",
                            "Check data formats and field lengths",
                            "Ensure all required UBL elements are present",
                            "Use AI assistant for detailed correction guidance"
                        ]
                    ))
            else:
                # This is a parsing error - file is not well-formed XML
                xml_errors.append(ErrorDetail(
                    step="XML_VALIDATION",
                    error_type="PARSING_ERROR",
                    error_message=xml_message,
                    suggestions=[
                        "Check XML file structure and syntax",
                        "Ensure XML is well-formed",
                        "Verify file encoding and format"
                    ]
                ))
            
            all_errors.extend(xml_errors)
            
            # Record failed step
            processing_steps.append(ProcessingStepResult(
                step_name="XML Validation",
                step_number=2,
                success=False,
                duration_seconds=step2_duration,
                error_details=xml_errors,
                message=xml_message
            ))
            
            logger.info(f"💾 Saving failed invoice to database...")
            
            # Determine blob paths for XML file
            blob_xml_path = None
            if USE_BLOB_STORAGE and isinstance(xml_path, dict):
                blob_xml_path = xml_path.get('url')
                logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
            else:
                logger.info(f"📁 Using local XML path: {xml_path}")
            
            # Save to failed table
            failed_invoice = FailedModel(
                tracking_id=tracking_id,
                user_id=current_user.id,
                xml_path=str(xml_path) if isinstance(xml_path, str) else xml_path.get('pathname', str(xml_path)),
                xml_validation_pass=False,
                xml_convert_message=xml_message,
                edi_convert_pass=False,
                edi_convert_message="Skipped due to XML validation failure",
                processing_steps_error=[error.dict() for error in all_errors],
                blob_xml_path=blob_xml_path,
                blob_edi_path=None
            )
            db.add(failed_invoice)
            db.commit()
            logger.info(f"💾 Successfully saved failed invoice to database for tracking ID {tracking_id}")
            
            # Prepare comprehensive error response
            response.processing_steps = processing_steps
            response.error_summary = {
                "total_errors": len(all_errors),
                "failed_step": "XML_VALIDATION",
                "error_categories": list(set([error.error_type for error in all_errors])),
                "suggested_actions": [
                    "Review XML file structure and required elements",
                    "Check data formats for InvoiceDate and TotalAmount",
                    "Ensure XML is well-formed and valid",
                    "Use AI assistant for detailed correction guidance"
                ]
            }
            response.suggested_actions = response.error_summary["suggested_actions"]
            
            # Return 200 OK with structured error response (file upload succeeded, processing failed)
            total_duration = time.time() - start_time
            logger.info(f"📤 Returning 200 OK for processing failure (file upload succeeded) for tracking ID {tracking_id}")
            logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
            logger.info(f"🚫 ===== INVOICE PROCESSING FAILED (XML VALIDATION) =====")
            # Convert UUID to string for JSON serialization
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            return Response(
                content=json.dumps(response_dict),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
        
        # Record successful XML validation step with warning status
        if xml_warnings:
            message = f"XML validation passed with {len(xml_warnings)} warnings"
            logger.info(f"⚠️ STEP 2 COMPLETED: XML validation passed with warnings (took {step2_duration:.3f}s)")
        else:
            message = "XML validation passed"
            logger.info(f"✅ STEP 2 COMPLETED: XML validation passed cleanly (took {step2_duration:.3f}s)")
        
        processing_steps.append(ProcessingStepResult(
            step_name="XML Validation",
            step_number=2,
            success=True,
            duration_seconds=step2_duration,
            message=message,
            error_details=[ErrorDetail(
                step="XML_VALIDATION",
                error_type="WARNING",
                error_message=warning,
                suggestions=["Review XML content for potential improvements"]
            ) for warning in xml_warnings] if xml_warnings else []
        ))
        
        # Update response message to reflect warning status
        if xml_warnings:
            response.xml_convert_message = f"XML validation passed with {len(xml_warnings)} warnings"
        else:
            response.xml_convert_message = "XML validation passed"
        
        # Step 3: EDI Conversion
        step3_start = time.time()
        logger.info(f"🔄 ===== STEP 3: EDI CONVERSION =====")
        x12_filename = f"{tracking_id}_converted.x12"
        logger.info(f"📄 Converting XML to X12 format")
        logger.info(f"📁 Source XML: {xml_path}")
        logger.info(f"📁 Target X12 filename: {x12_filename}")
        logger.info(f"🔍 Calling convert_xml_to_x12 function...")
        
        edi_success, edi_message, x12_path = await convert_xml_to_x12(xml_path, x12_filename)
        response.edi_convert_pass = edi_success
        response.edi_convert_message = edi_message
        
        step3_duration = time.time() - step3_start
        logger.info(f"🔄 EDI conversion completed in {step3_duration:.3f}s")
        logger.info(f"📊 EDI conversion result: {edi_success}")
        logger.info(f"📝 EDI conversion message: {edi_message}")
        
        if not edi_success:
            logger.error(f"❌ STEP 3 FAILED: EDI conversion failed for tracking ID {tracking_id}")
            logger.error(f"💥 Failure reason: {edi_message}")
            
            # Parse EDI conversion errors
            edi_errors = []
            if "XML parsing error" in edi_message:
                edi_errors.append(ErrorDetail(
                    step="EDI_CONVERSION",
                    error_type="PARSING_ERROR",
                    error_message=edi_message,
                    suggestions=[
                        "Check XML file is well-formed",
                        "Verify XML structure is valid",
                        "Ensure XML can be parsed correctly"
                    ]
                ))
            elif "conversion error" in edi_message:
                edi_errors.append(ErrorDetail(
                    step="EDI_CONVERSION",
                    error_type="CONVERSION_ERROR",
                    error_message=edi_message,
                    suggestions=[
                        "Check XML data completeness",
                        "Verify all required fields for EDI conversion",
                        "Review XML to EDI mapping logic"
                    ]
                ))
            else:
                edi_errors.append(ErrorDetail(
                    step="EDI_CONVERSION",
                    error_type="CONVERSION_ERROR",
                    error_message=edi_message,
                    suggestions=[
                        "Review XML file content",
                        "Check EDI conversion process",
                        "Verify data integrity"
                    ]
                ))
            
            all_errors.extend(edi_errors)
            
            # Record failed step
            processing_steps.append(ProcessingStepResult(
                step_name="EDI Conversion",
                step_number=3,
                success=False,
                duration_seconds=step3_duration,
                error_details=edi_errors,
                message=edi_message
            ))
            
            logger.info(f"💾 Saving failed invoice to database...")
            
            # Determine blob paths for XML and EDI files
            blob_xml_path = None
            blob_edi_path = None
            
            if USE_BLOB_STORAGE:
                if isinstance(xml_path, dict):
                    blob_xml_path = xml_path.get('url')
                    logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
                if isinstance(x12_path, dict):
                    blob_edi_path = x12_path.get('url')
                    logger.info(f"🔗 Extracted blob EDI URL: {blob_edi_path}")
            else:
                logger.info(f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")
            
            # Save to failed table
            failed_invoice = FailedModel(
                tracking_id=tracking_id,
                user_id=current_user.id,
                xml_path=str(xml_path) if isinstance(xml_path, str) else xml_path.get('pathname', str(xml_path)),
                xml_validation_pass=True,
                xml_convert_message="XML validation passed",
                edi_path=str(x12_path) if isinstance(x12_path, str) else x12_path.get('pathname', str(x12_path)),
                edi_convert_pass=False,
                edi_convert_message=edi_message,
                processing_steps_error=[error.dict() for error in all_errors],
                blob_xml_path=blob_xml_path,
                blob_edi_path=blob_edi_path
            )
            db.add(failed_invoice)
            db.commit()
            logger.info(f"💾 Successfully saved failed invoice to database for tracking ID {tracking_id}")
            
            # Prepare comprehensive error response
            response.processing_steps = processing_steps
            response.error_summary = {
                "total_errors": len(all_errors),
                "failed_step": "EDI_CONVERSION",
                "error_categories": list(set([error.error_type for error in all_errors])),
                "suggested_actions": [
                    "Review XML file structure and content",
                    "Check EDI conversion requirements",
                    "Verify data completeness for EDI format",
                    "Use AI assistant for conversion guidance"
                ]
            }
            response.suggested_actions = response.error_summary["suggested_actions"]
            
            # Return 200 OK with structured error response (file upload succeeded, processing failed)
            total_duration = time.time() - start_time
            logger.info(f"📤 Returning 200 OK for processing failure (file upload succeeded) for tracking ID {tracking_id}")
            logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
            logger.info(f"🚫 ===== INVOICE PROCESSING FAILED (EDI CONVERSION) =====")
            # Convert UUID to string for JSON serialization
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            return Response(
                content=json.dumps(response_dict),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
        
        # Record successful EDI conversion step
        processing_steps.append(ProcessingStepResult(
            step_name="EDI Conversion",
            step_number=3,
            success=True,
            duration_seconds=step3_duration,
            message="EDI conversion completed successfully"
        ))
        
        logger.info(f"✅ STEP 3 COMPLETED: EDI conversion successful (took {step3_duration:.3f}s)")
        
        # Step 4: EDI Format Validation
        step4_start = time.time()
        logger.info(f"🔍 ===== STEP 4: EDI FORMAT VALIDATION =====")
        logger.info(f"📄 Validating EDI format fields for correct values, format, and length")
        logger.info(f"🔍 Calling validate_edi_format function...")
        
        edi_format_valid, edi_format_message, edi_format_details = await validate_edi_format(x12_path)
        
        step4_duration = time.time() - step4_start
        logger.info(f"🔍 EDI format validation completed in {step4_duration:.3f}s")
        logger.info(f"📊 EDI format validation result: {edi_format_valid}")
        logger.info(f"📝 EDI format validation message: {edi_format_message}")
        
        if not edi_format_valid:
            logger.error(f"❌ STEP 4 FAILED: EDI format validation failed for tracking ID {tracking_id}")
            logger.error(f"💥 Failure reason: {edi_format_message}")
            
            # Parse EDI format validation errors using detailed information
            edi_format_errors = []
            if edi_format_details:
                # Use detailed error information from validation_results
                for segment_name, segment_data in edi_format_details.items():
                    if not segment_data['valid'] and segment_data['errors']:
                        for error in segment_data['errors']:
                            edi_format_errors.append(ErrorDetail(
                                step="EDI_FORMAT_VALIDATION",
                                error_type="FORMAT_ERROR",
                                error_message=f"{segment_name.upper()}: {error}",
                                suggestions=[
                                    "Check EDI segment structure and field lengths",
                                    "Verify required segments are present",
                                    "Ensure field formats match X12 standards",
                                    "Review EDI field validation rules"
                                ]
                            ))
            else:
                # Fallback to generic error handling
                edi_format_errors.append(ErrorDetail(
                    step="EDI_FORMAT_VALIDATION",
                    error_type="FORMAT_ERROR",
                    error_message=edi_format_message,
                    suggestions=[
                        "Check EDI segment structure and field lengths",
                        "Verify required segments are present",
                        "Ensure field formats match X12 standards",
                        "Review EDI field validation rules"
                    ]
                ))
            
            all_errors.extend(edi_format_errors)
            
            # Update response to reflect EDI conversion failure due to format validation
            response.edi_convert_pass = False
            response.edi_convert_message = f"EDI conversion completed but format validation failed: {edi_format_message}"
            
            # Record failed step
            processing_steps.append(ProcessingStepResult(
                step_name="EDI Format Validation",
                step_number=4,
                success=False,
                duration_seconds=step4_duration,
                error_details=edi_format_errors,
                message=edi_format_message
            ))
            
            logger.info(f"💾 Saving failed invoice to database...")
            
            # Determine blob paths for XML and EDI files
            blob_xml_path = None
            blob_edi_path = None
            
            if USE_BLOB_STORAGE:
                if isinstance(xml_path, dict):
                    blob_xml_path = xml_path.get('url')
                    logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
                if isinstance(x12_path, dict):
                    blob_edi_path = x12_path.get('url')
                    logger.info(f"🔗 Extracted blob EDI URL: {blob_edi_path}")
            else:
                logger.info(f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")
            
            # Save to failed table
            failed_invoice = FailedModel(
                tracking_id=tracking_id,
                user_id=current_user.id,
                xml_path=str(xml_path) if isinstance(xml_path, str) else xml_path.get('pathname', str(xml_path)),
                xml_validation_pass=True,
                xml_convert_message="XML validation passed",
                edi_path=str(x12_path) if isinstance(x12_path, str) else x12_path.get('pathname', str(x12_path)),
                edi_convert_pass=False,  # EDI format validation failed
                edi_convert_message=f"EDI conversion completed but format validation failed: {edi_format_message}",
                processing_steps_error=[error.dict() for error in all_errors],
                blob_xml_path=blob_xml_path,
                blob_edi_path=blob_edi_path
            )
            db.add(failed_invoice)
            db.commit()
            logger.info(f"💾 Successfully saved failed invoice to database for tracking ID {tracking_id}")
            
            # Prepare comprehensive error response
            response.processing_steps = processing_steps
            response.error_summary = {
                "total_errors": len(all_errors),
                "failed_step": "EDI_FORMAT_VALIDATION",
                "error_categories": list(set([error.error_type for error in all_errors])),
                "suggested_actions": [
                    "Review EDI format and field validation requirements",
                    "Check X12 compliance standards",
                    "Verify EDI segment structure and field lengths",
                    "Use AI assistant for EDI format guidance"
                ]
            }
            response.suggested_actions = response.error_summary["suggested_actions"]
            
            # Return 200 OK with structured error response (file upload succeeded, processing failed)
            total_duration = time.time() - start_time
            logger.info(f"📤 Returning 200 OK for processing failure (file upload succeeded) for tracking ID {tracking_id}")
            logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
            logger.info(f"🚫 ===== INVOICE PROCESSING FAILED (EDI FORMAT VALIDATION) =====")
            # Convert UUID to string for JSON serialization
            response_dict = response.dict()
            response_dict['tracking_id'] = str(response_dict['tracking_id'])
            return Response(
                content=json.dumps(response_dict),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
        
        # Record successful EDI format validation step
        processing_steps.append(ProcessingStepResult(
            step_name="EDI Format Validation",
            step_number=4,
            success=True,
            duration_seconds=step4_duration,
            message="EDI format validation passed"
        ))
        
        logger.info(f"✅ STEP 4 COMPLETED: EDI format validation successful (took {step4_duration:.3f}s)")
        
        # Step 5: Success - Save to success table
        step5_start = time.time()
        logger.info(f"🎉 ===== STEP 5: DATABASE SAVE (SUCCESS) =====")
        logger.info(f"💾 Saving successful invoice to database...")
        logger.info(f"📊 Creating success record with tracking ID: {tracking_id}")
        
        # Determine blob paths for XML and EDI files
        blob_xml_path = None
        blob_edi_path = None
        
        if USE_BLOB_STORAGE:
            if isinstance(xml_path, dict):
                blob_xml_path = xml_path.get('url')
                logger.info(f"🔗 Extracted blob XML URL: {blob_xml_path}")
            if isinstance(x12_path, dict):
                blob_edi_path = x12_path.get('url')
                logger.info(f"🔗 Extracted blob EDI URL: {blob_edi_path}")
        else:
            logger.info(f"📁 Using local paths - XML: {xml_path}, EDI: {x12_path}")
        
        success_invoice = SuccessModel(
            tracking_id=tracking_id,
            user_id=current_user.id,
            xml_path=str(xml_path) if isinstance(xml_path, str) else xml_path.get('pathname', str(xml_path)),
            xml_validation_pass=True,
            xml_convert_message=response.xml_convert_message,  # Use the updated message with warning info
            edi_path=str(x12_path) if isinstance(x12_path, str) else x12_path.get('pathname', str(x12_path)),
            edi_convert_pass=True,
            edi_convert_message="EDI conversion and format validation completed successfully",
            blob_xml_path=blob_xml_path,
            blob_edi_path=blob_edi_path
        )
        db.add(success_invoice)
        db.commit()
        
        step5_duration = time.time() - step5_start
        logger.info(f"💾 Successfully saved invoice to database (took {step5_duration:.3f}s)")
        logger.info(f"✅ STEP 5 COMPLETED: Database save successful")
        
        response.invoice_operation_success = True
        response.processing_steps = processing_steps
        total_duration = time.time() - start_time
        
        # Log warnings if any were found during processing
        if xml_warnings:
            logger.info(f"⚠️ Processing completed with {len(xml_warnings)} XML validation warnings")
            logger.info(f"📋 Warnings summary:")
            for warning in xml_warnings:
                logger.warning(f"   - {warning}")
        else:
            logger.info(f"✅ Processing completed cleanly with no warnings")
        
        logger.info(f"🎉 ===== INVOICE PROCESSING COMPLETED SUCCESSFULLY =====")
        logger.info(f"🆔 Tracking ID: {tracking_id}")
        logger.info(f"⏱️ Total processing time: {total_duration:.3f}s")
        logger.info(f"📊 Step timings: Upload={step1_duration:.3f}s, XML={step2_duration:.3f}s, EDI={step3_duration:.3f}s, EDI_Format={step4_duration:.3f}s, DB={step5_duration:.3f}s")
        logger.info(f"📁 Files created: XML={xml_filename}, X12={x12_filename}")
        
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
        logger.error(f"⏱️ Processing time before failure: {total_duration:.3f}s")
        logger.error(f"💥 HTTP Exception raised for tracking ID {tracking_id}")
        raise
    except Exception as e:
        total_duration = time.time() - start_time
        logger.error(f"💥 ===== UNEXPECTED ERROR =====")
        logger.error(f"🆔 Tracking ID: {tracking_id}")
        logger.error(f"⏱️ Processing time before failure: {total_duration:.3f}s")
        logger.error(f"💥 Unexpected error during invoice processing for tracking ID {tracking_id}: {str(e)}")
        logger.error(f"🔍 Error type: {type(e).__name__}")
        logger.error(f"📝 Error details: {str(e)}")
        
        # Provide more informative error message for client
        error_message = f"Processing failed: {str(e)}"
        if "blob storage" in str(e).lower():
            error_message = "File storage error: Unable to save or retrieve file from cloud storage"
        elif "xml" in str(e).lower():
            error_message = "XML processing error: Unable to parse or validate XML file"
        elif "edi" in str(e).lower():
            error_message = "EDI conversion error: Unable to convert XML to EDI format"
        elif "database" in str(e).lower():
            error_message = "Database error: Unable to save processing results"
        
        response.file_upload_message = error_message
        response.invoice_operation_success = False
        
        # Add error to processing steps
        processing_steps.append({
            "step": "Error Handling",
            "status": "failed",
            "message": error_message,
            "timestamp": time.time(),
            "duration": total_duration
        })
        
        # Convert UUID to string for JSON serialization
        response_dict = response.dict()
        response_dict['tracking_id'] = str(response_dict['tracking_id'])
        response_dict['processing_steps'] = processing_steps
        
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=response_dict)

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
            failed_count = db.execute(text("SELECT COUNT(*) FROM zodiac_invoice_failed_edi")).scalar()
            logger.info(f"📊 Total failed invoices in DB: {failed_count}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to count failed invoices: {e}")
            failed_count = 0
        
        # Test success invoices table with raw SQL
        try:
            success_count = db.execute(text("SELECT COUNT(*) FROM zodiac_invoice_success_edi")).scalar()
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

@router.get("/success", response_model=list[ZodiacInvoiceSuccessEdi])
def get_successful_invoices(
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get successfully processed invoices for current user"""
    try:
        # Use raw SQL to avoid schema issues
        query = """
        SELECT id, tracking_id, user_id, uploaded_at, xml_path, 
               xml_validation_pass, xml_convert_message, edi_path, 
               edi_convert_pass, edi_convert_message, processing_steps_error,
               blob_xml_path, blob_edi_path
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
                xml_path=row.xml_path,
                xml_validation_pass=row.xml_validation_pass,
                xml_convert_message=row.xml_convert_message,
                edi_path=row.edi_path,
                edi_convert_pass=row.edi_convert_pass,
                edi_convert_message=row.edi_convert_message,
                processing_steps_error=row.processing_steps_error,
                blob_xml_path=row.blob_xml_path,
                blob_edi_path=row.blob_edi_path
            )
            invoices.append(invoice)
        
        return invoices
    except Exception as e:
        logger.error(f"❌ Error getting successful invoices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting successful invoices: {str(e)}")

@router.get("/failed", response_model=list[ZodiacInvoiceFailedEdi])
async def get_failed_invoices(
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get failed invoices for current user"""
    try:
        # Use raw SQL to avoid schema issues
        query = """
        SELECT id, tracking_id, user_id, uploaded_at, xml_path, 
               xml_validation_pass, xml_convert_message, edi_path, 
               edi_convert_pass, edi_convert_message, processing_steps_error,
               blob_xml_path, blob_edi_path
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
            processing_steps_error = row.processing_steps_error
            if isinstance(processing_steps_error, str):
                try:
                    import json
                    processing_steps_error = json.loads(processing_steps_error)
                except (json.JSONDecodeError, TypeError):
                    processing_steps_error = None
            
            # Read file contents
            xml_content = ""
            edi_content = ""
            
            try:
                # Use blob path if available, otherwise fall back to local path
                if row.blob_xml_path and USE_BLOB_STORAGE:
                    logger.info(f"🔍 Reading XML file from blob: {row.blob_xml_path}")
                    xml_content_bytes = await read_file_from_storage(None, row.blob_xml_path, None)
                    xml_content = xml_content_bytes.decode('utf-8')
                    logger.info(f"✅ XML content read from blob successfully, length: {len(xml_content)}")
                else:
                    # Try to resolve the local path - it might be relative or have issues
                    xml_file_path = row.xml_path
                    if xml_file_path:
                        # Convert to absolute path if it's relative
                        if not os.path.isabs(xml_file_path):
                            xml_file_path = os.path.abspath(xml_file_path)
                        
                        logger.info(f"🔍 Reading XML file from local storage: {xml_file_path}")
                        logger.info(f"🔍 File exists: {os.path.exists(xml_file_path)}")
                        
                        if os.path.exists(xml_file_path):
                            xml_content_bytes = await read_file_from_storage(xml_file_path, None, None)
                            xml_content = xml_content_bytes.decode('utf-8')
                            logger.info(f"✅ XML content read from local storage successfully, length: {len(xml_content)}")
                        else:
                            logger.warning(f"⚠️ XML file not found: {xml_file_path}")
                    else:
                        logger.warning(f"⚠️ XML path is None")
            except Exception as e:
                logger.error(f"❌ Could not read XML file: {e}")
            
            try:
                # Use blob path if available, otherwise fall back to local path
                if row.blob_edi_path and USE_BLOB_STORAGE:
                    logger.info(f"🔍 Reading EDI file from blob: {row.blob_edi_path}")
                    edi_content_bytes = await read_file_from_storage(None, None, row.blob_edi_path)
                    edi_content = edi_content_bytes.decode('utf-8')
                    logger.info(f"✅ EDI content read from blob successfully, length: {len(edi_content)}")
                elif row.edi_path and (os.path.exists(row.edi_path) or USE_BLOB_STORAGE):
                    logger.info(f"🔍 Reading EDI file from local storage: {row.edi_path}")
                    edi_content_bytes = await read_file_from_storage(row.edi_path, None, None)
                    edi_content = edi_content_bytes.decode('utf-8')
                    logger.info(f"✅ EDI content read from local storage successfully, length: {len(edi_content)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not read EDI file: {e}")
            
            invoice = FailedModel(
                id=row.id,
                tracking_id=row.tracking_id,
                user_id=row.user_id,
                uploaded_at=row.uploaded_at,
                xml_path=row.xml_path,
                xml_validation_pass=row.xml_validation_pass,
                xml_convert_message=row.xml_convert_message,
                edi_path=row.edi_path,
                edi_convert_pass=row.edi_convert_pass,
                edi_convert_message=row.edi_convert_message,
                processing_steps_error=processing_steps_error,
                blob_xml_path=row.blob_xml_path,
                blob_edi_path=row.blob_edi_path
            )
            
            # Add file content as additional attributes (not part of the model)
            invoice.xml_content = xml_content
            invoice.edi_content = edi_content
            
            invoices.append(invoice)
        
        return invoices
    except Exception as e:
        logger.error(f"❌ Error getting failed invoices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting failed invoices: {str(e)}")

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
               edi_convert_pass, edi_convert_message, processing_steps_error,
               blob_xml_path, blob_edi_path
        FROM zodiac_invoice_failed_edi 
        WHERE tracking_id = :tracking_id AND user_id = :user_id
        """
        result = db.execute(text(query), {
            "tracking_id": tracking_id,
            "user_id": current_user.id
        }).fetchone()
        
        if not result:
            logger.warning(f"⚠️ Failed invoice not found for tracking ID: {tracking_id}")
            logger.warning(f"⚠️ User ID: {current_user.id}")
            logger.warning(f"⚠️ Tracking ID type: {type(tracking_id)}")
            logger.warning(f"⚠️ User ID type: {type(current_user.id)}")
            raise HTTPException(status_code=404, detail="Failed invoice not found")
        
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
            processing_steps_error=result.processing_steps_error,
            blob_xml_path=result.blob_xml_path,
            blob_edi_path=result.blob_edi_path
        )
        
        logger.info(f"✅ Found failed invoice for tracking ID: {tracking_id}")
        logger.info(f"🔍 Processing steps error from DB (raw): {result.processing_steps_error}")
        logger.info(f"🔍 Processing steps error type: {type(result.processing_steps_error)}")
        logger.info(f"🔍 Processing steps error is None: {result.processing_steps_error is None}")
        
        # Parse the JSON data if it's stored as a string
        processing_steps_error = result.processing_steps_error
        if isinstance(processing_steps_error, str):
            try:
                import json
                processing_steps_error = json.loads(processing_steps_error)
                logger.info(f"🔍 Parsed JSON processing steps error: {processing_steps_error}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"❌ Failed to parse processing_steps_error JSON: {e}")
                processing_steps_error = None
        
        # Read file contents
        xml_content = ""
        edi_content = ""
        
        try:
            # Use blob path if available, otherwise fall back to local path
            if invoice.blob_xml_path and USE_BLOB_STORAGE:
                logger.info(f"🔍 Reading XML file from blob: {invoice.blob_xml_path}")
                xml_content_bytes = await read_file_from_storage(None, invoice.blob_xml_path, None)
                xml_content = xml_content_bytes.decode('utf-8')
                logger.info(f"✅ XML content read from blob successfully, length: {len(xml_content)}")
            else:
                # Try to resolve the local path - it might be relative or have issues
                xml_file_path = invoice.xml_path
                if xml_file_path:
                    # Convert to absolute path if it's relative
                    if not os.path.isabs(xml_file_path):
                        xml_file_path = os.path.abspath(xml_file_path)
                    
                    logger.info(f"🔍 Reading XML file from local storage: {xml_file_path}")
                    logger.info(f"🔍 File exists: {os.path.exists(xml_file_path)}")
                    
                    if os.path.exists(xml_file_path):
                        with open(xml_file_path, 'r', encoding='utf-8') as f:
                            xml_content = f.read()
                        logger.info(f"✅ XML content read from local storage successfully, length: {len(xml_content)}")
                    else:
                        logger.warning(f"⚠️ XML file not found: {xml_file_path}")
                else:
                    logger.warning(f"⚠️ XML path is None")
        except Exception as e:
            logger.error(f"❌ Could not read XML file: {e}")
        
        try:
            # Use blob path if available, otherwise fall back to local path
            if invoice.blob_edi_path and USE_BLOB_STORAGE:
                logger.info(f"🔍 Reading EDI file from blob: {invoice.blob_edi_path}")
                edi_content_bytes = await read_file_from_storage(None, None, invoice.blob_edi_path)
                edi_content = edi_content_bytes.decode('utf-8')
                logger.info(f"✅ EDI content read from blob successfully, length: {len(edi_content)}")
            elif invoice.edi_path and (os.path.exists(invoice.edi_path) or USE_BLOB_STORAGE):
                logger.info(f"🔍 Reading EDI file from local storage: {invoice.edi_path}")
                edi_content_bytes = await read_file_from_storage(invoice.edi_path, None, None)
                edi_content = edi_content_bytes.decode('utf-8')
                logger.info(f"✅ EDI content read from local storage successfully, length: {len(edi_content)}")
        except Exception as e:
            logger.warning(f"⚠️ Could not read EDI file: {e}")
        
        # Add file content as additional attributes (not part of the model)
        invoice.xml_content = xml_content
        invoice.edi_content = edi_content
        
        # Create a response object that includes stored error details and file contents
        response_data = {
            "id": invoice.id,
            "tracking_id": str(invoice.tracking_id),
            "user_id": invoice.user_id,
            "uploaded_at": invoice.uploaded_at.isoformat(),
            "xml_path": invoice.blob_xml_path if (invoice.blob_xml_path and USE_BLOB_STORAGE) else invoice.xml_path,
            "xml_validation_pass": invoice.xml_validation_pass,
            "xml_convert_message": invoice.xml_convert_message,
            "xml_content": xml_content,
            "edi_path": invoice.blob_edi_path if (invoice.blob_edi_path and USE_BLOB_STORAGE) else invoice.edi_path,
            "edi_convert_pass": invoice.edi_convert_pass,
            "edi_convert_message": invoice.edi_convert_message,
            "edi_content": edi_content,
            "processing_steps_error": processing_steps_error,
            "blob_xml_path": invoice.blob_xml_path,
            "blob_edi_path": invoice.blob_edi_path
        }
        
        # Ensure processing_steps_error is JSON serializable
        try:
            import json
            json.dumps(response_data['processing_steps_error'])
            logger.info("✅ Processing steps error is JSON serializable")
        except (TypeError, ValueError) as e:
            logger.error(f"❌ Processing steps error is not JSON serializable: {e}")
            # Convert to a safe format
            if response_data['processing_steps_error']:
                response_data['processing_steps_error'] = json.loads(json.dumps(response_data['processing_steps_error'], default=str))
        
        logger.info(f"🔍 Response data includes processing_steps_error: {'processing_steps_error' in response_data}")
        logger.info(f"🔍 Processing steps error value: {response_data.get('processing_steps_error')}")
        logger.info(f"🔍 Full response data keys: {list(response_data.keys())}")
        
        # Ensure processing_steps_error is properly serialized
        if response_data.get('processing_steps_error'):
            logger.info(f"🔍 Processing steps error before return: {response_data['processing_steps_error']}")
            logger.info(f"🔍 Processing steps error type: {type(response_data['processing_steps_error'])}")
        else:
            logger.warning("⚠️ Processing steps error is missing from response_data!")
        
        # Return as JSONResponse to ensure proper serialization
        return JSONResponse(content=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting failed invoice by tracking ID {tracking_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting failed invoice: {str(e)}")

@router.get("/deleted", response_model=list[InvoiceResponse])
def get_deleted_invoices(
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get deleted invoices for current user"""
    logger.info(f"🗑️ Getting deleted invoices for user: {current_user.id}")
    
    try:
        # Get deleted successful invoices
        deleted_success_invoices = db.query(SuccessModel).filter(
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.isnot(None)
        ).offset(skip).limit(limit).all()
        
        # Get deleted failed invoices
        deleted_failed_invoices = db.query(FailedModel).filter(
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.isnot(None)
        ).offset(skip).limit(limit).all()
        
        # Convert to InvoiceResponse format
        deleted_invoices = []
        
        # Add successful invoices
        for invoice in deleted_success_invoices:
            deleted_invoices.append(InvoiceResponse(
                id=invoice.id,
                filename=f"{invoice.tracking_id}_invoice.xml",  # Generate filename from tracking_id
                status="success",
                accepted=1,
                rejected=0,
                customerName="N/A",
                formate="XML",
                export=False,
                uploaded_at=invoice.uploaded_at.isoformat() if invoice.uploaded_at else None,
                tracking_id=str(invoice.tracking_id),
                xml_validation_pass=invoice.xml_validation_pass,
                xml_convert_message=invoice.xml_convert_message,
                edi_convert_pass=invoice.edi_convert_pass,
                edi_convert_message=invoice.edi_convert_message,
                deleted_at=invoice.deleted_at.isoformat() if invoice.deleted_at else None
            ))
        
        # Add failed invoices
        for invoice in deleted_failed_invoices:
            deleted_invoices.append(InvoiceResponse(
                id=invoice.id,
                filename=f"{invoice.tracking_id}_invoice.xml",  # Generate filename from tracking_id
                status="failed",
                accepted=0,
                rejected=1,
                customerName="N/A",
                formate="XML",
                export=False,
                uploaded_at=invoice.uploaded_at.isoformat() if invoice.uploaded_at else None,
                tracking_id=str(invoice.tracking_id),
                xml_validation_pass=invoice.xml_validation_pass,
                xml_convert_message=invoice.xml_convert_message,
                edi_convert_pass=invoice.edi_convert_pass,
                edi_convert_message=invoice.edi_convert_message,
                deleted_at=invoice.deleted_at.isoformat() if invoice.deleted_at else None
            ))
        
        # Sort by deleted_at descending (most recently deleted first)
        deleted_invoices.sort(key=lambda x: x.deleted_at or "", reverse=True)
        
        logger.info(f"✅ Found {len(deleted_invoices)} deleted invoices for user: {current_user.id}")
        return deleted_invoices
        
    except Exception as e:
        logger.error(f"❌ Error getting deleted invoices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting deleted invoices: {str(e)}")

@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark an invoice as deleted (soft delete)"""
    logger.info(f"🗑️ Delete invoice request for ID: {invoice_id}, User: {current_user.id}")
    
    try:
        # First check if it's a successful invoice
        success_invoice = db.query(SuccessModel).filter(
            SuccessModel.id == invoice_id,
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.is_(None)  # Only non-deleted invoices
        ).first()
        
        if success_invoice:
            logger.info(f"🗑️ Found successful invoice to delete: {success_invoice.tracking_id}")
            success_invoice.deleted_at = datetime.utcnow()
            db.commit()
            logger.info(f"✅ Successfully soft-deleted successful invoice: {invoice_id}")
            return {"success": True, "message": "Invoice deleted successfully"}
        
        # Check if it's a failed invoice
        failed_invoice = db.query(FailedModel).filter(
            FailedModel.id == invoice_id,
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.is_(None)  # Only non-deleted invoices
        ).first()
        
        if failed_invoice:
            logger.info(f"🗑️ Found failed invoice to delete: {failed_invoice.tracking_id}")
            failed_invoice.deleted_at = datetime.utcnow()
            db.commit()
            logger.info(f"✅ Successfully soft-deleted failed invoice: {invoice_id}")
            return {"success": True, "message": "Invoice deleted successfully"}
        
        # Invoice not found or already deleted
        logger.warning(f"⚠️ Invoice not found or already deleted: {invoice_id}")
        raise HTTPException(status_code=404, detail="Invoice not found or already deleted")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting invoice {invoice_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting invoice: {str(e)}")

@router.post("/{invoice_id}/restore")
def restore_invoice(
    invoice_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a soft-deleted invoice"""
    logger.info(f"🔄 Restore invoice request for ID: {invoice_id}, User: {current_user.id}")
    
    try:
        # First check if it's a successful invoice
        success_invoice = db.query(SuccessModel).filter(
            SuccessModel.id == invoice_id,
            SuccessModel.user_id == current_user.id,
            SuccessModel.deleted_at.isnot(None)  # Only deleted invoices
        ).first()
        
        if success_invoice:
            logger.info(f"🔄 Found deleted successful invoice to restore: {success_invoice.tracking_id}")
            success_invoice.deleted_at = None
            db.commit()
            logger.info(f"✅ Successfully restored successful invoice: {invoice_id}")
            return {"success": True, "message": "Invoice restored successfully"}
        
        # Check if it's a failed invoice
        failed_invoice = db.query(FailedModel).filter(
            FailedModel.id == invoice_id,
            FailedModel.user_id == current_user.id,
            FailedModel.deleted_at.isnot(None)  # Only deleted invoices
        ).first()
        
        if failed_invoice:
            logger.info(f"🔄 Found deleted failed invoice to restore: {failed_invoice.tracking_id}")
            failed_invoice.deleted_at = None
            db.commit()
            logger.info(f"✅ Successfully restored failed invoice: {invoice_id}")
            return {"success": True, "message": "Invoice restored successfully"}
        
        # Invoice not found or not deleted
        logger.warning(f"⚠️ Invoice not found or not deleted: {invoice_id}")
        raise HTTPException(status_code=404, detail="Invoice not found or not deleted")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error restoring invoice {invoice_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error restoring invoice: {str(e)}")
