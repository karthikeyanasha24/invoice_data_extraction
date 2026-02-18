"""
Database Migration: Remove DEFAULT constraint from source column
This fixes the issue where database default 'admin' overrides Python code's source value.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Remove DEFAULT constraint from source column in sat_documents"""
    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")
    
    # Convert asyncpg URL to psycopg2 URL for synchronous SQLAlchemy
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        try:
            print("=" * 80)
            print("MIGRATION: Remove DEFAULT Constraint from source Column")
            print("=" * 80)
            print()
            
            # Check current default
            logger.info("Step 1: Checking current column default...")
            check_sql = text("""
                SELECT column_default 
                FROM information_schema.columns 
                WHERE table_name = 'sat_documents' 
                  AND column_name = 'source'
            """)
            result = conn.execute(check_sql)
            current_default = result.fetchone()
            
            if current_default:
                print(f"   Current default: {current_default[0]}")
            else:
                print("   Column not found or no default set")
            
            print()
            
            # Remove default
            logger.info("Step 2: Removing DEFAULT constraint...")
            remove_default_sql = text("""
                ALTER TABLE sat_documents 
                ALTER COLUMN source DROP DEFAULT
            """)
            conn.execute(remove_default_sql)
            
            print("   DEFAULT constraint removed")
            print()
            
            # Verify removal
            logger.info("Step 3: Verifying removal...")
            result = conn.execute(check_sql)
            new_default = result.fetchone()
            
            if new_default and new_default[0]:
                print(f"   WARNING: Default still exists: {new_default[0]}")
            else:
                print("   Verified: No default constraint")
            
            print()
            
            conn.commit()
            
            print("=" * 80)
            print("MIGRATION COMPLETE!")
            print("=" * 80)
            print()
            print("What changed:")
            print("  - BEFORE: source column had DEFAULT 'admin' in database")
            print("  - AFTER:  source column has NO default (Python code controls it)")
            print()
            print("Result:")
            print("  - Admin uploads will set source='admin' (in Python)")
            print("  - Supplier uploads will set source='supplier' (in Python)")
            print("  - Database won't override these values anymore!")
            print()
            print("=" * 80)
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            conn.rollback()
            print()
            print(f"ERROR: {e}")
            print()
            raise

if __name__ == "__main__":
    try:
        run_migration()
        print()
        print("SUCCESS! Now redeploy your app and test again.")
        print()
    except Exception as e:
        print()
        print("FAILED! See error above.")
        print()
        sys.exit(1)
