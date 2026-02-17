"""
UBL to PIDX Converter
Converts UBL 2.1 XML invoices to PIDX (Petroleum Industry Data Exchange) format
"""
import logging
from lxml import etree
from typing import Dict, Optional, List
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger("zodiac-api.xml_to_pidx")

# UBL Namespaces
UBL_NAMESPACES = {
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'invoice': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
}

# PIDX Namespace
PIDX_NAMESPACE = 'http://www.api.org/pidXML'


def convert_ubl_to_pidx(xml_content: bytes, invoice_data: Optional[Dict] = None) -> bytes:
    """
    Convert UBL XML to PIDX format.
    
    Args:
        xml_content: UBL XML content as bytes
        invoice_data: Optional parsed invoice data for reference
    
    Returns:
        PIDX XML content as bytes
    """
    try:
        logger.info("🔄 Converting UBL to PIDX format...")
        
        # Parse UBL XML
        root = etree.fromstring(xml_content)
        
        # Extract data from UBL (or use provided invoice_data)
        pidx_data = _extract_ubl_data(root, invoice_data)
        
        # Build PIDX XML
        pidx_xml = _build_pidx_xml(pidx_data)
        
        # Convert to bytes
        pidx_bytes = etree.tostring(
            pidx_xml,
            xml_declaration=True,
            encoding='UTF-8',
            pretty_print=True
        )
        
        logger.info(f"✅ PIDX conversion successful: {len(pidx_bytes)} bytes")
        return pidx_bytes
        
    except Exception as e:
        logger.error(f"❌ PIDX conversion failed: {e}")
        logger.exception(e)
        raise ValueError(f"PIDX conversion failed: {str(e)}")


def _extract_ubl_data(root: etree._Element, invoice_data: Optional[Dict] = None) -> Dict:
    """Extract relevant data from UBL XML or use provided invoice_data"""
    
    # If invoice_data is provided, use it (preferred)
    if invoice_data:
        logger.info("✅ Using pre-extracted invoice data")
        return invoice_data
    
    # Otherwise, extract from XML
    logger.info("📊 Extracting data from UBL XML...")
    data = {}
    
    # Basic invoice information
    data['invoice_number'] = _get_text(root, './/cbc:ID', UBL_NAMESPACES) or 'INV-000'
    data['issue_date'] = _get_text(root, './/cbc:IssueDate', UBL_NAMESPACES) or datetime.now().strftime('%Y-%m-%d')
    data['due_date'] = _get_text(root, './/cbc:DueDate', UBL_NAMESPACES)
    data['currency'] = _get_text(root, './/cbc:DocumentCurrencyCode', UBL_NAMESPACES) or 'USD'
    data['order_reference'] = _get_text(root, './/cac:OrderReference/cbc:ID', UBL_NAMESPACES)
    
    # Supplier (Seller)
    supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', UBL_NAMESPACES)
    if supplier_party is not None:
        data['supplier_name'] = _get_text_from_elem(supplier_party, './/cac:PartyName/cbc:Name', UBL_NAMESPACES) or 'Unknown Supplier'
        data['supplier_id'] = _get_text_from_elem(supplier_party, './/cac:PartyIdentification/cbc:ID', UBL_NAMESPACES)
        data['supplier_street'] = _get_text_from_elem(supplier_party, './/cac:PostalAddress/cbc:StreetName', UBL_NAMESPACES)
        data['supplier_city'] = _get_text_from_elem(supplier_party, './/cac:PostalAddress/cbc:CityName', UBL_NAMESPACES)
        data['supplier_postal_code'] = _get_text_from_elem(supplier_party, './/cac:PostalAddress/cbc:PostalZone', UBL_NAMESPACES)
        data['supplier_country'] = _get_text_from_elem(supplier_party, './/cac:PostalAddress/cac:Country/cbc:IdentificationCode', UBL_NAMESPACES)
    
    # Customer (Buyer)
    customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', UBL_NAMESPACES)
    if customer_party is not None:
        data['customer_name'] = _get_text_from_elem(customer_party, './/cac:PartyName/cbc:Name', UBL_NAMESPACES) or 'Unknown Customer'
        data['customer_id'] = _get_text_from_elem(customer_party, './/cac:PartyIdentification/cbc:ID', UBL_NAMESPACES)
        data['customer_street'] = _get_text_from_elem(customer_party, './/cac:PostalAddress/cbc:StreetName', UBL_NAMESPACES)
        data['customer_city'] = _get_text_from_elem(customer_party, './/cac:PostalAddress/cbc:CityName', UBL_NAMESPACES)
        data['customer_postal_code'] = _get_text_from_elem(customer_party, './/cac:PostalAddress/cbc:PostalZone', UBL_NAMESPACES)
        data['customer_country'] = _get_text_from_elem(customer_party, './/cac:PostalAddress/cac:Country/cbc:IdentificationCode', UBL_NAMESPACES)
    
    # Monetary totals
    data['tax_exclusive_amount'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount', UBL_NAMESPACES) or Decimal('0')
    data['tax_amount'] = _get_decimal(root, './/cac:TaxTotal/cbc:TaxAmount', UBL_NAMESPACES) or Decimal('0')
    data['payable_amount'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:PayableAmount', UBL_NAMESPACES) or Decimal('0')
    data['total_amount'] = data['payable_amount']  # Alias for compatibility
    
    # Line items
    data['line_items'] = []
    invoice_lines = root.findall('.//cac:InvoiceLine', UBL_NAMESPACES)
    for line in invoice_lines:
        item = {
            'id': _get_text_from_elem(line, './/cbc:ID', UBL_NAMESPACES) or '1',
            'quantity': _get_decimal_from_elem(line, './/cbc:InvoicedQuantity', UBL_NAMESPACES) or Decimal('1'),
            'unit_code': line.find('.//cbc:InvoicedQuantity', UBL_NAMESPACES).get('unitCode', 'EA') if line.find('.//cbc:InvoicedQuantity', UBL_NAMESPACES) is not None else 'EA',
            'item_description': _get_text_from_elem(line, './/cac:Item/cbc:Description', UBL_NAMESPACES),
            'item_name': _get_text_from_elem(line, './/cac:Item/cbc:Name', UBL_NAMESPACES),
            'seller_item_id': _get_text_from_elem(line, './/cac:Item/cac:SellersItemIdentification/cbc:ID', UBL_NAMESPACES),
            'price': _get_decimal_from_elem(line, './/cac:Price/cbc:PriceAmount', UBL_NAMESPACES) or Decimal('0'),
            'line_amount': _get_decimal_from_elem(line, './/cbc:LineExtensionAmount', UBL_NAMESPACES) or Decimal('0'),
            'tax_percent': _get_decimal_from_elem(line, './/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent', UBL_NAMESPACES) or Decimal('0')
        }
        data['line_items'].append(item)
    
    # Payment terms
    payment_terms = root.find('.//cac:PaymentTerms/cbc:Note', UBL_NAMESPACES)
    if payment_terms is not None:
        data['payment_terms'] = payment_terms.text
    
    return data


def _build_pidx_xml(data: Dict) -> etree._Element:
    """Build PIDX XML structure"""
    
    # Create namespace map
    nsmap = {'pidx': PIDX_NAMESPACE}
    
    # Create root element
    root = etree.Element(
        f"{{{PIDX_NAMESPACE}}}Invoice",
        nsmap=nsmap
    )
    
    # Add attributes
    root.set('transactionPurposeIndicator', 'Original')  # Original, Cancellation, Replace, etc.
    root.set('version', '1.2')
    
    # Add InvoiceProperties
    _add_invoice_properties(root, data)
    
    # Add InvoiceDetails
    _add_invoice_details(root, data)
    
    # Add InvoiceSummary
    _add_invoice_summary(root, data)
    
    return root


def _add_invoice_properties(root: etree._Element, data: Dict):
    """Add InvoiceProperties element"""
    properties = etree.SubElement(root, f"{{{PIDX_NAMESPACE}}}InvoiceProperties")
    
    # Invoice Number (required)
    invoice_num = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}InvoiceNumber")
    invoice_num.text = str(data.get('invoice_number', 'INV-000'))
    
    # Invoice Date (required)
    invoice_date = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}InvoiceDate")
    invoice_date.text = data.get('issue_date', datetime.now().strftime('%Y-%m-%d'))
    
    # Seller Partner Information (required)
    _add_partner_info(properties, data, 'Seller')
    
    # Buyer Partner Information (required)
    _add_partner_info(properties, data, 'Buyer')
    
    # Invoice Type Code (optional)
    invoice_type = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}InvoiceTypeCode")
    invoice_type.text = 'Standard'
    
    # Purchase Order Information (optional)
    if data.get('order_reference'):
        po_info = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}PurchaseOrderInformation")
        po_number = etree.SubElement(po_info, f"{{{PIDX_NAMESPACE}}}PurchaseOrderNumber")
        po_number.text = str(data.get('order_reference'))
    
    # Primary Currency (optional)
    currency = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}PrimaryCurrency")
    currency_code = etree.SubElement(currency, f"{{{PIDX_NAMESPACE}}}CurrencyCode")
    currency_code.text = data.get('currency', 'USD')
    
    # Language Code (optional)
    lang_code = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}LanguageCode")
    lang_code.text = 'en'
    
    # Payment Terms (optional)
    if data.get('payment_terms'):
        payment_terms = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}PaymentTerms")
        terms_desc = etree.SubElement(payment_terms, f"{{{PIDX_NAMESPACE}}}TermsDescription")
        terms_desc.text = str(data.get('payment_terms'))
    
    # Due Date (as Service DateTime if available)
    if data.get('due_date'):
        service_dt = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}ServiceDateTime")
        dt_qualifier = etree.SubElement(service_dt, f"{{{PIDX_NAMESPACE}}}DateTimeQualifier")
        dt_qualifier.text = 'DueDate'
        dt_value = etree.SubElement(service_dt, f"{{{PIDX_NAMESPACE}}}DateTime")
        dt_value.text = str(data.get('due_date'))
    
    # Comment (optional)
    if data.get('notes'):
        comment = etree.SubElement(properties, f"{{{PIDX_NAMESPACE}}}Comment")
        comment.text = str(data.get('notes'))


def _add_partner_info(parent: etree._Element, data: Dict, role: str):
    """Add PartnerInformation element for Seller or Buyer"""
    partner_info = etree.SubElement(parent, f"{{{PIDX_NAMESPACE}}}PartnerInformation")
    
    # Partner Role
    partner_role = etree.SubElement(partner_info, f"{{{PIDX_NAMESPACE}}}PartnerRoleCode")
    partner_role.text = role
    
    # Partner Identifier
    partner_id_elem = etree.SubElement(partner_info, f"{{{PIDX_NAMESPACE}}}PartnerIdentifier")
    if role == 'Seller':
        partner_id = data.get('supplier_id') or data.get('supplier_name', 'Unknown')
    else:
        partner_id = data.get('customer_id') or data.get('customer_name', 'Unknown')
    partner_id_elem.text = str(partner_id)[:35]  # Max 35 chars
    
    # Partner Name
    partner_name = etree.SubElement(partner_info, f"{{{PIDX_NAMESPACE}}}PartnerName")
    if role == 'Seller':
        name = data.get('supplier_name', 'Unknown Supplier')
    else:
        name = data.get('customer_name', 'Unknown Customer')
    partner_name.text = name[:70]  # Max 70 chars
    
    # Address
    address = etree.SubElement(partner_info, f"{{{PIDX_NAMESPACE}}}Address")
    
    # Get address data - support both nested dict and flat fields
    if role == 'Seller':
        addr_data = data.get('supplier_address', {})
        street = addr_data.get('street', '') or data.get('supplier_street', '')
        city = addr_data.get('city', '') or data.get('supplier_city', '')
        postal = addr_data.get('postal_zone', '') or data.get('supplier_postal_code', '')
        country = addr_data.get('country', '') or data.get('supplier_country', '')
    else:
        addr_data = data.get('customer_address', {})
        street = addr_data.get('street', '') or data.get('customer_street', '')
        city = addr_data.get('city', '') or data.get('customer_city', '')
        postal = addr_data.get('postal_zone', '') or data.get('customer_postal_code', '')
        country = addr_data.get('country', '') or data.get('customer_country', '')
    
    if street:
        addr_line1 = etree.SubElement(address, f"{{{PIDX_NAMESPACE}}}AddressLine")
        addr_line1.text = street[:55]
    
    # City
    if city:
        city_elem = etree.SubElement(address, f"{{{PIDX_NAMESPACE}}}CityName")
        city_elem.text = city[:35]
    
    # Postal Code
    if postal:
        postal_elem = etree.SubElement(address, f"{{{PIDX_NAMESPACE}}}PostalCode")
        postal_elem.text = postal[:15]
    
    # Country
    if country:
        country_elem = etree.SubElement(address, f"{{{PIDX_NAMESPACE}}}CountryCode")
        country_elem.text = country[:2]


def _add_invoice_details(root: etree._Element, data: Dict):
    """Add InvoiceDetails element with line items"""
    details = etree.SubElement(root, f"{{{PIDX_NAMESPACE}}}InvoiceDetails")
    
    line_items = data.get('line_items', [])
    
    for item in line_items:
        line_item = etree.SubElement(details, f"{{{PIDX_NAMESPACE}}}InvoiceLineItem")
        
        # Line Item Number (required)
        line_num = etree.SubElement(line_item, f"{{{PIDX_NAMESPACE}}}LineItemNumber")
        line_num.text = str(item.get('id', '1'))
        
        # Invoice Quantity (required)
        inv_qty = etree.SubElement(line_item, f"{{{PIDX_NAMESPACE}}}InvoiceQuantity")
        
        qty = etree.SubElement(inv_qty, f"{{{PIDX_NAMESPACE}}}Quantity")
        qty.text = f"{float(item.get('quantity', 1)):.6f}"
        
        uom = etree.SubElement(inv_qty, f"{{{PIDX_NAMESPACE}}}UnitOfMeasureCode")
        uom.text = item.get('unit_code', 'EA')
        
        # Line Item Information (required)
        line_info = etree.SubElement(line_item, f"{{{PIDX_NAMESPACE}}}LineItemInformation")
        
        # Item Description
        description = item.get('item_description') or item.get('item_name', 'Item')
        item_desc = etree.SubElement(line_info, f"{{{PIDX_NAMESPACE}}}ItemDescription")
        item_desc.text = description[:70]
        
        # Buyer Item Number (optional)
        if item.get('seller_item_id'):
            buyer_item = etree.SubElement(line_info, f"{{{PIDX_NAMESPACE}}}BuyerItemNumber")
            buyer_item.text = str(item.get('seller_item_id'))[:35]
        
        # Pricing (optional)
        pricing = etree.SubElement(line_item, f"{{{PIDX_NAMESPACE}}}Pricing")
        
        unit_price = etree.SubElement(pricing, f"{{{PIDX_NAMESPACE}}}UnitPrice")
        monetary_amount = etree.SubElement(unit_price, f"{{{PIDX_NAMESPACE}}}MonetaryAmount")
        monetary_amount.text = f"{float(item.get('price', 0)):.2f}"
        
        pricing_uom = etree.SubElement(unit_price, f"{{{PIDX_NAMESPACE}}}UnitOfMeasureCode")
        pricing_uom.text = item.get('unit_code', 'EA')
        
        # Tax (optional)
        if item.get('tax_percent'):
            tax = etree.SubElement(line_item, f"{{{PIDX_NAMESPACE}}}Tax")
            
            tax_type = etree.SubElement(tax, f"{{{PIDX_NAMESPACE}}}TaxTypeCode")
            tax_type.text = 'SalesTax'
            
            tax_rate = etree.SubElement(tax, f"{{{PIDX_NAMESPACE}}}TaxRate")
            tax_rate.text = f"{float(item.get('tax_percent', 0)):.2f}"
            
            # Calculate tax amount
            line_amt = float(item.get('line_amount', 0))
            tax_pct = float(item.get('tax_percent', 0))
            tax_amt = (line_amt * tax_pct) / 100
            
            tax_amount_elem = etree.SubElement(tax, f"{{{PIDX_NAMESPACE}}}TaxAmount")
            tax_amount_elem.text = f"{tax_amt:.2f}"
        
        # Line Item Total (optional)
        line_total = etree.SubElement(line_item, f"{{{PIDX_NAMESPACE}}}LineItemTotal")
        line_total.text = f"{float(item.get('line_amount', 0)):.2f}"


def _add_invoice_summary(root: etree._Element, data: Dict):
    """Add InvoiceSummary element"""
    summary = etree.SubElement(root, f"{{{PIDX_NAMESPACE}}}InvoiceSummary")
    
    # Total Line Items (required)
    total_lines = etree.SubElement(summary, f"{{{PIDX_NAMESPACE}}}TotalLineItems")
    line_items = data.get('line_items', [])
    total_lines.text = str(len(line_items))
    
    # Invoice Total (required) - try multiple field names
    total = data.get('payable_amount') or data.get('total_amount') or 0
    invoice_total = etree.SubElement(summary, f"{{{PIDX_NAMESPACE}}}InvoiceTotal")
    invoice_total.text = f"{float(total):.2f}"
    
    # SubTotal Amount (optional) - try multiple field names
    subtotal_amt = data.get('subtotal') or data.get('tax_exclusive_amount')
    if subtotal_amt:
        subtotal = etree.SubElement(summary, f"{{{PIDX_NAMESPACE}}}SubTotalAmount")
        subtotal_type = etree.SubElement(subtotal, f"{{{PIDX_NAMESPACE}}}SubTotalAmountTypeCode")
        subtotal_type.text = 'GoodsAndServices'
        subtotal_value = etree.SubElement(subtotal, f"{{{PIDX_NAMESPACE}}}MonetaryAmount")
        subtotal_value.text = f"{float(subtotal_amt):.2f}"
    
    # Tax (optional)
    if data.get('tax_amount'):
        tax = etree.SubElement(summary, f"{{{PIDX_NAMESPACE}}}Tax")
        
        tax_type = etree.SubElement(tax, f"{{{PIDX_NAMESPACE}}}TaxTypeCode")
        tax_type.text = 'SalesTax'
        
        tax_amount_elem = etree.SubElement(tax, f"{{{PIDX_NAMESPACE}}}TaxAmount")
        tax_amount_elem.text = f"{float(data.get('tax_amount', 0)):.2f}"


# Helper functions
def _get_text(root: etree._Element, xpath: str, namespaces: Dict) -> Optional[str]:
    """Get text content from XPath"""
    elem = root.find(xpath, namespaces)
    return elem.text if elem is not None and elem.text else None


def _get_text_from_elem(elem: etree._Element, xpath: str, namespaces: Dict) -> Optional[str]:
    """Get text content from XPath relative to element"""
    child = elem.find(xpath, namespaces)
    return child.text if child is not None and child.text else None


def _get_decimal(root: etree._Element, xpath: str, namespaces: Dict) -> Optional[Decimal]:
    """Get decimal value from XPath"""
    text = _get_text(root, xpath, namespaces)
    if text:
        try:
            return Decimal(text)
        except:
            return None
    return None


def _get_decimal_from_elem(elem: etree._Element, xpath: str, namespaces: Dict) -> Optional[Decimal]:
    """Get decimal value from XPath relative to element"""
    text = _get_text_from_elem(elem, xpath, namespaces)
    if text:
        try:
            return Decimal(text)
        except:
            return None
    return None
