"""
Correction Cache Service - Intelligent error correction with learning

This service manages the automatic correction of recurring errors by:
1. Checking if a correction exists for a customer + error combination
2. Applying cached corrections
3. Learning from AI corrections
4. Tracking success/failure rates
"""
import logging
import hashlib
import json
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from lxml import etree
import re

from ..models.correction_cache import CorrectionCache

logger = logging.getLogger("zodiac-api.correction_cache")


class CorrectionCacheService:
    """
    Service for managing correction cache operations.
    Provides intelligent error correction with learning capabilities.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    @staticmethod
    def generate_error_signature(error_type: str, error_context: Dict[str, Any]) -> str:
        """
        Generate a unique signature for an error based on type and context.
        
        Args:
            error_type: Type of error (e.g., "missing_sender_id")
            error_context: Dictionary with error details
        
        Returns:
            A signature string that uniquely identifies this error pattern
        """
        # Create a deterministic signature from error details
        signature_parts = [error_type]
        
        # Add relevant context based on error type
        if "xpath" in error_context:
            signature_parts.append(f"xpath:{error_context['xpath']}")
        
        if "element" in error_context:
            signature_parts.append(f"element:{error_context['element']}")
        
        if "field" in error_context:
            signature_parts.append(f"field:{error_context['field']}")
        
        if "segment" in error_context:
            signature_parts.append(f"segment:{error_context['segment']}")
        
        signature = "|".join(signature_parts)
        
        # For very long signatures, hash them
        if len(signature) > 400:
            signature_hash = hashlib.md5(signature.encode()).hexdigest()
            return f"{error_type}|hash:{signature_hash}"
        
        return signature
    
    def find_correction(
        self,
        customer_id: str,
        error_type: str,
        error_signature: str,
        correction_type: str = "XML"
    ) -> Optional[CorrectionCache]:
        """
        Find an existing correction for this customer + error combination.
        
        Args:
            customer_id: Customer identifier
            error_type: Type of error
            error_signature: Unique error signature
            correction_type: Type of correction ("XML" or "EDI")
        
        Returns:
            CorrectionCache object if found, None otherwise
        """
        try:
            logger.info(f"🔍 Searching for cached correction:")
            logger.info(f"   Customer: {customer_id}")
            logger.info(f"   Error Type: {error_type}")
            logger.info(f"   Signature: {error_signature}")
            logger.info(f"   Correction Type: {correction_type}")
            
            # Try exact match first (customer + error signature)
            correction = self.db.query(CorrectionCache).filter(
                CorrectionCache.customer_id == customer_id,
                CorrectionCache.error_signature == error_signature,
                CorrectionCache.correction_type == correction_type,
                CorrectionCache.is_active == True
            ).order_by(CorrectionCache.success_count.desc()).first()
            
            if correction:
                logger.info(f"✅ Found exact match: Correction ID {correction.id}")
                logger.info(f"   Success rate: {correction.get_success_rate():.1f}%")
                return correction
            
            # Try broader match (customer + error type, ignore signature)
            correction = self.db.query(CorrectionCache).filter(
                CorrectionCache.customer_id == customer_id,
                CorrectionCache.error_type == error_type,
                CorrectionCache.correction_type == correction_type,
                CorrectionCache.is_active == True
            ).order_by(CorrectionCache.success_count.desc()).first()
            
            if correction:
                logger.info(f"✅ Found broader match: Correction ID {correction.id}")
                logger.info(f"   Success rate: {correction.get_success_rate():.1f}%")
                return correction
            
            logger.info(f"❌ No cached correction found")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error searching for correction: {e}")
            return None
    
    def apply_xml_correction(
        self,
        xml_content: str,
        transformation_rule: Dict[str, Any]
    ) -> Tuple[bool, str, str]:
        """
        Apply a cached XML correction based on transformation rule.
        
        Args:
            xml_content: Original XML content
            transformation_rule: JSON rule describing the transformation
        
        Returns:
            Tuple of (success, corrected_xml, message)
        """
        try:
            logger.info(f"🔧 Applying cached XML correction")
            logger.info(f"   Transformation: {transformation_rule}")
            
            # Parse XML
            parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            
            # Get namespace map
            nsmap = root.nsmap
            
            # Apply transformation based on action type
            action = transformation_rule.get("action")
            
            if action == "add_element":
                # Add missing element
                xpath = transformation_rule.get("xpath")
                element_name = transformation_rule.get("element_name")
                value = transformation_rule.get("value")
                attributes = transformation_rule.get("attributes", {})
                
                # Find parent element
                parent_xpath = "/".join(xpath.split("/")[:-1])
                parent = root.xpath(parent_xpath, namespaces=nsmap)
                
                if parent:
                    parent = parent[0]
                    # Extract namespace from element name if present
                    if ":" in element_name:
                        ns_prefix, local_name = element_name.split(":", 1)
                        ns_uri = nsmap.get(ns_prefix)
                        new_element = etree.SubElement(parent, f"{{{ns_uri}}}{local_name}")
                    else:
                        new_element = etree.SubElement(parent, element_name)
                    
                    # Add attributes
                    for attr_name, attr_value in attributes.items():
                        new_element.set(attr_name, attr_value)
                    
                    # Set value
                    if value:
                        new_element.text = value
                    
                    logger.info(f"✅ Added element: {element_name}")
                else:
                    logger.error(f"❌ Parent element not found: {parent_xpath}")
                    return False, xml_content, "Parent element not found"
            
            elif action == "modify_element":
                # Modify existing element
                xpath = transformation_rule.get("xpath")
                value = transformation_rule.get("value")
                
                elements = root.xpath(xpath, namespaces=nsmap)
                if elements:
                    elements[0].text = value
                    logger.info(f"✅ Modified element: {xpath}")
                else:
                    logger.error(f"❌ Element not found: {xpath}")
                    return False, xml_content, "Element not found"
            
            elif action == "add_attribute":
                # Add attribute to element
                xpath = transformation_rule.get("xpath")
                attr_name = transformation_rule.get("attr_name")
                attr_value = transformation_rule.get("attr_value")
                
                elements = root.xpath(xpath, namespaces=nsmap)
                if elements:
                    elements[0].set(attr_name, attr_value)
                    logger.info(f"✅ Added attribute {attr_name} to {xpath}")
                else:
                    logger.error(f"❌ Element not found: {xpath}")
                    return False, xml_content, "Element not found"
            
            elif action == "regex_replace":
                # Apply regex replacement
                pattern = transformation_rule.get("pattern")
                replacement = transformation_rule.get("replacement")
                
                xml_content = re.sub(pattern, replacement, xml_content)
                logger.info(f"✅ Applied regex replacement")
                
                # Return early for regex (no need to re-serialize XML)
                return True, xml_content, "Regex correction applied successfully"
            
            else:
                logger.warning(f"⚠️ Unknown action type: {action}")
                return False, xml_content, f"Unknown action: {action}"
            
            # Serialize back to string
            corrected_xml = etree.tostring(root, encoding='unicode', pretty_print=True)
            
            logger.info(f"✅ XML correction applied successfully")
            return True, corrected_xml, "Correction applied successfully"
            
        except Exception as e:
            logger.error(f"❌ Error applying XML correction: {e}")
            logger.exception(e)
            return False, xml_content, f"Error applying correction: {str(e)}"
    
    def apply_edi_correction(
        self,
        edi_content: str,
        transformation_rule: Dict[str, Any]
    ) -> Tuple[bool, str, str]:
        """
        Apply a cached EDI correction based on transformation rule.
        
        Args:
            edi_content: Original EDI content
            transformation_rule: JSON rule describing the transformation
        
        Returns:
            Tuple of (success, corrected_edi, message)
        """
        try:
            logger.info(f"🔧 Applying cached EDI correction")
            logger.info(f"   Transformation: {transformation_rule}")
            
            action = transformation_rule.get("action")
            
            if action == "pad_field":
                # Pad a field to required length
                segment_name = transformation_rule.get("segment")
                field_index = transformation_rule.get("field_index")
                target_length = transformation_rule.get("length")
                pad_char = transformation_rule.get("pad_char", " ")
                
                segments = edi_content.split("~")
                corrected_segments = []
                
                for segment in segments:
                    if segment.startswith(f"{segment_name}*"):
                        fields = segment.split("*")
                        if len(fields) > field_index:
                            # Pad the field
                            fields[field_index] = fields[field_index].ljust(target_length, pad_char)[:target_length]
                            segment = "*".join(fields)
                            logger.info(f"✅ Padded {segment_name} field {field_index}")
                    corrected_segments.append(segment)
                
                corrected_edi = "~".join(corrected_segments)
                return True, corrected_edi, "EDI field padding applied"
            
            elif action == "replace_entity_code":
                # Replace entity identifier code (e.g., SU -> SE)
                old_code = transformation_rule.get("old_code")
                new_code = transformation_rule.get("new_code")
                segment_name = transformation_rule.get("segment", "N1")
                
                pattern = f"{segment_name}\\*{old_code}\\*"
                replacement = f"{segment_name}*{new_code}*"
                corrected_edi = re.sub(pattern, replacement, edi_content)
                
                logger.info(f"✅ Replaced entity code {old_code} -> {new_code}")
                return True, corrected_edi, "Entity code replacement applied"
            
            elif action == "regex_replace":
                # Apply regex replacement
                pattern = transformation_rule.get("pattern")
                replacement = transformation_rule.get("replacement")
                
                corrected_edi = re.sub(pattern, replacement, edi_content)
                logger.info(f"✅ Applied regex replacement")
                return True, corrected_edi, "Regex correction applied"
            
            else:
                logger.warning(f"⚠️ Unknown EDI action: {action}")
                return False, edi_content, f"Unknown action: {action}"
                
        except Exception as e:
            logger.error(f"❌ Error applying EDI correction: {e}")
            logger.exception(e)
            return False, edi_content, f"Error applying correction: {str(e)}"
    
    def save_correction_from_ai(
        self,
        customer_id: str,
        customer_name: Optional[str],
        error_type: str,
        error_signature: str,
        correction_type: str,
        original_content: str,
        corrected_content: str,
        ai_model: str,
        user_id: Optional[int] = None
    ) -> Optional[CorrectionCache]:
        """
        Save a new correction learned from AI.
        
        Args:
            customer_id: Customer identifier
            customer_name: Customer name
            error_type: Type of error corrected
            error_signature: Unique error signature
            correction_type: "XML" or "EDI"
            original_content: Original content before correction
            corrected_content: Corrected content from AI
            ai_model: AI model used (e.g., "gpt-4o-mini")
            user_id: User ID (integer) who triggered this correction
        
        Returns:
            CorrectionCache object if saved successfully, None otherwise
        """
        try:
            logger.info(f"💾 Saving new correction from AI:")
            logger.info(f"   Customer: {customer_id}")
            logger.info(f"   Error Type: {error_type}")
            logger.info(f"   AI Model: {ai_model}")
            
            # Try to infer transformation rule by comparing original and corrected
            transformation_rule = self._infer_transformation(
                original_content,
                corrected_content,
                correction_type,
                error_type
            )
            
            # Create new correction cache entry
            # user_id is already an Integer from ZodiacUser model
            correction = CorrectionCache(
                customer_id=customer_id,
                customer_name=customer_name,
                error_type=error_type,
                error_signature=error_signature,
                correction_type=correction_type,
                transformation_rule=transformation_rule,
                original_content_snippet=original_content[:1000] if original_content else None,
                corrected_content_snippet=corrected_content[:1000] if corrected_content else None,
                ai_model_used=ai_model,
                success_count=1,  # Start with 1 since AI just succeeded
                failure_count=0,
                is_active=True,
                created_by_user_id=user_id,  # Pass integer directly
                last_success_at=datetime.utcnow()
            )
            
            self.db.add(correction)
            self.db.commit()
            
            logger.info(f"✅ Correction saved with ID: {correction.id}")
            logger.info(f"   Transformation rule: {transformation_rule}")
            
            return correction
            
        except Exception as e:
            logger.error(f"❌ Error saving correction: {e}")
            logger.exception(e)
            self.db.rollback()
            return None
    
    def _infer_transformation(
        self,
        original: str,
        corrected: str,
        correction_type: str,
        error_type: str
    ) -> Dict[str, Any]:
        """
        Try to infer the transformation rule by comparing original and corrected content.
        
        This is a best-effort approach to extract reusable patterns.
        For complex changes, we store a generic "ai_correction" rule.
        """
        try:
            if correction_type == "XML":
                # Try to detect added elements
                if "<cbc:EndpointID" in corrected and "<cbc:EndpointID" not in original:
                    # Sender ID was added
                    return {
                        "action": "add_element",
                        "xpath": "/Invoice/cac:AccountingSupplierParty/cac:Party",
                        "element_name": "cbc:EndpointID",
                        "attributes": {"schemeID": "0088"},
                        "value": self._extract_endpoint_id(corrected),
                        "description": "Add missing sender EndpointID"
                    }
                
                # For other cases, use generic AI correction
                return {
                    "action": "ai_full_correction",
                    "error_type": error_type,
                    "description": "Full XML correction by AI",
                    "note": "Complex correction - full content replacement may be needed"
                }
            
            elif correction_type == "EDI":
                # Detect ISA field padding
                if "ISA*" in corrected:
                    return {
                        "action": "pad_field",
                        "segment": "ISA",
                        "field_index": 6,  # Sender ID
                        "length": 15,
                        "pad_char": " ",
                        "description": "Pad ISA sender ID to 15 characters"
                    }
                
                # Detect N1 entity code changes
                if "N1*SU*" in original and "N1*SE*" in corrected:
                    return {
                        "action": "replace_entity_code",
                        "segment": "N1",
                        "old_code": "SU",
                        "new_code": "SE",
                        "description": "Replace supplier code SU with SE"
                    }
                
                # Generic EDI correction
                return {
                    "action": "ai_full_correction",
                    "error_type": error_type,
                    "description": "Full EDI correction by AI"
                }
            
            # Default: store as generic correction
            return {
                "action": "ai_full_correction",
                "error_type": error_type,
                "description": f"Full {correction_type} correction by AI"
            }
            
        except Exception as e:
            logger.warning(f"⚠️ Could not infer transformation: {e}")
            return {
                "action": "ai_full_correction",
                "error_type": error_type,
                "description": "Generic AI correction"
            }
    
    def _extract_endpoint_id(self, xml_content: str) -> str:
        """Extract EndpointID value from XML content"""
        try:
            match = re.search(r'<cbc:EndpointID[^>]*>([^<]+)</cbc:EndpointID>', xml_content)
            if match:
                return match.group(1)
        except:
            pass
        return "UNKNOWN"
    
    def mark_success(self, correction_id: str):
        """Mark a correction as successfully applied"""
        try:
            correction = self.db.query(CorrectionCache).filter(
                CorrectionCache.id == correction_id
            ).first()
            
            if correction:
                correction.mark_success()
                self.db.commit()
                logger.info(f"✅ Marked correction {correction_id} as success")
        except Exception as e:
            logger.error(f"❌ Error marking success: {e}")
            self.db.rollback()
    
    def mark_failure(self, correction_id: str):
        """Mark a correction as failed when applied"""
        try:
            correction = self.db.query(CorrectionCache).filter(
                CorrectionCache.id == correction_id
            ).first()
            
            if correction:
                correction.mark_failure()
                self.db.commit()
                logger.info(f"⚠️ Marked correction {correction_id} as failure")
                
                if not correction.is_active:
                    logger.warning(f"🚫 Correction {correction_id} auto-disabled due to high failure rate")
        except Exception as e:
            logger.error(f"❌ Error marking failure: {e}")
            self.db.rollback()
    
    def get_customer_corrections(self, customer_id: str) -> List[CorrectionCache]:
        """Get all corrections for a specific customer"""
        try:
            corrections = self.db.query(CorrectionCache).filter(
                CorrectionCache.customer_id == customer_id,
                CorrectionCache.is_active == True
            ).order_by(CorrectionCache.success_count.desc()).all()
            
            return corrections
        except Exception as e:
            logger.error(f"❌ Error fetching customer corrections: {e}")
            return []
    
    def get_correction_stats(self) -> Dict[str, Any]:
        """Get overall correction cache statistics"""
        try:
            total_corrections = self.db.query(CorrectionCache).count()
            active_corrections = self.db.query(CorrectionCache).filter(
                CorrectionCache.is_active == True
            ).count()
            
            # Calculate total successes
            total_successes = self.db.query(
                CorrectionCache.success_count
            ).filter(CorrectionCache.is_active == True).all()
            total_success_count = sum([c[0] for c in total_successes])
            
            return {
                "total_corrections": total_corrections,
                "active_corrections": active_corrections,
                "inactive_corrections": total_corrections - active_corrections,
                "total_successful_applications": total_success_count
            }
        except Exception as e:
            logger.error(f"❌ Error fetching stats: {e}")
            return {}

