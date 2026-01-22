"""
Script to create the sat_simple_merged table in the database.
Run this before using the Simple Merge feature.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def create_sat_simple_merged_table():
    """Create the sat_simple_merged table and its indexes."""
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    
    if not database_url:
        print("❌ Error: DATABASE_URL not found in environment variables.")
        print("Please set DATABASE_URL in your .env file.")
        sys.exit(1)
    
    # Convert asyncpg URL to psycopg2 URL if needed
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    print(f"📊 Connecting to database...")
    print(f"Database URL: {database_url[:30]}...")
    
    try:
        # Create engine
        engine = create_engine(database_url)
        
        # SQL to create table
        create_table_sql = """
        -- Create sat_simple_merged table for storing merged SAT documents
        CREATE TABLE IF NOT EXISTS sat_simple_merged (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id INTEGER NOT NULL REFERENCES zodiac_users(id) ON DELETE CASCADE,
            vendor_rfc VARCHAR(13) NOT NULL,
            vendor_name VARCHAR(255),
            fiscal_year INTEGER NOT NULL,
            fiscal_period INTEGER NOT NULL,
            document_count INTEGER NOT NULL DEFAULT 0,
            document_types JSON,
            cfdi_uuids JSON,
            total_amount NUMERIC(15, 2),
            currency VARCHAR(3) DEFAULT 'MXN',
            merged_xml_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # SQL to create indexes
        create_indexes_sql = """
        -- Create indexes for better query performance
        CREATE INDEX IF NOT EXISTS idx_sat_simple_merged_user_id ON sat_simple_merged(user_id);
        CREATE INDEX IF NOT EXISTS idx_sat_simple_merged_vendor_rfc ON sat_simple_merged(vendor_rfc);
        CREATE INDEX IF NOT EXISTS idx_sat_simple_merged_fiscal_year ON sat_simple_merged(fiscal_year);
        CREATE INDEX IF NOT EXISTS idx_sat_simple_merged_fiscal_period ON sat_simple_merged(fiscal_period);
        
        -- Create a composite index for common queries
        CREATE INDEX IF NOT EXISTS idx_sat_simple_merged_lookup 
        ON sat_simple_merged(user_id, vendor_rfc, fiscal_year, fiscal_period);
        """
        
        # Execute SQL
        with engine.connect() as connection:
            # Start transaction
            trans = connection.begin()
            
            try:
                print("\n📝 Creating sat_simple_merged table...")
                connection.execute(text(create_table_sql))
                print("✅ Table created successfully!")
                
                print("\n📝 Creating indexes...")
                connection.execute(text(create_indexes_sql))
                print("✅ Indexes created successfully!")
                
                # Commit transaction
                trans.commit()
                print("\n✅ All database changes committed successfully!")
                
                # Verify table exists
                print("\n🔍 Verifying table exists...")
                result = connection.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'sat_simple_merged'
                """))
                
                if result.fetchone():
                    print("✅ Table 'sat_simple_merged' verified in database!")
                    
                    # Count existing records
                    count_result = connection.execute(text("SELECT COUNT(*) FROM sat_simple_merged"))
                    count = count_result.scalar()
                    print(f"📊 Current records in table: {count}")
                else:
                    print("⚠️  Warning: Could not verify table creation.")
                
                print("\n🎉 Setup complete! You can now use the Simple Merge feature.")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Error during table creation: {e}")
                raise
                
    except Exception as e:
        print(f"\n❌ Error connecting to database: {e}")
        print("\nPlease check:")
        print("1. DATABASE_URL is correct in your .env file")
        print("2. Database server is running")
        print("3. You have permission to create tables")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("  SAT Simple Merged Table Creation Script")
    print("=" * 60)
    create_sat_simple_merged_table()

