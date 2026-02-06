"""
Database Migration Script - Run Invoice Processing Fixes Migration

This script applies the database migration for invoice processing improvements.
It can be run directly from the command line.

Usage:
    python run_migration.py
    
Or with custom database URL:
    python run_migration.py --db-url "postgresql://user:pass@host:port/db"
"""

import sys
import os
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_database_url():
    """Get database URL from environment or config"""
    try:
        # Try to import from config
        from app.config.config import DATABASE_URL
        return DATABASE_URL
    except ImportError:
        # Fallback to environment variable
        db_url = os.getenv('DATABASE_URL')
        if db_url:
            return db_url
        
        # Fallback to local PostgreSQL
        logger.warning("No DATABASE_URL found, using default local PostgreSQL")
        return "postgresql://postgres:postgres@localhost:5432/zodiac"


def read_migration_sql():
    """Read the migration SQL file"""
    migration_file = os.path.join(
        os.path.dirname(__file__),
        'migrations',
        '001_fix_invoice_request_type_and_indices.sql'
    )
    
    if not os.path.exists(migration_file):
        raise FileNotFoundError(f"Migration file not found: {migration_file}")
    
    with open(migration_file, 'r', encoding='utf-8') as f:
        return f.read()


def check_if_migration_applied(conn):
    """Check if migration has already been applied"""
    try:
        # Check if indices exist
        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM pg_indexes
            WHERE indexname = 'idx_success_invoice_user_uploaded'
        """))
        count = result.scalar()
        return count > 0
    except Exception as e:
        logger.warning(f"Could not check migration status: {e}")
        return False


def apply_migration(db_url):
    """Apply the migration to the database"""
    try:
        logger.info("=" * 60)
        logger.info("Invoice Processing Fixes - Database Migration")
        logger.info("=" * 60)
        logger.info("")
        
        # Create engine
        logger.info(f"Connecting to database...")
        # Hide password in log
        safe_url = db_url.split('@')[1] if '@' in db_url else db_url
        logger.info(f"Database: {safe_url}")
        
        engine = create_engine(db_url)
        
        # Test connection
        with engine.connect() as conn:
            logger.info("✅ Database connection successful")
            
            # Check if already applied
            if check_if_migration_applied(conn):
                logger.warning("⚠️  Migration appears to have been applied already")
                response = input("Do you want to run it again? (y/N): ")
                if response.lower() != 'y':
                    logger.info("Migration cancelled")
                    return False
            
            logger.info("")
            logger.info("Reading migration SQL...")
            sql = read_migration_sql()
            
            logger.info("Applying migration...")
            logger.info("")
            
            # Split SQL into individual statements
            statements = []
            current_statement = []
            
            for line in sql.split('\n'):
                # Skip comments and empty lines
                line_stripped = line.strip()
                if line_stripped.startswith('--') or not line_stripped:
                    continue
                
                current_statement.append(line)
                
                # If line ends with semicolon, it's end of statement
                if line_stripped.endswith(';'):
                    statement = '\n'.join(current_statement)
                    statements.append(statement)
                    current_statement = []
            
            # Execute each statement
            success_count = 0
            for i, statement in enumerate(statements, 1):
                try:
                    # Get first few words for logging
                    statement_preview = ' '.join(statement.split()[:5]) + '...'
                    logger.info(f"[{i}/{len(statements)}] Executing: {statement_preview}")
                    
                    conn.execute(text(statement))
                    conn.commit()
                    success_count += 1
                    
                except SQLAlchemyError as e:
                    # Some statements might fail if already applied (like ALTER DEFAULT)
                    error_msg = str(e)
                    if 'already exists' in error_msg.lower() or 'does not exist' in error_msg.lower():
                        logger.warning(f"  ⚠️  Skipped (already applied): {error_msg.split('DETAIL:')[0].strip()}")
                    else:
                        logger.error(f"  ❌ Failed: {e}")
                        raise
            
            logger.info("")
            logger.info("=" * 60)
            logger.info(f"✅ Migration completed successfully!")
            logger.info(f"   Executed {success_count}/{len(statements)} statements")
            logger.info("=" * 60)
            logger.info("")
            
            # Verify migration
            logger.info("Verifying migration...")
            
            # Check request_type defaults
            result = conn.execute(text("""
                SELECT column_default 
                FROM information_schema.columns 
                WHERE table_name = 'zodiac_invoice_success_edi' 
                AND column_name = 'request_type'
            """))
            default_value = result.scalar()
            logger.info(f"✅ request_type default: {default_value}")
            
            # Check indices
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM pg_indexes 
                WHERE tablename IN ('zodiac_invoice_success_edi', 'zodiac_invoice_failed_edi')
                AND indexname LIKE 'idx_%'
            """))
            index_count = result.scalar()
            logger.info(f"✅ Performance indices created: {index_count}")
            
            # Check NULL values
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM zodiac_invoice_success_edi 
                WHERE request_type IS NULL
            """))
            null_count = result.scalar()
            logger.info(f"✅ NULL request_type values in success table: {null_count}")
            
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM zodiac_invoice_failed_edi 
                WHERE request_type IS NULL
            """))
            null_count = result.scalar()
            logger.info(f"✅ NULL request_type values in failed table: {null_count}")
            
            logger.info("")
            logger.info("Migration verification complete!")
            logger.info("")
            
            return True
            
    except FileNotFoundError as e:
        logger.error(f"❌ Error: {e}")
        return False
    except SQLAlchemyError as e:
        logger.error(f"❌ Database error: {e}")
        logger.error("")
        logger.error("Migration failed! Please check the error above.")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def rollback_migration(db_url):
    """Rollback the migration"""
    logger.info("=" * 60)
    logger.info("Rolling back migration...")
    logger.info("=" * 60)
    
    rollback_sql = """
    -- Drop indices
    DROP INDEX IF EXISTS idx_success_invoice_user_uploaded;
    DROP INDEX IF EXISTS idx_failed_invoice_user_uploaded;
    DROP INDEX IF EXISTS idx_success_invoice_request_type;
    DROP INDEX IF EXISTS idx_failed_invoice_request_type;
    DROP INDEX IF EXISTS idx_success_invoice_user_request_type;
    DROP INDEX IF EXISTS idx_failed_invoice_user_request_type;
    DROP INDEX IF EXISTS idx_success_invoice_deleted;
    DROP INDEX IF EXISTS idx_failed_invoice_deleted;
    
    -- Revert request_type defaults (optional - doesn't affect existing data)
    ALTER TABLE zodiac_invoice_success_edi ALTER COLUMN request_type DROP DEFAULT;
    ALTER TABLE zodiac_invoice_failed_edi ALTER COLUMN request_type DROP DEFAULT;
    """
    
    try:
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            for statement in rollback_sql.split(';'):
                statement = statement.strip()
                if statement:
                    try:
                        conn.execute(text(statement))
                        conn.commit()
                    except SQLAlchemyError as e:
                        logger.warning(f"Rollback statement warning: {e}")
            
            logger.info("✅ Rollback completed")
            return True
            
    except Exception as e:
        logger.error(f"❌ Rollback failed: {e}")
        return False


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Run invoice processing database migration'
    )
    parser.add_argument(
        '--db-url',
        type=str,
        help='Database URL (e.g., postgresql://user:pass@host:port/db)'
    )
    parser.add_argument(
        '--rollback',
        action='store_true',
        help='Rollback the migration instead of applying it'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without executing'
    )
    
    args = parser.parse_args()
    
    # Get database URL
    db_url = args.db_url or get_database_url()
    
    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("")
        logger.info("Would connect to database:")
        safe_url = db_url.split('@')[1] if '@' in db_url else db_url
        logger.info(f"  {safe_url}")
        logger.info("")
        logger.info("Would apply migration:")
        logger.info("  - Set request_type defaults to 'web'")
        logger.info("  - Update NULL values to 'web'")
        logger.info("  - Create 8 performance indices")
        logger.info("")
        return 0
    
    # Apply or rollback migration
    if args.rollback:
        success = rollback_migration(db_url)
    else:
        success = apply_migration(db_url)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
