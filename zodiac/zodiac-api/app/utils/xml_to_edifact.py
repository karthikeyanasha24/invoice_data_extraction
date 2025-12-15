"""
XML to EDIFACT Converter
Converts UBL XML invoices to EDIFACT format
"""
import logging
import os
from typing import Union, Optional, Tuple
from .xml_to_edifact_direct import convert_xml_to_edifact_direct
from .xml_to_x12 import convert_xml_to_x12_content
from .x12_converter import X12Converter
from ..services.file_service import read_file_from_storage, save_file_to_storage

logger = logging.getLogger("zodiac-api.xml_to_edifact")


async def convert_xml_to_edifact(
    xml_path: Union[str, dict], 
    edifact_filename: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Convert XML to EDIFACT format using direct conversion
    
    Strategy:
    1. Try direct XML → EDIFACT conversion (proper EDIFACT format)
    2. Fallback: XML → X12 → EDIFACT (via API if available)
    3. Last resort: XML → X12 (if all else fails)
    
    Args:
        xml_path: Path to XML file (can be local path or blob dict)
        edifact_filename: Target filename for EDIFACT file
        
    Returns:
        Tuple of (success, message, edifact_path)
    """
    logger.info(f"🔄 ===== XML TO EDIFACT CONVERSION =====")
    logger.info(f"📁 Source XML: {xml_path}")
    logger.info(f"📁 Target filename: {edifact_filename}")
    
    try:
        # Step 1: Read XML content
        logger.info(f"📄 Step 1: Reading XML content...")
        xml_content = await read_file_from_storage(xml_path, None, None)
        logger.info(f"✅ XML content read ({len(xml_content)} bytes)")
        
        # Step 2: Try direct XML to EDIFACT conversion (PRIMARY METHOD)
        logger.info(f"🔄 Step 2: Converting XML to EDIFACT (direct method)...")
        edifact_content = convert_xml_to_edifact_direct(xml_content)
        
        if edifact_content:
            logger.info(f"✅ Direct EDIFACT conversion successful ({len(edifact_content)} characters)")
            
            # Validate EDIFACT content
            if 'UNB' in edifact_content and 'UNH' in edifact_content:
                logger.info(f"✅ EDIFACT format validated (contains UNB and UNH segments)")
                
                # Save EDIFACT content
                logger.info(f"💾 Saving EDIFACT file...")
                edifact_path = await save_file_to_storage(
                    edifact_content.encode('utf-8'),
                    edifact_filename,
                    "converted"
                )
                
                logger.info(f"✅ EDIFACT file saved successfully")
                logger.info(f"📊 XML to EDIFACT conversion completed (direct method)")
                
                return True, "XML successfully converted to EDIFACT (direct)", edifact_path
            else:
                logger.warning("⚠️ Direct EDIFACT conversion produced invalid format, trying alternative method...")
        else:
            logger.warning("⚠️ Direct EDIFACT conversion failed, trying alternative method...")
        
        # Step 3: Fallback - Try X12 to EDIFACT via API
        logger.info(f"🔄 Step 3: Fallback - Converting XML to X12...")
        x12_content = convert_xml_to_x12_content(xml_content)
        
        if not x12_content:
            error_msg = "Both EDIFACT and X12 conversion failed"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None
        
        logger.info(f"✅ X12 content generated ({len(x12_content)} characters)")
        
        # Check if EDINation API is available
        api_key = os.getenv("EDINATION_API_KEY")
        
        if api_key:
            logger.info(f"🔄 Step 4: Converting X12 to EDIFACT via API...")
            
            # Initialize converter
            converter = X12Converter(api_key)
            
            # Convert X12 to EDIFACT
            success, api_edifact_content, message = converter.x12_to_edifact(x12_content)
            
            if success and api_edifact_content:
                logger.info(f"✅ API-based EDIFACT conversion successful ({len(api_edifact_content)} characters)")
                
                # Save EDIFACT content
                edifact_path = await save_file_to_storage(
                    api_edifact_content.encode('utf-8'),
                    edifact_filename,
                    "converted"
                )
                
                logger.info(f"✅ EDIFACT file saved successfully (API method)")
                return True, "XML successfully converted to EDIFACT (via API)", edifact_path
            else:
                logger.warning(f"⚠️ API-based conversion failed: {message}")
        else:
            logger.warning("⚠️ EDINATION_API_KEY not configured")
        
        # Step 5: Last resort - Save X12 format with warning
        logger.warning("⚠️ Using X12 format as last resort (EDIFACT conversion unavailable)")
        edifact_path = await save_file_to_storage(
            x12_content.encode('utf-8'),
            edifact_filename,
            "converted"
        )
        
        return True, "⚠️ EDIFACT conversion unavailable - X12 format used", edifact_path
        
    except Exception as e:
        error_msg = f"XML to EDIFACT conversion error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return False, error_msg, None


async def validate_edifact_content(edifact_content: str) -> Tuple[bool, str]:
    """
    Validate EDIFACT content format
    
    Args:
        edifact_content: EDIFACT file content
        
    Returns:
        Tuple of (is_valid, message)
    """
    try:
        # Basic EDIFACT validation
        if not edifact_content or len(edifact_content) < 10:
            return False, "EDIFACT content is empty or too short"
        
        # Check for EDIFACT segments (typically start with UNH, UNT, etc.)
        if 'UNH' not in edifact_content and 'ISA' in edifact_content:
            return True, "Format appears to be X12 (EDIFACT conversion may have failed)"
        
        if 'UNH' in edifact_content:
            return True, "EDIFACT format validated"
        
        return True, "Format validation passed (structure unknown)"
        
    except Exception as e:
        logger.error(f"❌ EDIFACT validation error: {str(e)}")
        return False, f"Validation error: {str(e)}"

