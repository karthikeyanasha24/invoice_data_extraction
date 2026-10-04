"""
UBL 2.1 Invoice Formatter
Validates, cleans, and formats UBL XML for download
"""

import logging
from lxml import etree
from typing import Optional, Tuple

logger = logging.getLogger("zodiac-api.ubl_formatter")

# UBL 2.1 Namespaces
UBL_NAMESPACES = {
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'invoice': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
}


def format_ubl_invoice(xml_content: bytes) -> Tuple[bytes, bool, str]:
    """
    Format and validate UBL 2.1 Invoice XML
    
    Args:
        xml_content: Raw UBL XML content as bytes
        
    Returns:
        Tuple of (formatted_xml_bytes, is_valid, message)
        - formatted_xml_bytes: Pretty-printed XML with proper namespaces
        - is_valid: True if valid UBL structure
        - message: Validation message or error details
    """
    try:
        logger.info("🔍 Validating and formatting UBL 2.1 Invoice...")
        
        # Parse XML
        root = etree.fromstring(xml_content)
        logger.info(f"✅ XML parsed successfully")
        
        # Validate it's an Invoice
        root_tag = etree.QName(root.tag).localname
        if root_tag != "Invoice":
            logger.warning(f"⚠️ Root element is '{root_tag}', expected 'Invoice'")
            return xml_content, False, f"Not a UBL Invoice (root element is '{root_tag}')"
        
        logger.info(f"✅ Root element confirmed: Invoice")
        
        # Check for required namespaces
        namespaces = root.nsmap
        has_cac = any('CommonAggregateComponents' in str(v) for v in namespaces.values() if v)
        has_cbc = any('CommonBasicComponents' in str(v) for v in namespaces.values() if v)
        has_invoice_ns = any('Invoice-2' in str(v) for v in namespaces.values() if v)
        
        if not (has_cac and has_cbc):
            logger.warning("⚠️ Missing required UBL namespaces")
            return xml_content, False, "Missing required UBL 2.1 namespaces (cac, cbc)"
        
        logger.info(f"✅ UBL namespaces present: cac={has_cac}, cbc={has_cbc}, invoice={has_invoice_ns}")
        
        # Validate required elements
        validation_checks = {
            './/cbc:ID': 'Invoice ID',
            './/cbc:IssueDate': 'Issue Date',
            './/cac:AccountingSupplierParty': 'Supplier',
            './/cac:AccountingCustomerParty': 'Customer',
            './/cac:LegalMonetaryTotal': 'Monetary Total',
            './/cac:InvoiceLine': 'Invoice Lines'
        }
        
        missing_elements = []
        for xpath, name in validation_checks.items():
            element = root.find(xpath, UBL_NAMESPACES)
            if element is None:
                missing_elements.append(name)
                logger.warning(f"⚠️ Missing required element: {name}")
            else:
                logger.info(f"✅ Found: {name}")
        
        if missing_elements:
            message = f"UBL validation warning: Missing elements: {', '.join(missing_elements)}"
            logger.warning(message)
        else:
            message = "UBL 2.1 Invoice validated successfully"
            logger.info(f"✅ {message}")
        
        # Get invoice details for logging
        invoice_id = root.find('.//cbc:ID', UBL_NAMESPACES)
        issue_date = root.find('.//cbc:IssueDate', UBL_NAMESPACES)
        currency = root.find('.//cbc:DocumentCurrencyCode', UBL_NAMESPACES)
        line_count = len(root.findall('.//cac:InvoiceLine', UBL_NAMESPACES))
        
        logger.info(f"📊 Invoice Details:")
        if invoice_id is not None and invoice_id.text:
            logger.info(f"   Invoice ID: {invoice_id.text}")
        if issue_date is not None and issue_date.text:
            logger.info(f"   Issue Date: {issue_date.text}")
        if currency is not None and currency.text:
            logger.info(f"   Currency: {currency.text}")
        logger.info(f"   Line Items: {line_count}")
        
        # Pretty print the XML
        formatted_xml = etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        )
        
        logger.info(f"✅ UBL formatting complete: {len(formatted_xml)} bytes")
        
        is_valid = len(missing_elements) == 0
        return formatted_xml, is_valid, message
        
    except etree.XMLSyntaxError as e:
        error_msg = f"Invalid XML syntax: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return xml_content, False, error_msg
        
    except Exception as e:
        error_msg = f"UBL formatting error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        logger.exception(e)
        return xml_content, False, error_msg


def validate_ubl_completeness(xml_content: bytes) -> dict:
    """
    Perform detailed validation of UBL invoice completeness
    
    Returns:
        Dictionary with validation results and statistics
    """
    try:
        root = etree.fromstring(xml_content)
        
        # Count elements
        stats = {
            'invoice_id': None,
            'issue_date': None,
            'due_date': None,
            'currency': None,
            'supplier': None,
            'customer': None,
            'line_items': 0,
            'has_totals': False,
            'has_tax_info': False,
            'has_payment_terms': False,
            'validation_errors': [],
            'validation_warnings': []
        }
        
        # Extract basic info
        invoice_id = root.find('.//cbc:ID', UBL_NAMESPACES)
        if invoice_id is not None and invoice_id.text:
            stats['invoice_id'] = invoice_id.text
        else:
            stats['validation_errors'].append('Missing invoice ID')
        
        issue_date = root.find('.//cbc:IssueDate', UBL_NAMESPACES)
        if issue_date is not None and issue_date.text:
            stats['issue_date'] = issue_date.text
        else:
            stats['validation_errors'].append('Missing issue date')
        
        due_date = root.find('.//cbc:DueDate', UBL_NAMESPACES)
        if due_date is not None and due_date.text:
            stats['due_date'] = due_date.text
        
        currency = root.find('.//cbc:DocumentCurrencyCode', UBL_NAMESPACES)
        if currency is not None and currency.text:
            stats['currency'] = currency.text
        else:
            stats['validation_warnings'].append('Missing currency code')
        
        # Check parties
        supplier = root.find('.//cac:AccountingSupplierParty', UBL_NAMESPACES)
        if supplier is not None:
            supplier_name = supplier.find('.//cac:PartyName/cbc:Name', UBL_NAMESPACES)
            if supplier_name is not None and supplier_name.text:
                stats['supplier'] = supplier_name.text
        else:
            stats['validation_errors'].append('Missing supplier information')
        
        customer = root.find('.//cac:AccountingCustomerParty', UBL_NAMESPACES)
        if customer is not None:
            customer_name = customer.find('.//cac:PartyName/cbc:Name', UBL_NAMESPACES)
            if customer_name is not None and customer_name.text:
                stats['customer'] = customer_name.text
        else:
            stats['validation_errors'].append('Missing customer information')
        
        # Count line items
        lines = root.findall('.//cac:InvoiceLine', UBL_NAMESPACES)
        stats['line_items'] = len(lines)
        if stats['line_items'] == 0:
            stats['validation_errors'].append('No invoice line items found')
        
        # Check for totals
        totals = root.find('.//cac:LegalMonetaryTotal', UBL_NAMESPACES)
        stats['has_totals'] = totals is not None
        if not stats['has_totals']:
            stats['validation_errors'].append('Missing monetary totals')
        
        # Check for tax info
        tax_total = root.find('.//cac:TaxTotal', UBL_NAMESPACES)
        stats['has_tax_info'] = tax_total is not None
        
        # Check for payment terms
        payment_terms = root.find('.//cac:PaymentTerms', UBL_NAMESPACES)
        stats['has_payment_terms'] = payment_terms is not None
        
        stats['is_valid'] = len(stats['validation_errors']) == 0
        stats['is_complete'] = stats['is_valid'] and len(stats['validation_warnings']) == 0
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Validation error: {e}")
        return {
            'is_valid': False,
            'validation_errors': [f"Validation failed: {str(e)}"]
        }
