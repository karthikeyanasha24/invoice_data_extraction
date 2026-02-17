"""
Test script for UBL 2.1 Invoice formatting and validation
"""

from app.utils.ubl_formatter import format_ubl_invoice, validate_ubl_completeness
from lxml import etree

# Sample UBL XML (same as used for other format testing)
SAMPLE_UBL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
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
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:PaymentTerms>
    <cbc:Note>Payment within 30 days</cbc:Note>
  </cac:PaymentTerms>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="NZD">208.11</cbc:TaxAmount>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="NZD">1487.40</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="NZD">1387.40</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="NZD">1595.51</cbc:TaxInclusiveAmount>
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
      <cac:StandardItemIdentification>
        <cbc:ID schemeID="0088">21382183120983</cbc:ID>
      </cac:StandardItemIdentification>
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
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount currencyID="NZD">7.50</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>
</Invoice>
"""

def main():
    print("=" * 80)
    print("TESTING UBL 2.1 INVOICE FORMATTING")
    print("=" * 80)
    print()
    
    # Display input info
    print("[INPUT] UBL 2.1 Invoice XML")
    print(f"   Size: {len(SAMPLE_UBL_XML)} bytes")
    print()
    
    # Test 1: Format and validate UBL
    print("[TEST 1] Format and validate UBL...")
    print()
    
    formatted_xml, is_valid, message = format_ubl_invoice(SAMPLE_UBL_XML)
    
    if is_valid:
        print(f"   [SUCCESS] {message}")
    else:
        print(f"   [WARNING] {message}")
    
    print(f"   Output size: {len(formatted_xml)} bytes")
    print()
    
    # Test 2: Detailed validation
    print("[TEST 2] Detailed validation check...")
    print()
    
    stats = validate_ubl_completeness(SAMPLE_UBL_XML)
    
    if stats.get('is_valid'):
        print("   [OK] UBL structure is valid")
    else:
        print("   [WARNING] UBL validation issues found")
    
    print(f"   Invoice ID: {stats.get('invoice_id', 'N/A')}")
    print(f"   Issue Date: {stats.get('issue_date', 'N/A')}")
    print(f"   Due Date: {stats.get('due_date', 'N/A')}")
    print(f"   Currency: {stats.get('currency', 'N/A')}")
    print(f"   Supplier: {stats.get('supplier', 'N/A')}")
    print(f"   Customer: {stats.get('customer', 'N/A')}")
    print(f"   Line Items: {stats.get('line_items', 0)}")
    print(f"   Has Totals: {'Yes' if stats.get('has_totals') else 'No'}")
    print(f"   Has Tax Info: {'Yes' if stats.get('has_tax_info') else 'No'}")
    print(f"   Has Payment Terms: {'Yes' if stats.get('has_payment_terms') else 'No'}")
    print()
    
    if stats.get('validation_errors'):
        print("   [ERRORS]")
        for error in stats['validation_errors']:
            print(f"      - {error}")
        print()
    
    if stats.get('validation_warnings'):
        print("   [WARNINGS]")
        for warning in stats['validation_warnings']:
            print(f"      - {warning}")
        print()
    
    # Test 3: Verify XML is well-formed
    print("[TEST 3] Verify output XML is well-formed...")
    try:
        root = etree.fromstring(formatted_xml)
        print(f"   [OK] XML is well-formed")
        print(f"   Root element: {etree.QName(root.tag).localname}")
        
        # Count elements
        namespaces = {
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
        }
        
        invoice_id = root.find('.//cbc:ID', namespaces)
        line_count = len(root.findall('.//cac:InvoiceLine', namespaces))
        
        print(f"   Invoice Number: {invoice_id.text if invoice_id is not None else 'N/A'}")
        print(f"   Line Items Found: {line_count}")
    except Exception as e:
        print(f"   [ERROR] XML parsing failed: {e}")
    
    print()
    
    # Test 4: Check pretty printing
    print("[TEST 4] Check formatting (pretty print)...")
    formatted_str = formatted_xml.decode('utf-8')
    lines = formatted_str.split('\n')
    print(f"   Total lines: {len(lines)}")
    print(f"   Has XML declaration: {lines[0].startswith('<?xml')}")
    
    # Check indentation
    indented_lines = [line for line in lines if line.startswith('  ') and line.strip()]
    print(f"   Indented lines: {len(indented_lines)}")
    print(f"   Pretty printed: {'Yes' if len(indented_lines) > 10 else 'No'}")
    print()
    
    # Save output
    output_path = "test_ubl_output.xml"
    with open(output_path, 'wb') as f:
        f.write(formatted_xml)
    
    import os
    abs_path = os.path.abspath(output_path)
    print(f"[SAVED] Output saved to: {abs_path}")
    print()
    
    # Show first few lines
    print("[PREVIEW] First 10 lines of output:")
    print("-" * 80)
    for i, line in enumerate(lines[:10], 1):
        print(f"   {i:2d}: {line}")
    print("-" * 80)
    print()
    
    # Summary
    print("=" * 80)
    if is_valid and stats.get('is_valid'):
        print("[SUCCESS] ALL TESTS PASSED!")
    else:
        print("[WARNING] Some validation issues found (but XML is formatted)")
    print("=" * 80)
    print()
    
    print("Expected output after formatting:")
    print("  - File extension: .xml")
    print("  - Content type: application/xml")
    print("  - Format: UBL 2.1 (Universal Business Language)")
    print("  - Root element: <Invoice>")
    print("  - Contains: All original data, properly formatted with indentation")
    print("  - Namespaces: cac, cbc, and default Invoice namespace")
    print("  - Ready for: Direct use, validation, or further processing")
    print("=" * 80)

if __name__ == "__main__":
    main()
