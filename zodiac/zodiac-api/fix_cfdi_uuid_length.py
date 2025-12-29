#!/usr/bin/env python3
"""
Fix CFDI UUID column length
Changes varchar(36) to varchar(50) to accommodate TEMP- prefix
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def fix_uuid_length():
    """Alter cfdi_uuid column to allow longer values"""
    print("=" * 70)
    print("Fix CFDI UUID Column Length")
    print("=" * 70)
    print()
    
    try:
        with engine.connect() as conn:
            print("📝 Altering cfdi_uuid columns from VARCHAR(36) to VARCHAR(50)...")
            
            # Alter sat_documents table
            print("   - sat_documents.cfdi_uuid...")
            conn.execute(text("""
                ALTER TABLE sat_documents 
                ALTER COLUMN cfdi_uuid TYPE VARCHAR(50);
            """))
            
            # Alter sat_duplicate_checks table
            print("   - sat_duplicate_checks.cfdi_uuid...")
            conn.execute(text("""
                ALTER TABLE sat_duplicate_checks 
                ALTER COLUMN cfdi_uuid TYPE VARCHAR(50);
            """))
            
            conn.commit()
            
            print("✅ Columns altered successfully!")
            print()
            print("=" * 70)
            print("✅ Fix Complete!")
            print("=" * 70)
            
    except Exception as e:
        print(f"❌ Fix failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    fix_uuid_length()

