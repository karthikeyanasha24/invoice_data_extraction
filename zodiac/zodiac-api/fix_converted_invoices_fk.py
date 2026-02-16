"""
Remove foreign key constraint from converted_invoices table
This allows it to work with invoices from any source
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

print("=" * 80)
print("REMOVE FOREIGN KEY CONSTRAINT FROM CONVERTED_INVOICES")
print("=" * 80)
print()

try:
    with engine.begin() as conn:
        print("Dropping foreign key constraint...")
        
        # Drop the constraint
        conn.execute(text("""
            ALTER TABLE converted_invoices 
            DROP CONSTRAINT IF EXISTS converted_invoices_validated_invoice_id_fkey;
        """))
        
        print("✅ Foreign key constraint removed!")
        print()
        print("The converted_invoices table can now accept any validated_invoice_id")
        print("without requiring it to exist in invoice_v2_validated table.")
        print()
        
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)

print("=" * 80)
print("DONE!")
print("=" * 80)
