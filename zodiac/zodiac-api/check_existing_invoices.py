"""
Check where the existing invoices are stored
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

print("=" * 80)
print("CHECKING EXISTING INVOICE DATA")
print("=" * 80)
print()

with engine.connect() as conn:
    # Check invoice_v2_validated table
    print("1. Checking invoice_v2_validated table:")
    print("-" * 80)
    result = conn.execute(text("SELECT COUNT(*) FROM invoice_v2_validated;"))
    count = result.scalar()
    print(f"   Records: {count}")
    
    if count > 0:
        result = conn.execute(text("SELECT id, status FROM invoice_v2_validated LIMIT 5;"))
        print("   Sample records:")
        for row in result:
            print(f"     ID: {row[0]}, Status: {row[1]}")
    print()
    
    # Check invoice_v2_documents table
    print("2. Checking invoice_v2_documents table:")
    print("-" * 80)
    result = conn.execute(text("SELECT COUNT(*) FROM invoice_v2_documents;"))
    count = result.scalar()
    print(f"   Records: {count}")
    
    if count > 0:
        result = conn.execute(text("SELECT id, filename, source, validation_status FROM invoice_v2_documents LIMIT 5;"))
        print("   Sample records:")
        for row in result:
            print(f"     ID: {row[0]}, File: {row[1]}, Source: {row[2]}, Status: {row[3]}")
    print()
    
    # Check for other invoice tables
    print("3. Checking for other invoice tables:")
    print("-" * 80)
    result = conn.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name LIKE '%invoice%' 
        AND table_name NOT LIKE 'invoice_v2%'
        ORDER BY table_name;
    """))
    
    other_tables = [row[0] for row in result]
    if other_tables:
        for table in other_tables:
            try:
                count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table};"))
                count = count_result.scalar()
                print(f"   ✓ {table}: {count} records")
                
                # Show structure
                col_result = conn.execute(text(f"""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = '{table}'
                    ORDER BY ordinal_position
                    LIMIT 10;
                """))
                print(f"     Columns: {', '.join([row[0] for row in col_result])}")
                print()
            except Exception as e:
                print(f"   ✗ {table}: Error - {e}")
    else:
        print("   No other invoice tables found")
    
    print()
    print("4. Searching for invoice ID 30:")
    print("-" * 80)
    
    # Try to find where ID 30 is
    for table in ['invoice_v2_validated', 'invoice_v2_documents'] + other_tables:
        try:
            result = conn.execute(text(f"SELECT * FROM {table} WHERE id = 30;"))
            row = result.fetchone()
            if row:
                print(f"   ✓ FOUND in {table}!")
                print(f"     Data: {dict(row._mapping)}")
                break
        except:
            pass
    else:
        print("   ✗ Invoice ID 30 not found in any table")

print()
print("=" * 80)
