"""
Check if invoice ID 30 exists in v2_validated_invoices
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

print("=" * 80)
print("CHECKING INVOICE ID 30")
print("=" * 80)
print()

with engine.connect() as conn:
    # Check v2_validated_invoices
    result = conn.execute(text("""
        SELECT id, status, invoice_data->>'invoice_number' as invoice_number,
               invoice_data->>'customer_id' as customer_id
        FROM v2_validated_invoices 
        WHERE id = 30;
    """))
    
    row = result.fetchone()
    
    if row:
        print("✅ FOUND Invoice ID 30 in v2_validated_invoices!")
        print(f"   ID: {row[0]}")
        print(f"   Status: {row[1]}")
        print(f"   Invoice Number: {row[2]}")
        print(f"   Customer ID: {row[3]}")
    else:
        print("❌ Invoice ID 30 NOT found in v2_validated_invoices")
        print()
        print("Let's see what IDs are available:")
        result = conn.execute(text("""
            SELECT id, status, invoice_data->>'invoice_number' as invoice_number
            FROM v2_validated_invoices 
            WHERE status = 'success'
            ORDER BY id DESC
            LIMIT 10;
        """))
        
        print("-" * 80)
        for row in result:
            print(f"   ID: {row[0]}, Status: {row[1]}, Invoice#: {row[2]}")

print()
print("=" * 80)
