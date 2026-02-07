"""
Complete SAP Integration Test Suite
Tests all aspects of SAP invoice integration including authentication, upload, and duplicate handling.

Run this script to validate your SAP integration is working correctly.

Usage:
    python test_sap_complete_integration.py

Requirements:
    - Backend server running (default: http://localhost:8000)
    - Valid API key (will be generated if not exists)
    - Test XML invoice file
"""

import requests
import json
import time
import os
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8000"
API_VERSION = "v1"

# Test user credentials (change these to match your test user)
TEST_EMAIL = "puspesh@gmail.com"
TEST_PASSWORD = "12345"

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_section(title):
    """Print a section header"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}  {title}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}\n")

def print_success(message):
    """Print success message"""
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")

def print_error(message):
    """Print error message"""
    print(f"{Colors.RED}❌ {message}{Colors.END}")

def print_warning(message):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.END}")

def print_info(message):
    """Print info message"""
    print(f"   {message}")

def create_test_xml():
    """Create a test XML invoice"""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>TEST-SAP-''' + str(int(time.time())) + '''</cbc:ID>
    <cbc:IssueDate>2026-02-07</cbc:IssueDate>
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cbc:EndpointID>CUST-001</cbc:EndpointID>
            <cac:PartyName>
                <cbc:Name>Test Customer</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>
    <cac:InvoiceLine>
        <cbc:ID>1</cbc:ID>
        <cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
        <cac:Item>
            <cbc:Description>Test Item</cbc:Description>
        </cac:Item>
    </cac:InvoiceLine>
</Invoice>'''

def test_1_login():
    """Test 1: Login to get access token"""
    print_section("TEST 1: User Login")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/{API_VERSION}/user/auth/login",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            print_success("Login successful")
            print_info(f"Access token: {access_token[:50]}...")
            return access_token
        else:
            print_error(f"Login failed: {response.status_code}")
            print_info(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Login error: {e}")
        return None

def test_2_get_or_generate_api_key(access_token):
    """Test 2: Get existing API key or generate new one"""
    print_section("TEST 2: Get/Generate API Key")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        # Check if API key exists
        response = requests.get(
            f"{BASE_URL}/api/{API_VERSION}/invoices/api-key",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("has_key") and data.get("is_active"):
                print_success("API key already exists and is active")
                print_info(f"API User ID: {data.get('api_user_identifier')}")
                print_warning("Note: Cannot retrieve existing API key, you must use your saved key")
                print_info("If you don't have your API key saved, generate a new one")
                return None
            else:
                print_info("No active API key found, generating new one...")
                
                # Generate new API key
                gen_response = requests.post(
                    f"{BASE_URL}/api/{API_VERSION}/invoices/api-key/generate",
                    headers=headers,
                    timeout=10
                )
                
                if gen_response.status_code == 200:
                    gen_data = gen_response.json()
                    api_key = gen_data.get("api_key")
                    print_success("API key generated successfully")
                    print_info(f"API Key: {api_key}")
                    print_warning("IMPORTANT: Save this API key! It won't be shown again.")
                    return api_key
                else:
                    print_error(f"Failed to generate API key: {gen_response.status_code}")
                    print_info(f"Response: {gen_response.text}")
                    return None
        else:
            print_error(f"Failed to check API key: {response.status_code}")
            print_info(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"API key error: {e}")
        return None

def test_3_health_check(api_key):
    """Test 3: Health check endpoint"""
    print_section("TEST 3: SAP Health Check")
    
    if not api_key:
        print_error("Cannot test health check without API key")
        print_warning("Please provide your API key manually or generate a new one")
        return False
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/{API_VERSION}/invoices/api/health-check",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success("Health check passed")
            print_info(f"Status: {data.get('status')}")
            print_info(f"User ID: {data.get('user_id')}")
            print_info(f"Username: {data.get('username')}")
            print_info(f"Timestamp: {data.get('timestamp')}")
            print_info(f"Version: {data.get('version')}")
            return True
        else:
            print_error(f"Health check failed: {response.status_code}")
            print_info(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"Health check error: {e}")
        return False

def test_4_upload_invoice(api_key):
    """Test 4: Upload test invoice"""
    print_section("TEST 4: Upload Invoice via SAP API")
    
    if not api_key:
        print_error("Cannot test upload without API key")
        return None
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Create test XML
    xml_content = create_test_xml()
    
    # Extract invoice number for reference
    import re
    invoice_match = re.search(r'<cbc:ID>(.*?)</cbc:ID>', xml_content)
    invoice_number = invoice_match.group(1) if invoice_match else "unknown"
    
    print_info(f"Test Invoice Number: {invoice_number}")
    
    try:
        # Prepare file upload
        files = {
            'file': ('test_invoice.xml', xml_content, 'application/xml')
        }
        
        print_info("Uploading invoice...")
        response = requests.post(
            f"{BASE_URL}/api/{API_VERSION}/invoices/api/process",
            headers=headers,
            files=files,
            timeout=30
        )
        
        if response.status_code in [200, 201, 202]:
            data = response.json()
            tracking_id = data.get("tracking_id")
            print_success("Invoice uploaded successfully")
            print_info(f"Tracking ID: {tracking_id}")
            print_info(f"Invoice Number: {invoice_number}")
            
            # Check processing steps if available
            steps = data.get("processing_steps", [])
            if steps:
                print_info(f"Processing steps: {len(steps)}")
                for step in steps:
                    status_icon = "✅" if step.get("success") else "❌"
                    print_info(f"  {status_icon} {step.get('step_name')}: {step.get('message', 'N/A')}")
            
            return tracking_id, invoice_number
        else:
            print_error(f"Upload failed: {response.status_code}")
            print_info(f"Response: {response.text}")
            return None, invoice_number
            
    except Exception as e:
        print_error(f"Upload error: {e}")
        return None, invoice_number

def test_5_duplicate_prevention(api_key, invoice_number):
    """Test 5: Test duplicate prevention"""
    print_section("TEST 5: Duplicate Prevention")
    
    if not api_key or not invoice_number:
        print_error("Cannot test duplicate prevention without API key and invoice number")
        return False
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Create XML with same invoice number
    xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>{invoice_number}</cbc:ID>
    <cbc:IssueDate>2026-02-07</cbc:IssueDate>
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cbc:EndpointID>CUST-001</cbc:EndpointID>
            <cac:PartyName>
                <cbc:Name>Test Customer</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>
</Invoice>'''
    
    try:
        files = {
            'file': ('duplicate_invoice.xml', xml_content, 'application/xml')
        }
        
        print_info(f"Attempting to upload duplicate invoice: {invoice_number}")
        response = requests.post(
            f"{BASE_URL}/api/{API_VERSION}/invoices/api/process",
            headers=headers,
            files=files,
            timeout=30
        )
        
        if response.status_code == 400:
            data = response.json()
            detail = data.get("detail", {})
            if isinstance(detail, dict) and detail.get("error") == "Duplicate invoice detected":
                print_success("Duplicate prevention working correctly!")
                print_info(f"Error message: {detail.get('message')}")
                return True
            else:
                print_error("Upload was blocked, but not by duplicate detection")
                print_info(f"Response: {data}")
                return False
        else:
            print_error(f"Duplicate was NOT blocked! Status: {response.status_code}")
            print_info(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"Duplicate test error: {e}")
        return False

def test_6_check_status(tracking_id):
    """Test 6: Check processing status"""
    print_section("TEST 6: Check Processing Status")
    
    if not tracking_id:
        print_warning("Skipping status check (no tracking ID)")
        return False
    
    try:
        print_info(f"Checking status for tracking ID: {tracking_id}")
        response = requests.get(
            f"{BASE_URL}/api/{API_VERSION}/invoices/status/{tracking_id}",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success("Status retrieved successfully")
            print_info(f"Status: {data.get('status', 'unknown')}")
            print_info(f"Progress: {data.get('progress', 0)}%")
            
            steps = data.get("processing_steps", [])
            if steps:
                print_info(f"Processing steps: {len(steps)}")
            
            return True
        else:
            print_error(f"Status check failed: {response.status_code}")
            print_info(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"Status check error: {e}")
        return False

def main():
    """Main test runner"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║        SAP INTEGRATION COMPLETE TEST SUITE                        ║")
    print("║        Testing all aspects of SAP invoice integration             ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")
    print(Colors.END)
    
    print_info(f"Backend URL: {BASE_URL}")
    print_info(f"API Version: {API_VERSION}")
    print_info(f"Test User: {TEST_EMAIL}")
    
    results = {
        "passed": 0,
        "failed": 0,
        "skipped": 0
    }
    
    # Test 1: Login
    access_token = test_1_login()
    if access_token:
        results["passed"] += 1
    else:
        results["failed"] += 1
        print_error("Cannot proceed without access token")
        print_final_results(results)
        return
    
    # Test 2: Get/Generate API Key
    api_key = test_2_get_or_generate_api_key(access_token)
    if api_key:
        results["passed"] += 1
    else:
        results["failed"] += 1
        print_warning("If you have an existing API key, you can continue by providing it manually")
        api_key = input("\nEnter your API key (or press Enter to skip remaining tests): ").strip()
        if not api_key:
            print_final_results(results)
            return
    
    # Test 3: Health Check
    if test_3_health_check(api_key):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # Test 4: Upload Invoice
    tracking_id, invoice_number = test_4_upload_invoice(api_key)
    if tracking_id:
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # Wait a moment for processing
    if tracking_id:
        print_info("\nWaiting 2 seconds for processing...")
        time.sleep(2)
    
    # Test 5: Duplicate Prevention
    if test_5_duplicate_prevention(api_key, invoice_number):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # Test 6: Check Status
    if test_6_check_status(tracking_id):
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["skipped"] += 1
    
    # Final results
    print_final_results(results)

def print_final_results(results):
    """Print final test results"""
    print_section("TEST RESULTS SUMMARY")
    
    total = results["passed"] + results["failed"]
    success_rate = (results["passed"] / total * 100) if total > 0 else 0
    
    print_info(f"Total Tests: {total}")
    print_success(f"Passed: {results['passed']}")
    print_error(f"Failed: {results['failed']}")
    
    if results["skipped"] > 0:
        print_warning(f"Skipped: {results['skipped']}")
    
    print_info(f"\nSuccess Rate: {success_rate:.1f}%")
    
    if results["failed"] == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 ALL TESTS PASSED! SAP integration is working correctly.{Colors.END}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  SOME TESTS FAILED. Check the output above for details.{Colors.END}")

if __name__ == "__main__":
    main()
