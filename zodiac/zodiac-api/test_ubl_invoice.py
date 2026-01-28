"""
Test pushing a UBL invoice via API
This tests the actual connectivity with a real standard invoice format
"""

import requests
import time

BASE_URL = "http://localhost:8000"
API_BASE_URL = f"{BASE_URL}/api/v1"

# Your API key from the connectivity test
API_KEY = "NmxwS2sxNnRsZy1SVThOVkFWdTMtN3p5MGJhLU1IQUF5TExGVmRFaUNqNndycW0xRlk0VTM4TTN4bG4xSV9DNGVhbk0wMll0bFU4LVliQU5NbFZEelE="

# Test credentials for verification
TEST_EMAIL = "testsalmen123@gmail.com"
TEST_PASSWORD = "testsalmen123"

print("=" * 80)
print("  Testing UBL Invoice Push (Real SAP Simulation)")
print("=" * 80)

# Step 1: Read the UBL invoice file
print("\n📄 Step 1: Reading UBL invoice file...")
try:
    with open("0090040077_PEPOLDBNA.xml", "r", encoding="utf-8") as f:
        xml_content = f.read()
    print(f"✅ File loaded: 0090040077_PEPOLDBNA.xml ({len(xml_content)} bytes)")
    print(f"   Invoice ID: 0090040077")
    print(f"   Supplier: PEPPOLSOFT LLC")
    print(f"   Customer: EDIFACTMX")
    print(f"   Total: $90.00 USD")
except FileNotFoundError:
    print("❌ File not found: 0090040077_PEPOLDBNA.xml")
    print("   Make sure the file is in the zodiac-api directory")
    exit(1)

# Step 2: Push invoice via API
print("\n📤 Step 2: Pushing invoice to Bridge Portal...")
print(f"   Endpoint: POST {API_BASE_URL}/invoices/api/process")
print(f"   Authentication: Bearer Token (API Key)")

files = {
    'file': ('0090040077_PEPOLDBNA.xml', xml_content, 'application/xml')
}

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

try:
    response = requests.post(
        f"{API_BASE_URL}/invoices/api/process",
        headers=headers,
        files=files
    )
    
    print(f"\n📊 Response Status: {response.status_code}")
    
    if response.status_code in [200, 202]:
        data = response.json()
        print("✅ Invoice pushed successfully!")
        print(f"   Tracking ID: {data.get('tracking_id')}")
        print(f"   Message: {data.get('message', 'Processing started')}")
        print(f"   Status: {data.get('status', 'processing')}")
        
        tracking_id = data.get('tracking_id')
        
        # Step 3: Wait for processing
        print("\n⏳ Step 3: Waiting 5 seconds for processing...")
        time.sleep(5)
        
        # Step 4: Login to verify
        print("\n🔐 Step 4: Logging in to verify invoice storage...")
        login_response = requests.post(
            f"{API_BASE_URL}/user/auth/login",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )
        
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            print("✅ Login successful")
            
            # Step 5: Check successful invoices
            print("\n📋 Step 5: Checking successful invoices...")
            headers_auth = {"Authorization": f"Bearer {token}"}
            
            success_response = requests.get(
                f"{API_BASE_URL}/invoices/success?limit=10",
                headers=headers_auth
            )
            
            if success_response.status_code == 200:
                invoices = success_response.json()
                if isinstance(invoices, list):
                    invoices_list = invoices
                else:
                    invoices_list = invoices.get("invoices", [])
                
                print(f"   Found {len(invoices_list)} successful invoices")
                
                # Look for our invoice
                found = False
                for invoice in invoices_list:
                    if str(invoice.get("tracking_id")) == str(tracking_id):
                        found = True
                        print("\n🎉 SUCCESS! Invoice found in successful list!")
                        print(f"   Invoice ID: {invoice.get('id')}")
                        print(f"   Customer: {invoice.get('customer_name', 'N/A')}")
                        print(f"   Format: {invoice.get('target_format', 'N/A')}")
                        print(f"   Created: {invoice.get('created_at', 'N/A')}")
                        break
                
                if not found:
                    print("\n⚠️  Invoice not in successful list, checking failed...")
                    
                    failed_response = requests.get(
                        f"{API_BASE_URL}/invoices/failed?limit=10",
                        headers=headers_auth
                    )
                    
                    if failed_response.status_code == 200:
                        failed = failed_response.json()
                        if isinstance(failed, list):
                            failed_list = failed
                        else:
                            failed_list = failed.get("invoices", [])
                        
                        for invoice in failed_list:
                            if str(invoice.get("tracking_id")) == str(tracking_id):
                                print("\n❌ Invoice found in FAILED list!")
                                print(f"   Error: {invoice.get('error_message', 'N/A')}")
                                print(f"   Reason: {invoice.get('reason', 'N/A')}")
                                print("\n💡 Check backend logs for details:")
                                print("   Look for processing errors in the terminal")
                                break
            else:
                print(f"❌ Failed to check invoices: {success_response.status_code}")
        else:
            print(f"❌ Login failed: {login_response.status_code}")
    else:
        print("❌ Invoice push failed!")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("  Test Completed")
print("=" * 80)

