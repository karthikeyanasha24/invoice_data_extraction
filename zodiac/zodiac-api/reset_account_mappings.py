"""
Reset Account Mappings
Cleans up all supplier account mappings for fresh testing.
Use this to test Excel upload feature.
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
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_account_mappings():
    """Delete all supplier account mappings"""
    
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
        logger.info("=" * 60)
        logger.info("🧹 RESET SUPPLIER ACCOUNT MAPPINGS")
        logger.info("=" * 60)
        
        # Count records before deletion
        logger.info("\n📊 Counting existing records...")
        result = session.execute(text("SELECT COUNT(*) FROM sat_supplier_account_mapping"))
        count_before = result.scalar()
        logger.info(f"   Supplier Mappings: {count_before}")
        
        if count_before == 0:
            logger.info("\n✅ No mappings to delete. Table is already empty!")
            return
        
        # Ask for confirmation
        logger.info("\n⚠️  WARNING: This will delete:")
        logger.info(f"   - {count_before} supplier account mapping(s)")
        logger.info("\n💡 TIP: This is useful for testing Excel upload feature.")
        
        response = input("\n❓ Are you sure you want to continue? (yes/no): ")
        
        if response.lower() not in ['yes', 'y']:
            logger.info("❌ Operation cancelled by user")
            return
        
        logger.info("\n🔄 Starting cleanup...")
        
        # Delete all mappings
        logger.info("   Deleting supplier account mappings...")
        session.execute(text("DELETE FROM sat_supplier_account_mapping"))
        logger.info(f"   ✅ Deleted {count_before} mapping(s)")
        
        # Commit the changes
        session.commit()
        
        # Verify deletion
        logger.info("\n📊 Verifying cleanup...")
        result = session.execute(text("SELECT COUNT(*) FROM sat_supplier_account_mapping"))
        count_after = result.scalar()
        logger.info(f"   Supplier Mappings: {count_after}")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("✅ CLEANUP COMPLETE!")
        logger.info("=" * 60)
        logger.info(f"   Deleted: {count_before} supplier account mapping(s)")
        logger.info(f"   Remaining: {count_after} mapping(s)")
        logger.info("=" * 60)
        logger.info("\n🚀 Ready for fresh Excel upload testing!")
        logger.info("\n📋 NEXT STEPS:")
        logger.info("   1. Go to: http://localhost:3000/admin/account-mapping")
        logger.info("   2. Upload your Excel file with supplier mappings")
        logger.info("   3. Verify mappings appear in the table")
        logger.info("   4. Test Simple Merge with the new mappings")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    reset_account_mappings()
