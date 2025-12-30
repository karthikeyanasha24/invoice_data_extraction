"""Test the SAT documents endpoint directly"""
import requests

BASE_URL = "http://localhost:8000"

# Login credentials
email = "testsalmen123@gmail.com"
password = "testsalmen123"

print("\n🔐 Logging in...")
login_response = requests.post(
    f"{BASE_URL}/api/v1/user/auth/login",
    json={"email": email, "password": password}
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print(login_response.text)
    exit(1)

token_data = login_response.json()
ACCESS_TOKEN = token_data.get("access_token")
user_info = token_data.get("user", {})

print(f"✅ Logged in as: {user_info.get('email')} (ID: {user_info.get('id')})")

# Now test SAT documents endpoint
url = f"{BASE_URL}/api/v1/sat/documents"
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}
params = {
    "skip": 0,
    "limit": 100
}

print(f"\n🔍 Testing SAT documents endpoint...")
print(f"URL: {url}")
print(f"Params: {params}\n")

try:
    response = requests.get(url, headers=headers, params=params)
    
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n✅ Success! Found {data.get('total', 0)} documents")
        
        if 'documents' in data and len(data['documents']) > 0:
            print(f"\nFirst 3 documents:")
            for i, doc in enumerate(data['documents'][:3]):
                print(f"  {i+1}. {doc.get('doc_type')}: RFC={doc.get('supplier_rfc')}, Total={doc.get('total')}")
        else:
            print("\n⚠️ No documents found!")
            print(f"User ID in token: {user_info.get('id')}")
            print("Make sure documents are created for this user ID")
    else:
        print(f"\n❌ Error: {response.status_code}")
        print(f"Response: {response.text[:500]}")
        
except Exception as e:
    print(f"\n❌ Exception: {e}")
    import traceback
    traceback.print_exc()

