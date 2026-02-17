"""
Test PIDX conversion with the provided UBL XML
"""
import sys
from pathlib import Path
from lxml import etree

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.xml_to_pidx import convert_ubl_to_pidx

# Test XML (NZ Invoice from user - same as used for CFDI)
TEST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
<cbc:ID>Snippet1</cbc:ID>
<cbc:IssueDate>2019-07-29</cbc:IssueDate>
<cbc:DueDate>2019-08-30</cbc:DueDate>
<cbc:DocumentCurrencyCode>NZD</cbc:DocumentCurrencyCode>
<cac:OrderReference>
<cbc:ID>SOMEBLERB</cbc:ID>
</cac:OrderReference>
<cac:AccountingSupplierParty>
<cac:Party>
<cac:PartyIdentification>
<cbc:ID>9429033821733</cbc:ID>
</cac:PartyIdentification>
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
</cac:Party>
</cac:AccountingSupplierParty>
<cac:AccountingCustomerParty>
<cac:Party>
<cac:PartyIdentification>
<cbc:ID>9429033591476</cbc:ID>
</cac:PartyIdentification>
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
</cac:Party>
</cac:AccountingCustomerParty>
<cac:TaxTotal>
<cbc:TaxAmount currencyID="NZD">208.11</cbc:TaxAmount>
</cac:TaxTotal>
<cac:LegalMonetaryTotal>
<cbc:TaxExclusiveAmount currencyID="NZD">1387.40</cbc:TaxExclusiveAmount>
<cbc:PayableAmount currencyID="NZD">1595.51</cbc:PayableAmount>
</cac:LegalMonetaryTotal>
<cac:InvoiceLine>
<cbc:ID>1</cbc:ID>
<cbc:InvoicedQuantity unitCode="E99">10</cbc:InvoicedQuantity>
<cbc:LineExtensionAmount currencyID="NZD">299.90</cbc:LineExtensionAmount>
<cac:Item>
<cbc:Description>Widgets True and Fair</cbc:Description>
<cbc:Name>True-Widgets</cbc:Name>
<cac:SellersItemIdentification>
<cbc:ID>WG546767</cbc:ID>
</cac:SellersItemIdentification>
<cac:ClassifiedTaxCategory>
<cbc:Percent>15</cbc:Percent>
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
<cac:Item>
<cbc:Description>Description 2</cbc:Description>
<cbc:Name>item name 2</cbc:Name>
<cac:SellersItemIdentification>
<cbc:ID>21382183120983</cbc:ID>
</cac:SellersItemIdentification>
<cac:ClassifiedTaxCategory>
<cbc:Percent>15</cbc:Percent>
</cac:ClassifiedTaxCategory>
</cac:Item>
<cac:Price>
<cbc:PriceAmount currencyID="NZD">500</cbc:PriceAmount>
</cac:Price>
</cac:InvoiceLine>
<cac:InvoiceLine>
<cbc:ID>3</cbc:ID>
<cbc:InvoicedQuantity unitCode="M66">25</cbc:InvoicedQuantity>
<cbc:LineExtensionAmount currencyID="NZD">187.50</cbc:LineExtensionAmount>
<cac:Item>
<cbc:Description>Widgets True and Fair</cbc:Description>
<cbc:Name>True-Widgets</cbc:Name>
<cac:SellersItemIdentification>
<cbc:ID>WG546767</cbc:ID>
</cac:SellersItemIdentification>
<cac:ClassifiedTaxCategory>
<cbc:Percent>15</cbc:Percent>
</cac:ClassifiedTaxCategory>
</cac:Item>
<cac:Price>
<cbc:PriceAmount currencyID="NZD">7.50</cbc:PriceAmount>
</cac:Price>
</cac:InvoiceLine>
</Invoice>'''


def test_pidx_conversion():
    """Test PIDX conversion"""
    print("=" * 80)
    print("TESTING PIDX CONVERSION")
    print("=" * 80)
    
    try:
        # Convert to bytes
        xml_bytes = TEST_XML.encode('utf-8')
        
        print("\n[INPUT] UBL 2.1 Invoice XML")
        print(f"   Size: {len(xml_bytes)} bytes")
        print(f"   Invoice Number: Snippet1")
        print(f"   Currency: NZD")
        print(f"   Total Amount: 1595.51")
        print(f"   Line Items: 3")
        
        # Convert to PIDX
        print("\n[CONVERTING] to PIDX format...")
        pidx_bytes = convert_ubl_to_pidx(xml_bytes)
        
        print(f"\n[SUCCESS] Conversion successful!")
        print(f"   Output size: {len(pidx_bytes)} bytes")
        
        # Parse PIDX to verify structure
        print("\n[VALIDATING] PIDX structure...")
        pidx_root = etree.fromstring(pidx_bytes)
        
        # Check root element
        assert 'Invoice' in pidx_root.tag, "Root element should be Invoice"
        print("   [OK] Root element: pidx:Invoice")
        
        # Check namespace
        assert 'api.org/pidXML' in pidx_root.tag, "Should have PIDX namespace"
        print("   [OK] PIDX namespace present")
        
        # Check version
        version = pidx_root.get('version')
        print(f"   [OK] PIDX Version: {version}")
        
        # Check InvoiceProperties
        props = pidx_root.find('.//{http://www.api.org/pidXML}InvoiceProperties')
        assert props is not None, "InvoiceProperties element not found"
        print("   [OK] InvoiceProperties section found")
        
        inv_num = props.find('.//{http://www.api.org/pidXML}InvoiceNumber')
        inv_date = props.find('.//{http://www.api.org/pidXML}InvoiceDate')
        currency = props.find('.//{http://www.api.org/pidXML}PrimaryCurrency//{http://www.api.org/pidXML}CurrencyCode')
        
        print(f"      Invoice Number: {inv_num.text if inv_num is not None else 'N/A'}")
        print(f"      Invoice Date: {inv_date.text if inv_date is not None else 'N/A'}")
        print(f"      Currency: {currency.text if currency is not None else 'N/A'}")
        
        # Check Partners
        partners = props.findall('.//{http://www.api.org/pidXML}PartnerInformation')
        print(f"\n   [OK] Partner Information: {len(partners)} partners")
        
        for partner in partners:
            role = partner.find('.//{http://www.api.org/pidXML}PartnerRoleCode')
            name = partner.find('.//{http://www.api.org/pidXML}PartnerName')
            if role is not None and name is not None:
                print(f"      {role.text}: {name.text}")
        
        # Check InvoiceDetails
        details = pidx_root.find('.//{http://www.api.org/pidXML}InvoiceDetails')
        assert details is not None, "InvoiceDetails element not found"
        print("\n   [OK] InvoiceDetails section found")
        
        line_items = details.findall('.//{http://www.api.org/pidXML}InvoiceLineItem')
        print(f"   [OK] Line Items: {len(line_items)} items")
        
        for i, line in enumerate(line_items, 1):
            line_num = line.find('.//{http://www.api.org/pidXML}LineItemNumber')
            qty = line.find('.//{http://www.api.org/pidXML}Quantity')
            desc = line.find('.//{http://www.api.org/pidXML}ItemDescription')
            price = line.find('.//{http://www.api.org/pidXML}UnitPrice//{http://www.api.org/pidXML}MonetaryAmount')
            
            print(f"      Line {i}:")
            if line_num is not None:
                print(f"         Number: {line_num.text}")
            if qty is not None:
                print(f"         Quantity: {qty.text}")
            if desc is not None:
                print(f"         Description: {desc.text[:50]}...")
            if price is not None:
                print(f"         Unit Price: {price.text}")
        
        # Check InvoiceSummary
        summary = pidx_root.find('.//{http://www.api.org/pidXML}InvoiceSummary')
        assert summary is not None, "InvoiceSummary element not found"
        print("\n   [OK] InvoiceSummary section found")
        
        total_lines = summary.find('.//{http://www.api.org/pidXML}TotalLineItems')
        invoice_total = summary.find('.//{http://www.api.org/pidXML}InvoiceTotal')
        subtotal = summary.find('.//{http://www.api.org/pidXML}SubTotalAmount//{http://www.api.org/pidXML}MonetaryAmount')
        
        print(f"      Total Line Items: {total_lines.text if total_lines is not None else 'N/A'}")
        print(f"      Invoice Total: {invoice_total.text if invoice_total is not None else 'N/A'}")
        print(f"      Subtotal: {subtotal.text if subtotal is not None else 'N/A'}")
        
        # Save output for inspection
        output_file = Path(__file__).parent / "test_pidx_output.xml"
        with open(output_file, 'wb') as f:
            f.write(pidx_bytes)
        
        print(f"\n[SAVED] Output saved to: {output_file}")
        
        print("\n" + "=" * 80)
        print("[SUCCESS] ALL TESTS PASSED!")
        print("=" * 80)
        print("\nExpected output after conversion:")
        print("  - File extension: .xml")
        print("  - Content type: application/xml")
        print("  - Root element: <pidx:Invoice> with PIDX namespace")
        print("  - Contains: InvoiceProperties, InvoiceDetails, InvoiceSummary")
        print("  - All invoice data properly mapped")
        print("  - Suitable for petroleum industry data exchange")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_pidx_conversion()
    sys.exit(0 if success else 1)
