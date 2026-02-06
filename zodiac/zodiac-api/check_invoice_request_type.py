"""
Check request_type for a specific invoice by tracking_id
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in environment")
    exit(1)

# Get tracking_id from command line
if len(sys.argv) < 2:
    print("Usage: python check_invoice_request_type.py <tracking_id>")
    print("Example: python check_invoice_request_type.py d632c4cf-9e25-43fa-a4e5-02b533f64b97")
    exit(1)

tracking_id = sys.argv[1]

print("=" * 80)
print(f"Checking invoice with tracking_id: {tracking_id}")
print("=" * 80)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Check success table
    result = conn.execute(text("""
        SELECT tracking_id, request_type, uploaded_at, user_id, target_file_format
        FROM zodiac_invoice_success_edi
        WHERE tracking_id = :tracking_id
    """), {"tracking_id": tracking_id}).fetchone()
    
    if result:
        print("\n[FOUND] Invoice in SUCCESS table:")
        print(f"  Tracking ID: {result.tracking_id}")
        print(f"  Request Type: '{result.request_type}'")
        print(f"  Uploaded At: {result.uploaded_at}")
        print(f"  User ID: {result.user_id}")
        print(f"  Target Format: {result.target_file_format}")
        
        if result.request_type == 'api':
            print("\n  ✓ Correctly marked as 'api' (from SAP)")
        elif result.request_type == 'web':
            print("\n  ✗ Incorrectly marked as 'web' (should be 'api')")
        else:
            print(f"\n  ? Unknown request_type: '{result.request_type}'")
        exit(0)
    
    # Check failed table
    result = conn.execute(text("""
        SELECT tracking_id, request_type, uploaded_at, user_id, target_file_format
        FROM zodiac_invoice_failed_edi
        WHERE tracking_id = :tracking_id
    """), {"tracking_id": tracking_id}).fetchone()
    
    if result:
        print("\n[FOUND] Invoice in FAILED table:")
        print(f"  Tracking ID: {result.tracking_id}")
        print(f"  Request Type: '{result.request_type}'")
        print(f"  Uploaded At: {result.uploaded_at}")
        print(f"  User ID: {result.user_id}")
        print(f"  Target Format: {result.target_file_format}")
        
        if result.request_type == 'api':
            print("\n  ✓ Correctly marked as 'api' (from SAP)")
        elif result.request_type == 'web':
            print("\n  ✗ Incorrectly marked as 'web' (should be 'api')")
        else:
            print(f"\n  ? Unknown request_type: '{result.request_type}'")
        exit(0)
    
    print(f"\n[NOT FOUND] No invoice found with tracking_id: {tracking_id}")
    exit(1)
