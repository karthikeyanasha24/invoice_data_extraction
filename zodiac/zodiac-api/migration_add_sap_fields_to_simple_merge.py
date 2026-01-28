"""
Migration: Add SAP Integration Fields to SATSimpleMerged

This migration adds the following fields to sat_simple_merged table:
- sent_to_sap: Boolean (default False)
- sap_document_number: String (50)
- sent_to_sap_at: DateTime
- sap_response: Text
"""

import asyncio
from sqlalchemy import create_engine, Column, Boolean, String, DateTime, Text, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def run_migration():
    """Add SAP integration fields to sat_simple_merged table"""
    print("=" * 80)
    print("🔄 MIGRATION: Add SAP Integration Fields to SATSimpleMerged")
    print("=" * 80)
    
    engine = create_engine(DATABASE_URL)
    
    with engine.begin() as conn:
        # Check if columns already exist
        print("\n1️⃣ Checking if columns already exist...")
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'sat_simple_merged' 
            AND column_name IN ('sent_to_sap', 'sap_document_number', 'sent_to_sap_at', 'sap_response')
        """))
        existing_columns = [row[0] for row in result]
        
        if 'sent_to_sap' in existing_columns:
            print("   ✅ Columns already exist. Skipping migration.")
            return
        
        print("   📝 Columns not found. Adding...")
        
        # Add columns
        print("\n2️⃣ Adding SAP integration columns...")
        
        try:
            conn.execute(text("""
                ALTER TABLE sat_simple_merged 
                ADD COLUMN IF NOT EXISTS sent_to_sap BOOLEAN DEFAULT FALSE NOT NULL
            """))
            print("   ✅ Added sent_to_sap column")
            
            conn.execute(text("""
                ALTER TABLE sat_simple_merged 
                ADD COLUMN IF NOT EXISTS sap_document_number VARCHAR(50)
            """))
            print("   ✅ Added sap_document_number column")
            
            conn.execute(text("""
                ALTER TABLE sat_simple_merged 
                ADD COLUMN IF NOT EXISTS sent_to_sap_at TIMESTAMP
            """))
            print("   ✅ Added sent_to_sap_at column")
            
            conn.execute(text("""
                ALTER TABLE sat_simple_merged 
                ADD COLUMN IF NOT EXISTS sap_response TEXT
            """))
            print("   ✅ Added sap_response column")
            
            print("\n✅ Migration completed successfully!")
            
        except Exception as e:
            print(f"\n❌ Error during migration: {e}")
            raise
        
    print("\n" + "=" * 80)
    print("🎉 MIGRATION COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    run_migration()

