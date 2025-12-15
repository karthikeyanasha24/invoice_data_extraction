"""
Direct XML to EDIFACT Converter
Converts UBL XML invoices to proper EDIFACT INVOIC D.96A format
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

logger = logging.getLogger("zodiac-api.xml_to_edifact_direct")


def format_edifact_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to YYMMDD format for EDIFACT"""
    try:
        if not date_str or date_str == "0000-00-00":
            return ""
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%y%m%d")
    except:
        return ""


def format_edifact_datetime(dt: datetime) -> tuple:
    """Format datetime for EDIFACT"""
    date_str = dt.strftime("%y%m%d")
    time_str = dt.strftime("%H%M")
    return date_str, time_str


def format_edifact_amount(amount_str: str, decimals: int = 2) -> str:
    """Format monetary amount for EDIFACT"""
    try:
        amount = float(amount_str)
        return f"{amount:.{decimals}f}"
    except:
        return "0.00"


def escape_edifact_text(text: str) -> str:
    """Escape special EDIFACT characters"""
    if not text:
        return ""
    # Replace special characters that could break EDIFACT format
    text = text.replace("'", "")
    text = text.replace("+", " ")
    text = text.replace(":", " ")
    text = text.replace("?", " ")
    return text.strip()


def extract_party_edifact(root, party_path: str, ns: dict) -> dict:
    """Extract party information for EDIFACT format"""
    party = root.find(party_path, ns)
    if party is not None:
        name_elem = party.find(".//cbc:Name", ns)
        endpoint_elem = party.find(".//cbc:EndpointID", ns)
        
        # Get company ID
        company_id = "UNKNOWN"
        if endpoint_elem is not None and endpoint_elem.text:
            company_id = endpoint_elem.text.strip()
        
        # Get address
        address = party.find("cac:PostalAddress", ns)
        street = city = postal = country = ""
        if address is not None:
            street_elem = address.find("cbc:StreetName", ns)
            city_elem = address.find("cbc:CityName", ns)
            postal_elem = address.find("cbc:PostalZone", ns)
            country_elem = address.find("cac:Country/cbc:IdentificationCode", ns)
            
            street = street_elem.text.strip() if street_elem is not None and street_elem.text else ""
            city = city_elem.text.strip() if city_elem is not None and city_elem.text else ""
            postal = postal_elem.text.strip() if postal_elem is not None and postal_elem.text else ""
            country = country_elem.text.strip() if country_elem is not None and country_elem.text else ""
        
        return {
            'name': escape_edifact_text(name_elem.text) if name_elem is not None and name_elem.text else "UNKNOWN",
            'id': company_id,
            'street': escape_edifact_text(street),
            'city': escape_edifact_text(city),
            'postal': postal,
            'country': country
        }
    
    return {
        'name': "UNKNOWN",
        'id': "UNKNOWN",
        'street': "",
        'city': "",
        'postal': "",
        'country': ""
    }


def convert_xml_to_edifact_direct(xml_content: bytes) -> Optional[str]:
    """
    Convert XML to EDIFACT INVOIC D.96A format directly
    
    EDIFACT Structure:
    - UNB: Interchange header
    - UNH: Message header
    - BGM: Beginning of message
    - DTM: Date/time
    - RFF: Reference
    - NAD: Name and address (supplier, buyer)
    - LIN: Line item
    - UNS: Section control
    - MOA: Monetary amount
    - UNT: Message trailer
    - UNZ: Interchange trailer
    """
    logger.info("🔄 Starting direct XML to EDIFACT conversion")
    
    try:
        # Parse XML
        root = ET.fromstring(xml_content)
        ns = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }
        
        logger.info("✅ XML parsed successfully")
        
        # Extract invoice data
        invoice_id_elem = root.find(".//cbc:ID", ns)
        invoice_date_elem = root.find(".//cbc:IssueDate", ns)
        currency_elem = root.find(".//cbc:DocumentCurrencyCode", ns)
        
        invoice_id = invoice_id_elem.text.strip() if invoice_id_elem is not None and invoice_id_elem.text else "UNKNOWN"
        invoice_date = invoice_date_elem.text.strip() if invoice_date_elem is not None and invoice_date_elem.text else ""
        currency = currency_elem.text.strip() if currency_elem is not None and currency_elem.text else "USD"
        
        # Extract parties
        supplier = extract_party_edifact(root, ".//cac:AccountingSupplierParty/cac:Party", ns)
        buyer = extract_party_edifact(root, ".//cac:AccountingCustomerParty/cac:Party", ns)
        
        # Generate control references
        current_time = datetime.now()
        interchange_ref = invoice_id[:14] if len(invoice_id) >= 14 else invoice_id.ljust(14, '0')
        message_ref = invoice_id[:14] if len(invoice_id) >= 14 else invoice_id.ljust(14, '0')
        
        edifact_date, edifact_time = format_edifact_datetime(current_time)
        formatted_invoice_date = format_edifact_date(invoice_date)
        
        # Build EDIFACT segments
        segments = []
        
        # UNB - Interchange header
        segments.append(
            f"UNB+UNOC:3+{supplier['id']}:14+{buyer['id']}:14+"
            f"{edifact_date}:{edifact_time}+{interchange_ref}'"
        )
        
        # UNH - Message header (INVOIC D.96A)
        segments.append(
            f"UNH+{message_ref}+INVOIC:D:96A:UN'"
        )
        
        # BGM - Beginning of message (380 = Commercial invoice)
        segments.append(
            f"BGM+380+{invoice_id}+9'"
        )
        
        # DTM - Invoice date (137 = Document date)
        if formatted_invoice_date:
            segments.append(
                f"DTM+137:{formatted_invoice_date}:102'"
            )
        
        # RFF - Reference (optional - order reference)
        order_ref_elem = root.find(".//cac:OrderReference/cbc:ID", ns)
        if order_ref_elem is not None and order_ref_elem.text:
            order_ref = escape_edifact_text(order_ref_elem.text.strip())
            segments.append(
                f"RFF+ON:{order_ref}'"
            )
        
        # NAD - Supplier (SU = Supplier)
        segments.append(
            f"NAD+SU+{supplier['id']}::9++{supplier['name']}+{supplier['street']}+"
            f"{supplier['city']}++{supplier['postal']}+{supplier['country']}'"
        )
        
        # NAD - Buyer (BY = Buyer)
        segments.append(
            f"NAD+BY+{buyer['id']}::9++{buyer['name']}+{buyer['street']}+"
            f"{buyer['city']}++{buyer['postal']}+{buyer['country']}'"
        )
        
        # CUX - Currency (if not default)
        if currency and currency != "USD":
            segments.append(
                f"CUX+2:{currency}:4'"
            )
        
        # Process invoice lines
        invoice_lines = root.findall(".//cac:InvoiceLine", ns)
        logger.info(f"📊 Processing {len(invoice_lines)} invoice lines")
        
        for idx, line in enumerate(invoice_lines, 1):
            line_id_elem = line.find("cbc:ID", ns)
            quantity_elem = line.find("cbc:InvoicedQuantity", ns)
            price_elem = line.find(".//cac:Price/cbc:PriceAmount", ns)
            item_name_elem = line.find(".//cac:Item/cbc:Name", ns)
            item_id_elem = line.find(".//cac:Item/cac:SellersItemIdentification/cbc:ID", ns)
            line_amount_elem = line.find("cbc:LineExtensionAmount", ns)
            
            line_id = line_id_elem.text.strip() if line_id_elem is not None and line_id_elem.text else str(idx)
            quantity = quantity_elem.text.strip() if quantity_elem is not None and quantity_elem.text else "1"
            price = format_edifact_amount(price_elem.text) if price_elem is not None and price_elem.text else "0.00"
            item_name = escape_edifact_text(item_name_elem.text) if item_name_elem is not None and item_name_elem.text else ""
            item_id = item_id_elem.text.strip() if item_id_elem is not None and item_id_elem.text else ""
            line_amount = format_edifact_amount(line_amount_elem.text) if line_amount_elem is not None and line_amount_elem.text else "0.00"
            
            # LIN - Line item
            segments.append(
                f"LIN+{line_id}++{item_id}:SA'"
            )
            
            # IMD - Item description (optional)
            if item_name:
                segments.append(
                    f"IMD+F++:::{item_name}'"
                )
            
            # QTY - Quantity (47 = Invoiced quantity)
            segments.append(
                f"QTY+47:{quantity}'"
            )
            
            # MOA - Line amount (203 = Line item amount)
            segments.append(
                f"MOA+203:{line_amount}'"
            )
            
            # PRI - Price details (AAA = Net price)
            segments.append(
                f"PRI+AAA:{price}'"
            )
        
        logger.info(f"✅ Processed {len(invoice_lines)} invoice lines")
        
        # UNS - Section separator (separates detail from summary)
        segments.append(
            "UNS+S'"
        )
        
        # MOA - Total amounts
        total_amount_elem = root.find(".//cac:LegalMonetaryTotal/cbc:PayableAmount", ns)
        tax_amount_elem = root.find(".//cac:TaxTotal/cbc:TaxAmount", ns)
        line_extension_elem = root.find(".//cac:LegalMonetaryTotal/cbc:LineExtensionAmount", ns)
        
        # 79 = Total line items amount
        if line_extension_elem is not None and line_extension_elem.text:
            line_total = format_edifact_amount(line_extension_elem.text)
            segments.append(
                f"MOA+79:{line_total}'"
            )
        
        # 176 = Tax amount
        if tax_amount_elem is not None and tax_amount_elem.text:
            tax_total = format_edifact_amount(tax_amount_elem.text)
            segments.append(
                f"MOA+176:{tax_total}'"
            )
        
        # 86 = Total payable amount
        if total_amount_elem is not None and total_amount_elem.text:
            payable_total = format_edifact_amount(total_amount_elem.text)
            segments.append(
                f"MOA+86:{payable_total}'"
            )
        
        # UNT - Message trailer (count all segments after UNH + UNT itself)
        segment_count = len(segments) - 1 + 1  # All segments after UNB
        segments.append(
            f"UNT+{segment_count}+{message_ref}'"
        )
        
        # UNZ - Interchange trailer (1 message in interchange)
        segments.append(
            f"UNZ+1+{interchange_ref}'"
        )
        
        # Join segments with newline
        edifact_content = "\n".join(segments)
        
        logger.info("✅ EDIFACT conversion completed successfully")
        logger.info(f"📊 Generated {len(segments)} segments")
        logger.info(f"📊 Total content length: {len(edifact_content)} characters")
        
        return edifact_content
        
    except Exception as e:
        logger.error(f"❌ EDIFACT conversion error: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return None

