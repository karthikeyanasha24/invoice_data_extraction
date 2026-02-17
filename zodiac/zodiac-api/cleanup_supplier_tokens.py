"""
Script to delete all supplier tokens from the database.
Use this to clean up and start fresh with token generation.

Usage:
    python cleanup_supplier_tokens.py           # Delete all tokens (with confirmation)
    python cleanup_supplier_tokens.py --show    # Just show tokens without deleting
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.dialects.postgresql import JSON

# Load environment variables
load_dotenv()

# Create a local Base (avoid circular imports)
Base = declarative_base()


# Define SupplierToken model locally (simplified)
class SupplierToken(Base):
    __tablename__ = "supplier_tokens"
    
    id = Column(Integer, primary_key=True)
    supplier_rfc = Column(String(13), unique=True, nullable=False)
    supplier_name = Column(String(255))
    token = Column(String(255), unique=True, nullable=False)
    token_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)
    created_by = Column(Integer)
    ip_whitelist = Column(JSON)
    notes = Column(Text)


def get_database_connection():
    """Get database engine and session"""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set!")
        print("Please ensure .env file exists with DATABASE_URL")
        sys.exit(1)
    
    # Convert asyncpg to psycopg2 if needed
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal()


def cleanup_all_tokens():
    """Delete all supplier tokens from the database"""
    
    print("=" * 80)
    print("SUPPLIER TOKEN CLEANUP SCRIPT")
    print("=" * 80)
    print()
    
    try:
        engine, db = get_database_connection()
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        return
    
    try:
        # Count existing tokens
        total_tokens = db.query(SupplierToken).count()
        active_tokens = db.query(SupplierToken).filter(SupplierToken.is_active == True).count()
        inactive_tokens = total_tokens - active_tokens
        
        print(f"Current Token Status:")
        print(f"   Total tokens: {total_tokens}")
        print(f"   Active: {active_tokens}")
        print(f"   Inactive: {inactive_tokens}")
        print()
        
        if total_tokens == 0:
            print("No tokens found. Database is already clean.")
            return
        
        # Show tokens before deletion
        print("Tokens to be deleted:")
        tokens = db.query(SupplierToken).all()
        for token in tokens:
            status = "[Active]" if token.is_active else "[Inactive]"
            print(f"   {status} - RFC: {token.supplier_rfc} | Name: {token.supplier_name} | Created: {token.created_at}")
        print()
        
        # Confirm deletion
        print("WARNING: This will DELETE ALL supplier tokens permanently!")
        print()
        confirmation = input("Are you sure you want to delete all tokens? Type 'yes' to confirm: ")
        
        if confirmation.lower() != 'yes':
            print("Deletion cancelled.")
            return
        
        print()
        print("Deleting all tokens...")
        
        # Delete all tokens
        deleted_count = db.query(SupplierToken).delete()
        db.commit()
        
        print(f"Successfully deleted {deleted_count} token(s)")
        print()
        
        # Verify deletion
        remaining = db.query(SupplierToken).count()
        if remaining == 0:
            print("Verification: All tokens have been deleted. Database is clean.")
        else:
            print(f"Warning: {remaining} token(s) still remain in database")
        
        print()
        print("=" * 80)
        print("CLEANUP COMPLETE")
        print("=" * 80)
        print()
        print("You can now create new tokens using the admin interface.")
        
    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print()
        print("Cleanup failed. Please check the error message above.")
        db.rollback()
    
    finally:
        db.close()


def show_tokens_only():
    """Just show existing tokens without deleting"""
    
    try:
        engine, db = get_database_connection()
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        return
    
    try:
        total_tokens = db.query(SupplierToken).count()
        
        if total_tokens == 0:
            print("No supplier tokens found in database.")
            return
        
        print("=" * 80)
        print(f"CURRENT SUPPLIER TOKENS ({total_tokens} total)")
        print("=" * 80)
        print()
        
        tokens = db.query(SupplierToken).order_by(SupplierToken.created_at.desc()).all()
        
        for i, token in enumerate(tokens, 1):
            status = "[Active]" if token.is_active else "[Inactive]"
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
