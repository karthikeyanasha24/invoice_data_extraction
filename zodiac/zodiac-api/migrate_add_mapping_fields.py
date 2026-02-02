"""
Migration: Add New Fields to Supplier Account Mapping Table

Adds the following columns:
- company_code
- fiscal_year
- currency
- opening_balance
- credit_amount
- debit_amount
- closing_balance
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_column_exists(engine, table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def migrate_add_mapping_fields():
    """Add new fields to sat_supplier_account_mapping table"""
    
    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")
    
    # Convert asyncpg URL to psycopg2 URL for synchronous SQLAlchemy
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        logger.info("=" * 70)
        logger.info("📊 MIGRATION: Add Fields to Supplier Account Mapping Table")
        logger.info("=" * 70)
        
        table_name = 'sat_supplier_account_mapping'
        
        # Check if table exists
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            logger.error(f"❌ Table '{table_name}' does not exist!")
            return
        
        logger.info(f"\n✅ Table '{table_name}' exists")
        
        # Columns to add
        columns_to_add = {
            'company_code': 'VARCHAR(10)',
            'fiscal_year': 'INTEGER',
            'currency': 'VARCHAR(3) DEFAULT \'MXN\'',
            'opening_balance': 'NUMERIC(15,2) DEFAULT 0.0',
            'credit_amount': 'NUMERIC(15,2) DEFAULT 0.0',
            'debit_amount': 'NUMERIC(15,2) DEFAULT 0.0',
            'closing_balance': 'NUMERIC(15,2) DEFAULT 0.0'
        }
        
        logger.info("\n📋 Checking existing columns...")
        
        added_count = 0
        skipped_count = 0
        
        for column_name, column_type in columns_to_add.items():
            if check_column_exists(engine, table_name, column_name):
                logger.info(f"   ⏭️  Column '{column_name}' already exists - skipping")
                skipped_count += 1
            else:
                logger.info(f"   ➕ Adding column '{column_name}' ({column_type})...")
                
                # Add column
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                session.execute(text(sql))
                session.commit()
                
                logger.info(f"   ✅ Column '{column_name}' added successfully")
                added_count += 1
        
        # Verify all columns exist now
        logger.info("\n📊 Verifying all columns...")
        all_exist = True
        for column_name in columns_to_add.keys():
            exists = check_column_exists(engine, table_name, column_name)
            status = "✅" if exists else "❌"
            logger.info(f"   {status} {column_name}: {'EXISTS' if exists else 'MISSING'}")
            if not exists:
                all_exist = False
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("✅ MIGRATION COMPLETE!")
        logger.info("=" * 70)
        logger.info(f"   Added: {added_count} column(s)")
        logger.info(f"   Skipped: {skipped_count} column(s) (already existed)")
        logger.info(f"   Status: {'✅ ALL COLUMNS EXIST' if all_exist else '⚠️ SOME COLUMNS MISSING'}")
        logger.info("=" * 70)
        
        if all_exist:
            logger.info("\n🚀 Ready to use new mapping fields!")
            logger.info("   You can now:")
            logger.info("   1. Upload Excel/CSV with new columns")
            logger.info("   2. Use mapping data in Simple Merge")
            logger.info("   3. Fields appear in SAP JSON output")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    try:
        migrate_add_mapping_fields()
    except KeyboardInterrupt:
        logger.info("\n⚠️ Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Migration failed with error: {e}")
        sys.exit(1)
