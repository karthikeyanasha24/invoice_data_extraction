#!/usr/bin/env python3
"""
Simulate ERP pushing invoices to the portal via API
This creates invoices with request_type='api' (not 'web')
"""
import requests
import time
from pathlib import Path

# Configuration
API_URL = "http://localhost:8000/api/v1/invoices/api/process"
# Get this from portal: Profile -> API Settings -> Generate API Key
API_KEY = "PUT_YOUR_API_KEY_HERE"  # Format: zdk_...
INVOICE_FILE = "test_invoice_simple.xml"

def push_invoice_as_erp():
    """
    Simulate ERP pushing an invoice to the portal
    This will create an invoice with request_type='api'
    
    NOTE: You need a valid API key from the portal!
    Login -> Profile -> API Settings -> Generate API Key
    """
    print("=" * 70)
    print("🔌 SIMULATING ERP INVOICE PUSH")
    print("=" * 70)
    
    # Check API key
    if API_KEY == "PUT_YOUR_API_KEY_HERE":
        print("\n❌ ERROR: No API key configured!")
        print("\n📝 To get an API key:")
        print("   1. Login to portal (http://localhost:3000)")
        print("   2. Go to Profile/Settings")
        print("   3. Find 'API Key' section")
        print("   4. Click 'Generate New API Key'")
        print("   5. Copy the key and paste it in this script (line 13)")
        print("\n💡 The key should look like: zdk_abc123xyz...")
        return
    
    # Check if file exists
    if not Path(INVOICE_FILE).exists():
        print(f"\n❌ Error: File '{INVOICE_FILE}' not found!")
        print(f"   Make sure {INVOICE_FILE} exists in the current directory")
        return
    
    print(f"\n📁 File: {INVOICE_FILE}")
    print(f"🌐 URL:  {API_URL}")
    print(f"🔑 API Key: {API_KEY[:20]}... (hidden)")
    print("\n🚀 Pushing invoice to portal (as ERP would do)...\n")
    
    try:
        # Prepare the request (exactly as ERP would)
        # API key should be sent as Bearer token
        headers = {
            'Authorization': f'Bearer {API_KEY}'
        }
        
        files = {
            'file': open(INVOICE_FILE, 'rb')
        }
        
        # Send the request
        response = requests.post(API_URL, headers=headers, files=files)
        
        print(f"📊 Response Status: {response.status_code}")
        print(f"📋 Response Body:")
        print(f"   {response.json()}")
        
        if response.status_code == 202:
            tracking_id = response.json().get('tracking_id')
            print(f"\n✅ SUCCESS! Invoice pushed as ERP would.")
            print(f"   Tracking ID: {tracking_id}")
            print(f"   This invoice will have request_type='api' in database")
            
            print(f"\n⏳ Waiting 2 seconds for processing...")
            time.sleep(2)
            
            print(f"\n💡 To verify it's an ERP invoice, run:")
            print(f"   python check_backend_invoices.py")
            print(f"\n   You should now see:")
            print(f"   🔌 API/ERP Pushes: 1  ← This should be > 0 now!")
            
        else:
            print(f"\n❌ FAILED! Status: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to API!")
        print("   Make sure the FastAPI server is running:")
        print("   cd zodiac-api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

def push_multiple_invoices(count=3):
    """Push multiple invoices to simulate ERP batch processing"""
    print("\n" + "=" * 70)
    print(f"🔄 PUSHING {count} INVOICES (BATCH MODE)")
    print("=" * 70)
    
    for i in range(count):
        print(f"\n📤 Pushing invoice {i+1}/{count}...")
        
        try:
            headers = {'Authorization': f'Bearer {API_KEY}'}
            files = {'file': open(INVOICE_FILE, 'rb')}
            response = requests.post(API_URL, headers=headers, files=files)
            
            if response.status_code == 202:
                tracking_id = response.json().get('tracking_id')
                print(f"   ✅ Success! Tracking: {tracking_id}")
            else:
                print(f"   ❌ Failed! Status: {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Wait a bit between requests
        if i < count - 1:
            time.sleep(1)
    
    print(f"\n✅ Batch push complete!")
    print(f"💡 Run 'python check_backend_invoices.py' to see the results")

if __name__ == "__main__":
    import sys
    
    print("\n🔌 ERP INVOICE PUSH SIMULATOR")
    print("This simulates how the ERP pushes invoices to the portal\n")
    
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        # Push multiple invoices
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        push_multiple_invoices(count)
    else:
        # Push single invoice
        push_invoice_as_erp()
    
    print("\n" + "=" * 70)
    print("✅ DONE")
    print("=" * 70)
    print()

