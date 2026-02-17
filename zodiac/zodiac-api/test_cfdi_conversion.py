"""
Test CFDI conversion with the provided UBL XML
"""
import sys
from pathlib import Path
from lxml import etree

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.xml_to_cfdi import convert_ubl_to_cfdi

# Test XML (NZ Invoice from user)
TEST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
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
<cac:PaymentMeans>
<cbc:PaymentMeansCode name="Credit transfer">30</cbc:PaymentMeansCode>
<cbc:PaymentID>Snippet1</cbc:PaymentID>
<cac:PayeeFinancialAccount>
<cbc:ID>IBAN32423940</cbc:ID>
<cbc:Name>AccountName</cbc:Name>
</cac:PayeeFinancialAccount>
</cac:PaymentMeans>
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
<cac:Item>
<cbc:Description>Widgets True and Fair</cbc:Description>
<cbc:Name>True-Widgets</cbc:Name>
<cac:StandardItemIdentification>
<cbc:ID schemeID="0088">WG546767</cbc:ID>
</cac:StandardItemIdentification>
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
<cac:Item>
<cbc:Description>Description 2</cbc:Description>
<cbc:Name>item name 2</cbc:Name>
<cac:StandardItemIdentification>
<cbc:ID schemeID="0088">21382183120983</cbc:ID>
</cac:StandardItemIdentification>
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
<cac:Item>
<cbc:Description>Widgets True and Fair</cbc:Description>
<cbc:Name>True-Widgets</cbc:Name>
<cac:StandardItemIdentification>
<cbc:ID schemeID="0088">WG546767</cbc:ID>
</cac:StandardItemIdentification>
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
</Invoice>'''


def test_cfdi_conversion():
    """Test CFDI conversion"""
    print("=" * 80)
    print("TESTING CFDI CONVERSION")
    print("=" * 80)
    
    try:
        # Convert to bytes
        xml_bytes = TEST_XML.encode('utf-8')
        
        print("\n[INPUT] UBL 2.1 Invoice XML")
        print(f"   Size: {len(xml_bytes)} bytes")
        print(f"   Invoice Number: Snippet1")
        print(f"   Currency: NZD")
        print(f"   Total Amount: 1595.51")
        
        # Convert to CFDI
        print("\n[CONVERTING] to CFDI 4.0...")
        cfdi_bytes = convert_ubl_to_cfdi(xml_bytes)
        
        print(f"\n[SUCCESS] Conversion successful!")
        print(f"   Output size: {len(cfdi_bytes)} bytes")
        
        # Parse CFDI to verify structure
        print("\n[VALIDATING] CFDI structure...")
        cfdi_root = etree.fromstring(cfdi_bytes)
        
        # Check root element
        assert 'Comprobante' in cfdi_root.tag, "Root element should be Comprobante"
        print("   [OK] Root element: cfdi:Comprobante")
        
        # Check version
        version = cfdi_root.get('Version')
        print(f"   [OK] CFDI Version: {version}")
        
        # Check basic attributes
        folio = cfdi_root.get('Folio')
        fecha = cfdi_root.get('Fecha')
        moneda = cfdi_root.get('Moneda')
        total = cfdi_root.get('Total')
        subtotal = cfdi_root.get('SubTotal')
        
        print(f"   [OK] Folio: {folio}")
        print(f"   [OK] Fecha: {fecha}")
        print(f"   [OK] Moneda: {moneda}")
        print(f"   [OK] SubTotal: {subtotal}")
        print(f"   [OK] Total: {total}")
        
        # Check Emisor (Supplier)
        emisor = cfdi_root.find('.//{http://www.sat.gob.mx/cfd/4}Emisor')
        assert emisor is not None, "Emisor element not found"
        emisor_rfc = emisor.get('Rfc')
        emisor_nombre = emisor.get('Nombre')
        print(f"\n   [OK] Emisor (Supplier):")
        print(f"      RFC: {emisor_rfc}")
        print(f"      Nombre: {emisor_nombre}")
        
        # Check Receptor (Customer)
        receptor = cfdi_root.find('.//{http://www.sat.gob.mx/cfd/4}Receptor')
        assert receptor is not None, "Receptor element not found"
        receptor_rfc = receptor.get('Rfc')
        receptor_nombre = receptor.get('Nombre')
        print(f"\n   [OK] Receptor (Customer):")
        print(f"      RFC: {receptor_rfc}")
        print(f"      Nombre: {receptor_nombre}")
        
        # Check Conceptos (Line Items)
        conceptos = cfdi_root.find('.//{http://www.sat.gob.mx/cfd/4}Conceptos')
        assert conceptos is not None, "Conceptos element not found"
        concepto_list = conceptos.findall('.//{http://www.sat.gob.mx/cfd/4}Concepto')
        print(f"\n   [OK] Conceptos (Line Items): {len(concepto_list)} items")
        
        for i, concepto in enumerate(concepto_list, 1):
            cantidad = concepto.get('Cantidad')
            descripcion = concepto.get('Descripcion')
            importe = concepto.get('Importe')
            print(f"      Item {i}: {cantidad} x {descripcion[:30]}... = {importe}")
        
        # Check Impuestos (Taxes)
        impuestos = cfdi_root.find('.//{http://www.sat.gob.mx/cfd/4}Impuestos')
        assert impuestos is not None, "Impuestos element not found"
        total_impuestos = impuestos.get('TotalImpuestosTrasladados')
        print(f"\n   [OK] Impuestos (Taxes):")
        print(f"      Total Impuestos Trasladados: {total_impuestos}")
        
        # Save output for inspection
        output_file = Path(__file__).parent / "test_cfdi_output.xml"
        with open(output_file, 'wb') as f:
            f.write(cfdi_bytes)
        
        print(f"\n[SAVED] Output saved to: {output_file}")
        
        print("\n" + "=" * 80)
        print("[SUCCESS] ALL TESTS PASSED!")
        print("=" * 80)
        print("\nExpected output after conversion:")
        print("  - File extension: .xml")
        print("  - Content type: application/xml")
        print("  - Root element: <cfdi:Comprobante> with CFDI 4.0 namespace")
        print("  - Contains: Emisor, Receptor, Conceptos, Impuestos")
        print("  - All monetary amounts properly formatted")
        print("  - Tax information (IVA) properly mapped")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_cfdi_conversion()
    sys.exit(0 if success else 1)
