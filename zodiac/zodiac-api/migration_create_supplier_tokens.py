"""
Database Migration: Create Supplier Tokens Table
Creates table for storing supplier API tokens for CFDI document submission.
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
    """Create supplier_tokens table"""
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
            logger.info("🔄 MIGRATION: Create Supplier Tokens Table")
            logger.info("=" * 80)
            
            # Check if table already exists
            check_sql = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'supplier_tokens'
                );
            """)
            result = conn.execute(check_sql)
            table_exists = result.scalar()
            
            if table_exists:
                logger.info("✅ Table 'supplier_tokens' already exists. Skipping creation.")
                return
            
            logger.info("📝 Creating supplier_tokens table...")
            
            # Create table
            create_table_sql = text("""
                CREATE TABLE supplier_tokens (
                    id SERIAL PRIMARY KEY,
                    supplier_rfc VARCHAR(13) UNIQUE NOT NULL,
                    supplier_name VARCHAR(255),
                    token VARCHAR(255) UNIQUE NOT NULL,
                    token_hash VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    created_by INTEGER REFERENCES zodiac_users(id),
                    ip_whitelist JSON,
                    notes TEXT
                );
            """)
            conn.execute(create_table_sql)
            logger.info("✅ Table created successfully")
            
            # Create indexes
            logger.info("📝 Creating indexes...")
            create_indexes_sql = text("""
                CREATE INDEX idx_supplier_token ON supplier_tokens(token);
                CREATE INDEX idx_supplier_rfc ON supplier_tokens(supplier_rfc);
                CREATE INDEX idx_supplier_token_active ON supplier_tokens(is_active, supplier_rfc);
                CREATE INDEX idx_supplier_token_expires ON supplier_tokens(expires_at);
            """)
            conn.execute(create_indexes_sql)
            logger.info("✅ Indexes created successfully")
            
            conn.commit()
            
            logger.info("=" * 80)
            logger.info("✅ MIGRATION COMPLETE!")
            logger.info("=" * 80)
            logger.info("   Created table: supplier_tokens")
            logger.info("   Created 4 indexes")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    run_migration()
