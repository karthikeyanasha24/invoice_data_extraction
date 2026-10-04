"""
XML Diff Service - Analyze differences between original and manually edited XML

This service compares two XML documents and generates transformation rules
that can be saved to the correction cache for future automatic fixes.
"""

import logging
import hashlib
import re
from typing import Dict, List, Optional, Tuple
from lxml import etree
from difflib import SequenceMatcher

logger = logging.getLogger("zodiac-api.xml_diff_service")


class XMLDiffService:
    """Service for analyzing XML differences and generating transformation rules"""
    
    def __init__(self):
        self.changes = []
    
    def compare_xml(self, original: str, edited: str) -> Dict:
        """
        Compare two XML documents and identify all differences
        
        Args:
            original: Original XML content
            edited: Edited XML content
        
        Returns:
            Dict containing:
                - changes: List of detected changes
                - change_summary: Summary of changes
                - transformation_rules: Extracted transformation rules
        """
        try:
            logger.info("🔍 Comparing original and edited XML...")
            
            # Parse both XML documents
            try:
                original_root = etree.fromstring(original.encode('utf-8'))
                edited_root = etree.fromstring(edited.encode('utf-8'))
            except Exception as parse_err:
                logger.error(f"❌ Failed to parse XML: {parse_err}")
                return {
                    "changes": [],
                    "change_summary": "Failed to parse XML",
                    "transformation_rules": []
                }
            
            # Detect changes
            changes = []
            
            # 1. Check for added elements
            added_elements = self._find_added_elements(original_root, edited_root)
            changes.extend(added_elements)
            
            # 2. Check for modified elements
            modified_elements = self._find_modified_elements(original_root, edited_root)
            changes.extend(modified_elements)
            
            # 3. Check for modified attributes
            modified_attributes = self._find_modified_attributes(original_root, edited_root)
            changes.extend(modified_attributes)
            
            # 4. Check for removed elements
            removed_elements = self._find_removed_elements(original_root, edited_root)
            changes.extend(removed_elements)
            
            logger.info(f"✅ Found {len(changes)} changes")
            
            # Generate summary
            change_summary = self._generate_change_summary(changes)
            
            # Generate transformation rules
            transformation_rules = self._generate_transformation_rules(changes)
            
            return {
                "changes": changes,
                "change_summary": change_summary,
                "transformation_rules": transformation_rules
            }
            
        except Exception as e:
            logger.error(f"❌ Error comparing XML: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "changes": [],
                "change_summary": f"Error: {str(e)}",
                "transformation_rules": []
            }
    
    def _get_element_path(self, element: etree._Element, root: etree._Element) -> str:
        """Get the XPath of an element relative to root"""
        try:
            path = root.getroottree().getelementpath(element)
            # Convert to more readable format
            if path.startswith('./'):
                path = '/' + root.tag + '/' + path[2:]
            return path
        except:
            return element.tag
    
    def _find_added_elements(self, original_root: etree._Element, edited_root: etree._Element) -> List[Dict]:
        """Find elements that were added in the edited version"""
        changes = []
        
        try:
            # Get all elements from both trees
            original_paths = set()
            for elem in original_root.iter():
                path = self._get_element_path(elem, original_root)
                original_paths.add(path)
            
            edited_elements = {}
            for elem in edited_root.iter():
                path = self._get_element_path(elem, edited_root)
                edited_elements[path] = elem
            
            # Find new elements
            for path, elem in edited_elements.items():
                if path not in original_paths:
                    changes.append({
                        "type": "add_element",
                        "xpath": path,
                        "tag": elem.tag,
                        "text": elem.text,
                        "attributes": dict(elem.attrib)
                    })
                    logger.debug(f"   Added element: {path}")
        
        except Exception as e:
            logger.warning(f"⚠️ Error finding added elements: {e}")
        
        return changes
    
    def _find_modified_elements(self, original_root: etree._Element, edited_root: etree._Element) -> List[Dict]:
        """Find elements whose text content was modified"""
        changes = []
        
        try:
            # Build maps of elements by path
            original_elements = {}
            for elem in original_root.iter():
                path = self._get_element_path(elem, original_root)
                original_elements[path] = elem
            
            edited_elements = {}
            for elem in edited_root.iter():
                path = self._get_element_path(elem, edited_root)
                edited_elements[path] = elem
            
            # Compare text content
            for path in original_elements:
                if path in edited_elements:
                    orig_text = (original_elements[path].text or "").strip()
                    edit_text = (edited_elements[path].text or "").strip()
                    
                    if orig_text != edit_text:
                        changes.append({
                            "type": "modify_element",
                            "xpath": path,
                            "tag": original_elements[path].tag,
                            "old_text": orig_text,
                            "new_text": edit_text
                        })
                        logger.debug(f"   Modified element: {path} ('{orig_text}' -> '{edit_text}')")
        
        except Exception as e:
            logger.warning(f"⚠️ Error finding modified elements: {e}")
        
        return changes
    
    def _find_modified_attributes(self, original_root: etree._Element, edited_root: etree._Element) -> List[Dict]:
        """Find attributes that were modified"""
        changes = []
        
        try:
            # Build maps of elements by path
            original_elements = {}
            for elem in original_root.iter():
                path = self._get_element_path(elem, original_root)
                original_elements[path] = elem
            
            edited_elements = {}
            for elem in edited_root.iter():
                path = self._get_element_path(elem, edited_root)
                edited_elements[path] = elem
            
            # Compare attributes
            for path in original_elements:
                if path in edited_elements:
                    orig_attrs = dict(original_elements[path].attrib)
                    edit_attrs = dict(edited_elements[path].attrib)
                    
                    # Find modified or added attributes
                    for attr_name, attr_value in edit_attrs.items():
                        if attr_name not in orig_attrs or orig_attrs[attr_name] != attr_value:
                            changes.append({
                                "type": "modify_attribute",
                                "xpath": path,
                                "tag": original_elements[path].tag,
                                "attribute": attr_name,
                                "old_value": orig_attrs.get(attr_name),
                                "new_value": attr_value
                            })
                            logger.debug(f"   Modified attribute: {path}[@{attr_name}]")
        
        except Exception as e:
            logger.warning(f"⚠️ Error finding modified attributes: {e}")
        
        return changes
    
    def _find_removed_elements(self, original_root: etree._Element, edited_root: etree._Element) -> List[Dict]:
        """Find elements that were removed in the edited version"""
        changes = []
        
        try:
            # Get all element paths
            original_elements = {}
            for elem in original_root.iter():
                path = self._get_element_path(elem, original_root)
                original_elements[path] = elem
            
            edited_paths = set()
            for elem in edited_root.iter():
                path = self._get_element_path(elem, edited_root)
                edited_paths.add(path)
            
            # Find removed elements
            for path, elem in original_elements.items():
                if path not in edited_paths:
                    changes.append({
                        "type": "remove_element",
                        "xpath": path,
                        "tag": elem.tag
                    })
                    logger.debug(f"   Removed element: {path}")
        
        except Exception as e:
            logger.warning(f"⚠️ Error finding removed elements: {e}")
        
        return changes
    
    def _generate_change_summary(self, changes: List[Dict]) -> str:
        """Generate a human-readable summary of changes"""
        if not changes:
            return "No changes detected"
        
        summary_parts = []
        
        # Count by type
        add_count = len([c for c in changes if c["type"] == "add_element"])
        modify_count = len([c for c in changes if c["type"] == "modify_element"])
        attr_count = len([c for c in changes if c["type"] == "modify_attribute"])
        remove_count = len([c for c in changes if c["type"] == "remove_element"])
        
        if add_count:
            summary_parts.append(f"{add_count} element(s) added")
        if modify_count:
            summary_parts.append(f"{modify_count} element(s) modified")
        if attr_count:
            summary_parts.append(f"{attr_count} attribute(s) modified")
        if remove_count:
            summary_parts.append(f"{remove_count} element(s) removed")
        
        return ", ".join(summary_parts)
    
    def _generate_transformation_rules(self, changes: List[Dict]) -> List[Dict]:
        """
        Generate transformation rules that can be applied to similar XML files
        
        Returns:
            List of transformation rules in a format compatible with correction cache
        """
        rules = []
        
        for change in changes:
            if change["type"] == "add_element":
                rules.append({
                    "action": "add_element",
                    "xpath": change["xpath"],
                    "tag": change["tag"],
                    "text": change.get("text"),
                    "attributes": change.get("attributes", {})
                })
            
            elif change["type"] == "modify_element":
                rules.append({
                    "action": "modify_element",
                    "xpath": change["xpath"],
                    "new_text": change["new_text"]
                })
            
            elif change["type"] == "modify_attribute":
                rules.append({
                    "action": "modify_attribute",
                    "xpath": change["xpath"],
                    "attribute": change["attribute"],
                    "new_value": change["new_value"]
                })
            
            elif change["type"] == "remove_element":
                rules.append({
                    "action": "remove_element",
                    "xpath": change["xpath"]
                })
        
        return rules
    
    def generate_error_signature(self, changes: List[Dict], error_type: str) -> str:
        """
        Generate a unique signature for the type of fix applied
        
        Args:
            changes: List of changes detected
            error_type: The error type that was being fixed
        
        Returns:
            Unique signature string
        """
        # Create a signature based on the changes
        signature_parts = [error_type]
        
        for change in changes[:3]:  # Use first 3 changes for signature
            if change["type"] == "add_element":
                signature_parts.append(f"add:{change['tag']}")
            elif change["type"] == "modify_element":
                signature_parts.append(f"modify:{change['tag']}")
            elif change["type"] == "modify_attribute":
                signature_parts.append(f"attr:{change['attribute']}")
        
        signature_str = "|".join(signature_parts)
        
        # Hash if too long
        if len(signature_str) > 200:
            return hashlib.md5(signature_str.encode()).hexdigest()
        
        return signature_str
    
    def extract_customer_id(self, xml_content: str) -> Optional[str]:
        """Extract customer/supplier ID from XML"""
        try:
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Try UBL format
            namespaces = {
                'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
                'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
            }
            
            # Try to get supplier party ID
            supplier_elem = root.find('.//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID', namespaces)
            if supplier_elem is not None and supplier_elem.text:
                return supplier_elem.text.strip()
            
            # Try SAT CFDI format
            cfdi_namespaces = {
                'cfdi': 'http://www.sat.gob.mx/cfd/4'
            }
            emisor = root.find('.//cfdi:Emisor', cfdi_namespaces)
            if emisor is not None:
                rfc = emisor.get('Rfc')
                if rfc:
                    return rfc
            
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Could not extract customer ID: {e}")
            return None
