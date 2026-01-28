"""
Make User Admin
Sets is_admin flag to True for a specific user.
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

def make_user_admin(email: str):
    """Set user as admin by email"""
    
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
            logger.info(f"🔧 MAKING USER ADMIN: {email}")
            logger.info("=" * 80)
            
            # Check if user exists
            check_sql = text("SELECT id, email, is_admin FROM zodiac_users WHERE email = :email")
            result = conn.execute(check_sql, {"email": email})
            user = result.fetchone()
            
            if not user:
                logger.error(f"❌ User not found: {email}")
                logger.info("\nAvailable users:")
                all_users_sql = text("SELECT id, email, is_admin FROM zodiac_users LIMIT 10")
                all_users = conn.execute(all_users_sql)
                for u in all_users:
                    logger.info(f"  ID: {u[0]}, Email: {u[1]}, Admin: {u[2]}")
                return
            
            user_id, user_email, is_admin = user
            
            logger.info(f"\n📊 Current Status:")
            logger.info(f"   User ID: {user_id}")
            logger.info(f"   Email: {user_email}")
            logger.info(f"   Is Admin: {is_admin}")
            
            if is_admin:
                logger.info("\n✅ User is already an admin!")
                return
            
            # Update user to admin
            logger.info(f"\n🔄 Setting is_admin = TRUE...")
            update_sql = text("UPDATE zodiac_users SET is_admin = TRUE WHERE email = :email")
            conn.execute(update_sql, {"email": email})
            conn.commit()
            
            logger.info("✅ User updated successfully!")
            
            # Verify update
            verify_sql = text("SELECT is_admin FROM zodiac_users WHERE email = :email")
            result = conn.execute(verify_sql, {"email": email})
            new_is_admin = result.scalar()
            
            logger.info("\n📊 New Status:")
            logger.info(f"   Is Admin: {new_is_admin}")
            
            logger.info("\n" + "=" * 80)
            logger.info("✅ COMPLETE!")
            logger.info("=" * 80)
            logger.info(f"   User {email} is now an admin")
            logger.info("   You can now access admin pages like:")
            logger.info("   - http://localhost:3000/admin/supplier-tokens")
            logger.info("   - http://localhost:3000/admin/account-mapping")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        # Default email
        email = "puspesh@gmail.com"
    
    make_user_admin(email)
