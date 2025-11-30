#!/usr/bin/env python3
"""
Database migration script to add updated_at column to zodiac_invoice_failed_edi table.
This is needed for tracking when failed invoices are reprocessed.
"""

import sys
import os
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import engine

def run_migration():
    """Run the database migration to add updated_at column"""
    
    print("Zodiac Database Migration: Add updated_at Column for Reprocessing")
    print("=" * 70)
    
    try:
        # Test connection
        with engine.connect() as conn:
            print("✅ Database connection successful")
            
            # Migration SQL
            migration_sql = """
            -- Add updated_at column to failed invoices table for tracking reprocessing
            ALTER TABLE zodiac_invoice_failed_edi 
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NULL;
            
            -- Create index for better performance on queries that filter by updated_at
            CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_updated_at 
            ON zodiac_invoice_failed_edi(updated_at);
            
            -- Create composite index for user_id + updated_at queries
            CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_user_updated 
            ON zodiac_invoice_failed_edi(user_id, updated_at);
            """
            
            print("Running migration...")
            
            # Execute migration
            conn.execute(text(migration_sql))
            conn.commit()
            
            print("✅ Migration executed successfully!")
            
            # Verify the column was added
            verification_sql = """
            SELECT table_name, column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'zodiac_invoice_failed_edi' 
            AND column_name = 'updated_at';
            """
            
            result = conn.execute(text(verification_sql))
            column = result.fetchone()
            
            if column:
                print("\n✅ Verification - Column added successfully:")
                print(f"   Table: {column[0]}")
                print(f"   Column: {column[1]}")
                print(f"   Type: {column[2]}")
                print(f"   Nullable: {column[3]}")
                print("\n✅ Migration completed successfully!")
                return True
            else:
                print("\n❌ Verification failed - Column was not added.")
                return False
                
    except Exception as e:
        print(f"❌ Migration error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
