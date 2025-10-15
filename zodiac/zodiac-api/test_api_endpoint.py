#!/usr/bin/env python3
import requests
import json

def test_api():
    """Test the API endpoint for failed invoice details"""
    try:
        # Test the failed invoice endpoint
        url = "http://localhost:8000/api/v1/invoices/failed/266c4a43-68ff-42e0-afb3-6ff683e0d8e4"
        
        print(f"Testing API endpoint: {url}")
        
        response = requests.get(url, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response Data: {json.dumps(data, indent=2)}")
        else:
            print(f"Error Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: API server is not running or not accessible")
    except requests.exceptions.Timeout:
        print("❌ Timeout Error: API server took too long to respond")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_api()
