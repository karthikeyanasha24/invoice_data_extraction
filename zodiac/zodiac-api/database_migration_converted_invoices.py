"""
Database Migration for Converted Invoices Table
Creates the converted_invoices table for storing conversion results
Run this script to create the table
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in environment variables")
    sys.exit(1)

print("=" * 80)
print("CONVERTED INVOICES TABLE MIGRATION")
print("=" * 80)
print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Unknown'}")
print()

# Create engine
engine = create_engine(DATABASE_URL)

def run_migration():
    """Run the migration"""
    print("Creating converted_invoices table...")
    print()
    
    try:
        with engine.begin() as conn:
            # Create the converted_invoices table
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS converted_invoices (
                id SERIAL PRIMARY KEY,
                validated_invoice_id INTEGER NOT NULL REFERENCES invoice_v2_validated(id) ON DELETE CASCADE,
                customer_id VARCHAR(255),
                target_format VARCHAR(32) NOT NULL,
                converted_file_path VARCHAR(1024),
                blob_converted_path VARCHAR(1024),
                conversion_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                conversion_notes TEXT,
                validation_overridden BOOLEAN DEFAULT FALSE,
                converted_at TIMESTAMP DEFAULT NOW()
            );
            """
            
            print("Executing SQL:")
            print(create_table_sql)
            print()
            
            conn.execute(text(create_table_sql))
            
            print("✅ Table created successfully!")
            print()
            
            # Create indexes for better performance
            print("Creating indexes...")
            
            index_sqls = [
                "CREATE INDEX IF NOT EXISTS idx_converted_invoices_validated_id ON converted_invoices(validated_invoice_id);",
                "CREATE INDEX IF NOT EXISTS idx_converted_invoices_customer_id ON converted_invoices(customer_id);",
                "CREATE INDEX IF NOT EXISTS idx_converted_invoices_status ON converted_invoices(conversion_status);",
                "CREATE INDEX IF NOT EXISTS idx_converted_invoices_date ON converted_invoices(converted_at DESC);"
            ]
            
            for idx_sql in index_sqls:
                conn.execute(text(idx_sql))
                print(f"✅ {idx_sql}")
            
            print()
        
        print("=" * 80)
        print("MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Summary:")
        print("  • converted_invoices table created")
        print("  • Foreign key to invoice_v2_validated created")
        print("  • Performance indexes created")
        print()
        
        # Verify table structure
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name, data_type, column_default, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'converted_invoices'
                ORDER BY ordinal_position;
            """))
            
            print("Table structure:")
            print("-" * 80)
            for row in result:
                print(f"  {row[0]:30} {row[1]:20} Default: {str(row[2] or 'None'):20} Nullable: {row[3]}")
        
        print()
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("MIGRATION FAILED!")
        print("=" * 80)
        print(f"Error: {e}")
        print()
        
        # Check if invoice_v2_validated table exists
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'invoice_v2_validated'
                    );
                """))
                exists = result.scalar()
                
                if not exists:
                    print("⚠️  WARNING: The 'invoice_v2_validated' table does not exist!")
                    print("   You need to create this table first before running this migration.")
                    print()
        except:
            pass
        
        print("To rollback (if table was partially created):")
        print("  DROP TABLE IF EXISTS converted_invoices CASCADE;")
        print()
        return False

def check_prerequisites():
    """Check if required tables exist"""
    try:
        with engine.connect() as conn:
            # Check if invoice_v2_validated exists
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'invoice_v2_validated'
                );
            """))
            validated_exists = result.scalar()
            
            # Check if converted_invoices already exists
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'converted_invoices'
                );
            """))
            converted_exists = result.scalar()
            
            print("Pre-migration check:")
            print("-" * 80)
            print(f"  invoice_v2_validated table: {'✅ EXISTS' if validated_exists else '❌ NOT FOUND'}")
            print(f"  converted_invoices table: {'⚠️  ALREADY EXISTS' if converted_exists else '✅ NOT EXISTS (will create)'}")
            print()
            
            if not validated_exists:
                print("❌ ERROR: Required table 'invoice_v2_validated' does not exist!")
                print("   Please ensure the Invoices V2 system is properly set up before running this migration.")
                print()
                return False
            
            if converted_exists:
                print("⚠️  WARNING: The 'converted_invoices' table already exists!")
                print()
                response = input("Do you want to drop and recreate it? (yes/no): ")
                if response.lower() in ['yes', 'y']:
                    with engine.begin() as conn:
                        conn.execute(text("DROP TABLE IF EXISTS converted_invoices CASCADE;"))
                        print("✅ Existing table dropped.")
                        print()
                    return True
                else:
                    print("Migration cancelled.")
                    return False
            
            return True
            
    except Exception as e:
        print(f"Error checking prerequisites: {e}")
        return False

if __name__ == "__main__":
    print()
    if check_prerequisites():
        success = run_migration()
        sys.exit(0 if success else 1)
    else:
        sys.exit(1)
