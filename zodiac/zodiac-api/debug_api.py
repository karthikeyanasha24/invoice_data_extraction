#!/usr/bin/env python3
"""
Debug script to test the API endpoint directly
"""
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

def test_api_endpoint():
    """Test the API endpoint directly"""
    try:
        # First, login to get a token
        login_url = "http://localhost:8000/api/v1/user/auth/login"
        login_data = {
            "email": "zackmwangi22@gmail.com",
            "password": "password123"
        }
        
        print("🔐 Logging in...")
        login_response = requests.post(login_url, json=login_data, timeout=10)
        
        if login_response.status_code != 200:
            print(f"❌ Login failed: {login_response.status_code} - {login_response.text}")
            return
        
        token = login_response.json()["access_token"]
        print(f"✅ Login successful, token: {token[:20]}...")
        
        # Now test the failed invoice endpoint
        headers = {"Authorization": f"Bearer {token}"}
        url = "http://localhost:8000/api/v1/invoices/failed/266c4a43-68ff-42e0-afb3-6ff683e0d8e4"
        
        print(f"🔍 Testing endpoint: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        
        print(f"📊 Status Code: {response.status_code}")
        print(f"📊 Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 Response Data Keys: {list(data.keys())}")
            print(f"📊 Has processing_steps_error: {'processing_steps_error' in data}")
            
            if 'processing_steps_error' in data:
                print(f"📊 Processing steps error: {data['processing_steps_error']}")
            else:
                print("❌ processing_steps_error field is missing!")
                
            print(f"📊 Full Response: {json.dumps(data, indent=2)}")
        else:
            print(f"❌ Request failed: {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_api_endpoint()



