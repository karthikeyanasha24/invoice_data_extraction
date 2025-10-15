#!/usr/bin/env python3
import requests
import json

def test_api_with_auth():
    """Test the API endpoint for failed invoice details with authentication"""
    try:
        # First, let's try to get an auth token
        login_url = "http://localhost:8000/api/v1/auth/login"
        login_data = {
            "email": "zackmwangi22@gmail.com",
            "password": "password123"
        }
        
        print("Attempting to login...")
        login_response = requests.post(login_url, json=login_data, timeout=10)
        
        if login_response.status_code == 200:
            auth_data = login_response.json()
            token = auth_data.get("access_token")
            print(f"Login successful, got token: {token[:20]}...")
            
            # Now test the failed invoice endpoint with auth
            url = "http://localhost:8000/api/v1/invoices/failed/266c4a43-68ff-42e0-afb3-6ff683e0d8e4"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            print(f"Testing API endpoint: {url}")
            response = requests.get(url, headers=headers, timeout=10)
            
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Response Data: {json.dumps(data, indent=2)}")
                
                # Check if processing_steps_error is present
                if 'processing_steps_error' in data:
                    print(f"✅ processing_steps_error found: {len(data['processing_steps_error'])} errors")
                    for i, error in enumerate(data['processing_steps_error']):
                        print(f"  Error {i+1}: {error.get('error_message', 'No message')}")
                else:
                    print("❌ processing_steps_error not found in response")
            else:
                print(f"Error Response: {response.text}")
        else:
            print(f"Login failed: {login_response.status_code} - {login_response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: API server is not running or not accessible")
    except requests.exceptions.Timeout:
        print("❌ Timeout Error: API server took too long to respond")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_api_without_auth():
    """Test the API endpoint without authentication to see the error"""
    try:
        url = "http://localhost:8000/api/v1/invoices/failed/266c4a43-68ff-42e0-afb3-6ff683e0d8e4"
        
        print(f"Testing API endpoint without auth: {url}")
        response = requests.get(url, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("=== Testing API without authentication ===")
    test_api_without_auth()
    
    print("\n=== Testing API with authentication ===")
    test_api_with_auth()
