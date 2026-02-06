"""
Add performance indexes to invoice tables
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in environment")
    exit(1)

print("=" * 80)
print("Adding Performance Indexes")
print("=" * 80)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    trans = conn.begin()
    
    try:
        print("\n1. Adding composite index on zodiac_invoice_success_edi...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_success_user_deleted_uploaded 
            ON zodiac_invoice_success_edi(user_id, deleted_at, uploaded_at DESC)
        """))
        print("   [OK] Success table index created")
        
        print("\n2. Adding composite index on zodiac_invoice_failed_edi...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_failed_user_deleted_uploaded 
            ON zodiac_invoice_failed_edi(user_id, deleted_at, uploaded_at DESC)
        """))
        print("   [OK] Failed table index created")
        
        print("\n3. Adding index for deleted invoices...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_success_deleted 
            ON zodiac_invoice_success_edi(user_id, deleted_at DESC) 
            WHERE deleted_at IS NOT NULL
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_failed_deleted 
            ON zodiac_invoice_failed_edi(user_id, deleted_at DESC) 
            WHERE deleted_at IS NOT NULL
        """))
        print("   [OK] Deleted invoices indexes created")
        
        print("\n4. Adding index on uploaded_at...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_success_uploaded_at 
            ON zodiac_invoice_success_edi(uploaded_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_failed_uploaded_at 
            ON zodiac_invoice_failed_edi(uploaded_at DESC)
        """))
        print("   [OK] Upload date indexes created")
        
        trans.commit()
        
        print("\n" + "=" * 80)
        print("SUCCESS: All indexes created!")
        print("=" * 80)
        print("\nPerformance improvements:")
        print("  - Faster user invoice queries")
        print("  - Improved sorting by date")
        print("  - Better deleted invoice performance")
        
    except Exception as e:
        trans.rollback()
        print(f"\nERROR: {e}")
        exit(1)

print("\nDone!")
