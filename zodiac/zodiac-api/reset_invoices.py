"""
Reset Invoices Script
Cleans up all invoice records (successful and failed) for fresh testing.
Optionally clears business intelligence data.
Keeps customer configuration and user data intact.

IMPORTANT: Also clears uploaded XML files and the in-memory processing cache.
"""
import os
import sys
import shutil
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

def reset_invoices(include_business_data: bool = True, clear_uploads: bool = True):
    """
    Delete all invoice records for fresh testing
    
    Args:
        include_business_data: If True, also clears business intelligence data
        clear_uploads: If True, also clears uploaded XML files from uploads/ folder
    """
    
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
        logger.info("🧹 RESET INVOICE SYSTEM")
        logger.info("=" * 60)
        
        # Count records before deletion
        logger.info("\n📊 Counting existing records...")
        
        count_queries = {
            "Successful Invoices": "SELECT COUNT(*) FROM zodiac_invoice_success_edi",
            "Failed Invoices": "SELECT COUNT(*) FROM zodiac_invoice_failed_edi",
        }
        
        if include_business_data:
            count_queries["Business Intelligence Data"] = "SELECT COUNT(*) FROM invoice_business_data"
        
        counts_before = {}
        for name, query in count_queries.items():
            try:
                result = session.execute(text(query))
                count = result.scalar()
                counts_before[name] = count
                logger.info(f"   {name}: {count}")
            except Exception as e:
                logger.warning(f"   {name}: Table may not exist ({e})")
                counts_before[name] = 0
        
        # Count uploaded files
        uploads_folder = Path(__file__).parent / "uploads"
        file_count = 0
        if uploads_folder.exists() and clear_uploads:
            file_count = len(list(uploads_folder.glob("*.xml")))
            logger.info(f"   Uploaded XML Files: {file_count}")
        
        # Ask for confirmation
        logger.info("\n⚠️  WARNING: This will DELETE:")
        logger.info(f"   - {counts_before.get('Successful Invoices', 0)} successful invoice(s) from database")
        logger.info(f"   - {counts_before.get('Failed Invoices', 0)} failed invoice(s) from database")
        if include_business_data:
            logger.info(f"   - {counts_before.get('Business Intelligence Data', 0)} business intelligence record(s)")
        if clear_uploads:
            logger.info(f"   - {file_count} uploaded XML file(s) from uploads/ folder")
            logger.info(f"   - In-memory processing cache (requires server restart)")
        
        logger.info(f"\n✅ This will KEEP:")
        logger.info(f"   - All user accounts")
        logger.info(f"   - All customer configurations")
        logger.info(f"   - All SAT documents and merges")
        
        logger.info("\n💡 TIP: This is useful for testing invoice processing from scratch.")
        logger.info("💡 IMPORTANT: Restart the API server after running this script!")
        
        response = input("\n❓ Are you sure you want to continue? (yes/no): ")
        
        if response.lower() not in ['yes', 'y']:
            logger.info("❌ Operation cancelled by user")
            return
        
        logger.info("\n🔄 Starting cleanup...")
        
        # Delete in correct order (respecting foreign keys if any)
        
        # 1. Delete business intelligence data first (if requested)
        if include_business_data:
            logger.info("   Deleting business intelligence data...")
            try:
                result = session.execute(text("DELETE FROM invoice_business_data"))
                session.commit()
                deleted_count = result.rowcount
                logger.info(f"   ✅ Deleted {deleted_count} business intelligence record(s)")
            except Exception as e:
                logger.warning(f"   ⚠️ Business intelligence table may not exist: {e}")
                session.rollback()
        
        # 2. Delete failed invoices
        logger.info("   Deleting failed invoices...")
        result = session.execute(text("DELETE FROM zodiac_invoice_failed_edi"))
        session.commit()
        failed_deleted = result.rowcount
        logger.info(f"   ✅ Deleted {failed_deleted} failed invoice(s)")
        
        # 3. Delete successful invoices
        logger.info("   Deleting successful invoices...")
        result = session.execute(text("DELETE FROM zodiac_invoice_success_edi"))
        session.commit()
        success_deleted = result.rowcount
        logger.info(f"   ✅ Deleted {success_deleted} successful invoice(s)")
        
        # 4. Delete uploaded XML files
        files_deleted = 0
        if clear_uploads:
            logger.info("   Deleting uploaded XML files...")
            uploads_folder = Path(__file__).parent / "uploads"
            if uploads_folder.exists():
                for xml_file in uploads_folder.glob("*.xml"):
                    try:
                        xml_file.unlink()
                        files_deleted += 1
                    except Exception as e:
                        logger.warning(f"   ⚠️ Could not delete {xml_file.name}: {e}")
                logger.info(f"   ✅ Deleted {files_deleted} uploaded XML file(s)")
            else:
                logger.info(f"   ℹ️ Uploads folder doesn't exist, nothing to delete")
        
        # Verify cleanup
        logger.info("\n📊 Verifying cleanup...")
        for name, query in count_queries.items():
            try:
                result = session.execute(text(query))
                count = result.scalar()
                logger.info(f"   {name}: {count}")
            except Exception as e:
                logger.info(f"   {name}: 0")
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ CLEANUP COMPLETE!")
        logger.info("=" * 60)
        logger.info(f"   Deleted {success_deleted} successful invoice(s) from database")
        logger.info(f"   Deleted {failed_deleted} failed invoice(s) from database")
        if include_business_data:
            logger.info(f"   Deleted business intelligence records from database")
        if clear_uploads:
            logger.info(f"   Deleted {files_deleted} uploaded XML file(s)")
        logger.info("=" * 60)
        
        logger.info("\n🚀 Ready for fresh invoice testing!")
        logger.info("\n📋 NEXT STEPS:")
        logger.info("   1. ⚠️ RESTART API SERVER (REQUIRED!):")
        logger.info("      • Stop the server (Ctrl+C)")
        logger.info("      • Start: uvicorn app.server:app --reload")
        logger.info("      • This clears the in-memory duplicate check cache")
        logger.info("   2. Go to: http://localhost:3000/invoices")
        logger.info("   3. Upload test invoices and verify:")
        logger.info("      • Invoices upload successfully (no false duplicates)")
        logger.info("      • Failed invoices appear with all data")
        logger.info("      • Format shows XML (not EDIFACT) for new customers")
        logger.info("      • Source shows 'Manual' for web uploads")
        logger.info("      • Real duplicate invoice numbers are blocked")
        logger.info("=" * 60)
        logger.info("\n💡 WHY RESTART? The API keeps an in-memory cache (_processing_invoices)")
        logger.info("   to prevent race conditions. This cache is cleared on restart.")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Reset invoice system for fresh testing')
    parser.add_argument(
        '--keep-business-data',
        action='store_true',
        help='Keep business intelligence data (only delete invoice records)'
    )
    parser.add_argument(
        '--keep-uploads',
        action='store_true',
        help='Keep uploaded XML files in uploads/ folder (only delete database records)'
    )
    
    args = parser.parse_args()
    
    reset_invoices(
        include_business_data=not args.keep_business_data,
        clear_uploads=not args.keep_uploads
    )
