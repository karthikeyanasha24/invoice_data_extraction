#!/usr/bin/env python3
"""
Simple database migration script to add deleted_at columns.
Uses the same database connection as the main app.
"""

import sys
import os
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import engine

def run_migration():
    """Run the database migration to add deleted_at columns"""
    
    print("Zodiac Database Migration: Add Soft Deletion Support")
    print("=" * 60)
    
    try:
        # Test connection
        with engine.connect() as conn:
            print("Database connection successful")
            
            # Migration SQL
            migration_sql = """
            -- Add deleted_at columns to invoice tables for soft deletion functionality
            
            -- Add deleted_at column to successful invoices table
            ALTER TABLE zodiac_invoice_success_edi 
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE NULL;
            
            -- Add deleted_at column to failed invoices table  
            ALTER TABLE zodiac_invoice_failed_edi 
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE NULL;
            
            -- Create indexes for better performance on soft deletion queries
            CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_deleted_at 
            ON zodiac_invoice_success_edi(deleted_at);
            
            CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_deleted_at 
            ON zodiac_invoice_failed_edi(deleted_at);
            
            -- Create composite indexes for user_id + deleted_at queries
            CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_user_deleted 
            ON zodiac_invoice_success_edi(user_id, deleted_at);
            
            CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_user_deleted 
            ON zodiac_invoice_failed_edi(user_id, deleted_at);
            """
            
            print("Running migration...")
            
            # Execute migration
            conn.execute(text(migration_sql))
            conn.commit()
            
            print("Migration completed successfully!")
            
            # Verify the columns were added
            verification_sql = """
            SELECT table_name, column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name IN ('zodiac_invoice_success_edi', 'zodiac_invoice_failed_edi') 
            AND column_name = 'deleted_at'
            ORDER BY table_name;
            """
            
            result = conn.execute(text(verification_sql))
            columns = result.fetchall()
            
            print("\nVerification - Added columns:")
            for row in columns:
                print(f"  {row[0]}.{row[1]} ({row[2]}, nullable: {row[3]})")
            
            if len(columns) == 2:
                print("\nMigration completed successfully! Soft deletion is now enabled.")
            else:
                print(f"\nExpected 2 columns, found {len(columns)}. Please check the migration.")
                
    except Exception as e:
        print(f"Migration error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()



