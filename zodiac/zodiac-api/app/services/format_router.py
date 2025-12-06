"""
Format Router Service
Routes invoice processing based on customer format configuration
"""
import logging
from typing import Tuple, Dict, Optional
from ..utils.xml_embed import check_if_content_embedded, embed_content_in_xml
from ..utils.pdf_generator import generate_pdf_from_xml
from ..utils.xml_to_x12 import convert_xml_to_x12_content
from ..utils.edination_validator import validate_x12_with_edination
from ..services.file_service import save_file_to_storage

logger = logging.getLogger("zodiac-api.format_router")


class ProcessingPath:
    """Defines the processing path for a specific format"""
    
    def __init__(
        self,
        format_name: str,
        needs_xml_validation: bool = True,
        needs_conversion: bool = False,
        conversion_target: Optional[str] = None,
        needs_edination_validation: bool = False,
        needs_embed: bool = False,
        embed_type: Optional[str] = None,
        needs_third_party: bool = False,
        description: str = ""
    ):
        self.format_name = format_name
        self.needs_xml_validation = needs_xml_validation
        self.needs_conversion = needs_conversion
        self.conversion_target = conversion_target
        self.needs_edination_validation = needs_edination_validation
        self.needs_embed = needs_embed
        self.embed_type = embed_type
        self.needs_third_party = needs_third_party
        self.description = description


# Define processing paths for each format
PROCESSING_PATHS: Dict[str, ProcessingPath] = {
    "XML": ProcessingPath(
        format_name="XML",
        needs_xml_validation=True,
        needs_conversion=False,
        needs_third_party=False,
        description="XML pass-through with validation only"
    ),
    "X12": ProcessingPath(
        format_name="X12",
        needs_xml_validation=True,
        needs_conversion=True,
        conversion_target="X12",
        needs_edination_validation=True,
        needs_third_party=False,
        description="XML to X12 conversion with EDINation validation"
    ),
    "EDIFACT": ProcessingPath(
        format_name="EDIFACT",
        needs_xml_validation=True,
        needs_conversion=True,
        conversion_target="EDIFACT",
        needs_third_party=False,
        description="XML to EDIFACT conversion"
    ),
    "XML_EMBED_PDF": ProcessingPath(
        format_name="XML_EMBED_PDF",
        needs_xml_validation=True,
        needs_conversion=False,
        needs_embed=True,
        embed_type="PDF",
        needs_third_party=True,
        description="Generate PDF, embed in XML, send to third party"
    ),
    "XML_EMBED_X12": ProcessingPath(
        format_name="XML_EMBED_X12",
        needs_xml_validation=True,
        needs_conversion=True,
        conversion_target="X12",
        needs_embed=True,
        embed_type="X12",
        needs_third_party=True,
        description="Generate X12, embed in XML, send to third party"
    ),
    "XML_EMBED_EDIFACT": ProcessingPath(
        format_name="XML_EMBED_EDIFACT",
        needs_xml_validation=True,
        needs_conversion=True,
        conversion_target="EDIFACT",
        needs_embed=True,
        embed_type="EDIFACT",
        needs_third_party=True,
        description="Generate EDIFACT, embed in XML, send to third party"
    ),
}


def get_processing_path(customer_format: str) -> ProcessingPath:
    """
    Get the processing path for a given customer format
    
    Args:
        customer_format: The format string from customer table
        
    Returns:
        ProcessingPath object defining the workflow
    """
    # Normalize format string (uppercase, handle legacy formats)
    normalized_format = customer_format.upper().strip() if customer_format else "EDIFACT"
    
    # Handle legacy format names
    legacy_mapping = {
        "XMLEMBED": "XML_EMBED_PDF",  # Default old XMLEMBED to PDF embed
        "X12_EMBED": "XML_EMBED_X12",
        "EDI": "EDIFACT",
        "EDIFACT": "EDIFACT",
    }
    
    normalized_format = legacy_mapping.get(normalized_format, normalized_format)
    
    # Get processing path or default to EDIFACT
    path = PROCESSING_PATHS.get(normalized_format, PROCESSING_PATHS["EDIFACT"])
    
    logger.info(f"🎯 Processing path determined: {path.format_name}")
    logger.info(f"📋 Description: {path.description}")
    logger.info(f"🔧 XML Validation: {path.needs_xml_validation}")
    logger.info(f"🔄 Conversion: {path.needs_conversion} → {path.conversion_target if path.needs_conversion else 'N/A'}")
    logger.info(f"🔍 EDINation: {path.needs_edination_validation}")
    logger.info(f"📎 Embed: {path.needs_embed} → {path.embed_type if path.needs_embed else 'N/A'}")
    logger.info(f"🌐 Third Party: {path.needs_third_party}")
    
    return path


async def handle_embed_workflow(
    xml_content: str,
    xml_path: str,
    tracking_id: str,
    embed_type: str,
    converted_content: Optional[str] = None
) -> Tuple[bool, str, str]:
    """
    Handle the embed workflow: check if content is embedded, if not, generate and embed it
    
    Args:
        xml_content: The original XML content
        xml_path: Path to the XML file
        tracking_id: Tracking ID for the processing
        embed_type: Type of content to embed ("PDF", "X12", "EDIFACT")
        converted_content: Pre-converted content (for X12/EDIFACT), if available
        
    Returns:
        Tuple of (success, message, modified_xml_path)
    """
    logger.info(f"📎 ===== EMBED WORKFLOW: {embed_type} =====")
    
    try:
        # Step 1: Check if content is already embedded
        logger.info(f"🔍 Checking if {embed_type} is already embedded...")
        is_embedded, embedded_content = check_if_content_embedded(xml_content, embed_type)
        
        if is_embedded:
            logger.info(f"✅ {embed_type} content already embedded - skipping generation")
            return True, f"{embed_type} already embedded in XML", xml_path
        
        # Step 2: Generate content to embed
        logger.info(f"🔄 {embed_type} not embedded - generating content...")
        
        content_to_embed = None
        
        if embed_type == "PDF":
            # Generate PDF from XML
            pdf_bytes = await generate_pdf_from_xml(xml_content)
            if pdf_bytes:
                content_to_embed = pdf_bytes
                logger.info(f"✅ PDF generated: {len(pdf_bytes)} bytes")
            else:
                logger.error("❌ PDF generation failed")
                return False, "PDF generation failed", xml_path
                
        elif embed_type == "X12":
            # Use pre-converted X12 content
            if converted_content:
                content_to_embed = converted_content.encode('utf-8')
                logger.info(f"✅ Using pre-converted X12: {len(content_to_embed)} bytes")
            else:
                logger.error("❌ No X12 content available to embed")
                return False, "No X12 content available to embed", xml_path
                
        elif embed_type == "EDIFACT":
            # Use pre-converted EDIFACT content
            if converted_content:
                content_to_embed = converted_content.encode('utf-8')
                logger.info(f"✅ Using pre-converted EDIFACT: {len(content_to_embed)} bytes")
            else:
                logger.error("❌ No EDIFACT content available to embed")
                return False, "No EDIFACT content available to embed", xml_path
        
        if not content_to_embed:
            logger.error(f"❌ Failed to generate {embed_type} content")
            return False, f"Failed to generate {embed_type} content", xml_path
        
        # Step 3: Embed content in XML
        logger.info(f"📎 Embedding {embed_type} into XML...")
        filename = f"{tracking_id}_{embed_type.lower()}"
        modified_xml = embed_content_in_xml(xml_content, content_to_embed, embed_type, filename)
        
        # Step 4: Save modified XML
        logger.info(f"💾 Saving modified XML with embedded {embed_type}...")
        modified_xml_filename = f"{tracking_id}_with_{embed_type.lower()}.xml"
        modified_xml_path = await save_file_to_storage(
            modified_xml.encode('utf-8'),
            modified_xml_filename,
            "uploads"
        )
        
        logger.info(f"✅ {embed_type} embedded and XML saved successfully")
        return True, f"{embed_type} embedded in XML successfully", modified_xml_path
        
    except Exception as e:
        logger.error(f"❌ Embed workflow error: {str(e)}")
        return False, f"Embed workflow error: {str(e)}", xml_path

