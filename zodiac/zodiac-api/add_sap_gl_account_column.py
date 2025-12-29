#!/usr/bin/env python3
"""
Add sap_gl_account column to sat_canonical_merged table
Run this AFTER updating the model
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")

# Modify URL for psycopg2 if it's an asyncpg URL
if DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

engine = create_engine(DATABASE_URL)

def add_column():
    """Add sap_gl_account column to sat_canonical_merged table"""
    print("=" * 70)
    print("Adding sap_gl_account column to sat_canonical_merged table")
    print("=" * 70)
    print()
    
    try:
        with engine.connect() as connection:
            # Check if column already exists
            check_sql = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'sat_canonical_merged' 
                AND column_name = 'sap_gl_account';
            """)
            
            result = connection.execute(check_sql)
            exists = result.fetchone()
            
            if exists:
                print("✅ Column 'sap_gl_account' already exists. Nothing to do.")
                return
            
            # Add the column
            print("📝 Adding column 'sap_gl_account' VARCHAR(20)...")
            add_column_sql = text("""
                ALTER TABLE sat_canonical_merged 
                ADD COLUMN sap_gl_account VARCHAR(20);
            """)
            connection.execute(add_column_sql)
            
            # Add index
            print("📝 Adding index on 'sap_gl_account'...")
            add_index_sql = text("""
                CREATE INDEX IF NOT EXISTS ix_sat_canonical_gl_account 
                ON sat_canonical_merged(sap_gl_account);
            """)
            connection.execute(add_index_sql)
            
            connection.commit()
            
            print()
            print("=" * 70)
            print("✅ Successfully added sap_gl_account column!")
            print("=" * 70)
            print()
            print("📊 Column details:")
            print("   - Name: sap_gl_account")
            print("   - Type: VARCHAR(20)")
            print("   - Nullable: Yes")
            print("   - Indexed: Yes")
            print()
            print("🔄 Next steps:")
            print("   1. Restart your backend server")
            print("   2. Re-run the merge to populate the column")
            print("   3. The preview modal should work now!")
            print()
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    add_column()

