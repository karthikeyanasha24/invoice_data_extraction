"""
Test script for X12 810 Invoice conversion
Tests conversion from UBL 2.1 to X12 EDI format
"""

from app.utils.xml_to_x12 import convert_xml_to_x12_content

# Sample UBL XML (same as used for CFDI/PIDX testing)
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
  <cac:BillingReference>
    <cac:InvoiceDocumentReference>
      <cbc:ID>THEIDGOESHERE</cbc:ID>
      <cbc:IssueDate>2019-07-30</cbc:IssueDate>
    </cac:InvoiceDocumentReference>
  </cac:BillingReference>
  <cac:DespatchDocumentReference>
    <cbc:ID>DDR-REF</cbc:ID>
  </cac:DespatchDocumentReference>
  <cac:ReceiptDocumentReference>
    <cbc:ID>RD-REF</cbc:ID>
  </cac:ReceiptDocumentReference>
  <cac:OriginatorDocumentReference>
    <cbc:ID>OD-REF</cbc:ID>
  </cac:OriginatorDocumentReference>
  <cac:ContractDocumentReference>
    <cbc:ID>CD-REF</cbc:ID>
  </cac:ContractDocumentReference>
  <cac:ProjectReference>
    <cbc:ID>PR-REF</cbc:ID>
  </cac:ProjectReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cbc:EndpointID schemeID="0088">9429033821733</cbc:EndpointID>
      <cac:PartyIdentification>
        <cbc:ID>9429033821733</cbc:ID>
      </cac:PartyIdentification>
      <cac:PartyName>
        <cbc:Name>SupplierTradingName Ltd.</cbc:Name>
      </cac:PartyName>
      <cac:PostalAddress>
        <cbc:StreetName>Main street 1</cbc:StreetName>
        <cbc:AdditionalStreetName>Postbox 123</cbc:AdditionalStreetName>
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
      <cac:PartyIdentification>
        <cbc:ID schemeID="0088">9429033591476</cbc:ID>
      </cac:PartyIdentification>
      <cac:PartyName>
        <cbc:Name>Trotters Trading Co Ltd</cbc:Name>
      </cac:PartyName>
      <cac:PostalAddress>
        <cbc:StreetName>100 Queen Street</cbc:StreetName>
        <cbc:AdditionalStreetName>Po box 878</cbc:AdditionalStreetName>
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
  <cac:PayeeParty>
    <cac:PartyIdentification>
      <cbc:ID>schemeID="SEPA" SR678659898009</cbc:ID>
    </cac:PartyIdentification>
    <cac:PartyName>
      <cbc:Name>Mr Anderson</cbc:Name>
    </cac:PartyName>
    <cac:PartyLegalEntity>
      <cbc:CompanyID schemeID="0088">9429033591476</cbc:CompanyID>
    </cac:PartyLegalEntity>
  </cac:PayeeParty>
  <cac:TaxRepresentativeParty>
    <cac:PartyName>
      <cbc:Name>Mr Wilson</cbc:Name>
    </cac:PartyName>
    <cac:PostalAddress>
      <cbc:StreetName>16 Stout Street</cbc:StreetName>
      <cbc:AdditionalStreetName>Po box 878</cbc:AdditionalStreetName>
      <cbc:CityName>Wellington</cbc:CityName>
      <cbc:PostalZone>1111</cbc:PostalZone>
      <cbc:CountrySubentity>Kapiti Coast</cbc:CountrySubentity>
      <cac:AddressLine>
        <cbc:Line>Out-in-theSticks</cbc:Line>
      </cac:AddressLine>
      <cac:Country>
        <cbc:IdentificationCode>NZ</cbc:IdentificationCode>
      </cac:Country>
    </cac:PostalAddress>
    <cac:PartyTaxScheme>
      <cbc:CompanyID>777-777-777</cbc:CompanyID>
      <cac:TaxScheme>
        <cbc:ID>GST</cbc:ID>
      </cac:TaxScheme>
    </cac:PartyTaxScheme>
  </cac:TaxRepresentativeParty>
  <cac:Delivery>
    <cbc:ActualDeliveryDate>2019-06-01</cbc:ActualDeliveryDate>
    <cac:DeliveryLocation>
      <cbc:ID schemeID="0088">9429033591476</cbc:ID>
      <cac:Address>
        <cbc:StreetName>Delivery street 2</cbc:StreetName>
        <cbc:AdditionalStreetName>Building 56</cbc:AdditionalStreetName>
        <cbc:CityName>Auckland</cbc:CityName>
        <cbc:PostalZone>21234</cbc:PostalZone>
        <cbc:CountrySubentity>Northland</cbc:CountrySubentity>
        <cac:AddressLine>
          <cbc:Line>One-Tree-Hill</cbc:Line>
        </cac:AddressLine>
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
    <cac:PaymentMandate>
      <cbc:ID>SEPA3245543940</cbc:ID>
      <cac:PayerFinancialAccount>
        <cbc:ID>BIC32778</cbc:ID>
      </cac:PayerFinancialAccount>
    </cac:PaymentMandate>
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
    <cac:TaxCategory>
      <cbc:ID>S</cbc:ID>
      <cbc:Percent>15</cbc:Percent>
      <cac:TaxScheme>
        <cbc:ID>GST</cbc:ID>
      </cac:TaxScheme>
    </cac:TaxCategory>
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
    <cac:InvoicePeriod>
      <cbc:StartDate>2019-06-01</cbc:StartDate>
      <cbc:EndDate>2019-07-30</cbc:EndDate>
    </cac:InvoicePeriod>
    <cac:OrderLineReference>
      <cbc:LineID>123</cbc:LineID>
    </cac:OrderLineReference>
    <cac:DocumentReference>
      <cbc:ID schemeID="HWB">9000074677</cbc:ID>
      <cbc:DocumentTypeCode>130</cbc:DocumentTypeCode>
    </cac:DocumentReference>
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
      <cac:CommodityClassification>
        <cbc:ItemClassificationCode listID="SRV">09348023</cbc:ItemClassificationCode>
      </cac:CommodityClassification>
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
      <cac:AllowanceCharge>
        <cbc:ChargeIndicator>false</cbc:ChargeIndicator>
        <cbc:Amount currencyID="NZD">0.00</cbc:Amount>
        <cbc:BaseAmount currencyID="NZD">29.99</cbc:BaseAmount>
      </cac:AllowanceCharge>
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
      <cac:CommodityClassification>
        <cbc:ItemClassificationCode listID="SRV">09348023</cbc:ItemClassificationCode>
      </cac:CommodityClassification>
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
    <cac:InvoicePeriod>
      <cbc:StartDate>2019-06-01</cbc:StartDate>
      <cbc:EndDate>2019-07-30</cbc:EndDate>
    </cac:InvoicePeriod>
    <cac:OrderLineReference>
      <cbc:LineID>123</cbc:LineID>
    </cac:OrderLineReference>
    <cac:DocumentReference>
      <cbc:ID schemeID="HWB">9000074677</cbc:ID>
      <cbc:DocumentTypeCode>130</cbc:DocumentTypeCode>
    </cac:DocumentReference>
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
      <cac:CommodityClassification>
        <cbc:ItemClassificationCode listID="SRV">09348023</cbc:ItemClassificationCode>
      </cac:CommodityClassification>
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
      <cac:AllowanceCharge>
        <cbc:ChargeIndicator>false</cbc:ChargeIndicator>
        <cbc:Amount currencyID="NZD">0.00</cbc:Amount>
        <cbc:BaseAmount currencyID="NZD">7.50</cbc:BaseAmount>
      </cac:AllowanceCharge>
    </cac:Price>
  </cac:InvoiceLine>
</Invoice>
"""

def main():
    print("=" * 80)
    print("TESTING X12 CONVERSION")
    print("=" * 80)
    print()
    
    # Display input info
    print("[INPUT] UBL 2.1 Invoice XML")
    print(f"   Size: {len(SAMPLE_UBL_XML)} bytes")
    print(f"   Invoice Number: Snippet1")
    print(f"   Currency: NZD")
    print(f"   Total Amount: 1595.51")
    print(f"   Line Items: 3")
    print()
    
    # Convert to X12
    print("[CONVERTING] to X12 format...")
    print()
    
    try:
        x12_content = convert_xml_to_x12_content(SAMPLE_UBL_XML)
        
        if not x12_content:
            print("[ERROR] Conversion returned empty content")
            return
        
        print("[SUCCESS] Conversion successful!")
        print(f"   Output size: {len(x12_content)} characters")
        print()
        
        # Validate X12 structure
        print("[VALIDATING] X12 structure...")
        
        segments = x12_content.strip().split('\n')
        segment_counts = {}
        
        for seg in segments:
            seg_type = seg.split('*')[0] if '*' in seg else seg.split('~')[0]
            segment_counts[seg_type] = segment_counts.get(seg_type, 0) + 1
        
        # Check required segments
        required_segments = ['ISA', 'GS', 'ST', 'BIG', 'N1', 'SE', 'GE', 'IEA']
        all_present = True
        
        for req_seg in required_segments:
            if req_seg in segment_counts:
                print(f"   [OK] {req_seg} segment present ({segment_counts[req_seg]})")
            else:
                print(f"   [MISSING] {req_seg} segment not found")
                all_present = False
        
        print()
        
        # Display key segments
        print("[KEY SEGMENTS]")
        for seg in segments[:5]:
            seg_type = seg.split('*')[0] if '*' in seg else seg[:3]
            if seg_type in ['ISA', 'GS', 'ST', 'BIG']:
                print(f"   {seg_type}: {seg[:80]}...")
        
        print()
        
        # Count line items
        it1_count = segment_counts.get('IT1', 0)
        print(f"[LINE ITEMS] Found {it1_count} IT1 segments (expected 3)")
        
        # Show some line item details
        for seg in segments:
            if seg.startswith('IT1'):
                parts = seg.split('*')
                if len(parts) >= 5:
                    line_num = parts[1]
                    quantity = parts[2]
                    price = parts[4]
                    product = parts[7] if len(parts) > 7 else 'N/A'
                    print(f"   Line {line_num}: Qty={quantity}, Price={price}, Product={product}")
        
        print()
        
        # Check total
        for seg in segments:
            if seg.startswith('TDS'):
                parts = seg.split('*')
                if len(parts) >= 2:
                    total = parts[1].rstrip('~')
                    # Convert from integer format (159551 = 1595.51)
                    total_decimal = float(total) / 100
                    print(f"[TOTAL] TDS segment: {total} (${total_decimal:.2f})")
        
        print()
        
        # Save output
        output_path = "test_x12_output.edi"
        with open(output_path, 'w') as f:
            f.write(x12_content)
        
        import os
        abs_path = os.path.abspath(output_path)
        print(f"[SAVED] Output saved to: {abs_path}")
        print()
        
        # Summary
        print("=" * 80)
        if all_present and it1_count == 3:
            print("[SUCCESS] ALL TESTS PASSED!")
        else:
            print("[WARNING] Some validation checks failed")
        print("=" * 80)
        print()
        
        print("Expected output after conversion:")
        print("  - File extension: .edi")
        print("  - Content type: text/plain (X12 EDI)")
        print("  - Format: X12 810 (Invoice)")
        print("  - Structure: ISA/GS/ST/BIG/N1/IT1/TDS/SE/GE/IEA segments")
        print("  - Delimiter: * (asterisk) with ~ (tilde) segment terminator")
        print("  - Contains: Supplier, Customer, 3 line items, totals")
        print("=" * 80)
        
    except Exception as e:
        print(f"[ERROR] Conversion failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
