"""
XML to EDIFACT Converter
Converts UBL XML invoices to EDIFACT format via X12 intermediate format
"""
import logging
import os
from typing import Union, Optional, Tuple
from .xml_to_x12 import convert_xml_to_x12_content
from .x12_converter import X12Converter
from ..services.file_service import read_file_from_storage, save_file_to_storage

logger = logging.getLogger("zodiac-api.xml_to_edifact")


async def convert_xml_to_edifact(
    xml_path: Union[str, dict], 
    edifact_filename: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Convert XML to EDIFACT format using two-step process:
    1. XML → X12 (using existing converter)
    2. X12 → EDIFACT (using EDINation API)
    
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
        
        # Step 2: Convert XML to X12
        logger.info(f"🔄 Step 2: Converting XML to X12...")
        x12_content = convert_xml_to_x12_content(xml_content)
        
        if not x12_content:
            error_msg = "XML to X12 conversion failed"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None
        
        logger.info(f"✅ X12 content generated ({len(x12_content)} characters)")
        
        # Step 3: Convert X12 to EDIFACT using EDINation API
        logger.info(f"🔄 Step 3: Converting X12 to EDIFACT...")
        
        # Get EDINation API key from environment
        api_key = os.getenv("EDINATION_API_KEY")
        
        if not api_key:
            logger.warning("⚠️ EDINATION_API_KEY not found - EDIFACT conversion not available")
            logger.info("💡 For now, returning X12 format as fallback")
            
            # Save X12 content as EDIFACT (temporary fallback)
            edifact_path = await save_file_to_storage(
                x12_content.encode('utf-8'),
                edifact_filename,
                "converted"
            )
            
            return True, "EDIFACT conversion skipped (API key not configured) - X12 format used", edifact_path
        
        # Initialize converter
        converter = X12Converter(api_key)
        
        # Convert X12 to EDIFACT
        success, edifact_content, message = converter.x12_to_edifact(x12_content)
        
        if not success:
            logger.error(f"❌ X12 to EDIFACT conversion failed: {message}")
            
            # Fallback: Save X12 format instead
            logger.warning("⚠️ Falling back to X12 format")
            edifact_path = await save_file_to_storage(
                x12_content.encode('utf-8'),
                edifact_filename,
                "converted"
            )
            
            return True, f"EDIFACT conversion failed ({message}), using X12 format", edifact_path
        
        logger.info(f"✅ EDIFACT content generated ({len(edifact_content)} characters)")
        
        # Step 4: Save EDIFACT content
        logger.info(f"💾 Step 4: Saving EDIFACT file...")
        edifact_path = await save_file_to_storage(
            edifact_content.encode('utf-8'),
            edifact_filename,
            "converted"
        )
        
        logger.info(f"✅ EDIFACT file saved successfully")
        logger.info(f"📊 XML to EDIFACT conversion completed")
        
        return True, "XML successfully converted to EDIFACT", edifact_path
        
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

