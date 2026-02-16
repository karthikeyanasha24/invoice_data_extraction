"""
Check what invoice-related tables exist in the database
"""
import os
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found")
    exit(1)

engine = create_engine(DATABASE_URL)
inspector = inspect(engine)

print("=" * 80)
print("DATABASE TABLES CHECK")
print("=" * 80)
print()

all_tables = inspector.get_table_names()

print("All tables in database:")
print("-" * 80)
for table in sorted(all_tables):
    print(f"  • {table}")

print()
print("Invoice-related tables:")
print("-" * 80)
invoice_tables = [t for t in all_tables if 'invoice' in t.lower()]
if invoice_tables:
    for table in invoice_tables:
        print(f"  ✓ {table}")
        
        # Show columns for invoice tables
        columns = inspector.get_columns(table)
        print(f"    Columns: {len(columns)}")
        for col in columns[:5]:  # Show first 5 columns
            print(f"      - {col['name']} ({col['type']})")
        if len(columns) > 5:
            print(f"      ... and {len(columns) - 5} more")
        print()
else:
    print("  ❌ No invoice-related tables found!")

print()
print("Looking for Invoices V2 tables specifically:")
print("-" * 80)
v2_tables = ['invoice_v2_documents', 'invoice_v2_validated']
for table in v2_tables:
    exists = table in all_tables
    print(f"  {'✓' if exists else '✗'} {table}: {'EXISTS' if exists else 'NOT FOUND'}")

print()
