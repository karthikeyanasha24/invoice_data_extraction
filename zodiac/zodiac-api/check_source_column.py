"""
Script to check the source column configuration in the database.
This verifies if the DEFAULT constraint has been removed.

Usage:
    python check_source_column.py
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

def check_source_column():
    """Check source column configuration"""
    
    print("=" * 80)
    print("CHECKING SOURCE COLUMN CONFIGURATION")
    print("=" * 80)
    print()
    
    # Get database URL
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set!")
        return
    
    # Convert asyncpg to psycopg2 if needed
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    try:
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            print("Step 1: Checking column default constraint...")
            print()
            
            # Check if default constraint exists
            check_default_sql = text("""
                SELECT column_default 
                FROM information_schema.columns 
                WHERE table_name = 'sat_documents' 
                  AND column_name = 'source'
            """)
            result = conn.execute(check_default_sql)
            default_value = result.fetchone()
            
            if default_value and default_value[0]:
                print(f"   PROBLEM FOUND: Default constraint exists!")
                print(f"   Current default: {default_value[0]}")
                print()
                print("   This DEFAULT is overriding your Python code!")
                print()
                print("   FIX: Run this command:")
                print("   python migration_fix_source_default.py")
                print()
                status = "FAILED"
            else:
                print("   OK: No default constraint found")
                print("   Python code controls the source value")
                print()
                status = "PASSED"
            
            print("-" * 80)
            print()
            print("Step 2: Checking column details...")
            print()
            
            # Get full column info
            column_info_sql = text("""
                SELECT 
                    column_name,
                    data_type,
                    character_maximum_length,
                    is_nullable,
                    column_default
                FROM information_schema.columns 
                WHERE table_name = 'sat_documents' 
                  AND column_name = 'source'
            """)
            result = conn.execute(column_info_sql)
            col_info = result.fetchone()
            
            if col_info:
                print(f"   Column Name: {col_info[0]}")
                print(f"   Data Type: {col_info[1]}")
                print(f"   Max Length: {col_info[2]}")
                print(f"   Nullable: {col_info[3]}")
                print(f"   Default: {col_info[4] or 'None'}")
            else:
                print("   ERROR: source column not found in database!")
                status = "FAILED"
            
            print()
            print("-" * 80)
            print()
            print("Step 3: Checking recent documents...")
            print()
            
            # Check recent documents
            recent_docs_sql = text("""
                SELECT 
                    source,
                    supplier_rfc,
                    portal_ref_id,
                    received_at
                FROM sat_documents 
                ORDER BY received_at DESC 
                LIMIT 5
            """)
            result = conn.execute(recent_docs_sql)
            docs = result.fetchall()
            
            if docs:
                print(f"   Last 5 documents:")
                print()
                for i, doc in enumerate(docs, 1):
                    print(f"   {i}. Source: {doc[0]:10s} | RFC: {doc[1]} | Time: {doc[3]}")
                print()
                
                # Count by source
                count_sql = text("""
                    SELECT source, COUNT(*) as count
                    FROM sat_documents
                    GROUP BY source
                    ORDER BY source
                """)
                result = conn.execute(count_sql)
                counts = result.fetchall()
                
                print("   Total documents by source:")
                for source, count in counts:
                    print(f"   - {source}: {count}")
            else:
                print("   No documents found in database")
            
            print()
            print("=" * 80)
            print(f"RESULT: {status}")
            print("=" * 80)
            print()
            
            if status == "PASSED":
                print("Database configuration is CORRECT!")
                print()
                print("If documents still show as 'admin', the issue is in:")
                print("  1. Your deployed code (Vercel)")
                print("  2. How the endpoint is being called")
                print()
                print("Next step: Check Vercel deployment and logs")
            else:
                print("Database configuration has ISSUES!")
                print()
                print("Run the migration script to fix:")
                print("  python migration_fix_source_default.py")
            
            print()
            
    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()
        import traceback
        traceback.print_exc()
        print()

if __name__ == "__main__":
    check_source_column()
