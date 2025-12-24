#!/usr/bin/env python3
"""
Test the admin backfill endpoint
"""
import requests
import json

# Configuration
API_URL = "http://localhost:8000"
LOGIN_EMAIL = "testsalmen123@gmail.com"  # Update with your email
LOGIN_PASSWORD = "testsalmen123"  # Update with your password

def test_backfill():
    print("=" * 70)
    print("Testing Admin Backfill Endpoint")
    print("=" * 70)
    print()
    
    # Step 0: Check if backend is running
    print("🔍 Checking if backend is running...")
    try:
        health_check = requests.get(f"{API_URL}/", timeout=5)
        print(f"✅ Backend is running on {API_URL}")
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to backend at {API_URL}")
        print("   Please start the backend server:")
        print("   cd zodiac-api")
        print("   python -m uvicorn app.server:app --reload --host 0.0.0.0 --port 8000")
        return
    except Exception as e:
        print(f"❌ Error checking backend: {e}")
        return
    print()
    
    # Step 1: Login to get token
    print("🔐 Logging in...")
    print(f"   URL: {API_URL}/api/v1/user/auth/login")
    print(f"   Email: {LOGIN_EMAIL}")
    
    try:
        login_response = requests.post(
            f"{API_URL}/api/v1/user/auth/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
            timeout=10
        )
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        print(f"   Response: {login_response.text}")
        print()
        print("💡 Troubleshooting:")
        print("   1. Check if email/password are correct")
        print("   2. Try logging in via the web interface first")
        print("   3. Check backend logs for errors")
        return
    
    token = login_response.json().get("access_token")
    print(f"✅ Logged in successfully")
    print()
    
    # Step 2: Check backfill status
    print("📊 Checking backfill status...")
    status_response = requests.get(
        f"{API_URL}/api/v1/admin/backfill-status",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    print(f"Status Code: {status_response.status_code}")
    print(f"Response: {json.dumps(status_response.json(), indent=2)}")
    print()
    
    # Step 3: Trigger backfill
    print("🚀 Triggering backfill...")
    backfill_response = requests.post(
        f"{API_URL}/api/v1/admin/backfill-business-intelligence",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    print(f"Status Code: {backfill_response.status_code}")
    print(f"Response: {json.dumps(backfill_response.json(), indent=2)}")
    print()
    
    if backfill_response.status_code == 200:
        result = backfill_response.json()
        print("✅ Backfill started successfully!")
        print(f"   Total invoices: {result.get('total_invoices')}")
        print(f"   Estimated time: {result.get('estimated_time_minutes')} minutes")
        print()
        print("⏳ Wait a few minutes, then check the Business tab!")
    else:
        print(f"❌ Backfill failed")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    test_backfill()

