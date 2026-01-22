"""
Test the new CFDI_DETAILS field in canonical merge preview.
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_canonical_cfdi_details():
    """Test that CFDI_DETAILS shows document types."""
    
    print("=" * 60)
    print("  Testing Canonical Merge CFDI Details")
    print("=" * 60)
    
    # Step 1: Login
    print("\n📝 Step 1: Logging in...")
    login_response = requests.post(
        f"{BASE_URL}/api/v1/user/auth/login",
        json={
            "email": "testsalmen123@gmail.com",
            "password": "testsalmen123"
        }
    )
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        return
    
    token = login_response.json()["access_token"]
    print("✅ Login successful!")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Step 2: List canonical documents
    print("\n📝 Step 2: Listing canonical documents...")
    list_response = requests.get(
        f"{BASE_URL}/api/v1/sat/canonical",
        headers=headers,
        params={"fiscal_year": 2025, "fiscal_period": 11}
    )
    
    if list_response.status_code != 200:
        print(f"❌ List failed: {list_response.status_code}")
        return
    
    canonical_docs = list_response.json()["documents"]
    
    if not canonical_docs:
        print("⚠️  No canonical documents found for testing.")
        print("💡 Tip: Go to the Canonical Merge tab and merge some documents first.")
        return
    
    print(f"✅ Found {len(canonical_docs)} canonical documents")
    
    # Step 3: Preview SAP JSON for first document
    canonical_id = canonical_docs[0]["id"]
    print(f"\n📝 Step 3: Previewing SAP JSON for document {canonical_id}...")
    
    preview_response = requests.get(
        f"{BASE_URL}/api/v1/sat/canonical/{canonical_id}/preview-sap-json",
        headers=headers
    )
    
    if preview_response.status_code != 200:
        print(f"❌ Preview failed: {preview_response.status_code}")
        print(preview_response.text)
        return
    
    sap_payload = preview_response.json()["json_payload"]
    
    print("\n✅ Preview successful!")
    print("\n" + "=" * 60)
    print("  SAP JSON Payload (Pretty Printed)")
    print("=" * 60)
    print(json.dumps(sap_payload, indent=2))
    
    # Verify CFDI_DETAILS exists
    print("\n" + "=" * 60)
    print("  Verification")
    print("=" * 60)
    
    if "CFDI_DETAILS" in sap_payload:
        print("✅ CFDI_DETAILS field exists!")
        
        cfdi_details = sap_payload["CFDI_DETAILS"]
        print(f"✅ Found {len(cfdi_details)} CFDIs with details")
        
        print("\n📋 CFDI Details:")
        for idx, detail in enumerate(cfdi_details, 1):
            print(f"\n   {idx}. Type: {detail['type']}")
            print(f"      UUID: {detail['uuid']}")
            print(f"      Total: {detail['total']} {detail['currency']}")
            print(f"      Date: {detail['date']}")
        
        # Check document types
        doc_types = [d['type'] for d in cfdi_details]
        print(f"\n✅ Document types found: {', '.join(set(doc_types))}")
        
        print("\n🎉 Success! CFDI_DETAILS is working correctly!")
        print("   Each UUID now shows its document type (INVOICE, PAYMENT, CREDIT_NOTE)")
        
    else:
        print("❌ CFDI_DETAILS field not found in payload!")
        print("   Available fields:", list(sap_payload.keys()))

if __name__ == "__main__":
    test_canonical_cfdi_details()

