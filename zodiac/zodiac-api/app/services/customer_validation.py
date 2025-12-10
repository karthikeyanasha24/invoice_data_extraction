"""
Customer-specific XML validation service.

This module handles validation of XML invoices based on customer-specific
required fields defined in the zodiac_customers table.
"""

import json
import logging
from lxml import etree
from typing import Tuple, List, Optional

logger = logging.getLogger("zodiac-api.customer_validation")


class CustomerValidationService:
    """Service for validating XML against customer-specific rules"""
    
    # Default UBL namespaces
    NAMESPACES = {
        'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        'ubl': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    }
    
    # Default required fields (always validated)
    DEFAULT_REQUIRED_FIELDS = [
        "//cbc:ID",  # Invoice ID
        "//cbc:IssueDate",  # Invoice date
        "//cac:AccountingSupplierParty",  # Supplier information
        "//cac:AccountingCustomerParty",  # Customer information
        "//cac:LegalMonetaryTotal/cbc:PayableAmount",  # Total amount
    ]
    
    def __init__(self):
        """Initialize the validation service"""
        pass
    
    def parse_validation_rules(self, validation_rules: Optional[str]) -> List[dict]:
        """
        Parse validation rules JSON string into a list of field configurations.
        
        Args:
            validation_rules: JSON string containing validation rules
            
        Returns:
            List of dicts with xpath and default_value
            
        Example input:
            {
                "required_fields": [
                    {"xpath": "//cbc:ID", "default_value": "INV-DEFAULT"},
                    {"xpath": "//cbc:IssueDate", "default_value": null}
                ]
            }
            
        Or old format (backward compatible):
            {
                "required_fields": ["//cbc:ID", "//cbc:IssueDate"]
            }
        """
        if not validation_rules:
            logger.info("No custom validation rules provided, using defaults only")
            return []
        
        try:
            rules = json.loads(validation_rules)
            required_fields = rules.get("required_fields", [])
            
            if not isinstance(required_fields, list):
                logger.warning(f"Invalid validation rules format: 'required_fields' must be a list")
                return []
            
            # Parse fields - support both old (string) and new (dict) formats
            parsed_fields = []
            for field in required_fields:
                if isinstance(field, str):
                    # Old format - just XPath string
                    parsed_fields.append({"xpath": field, "default_value": None})
                elif isinstance(field, dict) and "xpath" in field:
                    # New format - dict with xpath and default_value
                    parsed_fields.append({
                        "xpath": field["xpath"],
                        "default_value": field.get("default_value")
                    })
                else:
                    logger.warning(f"Invalid field format: {field}")
            
            logger.info(f"Parsed {len(parsed_fields)} custom required fields from validation rules")
            return parsed_fields
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse validation rules JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing validation rules: {e}")
            return []
    
    def validate_xml_with_customer_rules(
        self,
        xml_content: str,
        validation_rules: Optional[str] = None,
        use_defaults: bool = True,
        apply_defaults: bool = False
    ) -> Tuple[bool, str, List[dict], Optional[str]]:
        """
        Validate XML content against customer-specific required fields.
        
        Args:
            xml_content: XML content as string
            validation_rules: JSON string with customer validation rules
            use_defaults: Whether to include default required fields
            apply_defaults: Whether to apply default values to missing fields
            
        Returns:
            Tuple of (is_valid, message, missing_fields, corrected_xml)
            - is_valid: True if all required fields are present or have defaults
            - message: Validation result message
            - missing_fields: List of dicts with field info and default values
            - corrected_xml: XML with defaults applied (if apply_defaults=True)
        """
        try:
            # Parse XML
            root = etree.fromstring(xml_content.encode('utf-8'))
            logger.info("✅ XML parsed successfully")
            
            # Get required fields
            required_fields = []
            if use_defaults:
                # Convert default fields to dict format
                default_field_dicts = [{"xpath": xpath, "default_value": None} for xpath in self.DEFAULT_REQUIRED_FIELDS]
                required_fields.extend(default_field_dicts)
                logger.info(f"Added {len(self.DEFAULT_REQUIRED_FIELDS)} default required fields")
            
            custom_fields = self.parse_validation_rules(validation_rules)
            required_fields.extend(custom_fields)
            
            if not required_fields:
                logger.info("No required fields to validate")
                return True, "No required fields specified", [], None
            
            logger.info(f"Validating {len(required_fields)} required fields")
            
            # Validate each required field
            missing_fields = []
            fields_to_add = []
            
            for field_config in required_fields:
                xpath = field_config["xpath"]
                default_value = field_config.get("default_value")
                
                try:
                    # Evaluate XPath
                    elements = root.xpath(xpath, namespaces=self.NAMESPACES)
                    
                    if not elements:
                        logger.warning(f"❌ Missing required field: {xpath}")
                        missing_fields.append({
                            "xpath": xpath,
                            "default_value": default_value,
                            "reason": "missing"
                        })
                        if default_value and apply_defaults:
                            fields_to_add.append({"xpath": xpath, "value": default_value})
                    else:
                        # Check if element has content (not just empty tag)
                        if isinstance(elements[0], etree._Element):
                            text_content = elements[0].text
                            if text_content is None or text_content.strip() == "":
                                logger.warning(f"⚠️ Required field exists but is empty: {xpath}")
                                missing_fields.append({
                                    "xpath": xpath,
                                    "default_value": default_value,
                                    "reason": "empty"
                                })
                                if default_value and apply_defaults:
                                    # Update existing empty element
                                    elements[0].text = str(default_value)
                        logger.debug(f"✅ Found required field: {xpath}")
                        
                except etree.XPathEvalError as e:
                    logger.error(f"Invalid XPath expression '{xpath}': {e}")
                    missing_fields.append({
                        "xpath": xpath,
                        "default_value": default_value,
                        "reason": "invalid_xpath"
                    })
            
            # Apply defaults by adding missing elements
            corrected_xml = None
            if apply_defaults and fields_to_add:
                logger.info(f"Applying {len(fields_to_add)} default values to missing fields")
                for field_info in fields_to_add:
                    try:
                        self._add_element_to_xml(root, field_info["xpath"], field_info["value"])
                    except Exception as e:
                        logger.error(f"Failed to add field {field_info['xpath']}: {e}")
                
                corrected_xml = etree.tostring(root, encoding='unicode', pretty_print=True)
            
            # Determine validation result
            fields_with_no_default = [f for f in missing_fields if not f.get("default_value")]
            
            if fields_with_no_default:
                message = f"Validation failed: {len(fields_with_no_default)} required field(s) missing without defaults"
                logger.warning(f"⚠️ {message}")
                return False, message, missing_fields, corrected_xml
            elif missing_fields and apply_defaults:
                message = f"Validation passed with defaults: {len(missing_fields)} field(s) corrected"
                logger.info(f"✅ {message}")
                return True, message, missing_fields, corrected_xml
            else:
                message = f"Validation passed: All {len(required_fields)} required fields present"
                logger.info(f"✅ {message}")
                return True, message, [], None
                
        except etree.XMLSyntaxError as e:
            logger.error(f"XML syntax error: {e}")
            return False, f"XML syntax error: {str(e)}", [], None
        except Exception as e:
            logger.error(f"Error during validation: {e}")
            return False, f"Validation error: {str(e)}", [], None
    
    def _add_element_to_xml(self, root: etree._Element, xpath: str, value: str):
        """
        Add a new element to XML based on XPath.
        
        Args:
            root: XML root element
            xpath: XPath expression (e.g., //cbc:ID)
            value: Value to set
        """
        # Extract namespace and element name from XPath
        # Simple implementation - assumes format //prefix:ElementName
        if "//" in xpath and ":" in xpath:
            parts = xpath.replace("//", "").split("/")
            last_part = parts[-1]
            
            if ":" in last_part:
                prefix, element_name = last_part.split(":", 1)
                namespace_uri = self.NAMESPACES.get(prefix)
                
                if namespace_uri:
                    # Create element with namespace
                    new_element = etree.Element(f"{{{namespace_uri}}}{element_name}")
                    new_element.text = str(value)
                    root.append(new_element)
                    logger.info(f"Added element {xpath} with value: {value}")
                else:
                    logger.warning(f"Unknown namespace prefix: {prefix}")
        else:
            logger.warning(f"Cannot parse XPath for adding element: {xpath}")
    
    def get_field_description(self, xpath: str) -> str:
        """
        Get a human-readable description of an XPath field.
        
        Args:
            xpath: XPath expression
            
        Returns:
            Human-readable description
        """
        descriptions = {
            "//cbc:ID": "Invoice ID",
            "//cbc:IssueDate": "Invoice Issue Date",
            "//cbc:DueDate": "Payment Due Date",
            "//cbc:InvoiceTypeCode": "Invoice Type Code",
            "//cac:AccountingSupplierParty": "Supplier Information",
            "//cac:AccountingCustomerParty": "Customer Information",
            "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID": "Supplier Endpoint ID",
            "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID": "Customer Endpoint ID",
            "//cac:LegalMonetaryTotal/cbc:PayableAmount": "Total Payable Amount",
            "//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount": "Tax Inclusive Amount",
            "//cac:InvoiceLine": "Invoice Line Items",
            "//cac:TaxTotal": "Tax Information",
            "//cbc:DocumentCurrencyCode": "Currency Code",
        }
        
        return descriptions.get(xpath, xpath)
    
    def generate_validation_report(
        self,
        xml_content: str,
        validation_rules: Optional[str] = None,
        apply_defaults: bool = False
    ) -> dict:
        """
        Generate a detailed validation report.
        
        Args:
            xml_content: XML content as string
            validation_rules: JSON string with customer validation rules
            apply_defaults: Whether to apply default values
            
        Returns:
            Dictionary with validation report
        """
        is_valid, message, missing_fields, corrected_xml = self.validate_xml_with_customer_rules(
            xml_content, validation_rules, apply_defaults=apply_defaults
        )
        
        # Get custom fields
        custom_fields = self.parse_validation_rules(validation_rules)
        
        report = {
            "is_valid": is_valid,
            "message": message,
            "total_required_fields": len(self.DEFAULT_REQUIRED_FIELDS) + len(custom_fields),
            "default_fields_count": len(self.DEFAULT_REQUIRED_FIELDS),
            "custom_fields_count": len(custom_fields),
            "missing_fields_count": len(missing_fields),
            "missing_fields": [
                {
                    "xpath": field.get("xpath"),
                    "description": self.get_field_description(field.get("xpath", "")),
                    "default_value": field.get("default_value"),
                    "reason": field.get("reason")
                }
                for field in missing_fields
            ],
            "corrected_xml": corrected_xml
        }
        
        return report


# Global instance
customer_validation_service = CustomerValidationService()

