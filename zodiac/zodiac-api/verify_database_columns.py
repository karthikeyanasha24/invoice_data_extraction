"""
Verify Database Columns
Checks if the sat_supplier_account_mapping table has all required columns.
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

def verify_database_columns():
    """Verify that all required columns exist in the database"""
    
    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")
    
    logger.info("=" * 70)
    logger.info("🔍 DATABASE VERIFICATION")
    logger.info("=" * 70)
    
    # Show which database we're connecting to
    # Mask password for security
    display_url = DATABASE_URL
    if '@' in display_url:
        parts = display_url.split('@')
        user_pass = parts[0].split('//')[-1]
        if ':' in user_pass:
            user = user_pass.split(':')[0]
            display_url = display_url.replace(user_pass, f"{user}:****")
    
    logger.info(f"\n📊 Connecting to database:")
    logger.info(f"   {display_url}")
    
    # Convert asyncpg URL to psycopg2 URL for synchronous SQLAlchemy
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        table_name = 'sat_supplier_account_mapping'
        
        # Check if table exists
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            logger.error(f"\n❌ Table '{table_name}' does NOT exist!")
            logger.error("   You may be connected to the wrong database.")
            return False
        
        logger.info(f"\n✅ Table '{table_name}' exists")
        
        # Get all columns
        columns = inspector.get_columns(table_name)
        column_names = [col['name'] for col in columns]
        
        logger.info(f"\n📋 Current columns ({len(column_names)} total):")
        for col in columns:
            col_type = str(col['type'])
            logger.info(f"   - {col['name']:<25} {col_type}")
        
        # Required columns
        required_columns = {
            'id': 'Required',
            'supplier_rfc': 'Required',
            'sap_gl_account': 'Required',
            'account_description': 'Optional',
            'company_code': 'NEW - Required',
            'fiscal_year': 'NEW - Required',
            'currency': 'NEW - Required',
            'opening_balance': 'NEW - Required',
            'credit_amount': 'NEW - Required',
            'debit_amount': 'NEW - Required',
            'closing_balance': 'NEW - Required',
            'is_active': 'Required',
            'is_default': 'Required',
            'created_at': 'Required',
            'updated_at': 'Required'
        }
        
        logger.info(f"\n🔍 Checking required columns:")
        missing_columns = []
        present_columns = []
        
        for col_name, description in required_columns.items():
            exists = col_name in column_names
            status = "✅" if exists else "❌"
            
            if exists:
                present_columns.append(col_name)
                logger.info(f"   {status} {col_name:<25} {description} - EXISTS")
            else:
                missing_columns.append(col_name)
                logger.error(f"   {status} {col_name:<25} {description} - MISSING!")
        
        # Summary
        logger.info("\n" + "=" * 70)
        if missing_columns:
            logger.error("❌ VERIFICATION FAILED!")
            logger.error("=" * 70)
            logger.error(f"   Present: {len(present_columns)}/{len(required_columns)} columns")
            logger.error(f"   Missing: {len(missing_columns)} columns")
            logger.error("\n   Missing columns:")
            for col in missing_columns:
                logger.error(f"      - {col}")
            logger.error("\n💡 SOLUTION:")
            logger.error("   Run the migration script:")
            logger.error("   python migrate_add_mapping_fields.py")
            return False
        else:
            logger.info("✅ VERIFICATION PASSED!")
            logger.info("=" * 70)
            logger.info(f"   All {len(required_columns)} required columns exist!")
            logger.info("\n🚀 Database is ready to use!")
            return True
        
    except Exception as e:
        logger.error(f"\n❌ Verification failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

if __name__ == "__main__":
    try:
        success = verify_database_columns()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Verification cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Verification failed with error: {e}")
        sys.exit(1)
