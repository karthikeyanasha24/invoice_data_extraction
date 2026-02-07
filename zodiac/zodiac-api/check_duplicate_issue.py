"""
Quick script to check why duplicate detection isn't working
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
    logger.info("=" * 80)
    logger.info("🔍 DUPLICATE DETECTION ISSUE DIAGNOSIS")
    logger.info("=" * 80)
    
    # Check successful invoices
    logger.info("\n📊 Checking successful invoices with invoice_number='0090040077'...")
    result = session.execute(text("""
        SELECT id, tracking_id, invoice_number, uploaded_at, user_id
        FROM zodiac_invoice_success_edi
        WHERE invoice_number = '0090040077'
        AND deleted_at IS NULL
        ORDER BY uploaded_at DESC
    """))
    
    rows = result.fetchall()
    logger.info(f"\n✅ Found {len(rows)} invoice(s) with invoice_number='0090040077':")
    
    if len(rows) == 0:
        logger.error("❌ NO INVOICES FOUND! This means invoice_number is NOT being saved to DB!")
        logger.error("   The column exists but data is not being written.")
        
        # Check if there are ANY invoices with invoice_number
        result2 = session.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(invoice_number) as with_invoice_number,
                   COUNT(*) - COUNT(invoice_number) as without_invoice_number
            FROM zodiac_invoice_success_edi
            WHERE deleted_at IS NULL
        """))
        row2 = result2.fetchone()
        logger.info(f"\n📊 Database statistics:")
        logger.info(f"   Total invoices: {row2[0]}")
        logger.info(f"   With invoice_number: {row2[1]}")
        logger.info(f"   Without invoice_number (NULL): {row2[2]}")
        
        # Show sample of recent invoices
        logger.info(f"\n📋 Sample of recent invoices:")
        result3 = session.execute(text("""
            SELECT id, tracking_id, invoice_number, uploaded_at
            FROM zodiac_invoice_success_edi
            WHERE deleted_at IS NULL
            ORDER BY uploaded_at DESC
            LIMIT 5
        """))
        rows3 = result3.fetchall()
        for row in rows3:
            logger.info(f"   ID: {row[0]}, Tracking: {row[1][:20]}..., InvoiceNum: {row[2]}, Date: {row[3]}")
    else:
        for i, row in enumerate(rows, 1):
            logger.info(f"\n   Invoice #{i}:")
            logger.info(f"      Database ID: {row[0]}")
            logger.info(f"      Tracking ID: {row[1]}")
            logger.info(f"      Invoice Number: {row[2]}")
            logger.info(f"      Uploaded At: {row[3]}")
            logger.info(f"      User ID: {row[4]}")
        
        if len(rows) > 1:
            logger.error(f"\n🚨 DUPLICATE DETECTION FAILED!")
            logger.error(f"   Expected: 1 invoice")
            logger.error(f"   Found: {len(rows)} invoices")
            logger.error(f"   This means the duplicate check is not working properly!")
    
    logger.info("\n" + "=" * 80)
    
except Exception as e:
    logger.error(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    session.close()
