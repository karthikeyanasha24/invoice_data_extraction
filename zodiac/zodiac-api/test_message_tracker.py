"""
Simple test script to check if message tracker / status updates are working
"""
import requests
import time
import sys

# ===== CONFIGURATION =====
API_URL = "http://localhost:8000"
API_KEY = "test-api-key-123"  # The x-api-key you use in Postman (NOT OpenAI key!)
TEST_FILE = "test_invoice_simple.xml"  # Test XML file in same directory

print("🧪 ZODIAC MESSAGE TRACKER TEST")
print("=" * 80)
print(f"API URL: {API_URL}")
print(f"API Key: {API_KEY[:20]}...")
print(f"Test File: {TEST_FILE}")
print("=" * 80)

# Step 1: Upload invoice
print("\n1️⃣ UPLOADING INVOICE...")
try:
    with open(TEST_FILE, "rb") as f:
        response = requests.post(
            f"{API_URL}/api/v1/invoices/api/process",
            files={"file": (TEST_FILE, f, "application/xml")},
            params={"strict_validation": "false"},
            headers={"x-api-key": API_KEY}
        )
except FileNotFoundError:
    print(f"❌ ERROR: File '{TEST_FILE}' not found!")
    print("   Please update TEST_FILE variable with your XML file path")
    sys.exit(1)
except Exception as e:
    print(f"❌ ERROR: {e}")
    sys.exit(1)

print(f"   Response Status: {response.status_code}")

if response.status_code not in [200, 202]:
    print(f"❌ Upload failed!")
    print(f"   Response: {response.text}")
    sys.exit(1)

try:
    upload_data = response.json()
    tracking_id = upload_data.get("tracking_id")
    
    if not tracking_id:
        print(f"❌ No tracking_id in response!")
        print(f"   Response: {upload_data}")
        sys.exit(1)
    
    print(f"✅ Upload successful!")
    print(f"   Tracking ID: {tracking_id}")
    
except Exception as e:
    print(f"❌ Failed to parse response: {e}")
    print(f"   Response text: {response.text}")
    sys.exit(1)

# Step 2: Poll status
print("\n2️⃣ POLLING STATUS (10 times, 500ms interval)...")
print("-" * 80)

found_steps = []
all_polls_empty = True

for poll_num in range(10):
    time.sleep(0.5)  # Wait 500ms between polls
    
    try:
        status_response = requests.get(
            f"{API_URL}/api/v1/invoices/status/{tracking_id}",
            headers={"x-api-key": API_KEY}
        )
        
        if status_response.status_code == 404:
            print(f"   Poll {poll_num+1}: ❌ Status not found (404)")
            continue
            
        if status_response.status_code == 401:
            print(f"   Poll {poll_num+1}: ❌ Unauthorized (401) - Check API key!")
            continue
            
        if status_response.status_code != 200:
            print(f"   Poll {poll_num+1}: ❌ HTTP {status_response.status_code}")
            continue
        
        data = status_response.json()
        steps = data.get("processing_steps", [])
        
        if len(steps) > 0:
            all_polls_empty = False
        
        # Check for new steps
        new_steps = [s for s in steps if s['step_number'] not in [fs['step_number'] for fs in found_steps]]
        
        if new_steps:
            for step in new_steps:
                status_icon = "✅" if step.get("success") else "❌"
                print(f"   Poll {poll_num+1}: {status_icon} NEW - Step {step['step_number']}: {step['step_name']}")
                found_steps.append(step)
        else:
            if len(steps) > 0:
                print(f"   Poll {poll_num+1}: ⏳ No new steps ({len(steps)} total)")
            else:
                print(f"   Poll {poll_num+1}: ⚠️  Empty (0 steps)")
        
        # Check if completed
        if any(s.get("step_name") == "Database Save" and s.get("success") for s in steps):
            print(f"\n✅ Processing completed at poll {poll_num+1}!")
            break
            
    except Exception as e:
        print(f"   Poll {poll_num+1}: ❌ Error: {e}")

# Step 3: Summary
print("\n" + "=" * 80)
print("3️⃣ SUMMARY")
print("=" * 80)

if len(found_steps) == 0:
    print("❌ ISSUE FOUND: No status steps were ever returned!")
    print("\nPossible causes:")
    print("   1. Backend not calling status_tracker.update_step()")
    print("   2. Status tracker not initialized")
    print("   3. Authentication issue")
    print("\n⚠️  Check backend logs for errors")
    
elif all_polls_empty:
    print("❌ ISSUE FOUND: Status was never found (all polls returned 404 or empty)")
    print("\nPossible causes:")
    print("   1. status_tracker.initialize_status() not being called")
    print("   2. Tracking ID mismatch")
    print("\n⚠️  Check backend logs for: 'Status tracker initialized'")
    
elif len(found_steps) < 3:
    print(f"⚠️  WARNING: Only {len(found_steps)} step(s) found")
    print("   Expected at least 3-5 steps")
    print("\nPossible causes:")
    print("   1. Processing failed early")
    print("   2. Some steps not being tracked")
    print("\n⚠️  Check backend logs for errors")
    
else:
    print(f"✅ SUCCESS: Status tracker is working!")
    print(f"   Total steps found: {len(found_steps)}")
    
print("\nSteps found:")
for step in found_steps:
    status_icon = "✅" if step.get("success") else "❌"
    print(f"   {status_icon} Step {step['step_number']}: {step['step_name']} - {step.get('message', 'No message')}")

# Step 4: Check database
print("\n4️⃣ CHECKING DATABASE...")
try:
    db_response = requests.get(
        f"{API_URL}/api/v1/invoices/success",
        headers={"x-api-key": API_KEY},
        params={"limit": 10}
    )
    
    if db_response.status_code == 200:
        invoices = db_response.json()
        found_in_db = any(inv.get("tracking_id") == tracking_id for inv in invoices)
        
        if found_in_db:
            print(f"✅ Invoice found in success table")
        else:
            # Check failed table
            failed_response = requests.get(
                f"{API_URL}/api/v1/invoices/failed",
                headers={"x-api-key": API_KEY},
                params={"limit": 10}
            )
            if failed_response.status_code == 200:
                failed_invoices = failed_response.json()
                found_in_failed = any(inv.get("tracking_id") == tracking_id for inv in failed_invoices)
                
                if found_in_failed:
                    print(f"⚠️  Invoice found in FAILED table")
                else:
                    print(f"⏳ Invoice not found in database yet (still processing)")
            else:
                print(f"❓ Could not check failed table")
    else:
        print(f"❌ Could not check database (HTTP {db_response.status_code})")
        
except Exception as e:
    print(f"❌ Database check error: {e}")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)

