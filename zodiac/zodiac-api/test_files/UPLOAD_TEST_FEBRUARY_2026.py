"""
Test Upload Script for February 2026 - Two RFCs
Uploads 6 CFDI files (3 files per RFC) for testing Simple Merge

RFCs:
- TEC940201K89 (Invoice, Payment, Credit Note)
- TEC940201K90 (Invoice, Payment, Credit Note)

Period: February 2026 (fiscal_year=2026, fiscal_period=2)
"""
import requests
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

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.END}")

def print_info(message):
    print(f"{Colors.YELLOW}ℹ️  {message}{Colors.END}")

def print_header(message):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{message}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.END}\n")

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
    print_header("📤 UPLOAD TEST FILES FOR FEBRUARY 2026")
    
    # Files to upload (6 files total - 3 per RFC)
    files_to_upload = [
        # RFC: TEC940201K89
        ("TEC940201K89_INVOICE.xml", "TEC940201K89", "INVOICE"),
        ("TEC940201K89_PAYMENT.xml", "TEC940201K89", "PAYMENT"),
        ("TEC940201K89_CREDIT_NOTE.xml", "TEC940201K89", "CREDIT_NOTE"),
        # RFC: TEC940201K90
        ("TEC940201K90_INVOICE.xml", "TEC940201K90", "INVOICE"),
        ("TEC940201K90_PAYMENT.xml", "TEC940201K90", "PAYMENT"),
        ("TEC940201K90_CREDIT_NOTE.xml", "TEC940201K90", "CREDIT_NOTE"),
    ]
    
    print_info(f"Will upload {len(files_to_upload)} files for 2 RFCs")
    print_info("Period: February 2026 (fiscal_year=2026, fiscal_period=2)")
    print()
    
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
    
    # Step 2: Upload files
    uploaded_docs = []
    
    for filename, rfc, doc_type in files_to_upload:
        print(f"\n{Colors.BOLD}Step 2.{len(uploaded_docs)+1}: Upload {doc_type} for {rfc}{Colors.END}")
        
        xml_content = read_xml_file(filename)
        if not xml_content:
            print_error(f"Failed to read {filename}")
            continue
        
        print_info(f"Read {filename} ({len(xml_content)} bytes)")
        
        # Upload to database
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
            
            uploaded_docs.append({
                "type": doc_type,
                "rfc": rfc,
                "uuid": data['cfdi_uuid'],
                "id": data['document_id']
            })
        else:
            print_error(f"Failed to upload {doc_type}: {response.status_code}")
            print_error(response.text)
    
    # Summary
    print_header("✅ UPLOAD COMPLETE!")
    
    print(f"{Colors.BOLD}Summary:{Colors.END}")
    print(f"  📄 Uploaded {len(uploaded_docs)} documents for February 2026")
    
    # Group by RFC
    rfc_groups = {}
    for doc in uploaded_docs:
        if doc['rfc'] not in rfc_groups:
            rfc_groups[doc['rfc']] = []
        rfc_groups[doc['rfc']].append(doc['type'])
    
    for rfc, types in rfc_groups.items():
        print(f"\n  🏢 {rfc}:")
        for doc_type in types:
            print(f"     ✓ {doc_type}")
        
        # Check if all 3 files present
        if len(types) == 3:
            print_success(f"     All 3 files uploaded - Ready to merge!")
        else:
            missing = set(['INVOICE', 'PAYMENT', 'CREDIT_NOTE']) - set(types)
            print_error(f"     Missing: {', '.join(missing)}")
    
    print(f"\n{Colors.BOLD}Next Steps:{Colors.END}")
    print(f"  1. Open frontend: {Colors.CYAN}http://localhost:3000/sat-documents{Colors.END}")
    print(f"  2. Go to 'Simple Merge' tab")
    print(f"  3. Select {Colors.BOLD}Year: 2026, Period: February{Colors.END}")
    print(f"  4. You should see 2 RFC groups with file status indicators:")
    print(f"     - TEC940201K89 (all 3 files ✅)")
    print(f"     - TEC940201K90 (all 3 files ✅)")
    print(f"  5. Check mapping status for each RFC")
    print(f"  6. Click 'Merge & Save' for each group")
    
    print(f"\n{Colors.BOLD}Database Verification:{Colors.END}")
    print(f"  Run this SQL query to verify:")
    print(f"  {Colors.CYAN}SELECT id, cfdi_uuid, doc_type, supplier_rfc, total, status")
    print(f"  FROM sat_documents")
    print(f"  WHERE fiscal_year = 2026 AND fiscal_period = 2")
    print(f"  ORDER BY supplier_rfc, doc_type;{Colors.END}")
    
    print(f"\n{Colors.GREEN}🎉 Done! All 6 files uploaded for February 2026!{Colors.END}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Upload interrupted{Colors.END}")
    except Exception as e:
        print_error(f"Error: {e}")
        import traceback
        traceback.print_exc()
