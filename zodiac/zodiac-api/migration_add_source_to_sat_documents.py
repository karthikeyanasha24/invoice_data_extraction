"""
Database Migration: Add source column to sat_documents
Tracks whether document came from supplier API or admin upload.
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
    """Add source column to sat_documents table"""
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
            logger.info("=" * 80)
            logger.info("🔄 MIGRATION: Add source column to sat_documents")
            logger.info("=" * 80)
            
            # Check if column already exists
            check_sql = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'sat_documents' 
                AND column_name = 'source'
            """)
            result = conn.execute(check_sql)
            exists = result.fetchone()
            
            if exists:
                logger.info("✅ Column 'source' already exists. Skipping.")
                return
            
            logger.info("📝 Adding 'source' column...")
            
            # Add source column
            add_column_sql = text("""
                ALTER TABLE sat_documents 
                ADD COLUMN source VARCHAR(20) DEFAULT 'admin'
            """)
            conn.execute(add_column_sql)
            
            # Create index for filtering
            create_index_sql = text("""
                CREATE INDEX IF NOT EXISTS idx_sat_documents_source 
                ON sat_documents(source)
            """)
            conn.execute(create_index_sql)
            
            conn.commit()
            
            logger.info("✅ Column added successfully")
            logger.info("=" * 80)
            logger.info("✅ MIGRATION COMPLETE!")
            logger.info("=" * 80)
            logger.info("   Added column: source (VARCHAR 20, default: 'admin')")
            logger.info("   Created index: idx_sat_documents_source")
            logger.info("   Values: 'admin' or 'supplier'")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    run_migration()
