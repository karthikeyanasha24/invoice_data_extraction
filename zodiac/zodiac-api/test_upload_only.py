"""
Simple Test: Upload CFDI Documents Only
Just uploads the 3 test files to the database
"""
import requests
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"

# Colors
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.END}")

def print_info(message):
    print(f"{Colors.YELLOW}ℹ️  {message}{Colors.END}")

def read_xml_file(filename):
    """Read XML file content"""
    try:
        file_path = Path(__file__).parent / filename
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print_error(f"File not found: {filename}")
        return None

def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}📤 UPLOAD CFDI DOCUMENTS TO DATABASE{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}\n")
    
    # Step 1: Login
    print(f"{Colors.BOLD}Step 1: Login{Colors.END}")
    login_response = requests.post(
        f"{BASE_URL}/api/v1/user/auth/login",
        json={"email": EMAIL, "password": PASSWORD}
    )
    
    if login_response.status_code != 200:
        print_error(f"Login failed: {login_response.status_code}")
        return
    
    access_token = login_response.json()["access_token"]
    user = login_response.json()["user"]
    print_success(f"Logged in as: {user['email']}")
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Step 2: Read XML Files
    print(f"\n{Colors.BOLD}Step 2: Read XML Files{Colors.END}")
    files_to_upload = [
        ("INVOICE.xml", "INVOICE"),
        ("CREDIT NOTE.xml", "CREDIT_NOTE"),
        ("PAYMENT COMPLEMENT.xml", "PAYMENT")
    ]
    
    uploaded_docs = []
    
    for filename, doc_type in files_to_upload:
        xml_content = read_xml_file(filename)
        if not xml_content:
            print_error(f"Failed to read {filename}")
            continue
        
        print_info(f"Read {filename} ({len(xml_content)} bytes)")
        
        # Step 3: Upload to Database
        print(f"\n{Colors.BOLD}Step 3: Upload {doc_type}{Colors.END}")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/sat/intake",
            headers=headers,
            json={"xml_content": xml_content}
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"{doc_type} uploaded successfully!")
            print_info(f"  UUID: {data['cfdi_uuid']}")
            print_info(f"  Document ID: {data['document_id']}")
            print_info(f"  Supplier RFC: {data['supplier_rfc']}")
            print_info(f"  Total: ${data['total']} {data['currency']}")
            print_info(f"  Status: {data['status']}")
            
            uploaded_docs.append({
                "type": doc_type,
                "uuid": data['cfdi_uuid'],
                "id": data['document_id'],
                "rfc": data['supplier_rfc']
            })
        else:
            print_error(f"Failed to upload {doc_type}: {response.status_code}")
            print_error(response.text)
    
    # Summary
    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}✅ UPLOAD COMPLETE!{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}\n")
    
    print(f"{Colors.BOLD}Summary:{Colors.END}")
    print(f"  📄 Uploaded {len(uploaded_docs)} documents to database")
    for doc in uploaded_docs:
        print(f"     • {doc['type']} - {doc['uuid'][:20]}...")
    
    print(f"\n{Colors.BOLD}Next Steps:{Colors.END}")
    print(f"  1. Open frontend: {Colors.CYAN}http://localhost:3000/sat-documents{Colors.END}")
    print(f"  2. Go to 'Documents' tab")
    print(f"  3. You should see {len(uploaded_docs)} documents")
    print(f"  4. Manually merge them using the UI:")
    print(f"     • Click 'Simple Merge' tab → Select period → Click 'Merge & Save'")
    print(f"     • Click 'Canonical Merged' tab → Select period → Click 'Generate Canonical'")
    print(f"     • Click 'Send to SAP' tab → Click 'Send to SAP' for each document")
    
    print(f"\n{Colors.BOLD}Database Verification:{Colors.END}")
    print(f"  Run this SQL query to verify:")
    print(f"  {Colors.CYAN}SELECT id, cfdi_uuid, doc_type, supplier_rfc, total, status")
    print(f"  FROM sat_documents")
    print(f"  WHERE fiscal_year = 2026 AND fiscal_period = 1")
    print(f"  ORDER BY created_at DESC;{Colors.END}")
    
    print(f"\n{Colors.GREEN}🎉 Done! Documents are in your database!{Colors.END}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Upload interrupted{Colors.END}")
    except Exception as e:
        print_error(f"Error: {e}")
        import traceback
        traceback.print_exc()

