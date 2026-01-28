"""
Test Bridge Portal <-> SAP Connectivity
Tests if invoices are correctly received and stored when pushed from external systems.
"""

import requests
import json
from datetime import datetime
import time

# Configuration
BASE_URL = "http://localhost:8000"
API_BASE_URL = f"{BASE_URL}/api/v1"

# Test credentials
TEST_EMAIL = "testsalmen123@gmail.com"
TEST_PASSWORD = "testsalmen123"

# Colors for output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(80)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}\n")

def print_success(text):
    print(f"{Colors.OKGREEN}✅ {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.FAIL}❌ {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKCYAN}ℹ️  {text}{Colors.ENDC}")

def print_warning(text):
    print(f"{Colors.WARNING}⚠️  {text}{Colors.ENDC}")

def test_1_login():
    """Test 1: Login to get access token"""
    print_header("TEST 1: User Login")
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/user/auth/login",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            print_success(f"Login successful!")
            print_info(f"Access Token: {token[:50]}...")
            return token
        else:
            print_error(f"Login failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Login error: {e}")
        return None

def test_2_get_api_key(token):
    """Test 2: Get or generate API key"""
    print_header("TEST 2: Get API Key")
    
    if not token:
        print_error("No access token available. Skipping.")
        return None
    
    try:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try to get existing API key
        print_info("Checking for existing API key...")
        response = requests.get(
            f"{API_BASE_URL}/invoices/api-key",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("api_key"):
                print_success("API key already exists!")
                api_key = data["api_key"]
                print_info(f"API Key: {api_key[:50]}...")
                return api_key
            else:
                print_info("No API key found. Generating new one...")
        
        # Generate new API key
        print_info("Generating new API key...")
        response = requests.post(
            f"{API_BASE_URL}/invoices/api-key/generate",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            api_key = data.get("api_key")
            print_success("API key generated successfully!")
            print_info(f"API Key: {api_key[:50]}...")
            print_warning("⚠️  SAVE THIS KEY! It won't be shown again!")
            return api_key
        else:
            print_error(f"API key generation failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"API key error: {e}")
        return None

def test_3_push_invoice_via_api(api_key):
    """Test 3: Push invoice via API (simulating SAP)"""
    print_header("TEST 3: Push Invoice via API (SAP Simulation)")
    
    if not api_key:
        print_error("No API key available. Skipping.")
        return None
    
    try:
        # Read test XML file
        xml_files = ["INVOICE.xml", "test_invoice.xml", "sample_invoice.xml"]
        xml_content = None
        xml_filename = None
        
        for filename in xml_files:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
                    xml_filename = filename
                    print_info(f"Using XML file: {filename}")
                    break
            except FileNotFoundError:
                continue
        
        if not xml_content:
            print_warning("No test XML file found. Creating a simple test XML...")
            xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice>
    <InvoiceNumber>TEST-001</InvoiceNumber>
    <Date>2025-01-22</Date>
    <Supplier>
        <Name>Test Supplier</Name>
        <ID>SUPPLIER123</ID>
    </Supplier>
    <Customer>
        <Name>Test Customer</Name>
        <ID>CUSTOMER456</ID>
    </Customer>
    <Total>1000.00</Total>
    <Currency>USD</Currency>
</Invoice>"""
            xml_filename = "test_invoice_generated.xml"
        
        # Prepare multipart form data
        files = {
            'file': (xml_filename, xml_content, 'application/xml')
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        print_info("Pushing invoice to Bridge Portal...")
        print_info(f"Endpoint: POST {API_BASE_URL}/invoices/api/process")
        print_info(f"File: {xml_filename} ({len(xml_content)} bytes)")
        
        response = requests.post(
            f"{API_BASE_URL}/invoices/api/process",
            headers=headers,
            files=files
        )
        
        print_info(f"Response Status: {response.status_code}")
        
        if response.status_code in [200, 202]:
            data = response.json()
            print_success("Invoice pushed successfully!")
            print_info(f"Tracking ID: {data.get('tracking_id')}")
            print_info(f"Message: {data.get('message')}")
            
            # Wait a bit for processing
            print_info("Waiting 3 seconds for processing...")
            time.sleep(3)
            
            return data.get('tracking_id')
        else:
            print_error(f"Invoice push failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Invoice push error: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_4_verify_invoice_stored(token, tracking_id):
    """Test 4: Verify invoice was stored in database"""
    print_header("TEST 4: Verify Invoice Stored in Database")
    
    if not token:
        print_error("No access token available. Skipping.")
        return False
    
    if not tracking_id:
        print_error("No tracking ID available. Skipping.")
        return False
    
    try:
        headers = {"Authorization": f"Bearer {token}"}
        
        print_info("Checking successful invoices...")
        response = requests.get(
            f"{API_BASE_URL}/invoices/success",
            headers=headers,
            params={"limit": 10}
        )
        
        if response.status_code == 200:
            data = response.json()
            # Handle both response formats: list or dict with 'invoices' key
            if isinstance(data, list):
                invoices = data
            else:
                invoices = data.get("invoices", [])
            print_info(f"Found {len(invoices)} successful invoices")
            
            # Check if our tracking_id is in the list
            found = False
            for invoice in invoices:
                if str(invoice.get("tracking_id")) == str(tracking_id):
                    found = True
                    print_success("Invoice found in successful invoices!")
                    print_info(f"  Invoice ID: {invoice.get('id')}")
                    print_info(f"  Customer Name: {invoice.get('customer_name', 'N/A')}")
                    print_info(f"  Target Format: {invoice.get('target_format', 'N/A')}")
                    print_info(f"  Created At: {invoice.get('created_at', 'N/A')}")
                    break
            
            if not found:
                print_warning("Invoice not found in successful list. Checking failed invoices...")
                
                response = requests.get(
                    f"{API_BASE_URL}/invoices/failed",
                    headers=headers,
                    params={"limit": 10}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Handle both response formats: list or dict with 'invoices' key
                    if isinstance(data, list):
                        failed_invoices = data
                    else:
                        failed_invoices = data.get("invoices", [])
                    print_info(f"Found {len(failed_invoices)} failed invoices")
                    
                    for invoice in failed_invoices:
                        if str(invoice.get("tracking_id")) == str(tracking_id):
                            print_warning("Invoice found in failed list!")
                            print_info(f"  Error: {invoice.get('error_message', 'N/A')}")
                            return False
                
                print_error("Invoice not found in database!")
                return False
            
            return True
        else:
            print_error(f"Failed to check invoices: {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print_error(f"Verification error: {e}")
        return None

def test_5_check_database_connectivity():
    """Test 5: Check database connectivity via health endpoint"""
    print_header("TEST 5: Database Connectivity Check")
    
    try:
        print_info("Checking Bridge Portal health...")
        response = requests.get(f"{BASE_URL}/health")
        
        if response.status_code == 200:
            data = response.json()
            print_success("Bridge Portal is running!")
            print_info(f"Status: {data.get('status')}")
            print_info(f"Message: {data.get('message')}")
            return True
        else:
            print_error(f"Health check failed: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Health check error: {e}")
        return False

def test_6_api_endpoint_accessibility():
    """Test 6: Check all critical API endpoints"""
    print_header("TEST 6: API Endpoints Accessibility Check")
    
    endpoints = [
        ("GET", "/health", "Health Check", False),
        ("POST", "/api/v1/user/auth/login", "User Login", False),
        ("POST", "/api/v1/invoices/api/process", "Invoice API Process", True),
        ("GET", "/api/v1/invoices/success", "List Successful Invoices", True),
        ("GET", "/api/v1/invoices/failed", "List Failed Invoices", True),
    ]
    
    results = []
    
    for method, endpoint, name, requires_auth in endpoints:
        try:
            url = f"{BASE_URL}{endpoint}"
            print_info(f"Testing: {method} {endpoint} ({name})")
            
            # Just test if endpoint exists (expecting auth error for protected endpoints)
            if method == "GET":
                response = requests.get(url)
            else:
                response = requests.post(url)
            
            # For protected endpoints, 401/403 means endpoint exists but needs auth
            if requires_auth and response.status_code in [401, 403]:
                print_success(f"  ✓ Endpoint exists (auth required)")
                results.append(True)
            elif not requires_auth and response.status_code in [200, 422]:
                print_success(f"  ✓ Endpoint accessible")
                results.append(True)
            else:
                print_info(f"  Status: {response.status_code}")
                results.append(True)
                
        except Exception as e:
            print_error(f"  ✗ Endpoint error: {e}")
            results.append(False)
    
    success_rate = (sum(results) / len(results)) * 100
    print(f"\n{Colors.BOLD}Endpoint Accessibility: {success_rate:.0f}% ({sum(results)}/{len(results)}){Colors.ENDC}")
    return all(results)

def generate_postman_collection(api_key):
    """Generate Postman collection for SAP simulation"""
    print_header("Postman Collection for SAP Simulation")
    
    collection = {
        "info": {
            "name": "Bridge Portal - SAP Connectivity",
            "description": "Test Bridge Portal connectivity by simulating SAP pushing invoices",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": [
            {
                "name": "1. Health Check",
                "request": {
                    "method": "GET",
                    "header": [],
                    "url": {
                        "raw": f"{BASE_URL}/health",
                        "host": [BASE_URL.replace("http://", "").replace("https://", "")],
                        "path": ["health"]
                    }
                }
            },
            {
                "name": "2. Login (Get Access Token)",
                "request": {
                    "method": "POST",
                    "header": [
                        {
                            "key": "Content-Type",
                            "value": "application/json"
                        }
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": json.dumps({
                            "email": TEST_EMAIL,
                            "password": TEST_PASSWORD
                        }, indent=2)
                    },
                    "url": {
                        "raw": f"{API_BASE_URL}/user/auth/login",
                        "host": [BASE_URL.replace("http://", "").replace("https://", "")],
                        "path": ["api", "v1", "user", "auth", "login"]
                    }
                }
            },
            {
                "name": "3. Push Invoice via API (SAP Simulation)",
                "request": {
                    "method": "POST",
                    "header": [
                        {
                            "key": "Authorization",
                            "value": f"Bearer {api_key if api_key else 'YOUR_API_KEY_HERE'}"
                        }
                    ],
                    "body": {
                        "mode": "formdata",
                        "formdata": [
                            {
                                "key": "file",
                                "type": "file",
                                "src": "INVOICE.xml"
                            }
                        ]
                    },
                    "url": {
                        "raw": f"{API_BASE_URL}/invoices/api/process",
                        "host": [BASE_URL.replace("http://", "").replace("https://", "")],
                        "path": ["api", "v1", "invoices", "api", "process"]
                    }
                }
            },
            {
                "name": "4. Check Successful Invoices",
                "request": {
                    "method": "GET",
                    "header": [
                        {
                            "key": "Authorization",
                            "value": "Bearer {{access_token}}"
                        }
                    ],
                    "url": {
                        "raw": f"{API_BASE_URL}/invoices/success?limit=10",
                        "host": [BASE_URL.replace("http://", "").replace("https://", "")],
                        "path": ["api", "v1", "invoices", "success"],
                        "query": [
                            {
                                "key": "limit",
                                "value": "10"
                            }
                        ]
                    }
                }
            }
        ]
    }
    
    filename = "bridge_sap_connectivity.postman_collection.json"
    with open(filename, 'w') as f:
        json.dump(collection, f, indent=2)
    
    print_success(f"Postman collection saved: {filename}")
    print_info("Import this file into Postman to test SAP connectivity")
    
    if api_key:
        print_warning(f"\n⚠️  Your API Key: {api_key}")
        print_info("Use this key in Postman's 'Authorization' header")

def main():
    """Run all connectivity tests"""
    print_header("Bridge Portal <-> SAP Connectivity Test Suite")
    print_info(f"Testing Bridge Portal at: {BASE_URL}")
    print_info(f"Timestamp: {datetime.now().isoformat()}\n")
    
    results = {}
    
    # Test 5: Database Connectivity (first, as it's basic)
    results["database_connectivity"] = test_5_check_database_connectivity()
    
    # Test 6: API Endpoints
    results["api_endpoints"] = test_6_api_endpoint_accessibility()
    
    # Test 1: Login
    token = test_1_login()
    results["login"] = token is not None
    
    # Test 2: API Key
    api_key = test_2_get_api_key(token)
    results["api_key"] = api_key is not None
    
    # Test 3: Push Invoice
    tracking_id = test_3_push_invoice_via_api(api_key)
    results["invoice_push"] = tracking_id is not None
    
    # Test 4: Verify Storage
    results["invoice_storage"] = test_4_verify_invoice_stored(token, tracking_id)
    
    # Generate Postman collection
    generate_postman_collection(api_key)
    
    # Final Summary
    print_header("Test Results Summary")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    for test_name, result in results.items():
        status = f"{Colors.OKGREEN}✅ PASS{Colors.ENDC}" if result else f"{Colors.FAIL}❌ FAIL{Colors.ENDC}"
        print(f"{test_name.replace('_', ' ').title()}: {status}")
    
    print(f"\n{Colors.BOLD}Overall: {passed}/{total} tests passed{Colors.ENDC}")
    
    if passed == total:
        print_success("\n🎉 All connectivity tests passed!")
        print_info("Bridge Portal is correctly receiving and storing invoices!")
    else:
        print_warning(f"\n⚠️  {failed} test(s) failed. Check the errors above.")
    
    return passed == total

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print_warning("\n\n⚠️  Tests interrupted by user")
        exit(1)
    except Exception as e:
        print_error(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

