"""
UBL to CFDI Converter
Converts UBL 2.1 XML invoices to Mexican CFDI 4.0 format
"""
import logging
from lxml import etree
from typing import Dict, Optional, List
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger("zodiac-api.xml_to_cfdi")

# UBL Namespaces
UBL_NAMESPACES = {
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'invoice': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
}

# CFDI Namespaces
CFDI_NAMESPACES = {
    'cfdi': 'http://www.sat.gob.mx/cfd/4',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
}


def convert_ubl_to_cfdi(xml_content: bytes, invoice_data: Optional[Dict] = None) -> bytes:
    """
    Convert UBL XML to CFDI 4.0 format.
    
    Args:
        xml_content: UBL XML content as bytes
        invoice_data: Optional parsed invoice data for reference
    
    Returns:
        CFDI XML content as bytes
    """
    try:
        logger.info("🔄 Converting UBL to CFDI format...")
        
        # Parse UBL XML
        root = etree.fromstring(xml_content)
        
        # Extract data from UBL
        cfdi_data = _extract_ubl_data(root, invoice_data)
        
        # Build CFDI XML
        cfdi_xml = _build_cfdi_xml(cfdi_data)
        
        # Convert to bytes
        cfdi_bytes = etree.tostring(
            cfdi_xml,
            xml_declaration=True,
            encoding='UTF-8',
            pretty_print=True
        )
        
        logger.info(f"✅ CFDI conversion successful: {len(cfdi_bytes)} bytes")
        return cfdi_bytes
        
    except Exception as e:
        logger.error(f"❌ CFDI conversion failed: {e}")
        logger.exception(e)
        raise ValueError(f"CFDI conversion failed: {str(e)}")


def _extract_ubl_data(root: etree._Element, invoice_data: Optional[Dict] = None) -> Dict:
    """Extract relevant data from UBL XML"""
    data = {}
    
    # Basic invoice information
    data['invoice_number'] = _get_text(root, './/cbc:ID', UBL_NAMESPACES) or 'INV-000'
    data['issue_date'] = _get_text(root, './/cbc:IssueDate', UBL_NAMESPACES) or datetime.now().strftime('%Y-%m-%d')
    data['due_date'] = _get_text(root, './/cbc:DueDate', UBL_NAMESPACES)
    data['invoice_type_code'] = _get_text(root, './/cbc:InvoiceTypeCode', UBL_NAMESPACES) or '380'
    data['note'] = _get_text(root, './/cbc:Note', UBL_NAMESPACES)
    data['currency'] = _get_text(root, './/cbc:DocumentCurrencyCode', UBL_NAMESPACES) or 'MXN'
    
    # Monetary totals
    data['line_extension_amount'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:LineExtensionAmount', UBL_NAMESPACES) or Decimal('0')
    data['tax_exclusive_amount'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount', UBL_NAMESPACES) or Decimal('0')
    data['tax_inclusive_amount'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount', UBL_NAMESPACES) or Decimal('0')
    data['allowance_total'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:AllowanceTotalAmount', UBL_NAMESPACES) or Decimal('0')
    data['payable_amount'] = _get_decimal(root, './/cac:LegalMonetaryTotal/cbc:PayableAmount', UBL_NAMESPACES) or Decimal('0')
    
    # Tax information
    tax_total_elem = root.find('.//cac:TaxTotal', UBL_NAMESPACES)
    if tax_total_elem is not None:
        data['tax_amount'] = _get_decimal_from_elem(tax_total_elem, './/cbc:TaxAmount', UBL_NAMESPACES) or Decimal('0')
        data['taxable_amount'] = _get_decimal_from_elem(tax_total_elem, './/cac:TaxSubtotal/cbc:TaxableAmount', UBL_NAMESPACES) or Decimal('0')
        data['tax_percent'] = _get_decimal_from_elem(tax_total_elem, './/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent', UBL_NAMESPACES) or Decimal('15')
        data['tax_id'] = _get_text_from_elem(tax_total_elem, './/cac:TaxSubtotal/cac:TaxCategory/cac:TaxScheme/cbc:ID', UBL_NAMESPACES) or 'VAT'
    else:
        data['tax_amount'] = Decimal('0')
        data['taxable_amount'] = data['tax_exclusive_amount']
        data['tax_percent'] = Decimal('15')
        data['tax_id'] = 'VAT'
    
    # Supplier (Emisor)
    supplier_elem = root.find('.//cac:AccountingSupplierParty/cac:Party', UBL_NAMESPACES)
    if supplier_elem is not None:
        data['supplier'] = _extract_party_data(supplier_elem, 'supplier')
    else:
        data['supplier'] = _get_default_party('supplier')
    
    # Customer (Receptor)
    customer_elem = root.find('.//cac:AccountingCustomerParty/cac:Party', UBL_NAMESPACES)
    if customer_elem is not None:
        data['customer'] = _extract_party_data(customer_elem, 'customer')
    else:
        data['customer'] = _get_default_party('customer')
    
    # Payment information
    payment_means_elem = root.find('.//cac:PaymentMeans', UBL_NAMESPACES)
    if payment_means_elem is not None:
        data['payment_means_code'] = _get_text_from_elem(payment_means_elem, './/cbc:PaymentMeansCode', UBL_NAMESPACES) or '99'
    else:
        data['payment_means_code'] = '99'
    
    # Line items
    data['line_items'] = _extract_line_items(root)
    
    # Allowances/Charges at document level
    data['allowances'] = _extract_allowances(root)
    
    return data


def _extract_party_data(party_elem: etree._Element, party_type: str) -> Dict:
    """Extract party (supplier/customer) data from UBL"""
    party = {}
    
    # Party identification
    party['id'] = _get_text_from_elem(party_elem, './/cac:PartyIdentification/cbc:ID', UBL_NAMESPACES) or 'XAXX010101000'
    party['name'] = _get_text_from_elem(party_elem, './/cac:PartyName/cbc:Name', UBL_NAMESPACES) or 'Unknown'
    party['legal_name'] = _get_text_from_elem(party_elem, './/cac:PartyLegalEntity/cbc:RegistrationName', UBL_NAMESPACES) or party['name']
    
    # Address
    postal_addr = party_elem.find('.//cac:PostalAddress', UBL_NAMESPACES)
    if postal_addr is not None:
        party['street'] = _get_text_from_elem(postal_addr, './/cbc:StreetName', UBL_NAMESPACES) or ''
        party['city'] = _get_text_from_elem(postal_addr, './/cbc:CityName', UBL_NAMESPACES) or ''
        party['postal_code'] = _get_text_from_elem(postal_addr, './/cbc:PostalZone', UBL_NAMESPACES) or '00000'
        party['country'] = _get_text_from_elem(postal_addr, './/cac:Country/cbc:IdentificationCode', UBL_NAMESPACES) or 'MX'
    else:
        party['street'] = ''
        party['city'] = ''
        party['postal_code'] = '00000'
        party['country'] = 'MX'
    
    # Tax information
    tax_scheme = party_elem.find('.//cac:PartyTaxScheme', UBL_NAMESPACES)
    if tax_scheme is not None:
        party['tax_id'] = _get_text_from_elem(tax_scheme, './/cbc:CompanyID', UBL_NAMESPACES) or 'XAXX010101000'
        party['tax_scheme_id'] = _get_text_from_elem(tax_scheme, './/cac:TaxScheme/cbc:ID', UBL_NAMESPACES) or 'VAT'
    else:
        party['tax_id'] = 'XAXX010101000'
        party['tax_scheme_id'] = 'VAT'
    
    return party


def _get_default_party(party_type: str) -> Dict:
    """Get default party data"""
    return {
        'id': 'XAXX010101000',
        'name': f'Default {party_type.title()}',
        'legal_name': f'Default {party_type.title()}',
        'street': 'Unknown Street',
        'city': 'Unknown City',
        'postal_code': '00000',
        'country': 'MX',
        'tax_id': 'XAXX010101000',
        'tax_scheme_id': 'VAT'
    }


def _extract_line_items(root: etree._Element) -> List[Dict]:
    """Extract line items from UBL"""
    items = []
    
    line_items = root.findall('.//cac:InvoiceLine', UBL_NAMESPACES)
    
    for line in line_items:
        item = {}
        
        item['id'] = _get_text_from_elem(line, './/cbc:ID', UBL_NAMESPACES) or '1'
        item['quantity'] = _get_decimal_from_elem(line, './/cbc:InvoicedQuantity', UBL_NAMESPACES) or Decimal('1')
        item['unit_code'] = line.find('.//cbc:InvoicedQuantity', UBL_NAMESPACES).get('unitCode', 'E48') if line.find('.//cbc:InvoicedQuantity', UBL_NAMESPACES) is not None else 'E48'
        item['description'] = _get_text_from_elem(line, './/cac:Item/cbc:Description', UBL_NAMESPACES) or 'Item'
        item['name'] = _get_text_from_elem(line, './/cac:Item/cbc:Name', UBL_NAMESPACES) or item['description']
        item['line_extension_amount'] = _get_decimal_from_elem(line, './/cbc:LineExtensionAmount', UBL_NAMESPACES) or Decimal('0')
        item['price'] = _get_decimal_from_elem(line, './/cac:Price/cbc:PriceAmount', UBL_NAMESPACES) or Decimal('0')
        
        # Tax information for line item
        tax_category = line.find('.//cac:Item/cac:ClassifiedTaxCategory', UBL_NAMESPACES)
        if tax_category is not None:
            item['tax_id'] = _get_text_from_elem(tax_category, './/cbc:ID', UBL_NAMESPACES) or 'S'
            item['tax_percent'] = _get_decimal_from_elem(tax_category, './/cbc:Percent', UBL_NAMESPACES) or Decimal('15')
        else:
            item['tax_id'] = 'S'
            item['tax_percent'] = Decimal('15')
        
        # Product codes
        item['standard_item_id'] = _get_text_from_elem(line, './/cac:Item/cac:StandardItemIdentification/cbc:ID', UBL_NAMESPACES) or '01010101'
        item['sellers_item_id'] = _get_text_from_elem(line, './/cac:Item/cac:SellersItemIdentification/cbc:ID', UBL_NAMESPACES)
        
        items.append(item)
    
    return items


def _extract_allowances(root: etree._Element) -> List[Dict]:
    """Extract document-level allowances/charges"""
    allowances = []
    
    allowance_elems = root.findall('.//cac:AllowanceCharge', UBL_NAMESPACES)
    
    for allowance_elem in allowance_elems:
        charge_indicator = _get_text_from_elem(allowance_elem, './/cbc:ChargeIndicator', UBL_NAMESPACES)
        
        # Only handle allowances (not charges) for now
        if charge_indicator and charge_indicator.lower() == 'false':
            allowance = {}
            allowance['amount'] = _get_decimal_from_elem(allowance_elem, './/cbc:Amount', UBL_NAMESPACES) or Decimal('0')
            allowance['reason'] = _get_text_from_elem(allowance_elem, './/cbc:AllowanceChargeReason', UBL_NAMESPACES) or 'Discount'
            allowance['reason_code'] = _get_text_from_elem(allowance_elem, './/cbc:AllowanceChargeReasonCode', UBL_NAMESPACES) or '00'
            
            # Tax for allowance
            tax_category = allowance_elem.find('.//cac:TaxCategory', UBL_NAMESPACES)
            if tax_category is not None:
                allowance['tax_percent'] = _get_decimal_from_elem(tax_category, './/cbc:Percent', UBL_NAMESPACES) or Decimal('15')
            else:
                allowance['tax_percent'] = Decimal('15')
            
            allowances.append(allowance)
    
    return allowances


def _build_cfdi_xml(data: Dict) -> etree._Element:
    """Build CFDI 4.0 XML structure"""
    
    # Create root element with namespaces
    nsmap = {
        'cfdi': CFDI_NAMESPACES['cfdi'],
        'xsi': CFDI_NAMESPACES['xsi']
    }
    
    root = etree.Element(
        f"{{{CFDI_NAMESPACES['cfdi']}}}Comprobante",
        nsmap=nsmap
    )
    
    # Add schema location
    root.set(
        f"{{{CFDI_NAMESPACES['xsi']}}}schemaLocation",
        "http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    )
    
    # Root attributes
    root.set("Version", "4.0")
    
    # Parse invoice number to Serie and Folio
    invoice_number = data.get('invoice_number', 'INV-000')
    serie, folio = _parse_invoice_number(invoice_number)
    
    if serie:
        root.set("Serie", serie)
    if folio:
        root.set("Folio", folio)
    
    # Date and time (CFDI requires ISO format with timezone)
    issue_date = data.get('issue_date', datetime.now().strftime('%Y-%m-%d'))
    root.set("Fecha", f"{issue_date}T12:00:00")
    
    # Payment method
    payment_means_code = data.get('payment_means_code', '99')
    forma_pago = _map_ubl_payment_to_cfdi(payment_means_code)
    root.set("FormaPago", forma_pago)
    
    # Amounts
    subtotal = data.get('tax_exclusive_amount', Decimal('0'))
    total = data.get('payable_amount', Decimal('0'))
    
    root.set("SubTotal", f"{subtotal:.2f}")
    root.set("Total", f"{total:.2f}")
    
    # Currency
    currency = data.get('currency', 'MXN')
    # Map currency codes
    currency_map = {'NZD': 'MXN', 'USD': 'USD', 'EUR': 'EUR'}
    cfdi_currency = currency_map.get(currency, currency)
    root.set("Moneda", cfdi_currency)
    
    # Document type (always Invoice for now)
    root.set("TipoDeComprobante", "I")  # I = Ingreso (Invoice)
    
    # Payment method (PUE = Pago en una sola exhibición, PPD = Pago en parcialidades o diferido)
    root.set("MetodoPago", "PUE")
    
    # Place of issuance (use supplier postal code)
    supplier_postal = data.get('supplier', {}).get('postal_code', '00000')
    root.set("LugarExpedicion", supplier_postal)
    
    # Export indicator (01 = No aplica)
    root.set("Exportacion", "01")
    
    # Add Emisor (Supplier)
    _add_emisor(root, data.get('supplier', {}))
    
    # Add Receptor (Customer)
    _add_receptor(root, data.get('customer', {}))
    
    # Add Conceptos (Line Items)
    _add_conceptos(root, data)
    
    # Add Impuestos (Taxes)
    _add_impuestos(root, data)
    
    return root


def _parse_invoice_number(invoice_number: str) -> tuple:
    """Parse invoice number into Serie and Folio"""
    # Try to split by common separators
    for sep in ['-', '_', '/']:
        if sep in invoice_number:
            parts = invoice_number.split(sep, 1)
            return parts[0], parts[1]
    
    # If no separator, treat the whole thing as folio
    return None, invoice_number


def _map_ubl_payment_to_cfdi(ubl_code: str) -> str:
    """Map UBL payment means code to CFDI FormaPago"""
    mapping = {
        '30': '03',  # Credit transfer -> Transferencia electrónica
        '31': '04',  # Debit transfer -> Tarjeta de crédito
        '48': '01',  # Bank card -> Efectivo
        '49': '28',  # Direct debit -> Tarjeta de débito
    }
    return mapping.get(ubl_code, '99')  # 99 = Por definir


def _add_emisor(root: etree._Element, supplier: Dict):
    """Add Emisor (Supplier) element"""
    emisor = etree.SubElement(root, f"{{{CFDI_NAMESPACES['cfdi']}}}Emisor")
    
    # RFC (Tax ID) - required
    rfc = supplier.get('tax_id', 'XAXX010101000')
    # Clean RFC (remove special characters, ensure uppercase)
    rfc = ''.join(c for c in rfc if c.isalnum()).upper()[:13]
    if not rfc or len(rfc) < 12:
        rfc = 'XAXX010101000'  # Generic RFC for foreign entities
    emisor.set("Rfc", rfc)
    
    # Name
    name = supplier.get('legal_name') or supplier.get('name', 'Unknown Supplier')
    emisor.set("Nombre", name[:254])  # Max 254 chars
    
    # Tax regime (601 = General de Ley Personas Morales)
    emisor.set("RegimenFiscal", "601")


def _add_receptor(root: etree._Element, customer: Dict):
    """Add Receptor (Customer) element"""
    receptor = etree.SubElement(root, f"{{{CFDI_NAMESPACES['cfdi']}}}Receptor")
    
    # RFC (Tax ID) - required
    rfc = customer.get('tax_id', 'XAXX010101000')
    # Clean RFC
    rfc = ''.join(c for c in rfc if c.isalnum()).upper()[:13]
    if not rfc or len(rfc) < 12:
        rfc = 'XEXX010101000'  # Generic RFC for foreign customers
    receptor.set("Rfc", rfc)
    
    # Name
    name = customer.get('legal_name') or customer.get('name', 'Unknown Customer')
    receptor.set("Nombre", name[:254])
    
    # Fiscal domicile (postal code)
    postal_code = customer.get('postal_code', '00000')
    receptor.set("DomicilioFiscalReceptor", postal_code)
    
    # Tax regime
    receptor.set("RegimenFiscalReceptor", "601")
    
    # UsoCFDI (G03 = Gastos en general)
    receptor.set("UsoCFDI", "G03")


def _add_conceptos(root: etree._Element, data: Dict):
    """Add Conceptos (Line Items) element"""
    conceptos = etree.SubElement(root, f"{{{CFDI_NAMESPACES['cfdi']}}}Conceptos")
    
    line_items = data.get('line_items', [])
    
    for item in line_items:
        concepto = etree.SubElement(conceptos, f"{{{CFDI_NAMESPACES['cfdi']}}}Concepto")
        
        # Product/Service code (required) - Use SAT catalog
        prod_code = item.get('standard_item_id', '01010101')
        concepto.set("ClaveProdServ", prod_code[:10])
        
        # Quantity
        quantity = item.get('quantity', Decimal('1'))
        concepto.set("Cantidad", f"{quantity:.6f}")
        
        # Unit code (ClaveUnidad from SAT catalog)
        unit_code = item.get('unit_code', 'E48')
        # Map common UBL unit codes to CFDI
        unit_map = {
            'E99': 'E48',  # Piece -> Unidad de servicio
            'DAY': 'E48',  # Day -> Unidad de servicio
            'M66': 'E48',  # Other -> Unidad de servicio
        }
        cfdi_unit = unit_map.get(unit_code, unit_code)
        concepto.set("ClaveUnidad", cfdi_unit)
        
        # Unit description (optional)
        concepto.set("Unidad", "Unidad")
        
        # Description
        description = item.get('description') or item.get('name', 'Item')
        concepto.set("Descripcion", description[:1000])
        
        # Unit price
        price = item.get('price', Decimal('0'))
        concepto.set("ValorUnitario", f"{price:.6f}")
        
        # Total amount
        amount = item.get('line_extension_amount', Decimal('0'))
        concepto.set("Importe", f"{amount:.2f}")
        
        # Tax object (02 = Sí objeto de impuesto)
        concepto.set("ObjetoImp", "02")
        
        # Add taxes for this line item
        _add_concepto_impuestos(concepto, item, amount)


def _add_concepto_impuestos(concepto: etree._Element, item: Dict, base_amount: Decimal):
    """Add tax information to a concepto (line item)"""
    impuestos = etree.SubElement(concepto, f"{{{CFDI_NAMESPACES['cfdi']}}}Impuestos")
    
    # Traslados (Transferred taxes - like VAT/IVA)
    traslados = etree.SubElement(impuestos, f"{{{CFDI_NAMESPACES['cfdi']}}}Traslados")
    traslado = etree.SubElement(traslados, f"{{{CFDI_NAMESPACES['cfdi']}}}Traslado")
    
    # Base (taxable amount)
    traslado.set("Base", f"{base_amount:.2f}")
    
    # Tax code (002 = IVA, 001 = ISR)
    traslado.set("Impuesto", "002")  # IVA (VAT equivalent)
    
    # Factor type (Tasa = rate)
    traslado.set("TipoFactor", "Tasa")
    
    # Tax rate
    tax_percent = item.get('tax_percent', Decimal('15'))
    tax_rate = tax_percent / Decimal('100')
    traslado.set("TasaOCuota", f"{tax_rate:.6f}")
    
    # Tax amount
    tax_amount = base_amount * tax_rate
    traslado.set("Importe", f"{tax_amount:.2f}")


def _add_impuestos(root: etree._Element, data: Dict):
    """Add document-level Impuestos (Taxes) element"""
    impuestos = etree.SubElement(root, f"{{{CFDI_NAMESPACES['cfdi']}}}Impuestos")
    
    # Total transferred taxes
    tax_amount = data.get('tax_amount', Decimal('0'))
    if tax_amount > 0:
        impuestos.set("TotalImpuestosTrasladados", f"{tax_amount:.2f}")
    
    # Traslados (summary of transferred taxes)
    traslados = etree.SubElement(impuestos, f"{{{CFDI_NAMESPACES['cfdi']}}}Traslados")
    traslado = etree.SubElement(traslados, f"{{{CFDI_NAMESPACES['cfdi']}}}Traslado")
    
    # Base amount
    taxable_amount = data.get('taxable_amount', data.get('tax_exclusive_amount', Decimal('0')))
    traslado.set("Base", f"{taxable_amount:.2f}")
    
    # Tax code (002 = IVA)
    traslado.set("Impuesto", "002")
    
    # Factor type
    traslado.set("TipoFactor", "Tasa")
    
    # Tax rate
    tax_percent = data.get('tax_percent', Decimal('15'))
    tax_rate = tax_percent / Decimal('100')
    traslado.set("TasaOCuota", f"{tax_rate:.6f}")
    
    # Tax amount
    traslado.set("Importe", f"{tax_amount:.2f}")


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
