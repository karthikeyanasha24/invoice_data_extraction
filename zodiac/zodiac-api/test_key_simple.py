"""
Simple standalone test for API key encoding/decoding
"""

import base64
import secrets

def generate_api_key():
    """Generate a secure random API key"""
    return secrets.token_urlsafe(48)

def encode_api_key_for_transport(api_key: str) -> str:
    """Encode API key for transport (base64)."""
    return base64.b64encode(api_key.encode('utf-8')).decode('utf-8')

def decode_api_key_from_transport(encoded_key: str) -> str:
    """Decode API key from transport (base64)."""
    try:
        return base64.b64decode(encoded_key.encode('utf-8')).decode('utf-8')
    except Exception:
        return None

# Test the flow
print("=" * 80)
print("API Key Test - Simulating the exact flow")
print("=" * 80)

# Step 1: Generate
raw_key = generate_api_key()
print(f"\n1. Generated Raw Key (64 chars): {raw_key}")

# Step 2: Encode (what /api-key/generate returns)
encoded = encode_api_key_for_transport(raw_key)
print(f"\n2. Encoded for Transport (what API returns):")
print(f"   {encoded}")
print(f"   Length: {len(encoded)} characters")

# Step 3: Use in Postman
print(f"\n3. In Postman Authorization:")
print(f"   Type: Bearer Token")
print(f"   Token: {encoded}")

# Step 4: Backend receives and decodes
decoded = decode_api_key_from_transport(encoded)
print(f"\n4. Backend Decodes:")
print(f"   Success: {decoded is not None}")
print(f"   Matches Original: {decoded == raw_key}")

# Test common mistakes
print("\n" + "=" * 80)
print("COMMON MISTAKES THAT CAUSE 'Invalid API key format'")
print("=" * 80)

print("\n[X] Mistake 1: Using raw key directly (not base64 encoded)")
result = decode_api_key_from_transport(raw_key)
print(f"   Decode result: {result if result else 'FAILED'}")

print("\n[X] Mistake 2: Extra whitespace")
result = decode_api_key_from_transport(f" {encoded} ")
print(f"   Decode result: {result if result else 'FAILED'}")

print("\n[X] Mistake 3: Incomplete key (missing last char)")
result = decode_api_key_from_transport(encoded[:-1])
print(f"   Decode result: {result if result else 'FAILED'}")

print("\n[X] Mistake 4: Adding 'Bearer ' prefix to the token value")
result = decode_api_key_from_transport(f"Bearer {encoded}")
print(f"   Decode result: {result if result else 'FAILED'}")

print("\n" + "=" * 80)
print("CORRECT POSTMAN SETUP:")
print("=" * 80)
print("""
Step 1: Generate API key (with your JWT token)
  POST http://localhost:8000/api/v1/invoices/api-key/generate
  Authorization: Bearer <your_jwt_token>

Step 2: Copy ONLY the "api_key" value from response
  Response: { "api_key": "abc123...", ... }
  Copy: abc123...  (the full value, no quotes)

Step 3: Use in invoice upload request
  POST http://localhost:8000/api/v1/invoices/api/process
  Authorization Tab:
    - Type: Bearer Token
    - Token: <paste_the_api_key_here>
  
  Postman will automatically add "Bearer " prefix
  Final header: Authorization: Bearer abc123...

IMPORTANT:
  - Copy the ENTIRE api_key value
  - Don't add spaces, quotes, or any extra characters
  - Don't manually encode/decode anything
  - Paste exactly what the generate endpoint returns
""")
