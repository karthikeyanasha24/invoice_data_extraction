"""
Reset SAT Documents and Merges
Cleans up all SAT documents, simple merges, and canonical merges for fresh testing.
Keeps supplier account mappings intact.
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

def reset_sat_data():
    """Delete all SAT documents and merges, keep supplier mappings"""
    
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
        logger.info("🧹 RESET SAT DOCUMENTS AND MERGES")
        logger.info("=" * 60)
        
        # Count records before deletion
        logger.info("\n📊 Counting existing records...")
        
        count_queries = {
            "SAT Documents": "SELECT COUNT(*) FROM sat_documents",
            "Simple Merges": "SELECT COUNT(*) FROM sat_simple_merged",
            "Canonical Merges": "SELECT COUNT(*) FROM sat_canonical_merged",
            "Supplier Mappings": "SELECT COUNT(*) FROM sat_supplier_account_mapping"
        }
        
        counts_before = {}
        for name, query in count_queries.items():
            result = session.execute(text(query))
            count = result.scalar()
            counts_before[name] = count
            logger.info(f"   {name}: {count}")
        
        # Ask for confirmation
        logger.info("\n⚠️  WARNING: This will delete:")
        logger.info(f"   - {counts_before['SAT Documents']} SAT document(s)")
        logger.info(f"   - {counts_before['Simple Merges']} simple merge(s)")
        logger.info(f"   - {counts_before['Canonical Merges']} canonical merge(s)")
        logger.info(f"\n✅ This will KEEP:")
        logger.info(f"   - {counts_before['Supplier Mappings']} supplier mapping(s)")
        
        response = input("\n❓ Are you sure you want to continue? (yes/no): ")
        
        if response.lower() not in ['yes', 'y']:
            logger.info("❌ Operation cancelled by user")
            return
        
        logger.info("\n🔄 Starting cleanup...")
        
        # Delete in correct order (respecting foreign keys)
        
        # 1. Delete canonical merged documents
        logger.info("   Deleting canonical merged documents...")
        session.execute(text("DELETE FROM sat_canonical_merged"))
        logger.info(f"   ✅ Deleted {counts_before['Canonical Merges']} canonical merge(s)")
        
        # 2. Delete simple merged documents
        logger.info("   Deleting simple merged documents...")
        session.execute(text("DELETE FROM sat_simple_merged"))
        logger.info(f"   ✅ Deleted {counts_before['Simple Merges']} simple merge(s)")
        
        # 3. Delete SAT documents
        logger.info("   Deleting SAT documents...")
        session.execute(text("DELETE FROM sat_documents"))
        logger.info(f"   ✅ Deleted {counts_before['SAT Documents']} SAT document(s)")
        
        # Commit the changes
        session.commit()
        
        # Verify deletion
        logger.info("\n📊 Verifying cleanup...")
        counts_after = {}
        for name, query in count_queries.items():
            result = session.execute(text(query))
            count = result.scalar()
            counts_after[name] = count
            logger.info(f"   {name}: {count}")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("✅ CLEANUP COMPLETE!")
        logger.info("=" * 60)
        logger.info(f"   Deleted {counts_before['SAT Documents']} SAT document(s)")
        logger.info(f"   Deleted {counts_before['Simple Merges']} simple merge(s)")
        logger.info(f"   Deleted {counts_before['Canonical Merges']} canonical merge(s)")
        logger.info(f"   Kept {counts_after['Supplier Mappings']} supplier mapping(s)")
        logger.info("=" * 60)
        logger.info("\n🚀 Ready for fresh testing!")
        logger.info("   Next step: python test_upload_only.py")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    reset_sat_data()

