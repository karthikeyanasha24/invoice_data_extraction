"""
Database Migration: Add GL Account Fields to Supplier Mapping
Adds new columns for company code, fiscal year, currency, and balance tracking.
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
    """Add new GL account fields to sat_supplier_account_mapping table"""
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
            logger.info("🔄 Starting migration: Add GL account fields to supplier mapping...")
            
            # Add new columns
            migrations = [
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS company_code VARCHAR(10)",
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS fiscal_year INTEGER",
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'MXN'",
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS opening_balance NUMERIC(15, 2) DEFAULT 0",
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS credit_amount NUMERIC(15, 2) DEFAULT 0",
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS debit_amount NUMERIC(15, 2) DEFAULT 0",
                "ALTER TABLE sat_supplier_account_mapping ADD COLUMN IF NOT EXISTS closing_balance NUMERIC(15, 2) DEFAULT 0"
            ]
            
            for migration_sql in migrations:
                logger.info(f"  Executing: {migration_sql}")
                conn.execute(text(migration_sql))
            
            conn.commit()
            logger.info("✅ Migration completed successfully!")
            logger.info("   Added columns:")
            logger.info("   - company_code (VARCHAR 10)")
            logger.info("   - fiscal_year (INTEGER)")
            logger.info("   - currency (VARCHAR 3, default: MXN)")
            logger.info("   - opening_balance (NUMERIC 15,2)")
            logger.info("   - credit_amount (NUMERIC 15,2)")
            logger.info("   - debit_amount (NUMERIC 15,2)")
            logger.info("   - closing_balance (NUMERIC 15,2)")
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    run_migration()

