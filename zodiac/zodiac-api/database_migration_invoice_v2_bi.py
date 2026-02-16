"""
Migration script to create invoice_v2_business_data table for BI and analytics
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text, inspect
from app.database import engine, Base
from app.models.invoice_v2_business_data import InvoiceV2BusinessData

def check_table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def create_invoice_v2_bi_table():
    """Create the invoice_v2_business_data table with indexes"""
    
    print("=" * 60)
    print("Invoice V2 Business Intelligence Table Migration")
    print("=" * 60)
    
    # Check if table already exists
    if check_table_exists("invoice_v2_business_data"):
        print("\n⚠️  Table 'invoice_v2_business_data' already exists.")
        response = input("Do you want to recreate it? This will DROP all existing data! (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Migration cancelled.")
            return
        
        # Drop existing table
        print("\n🗑️  Dropping existing table...")
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS invoice_v2_business_data CASCADE"))
            conn.commit()
        print("✅ Table dropped.")
    
    # Create the table
    print("\n📋 Creating invoice_v2_business_data table...")
    
    try:
        # Use SQLAlchemy to create the table
        InvoiceV2BusinessData.__table__.create(engine, checkfirst=True)
        print("✅ Table created successfully using SQLAlchemy ORM")
        
        # Add additional indexes for performance
        print("\n📊 Creating additional indexes...")
        with engine.connect() as conn:
            # GIN index for JSONB products column (for fast JSON queries)
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_v2_bi_products 
                    ON invoice_v2_business_data USING GIN(products)
                """))
                print("  ✅ GIN index on products column created")
            except Exception as e:
                print(f"  ⚠️  Could not create GIN index on products: {e}")
            
            # Composite indexes for common queries
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_v2_bi_user_date 
                    ON invoice_v2_business_data(user_id, invoice_date DESC)
                """))
                print("  ✅ Composite index (user_id, invoice_date) created")
            except Exception as e:
                print(f"  ⚠️  Composite index creation failed: {e}")
            
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_v2_bi_industry_stage 
                    ON invoice_v2_business_data(industry, current_stage)
                """))
                print("  ✅ Composite index (industry, current_stage) created")
            except Exception as e:
                print(f"  ⚠️  Composite index creation failed: {e}")
            
            conn.commit()
        
        print("\n✅ All indexes created successfully!")
        
        # Verify table structure
        print("\n🔍 Verifying table structure...")
        inspector = inspect(engine)
        columns = inspector.get_columns("invoice_v2_business_data")
        indexes = inspector.get_indexes("invoice_v2_business_data")
        
        print(f"\n📋 Table Columns ({len(columns)}):")
        for col in columns:
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            print(f"  • {col['name']}: {col['type']} ({nullable})")
        
        print(f"\n📊 Table Indexes ({len(indexes)}):")
        for idx in indexes:
            cols = ', '.join(idx['column_names'])
            unique = "UNIQUE" if idx.get('unique') else ""
            print(f"  • {idx['name']}: ({cols}) {unique}")
        
        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60)
        print("\n💡 Next steps:")
        print("  1. Use the backfill endpoint to populate data from existing invoices")
        print("  2. BI data will be automatically created for new validated invoices")
        print("  3. Dashboard analytics can now query this table for insights")
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    create_invoice_v2_bi_table()
