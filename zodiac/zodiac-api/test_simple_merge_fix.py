"""
Quick test to verify the Simple Merge fix.
Run this after restarting the backend.
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_simple_merge():
    """Test the simple merge endpoint."""
    
    print("=" * 60)
    print("  Testing Simple Merge Fix")
    print("=" * 60)
    
    # Step 1: Login
    print("\n[Step 1] Logging in...")
    login_response = requests.post(
        f"{BASE_URL}/api/v1/user/auth/login",
        json={
            "email": "puspesh@gmail.com",
            "password": "12345"
        }
    )
    
    if login_response.status_code != 200:
        print(f"[FAIL] Login failed: {login_response.status_code}")
        print(login_response.text)
        return
    
    token = login_response.json()["access_token"]
    print("[OK] Login successful!")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Step 2: List existing merged documents
    print("\n[Step 2] Listing existing merged documents...")
    list_response = requests.get(
        f"{BASE_URL}/api/v1/sat/simple-merge/",
        headers=headers,
        params={"fiscal_year": 2025, "fiscal_period": 11}
    )
    
    if list_response.status_code != 200:
        print(f"[FAIL] List failed: {list_response.status_code}")
        print(list_response.text)
        return
    
    print(f"[OK] List successful! Found {list_response.json()['total']} existing merged documents")
    
    # Step 3: Try to merge documents
    print("\n[Step 3] Attempting to merge documents...")
    merge_response = requests.post(
        f"{BASE_URL}/api/v1/sat/simple-merge/merge",
        headers=headers,
        json={
            "fiscal_year": 2025,
            "fiscal_period": 11,
            "supplier_rfc": "IIA040805DZ4"
        }
    )
    
    if merge_response.status_code == 200:
        merged_doc = merge_response.json()
        print("[OK] Merge successful!")
        print(f"   - Document ID: {merged_doc['id']}")
        print(f"   - Vendor: {merged_doc['vendor_name']} ({merged_doc['vendor_rfc']})")
        print(f"   - Period: {merged_doc['fiscal_period']}/{merged_doc['fiscal_year']}")
        print(f"   - Documents: {merged_doc['document_count']}")
        print(f"   - Total: {merged_doc['total_amount']} {merged_doc['currency']}")
        print(f"   - Types: {', '.join(merged_doc['document_types'])}")
        return merged_doc['id']
    else:
        print(f"[FAIL] Merge failed: {merge_response.status_code}")
        print(merge_response.text)
        return None

if __name__ == "__main__":
    test_simple_merge()

