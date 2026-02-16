"""
Database Migration for Invoices V2 Tables
Creates all necessary tables for the Invoices V2 system
Run this script to create the tables
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
print("INVOICES V2 TABLES MIGRATION")
print("=" * 80)
print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Unknown'}")
print()

# Create engine
engine = create_engine(DATABASE_URL)

def run_migration():
    """Run the migration"""
    print("Creating Invoices V2 tables...")
    print()
    
    try:
        with engine.begin() as conn:
            # Table 1: invoice_v2_documents
            print("1. Creating invoice_v2_documents table...")
            create_documents_sql = """
            CREATE TABLE IF NOT EXISTS invoice_v2_documents (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(512) NOT NULL,
                source VARCHAR(32) NOT NULL,
                xml_path VARCHAR(1024),
                blob_xml_path VARCHAR(1024),
                validation_status VARCHAR(32) DEFAULT 'pending',
                uploaded_at TIMESTAMP DEFAULT NOW(),
                uploaded_by INTEGER REFERENCES zodiac_users(id) ON DELETE SET NULL
            );
            """
            conn.execute(text(create_documents_sql))
            print("   ✅ invoice_v2_documents created")
            
            # Table 2: invoice_v2_validated
            print("2. Creating invoice_v2_validated table...")
            create_validated_sql = """
            CREATE TABLE IF NOT EXISTS invoice_v2_validated (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES invoice_v2_documents(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL,
                invoice_data JSONB NOT NULL,
                missing_fields TEXT[],
                validation_errors JSONB,
                validated_at TIMESTAMP DEFAULT NOW()
            );
            """
            conn.execute(text(create_validated_sql))
            print("   ✅ invoice_v2_validated created")
            
            # Table 3: invoice_v2_correction_cache
            print("3. Creating invoice_v2_correction_cache table...")
            create_cache_sql = """
            CREATE TABLE IF NOT EXISTS invoice_v2_correction_cache (
                id SERIAL PRIMARY KEY,
                customer_id VARCHAR(255) NOT NULL,
                field_name VARCHAR(255) NOT NULL,
                corrected_value TEXT NOT NULL,
                correction_count INTEGER DEFAULT 1,
                last_used_at TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(customer_id, field_name)
            );
            """
            conn.execute(text(create_cache_sql))
            print("   ✅ invoice_v2_correction_cache created")
            
            print()
            print("Creating indexes...")
            
            # Indexes for invoice_v2_documents
            index_sqls = [
                "CREATE INDEX IF NOT EXISTS idx_v2_docs_source ON invoice_v2_documents(source);",
                "CREATE INDEX IF NOT EXISTS idx_v2_docs_status ON invoice_v2_documents(validation_status);",
                "CREATE INDEX IF NOT EXISTS idx_v2_docs_uploaded ON invoice_v2_documents(uploaded_at DESC);",
                
                # Indexes for invoice_v2_validated
                "CREATE INDEX IF NOT EXISTS idx_v2_validated_doc ON invoice_v2_validated(document_id);",
                "CREATE INDEX IF NOT EXISTS idx_v2_validated_status ON invoice_v2_validated(status);",
                "CREATE INDEX IF NOT EXISTS idx_v2_validated_date ON invoice_v2_validated(validated_at DESC);",
                "CREATE INDEX IF NOT EXISTS idx_v2_validated_data ON invoice_v2_validated USING GIN(invoice_data);",
                
                # Indexes for correction cache
                "CREATE INDEX IF NOT EXISTS idx_v2_cache_customer ON invoice_v2_correction_cache(customer_id);",
                "CREATE INDEX IF NOT EXISTS idx_v2_cache_field ON invoice_v2_correction_cache(field_name);",
                "CREATE INDEX IF NOT EXISTS idx_v2_cache_used ON invoice_v2_correction_cache(last_used_at DESC);"
            ]
            
            for idx_sql in index_sqls:
                conn.execute(text(idx_sql))
            print("   ✅ All indexes created")
            
            print()
        
        print("=" * 80)
        print("MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Summary:")
        print("  • invoice_v2_documents table created")
        print("  • invoice_v2_validated table created")
        print("  • invoice_v2_correction_cache table created")
        print("  • All indexes created")
        print()
        
        # Verify tables
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name LIKE 'invoice_v2%'
                ORDER BY table_name;
            """))
            
            print("Created tables:")
            print("-" * 80)
            for row in result:
                # Get column count
                col_result = conn.execute(text(f"""
                    SELECT COUNT(*) 
                    FROM information_schema.columns 
                    WHERE table_name = '{row[0]}';
                """))
                col_count = col_result.scalar()
                print(f"  ✓ {row[0]} ({col_count} columns)")
        
        print()
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("MIGRATION FAILED!")
        print("=" * 80)
        print(f"Error: {e}")
        print()
        print("To rollback:")
        print("  DROP TABLE IF EXISTS invoice_v2_correction_cache CASCADE;")
        print("  DROP TABLE IF EXISTS invoice_v2_validated CASCADE;")
        print("  DROP TABLE IF EXISTS invoice_v2_documents CASCADE;")
        print()
        return False

def check_prerequisites():
    """Check if tables already exist and if zodiac_users exists"""
    try:
        with engine.connect() as conn:
            # Check if zodiac_users exists (required for foreign key)
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'zodiac_users'
                );
            """))
            users_exists = result.scalar()
            
            # Check if tables already exist
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name LIKE 'invoice_v2%'
                ORDER BY table_name;
            """))
            existing_tables = [row[0] for row in result]
            
            print("Pre-migration check:")
            print("-" * 80)
            print(f"  zodiac_users table: {'✅ EXISTS' if users_exists else '⚠️  NOT FOUND (optional FK will be nullable)'}")
            print()
            
            if existing_tables:
                print("  Existing Invoices V2 tables:")
                for table in existing_tables:
                    print(f"    ⚠️  {table}")
                print()
                print("⚠️  WARNING: Some Invoices V2 tables already exist!")
                print()
                response = input("Do you want to drop and recreate them? (yes/no): ")
                if response.lower() in ['yes', 'y']:
                    with engine.begin() as conn:
                        conn.execute(text("DROP TABLE IF EXISTS invoice_v2_correction_cache CASCADE;"))
                        conn.execute(text("DROP TABLE IF EXISTS invoice_v2_validated CASCADE;"))
                        conn.execute(text("DROP TABLE IF EXISTS invoice_v2_documents CASCADE;"))
                        print("✅ Existing tables dropped.")
                        print()
                    return True
                else:
                    print("Migration cancelled.")
                    return False
            else:
                print("  ✅ No existing Invoices V2 tables found (will create)")
                print()
            
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
