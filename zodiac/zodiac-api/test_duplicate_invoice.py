"""
Test script to verify duplicate invoice prevention works correctly
"""
import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8000"

def print_section(title):
    """Print formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def test_duplicate_prevention():
    """Test that duplicate invoices are blocked"""
    
    print_section("DUPLICATE INVOICE PREVENTION TEST")
    
    # Step 1: Login
    print("\n[Step 1] Logging in...")
    try:
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
    except Exception as e:
        print(f"[FAIL] Login error: {e}")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Step 2: Find a test XML file
    print_section("TEST INVOICE UPLOAD")
    
    # Look for test XML files
    test_files = list(Path("test_files").glob("*.xml")) if Path("test_files").exists() else []
    
    if not test_files:
        print("[WARN] No test XML files found in test_files/ directory")
        print("       Please create test_files/ directory and add test XML files")
        print("\n[INFO] You can manually test by:")
        print("       1. Upload an invoice via the UI at http://localhost:3000/invoices")
        print("       2. Wait for it to show 'successful' status")
        print("       3. Try uploading the SAME invoice again")
        print("       4. You should see an error: 'Invoice #XXX has already been processed'")
        return
    
    test_file = test_files[0]
    print(f"[INFO] Using test file: {test_file.name}")
    
    # Step 3: First upload (should succeed)
    print("\n[Step 3] First upload - should succeed...")
    try:
        with open(test_file, 'rb') as f:
            files = {'file': (test_file.name, f, 'application/xml')}
            
            response = requests.post(
                f"{BASE_URL}/api/v1/invoices/process",
                headers=headers,
                files=files,
                data={'strict_validation': 'false'}
            )
        
        if response.status_code in [200, 202]:
            print(f"[OK] First upload accepted: {response.status_code}")
            result = response.json()
            tracking_id = result.get('tracking_id')
            print(f"     Tracking ID: {tracking_id}")
            
            # Wait for processing to complete
            print("\n[INFO] Waiting 5 seconds for processing to complete...")
            time.sleep(5)
            
            # Check status
            status_response = requests.get(
                f"{BASE_URL}/api/v1/invoices/status/{tracking_id}",
                headers=headers
            )
            
            if status_response.status_code == 200:
                status_data = status_response.json()
                final_status = status_data.get('overall_status', {}).get('status')
                print(f"[INFO] Processing status: {final_status}")
                
                if final_status == 'completed':
                    print("[OK] Processing completed successfully!")
                elif final_status == 'failed':
                    print("[WARN] Processing failed - but that's OK for this test")
                    print("       The duplicate check should still work")
                else:
                    print(f"[INFO] Status: {final_status} - waiting a bit more...")
                    time.sleep(3)
            
        else:
            print(f"[FAIL] First upload failed: {response.status_code}")
            print(f"       Response: {response.text}")
            return
            
    except Exception as e:
        print(f"[FAIL] First upload error: {e}")
        return
    
    # Step 4: Second upload (should be blocked)
    print_section("DUPLICATE UPLOAD TEST")
    print("\n[Step 4] Second upload - should be BLOCKED...")
    
    try:
        with open(test_file, 'rb') as f:
            files = {'file': (test_file.name, f, 'application/xml')}
            
            response = requests.post(
                f"{BASE_URL}/api/v1/invoices/process",
                headers=headers,
                files=files,
                data={'strict_validation': 'false'}
            )
        
        if response.status_code == 400:
            error_detail = response.json().get('detail', '')
            
            if 'already been successfully processed' in error_detail:
                print("[✅ PASS] Duplicate blocked with correct error message!")
                print(f"         Error: {error_detail}")
                print("\n" + "=" * 70)
                print("  🎉 DUPLICATE PREVENTION WORKING CORRECTLY!")
                print("=" * 70)
            else:
                print(f"[WARN] Got 400 error but unexpected message:")
                print(f"       {error_detail}")
        
        elif response.status_code in [200, 202]:
            print("[❌ FAIL] Second upload was accepted - DUPLICATE CHECK NOT WORKING!")
            print(f"          Status: {response.status_code}")
            print(f"          Response: {response.json()}")
            print("\n[DEBUG] Check backend logs for:")
            print("        - '📄 Extracted invoice number from upload'")
            print("        - '🔍 Checking for duplicate invoice number'")
            print("        - '🚫 DUPLICATE DETECTED'")
            
        else:
            print(f"[FAIL] Unexpected status code: {response.status_code}")
            print(f"       Response: {response.text}")
            
    except Exception as e:
        print(f"[FAIL] Second upload error: {e}")
        return
    
    # Step 5: Check backend logs
    print_section("DEBUGGING HELP")
    print("""
To check backend logs for duplicate detection:

    tail -f logs/zodiac-api.log | grep -E "📄|🔍|🚫|duplicate"

Expected log output:
    📄 Extracted invoice number from upload: INV-12345
    🔍 Checking for duplicate invoice number: INV-12345
       Found 1 successful invoices to check
    ⚠️ Duplicate found! Invoice #INV-12345 already exists
    🚫 DUPLICATE DETECTED - Invoice #INV-12345 already exists!

If you don't see these logs:
    1. Check if invoice number extraction is working
    2. Verify XML has <cbc:ID> element
    3. Check if first invoice was actually successful
    4. Try with a different test XML file
    """)


if __name__ == "__main__":
    test_duplicate_prevention()
