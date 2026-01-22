"""
Complete SAT Flow Test Script
Tests the entire flow: Upload 3 documents → Merge → Send to SAP
"""
import requests
import json
import time
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_step(step_num, message):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}STEP {step_num}: {message}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.END}")

def print_info(message):
    print(f"{Colors.YELLOW}ℹ️  {message}{Colors.END}")

# Read XML files
def read_xml_file(filename):
    """Read XML file and return content as string"""
    try:
        file_path = Path(__file__).parent / filename
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        print_error(f"File not found: {filename}")
        print_info(f"Looking in: {Path(__file__).parent}")
        return None

def main():
    print(f"{Colors.BOLD}{Colors.GREEN}")
    print("="*60)
    print("  🚀 SAT COMPLETE FLOW TEST")
    print("="*60)
    print(Colors.END)
    
    # ============================================================
    # STEP 1: Login
    # ============================================================
    print_step(1, "Login to get access token")
    
    login_response = requests.post(
        f"{BASE_URL}/api/v1/user/auth/login",
        json={"email": EMAIL, "password": PASSWORD}
    )
    
    if login_response.status_code == 200:
        access_token = login_response.json()["access_token"]
        user = login_response.json()["user"]
        print_success(f"Logged in as: {user['email']} (ID: {user['id']})")
        print_info(f"Token: {access_token[:50]}...")
    else:
        print_error(f"Login failed: {login_response.status_code}")
        print_error(login_response.text)
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # ============================================================
    # STEP 2: Read XML Files
    # ============================================================
    print_step(2, "Reading XML files")
    
    invoice_xml = read_xml_file("INVOICE.xml")
    credit_note_xml = read_xml_file("CREDIT NOTE.xml")
    payment_xml = read_xml_file("PAYMENT COMPLEMENT.xml")
    
    if not all([invoice_xml, credit_note_xml, payment_xml]):
        print_error("Failed to read one or more XML files")
        return
    
    print_success(f"INVOICE.xml: {len(invoice_xml)} bytes")
    print_success(f"CREDIT NOTE.xml: {len(credit_note_xml)} bytes")
    print_success(f"PAYMENT COMPLEMENT.xml: {len(payment_xml)} bytes")
    
    # ============================================================
    # STEP 3: Send INVOICE
    # ============================================================
    print_step(3, "Sending INVOICE document")
    
    invoice_response = requests.post(
        f"{BASE_URL}/api/v1/sat/intake",
        headers=headers,
        json={"xml_content": invoice_xml}
    )
    
    if invoice_response.status_code == 200:
        invoice_data = invoice_response.json()
        print_success(f"INVOICE uploaded successfully")
        print_info(f"UUID: {invoice_data['cfdi_uuid']}")
        print_info(f"Document ID: {invoice_data['document_id']}")
        print_info(f"Supplier RFC: {invoice_data['supplier_rfc']}")
        print_info(f"Total: ${invoice_data['total']} {invoice_data['currency']}")
    else:
        print_error(f"Failed to upload INVOICE: {invoice_response.status_code}")
        print_error(invoice_response.text)
        return
    
    time.sleep(1)  # Brief pause between uploads
    
    # ============================================================
    # STEP 4: Send CREDIT_NOTE
    # ============================================================
    print_step(4, "Sending CREDIT_NOTE document")
    
    credit_response = requests.post(
        f"{BASE_URL}/api/v1/sat/intake",
        headers=headers,
        json={"xml_content": credit_note_xml}
    )
    
    if credit_response.status_code == 200:
        credit_data = credit_response.json()
        print_success(f"CREDIT_NOTE uploaded successfully")
        print_info(f"UUID: {credit_data['cfdi_uuid']}")
        print_info(f"Document ID: {credit_data['document_id']}")
        print_info(f"Total: ${credit_data['total']} {credit_data['currency']}")
    else:
        print_error(f"Failed to upload CREDIT_NOTE: {credit_response.status_code}")
        print_error(credit_response.text)
        return
    
    time.sleep(1)
    
    # ============================================================
    # STEP 5: Send PAYMENT
    # ============================================================
    print_step(5, "Sending PAYMENT document")
    
    payment_response = requests.post(
        f"{BASE_URL}/api/v1/sat/intake",
        headers=headers,
        json={"xml_content": payment_xml}
    )
    
    if payment_response.status_code == 200:
        payment_data = payment_response.json()
        print_success(f"PAYMENT uploaded successfully")
        print_info(f"UUID: {payment_data['cfdi_uuid']}")
        print_info(f"Document ID: {payment_data['document_id']}")
        print_info(f"Total: ${payment_data['total']} {payment_data['currency']}")
        print_info(f"Related Invoice UUID: {payment_data.get('related_cfdi_uuid', 'N/A')}")
    else:
        print_error(f"Failed to upload PAYMENT: {payment_response.status_code}")
        print_error(payment_response.text)
        return
    
    time.sleep(1)
    
    # Extract fiscal info from first document
    # If fiscal_year and fiscal_period are not in response, use defaults or fetch from API
    fiscal_year = invoice_data.get('fiscal_year')
    fiscal_period = invoice_data.get('fiscal_period')
    supplier_rfc = invoice_data['supplier_rfc']
    
    # If fiscal info not in response, fetch from documents list
    if not fiscal_year or not fiscal_period:
        print_info("Fiscal info not in response, fetching from documents list...")
        docs_response = requests.get(
            f"{BASE_URL}/api/v1/sat/documents",
            headers=headers
        )
        if docs_response.status_code == 200:
            docs = docs_response.json().get('documents', [])
            if docs:
                fiscal_year = docs[0].get('fiscal_year', 2025)
                fiscal_period = docs[0].get('fiscal_period', 11)
                print_info(f"Found fiscal period: {fiscal_year}-{fiscal_period:02d}")
        
        # Fallback to defaults if still not found
        if not fiscal_year or not fiscal_period:
            fiscal_year = 2025
            fiscal_period = 11
            print_info(f"Using default period: {fiscal_year}-{fiscal_period:02d}")
    
    # ============================================================
    # STEP 6: Create Supplier Mapping (if not exists)
    # ============================================================
    print_step(6, "Creating/Checking supplier mapping")
    
    # Check if mapping exists
    mapping_list_response = requests.get(
        f"{BASE_URL}/api/v1/sat/supplier-mapping/list",
        headers=headers
    )
    
    mapping_exists = False
    if mapping_list_response.status_code == 200:
        mappings = mapping_list_response.json().get('mappings', [])
        for mapping in mappings:
            if mapping['supplier_rfc'] == supplier_rfc:
                mapping_exists = True
                print_info(f"Mapping already exists: {supplier_rfc} → {mapping['sap_gl_account']}")
                break
    
    if not mapping_exists:
        print_info(f"Creating new mapping for RFC: {supplier_rfc}")
        mapping_response = requests.post(
            f"{BASE_URL}/api/v1/sat/supplier-mapping/create",
            headers=headers,
            json={
                "supplier_rfc": supplier_rfc,
                "sap_gl_account": "40000001",
                "account_description": "Test Supplier - Illumination Equipment",
                "is_active": True
            }
        )
        
        if mapping_response.status_code == 200:
            print_success(f"Mapping created: {supplier_rfc} → 40000001")
        else:
            print_error(f"Failed to create mapping: {mapping_response.status_code}")
            print_error(mapping_response.text)
    
    time.sleep(1)
    
    # ============================================================
    # STEP 7: Merge Documents
    # ============================================================
    print_step(7, f"Merging documents for period {fiscal_year}-{fiscal_period:02d}")
    
    merge_response = requests.post(
        f"{BASE_URL}/api/v1/sat/canonical/merge",
        headers=headers,
        json={
            "company_code": "MX01",
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period
        }
    )
    
    if merge_response.status_code == 200:
        merge_data = merge_response.json()
        print_success(f"Documents merged successfully!")
        print_info(f"Vendors merged: {merge_data['summary']['total_vendors']}")
        print_info(f"Documents merged: {merge_data['summary']['total_documents_merged']}")
        print_info(f"Canonical documents created: {merge_data['summary']['total_canonical_created']}")
        
        if merge_data['canonical_documents']:
            canonical = merge_data['canonical_documents'][0]
            canonical_id = canonical['id']
            print_info(f"Canonical ID: {canonical_id}")
            print_info(f"Vendor: {canonical['vendor_name']}")
            print_info(f"Total Invoices: ${canonical['total_invoices']}")
            print_info(f"Total Credits: ${canonical['total_credits']}")
            print_info(f"Total Payments: ${canonical['total_payments']}")
            print_info(f"Net Amount: ${canonical['net_amount']}")
            print_info(f"SAP G/L Account: {canonical['sap_gl_account']}")
    else:
        print_error(f"Failed to merge documents: {merge_response.status_code}")
        print_error(merge_response.text)
        return
    
    time.sleep(1)
    
    # ============================================================
    # STEP 8: Preview SAP XML
    # ============================================================
    print_step(8, "Previewing SAP XML")
    
    preview_response = requests.get(
        f"{BASE_URL}/api/v1/sat/canonical/{canonical_id}/sap-xml",
        headers=headers
    )
    
    if preview_response.status_code == 200:
        sap_xml = preview_response.text
        print_success("SAP XML generated successfully!")
        print("\n" + "="*60)
        print("SAP XML Preview:")
        print("="*60)
        print(sap_xml)
        print("="*60 + "\n")
    else:
        print_error(f"Failed to preview SAP XML: {preview_response.status_code}")
        print_error(preview_response.text)
    
    # ============================================================
    # STEP 9: Send to SAP
    # ============================================================
    print_step(9, "Sending to SAP")
    
    sap_response = requests.post(
        f"{BASE_URL}/api/v1/sat/canonical/{canonical_id}/send-to-sap",
        headers=headers
    )
    
    if sap_response.status_code == 200:
        sap_data = sap_response.json()
        print_success("Document sent to SAP successfully!")
        print_info(f"SAP Document Number: {sap_data.get('sap_document_number', 'N/A')}")
        print_info(f"Sent at: {sap_data.get('sent_at', 'N/A')}")
        print_info(f"SAP Response: {sap_data.get('sap_response', 'N/A')}")
    else:
        print_error(f"Failed to send to SAP: {sap_response.status_code}")
        print_error(sap_response.text)
        return
    
    # ============================================================
    # FINAL SUMMARY
    # ============================================================
    print(f"\n{Colors.BOLD}{Colors.GREEN}")
    print("="*60)
    print("  ✅ TEST COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(Colors.END)
    
    print(f"\n{Colors.BOLD}Summary:{Colors.END}")
    print(f"  • Uploaded 3 CFDI documents (INVOICE, CREDIT_NOTE, PAYMENT)")
    print(f"  • Created supplier mapping: {supplier_rfc} → 40000001")
    print(f"  • Merged documents for period: {fiscal_year}-{fiscal_period:02d}")
    print(f"  • Generated canonical document: {canonical_id}")
    print(f"  • Sent to SAP successfully")
    
    print(f"\n{Colors.BOLD}View in Portal:{Colors.END}")
    print(f"  • http://localhost:3000/sat-documents")
    print(f"  • Go to 'Canonical' tab")
    print(f"  • Filter by Year: {fiscal_year}, Month: {fiscal_period}")
    
    print(f"\n{Colors.BOLD}Database Queries:{Colors.END}")
    print(f"  • Individual docs: SELECT * FROM sat_documents WHERE fiscal_year = {fiscal_year} AND fiscal_period = {fiscal_period};")
    print(f"  • Canonical doc: SELECT * FROM sat_canonical_merged WHERE id = '{canonical_id}';")
    
    print(f"\n{Colors.GREEN}🎉 All done! Your SAT flow is working perfectly!{Colors.END}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrupted by user{Colors.END}")
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()

