"""
Database Migration: Add Performance Indexes
This migration adds indexes to improve query performance for the invoices page.
"""

import os
import sys
from sqlalchemy import create_engine, text

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import get_db_url

def run_migration():
    """Add indexes for better query performance"""
    
    engine = create_engine(get_db_url())
    
    print("=" * 80)
    print("Adding Performance Indexes for Invoices")
    print("=" * 80)
    
    with engine.connect() as conn:
        # Start transaction
        trans = conn.begin()
        
        try:
            # Add index on user_id + deleted_at + uploaded_at for success table
            print("\n1. Adding composite index on zodiac_invoice_success_edi...")
            print("   Columns: (user_id, deleted_at, uploaded_at DESC)")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_success_user_deleted_uploaded 
                ON zodiac_invoice_success_edi(user_id, deleted_at, uploaded_at DESC)
            """))
            print("   ✓ Success table index created")
            
            # Add index on user_id + deleted_at + uploaded_at for failed table
            print("\n2. Adding composite index on zodiac_invoice_failed_edi...")
            print("   Columns: (user_id, deleted_at, uploaded_at DESC)")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_failed_user_deleted_uploaded 
                ON zodiac_invoice_failed_edi(user_id, deleted_at, uploaded_at DESC)
            """))
            print("   ✓ Failed table index created")
            
            # Add index for deleted invoices query
            print("\n3. Adding index for deleted invoices query...")
            print("   Columns: (user_id, deleted_at DESC) where deleted_at IS NOT NULL")
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
            print("   ✓ Deleted invoices indexes created")
            
            # Add index on uploaded_at for sorting
            print("\n4. Adding index on uploaded_at for sorting...")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_success_uploaded_at 
                ON zodiac_invoice_success_edi(uploaded_at DESC)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_failed_uploaded_at 
                ON zodiac_invoice_failed_edi(uploaded_at DESC)
            """))
            print("   ✓ Upload date indexes created")
            
            # Commit transaction
            trans.commit()
            
            print("\n" + "=" * 80)
            print("✓ All indexes created successfully!")
            print("=" * 80)
            print("\nBenefits:")
            print("  - Faster filtering by user and deleted status")
            print("  - Improved sorting by upload date")
            print("  - Better performance for deleted invoices queries")
            print("  - Reduced query execution time for large datasets")
            
            # Show index information
            print("\n" + "=" * 80)
            print("Verifying Indexes")
            print("=" * 80)
            
            result = conn.execute(text("""
                SELECT schemaname, tablename, indexname, indexdef
                FROM pg_indexes
                WHERE tablename IN ('zodiac_invoice_success_edi', 'zodiac_invoice_failed_edi')
                AND indexname LIKE 'idx_%'
                ORDER BY tablename, indexname
            """))
            
            print("\nCreated indexes:")
            for row in result:
                print(f"\n  Table: {row.tablename}")
                print(f"  Index: {row.indexname}")
                print(f"  Definition: {row.indexdef}")
            
            return True
            
        except Exception as e:
            trans.rollback()
            print(f"\n❌ Error creating indexes: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    try:
        success = run_migration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
