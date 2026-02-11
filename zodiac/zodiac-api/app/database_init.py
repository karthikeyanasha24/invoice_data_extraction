"""
Database initialization and migration module.
Consolidates all database setup and migration logic for remote server deployment.
"""

import os
import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class DatabaseInitializer:
    """Handles database initialization and migrations"""
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        # Convert asyncpg URL to psycopg2 URL for synchronous SQLAlchemy
        if self.database_url.startswith("postgresql+asyncpg://"):
            self.database_url = self.database_url.replace("postgresql+asyncpg://", "postgresql://")
        
        self.engine = create_engine(self.database_url, echo=False)
    
    def check_column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name 
                    AND column_name = :column_name
                """), {"table_name": table_name, "column_name": column_name})
                
                return result.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking column existence: {e}")
            return False
    
    def check_index_exists(self, index_name: str) -> bool:
        """Check if an index exists"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT indexname 
                    FROM pg_indexes 
                    WHERE indexname = :index_name
                """), {"index_name": index_name})
                
                return result.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking index existence: {e}")
            return False
    
    def add_deleted_at_columns(self):
        """Add deleted_at columns for soft deletion functionality"""
        logger.info("Checking for deleted_at columns...")
        
        migrations = [
            {
                "table": "zodiac_invoice_success_edi",
                "column": "deleted_at",
                "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE NULL;"
            },
            {
                "table": "zodiac_invoice_failed_edi", 
                "column": "deleted_at",
                "sql": "ALTER TABLE zodiac_invoice_failed_edi ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE NULL;"
            }
        ]
        
        indexes = [
            {
                "name": "idx_zodiac_invoice_success_edi_deleted_at",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_deleted_at ON zodiac_invoice_success_edi(deleted_at);"
            },
            {
                "name": "idx_zodiac_invoice_failed_edi_deleted_at", 
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_deleted_at ON zodiac_invoice_failed_edi(deleted_at);"
            },
            {
                "name": "idx_zodiac_invoice_success_edi_user_deleted",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_user_deleted ON zodiac_invoice_success_edi(user_id, deleted_at);"
            },
            {
                "name": "idx_zodiac_invoice_failed_edi_user_deleted",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_user_deleted ON zodiac_invoice_failed_edi(user_id, deleted_at);"
            }
        ]
        
        try:
            with self.engine.connect() as conn:
                # Add columns
                for migration in migrations:
                    if not self.check_column_exists(migration["table"], migration["column"]):
                        logger.info(f"Adding {migration['column']} column to {migration['table']}...")
                        conn.execute(text(migration["sql"]))
                    else:
                        logger.info(f"Column {migration['column']} already exists in {migration['table']}")
                
                # Add indexes
                for index in indexes:
                    if not self.check_index_exists(index["name"]):
                        logger.info(f"Creating index {index['name']}...")
                        conn.execute(text(index["sql"]))
                    else:
                        logger.info(f"Index {index['name']} already exists")
                
                conn.commit()
                logger.info("✅ Deleted_at columns migration completed")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during deleted_at migration: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during deleted_at migration: {e}")
            raise
    
    def add_processing_steps_columns(self):
        """Add processing_steps and processing_steps_error columns for detailed processing information"""
        logger.info("Checking for processing_steps columns...")
        
        migrations = [
            {
                "table": "zodiac_invoice_success_edi",
                "column": "processing_steps",
                "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS processing_steps JSON NULL;"
            },
            {
                "table": "zodiac_invoice_failed_edi",
                "column": "processing_steps",
                "sql": "ALTER TABLE zodiac_invoice_failed_edi ADD COLUMN IF NOT EXISTS processing_steps JSON NULL;"
            },
            {
                "table": "zodiac_invoice_success_edi",
                "column": "processing_steps_error",
                "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS processing_steps_error JSON NULL;"
            },
            {
                "table": "zodiac_invoice_failed_edi",
                "column": "processing_steps_error", 
                "sql": "ALTER TABLE zodiac_invoice_failed_edi ADD COLUMN IF NOT EXISTS processing_steps_error JSON NULL;"
            }
        ]
        
        indexes = [
            {
                "name": "idx_zodiac_invoice_success_edi_processing_steps",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_processing_steps ON zodiac_invoice_success_edi USING GIN ((processing_steps::jsonb));"
            },
            {
                "name": "idx_zodiac_invoice_failed_edi_processing_steps",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_processing_steps ON zodiac_invoice_failed_edi USING GIN ((processing_steps::jsonb));"
            },
            {
                "name": "idx_zodiac_invoice_success_edi_processing_steps_error",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_processing_steps_error ON zodiac_invoice_success_edi USING GIN ((processing_steps_error::jsonb));"
            },
            {
                "name": "idx_zodiac_invoice_failed_edi_processing_steps_error",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_processing_steps_error ON zodiac_invoice_failed_edi USING GIN ((processing_steps_error::jsonb));"
            }
        ]
        
        try:
            with self.engine.connect() as conn:
                # Add columns
                for migration in migrations:
                    if not self.check_column_exists(migration["table"], migration["column"]):
                        logger.info(f"Adding {migration['column']} column to {migration['table']}...")
                        conn.execute(text(migration["sql"]))
                    else:
                        logger.info(f"Column {migration['column']} already exists in {migration['table']}")
                
                # Add indexes
                for index in indexes:
                    if not self.check_index_exists(index["name"]):
                        logger.info(f"Creating index {index['name']}...")
                        conn.execute(text(index["sql"]))
                    else:
                        logger.info(f"Index {index['name']} already exists")
                
                conn.commit()
                logger.info("✅ Processing steps columns migration completed")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during processing steps migration: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during processing steps migration: {e}")
            raise
    
    def add_blob_path_columns(self):
        """Add blob_xml_path and blob_edi_path columns for blob storage path tracking"""
        logger.info("Checking for blob path columns...")
        
        migrations = [
            {
                "table": "zodiac_invoice_success_edi",
                "column": "blob_xml_path",
                "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS blob_xml_path TEXT NULL;"
            },
            {
                "table": "zodiac_invoice_success_edi",
                "column": "blob_edi_path",
                "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS blob_edi_path TEXT NULL;"
            },
            {
                "table": "zodiac_invoice_failed_edi",
                "column": "blob_xml_path", 
                "sql": "ALTER TABLE zodiac_invoice_failed_edi ADD COLUMN IF NOT EXISTS blob_xml_path TEXT NULL;"
            },
            {
                "table": "zodiac_invoice_failed_edi",
                "column": "blob_edi_path", 
                "sql": "ALTER TABLE zodiac_invoice_failed_edi ADD COLUMN IF NOT EXISTS blob_edi_path TEXT NULL;"
            }
        ]
        
        try:
            with self.engine.connect() as conn:
                # Add columns
                for migration in migrations:
                    if not self.check_column_exists(migration["table"], migration["column"]):
                        logger.info(f"Adding {migration['column']} column to {migration['table']}...")
                        conn.execute(text(migration["sql"]))
                    else:
                        logger.info(f"Column {migration['column']} already exists in {migration['table']}")
                
                conn.commit()
                logger.info("✅ Blob path columns migration completed")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during blob path migration: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during blob path migration: {e}")
            raise
    
    def add_api_key_columns(self):
        """Add API key related columns to users table"""
        logger.info("Checking for API key columns...")
        
        migrations = [
            {
                "table": "zodiac_users",
                "column": "api_user_identifier",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_user_identifier VARCHAR UNIQUE;"
            },
            {
                "table": "zodiac_users",
                "column": "api_user_allowed",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_user_allowed BOOLEAN DEFAULT TRUE;"
            },
            {
                "table": "zodiac_users",
                "column": "api_key_hashed",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_key_hashed VARCHAR NULL;"
            },
            {
                "table": "zodiac_users",
                "column": "api_key_created_at",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_key_created_at TIMESTAMP WITH TIME ZONE NULL;"
            },
            {
                "table": "zodiac_users",
                "column": "api_key_updated_at",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_key_updated_at TIMESTAMP WITH TIME ZONE NULL;"
            },
            {
                "table": "zodiac_users",
                "column": "api_key_deactivated_at",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_key_deactivated_at TIMESTAMP WITH TIME ZONE NULL;"
            },
            {
                "table": "zodiac_users",
                "column": "api_key_allow_list",
                "sql": "ALTER TABLE zodiac_users ADD COLUMN IF NOT EXISTS api_key_allow_list JSON NULL;"
            }
        ]
        
        indexes = [
            {
                "name": "idx_zodiac_users_api_user_identifier",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_users_api_user_identifier ON zodiac_users(api_user_identifier);"
            },
            {
                "name": "idx_zodiac_users_api_user_allowed",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_users_api_user_allowed ON zodiac_users(api_user_allowed);"
            }
        ]
        
        try:
            with self.engine.connect() as conn:
                # Add columns
                for migration in migrations:
                    if not self.check_column_exists(migration["table"], migration["column"]):
                        logger.info(f"Adding {migration['column']} column to {migration['table']}...")
                        conn.execute(text(migration["sql"]))
                    else:
                        logger.info(f"Column {migration['column']} already exists in {migration['table']}")
                
                # Add indexes
                for index in indexes:
                    if not self.check_index_exists(index["name"]):
                        logger.info(f"Creating index {index['name']}...")
                        conn.execute(text(index["sql"]))
                    else:
                        logger.info(f"Index {index['name']} already exists")
                
                conn.commit()
                logger.info("✅ API key columns migration completed")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during API key migration: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during API key migration: {e}")
            raise
    
    def add_request_type_columns(self):
        """Add request_type columns to invoice tables"""
        logger.info("Checking for request_type columns...")
        
        migrations = [
            {
                "table": "zodiac_invoice_success_edi",
                "column": "request_type",
                "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS request_type VARCHAR DEFAULT 'web' NOT NULL;"
            },
            {
                "table": "zodiac_invoice_failed_edi",
                "column": "request_type",
                "sql": "ALTER TABLE zodiac_invoice_failed_edi ADD COLUMN IF NOT EXISTS request_type VARCHAR DEFAULT 'web' NOT NULL;"
            }
        ]
        
        indexes = [
            {
                "name": "idx_zodiac_invoice_success_edi_request_type",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_success_edi_request_type ON zodiac_invoice_success_edi(request_type);"
            },
            {
                "name": "idx_zodiac_invoice_failed_edi_request_type",
                "sql": "CREATE INDEX IF NOT EXISTS idx_zodiac_invoice_failed_edi_request_type ON zodiac_invoice_failed_edi(request_type);"
            }
        ]
        
        try:
            with self.engine.connect() as conn:
                # Add columns
                for migration in migrations:
                    if not self.check_column_exists(migration["table"], migration["column"]):
                        logger.info(f"Adding {migration['column']} column to {migration['table']}...")
                        conn.execute(text(migration["sql"]))
                    else:
                        logger.info(f"Column {migration['column']} already exists in {migration['table']}")
                
                # Add indexes
                for index in indexes:
                    if not self.check_index_exists(index["name"]):
                        logger.info(f"Creating index {index['name']}...")
                        conn.execute(text(index["sql"]))
                    else:
                        logger.info(f"Index {index['name']} already exists")
                
                conn.commit()
                logger.info("✅ Request type columns migration completed")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during request type migration: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during request type migration: {e}")
            raise
    
    def verify_tables_exist(self):
        """Verify that required tables exist"""
        required_tables = [
            "zodiac_users",
            "zodiac_invoice_success_edi", 
            "zodiac_invoice_failed_edi"
        ]
        
        try:
            inspector = inspect(self.engine)
            existing_tables = inspector.get_table_names()
            
            missing_tables = []
            for table in required_tables:
                if table not in existing_tables:
                    missing_tables.append(table)
            
            if missing_tables:
                logger.warning(f"Missing required tables: {missing_tables}")
                logger.warning("Please ensure the database schema is created first")
                return False
            
            logger.info("✅ All required tables exist")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying tables: {e}")
            return False
    
    def check_table_exists(self, table_name: str) -> bool:
        """Check if a table exists"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_name = :table_name
                """), {"table_name": table_name})
                
                return result.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking table existence: {e}")
            return False
    
    def create_invoice_v2_tables(self):
        """Create Invoice V2 tables for the new invoice management system"""
        logger.info("Checking for Invoice V2 tables...")
        
        tables = [
            {
                "name": "v2_invoice_documents",
                "sql": """
                    CREATE TABLE IF NOT EXISTS v2_invoice_documents (
                        id SERIAL PRIMARY KEY,
                        tracking_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
                        user_id INTEGER NOT NULL REFERENCES zodiac_users(id),
                        source VARCHAR(50) NOT NULL,
                        filename VARCHAR(500) NOT NULL,
                        xml_path TEXT,
                        blob_xml_path TEXT,
                        validation_status VARCHAR(50) DEFAULT 'not_validated' NOT NULL,
                        uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        deleted_at TIMESTAMP WITH TIME ZONE
                    );
                """
            },
            {
                "name": "v2_validated_invoices",
                "sql": """
                    CREATE TABLE IF NOT EXISTS v2_validated_invoices (
                        id SERIAL PRIMARY KEY,
                        document_id INTEGER UNIQUE NOT NULL REFERENCES v2_invoice_documents(id),
                        status VARCHAR(50) NOT NULL,
                        invoice_data JSON NOT NULL,
                        missing_fields JSON,
                        validation_errors JSON,
                        validation_notes TEXT,
                        correction_applied BOOLEAN DEFAULT FALSE,
                        correction_cache_id UUID,
                        validated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE
                    );
                """
            },
            {
                "name": "v2_correction_cache",
                "sql": """
                    CREATE TABLE IF NOT EXISTS v2_correction_cache (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        customer_id VARCHAR(255) NOT NULL,
                        customer_name VARCHAR(500),
                        field_name VARCHAR(100) NOT NULL,
                        field_value TEXT NOT NULL,
                        error_signature VARCHAR(500) NOT NULL,
                        success_count INTEGER DEFAULT 1 NOT NULL,
                        failure_count INTEGER DEFAULT 0 NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        last_used_at TIMESTAMP,
                        last_success_at TIMESTAMP,
                        last_failure_at TIMESTAMP,
                        created_by_user_id INTEGER REFERENCES zodiac_users(id),
                        notes TEXT
                    );
                """
            }
        ]
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_v2_tracking_id ON v2_invoice_documents(tracking_id);",
            "CREATE INDEX IF NOT EXISTS idx_v2_user_source ON v2_invoice_documents(user_id, source);",
            "CREATE INDEX IF NOT EXISTS idx_v2_validation_status ON v2_invoice_documents(validation_status, deleted_at);",
            "CREATE INDEX IF NOT EXISTS idx_v2_validated_document_id ON v2_validated_invoices(document_id);",
            "CREATE INDEX IF NOT EXISTS idx_v2_validated_status ON v2_validated_invoices(status);",
            "CREATE INDEX IF NOT EXISTS idx_v2_correction_customer_id ON v2_correction_cache(customer_id);",
            "CREATE INDEX IF NOT EXISTS idx_v2_correction_field_name ON v2_correction_cache(field_name);",
            "CREATE INDEX IF NOT EXISTS idx_v2_customer_field ON v2_correction_cache(customer_id, field_name);",
            "CREATE INDEX IF NOT EXISTS idx_v2_error_signature ON v2_correction_cache(error_signature);",
            "CREATE INDEX IF NOT EXISTS idx_v2_active_corrections ON v2_correction_cache(is_active, customer_id);",
        ]
        
        # Add foreign key for correction_cache_id
        fk_sql = """
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints 
                    WHERE constraint_name = 'fk_v2_validated_correction_cache'
                ) THEN
                    ALTER TABLE v2_validated_invoices 
                    ADD CONSTRAINT fk_v2_validated_correction_cache 
                    FOREIGN KEY (correction_cache_id) REFERENCES v2_correction_cache(id);
                END IF;
            END $$;
        """
        
        try:
            with self.engine.connect() as conn:
                # Create tables
                for table in tables:
                    if not self.check_table_exists(table["name"]):
                        logger.info(f"Creating table {table['name']}...")
                        conn.execute(text(table["sql"]))
                    else:
                        logger.info(f"Table {table['name']} already exists")
                
                # Create indexes
                for index_sql in indexes:
                    logger.info(f"Creating index...")
                    conn.execute(text(index_sql))
                
                # Add foreign key
                logger.info("Adding foreign key constraint...")
                conn.execute(text(fk_sql))
                
                conn.commit()
                logger.info("✅ Invoice V2 tables migration completed")
                
        except SQLAlchemyError as e:
            logger.error(f"Database error during Invoice V2 tables migration: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Invoice V2 tables migration: {e}")
            raise
    
    def run_all_migrations(self):
        """Run all database migrations"""
        logger.info("🚀 Starting database initialization and migrations...")
        
        try:
            # Verify tables exist first
            if not self.verify_tables_exist():
                logger.error("❌ Required tables missing. Please create database schema first.")
                return False
            
            # Run migrations
            self.add_deleted_at_columns()
            self.add_processing_steps_columns()
            self.add_blob_path_columns()
            self.add_api_key_columns()
            self.add_request_type_columns()
            self.create_invoice_v2_tables()
            
            logger.info("✅ All database migrations completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Database migration failed: {e}")
            return False
    
    def get_migration_status(self):
        """Get the current status of all migrations"""
        status = {
            "deleted_at_columns": {
                "zodiac_invoice_success_edi": self.check_column_exists("zodiac_invoice_success_edi", "deleted_at"),
                "zodiac_invoice_failed_edi": self.check_column_exists("zodiac_invoice_failed_edi", "deleted_at")
            },
            "processing_steps_columns": {
                "zodiac_invoice_success_edi": self.check_column_exists("zodiac_invoice_success_edi", "processing_steps_error"),
                "zodiac_invoice_failed_edi": self.check_column_exists("zodiac_invoice_failed_edi", "processing_steps_error")
            },
            "blob_path_columns": {
                "zodiac_invoice_success_edi": {
                    "blob_xml_path": self.check_column_exists("zodiac_invoice_success_edi", "blob_xml_path"),
                    "blob_edi_path": self.check_column_exists("zodiac_invoice_success_edi", "blob_edi_path")
                },
                "zodiac_invoice_failed_edi": {
                    "blob_xml_path": self.check_column_exists("zodiac_invoice_failed_edi", "blob_xml_path"),
                    "blob_edi_path": self.check_column_exists("zodiac_invoice_failed_edi", "blob_edi_path")
                }
            },
            "api_key_columns": {
                "zodiac_users": {
                    "api_user_identifier": self.check_column_exists("zodiac_users", "api_user_identifier"),
                    "api_user_allowed": self.check_column_exists("zodiac_users", "api_user_allowed"),
                    "api_key_hashed": self.check_column_exists("zodiac_users", "api_key_hashed"),
                    "api_key_created_at": self.check_column_exists("zodiac_users", "api_key_created_at"),
                    "api_key_updated_at": self.check_column_exists("zodiac_users", "api_key_updated_at"),
                    "api_key_deactivated_at": self.check_column_exists("zodiac_users", "api_key_deactivated_at"),
                    "api_key_allow_list": self.check_column_exists("zodiac_users", "api_key_allow_list")
                }
            },
            "request_type_columns": {
                "zodiac_invoice_success_edi": self.check_column_exists("zodiac_invoice_success_edi", "request_type"),
                "zodiac_invoice_failed_edi": self.check_column_exists("zodiac_invoice_failed_edi", "request_type")
            },
            "indexes": {
                "deleted_at_indexes": [
                    self.check_index_exists("idx_zodiac_invoice_success_edi_deleted_at"),
                    self.check_index_exists("idx_zodiac_invoice_failed_edi_deleted_at"),
                    self.check_index_exists("idx_zodiac_invoice_success_edi_user_deleted"),
                    self.check_index_exists("idx_zodiac_invoice_failed_edi_user_deleted")
                ],
                "processing_steps_indexes": [
                    self.check_index_exists("idx_zodiac_invoice_success_edi_processing_steps_error"),
                    self.check_index_exists("idx_zodiac_invoice_failed_edi_processing_steps_error")
                ]
            }
        }
        
        return status


def initialize_database(database_url: str = None) -> bool:
    """
    Initialize database with all required migrations.
    This function should be called during application startup.
    
    Args:
        database_url: Optional database URL override
        
    Returns:
        bool: True if initialization successful, False otherwise
    """
    try:
        initializer = DatabaseInitializer(database_url)
        return initializer.run_all_migrations()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


def get_database_status(database_url: str = None) -> dict:
    """
    Get the current status of database migrations.
    
    Args:
        database_url: Optional database URL override
        
    Returns:
        dict: Migration status information
    """
    try:
        initializer = DatabaseInitializer(database_url)
        return initializer.get_migration_status()
    except Exception as e:
        logger.error(f"Failed to get database status: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    # Allow running as standalone script for testing
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print("Database Migration Status:")
        print("=" * 50)
        status = get_database_status()
        print(status)
    else:
        print("Running database initialization...")
        success = initialize_database()
        sys.exit(0 if success else 1)


