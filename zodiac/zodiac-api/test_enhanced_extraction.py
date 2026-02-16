"""
Test Enhanced Invoice Extraction
Verify that all fields from the provided UBL invoice are correctly extracted
"""
import sys
import os
from typing import Dict, Any, Optional, List
from lxml import etree

# Set UTF-8 encoding for console output
if sys.platform == 'win32':
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except:
        pass  # Fall back to default encoding

# Standalone extraction logic for testing (no DB imports)
UBL_NAMESPACES = {
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'invoice': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
}

REQUIRED_FIELDS = [
    "invoice_number",
    "issue_date",
    "currency",
    "customer_id",
    "customer_name",
    "supplier_id",
    "supplier_name",
    "total",
    "tax_percentage"
]


def _get_text(element, xpath: str, namespaces: dict) -> Optional[str]:
    """Safely extract text from XML element"""
    try:
        elem = element.find(xpath, namespaces)
        if elem is not None and elem.text:
            return elem.text.strip()
    except Exception:
        pass
    return None


def _get_attribute(element, xpath: str, attr_name: str, namespaces: dict) -> Optional[str]:
    """Safely extract attribute from XML element"""
    try:
        elem = element.find(xpath, namespaces)
        if elem is not None:
            return elem.get(attr_name)
    except Exception:
        pass
    return None


def _extract_address(party_element, namespaces: dict) -> Optional[Dict[str, str]]:
    """Extract postal address from party element"""
    try:
        address_elem = party_element.find('.//cac:PostalAddress', namespaces)
        if address_elem is not None:
            return {
                "street": _get_text(address_elem, './/cbc:StreetName', namespaces),
                "city": _get_text(address_elem, './/cbc:CityName', namespaces),
                "postal_zone": _get_text(address_elem, './/cbc:PostalZone', namespaces),
                "country": _get_text(address_elem, './/cac:Country/cbc:IdentificationCode', namespaces),
            }
    except Exception:
        pass
    return None


def _extract_party_contact(party_element, namespaces: dict) -> Optional[Dict[str, str]]:
    """Extract contact information from party element"""
    try:
        contact_elem = party_element.find('.//cac:Contact', namespaces)
        if contact_elem is not None:
            return {
                "name": _get_text(contact_elem, './/cbc:Name', namespaces),
                "telephone": _get_text(contact_elem, './/cbc:Telephone', namespaces),
                "email": _get_text(contact_elem, './/cbc:ElectronicMail', namespaces),
            }
    except Exception:
        pass
    return None


def _extract_payment_info(root, namespaces: dict) -> Dict[str, Any]:
    """Extract payment means and terms"""
    payment_info = {}
    try:
        payment_means = root.find('.//cac:PaymentMeans', namespaces)
        if payment_means is not None:
            payment_info["payment_means_code"] = _get_text(payment_means, './/cbc:PaymentMeansCode', namespaces)
            payment_info["payment_means_name"] = _get_attribute(payment_means, './/cbc:PaymentMeansCode', 'name', namespaces)
            payment_info["payment_id"] = _get_text(payment_means, './/cbc:PaymentID', namespaces)
            
            financial_account = payment_means.find('.//cac:PayeeFinancialAccount', namespaces)
            if financial_account is not None:
                payment_info["payee_financial_account"] = {
                    "account_id": _get_text(financial_account, './/cbc:ID', namespaces),
                    "account_name": _get_text(financial_account, './/cbc:Name', namespaces),
                    "bank_id": _get_text(financial_account, './/cac:FinancialInstitutionBranch/cbc:ID', namespaces),
                }
        
        payment_terms = root.find('.//cac:PaymentTerms', namespaces)
        if payment_terms is not None:
            payment_info["payment_terms"] = _get_text(payment_terms, './/cbc:Note', namespaces)
    except Exception:
        pass
    
    return payment_info


def _extract_tax_breakdown(root, namespaces: dict) -> Dict[str, Any]:
    """Extract full tax breakdown including percentage"""
    tax_info = {}
    try:
        tax_total = root.find('.//cac:TaxTotal', namespaces)
        if tax_total is not None:
            tax_info["tax_amount"] = _get_text(tax_total, './/cbc:TaxAmount', namespaces)
            
            tax_subtotal = tax_total.find('.//cac:TaxSubtotal', namespaces)
            if tax_subtotal is not None:
                tax_info["taxable_amount"] = _get_text(tax_subtotal, './/cbc:TaxableAmount', namespaces)
                
                tax_category = tax_subtotal.find('.//cac:TaxCategory', namespaces)
                if tax_category is not None:
                    tax_info["tax_category_id"] = _get_text(tax_category, './/cbc:ID', namespaces)
                    tax_info["tax_percentage"] = _get_text(tax_category, './/cbc:Percent', namespaces)
                    
                    tax_scheme = tax_category.find('.//cac:TaxScheme', namespaces)
                    if tax_scheme is not None:
                        tax_info["tax_scheme"] = _get_text(tax_scheme, './/cbc:ID', namespaces)
    except Exception:
        pass
    
    return tax_info


def _extract_allowances_charges(root, namespaces: dict) -> List[Dict[str, Any]]:
    """Extract allowance/charge array"""
    allowances_charges = []
    try:
        ac_elements = root.findall('.//cac:AllowanceCharge', namespaces)
        for ac in ac_elements:
            item = {
                "charge_indicator": _get_text(ac, './/cbc:ChargeIndicator', namespaces),
                "reason_code": _get_text(ac, './/cbc:AllowanceChargeReasonCode', namespaces),
                "reason": _get_text(ac, './/cbc:AllowanceChargeReason', namespaces),
                "multiplier": _get_text(ac, './/cbc:MultiplierFactorNumeric', namespaces),
                "amount": _get_text(ac, './/cbc:Amount', namespaces),
                "base_amount": _get_text(ac, './/cbc:BaseAmount', namespaces),
            }
            allowances_charges.append(item)
    except Exception:
        pass
    
    return allowances_charges


def _extract_delivery_info(root, namespaces: dict) -> Dict[str, Any]:
    """Extract delivery details"""
    delivery_info = {}
    try:
        delivery = root.find('.//cac:Delivery', namespaces)
        if delivery is not None:
            delivery_info["delivery_date"] = _get_text(delivery, './/cbc:ActualDeliveryDate', namespaces)
            
            delivery_location = delivery.find('.//cac:DeliveryLocation', namespaces)
            if delivery_location is not None:
                delivery_info["delivery_location_id"] = _get_text(delivery_location, './/cbc:ID', namespaces)
                
                address_elem = delivery_location.find('.//cac:Address', namespaces)
                if address_elem is not None:
                    delivery_info["delivery_address"] = {
                        "street": _get_text(address_elem, './/cbc:StreetName', namespaces),
                        "city": _get_text(address_elem, './/cbc:CityName', namespaces),
                        "postal_zone": _get_text(address_elem, './/cbc:PostalZone', namespaces),
                        "country": _get_text(address_elem, './/cac:Country/cbc:IdentificationCode', namespaces),
                    }
            
            delivery_party = delivery.find('.//cac:DeliveryParty', namespaces)
            if delivery_party is not None:
                delivery_info["delivery_party_name"] = _get_text(delivery_party, './/cac:PartyName/cbc:Name', namespaces)
    except Exception:
        pass
    
    return delivery_info


def extract_invoice_fields(xml_content: str) -> Dict[str, Any]:
    """Extract all fields from UBL XML"""
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        ns = UBL_NAMESPACES
        
        # Extract invoice header with metadata
        invoice_data = {
            "invoice_number": _get_text(root, './/cbc:ID', ns),
            "issue_date": _get_text(root, './/cbc:IssueDate', ns),
            "due_date": _get_text(root, './/cbc:DueDate', ns),
            "currency": _get_text(root, './/cbc:DocumentCurrencyCode', ns),
            "invoice_type_code": _get_text(root, './/cbc:InvoiceTypeCode', ns),
            "customization_id": _get_text(root, './/cbc:CustomizationID', ns),
            "profile_id": _get_text(root, './/cbc:ProfileID', ns),
            "note": _get_text(root, './/cbc:Note', ns),
            "accounting_cost": _get_text(root, './/cbc:AccountingCost', ns),
            "buyer_reference": _get_text(root, './/cbc:BuyerReference', ns),
        }
        
        # Extract order and document references
        order_ref = root.find('.//cac:OrderReference', ns)
        if order_ref is not None:
            invoice_data["order_reference"] = _get_text(order_ref, './/cbc:ID', ns)
            invoice_data["sales_order_id"] = _get_text(order_ref, './/cbc:SalesOrderID', ns)
        
        invoice_data["contract_reference"] = _get_text(root, './/cac:ContractDocumentReference/cbc:ID', ns)
        invoice_data["project_reference"] = _get_text(root, './/cac:ProjectReference/cbc:ID', ns)
        
        # Extract customer
        customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', ns)
        if customer_party is not None:
            invoice_data.update({
                "customer_id": _get_text(customer_party, './/cbc:EndpointID', ns),
                "customer_id_scheme": _get_attribute(customer_party, './/cbc:EndpointID', 'schemeID', ns),
                "customer_name": _get_text(customer_party, './/cac:PartyName/cbc:Name', ns),
                "customer_tax_id": _get_text(customer_party, './/cac:PartyTaxScheme/cbc:CompanyID', ns),
                "customer_legal_name": _get_text(customer_party, './/cac:PartyLegalEntity/cbc:RegistrationName', ns),
                "customer_address": _extract_address(customer_party, ns),
            })
            
            customer_contact = _extract_party_contact(customer_party, ns)
            if customer_contact:
                invoice_data["customer_contact_name"] = customer_contact.get("name")
                invoice_data["customer_contact_telephone"] = customer_contact.get("telephone")
                invoice_data["customer_contact_email"] = customer_contact.get("email")
        
        # Extract supplier
        supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', ns)
        if supplier_party is not None:
            invoice_data.update({
                "supplier_id": _get_text(supplier_party, './/cbc:EndpointID', ns),
                "supplier_id_scheme": _get_attribute(supplier_party, './/cbc:EndpointID', 'schemeID', ns),
                "supplier_name": _get_text(supplier_party, './/cac:PartyName/cbc:Name', ns),
                "supplier_tax_id": _get_text(supplier_party, './/cac:PartyTaxScheme/cbc:CompanyID', ns),
                "supplier_legal_name": _get_text(supplier_party, './/cac:PartyLegalEntity/cbc:RegistrationName', ns),
                "supplier_company_legal_form": _get_text(supplier_party, './/cac:PartyLegalEntity/cbc:CompanyLegalForm', ns),
                "supplier_address": _extract_address(supplier_party, ns),
            })
            
            supplier_contact = _extract_party_contact(supplier_party, ns)
            if supplier_contact:
                invoice_data["supplier_contact_name"] = supplier_contact.get("name")
                invoice_data["supplier_contact_telephone"] = supplier_contact.get("telephone")
                invoice_data["supplier_contact_email"] = supplier_contact.get("email")
        
        # Extract monetary totals
        legal_monetary = root.find('.//cac:LegalMonetaryTotal', ns)
        if legal_monetary is not None:
            invoice_data.update({
                "line_extension_amount": _get_text(legal_monetary, './/cbc:LineExtensionAmount', ns),
                "subtotal": _get_text(legal_monetary, './/cbc:TaxExclusiveAmount', ns),
                "total": _get_text(legal_monetary, './/cbc:TaxInclusiveAmount', ns),
                "payable_amount": _get_text(legal_monetary, './/cbc:PayableAmount', ns),
                "allowance_total_amount": _get_text(legal_monetary, './/cbc:AllowanceTotalAmount', ns),
                "prepaid_amount": _get_text(legal_monetary, './/cbc:PrepaidAmount', ns),
            })
        
        # Extract tax breakdown
        tax_breakdown = _extract_tax_breakdown(root, ns)
        invoice_data.update(tax_breakdown)
        
        # Extract payment information
        payment_info = _extract_payment_info(root, ns)
        invoice_data.update(payment_info)
        
        # Extract delivery information
        delivery_info = _extract_delivery_info(root, ns)
        invoice_data.update(delivery_info)
        
        # Extract allowances and charges
        allowances_charges = _extract_allowances_charges(root, ns)
        if allowances_charges:
            invoice_data["allowances_charges"] = allowances_charges
        
        # Extract line items
        line_items = []
        invoice_lines = root.findall('.//cac:InvoiceLine', ns)
        for line in invoice_lines:
            line_item = {
                "id": _get_text(line, './/cbc:ID', ns),
                "line_note": _get_text(line, './/cbc:Note', ns),
                "quantity": _get_text(line, './/cbc:InvoicedQuantity', ns),
                "unit_code": _get_attribute(line, './/cbc:InvoicedQuantity', 'unitCode', ns),
                "line_amount": _get_text(line, './/cbc:LineExtensionAmount', ns),
                "accounting_cost": _get_text(line, './/cbc:AccountingCost', ns),
                "order_line_reference": _get_text(line, './/cac:OrderLineReference/cbc:LineID', ns),
                "item_name": _get_text(line, './/cac:Item/cbc:Name', ns),
                "item_description": _get_text(line, './/cac:Item/cbc:Description', ns),
                "buyer_item_id": _get_text(line, './/cac:Item/cac:BuyersItemIdentification/cbc:ID', ns),
                "seller_item_id": _get_text(line, './/cac:Item/cac:SellersItemIdentification/cbc:ID', ns),
                "standard_item_id": _get_text(line, './/cac:Item/cac:StandardItemIdentification/cbc:ID', ns),
                "origin_country": _get_text(line, './/cac:Item/cac:OriginCountry/cbc:IdentificationCode', ns),
                "tax_category": _get_text(line, './/cac:Item/cac:ClassifiedTaxCategory/cbc:ID', ns),
                "tax_percent": _get_text(line, './/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent', ns),
                "price": _get_text(line, './/cac:Price/cbc:PriceAmount', ns),
            }
            line_items.append(line_item)
        
        invoice_data["line_items"] = line_items
        invoice_data["line_items_count"] = len(line_items)
        
        return invoice_data
        
    except Exception as e:
        print(f"Error extracting invoice fields: {e}")
        return {}


def find_missing_fields(invoice_data: Dict[str, Any]) -> List[str]:
    """Find missing required fields"""
    missing = []
    for field in REQUIRED_FIELDS:
        value = invoice_data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


# Sample invoice XML from user (Snippet1 - NZ Invoice)
SAMPLE_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
<cbc:CustomizationID>urn:cen.eu:en16931:2017#conformant#urn:fdc:peppol.eu:2017:poacc:billing:international:aunz:3.0</cbc:CustomizationID>
<cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
<cbc:ID>Snippet1</cbc:ID>
<cbc:IssueDate>2019-07-29</cbc:IssueDate>
<cbc:DueDate>2019-08-30</cbc:DueDate>
<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
<cbc:Note>Some Blurb about the Invoice</cbc:Note>
<cbc:DocumentCurrencyCode>NZD</cbc:DocumentCurrencyCode>
<cbc:AccountingCost>4025:123:4343</cbc:AccountingCost>
<cbc:BuyerReference>0150abc</cbc:BuyerReference>
<cac:OrderReference>
<cbc:ID>SOMEBLERB</cbc:ID>
<cbc:SalesOrderID>12345678</cbc:SalesOrderID>
</cac:OrderReference>
<cac:ContractDocumentReference>
<cbc:ID>CD-REF</cbc:ID>
</cac:ContractDocumentReference>
<cac:ProjectReference>
<cbc:ID>PR-REF</cbc:ID>
</cac:ProjectReference>
<cac:AccountingSupplierParty>
<cac:Party>
<cbc:EndpointID schemeID="0088">9429033821733</cbc:EndpointID>
<cac:PartyName>
<cbc:Name>SupplierTradingName Ltd.</cbc:Name>
</cac:PartyName>
<cac:PostalAddress>
<cbc:StreetName>Main street 1</cbc:StreetName>
<cbc:CityName>Wellington</cbc:CityName>
<cbc:PostalZone>NZ 123 EW</cbc:PostalZone>
<cac:Country>
<cbc:IdentificationCode>NZ</cbc:IdentificationCode>
</cac:Country>
</cac:PostalAddress>
<cac:PartyTaxScheme>
<cbc:CompanyID>888-888-888</cbc:CompanyID>
<cac:TaxScheme>
<cbc:ID>GST</cbc:ID>
</cac:TaxScheme>
</cac:PartyTaxScheme>
<cac:PartyLegalEntity>
<cbc:RegistrationName>SupplierOfficialName Ltd</cbc:RegistrationName>
<cbc:CompanyID schemeID="0088">9429033821733</cbc:CompanyID>
<cbc:CompanyLegalForm>Partnership</cbc:CompanyLegalForm>
</cac:PartyLegalEntity>
<cac:Contact>
<cbc:Name>Ronald MacDonald</cbc:Name>
<cbc:Telephone>Mobile 021 1090666</cbc:Telephone>
<cbc:ElectronicMail>ronald.macdonald@qualitygoods.co.nz</cbc:ElectronicMail>
</cac:Contact>
</cac:Party>
</cac:AccountingSupplierParty>
<cac:AccountingCustomerParty>
<cac:Party>
<cbc:EndpointID schemeID="0088">9429033591476</cbc:EndpointID>
<cac:PartyName>
<cbc:Name>Trotters Trading Co Ltd</cbc:Name>
</cac:PartyName>
<cac:PostalAddress>
<cbc:StreetName>100 Queen Street</cbc:StreetName>
<cbc:CityName>Auckland</cbc:CityName>
<cbc:PostalZone>A36577</cbc:PostalZone>
<cac:Country>
<cbc:IdentificationCode>NZ</cbc:IdentificationCode>
</cac:Country>
</cac:PostalAddress>
<cac:PartyTaxScheme>
<cbc:CompanyID>999-999-999</cbc:CompanyID>
<cac:TaxScheme>
<cbc:ID>GST</cbc:ID>
</cac:TaxScheme>
</cac:PartyTaxScheme>
<cac:PartyLegalEntity>
<cbc:RegistrationName>Buyer Official Name</cbc:RegistrationName>
<cbc:CompanyID schemeID="0088">9429033591476</cbc:CompanyID>
</cac:PartyLegalEntity>
<cac:Contact>
<cbc:Name>Lisa Johnson</cbc:Name>
<cbc:Telephone>23434234</cbc:Telephone>
<cbc:ElectronicMail>lj@buyer.se</cbc:ElectronicMail>
</cac:Contact>
</cac:Party>
</cac:AccountingCustomerParty>
<cac:Delivery>
<cbc:ActualDeliveryDate>2019-06-01</cbc:ActualDeliveryDate>
<cac:DeliveryLocation>
<cbc:ID schemeID="0088">9429033591476</cbc:ID>
<cac:Address>
<cbc:StreetName>Delivery street 2</cbc:StreetName>
<cbc:CityName>Auckland</cbc:CityName>
<cbc:PostalZone>21234</cbc:PostalZone>
<cac:Country>
<cbc:IdentificationCode>NZ</cbc:IdentificationCode>
</cac:Country>
</cac:Address>
</cac:DeliveryLocation>
<cac:DeliveryParty>
<cac:PartyName>
<cbc:Name>Delivery party Name</cbc:Name>
</cac:PartyName>
</cac:DeliveryParty>
</cac:Delivery>
<cac:PaymentMeans>
<cbc:PaymentMeansCode name="Credit transfer">30</cbc:PaymentMeansCode>
<cbc:PaymentID>Snippet1</cbc:PaymentID>
<cac:PayeeFinancialAccount>
<cbc:ID>IBAN32423940</cbc:ID>
<cbc:Name>AccountName</cbc:Name>
<cac:FinancialInstitutionBranch>
<cbc:ID>BIC324098</cbc:ID>
</cac:FinancialInstitutionBranch>
</cac:PayeeFinancialAccount>
</cac:PaymentMeans>
<cac:PaymentTerms>
<cbc:Note>Payment within 30 days</cbc:Note>
</cac:PaymentTerms>
<cac:AllowanceCharge>
<cbc:ChargeIndicator>false</cbc:ChargeIndicator>
<cbc:AllowanceChargeReasonCode>95</cbc:AllowanceChargeReasonCode>
<cbc:AllowanceChargeReason>Discount</cbc:AllowanceChargeReason>
<cbc:MultiplierFactorNumeric>100</cbc:MultiplierFactorNumeric>
<cbc:Amount currencyID="NZD">100.00</cbc:Amount>
<cbc:BaseAmount currencyID="NZD">100.00</cbc:BaseAmount>
</cac:AllowanceCharge>
<cac:TaxTotal>
<cbc:TaxAmount currencyID="NZD">208.11</cbc:TaxAmount>
<cac:TaxSubtotal>
<cbc:TaxableAmount currencyID="NZD">1387.40</cbc:TaxableAmount>
<cbc:TaxAmount currencyID="NZD">208.11</cbc:TaxAmount>
<cac:TaxCategory>
<cbc:ID>S</cbc:ID>
<cbc:Percent>15</cbc:Percent>
<cac:TaxScheme>
<cbc:ID>GST</cbc:ID>
</cac:TaxScheme>
</cac:TaxCategory>
</cac:TaxSubtotal>
</cac:TaxTotal>
<cac:LegalMonetaryTotal>
<cbc:LineExtensionAmount currencyID="NZD">1487.40</cbc:LineExtensionAmount>
<cbc:TaxExclusiveAmount currencyID="NZD">1387.40</cbc:TaxExclusiveAmount>
<cbc:TaxInclusiveAmount currencyID="NZD">1595.51</cbc:TaxInclusiveAmount>
<cbc:AllowanceTotalAmount currencyID="NZD">100.00</cbc:AllowanceTotalAmount>
<cbc:PrepaidAmount currencyID="NZD">0.00</cbc:PrepaidAmount>
<cbc:PayableAmount currencyID="NZD">1595.51</cbc:PayableAmount>
</cac:LegalMonetaryTotal>
<cac:InvoiceLine>
<cbc:ID>1</cbc:ID>
<cbc:Note>Some Blurb Giving More Info about the Invoice Line</cbc:Note>
<cbc:InvoicedQuantity unitCode="E99">10</cbc:InvoicedQuantity>
<cbc:LineExtensionAmount currencyID="NZD">299.90</cbc:LineExtensionAmount>
<cbc:AccountingCost>Consulting Fees</cbc:AccountingCost>
<cac:OrderLineReference>
<cbc:LineID>123</cbc:LineID>
</cac:OrderLineReference>
<cac:Item>
<cbc:Description>Widgets True and Fair</cbc:Description>
<cbc:Name>True-Widgets</cbc:Name>
<cac:BuyersItemIdentification>
<cbc:ID>W659590</cbc:ID>
</cac:BuyersItemIdentification>
<cac:SellersItemIdentification>
<cbc:ID>WG546767</cbc:ID>
</cac:SellersItemIdentification>
<cac:StandardItemIdentification>
<cbc:ID schemeID="0088">WG546767</cbc:ID>
</cac:StandardItemIdentification>
<cac:OriginCountry>
<cbc:IdentificationCode>NZ</cbc:IdentificationCode>
</cac:OriginCountry>
<cac:ClassifiedTaxCategory>
<cbc:ID>S</cbc:ID>
<cbc:Percent>15</cbc:Percent>
<cac:TaxScheme>
<cbc:ID>GST</cbc:ID>
</cac:TaxScheme>
</cac:ClassifiedTaxCategory>
</cac:Item>
<cac:Price>
<cbc:PriceAmount currencyID="NZD">29.99</cbc:PriceAmount>
</cac:Price>
</cac:InvoiceLine>
<cac:InvoiceLine>
<cbc:ID>2</cbc:ID>
<cbc:InvoicedQuantity unitCode="DAY">2</cbc:InvoicedQuantity>
<cbc:LineExtensionAmount currencyID="NZD">1000</cbc:LineExtensionAmount>
<cac:OrderLineReference>
<cbc:LineID>123</cbc:LineID>
</cac:OrderLineReference>
<cac:Item>
<cbc:Description>Description 2</cbc:Description>
<cbc:Name>item name 2</cbc:Name>
<cac:StandardItemIdentification>
<cbc:ID schemeID="0088">21382183120983</cbc:ID>
</cac:StandardItemIdentification>
<cac:OriginCountry>
<cbc:IdentificationCode>NO</cbc:IdentificationCode>
</cac:OriginCountry>
<cac:ClassifiedTaxCategory>
<cbc:ID>S</cbc:ID>
<cbc:Percent>15</cbc:Percent>
<cac:TaxScheme>
<cbc:ID>GST</cbc:ID>
</cac:TaxScheme>
</cac:ClassifiedTaxCategory>
</cac:Item>
<cac:Price>
<cbc:PriceAmount currencyID="NZD">500</cbc:PriceAmount>
</cac:Price>
</cac:InvoiceLine>
<cac:InvoiceLine>
<cbc:ID>3</cbc:ID>
<cbc:Note>Invoice Line Description</cbc:Note>
<cbc:InvoicedQuantity unitCode="M66">25</cbc:InvoicedQuantity>
<cbc:LineExtensionAmount currencyID="NZD">187.50</cbc:LineExtensionAmount>
<cbc:AccountingCost>Consulting Fees</cbc:AccountingCost>
<cac:OrderLineReference>
<cbc:LineID>123</cbc:LineID>
</cac:OrderLineReference>
<cac:Item>
<cbc:Description>Widgets True and Fair</cbc:Description>
<cbc:Name>True-Widgets</cbc:Name>
<cac:BuyersItemIdentification>
<cbc:ID>W659590</cbc:ID>
</cac:BuyersItemIdentification>
<cac:SellersItemIdentification>
<cbc:ID>WG546767</cbc:ID>
</cac:SellersItemIdentification>
<cac:StandardItemIdentification>
<cbc:ID schemeID="0088">WG546767</cbc:ID>
</cac:StandardItemIdentification>
<cac:OriginCountry>
<cbc:IdentificationCode>NZ</cbc:IdentificationCode>
</cac:OriginCountry>
<cac:ClassifiedTaxCategory>
<cbc:ID>S</cbc:ID>
<cbc:Percent>15</cbc:Percent>
<cac:TaxScheme>
<cbc:ID>GST</cbc:ID>
</cac:TaxScheme>
</cac:ClassifiedTaxCategory>
</cac:Item>
<cac:Price>
<cbc:PriceAmount currencyID="NZD">7.50</cbc:PriceAmount>
</cac:Price>
</cac:InvoiceLine>
</Invoice>
"""


def test_extraction():
    """Test that all fields are correctly extracted"""
    print("=" * 80)
    print("TESTING ENHANCED INVOICE EXTRACTION")
    print("=" * 80)
    
    # Extract fields
    invoice_data = extract_invoice_fields(SAMPLE_INVOICE_XML)
    
    print(f"\nTotal fields extracted: {len(invoice_data)}\n")
    
    # Test required fields (including new tax_percentage)
    print("REQUIRED FIELDS:")
    print("-" * 80)
    for field in REQUIRED_FIELDS:
        value = invoice_data.get(field)
        status = "OK" if value else "MISSING"
        print(f"[{status}] {field}: {value}")
    
    # Check if all required fields present
    missing = find_missing_fields(invoice_data)
    print(f"\n{'✅ All required fields present!' if not missing else f'❌ Missing {len(missing)} required fields: {missing}'}")
    
    # Test document metadata
    print("\n📄 DOCUMENT METADATA:")
    print("-" * 80)
    metadata_fields = ['customization_id', 'profile_id', 'note', 'accounting_cost', 'buyer_reference']
    for field in metadata_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "⚠️"
        print(f"{status} {field}: {value}")
    
    # Test references
    print("\n🔗 REFERENCES:")
    print("-" * 80)
    ref_fields = ['order_reference', 'sales_order_id', 'contract_reference', 'project_reference']
    for field in ref_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "⚠️"
        print(f"{status} {field}: {value}")
    
    # Test tax breakdown (CRITICAL - user reported this as missing)
    print("\n💰 TAX BREAKDOWN (User Reported Missing):")
    print("-" * 80)
    tax_fields = ['tax_amount', 'tax_percentage', 'taxable_amount', 'tax_category_id', 'tax_scheme']
    for field in tax_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "❌"
        print(f"{status} {field}: {value}")
    
    # Test monetary totals (CRITICAL - user reported this as missing)
    print("\n💵 MONETARY TOTALS (User Reported Missing):")
    print("-" * 80)
    monetary_fields = ['line_extension_amount', 'subtotal', 'total', 'payable_amount', 
                       'allowance_total_amount', 'prepaid_amount']
    for field in monetary_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "❌"
        print(f"{status} {field}: {value}")
    
    # Test payment info
    print("\n💳 PAYMENT INFORMATION:")
    print("-" * 80)
    payment_fields = ['payment_means_code', 'payment_means_name', 'payment_id', 'payment_terms']
    for field in payment_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "⚠️"
        print(f"{status} {field}: {value}")
    if 'payee_financial_account' in invoice_data:
        print(f"✅ payee_financial_account: {invoice_data['payee_financial_account']}")
    
    # Test delivery info
    print("\n🚚 DELIVERY INFORMATION:")
    print("-" * 80)
    delivery_fields = ['delivery_date', 'delivery_location_id', 'delivery_party_name']
    for field in delivery_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "⚠️"
        print(f"{status} {field}: {value}")
    
    # Test allowances/charges
    print("\n💸 ALLOWANCES & CHARGES:")
    print("-" * 80)
    if 'allowances_charges' in invoice_data:
        acs = invoice_data['allowances_charges']
        print(f"✅ Found {len(acs)} allowance/charge item(s)")
        for idx, ac in enumerate(acs):
            print(f"  Item {idx + 1}: {ac}")
    else:
        print("⚠️ No allowances/charges found")
    
    # Test contact information
    print("\n📞 CONTACT INFORMATION:")
    print("-" * 80)
    contact_fields = ['customer_contact_name', 'customer_contact_telephone', 'customer_contact_email',
                      'supplier_contact_name', 'supplier_contact_telephone', 'supplier_contact_email']
    for field in contact_fields:
        value = invoice_data.get(field)
        status = "✅" if value else "⚠️"
        print(f"{status} {field}: {value}")
    
    # Test line items (CRITICAL - user reported product IDs missing)
    print("\n📦 LINE ITEMS (User Reported Product IDs Missing):")
    print("-" * 80)
    if 'line_items' in invoice_data:
        items = invoice_data['line_items']
        print(f"✅ Found {len(items)} line item(s)\n")
        for idx, item in enumerate(items):
            print(f"  Line {idx + 1}:")
            print(f"    Item Name: {item.get('item_name')}")
            print(f"    Buyer Item ID: {item.get('buyer_item_id')} {'✅' if item.get('buyer_item_id') else '❌'}")
            print(f"    Seller Item ID: {item.get('seller_item_id')} {'✅' if item.get('seller_item_id') else '❌'}")
            print(f"    Standard Item ID: {item.get('standard_item_id')} {'✅' if item.get('standard_item_id') else '❌'}")
            print(f"    Tax Percent: {item.get('tax_percent')}% {'✅' if item.get('tax_percent') else '❌'}")
            print(f"    Origin Country: {item.get('origin_country')} {'✅' if item.get('origin_country') else '⚠️'}")
            print(f"    Line Note: {item.get('line_note')} {'✅' if item.get('line_note') else '⚠️'}")
            print(f"    Order Line Ref: {item.get('order_line_reference')} {'✅' if item.get('order_line_reference') else '⚠️'}")
            print()
    
    # Final summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total fields extracted: {len(invoice_data)}")
    print(f"Required fields status: {'✅ ALL PRESENT' if not missing else f'❌ MISSING {len(missing)}'}")
    print(f"Tax percentage (new required): {'✅ PRESENT' if invoice_data.get('tax_percentage') else '❌ MISSING'}")
    print(f"Product IDs in line items: {'✅ PRESENT' if any(item.get('buyer_item_id') or item.get('seller_item_id') for item in invoice_data.get('line_items', [])) else '❌ MISSING'}")
    
    # Determine overall status
    critical_checks = [
        not missing,  # All required fields present
        invoice_data.get('tax_percentage'),  # Tax percentage present
        invoice_data.get('tax_amount'),  # Tax amount present
        invoice_data.get('line_extension_amount'),  # Line extension amount present
        any(item.get('buyer_item_id') or item.get('seller_item_id') for item in invoice_data.get('line_items', []))  # Product IDs present
    ]
    
    if all(critical_checks):
        print("\n🎉 TEST PASSED: All critical fields extracted successfully!")
        return True
    else:
        print("\n❌ TEST FAILED: Some critical fields are missing")
        return False


if __name__ == "__main__":
    success = test_extraction()
    sys.exit(0 if success else 1)
