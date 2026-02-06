"""
Test script to verify API key generation and validation flow
Run this to test if the encoding/decoding is working correctly
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.models.user import (
    generate_api_key, 
    hash_api_key, 
    verify_api_key,
    encode_api_key_for_transport,
    decode_api_key_from_transport
)

def test_api_key_flow():
    print("=" * 80)
    print("Testing API Key Generation and Validation Flow")
    print("=" * 80)
    
    # Step 1: Generate API key (simulating what /api-key/generate does)
    print("\n✓ Step 1: Generate API Key")
    raw_api_key = generate_api_key()
    print(f"   Raw API Key: {raw_api_key[:30]}... (length: {len(raw_api_key)})")
    
    # Step 2: Hash it for storage (simulating database storage)
    print("\n✓ Step 2: Hash for Database Storage")
    hashed_key = hash_api_key(raw_api_key)
    print(f"   Hashed: {hashed_key[:40]}...")
    
    # Step 3: Encode for transport (what the API returns to user)
    print("\n✓ Step 3: Encode for Transport (what you receive from /api-key/generate)")
    encoded_key = encode_api_key_for_transport(raw_api_key)
    print(f"   Encoded API Key: {encoded_key[:50]}...")
    print(f"   Full Length: {len(encoded_key)} characters")
    print(f"\n   📋 COPY THIS EXACT VALUE TO POSTMAN:")
    print(f"   {encoded_key}")
    
    # Step 4: Simulate Postman sending request
    print("\n✓ Step 4: Simulate Backend Receiving Request (what happens when you POST)")
    print(f"   Authorization Header should be: Bearer {encoded_key[:50]}...")
    
    # Step 5: Decode (what the backend does)
    print("\n✓ Step 5: Backend Decodes the Key")
    decoded_key = decode_api_key_from_transport(encoded_key)
    if decoded_key:
        print(f"   ✅ Decode successful!")
        print(f"   Decoded matches original: {decoded_key == raw_api_key}")
    else:
        print(f"   ❌ Decode FAILED! This is the error you're seeing!")
        return False
    
    # Step 6: Verify against hash
    print("\n✓ Step 6: Verify Decoded Key Against Hash")
    is_valid = verify_api_key(decoded_key, hashed_key)
    print(f"   Verification result: {'✅ VALID' if is_valid else '❌ INVALID'}")
    
    # Test with common mistakes
    print("\n" + "=" * 80)
    print("Testing Common Mistakes")
    print("=" * 80)
    
    # Mistake 1: Using raw key instead of encoded
    print("\n❌ Mistake 1: Using raw API key (without base64 encoding)")
    result = decode_api_key_from_transport(raw_api_key)
    print(f"   Result: {result if result else 'FAILED - this causes Invalid API key format error'}")
    
    # Mistake 2: Adding extra spaces
    print("\n❌ Mistake 2: Adding spaces around the encoded key")
    result = decode_api_key_from_transport(f" {encoded_key} ")
    print(f"   Result: {result if result else 'FAILED - this causes Invalid API key format error'}")
    
    # Mistake 3: Missing characters
    print("\n❌ Mistake 3: Copying incomplete key (missing last characters)")
    result = decode_api_key_from_transport(encoded_key[:-5])
    print(f"   Result: {result if result else 'FAILED - this causes Invalid API key format error'}")
    
    print("\n" + "=" * 80)
    print("POSTMAN SETUP CHECKLIST")
    print("=" * 80)
    print("""
1. ✓ Generate API key via: POST http://localhost:8000/api/v1/invoices/api-key/generate
   - Use your JWT token for authentication

2. ✓ Copy the EXACT api_key value from the response (already base64 encoded)

3. ✓ In Postman, for the invoice upload request:
   - Go to Authorization tab
   - Select "Bearer Token"
   - Paste the ENCODED key (from step 2) - NO SPACES, NO MODIFICATIONS

4. ✓ The full header should look like:
   Authorization: Bearer <the_long_encoded_string>

5. ✓ Common issues:
   - Don't manually encode/decode the key
   - Don't add extra spaces or newlines
   - Don't modify the key in any way
   - Make sure you copy the ENTIRE key value
""")
    
    return True

if __name__ == "__main__":
    try:
        success = test_api_key_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
