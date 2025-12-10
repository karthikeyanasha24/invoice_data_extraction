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
    
    def parse_validation_rules(self, validation_rules: Optional[str]) -> List[str]:
        """
        Parse validation rules JSON string into a list of XPath expressions.
        
        Args:
            validation_rules: JSON string containing validation rules
            
        Returns:
            List of XPath expressions for required fields
            
        Example input:
            {
                "required_fields": [
                    "//cbc:ID",
                    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
                    "//cbc:InvoiceTypeCode"
                ]
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
            
            logger.info(f"Parsed {len(required_fields)} custom required fields from validation rules")
            return required_fields
            
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
        use_defaults: bool = True
    ) -> Tuple[bool, str, List[str]]:
        """
        Validate XML content against customer-specific required fields.
        
        Args:
            xml_content: XML content as string
            validation_rules: JSON string with customer validation rules
            use_defaults: Whether to include default required fields
            
        Returns:
            Tuple of (is_valid, message, missing_fields)
            - is_valid: True if all required fields are present
            - message: Validation result message
            - missing_fields: List of missing field XPaths
        """
        try:
            # Parse XML
            root = etree.fromstring(xml_content.encode('utf-8'))
            logger.info("✅ XML parsed successfully")
            
            # Get required fields
            required_fields = []
            if use_defaults:
                required_fields.extend(self.DEFAULT_REQUIRED_FIELDS)
                logger.info(f"Added {len(self.DEFAULT_REQUIRED_FIELDS)} default required fields")
            
            custom_fields = self.parse_validation_rules(validation_rules)
            required_fields.extend(custom_fields)
            
            if not required_fields:
                logger.info("No required fields to validate")
                return True, "No required fields specified", []
            
            logger.info(f"Validating {len(required_fields)} required fields")
            
            # Validate each required field
            missing_fields = []
            for xpath in required_fields:
                try:
                    # Evaluate XPath
                    elements = root.xpath(xpath, namespaces=self.NAMESPACES)
                    
                    if not elements:
                        logger.warning(f"❌ Missing required field: {xpath}")
                        missing_fields.append(xpath)
                    else:
                        # Check if element has content (not just empty tag)
                        if isinstance(elements[0], etree._Element):
                            text_content = elements[0].text
                            if text_content is None or text_content.strip() == "":
                                logger.warning(f"⚠️ Required field exists but is empty: {xpath}")
                                missing_fields.append(f"{xpath} (empty)")
                        logger.debug(f"✅ Found required field: {xpath}")
                        
                except etree.XPathEvalError as e:
                    logger.error(f"Invalid XPath expression '{xpath}': {e}")
                    missing_fields.append(f"{xpath} (invalid XPath)")
            
            # Determine validation result
            if missing_fields:
                message = f"Validation failed: {len(missing_fields)} required field(s) missing"
                logger.warning(f"⚠️ {message}")
                logger.warning(f"Missing fields: {', '.join(missing_fields)}")
                return False, message, missing_fields
            else:
                message = f"Validation passed: All {len(required_fields)} required fields present"
                logger.info(f"✅ {message}")
                return True, message, []
                
        except etree.XMLSyntaxError as e:
            logger.error(f"XML syntax error: {e}")
            return False, f"XML syntax error: {str(e)}", []
        except Exception as e:
            logger.error(f"Error during validation: {e}")
            return False, f"Validation error: {str(e)}", []
    
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
        validation_rules: Optional[str] = None
    ) -> dict:
        """
        Generate a detailed validation report.
        
        Args:
            xml_content: XML content as string
            validation_rules: JSON string with customer validation rules
            
        Returns:
            Dictionary with validation report
        """
        is_valid, message, missing_fields = self.validate_xml_with_customer_rules(
            xml_content, validation_rules
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
                    "xpath": field,
                    "description": self.get_field_description(field.replace(" (empty)", ""))
                }
                for field in missing_fields
            ]
        }
        
        return report


# Global instance
customer_validation_service = CustomerValidationService()

