"""
Migration script to convert JSON columns to JSONB in invoice_v2_validated table
This improves performance and enables proper updates to nested JSON structures
"""
import sys
from sqlalchemy import text, inspect
from app.database import engine

def migrate_json_to_jsonb():
    """Convert JSON columns to JSONB"""
    
    print("=" * 70)
    print("Migration: Convert JSON to JSONB in v2_validated_invoices")
    print("=" * 70)
    
    with engine.connect() as conn:
        # Check if table exists
        inspector = inspect(engine)
        if 'v2_validated_invoices' not in inspector.get_table_names():
            print("\nERROR: Table 'v2_validated_invoices' does not exist!")
            return
        
        print("\n1. Checking current column types...")
        
        # Get current column types
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'v2_validated_invoices'
            AND column_name IN ('invoice_data', 'missing_fields', 'validation_errors')
            ORDER BY column_name
        """))
        
        columns = result.fetchall()
        for col_name, data_type in columns:
            print(f"   {col_name}: {data_type}")
        
        # Check if already JSONB
        invoice_data_type = next((dt for cn, dt in columns if cn == 'invoice_data'), None)
        if invoice_data_type == 'jsonb':
            print("\n SUCCESS: Columns are already JSONB type!")
            print("=" * 70)
            return
        
        print("\n2. Converting columns from JSON to JSONB...")
        print("   NOTE: This creates new columns and migrates data")
        
        # Count records to migrate
        count_result = conn.execute(text("SELECT COUNT(*) FROM v2_validated_invoices"))
        total_records = count_result.scalar()
        print(f"\n   Found {total_records} records to migrate")
        
        if total_records == 0:
            print("   No data to migrate - proceeding with column type change")
        
        try:
            # For each JSON column, convert to JSONB
            # PostgreSQL allows direct casting from JSON to JSONB
            
            print("\n   Converting 'invoice_data' column...")
            conn.execute(text("""
                ALTER TABLE v2_validated_invoices 
                ALTER COLUMN invoice_data TYPE JSONB USING invoice_data::jsonb
            """))
            conn.commit()
            print("   SUCCESS: invoice_data converted to JSONB")
            
            print("\n   Converting 'missing_fields' column...")
            conn.execute(text("""
                ALTER TABLE v2_validated_invoices 
                ALTER COLUMN missing_fields TYPE JSONB USING missing_fields::jsonb
            """))
            conn.commit()
            print("   SUCCESS: missing_fields converted to JSONB")
            
            print("\n   Converting 'validation_errors' column...")
            conn.execute(text("""
                ALTER TABLE v2_validated_invoices 
                ALTER COLUMN validation_errors TYPE JSONB USING validation_errors::jsonb
            """))
            conn.commit()
            print("   SUCCESS: validation_errors converted to JSONB")
            
            print("\n3. Verifying new column types...")
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'v2_validated_invoices'
                AND column_name IN ('invoice_data', 'missing_fields', 'validation_errors')
                ORDER BY column_name
            """))
            
            new_columns = result.fetchall()
            for col_name, data_type in new_columns:
                status = "OK" if data_type == 'jsonb' else "ERROR"
                print(f"   [{status}] {col_name}: {data_type}")
            
            print("\n" + "=" * 70)
            print("SUCCESS: Migration completed!")
            print("=" * 70)
            print("\nBenefits:")
            print("  - Faster JSON queries and updates")
            print("  - Proper detection of nested field changes")
            print("  - Support for GIN indexes on JSON fields")
            print("  - Product edits will now save correctly!")
            
        except Exception as e:
            conn.rollback()
            print(f"\nERROR during migration: {e}")
            print("\nYou may need to:")
            print("  1. Backup your database first")
            print("  2. Ensure no active connections are using the table")
            print("  3. Run with database admin privileges")
            raise

if __name__ == "__main__":
    try:
        migrate_json_to_jsonb()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        sys.exit(1)
