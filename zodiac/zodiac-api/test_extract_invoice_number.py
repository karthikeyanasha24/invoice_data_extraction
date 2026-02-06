"""
Test invoice number extraction from different XML formats
"""
from lxml import etree

def extract_invoice_number_from_xml(xml_content: str):
    """Extract invoice number from XML content (supports both UBL and SAT CFDI formats)"""
    try:
        root = etree.fromstring(xml_content.encode('utf-8'))
        
        # Try UBL format first (cbc:ID element)
        ubl_namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        }
        invoice_id_elem = root.find('.//cbc:ID', ubl_namespaces)
        if invoice_id_elem is not None and invoice_id_elem.text:
            invoice_number = invoice_id_elem.text.strip().upper()
            print(f"[OK] Extracted UBL invoice ID: {invoice_number}")
            return invoice_number
        
        # Try SAT CFDI format (Serie + Folio attributes)
        cfdi_namespaces = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'cfdi3': 'http://www.sat.gob.mx/cfd/3',
        }
        
        # Try CFDI 4.0
        comprobante = root if root.tag.endswith('Comprobante') else root.find('.//cfdi:Comprobante', cfdi_namespaces)
        
        # Try CFDI 3.3 if 4.0 not found
        if comprobante is None:
            comprobante = root.find('.//cfdi3:Comprobante', cfdi_namespaces)
        
        if comprobante is not None:
            serie = comprobante.get('Serie', '')
            folio = comprobante.get('Folio', '')
            
            if serie and folio:
                invoice_number = f"{serie}-{folio}".upper()
                print(f"[OK] Extracted SAT CFDI invoice ID: {invoice_number}")
                return invoice_number
            elif folio:
                invoice_number = folio.upper()
                print(f"[OK] Extracted SAT CFDI folio: {invoice_number}")
                return invoice_number
        
        # Try to find any ID element without namespace
        any_id = root.find('.//{*}ID')
        if any_id is not None and any_id.text:
            invoice_number = any_id.text.strip().upper()
            print(f"[OK] Extracted generic ID: {invoice_number}")
            return invoice_number
        
        print(f"[FAIL] Could not extract invoice number from XML")
        return None
        
    except Exception as e:
        print(f"[ERROR] Failed to extract invoice number: {e}")
        import traceback
        traceback.print_exc()
        return None


# Test with SAT CFDI file
print("\n" + "="*70)
print("Testing with TEC940201K89_CREDIT_NOTE.xml")
print("="*70)

with open('test_files/TEC940201K89_CREDIT_NOTE.xml', 'r', encoding='utf-8') as f:
    xml_content = f.read()
    result = extract_invoice_number_from_xml(xml_content)
    print(f"\nResult: {result}")
    print(f"Expected: NC-001")
    
    if result == "NC-001":
        print("[PASS] Extraction working correctly!")
    else:
        print("[FAIL] Extraction not working!")

print("\n" + "="*70)
