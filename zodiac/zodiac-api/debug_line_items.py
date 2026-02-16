"""
Debug script to check how line_items are stored and updated
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
from app.config.config import DATABASE_URL

engine = create_engine(DATABASE_URL)

print("=" * 60)
print("Checking Line Items Storage")
print("=" * 60)

with engine.connect() as conn:
    # Check a sample invoice's line_items
    result = conn.execute(text("""
        SELECT id, invoice_number, invoice_data
        FROM invoice_v2_validated
        WHERE invoice_data::jsonb ? 'line_items'
        ORDER BY id DESC
        LIMIT 1
    """)).fetchone()
    
    if result:
        invoice_id, invoice_number, invoice_data = result
        print(f"\nFound invoice:")
        print(f"   ID: {invoice_id}")
        print(f"   Number: {invoice_number}")
        print(f"\nLine Items Data:")
        
        if 'line_items' in invoice_data:
            line_items = invoice_data['line_items']
            print(f"   Type: {type(line_items)}")
            print(f"   Count: {len(line_items) if isinstance(line_items, list) else 'N/A'}")
            
            if isinstance(line_items, list) and len(line_items) > 0:
                print(f"\n   First item:")
                first_item = line_items[0]
                for key, value in first_item.items():
                    print(f"      {key}: {value} (type: {type(value).__name__})")
        else:
            print("   WARNING: No line_items found in invoice_data")
    else:
        print("\nWARNING: No invoices with line_items found")

print("\n" + "=" * 60)
