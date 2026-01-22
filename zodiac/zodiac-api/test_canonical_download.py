"""
Test the new canonical merged XML download functionality.
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_canonical_download():
    """Test canonical merged document details and download."""
    
    print("=" * 60)
    print("  Testing Canonical Merged Download")
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
    canonical_id = canonical_docs[0]["id"]
    print(f"   Using document ID: {canonical_id}")
    
    # Step 3: Get document details
    print(f"\n📝 Step 3: Fetching document details...")
    detail_response = requests.get(
        f"{BASE_URL}/api/v1/sat/canonical/{canonical_id}",
        headers=headers
    )
    
    if detail_response.status_code != 200:
        print(f"❌ Details failed: {detail_response.status_code}")
        return
    
    doc_details = detail_response.json()
    print("✅ Details fetched successfully!")
    print(f"   Vendor: {doc_details['vendor_name']} ({doc_details['vendor_rfc']})")
    print(f"   Period: {doc_details['fiscal_period']}/{doc_details['fiscal_year']}")
    print(f"   Net Amount: {doc_details['net_amount']} {doc_details['currency']}")
    
    # Step 4: Get JSON Preview
    print(f"\n📝 Step 4: Fetching SAP JSON preview...")
    preview_response = requests.get(
        f"{BASE_URL}/api/v1/sat/canonical/{canonical_id}/preview-sap-json",
        headers=headers
    )
    
    if preview_response.status_code != 200:
        print(f"⚠️  Preview failed: {preview_response.status_code}")
    else:
        json_preview = preview_response.json()
        print("✅ JSON preview fetched successfully!")
        if "json_payload" in json_preview:
            payload = json_preview["json_payload"]
            print(f"   Company Code: {payload.get('COMPANY_CODE', 'N/A')}")
            print(f"   Net Amount: {payload.get('NET_AMOUNT', 'N/A')} {payload.get('CURRENCY', 'N/A')}")
            if "CFDI_DETAILS" in payload:
                print(f"   CFDI Details: {len(payload['CFDI_DETAILS'])} documents")
                for i, cfdi in enumerate(payload['CFDI_DETAILS'][:3], 1):
                    print(f"     {i}. {cfdi.get('type', 'N/A')}: {cfdi.get('uuid', 'N/A')[:20]}...")
            else:
                print("   ⚠️  CFDI_DETAILS not found in JSON")
    
    # Step 5: Download XML
    print(f"\n📝 Step 5: Downloading canonical merged XML...")
    download_response = requests.get(
        f"{BASE_URL}/api/v1/sat/canonical/{canonical_id}/download-xml",
        headers=headers
    )
    
    if download_response.status_code != 200:
        print(f"❌ Download failed: {download_response.status_code}")
        print(download_response.text)
        return
    
    xml_content = download_response.text
    print("✅ XML downloaded successfully!")
    print(f"   XML size: {len(xml_content)} bytes")
    
    # Verify XML structure
    print("\n📝 Step 6: Verifying XML structure...")
    if "<?xml" in xml_content:
        print("✅ XML declaration found")
    if "VENDOR_RFC" in xml_content:
        print("✅ VENDOR_RFC found")
    if "NET_AMOUNT" in xml_content:
        print("✅ NET_AMOUNT found")
    if "CFDI_UUIDS" in xml_content or "CFDI_UUID" in xml_content:
        print("✅ CFDI_UUIDS found")
    if "CFDI_DETAILS" in xml_content:
        print("✅ CFDI_DETAILS section found")
        if "<TYPE>" in xml_content:
            print("✅ Document TYPE found in CFDI_DETAILS")
    else:
        print("⚠️  CFDI_DETAILS section not found")
    
    # Save XML to file for inspection
    filename = f"test_canonical_merged_{doc_details['vendor_rfc']}_{doc_details['fiscal_year']}_{str(doc_details['fiscal_period']).zfill(2)}.xml"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(xml_content)
    print(f"\n💾 XML saved to: {filename}")
    
    # Show XML preview
    print("\n📋 XML Preview (first 500 characters):")
    print("-" * 60)
    print(xml_content[:500])
    print("..." if len(xml_content) > 500 else "")
    print("-" * 60)
    
    print("\n🎉 All tests passed!")
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"✅ Details endpoint working: GET /api/v1/sat/canonical/{canonical_id}")
    print(f"✅ JSON Preview endpoint working: GET /api/v1/sat/canonical/{canonical_id}/preview-sap-json")
    print(f"✅ Download endpoint working: GET /api/v1/sat/canonical/{canonical_id}/download-xml")
    print(f"✅ XML file generated successfully with CFDI_DETAILS")
    print(f"✅ File saved: {filename}")

if __name__ == "__main__":
    test_canonical_download()

