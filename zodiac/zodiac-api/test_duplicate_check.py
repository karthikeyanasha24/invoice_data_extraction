"""
Quick test to diagnose why duplicate check is not working
"""
import requests

BASE_URL = "http://localhost:8000"

# Test credentials
TEST_EMAIL = "puspesh@gmail.com"
TEST_PASSWORD = "12345"

# Simple test XML with a known invoice number
TEST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>TEST-DUPLICATE-CHECK-123</cbc:ID>
    <cbc:IssueDate>2026-02-07</cbc:IssueDate>
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cbc:EndpointID>CUST-001</cbc:EndpointID>
        </cac:Party>
    </cac:AccountingCustomerParty>
</Invoice>'''

def test():
    print("=" * 70)
    print("  TESTING DUPLICATE CHECK")
    print("=" * 70)
    
    # 1. Login
    print("\n[1] Logging in...")
    login_resp = requests.post(
        f"{BASE_URL}/api/v1/user/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    
    if login_resp.status_code != 200:
        print(f"❌ Login failed: {login_resp.status_code}")
        print(login_resp.text)
        return
    
    token = login_resp.json()["access_token"]
    print("✅ Login successful")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Upload first time
    print("\n[2] Uploading invoice (FIRST TIME)...")
    files = {'file': ('test.xml', TEST_XML, 'application/xml')}
    
    resp1 = requests.post(
        f"{BASE_URL}/api/v1/invoices/process",
        headers=headers,
        files=files
    )
    
    print(f"   Status: {resp1.status_code}")
    if resp1.status_code in [200, 202]:
        data = resp1.json()
        tracking_id = data.get("tracking_id")
        print(f"   ✅ Upload successful - Tracking ID: {tracking_id}")
    else:
        print(f"   ❌ Upload failed: {resp1.text}")
        return
    
    # Wait a moment for processing
    import time
    print("\n[3] Waiting 3 seconds for processing...")
    time.sleep(3)
    
    # 3. Upload second time (should be BLOCKED)
    print("\n[4] Uploading SAME invoice (SECOND TIME)...")
    files2 = {'file': ('test.xml', TEST_XML, 'application/xml')}
    
    resp2 = requests.post(
        f"{BASE_URL}/api/v1/invoices/process",
        headers=headers,
        files=files2
    )
    
    print(f"   Status: {resp2.status_code}")
    
    if resp2.status_code == 400:
        print("   ✅ DUPLICATE BLOCKED! (This is correct)")
        print(f"   Error message: {resp2.json()}")
    elif resp2.status_code in [200, 202]:
        print("   ❌ DUPLICATE WAS NOT BLOCKED! (This is the bug)")
        print(f"   Response: {resp2.json()}")
        print("\n🐛 BUG CONFIRMED: Duplicate check is not working!")
    else:
        print(f"   ❓ Unexpected status: {resp2.text}")
    
    print("\n" + "=" * 70)
    print("CHECK BACKEND LOGS FOR DETAILED DEBUG INFO")
    print("Look for:")
    print("  - 'Extracted invoice number'")
    print("  - 'DUPLICATE CHECK START'")
    print("  - 'Found X successful invoices to check against'")
    print("  - Any errors reading files or extracting invoice numbers")
    print("=" * 70)

if __name__ == "__main__":
    test()
