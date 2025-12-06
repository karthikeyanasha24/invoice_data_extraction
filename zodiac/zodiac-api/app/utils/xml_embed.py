"""
XML Embed Utilities
Functions to check and embed content (PDF, X12, EDIFACT) into XML files
"""
import logging
from lxml import etree
from typing import Tuple, Optional
import base64

logger = logging.getLogger("zodiac-api.xml_embed")


def check_if_content_embedded(xml_content: str, content_type: str = "PDF") -> Tuple[bool, Optional[str]]:
    """
    Check if content (PDF/X12/EDIFACT) is already embedded in XML
    
    Args:
        xml_content: The XML content to check
        content_type: Type of content to check for ("PDF", "X12", "EDIFACT")
        
    Returns:
        Tuple of (is_embedded, embedded_content)
        - is_embedded: Boolean indicating if content is found
        - embedded_content: The embedded content if found, None otherwise
    """
    logger.info(f"🔍 Checking if {content_type} is embedded in XML")
    
    try:
        # Parse XML
        root = etree.fromstring(xml_content.encode('utf-8'))
        
        # Define namespaces
        namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        }
        
        # Look for AdditionalDocumentReference with embedded content
        # UBL structure: <cac:AdditionalDocumentReference>
        #                   <cbc:ID>...</cbc:ID>
        #                   <cbc:DocumentTypeCode>...</cbc:DocumentTypeCode>
        #                   <cac:Attachment>
        #                       <cbc:EmbeddedDocumentBinaryObject mimeCode="..." filename="...">
        #                           base64content
        #                       </cbc:EmbeddedDocumentBinaryObject>
        #                   </cac:Attachment>
        #                </cac:AdditionalDocumentReference>
        
        # Search for embedded documents
        embedded_docs = root.findall('.//cac:AdditionalDocumentReference', namespaces)
        
        for doc in embedded_docs:
            doc_type = doc.find('.//cbc:DocumentTypeCode', namespaces)
            embedded_binary = doc.find('.//cbc:EmbeddedDocumentBinaryObject', namespaces)
            
            if embedded_binary is not None:
                mime_code = embedded_binary.get('mimeCode', '')
                
                # Check if this is the type we're looking for
                if content_type.upper() == "PDF" and "pdf" in mime_code.lower():
                    logger.info(f"✅ {content_type} content found embedded in XML")
                    return True, embedded_binary.text
                elif content_type.upper() == "X12" and ("x12" in mime_code.lower() or "edi" in mime_code.lower()):
                    logger.info(f"✅ {content_type} content found embedded in XML")
                    return True, embedded_binary.text
                elif content_type.upper() == "EDIFACT" and ("edifact" in mime_code.lower() or "edi" in mime_code.lower()):
                    logger.info(f"✅ {content_type} content found embedded in XML")
                    return True, embedded_binary.text
        
        logger.info(f"ℹ️ No {content_type} content found embedded in XML")
        return False, None
        
    except Exception as e:
        logger.error(f"❌ Error checking for embedded content: {str(e)}")
        return False, None


def embed_content_in_xml(xml_content: str, content_to_embed: bytes, content_type: str = "PDF", filename: str = "document") -> str:
    """
    Embed content (PDF/X12/EDIFACT) into XML as base64 encoded binary object
    
    Args:
        xml_content: The original XML content
        content_to_embed: The binary content to embed (PDF bytes, X12 string bytes, etc.)
        content_type: Type of content ("PDF", "X12", "EDIFACT")
        filename: Name for the embedded file
        
    Returns:
        Modified XML content with embedded document
    """
    logger.info(f"📎 Embedding {content_type} content into XML")
    logger.info(f"📊 Content size: {len(content_to_embed)} bytes")
    
    try:
        # Parse XML
        parser = etree.XMLParser(remove_blank_text=True)
        root = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        # Define namespaces
        namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        }
        
        # Register namespaces
        for prefix, uri in namespaces.items():
            etree.register_namespace(prefix, uri)
        
        # Encode content to base64
        base64_content = base64.b64encode(content_to_embed).decode('utf-8')
        
        # Determine MIME type and document type code
        if content_type.upper() == "PDF":
            mime_code = "application/pdf"
            doc_type_code = "916"  # UBL code for attached document
            file_extension = ".pdf"
        elif content_type.upper() == "X12":
            mime_code = "application/x12"
            doc_type_code = "916"
            file_extension = ".x12"
        elif content_type.upper() == "EDIFACT":
            mime_code = "application/edifact"
            doc_type_code = "916"
            file_extension = ".edi"
        else:
            mime_code = "application/octet-stream"
            doc_type_code = "916"
            file_extension = ""
        
        # Create AdditionalDocumentReference element
        additional_doc_ref = etree.Element(
            f"{{{namespaces['cac']}}}AdditionalDocumentReference"
        )
        
        # Add ID
        id_elem = etree.SubElement(
            additional_doc_ref,
            f"{{{namespaces['cbc']}}}ID"
        )
        id_elem.text = f"{content_type}_EMBEDDED"
        
        # Add DocumentTypeCode
        doc_type_elem = etree.SubElement(
            additional_doc_ref,
            f"{{{namespaces['cbc']}}}DocumentTypeCode"
        )
        doc_type_elem.text = doc_type_code
        
        # Add Attachment
        attachment = etree.SubElement(
            additional_doc_ref,
            f"{{{namespaces['cac']}}}Attachment"
        )
        
        # Add EmbeddedDocumentBinaryObject
        embedded_binary = etree.SubElement(
            attachment,
            f"{{{namespaces['cbc']}}}EmbeddedDocumentBinaryObject",
            mimeCode=mime_code,
            filename=f"{filename}{file_extension}"
        )
        embedded_binary.text = base64_content
        
        # Find the best insertion point (after AccountingCustomerParty, before PaymentMeans)
        insertion_point = None
        payment_means = root.find('.//cac:PaymentMeans', namespaces)
        if payment_means is not None:
            insertion_point = root.index(payment_means)
        
        # Insert the AdditionalDocumentReference
        if insertion_point is not None:
            root.insert(insertion_point, additional_doc_ref)
        else:
            root.append(additional_doc_ref)
        
        # Convert back to string
        modified_xml = etree.tostring(
            root,
            encoding='utf-8',
            xml_declaration=True,
            pretty_print=True
        ).decode('utf-8')
        
        logger.info(f"✅ {content_type} content embedded successfully")
        logger.info(f"📊 Modified XML size: {len(modified_xml)} characters")
        
        return modified_xml
        
    except Exception as e:
        logger.error(f"❌ Error embedding content in XML: {str(e)}")
        raise


def extract_embedded_content(xml_content: str, content_type: str = "PDF") -> Optional[bytes]:
    """
    Extract embedded content from XML and decode from base64
    
    Args:
        xml_content: The XML content with embedded document
        content_type: Type of content to extract ("PDF", "X12", "EDIFACT")
        
    Returns:
        Decoded binary content, or None if not found
    """
    logger.info(f"📤 Extracting {content_type} content from XML")
    
    try:
        is_embedded, base64_content = check_if_content_embedded(xml_content, content_type)
        
        if not is_embedded or not base64_content:
            logger.warning(f"⚠️ No {content_type} content found to extract")
            return None
        
        # Decode from base64
        decoded_content = base64.b64decode(base64_content)
        
        logger.info(f"✅ {content_type} content extracted successfully")
        logger.info(f"📊 Decoded size: {len(decoded_content)} bytes")
        
        return decoded_content
        
    except Exception as e:
        logger.error(f"❌ Error extracting embedded content: {str(e)}")
        return None

