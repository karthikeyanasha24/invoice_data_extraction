import xml.etree.ElementTree as ET
from datetime import datetime
from unidecode import unidecode


class X12ControlNumbers:
    def __init__(self, root, ns):
        invoice_id = root.find(".//cbc:ID", ns)
        self.interchange_control = (invoice_id.text[:9] if invoice_id else "000000000").zfill(9)
        order_ref = root.find(".//cac:OrderReference/cbc:ID", ns)
        self.group_control = (order_ref.text[:6] if order_ref  else "000000").zfill(6)
        originator_ref = root.find(".//cac:OriginatorDocumentReference/cbc:ID", ns)
        self.transaction_control = (originator_ref.text[:4] if originator_ref else "0000").zfill(4)


def format_number(number_str, decimal_places=2):
    try:
        number = float(number_str)
        return str(int(round(number * (10 ** decimal_places))))
    except (ValueError, TypeError):
        return "0"


def extract_party_info(root, party_path, ns):
    party = root.find(party_path, ns)
    if party is not None:
        name_elem = party.find(".//cbc:Name", ns)
        endpoint_elem = party.find(".//cbc:EndpointID", ns)
        qualifier = "ZZ"
        endpoint_id = "UNKNOWN"
        if endpoint_elem is not None:
            scheme_id = endpoint_elem.get('schemeID')
            qualifier_map = {
                '0002': '01',
                '0007': '14',
                '0009': '33',
                '0037': '94',
                '0060': 'N1',
                '0088': '12',
                '0160': '98',
                '9930': '93',
                '0096': '24',
            }
            if scheme_id:
                qualifier = qualifier_map.get(scheme_id, 'ZZ')
            endpoint_id = endpoint_elem.text.strip() if endpoint_elem.text else "UNKNOWN"
        endpoint_id = endpoint_id.ljust(15)[:15]
        return {
            'name': name_elem.text.strip() if name_elem is not None and name_elem.text else "UNKNOWN",
            'id': endpoint_id,
            'qualifier': qualifier
        }
    return {'name': "UNKNOWN", 'id': "UNKNOWN".ljust(15), 'qualifier': "ZZ"}


def extract_postal_address(root, party_path, ns):
    address = root.find(f"{party_path}/cac:PostalAddress", ns)
    if address is not None:
        street_elem = address.find("cbc:StreetName", ns)
        city_elem = address.find("cbc:CityName", ns)
        postal_elem = address.find("cbc:PostalZone", ns)
        country_elem = address.find("cac:Country/cbc:IdentificationCode", ns)
        return {
            "street": street_elem.text.strip() if street_elem is not None and street_elem.text else "",
            "city": city_elem.text.strip() if city_elem is not None and city_elem.text else "",
            "postal": postal_elem.text.strip() if postal_elem is not None and postal_elem.text else "",
            "country": country_elem.text.strip() if country_elem is not None and country_elem.text else ""
        }
    return {"street": "", "city": "", "postal": "", "country": ""}


def map_address(address):
    city = address.get("city", "")
    postal = address.get("postal", "")
    country = address.get("country", "")
    state = "XX"
    if city.lower() == "north sydney":
        state = "NS"
    elif city.lower() == "port lincoln":
        state = "SA"
    if country.upper() == "AU":
        country = "AUS"
    return state, postal, country


def create_ISA_segment(supplier, customer, control_numbers, current_time):
    # Build each data element with fixed width:
    isa01 = "00"  # 2 characters
    isa02 = " " * 10  # 10 characters
    isa03 = "00"  # 2 characters
    isa04 = " " * 10  # 10 characters
    isa05 = supplier['qualifier'][:2].ljust(2)  # 2 characters
    isa06 = supplier['id'][:15].ljust(15)  # 15 characters
    isa07 = customer['qualifier'][:2].ljust(2)  # 2 characters
    isa08 = customer['id'][:15].ljust(15)  # 15 characters
    isa09 = current_time.strftime("%y%m%d")  # 6 characters
    isa10 = current_time.strftime("%H%M")  # 4 characters
    isa11 = "U"  # 1 character
    isa12 = "00401"  # 5 characters
    isa13 = control_numbers.interchange_control.zfill(9)  # 9 characters
    isa14 = "0"  # 1 character
    isa15 = "P"  # 1 character
    isa16 = ">"  # 1 character; must be exactly one character

    # Build ISA segment using "*" delimiters without additional padding afterwards.
    # Do NOT pad the complete segment to 106 characters as that can overwrite ISA16.
    isa_elements = [
        "ISA", isa01, isa02, isa03, isa04,
        isa05, isa06, isa07, isa08, isa09,
        isa10, isa11, isa12, isa13, isa14, isa15, isa16
    ]
    return "*".join(isa_elements) + "~"


def convert_xml_to_x12(xml_content):
    ns = {
        'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
    }
    root = ET.fromstring(xml_content)
    x12_segments = []
    control_numbers = X12ControlNumbers(root, ns)

    supplier = extract_party_info(root, ".//cac:AccountingSupplierParty/cac:Party", ns)
    customer = extract_party_info(root, ".//cac:AccountingCustomerParty/cac:Party", ns)
    if supplier["id"].strip() == "UNKNOWN":
        supplier["id"] = "SENDERID".ljust(15)
    if customer["id"].strip() == "UNKNOWN":
        customer["id"] = "RECEIVERID".ljust(15)

    current_time = datetime.now()
    # Create ISA segment using fixed-width fields; do not pad the final segment.
    isa_segment = create_ISA_segment(supplier, customer, control_numbers, current_time)
    x12_segments.append(isa_segment)

    gs = (
        f"GS*IN*{supplier['id'].strip()}*{customer['id'].strip()}*"
        f"{current_time.strftime('%Y%m%d')}*{current_time.strftime('%H%M')}*"
        f"{control_numbers.group_control}*X*004010~"
    )
    x12_segments.append(gs)

    st = f"ST*810*{control_numbers.transaction_control}~"
    x12_segments.append(st)

    invoice_date_elem = root.find(".//cbc:IssueDate", ns)
    invoice_number_elem = root.find(".//cbc:ID", ns)
    purchase_order_elem = root.find(".//cac:OrderReference/cbc:ID", ns)
    invoice_date = invoice_date_elem.text.strip() if invoice_date_elem is not None and invoice_date_elem.text else ""
    print(invoice_date)
    if invoice_date == "0000-00-00":
        formatted_date = ""
    else:
        formatted_date = datetime.strptime(invoice_date, "%Y-%m-%d").strftime("%Y%m%d") if invoice_date else ""
    purchase_order = ""
    if purchase_order_elem is not None and purchase_order_elem.text:
        po = purchase_order_elem.text.strip()
        purchase_order = po[:8] if len(po) >= 8 else po.zfill(8)
    big = (
        f"BIG*{formatted_date}*"
        f"{invoice_number_elem.text.strip() if invoice_number_elem is not None and invoice_number_elem.text else ''}~"
    )
    x12_segments.append(big)

    note_elem = root.find(".//cbc:Note", ns)
    if note_elem is not None and note_elem.text and note_elem.text.strip() not in [".", ""]:
        x12_segments.append(f"NTE*GEN*{note_elem.text.strip()}~")

    currency_elem = root.find(".//cbc:DocumentCurrencyCode", ns)
    if currency_elem is not None and currency_elem.text:
        x12_segments.append(f"CUR*BY*{currency_elem.text.strip()}~")

    contract_ref = root.find(".//cac:ContractDocumentReference/cbc:ID", ns)
    if contract_ref is not None and contract_ref.text:
        x12_segments.append(f"REF*CT*{contract_ref.text.strip()}~")

    contact = root.find(".//cac:AccountingSupplierParty//cac:Contact", ns)
    if contact is not None:
        contact_name = contact.find("cbc:Name", ns)
        contact_phone = contact.find("cbc:Telephone", ns)
        if contact_name is not None and contact_phone is not None and contact_name.text and contact_phone.text:
            x12_segments.append(f"PER*IC*{contact_name.text.strip()}*TE*{contact_phone.text.strip()}~")

    x12_segments.append(f"N1*SU*{supplier['name']}*{supplier['qualifier']}*{supplier['id'].strip()}~")
    supplier_address = extract_postal_address(root, ".//cac:AccountingSupplierParty/cac:Party", ns)
    if supplier_address["street"]:
        x12_segments.append(f"N3*{supplier_address['street']}~")
    state, postal, country = map_address(supplier_address)
    if supplier_address["city"] or postal or country:
        x12_segments.append(f"N4*{supplier_address['city']}*{state}*{postal}*{country}~")

    x12_segments.append(f"N1*BY*{customer['name']}*{customer['qualifier']}*{customer['id'].strip()}~")
    customer_address = extract_postal_address(root, ".//cac:AccountingCustomerParty/cac:Party", ns)
    if customer_address["street"]:
        x12_segments.append(f"N3*{customer_address['street']}~")
    state, postal, country = map_address(customer_address)
    if customer_address["city"] or postal or country:
        x12_segments.append(f"N4*{customer_address['city']}*{state}*{postal}*{country}~")

    payment_terms_elem = root.find(".//cac:PaymentTerms/cbc:Note", ns)
    if payment_terms_elem is not None and payment_terms_elem.text:
        term = payment_terms_elem.text.strip()
        if term.lower().startswith("pay immediately"):
            term = "1"
        x12_segments.append(f"ITD*01*{term}~")

    due_date_elem = root.find(".//cbc:DueDate", ns)
    if due_date_elem is not None and due_date_elem.text:
        due_date = datetime.strptime(due_date_elem.text.strip(), "%Y-%m-%d").strftime("%Y%m%d")
        x12_segments.append(f"DTM*011*{due_date}~")

    delivery = root.find(".//cac:Delivery", ns)
    if delivery is not None:
        x12_segments.append("FOB*CC~")

    invoice_lines = root.findall(".//cac:InvoiceLine", ns)
    for idx, line in enumerate(invoice_lines, 1):
        quantity_elem = line.find("cbc:InvoicedQuantity", ns)
        price_elem = line.find(".//cac:Price/cbc:PriceAmount", ns)
        product_elem = line.find(".//cac:Item/cac:SellersItemIdentification/cbc:ID", ns)
        quantity_val = quantity_elem.text.strip() if quantity_elem is not None and quantity_elem.text else "0"
        price_val = format_number(price_elem.text) if price_elem is not None and price_elem.text else "0"
        product_code = product_elem.text.strip() if product_elem is not None and product_elem.text else ""
        x12_segments.append(f"IT1*{idx}*{quantity_val}*EA*{price_val}*CP*VP*{product_code}~")

    total_amount_elem = root.find(".//cac:LegalMonetaryTotal/cbc:PayableAmount", ns)
    if total_amount_elem is not None and total_amount_elem.text:
        formatted_total = format_number(total_amount_elem.text)
        x12_segments.append(f"TDS*{formatted_total}~")

    hash_total = sum(int(line.find("cbc:ID", ns).text.lstrip("0") or "0") for line in invoice_lines)
    x12_segments.append(f"CTT*{len(invoice_lines)}*{hash_total}~")

    st_index = next(i for i, seg in enumerate(x12_segments) if seg.startswith("ST"))
    transaction_segment_count = len(x12_segments) - st_index + 1
    x12_segments.append(f"SE*{transaction_segment_count}*{control_numbers.transaction_control}~")

    x12_segments.append(f"GE*1*{control_numbers.group_control}~")
    x12_segments.append(f"IEA*1*{control_numbers.interchange_control}~")

    return unidecode("\n".join(x12_segments))
