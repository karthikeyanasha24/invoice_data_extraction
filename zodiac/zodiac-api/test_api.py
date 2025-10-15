#!/usr/bin/env python3
"""
Test script for Zodiac API endpoints
"""
import requests
import json

def test_api():
    base_url = "http://localhost:8000"
    
    print("Testing Zodiac API endpoints...")
    
    # Test root endpoint
    try:
        response = requests.get(f"{base_url}/")
        print(f"✓ Root endpoint: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"✗ Root endpoint failed: {e}")
    
    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/health")
        print(f"✓ Health endpoint: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"✗ Health endpoint failed: {e}")
    
    # Test invoices endpoint (should work even without DB)
    try:
        response = requests.get(f"{base_url}/api/v1/invoices/")
        print(f"✓ Invoices endpoint: {response.status_code}")
        if response.status_code == 200:
            print(f"  Response: {response.json()}")
    except Exception as e:
        print(f"✗ Invoices endpoint failed: {e}")
    
    print("\nAPI Documentation available at:")
    print(f"- Swagger UI: {base_url}/docs")
    print(f"- ReDoc: {base_url}/redoc")

if __name__ == "__main__":
    test_api()


