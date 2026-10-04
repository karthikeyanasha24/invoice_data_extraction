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


def convert_xml_to_edifact_direct(xml_content: bytes, invoice_data: dict = None) -> Optional[str]:
    """
    Convert XML to EDIFACT INVOIC D.96A format directly.
    Uses extracted invoice_data for comprehensive field coverage.
    
    EDIFACT Structure:
    - UNB: Interchange header
    - UNH: Message header
    - BGM: Beginning of message
    - DTM: Date/time/periods
    - RFF: References
    - NAD: Name and address (supplier, buyer, delivery, etc.)
    - CTA/COM: Contact information
    - PAI: Payment instructions
    - FII: Financial institution
    - PAT/PCD: Payment terms
    - ALC: Allowances/charges
    - LIN: Line item
    - TAX: Tax information
    - UNS: Section control
    - MOA: Monetary amounts
    - UNT: Message trailer
    - UNZ: Interchange trailer
    """
    logger.info("🔄 Starting comprehensive XML to EDIFACT conversion")
    if invoice_data:
        logger.info(f"📊 Using extracted invoice data with {len(invoice_data)} fields")
    
    try:
        # Parse XML for structure
        root = ET.fromstring(xml_content)
        ns = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }
        
        logger.info("✅ XML parsed successfully")
        
        # Use invoice_data if available, otherwise parse from XML
        if invoice_data:
            invoice_id = invoice_data.get("invoice_number", "UNKNOWN")
            invoice_date = invoice_data.get("issue_date", "")
            currency = invoice_data.get("currency", "USD")
            
            # Supplier info from extracted data
            supplier = {
                'name': escape_edifact_text(invoice_data.get("supplier_name", "UNKNOWN")),
                'id': invoice_data.get("supplier_id", "UNKNOWN"),
                'street': escape_edifact_text(invoice_data.get("supplier_street", "")),
                'city': escape_edifact_text(invoice_data.get("supplier_city", "")),
                'postal': invoice_data.get("supplier_postal_code", ""),
                'country': invoice_data.get("supplier_country", ""),
                'tax_id': invoice_data.get("supplier_tax_id", ""),
                'registration_name': escape_edifact_text(invoice_data.get("supplier_registration_name", "")),
                'contact_name': escape_edifact_text(invoice_data.get("supplier_contact_name", "")),
                'contact_phone': escape_edifact_text(invoice_data.get("supplier_contact_phone", "")),
                'contact_email': escape_edifact_text(invoice_data.get("supplier_contact_email", ""))
            }
            
            # Buyer info from extracted data
            buyer = {
                'name': escape_edifact_text(invoice_data.get("customer_name", "UNKNOWN")),
                'id': invoice_data.get("customer_id", "UNKNOWN"),
                'street': escape_edifact_text(invoice_data.get("customer_street", "")),
                'city': escape_edifact_text(invoice_data.get("customer_city", "")),
                'postal': invoice_data.get("customer_postal_code", ""),
                'country': invoice_data.get("customer_country", ""),
                'tax_id': invoice_data.get("customer_tax_id", ""),
                'registration_name': escape_edifact_text(invoice_data.get("customer_registration_name", "")),
                'contact_name': escape_edifact_text(invoice_data.get("customer_contact_name", "")),
                'contact_phone': escape_edifact_text(invoice_data.get("customer_contact_phone", "")),
                'contact_email': escape_edifact_text(invoice_data.get("customer_contact_email", ""))
            }
        else:
            # Fallback to XML parsing
            invoice_id_elem = root.find(".//cbc:ID", ns)
            invoice_date_elem = root.find(".//cbc:IssueDate", ns)
            currency_elem = root.find(".//cbc:DocumentCurrencyCode", ns)
            
            invoice_id = invoice_id_elem.text.strip() if invoice_id_elem is not None and invoice_id_elem.text else "UNKNOWN"
            invoice_date = invoice_date_elem.text.strip() if invoice_date_elem is not None and invoice_date_elem.text else ""
            currency = currency_elem.text.strip() if currency_elem is not None and currency_elem.text else "USD"
            
            # Extract parties from XML
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
        
        # DTM - Due date (13 = Payment due date)
        if invoice_data and invoice_data.get("due_date"):
            formatted_due_date = format_edifact_date(invoice_data.get("due_date"))
            if formatted_due_date:
                segments.append(f"DTM+13:{formatted_due_date}:102'")
        
        # DTM - Delivery date (35 = Actual delivery date)
        if invoice_data and invoice_data.get("delivery_date"):
            formatted_delivery_date = format_edifact_date(invoice_data.get("delivery_date"))
            if formatted_delivery_date:
                segments.append(f"DTM+35:{formatted_delivery_date}:102'")
        
        # RFF - References (use invoice_data if available)
        if invoice_data:
            # Order reference
            if invoice_data.get("order_reference"):
                segments.append(f"RFF+ON:{escape_edifact_text(invoice_data.get('order_reference'))}'")
            # Sales order ID
            if invoice_data.get("sales_order_id"):
                segments.append(f"RFF+VN:{escape_edifact_text(invoice_data.get('sales_order_id'))}'")
            # Buyer reference
            if invoice_data.get("buyer_reference"):
                segments.append(f"RFF+CR:{escape_edifact_text(invoice_data.get('buyer_reference'))}'")
            # Contract reference
            if invoice_data.get("contract_reference"):
                segments.append(f"RFF+CT:{escape_edifact_text(invoice_data.get('contract_reference'))}'")
            # Project reference
            if invoice_data.get("project_reference"):
                segments.append(f"RFF+PL:{escape_edifact_text(invoice_data.get('project_reference'))}'")
            # Despatch document reference
            if invoice_data.get("despatch_document_reference"):
                segments.append(f"RFF+DQ:{escape_edifact_text(invoice_data.get('despatch_document_reference'))}'")
            # Receipt document reference
            if invoice_data.get("receipt_document_reference"):
                segments.append(f"RFF+RR:{escape_edifact_text(invoice_data.get('receipt_document_reference'))}'")
        else:
            # Fallback to XML parsing
            order_ref_elem = root.find(".//cac:OrderReference/cbc:ID", ns)
            if order_ref_elem is not None and order_ref_elem.text:
                order_ref = escape_edifact_text(order_ref_elem.text.strip())
                segments.append(f"RFF+ON:{order_ref}'")
        
        # FTX - Free text / Notes
        if invoice_data and invoice_data.get("invoice_note"):
            note_text = escape_edifact_text(invoice_data.get("invoice_note"))
            if note_text:
                segments.append(f"FTX+AAI+++{note_text}'")
        
        # NAD - Supplier (SU = Supplier)
        segments.append(
            f"NAD+SU+{supplier['id']}::9++{supplier['name']}+{supplier['street']}+"
            f"{supplier['city']}++{supplier['postal']}+{supplier['country']}'"
        )
        
        # RFF - Supplier tax ID
        if supplier.get('tax_id'):
            segments.append(f"RFF+VA:{supplier['tax_id']}'")
        
        # CTA/COM - Supplier contact
        if supplier.get('contact_name'):
            segments.append(f"CTA+IC+:{supplier['contact_name']}'")
            if supplier.get('contact_phone'):
                segments.append(f"COM+{supplier['contact_phone']}:TE'")
            if supplier.get('contact_email'):
                segments.append(f"COM+{supplier['contact_email']}:EM'")
        
        # NAD - Buyer (BY = Buyer)
        segments.append(
            f"NAD+BY+{buyer['id']}::9++{buyer['name']}+{buyer['street']}+"
            f"{buyer['city']}++{buyer['postal']}+{buyer['country']}'"
        )
        
        # RFF - Buyer tax ID
        if buyer.get('tax_id'):
            segments.append(f"RFF+VA:{buyer['tax_id']}'")
        
        # CTA/COM - Buyer contact
        if buyer.get('contact_name'):
            segments.append(f"CTA+PD+:{buyer['contact_name']}'")
            if buyer.get('contact_phone'):
                segments.append(f"COM+{buyer['contact_phone']}:TE'")
            if buyer.get('contact_email'):
                segments.append(f"COM+{buyer['contact_email']}:EM'")
        
        # NAD - Delivery party (if different)
        if invoice_data and invoice_data.get("delivery_party_name"):
            delivery_street = escape_edifact_text(invoice_data.get("delivery_street", ""))
            delivery_city = escape_edifact_text(invoice_data.get("delivery_city", ""))
            delivery_postal = invoice_data.get("delivery_postal_code", "")
            delivery_country = invoice_data.get("delivery_country", "")
            delivery_name = escape_edifact_text(invoice_data.get("delivery_party_name", ""))
            
            segments.append(
                f"NAD+DP+++{delivery_name}+{delivery_street}+{delivery_city}++{delivery_postal}+{delivery_country}'"
            )
        
        # NAD - Payee party (if different)
        if invoice_data and invoice_data.get("payee_party_name"):
            payee_name = escape_edifact_text(invoice_data.get("payee_party_name", ""))
            payee_id = invoice_data.get("payee_party_id", "")
            segments.append(f"NAD+PE+{payee_id}++{payee_name}'")
        
        # CUX - Currency (if not default)
        if currency and currency != "USD":
            segments.append(
                f"CUX+2:{currency}:4'"
            )
        
        # PAT - Payment terms
        if invoice_data and invoice_data.get("payment_terms"):
            payment_terms = escape_edifact_text(invoice_data.get("payment_terms"))
            segments.append(f"PAT+22'")  # 22 = Payment terms
            segments.append(f"FTX+PAT+++{payment_terms}'")
        
        # PAI - Payment instructions
        if invoice_data and invoice_data.get("payment_means_code"):
            payment_code = invoice_data.get("payment_means_code", "30")
            segments.append(f"PAI++{payment_code}'")
        
        # FII - Financial institution (bank account)
        if invoice_data and invoice_data.get("payee_account_id"):
            account_id = invoice_data.get("payee_account_id")
            account_name = escape_edifact_text(invoice_data.get("payee_account_name", ""))
            bic = invoice_data.get("payee_bic", "")
            segments.append(f"FII+RB+{account_id}+{account_name}++{bic}'")
        
        # ALC - Document-level allowances/charges
        if invoice_data and invoice_data.get("allowance_total_amount"):
            allowance_amount = format_edifact_amount(str(invoice_data.get("allowance_total_amount")))
            allowance_reason = escape_edifact_text(invoice_data.get("allowance_charge_reason", "Discount"))
            # A = Allowance, C = Charge
            charge_indicator = "C" if invoice_data.get("charge_indicator") else "A"
            segments.append(f"ALC+{charge_indicator}'")
            segments.append(f"PCD+1:100'")  # Percentage (if applicable)
            segments.append(f"MOA+8:{allowance_amount}'")
            if allowance_reason:
                segments.append(f"FTX+AAB+++{allowance_reason}'")
        
        # Process invoice lines (use invoice_data if available)
        if invoice_data and "line_items" in invoice_data:
            line_items = invoice_data.get("line_items", [])
            logger.info(f"📊 Processing {len(line_items)} invoice lines from extracted data")
            
            for idx, line_data in enumerate(line_items, 1):
                line_id = str(line_data.get("line_id", idx))
                quantity = str(line_data.get("quantity", "1"))
                unit_code = line_data.get("unit_code", "C62")
                price = format_edifact_amount(str(line_data.get("price", "0.00")))
                line_amount = format_edifact_amount(str(line_data.get("line_amount", "0.00")))
                
                # Item identifiers
                seller_item_id = line_data.get("seller_item_id", "")
                buyer_item_id = line_data.get("buyer_item_id", "")
                standard_item_id = line_data.get("standard_item_id", "")
                
                item_name = escape_edifact_text(line_data.get("item_name", ""))
                item_description = escape_edifact_text(line_data.get("item_description", ""))
                
                # LIN - Line item (use seller ID primary, fallback to standard ID)
                line_item_id = seller_item_id or standard_item_id or ""
                segments.append(f"LIN+{line_id}++{line_item_id}:SA'")
                
                # PIA - Additional product IDs
                if buyer_item_id:
                    segments.append(f"PIA+1+{buyer_item_id}:BP'")
                if standard_item_id and standard_item_id != seller_item_id:
                    segments.append(f"PIA+1+{standard_item_id}:EN'")
                
                # IMD - Item name
                if item_name:
                    segments.append(f"IMD+F++:::{item_name}'")
                
                # IMD - Item description (if different from name)
                if item_description and item_description != item_name:
                    segments.append(f"IMD+E++:::{item_description}'")
                
                # FTX - Line note
                if line_data.get("line_note"):
                    line_note = escape_edifact_text(line_data.get("line_note"))
                    segments.append(f"FTX+AAI+++{line_note}'")
                
                # QTY - Quantity (47 = Invoiced quantity)
                segments.append(f"QTY+47:{quantity}:{unit_code}'")
                
                # MOA - Line amount (203 = Line item amount)
                segments.append(f"MOA+203:{line_amount}'")
                
                # PRI - Price details (AAA = Net price)
                segments.append(f"PRI+AAA:{price}'")
                
                # TAX - Tax information per line
                if line_data.get("tax_percentage"):
                    tax_percent = str(line_data.get("tax_percentage"))
                    tax_category = line_data.get("tax_category_id", "S")
                    segments.append(f"TAX+7+{tax_category}++:::{tax_percent}'")
                
                # ALC - Line-level allowances/charges
                if line_data.get("line_allowance_amount"):
                    line_allowance = format_edifact_amount(str(line_data.get("line_allowance_amount")))
                    segments.append(f"ALC+A'")
                    segments.append(f"MOA+8:{line_allowance}'")
                
                # Origin country
                if line_data.get("origin_country"):
                    segments.append(f"RFF+OC:{line_data.get('origin_country')}'")
                
                # Commodity classification
                if line_data.get("commodity_code"):
                    commodity_code = line_data.get("commodity_code")
                    segments.append(f"RFF+HS:{commodity_code}'")
                
                # Accounting cost
                if line_data.get("accounting_cost"):
                    accounting_cost = escape_edifact_text(line_data.get("accounting_cost"))
                    segments.append(f"FTX+ACB+++{accounting_cost}'")
            
            logger.info(f"✅ Processed {len(line_items)} invoice lines from extracted data")
        else:
            # Fallback to XML parsing
            invoice_lines = root.findall(".//cac:InvoiceLine", ns)
            logger.info(f"📊 Processing {len(invoice_lines)} invoice lines from XML")
            
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
                segments.append(f"LIN+{line_id}++{item_id}:SA'")
                
                # IMD - Item description (optional)
                if item_name:
                    segments.append(f"IMD+F++:::{item_name}'")
                
                # QTY - Quantity (47 = Invoiced quantity)
                segments.append(f"QTY+47:{quantity}'")
                
                # MOA - Line amount (203 = Line item amount)
                segments.append(f"MOA+203:{line_amount}'")
                
                # PRI - Price details (AAA = Net price)
                segments.append(f"PRI+AAA:{price}'")
            
            logger.info(f"✅ Processed {len(invoice_lines)} invoice lines from XML")
        
        # UNS - Section separator (separates detail from summary)
        segments.append("UNS+S'")
        
        # TAX - Document-level tax information
        if invoice_data:
            tax_amount = invoice_data.get("tax_amount")
            tax_percentage = invoice_data.get("tax_percentage")
            taxable_amount = invoice_data.get("taxable_amount")
            tax_category = invoice_data.get("tax_category_id", "S")
            
            if tax_amount:
                # TAX segment: 7=Tax, category, percentage
                if tax_percentage:
                    segments.append(f"TAX+7+{tax_category}++:::{tax_percentage}'")
                # MOA for taxable base
                if taxable_amount:
                    taxable = format_edifact_amount(str(taxable_amount))
                    segments.append(f"MOA+125:{taxable}'")
        
        # MOA - Total amounts (use invoice_data if available)
        if invoice_data:
            # 79 = Total line items amount
            if invoice_data.get("line_extension_amount"):
                line_total = format_edifact_amount(str(invoice_data.get("line_extension_amount")))
                segments.append(f"MOA+79:{line_total}'")
            
            # 125 = Taxable amount
            if invoice_data.get("tax_exclusive_amount"):
                tax_exclusive = format_edifact_amount(str(invoice_data.get("tax_exclusive_amount")))
                segments.append(f"MOA+125:{tax_exclusive}'")
            
            # 176 = Tax amount
            if invoice_data.get("tax_amount"):
                tax_total = format_edifact_amount(str(invoice_data.get("tax_amount")))
                segments.append(f"MOA+176:{tax_total}'")
            
            # 131 = Total with tax
            if invoice_data.get("tax_inclusive_amount"):
                tax_inclusive = format_edifact_amount(str(invoice_data.get("tax_inclusive_amount")))
                segments.append(f"MOA+131:{tax_inclusive}'")
            
            # 8 = Allowances total
            if invoice_data.get("allowance_total_amount"):
                allowance_total = format_edifact_amount(str(invoice_data.get("allowance_total_amount")))
                segments.append(f"MOA+8:{allowance_total}'")
            
            # 113 = Prepaid amount
            if invoice_data.get("prepaid_amount"):
                prepaid = format_edifact_amount(str(invoice_data.get("prepaid_amount")))
                segments.append(f"MOA+113:{prepaid}'")
            
            # 86 = Total payable amount
            if invoice_data.get("total") or invoice_data.get("payable_amount"):
                payable_total = format_edifact_amount(str(invoice_data.get("total") or invoice_data.get("payable_amount")))
                segments.append(f"MOA+86:{payable_total}'")
        else:
            # Fallback to XML parsing
            total_amount_elem = root.find(".//cac:LegalMonetaryTotal/cbc:PayableAmount", ns)
            tax_amount_elem = root.find(".//cac:TaxTotal/cbc:TaxAmount", ns)
            line_extension_elem = root.find(".//cac:LegalMonetaryTotal/cbc:LineExtensionAmount", ns)
            
            # 79 = Total line items amount
            if line_extension_elem is not None and line_extension_elem.text:
                line_total = format_edifact_amount(line_extension_elem.text)
                segments.append(f"MOA+79:{line_total}'")
            
            # 176 = Tax amount
            if tax_amount_elem is not None and tax_amount_elem.text:
                tax_total = format_edifact_amount(tax_amount_elem.text)
                segments.append(f"MOA+176:{tax_total}'")
            
            # 86 = Total payable amount
            if total_amount_elem is not None and total_amount_elem.text:
                payable_total = format_edifact_amount(total_amount_elem.text)
                segments.append(f"MOA+86:{payable_total}'")
        
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

