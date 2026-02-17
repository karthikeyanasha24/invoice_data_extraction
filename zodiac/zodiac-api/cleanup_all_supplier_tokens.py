"""
Script to delete all supplier tokens from the database.
Use this to clean up and start fresh with token generation.

Usage:
    python cleanup_all_supplier_tokens.py
"""

import sys
import os
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import SupplierToken model directly
from app.models.supplier_token import SupplierToken


def cleanup_all_tokens():
    """Delete all supplier tokens from the database"""
    
    print("=" * 80)
    print("SUPPLIER TOKEN CLEANUP SCRIPT")
    print("=" * 80)
    print()
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL environment variable not set!")
        print("Please ensure .env file exists with DATABASE_URL")
        return
    
    # Convert asyncpg to psycopg2 if needed
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    # Create engine and session
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Count existing tokens
        total_tokens = db.query(SupplierToken).count()
        active_tokens = db.query(SupplierToken).filter(SupplierToken.is_active == True).count()
        inactive_tokens = total_tokens - active_tokens
        
        print(f"📊 Current Token Status:")
        print(f"   Total tokens: {total_tokens}")
        print(f"   Active: {active_tokens}")
        print(f"   Inactive: {inactive_tokens}")
        print()
        
        if total_tokens == 0:
            print("✅ No tokens found. Database is already clean.")
            return
        
        # Show tokens before deletion
        print("📋 Tokens to be deleted:")
        tokens = db.query(SupplierToken).all()
        for token in tokens:
            status = "🟢 Active" if token.is_active else "🔴 Inactive"
            print(f"   {status} - RFC: {token.supplier_rfc} | Name: {token.supplier_name} | Created: {token.created_at}")
        print()
        
        # Confirm deletion
        print("⚠️  WARNING: This will DELETE ALL supplier tokens permanently!")
        print()
        confirmation = input("Are you sure you want to delete all tokens? Type 'yes' to confirm: ")
        
        if confirmation.lower() != 'yes':
            print("❌ Deletion cancelled.")
            return
        
        print()
        print("🗑️  Deleting all tokens...")
        
        # Delete all tokens
        deleted_count = db.query(SupplierToken).delete()
        db.commit()
        
        print(f"✅ Successfully deleted {deleted_count} token(s)")
        print()
        
        # Verify deletion
        remaining = db.query(SupplierToken).count()
        if remaining == 0:
            print("✅ Verification: All tokens have been deleted. Database is clean.")
        else:
            print(f"⚠️  Warning: {remaining} token(s) still remain in database")
        
        print()
        print("=" * 80)
        print("CLEANUP COMPLETE")
        print("=" * 80)
        print()
        print("You can now create new tokens using the admin interface.")
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        db.rollback()
        print()
        print(f"❌ Error: {e}")
        print()
        print("Cleanup failed. Please check the error message above.")
    
    finally:
        db.close()


def show_tokens_only():
    """Just show existing tokens without deleting"""
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL environment variable not set!")
        print("Please ensure .env file exists with DATABASE_URL")
        return
    
    # Convert asyncpg to psycopg2 if needed
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        total_tokens = db.query(SupplierToken).count()
        
        if total_tokens == 0:
            print("📋 No supplier tokens found in database.")
            return
        
        print("=" * 80)
        print(f"CURRENT SUPPLIER TOKENS ({total_tokens} total)")
        print("=" * 80)
        print()
        
        tokens = db.query(SupplierToken).order_by(SupplierToken.created_at.desc()).all()
        
        for i, token in enumerate(tokens, 1):
            status = "🟢 Active" if token.is_active else "🔴 Inactive"
            expired = ""
            if token.expires_at:
                if token.expires_at < datetime.utcnow():
                    expired = " (EXPIRED)"
            
            print(f"{i}. {status}{expired}")
            print(f"   RFC: {token.supplier_rfc}")
            print(f"   Name: {token.supplier_name}")
            print(f"   Created: {token.created_at}")
            if token.expires_at:
                print(f"   Expires: {token.expires_at}")
            if token.last_used_at:
                print(f"   Last Used: {token.last_used_at}")
            if token.notes:
                print(f"   Notes: {token.notes}")
            print()
        
    finally:
        db.close()


if __name__ == "__main__":
    print()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--show":
        # Just show tokens
        show_tokens_only()
    else:
        # Run cleanup
        cleanup_all_tokens()
    
    print()
