"""
Database migration script to add invoice_number column to invoice tables.
This enables fast duplicate checking without reading XML files.

Run this ONCE after deploying the new code:
    python add_invoice_number_column.py
"""

import logging
from sqlalchemy import text
from app.database import SessionLocal, engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Add invoice_number column to both successful and failed invoice tables"""
    
    logger.info("=" * 70)
    logger.info("DATABASE MIGRATION: Adding invoice_number column")
    logger.info("=" * 70)
    
    db = SessionLocal()
    
    try:
        # Check if column already exists in success table
        logger.info("\n📊 Checking zodiac_invoice_success_edi table...")
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='zodiac_invoice_success_edi' 
            AND column_name='invoice_number'
        """))
        
        if result.fetchone():
            logger.info("✅ Column invoice_number already exists in zodiac_invoice_success_edi")
        else:
            logger.info("➕ Adding invoice_number column to zodiac_invoice_success_edi...")
            db.execute(text("""
                ALTER TABLE zodiac_invoice_success_edi 
                ADD COLUMN invoice_number VARCHAR(255);
            """))
            db.execute(text("""
                CREATE INDEX ix_zodiac_invoice_success_edi_invoice_number 
                ON zodiac_invoice_success_edi(invoice_number);
            """))
            db.commit()
            logger.info("✅ Column added successfully to zodiac_invoice_success_edi")
        
        # Check if column already exists in failed table
        logger.info("\n📊 Checking zodiac_invoice_failed_edi table...")
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='zodiac_invoice_failed_edi' 
            AND column_name='invoice_number'
        """))
        
        if result.fetchone():
            logger.info("✅ Column invoice_number already exists in zodiac_invoice_failed_edi")
        else:
            logger.info("➕ Adding invoice_number column to zodiac_invoice_failed_edi...")
            db.execute(text("""
                ALTER TABLE zodiac_invoice_failed_edi 
                ADD COLUMN invoice_number VARCHAR(255);
            """))
            db.execute(text("""
                CREATE INDEX ix_zodiac_invoice_failed_edi_invoice_number 
                ON zodiac_invoice_failed_edi(invoice_number);
            """))
            db.commit()
            logger.info("✅ Column added successfully to zodiac_invoice_failed_edi")
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ MIGRATION COMPLETE!")
        logger.info("=" * 70)
        logger.info("\n📝 NOTES:")
        logger.info("   - New invoices will automatically have invoice_number populated")
        logger.info("   - Old invoices (uploaded before this migration) will have NULL")
        logger.info("   - The system will fall back to reading XML files for old invoices")
        logger.info("   - Duplicate check will be much faster for new invoices")
        logger.info("\n🚀 You can now restart your server and test duplicate prevention!")
        
    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        db.rollback()
        import traceback
        logger.error(traceback.format_exc())
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
