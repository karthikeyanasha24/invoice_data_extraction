#!/usr/bin/env python3
"""
Quick test to simulate SAP pushing an invoice to Bridge Portal
This tests the API endpoint that SAP would use
"""

import requests
import time
import sys
from pathlib import Path

# Configuration
API_URL = "http://localhost:8000/api/v1/invoices/api/process"
API_KEY = "NmxwS2sxNnRsZy1SVThOVkFWdTMtN3p5MGJhLU1IQUF5TExGVmRFaUNqNndycW0xRlk0VTM4TTN4bG4xSV9DNGVhbk0wMll0bFU4LVliQU5NbFZEelE="

# Test invoice file (UBL format)
INVOICE_FILE = "0090040077_PEPOLDBNA.xml"

def main():
    print("\n" + "="*60)
    print("🚀 SIMULATING SAP PUSHING INVOICE TO BRIDGE PORTAL")
    print("="*60 + "\n")
    
    # Check if file exists
    if not Path(INVOICE_FILE).exists():
        print(f"❌ Error: Invoice file not found: {INVOICE_FILE}")
        print(f"💡 Make sure you're in the zodiac-api directory")
        return 1
    
    print(f"📄 Invoice File: {INVOICE_FILE}")
    print(f"🌐 API Endpoint: {API_URL}")
    print(f"🔑 Using API Key: {API_KEY[:20]}...")
    print()
    
    # Prepare request
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }
    
    files = {
        "file": (INVOICE_FILE, open(INVOICE_FILE, "rb"), "application/xml")
    }
    
    print("📤 Sending invoice to Bridge Portal...")
    
    try:
        # Send request (this is what SAP would do)
        response = requests.post(API_URL, headers=headers, files=files, timeout=30)
        
        print(f"📥 Response Status: {response.status_code}")
        print()
        
        if response.status_code == 200:
            data = response.json()
            tracking_id = data.get("tracking_id")
            message = data.get("message")
            status = data.get("status")
            
            print("✅ SUCCESS! Invoice pushed to Bridge Portal")
            print(f"   Tracking ID: {tracking_id}")
            print(f"   Message: {message}")
            print(f"   Status: {status}")
            print()
            print("🎯 NEXT STEPS:")
            print("   1. Wait 5-10 seconds for processing")
            print("   2. Open Bridge Portal: http://localhost:3000")
            print("   3. Login and go to Invoices page")
            print("   4. Look for your invoice with customer 'EDIFACTMX'")
            print()
            print("💡 This is exactly how SAP would push invoices!")
            print()
            
            # Wait and check
            print("⏳ Waiting 5 seconds for processing...")
            time.sleep(5)
            
            # Try to check status
            print("\n🔍 Checking invoice status...")
            login_url = "http://localhost:8000/api/v1/user/auth/login"
            login_data = {
                "email": "testsalmen123@gmail.com",
                "password": "testsalmen123"
            }
            
            try:
                login_response = requests.post(login_url, json=login_data)
                if login_response.status_code == 200:
                    access_token = login_response.json().get("access_token")
                    
                    # Check successful invoices
                    success_url = "http://localhost:8000/api/v1/invoices/success?limit=5"
                    check_headers = {"Authorization": f"Bearer {access_token}"}
                    success_response = requests.get(success_url, headers=check_headers)
                    
                    if success_response.status_code == 200:
                        invoices = success_response.json()
                        found = False
                        for inv in invoices:
                            if inv.get("tracking_id") == tracking_id:
                                print(f"✅ Invoice found in database!")
                                print(f"   Customer: {inv.get('customerName')}")
                                print(f"   Invoice ID: {inv.get('customerId')}")
                                print(f"   Status: {inv.get('status')}")
                                found = True
                                break
                        
                        if not found:
                            print("⏳ Invoice is still processing...")
                            print("   Check the Invoices page in a few seconds")
            except Exception as e:
                print(f"💡 Could not auto-check status: {e}")
                print("   Check the Invoices page manually")
            
            return 0
            
        else:
            print(f"❌ ERROR: {response.status_code}")
            print(f"Response: {response.text}")
            return 1
            
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to Bridge Portal")
        print("💡 Make sure the backend is running:")
        print("   cd zodiac-api && python -m uvicorn app.server:app --reload")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

