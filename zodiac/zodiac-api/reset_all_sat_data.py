"""
Reset ALL SAT Data
Cleans up EVERYTHING: documents, merges, AND supplier mappings.
Use this for complete fresh start.
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

def reset_all_sat_data():
    """Delete ALL SAT-related data: documents, merges, and mappings"""
    
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
        logger.info("🧹 RESET ALL SAT DATA")
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
        logger.info("\n⚠️  WARNING: This will delete EVERYTHING:")
        logger.info(f"   - {counts_before['SAT Documents']} SAT document(s)")
        logger.info(f"   - {counts_before['Simple Merges']} simple merge(s)")
        logger.info(f"   - {counts_before['Canonical Merges']} canonical merge(s)")
        logger.info(f"   - {counts_before['Supplier Mappings']} supplier mapping(s)")
        logger.info("\n🔥 This is a COMPLETE RESET - all SAT data will be gone!")
        
        response = input("\n❓ Are you ABSOLUTELY sure? (yes/no): ")
        
        if response.lower() not in ['yes', 'y']:
            logger.info("❌ Operation cancelled by user")
            return
        
        logger.info("\n🔄 Starting complete cleanup...")
        
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
        
        # 4. Delete supplier account mappings
        logger.info("   Deleting supplier account mappings...")
        session.execute(text("DELETE FROM sat_supplier_account_mapping"))
        logger.info(f"   ✅ Deleted {counts_before['Supplier Mappings']} supplier mapping(s)")
        
        # Commit the changes
        session.commit()
        
        # Verify deletion
        logger.info("\n📊 Verifying complete cleanup...")
        counts_after = {}
        for name, query in count_queries.items():
            result = session.execute(text(query))
            count = result.scalar()
            counts_after[name] = count
            logger.info(f"   {name}: {count}")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("✅ COMPLETE CLEANUP FINISHED!")
        logger.info("=" * 60)
        logger.info(f"   Deleted {counts_before['SAT Documents']} SAT document(s)")
        logger.info(f"   Deleted {counts_before['Simple Merges']} simple merge(s)")
        logger.info(f"   Deleted {counts_before['Canonical Merges']} canonical merge(s)")
        logger.info(f"   Deleted {counts_before['Supplier Mappings']} supplier mapping(s)")
        logger.info("=" * 60)
        logger.info("\n🚀 Ready for complete fresh start!")
        logger.info("\n📋 NEXT STEPS:")
        logger.info("   1. Upload supplier mappings (Excel)")
        logger.info("      → http://localhost:3000/admin/account-mapping")
        logger.info("   2. Upload SAT documents")
        logger.info("      → http://localhost:3000/sat-documents")
        logger.info("   3. Test Simple Merge")
        logger.info("   4. Test Canonical Merge")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    reset_all_sat_data()
