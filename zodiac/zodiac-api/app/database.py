import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL environment variable is required but not set!")
    print("Available environment variables:")
    for key, value in os.environ.items():
        if 'DATABASE' in key or 'API' in key or 'CORS' in key:
            print(f"  {key}={value[:50]}..." if len(value) > 50 else f"  {key}={value}")
    raise ValueError("DATABASE_URL environment variable is required")

# Convert asyncpg URL to psycopg2 URL for synchronous SQLAlchemy
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "5"))  # Reduced for serverless
DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "10"))  # Reduced for serverless

# --------------------------------
# Create SQLAlchemy engine + Base
# --------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=False,
    connect_args={
        "connect_timeout": 10,  # 10 second timeout
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ------------------------------------------
# Import all models to register them with Base.metadata
# This ensures all tables are created when Base.metadata.create_all() is called
# ------------------------------------------
def init_models():
    """Import all models to ensure they are registered with SQLAlchemy Base.metadata.
    This must be called before Base.metadata.create_all() to ensure all tables are created.
    """
    # Import all models - they will register themselves with Base
    try:
        from .models.user import ZodiacUser
        from .models.invoice import ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi
        from .models.customer import Customer
        from .models.correction_cache import CorrectionCache
        from .models.customer_token import CustomerToken
        from .models.customer_certificate import CustomerCertificate
        from .models.certificate_renewal_request import CertificateRenewalRequest
        from .models.certificate_revocation import CertificateRevocation
        from .models.ai_query_memory import AiQueryMemory
        # Models are now registered with Base.metadata
        print("✅ All models initialized and registered with Base.metadata")
    except ImportError as e:
        print(f"⚠️ Warning: Could not import all models: {e}")
    except Exception as e:
        print(f"⚠️ Warning: Error initializing models: {e}")

# Initialize all models when this module is loaded
init_models()

# ------------------------------------------
# Function to create all database tables
# ------------------------------------------
def create_all_tables():
    """Create all database tables based on registered models.
    This ensures all tables (including all columns) are created in the database.
    Safe to call multiple times - SQLAlchemy will only create missing tables/columns.
    """
    try:
        # Ensure all models are initialized first
        init_models()
        
        # Create all tables defined in models
        Base.metadata.create_all(bind=engine)
        print("✅ All database tables created/verified successfully")
        return True
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")
        return False

# ------------------------------------------
# Ensure all required columns exist (safe + idempotent)
# This ensures all model-defined columns exist in the database tables
# ------------------------------------------
def ensure_columns_exist():
    """Check and add missing columns to all tables.
    This ensures all columns defined in models exist in the database.
    """
    # Define all required columns for each table based on model definitions
    table_columns = {
        # ZodiacUser model - zodiac_users table
        "zodiac_users": {
            "email": "VARCHAR NOT NULL",
            "username": "VARCHAR NOT NULL",
            "password_hash": "VARCHAR NOT NULL",
            "is_active": "BOOLEAN DEFAULT TRUE",
            "is_verified": "BOOLEAN DEFAULT FALSE",
            "is_admin": "BOOLEAN DEFAULT FALSE",
            "created_at": "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TIMESTAMP WITH TIME ZONE NULL",
            "api_user_identifier": "VARCHAR NULL",
            "api_user_allowed": "BOOLEAN DEFAULT TRUE",
            "api_key_hashed": "VARCHAR NULL",
            "api_key_created_at": "TIMESTAMP WITH TIME ZONE NULL",
            "api_key_updated_at": "TIMESTAMP WITH TIME ZONE NULL",
            "api_key_deactivated_at": "TIMESTAMP WITH TIME ZONE NULL",
            "api_key_allow_list": "JSON NULL"
        },
        # Customer model - zodiac_customers table
        "zodiac_customers": {
            "customer_id": "VARCHAR(255) NOT NULL",
            "format": "VARCHAR(32) NOT NULL DEFAULT 'edifact'",
            "validation_rules": "TEXT NULL",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        },
        # CorrectionCache model - correction_cache table
        "correction_cache": {
            "customer_id": "VARCHAR(255) NOT NULL",
            "customer_name": "VARCHAR(500) NULL",
            "error_type": "VARCHAR(100) NOT NULL",
            "error_signature": "VARCHAR(500) NOT NULL",
            "correction_type": "VARCHAR(50) NOT NULL",
            "transformation_rule": "JSON NOT NULL",
            "original_content_snippet": "TEXT NULL",
            "corrected_content_snippet": "TEXT NULL",
            "ai_model_used": "VARCHAR(100) NULL",
            "ai_prompt_hash": "VARCHAR(100) NULL",
            "success_count": "INTEGER DEFAULT 0 NOT NULL",
            "failure_count": "INTEGER DEFAULT 0 NOT NULL",
            "is_active": "BOOLEAN DEFAULT TRUE NOT NULL",
            "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "last_used_at": "TIMESTAMP NULL",
            "last_success_at": "TIMESTAMP NULL",
            "last_failure_at": "TIMESTAMP NULL",
            "created_by_user_id": "INTEGER NULL",
            "notes": "TEXT NULL"
        },
        # ZodiacInvoiceSuccessEdi model - zodiac_invoice_success_edi table
        "zodiac_invoice_success_edi": {
            "tracking_id": "UUID NULL",
            "user_id": "INTEGER NOT NULL",
            "uploaded_at": "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
            "xml_path": "TEXT NULL",
            "xml_validation_pass": "BOOLEAN DEFAULT FALSE",
            "xml_convert_message": "TEXT NULL",
            "edi_path": "TEXT NULL",
            "edi_convert_pass": "BOOLEAN DEFAULT FALSE",
            "edi_convert_message": "TEXT NULL",
            "deleted_at": "TIMESTAMP WITH TIME ZONE NULL",
            "processing_steps": "JSON NULL",
            "blob_xml_path": "TEXT NULL",
            "blob_edi_path": "TEXT NULL",
            "request_type": "VARCHAR DEFAULT 'web' NOT NULL",
            "external_status": "VARCHAR DEFAULT 'False' NULL",
            "external_message": "VARCHAR DEFAULT 'No msg' NULL",
            "target_file_format": "VARCHAR NULL"
        },
        "customer_tokens": {
            "customer_id": "VARCHAR(255) NOT NULL",
            "token": "VARCHAR(255) NOT NULL",
            "token_hash": "VARCHAR(255) NOT NULL",
            "is_active": "BOOLEAN DEFAULT TRUE NOT NULL",
            "created_at": "TIMESTAMP NOT NULL",
            "last_used_at": "TIMESTAMP NULL",
            "expires_at": "TIMESTAMP NULL",
            "created_by": "INTEGER NULL",
            "notes": "TEXT NULL",
        },
        "customer_certificates": {
            "customer_id": "VARCHAR(255) NOT NULL",
            "certificate_type": "VARCHAR(32) NOT NULL DEFAULT 'client'",
            "common_name": "VARCHAR(255) NOT NULL",
            "organization": "VARCHAR(255) NULL",
            "organizational_unit": "VARCHAR(255) NULL",
            "country": "VARCHAR(2) NULL",
            "email": "VARCHAR(255) NULL",
            "certificate_pem": "TEXT NOT NULL",
            "private_key_encrypted": "TEXT NULL",
            "serial_number": "VARCHAR(255) NOT NULL",
            "fingerprint_sha256": "VARCHAR(64) NOT NULL",
            "issued_at": "TIMESTAMP NOT NULL",
            "expires_at": "TIMESTAMP NOT NULL",
            "revoked_at": "TIMESTAMP NULL",
            "renewed_at": "TIMESTAMP NULL",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL",
            "updated_at": "TIMESTAMP NULL",
            "created_by": "INTEGER NULL",
            "revoked_by": "INTEGER NULL",
            "notes": "TEXT NULL",
            "revocation_reason": "VARCHAR(255) NULL",
            "renewed_certificate_id": "INTEGER NULL",
        },
        "certificate_renewal_requests": {
            "certificate_id": "INTEGER NOT NULL",
            "customer_id": "VARCHAR(255) NOT NULL",
            "request_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
            "requested_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL",
            "requested_by": "INTEGER NULL",
            "processed_at": "TIMESTAMP NULL",
            "processed_by": "INTEGER NULL",
            "new_certificate_id": "INTEGER NULL",
            "notes": "TEXT NULL",
            "rejection_reason": "TEXT NULL",
        },
        "certificate_revocation_list": {
            "certificate_id": "INTEGER NOT NULL",
            "customer_id": "VARCHAR(255) NOT NULL",
            "serial_number": "VARCHAR(255) NOT NULL",
            "fingerprint_sha256": "VARCHAR(64) NOT NULL",
            "revoked_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL",
            "revoked_by": "INTEGER NULL",
            "reason": "VARCHAR(64) NULL",
            "notes": "TEXT NULL",
            "published_in_crl_at": "TIMESTAMP NULL",
        },
        # ZodiacInvoiceFailedEdi model - zodiac_invoice_failed_edi table
        "zodiac_invoice_failed_edi": {
            "tracking_id": "UUID NULL",
            "user_id": "INTEGER NOT NULL",
            "uploaded_at": "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TIMESTAMP WITH TIME ZONE NULL",
            "xml_path": "TEXT NULL",
            "xml_validation_pass": "BOOLEAN DEFAULT FALSE",
            "xml_convert_message": "TEXT NULL",
            "edi_path": "TEXT NULL",
            "edi_convert_pass": "BOOLEAN DEFAULT FALSE",
            "edi_convert_message": "TEXT NULL",
            "deleted_at": "TIMESTAMP WITH TIME ZONE NULL",
            "processing_steps": "JSON NULL",
            "blob_xml_path": "TEXT NULL",
            "blob_edi_path": "TEXT NULL",
            "request_type": "VARCHAR DEFAULT 'web' NOT NULL",
            "target_file_format": "VARCHAR NULL"
        }
    }

    with engine.connect() as conn:
        inspector = inspect(engine)
        
        # Define primary key columns that should not be added (they're created with the table)
        primary_keys = {
            "zodiac_users": ["id"],
            "zodiac_customers": ["id"],
            "correction_cache": ["id"],
            "zodiac_invoice_success_edi": ["id"],
            "zodiac_invoice_failed_edi": ["id"],
            "customer_tokens": ["id"],
            "customer_certificates": ["id"],
            "certificate_renewal_requests": ["id"],
            "certificate_revocation_list": ["id"],
        }
        
        tables_checked = 0
        columns_added = 0
        
        for table_name, required_columns in table_columns.items():
            try:
                # Check if table exists first
                if table_name not in inspector.get_table_names():
                    print(f"⚠️ Table '{table_name}' does not exist yet. It will be created by Base.metadata.create_all()")
                    continue
                
                tables_checked += 1
                existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
                pk_columns = set(primary_keys.get(table_name, []))
                
                for col, definition in required_columns.items():
                    # Skip primary key columns - they're created with the table
                    if col in pk_columns:
                        continue
                    
                    if col not in existing_columns:
                        print(f"🛠️ Adding missing column '{col}' to '{table_name}'...")
                        try:
                            # Add the column
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {definition};"))
                            conn.commit()
                            columns_added += 1
                            print(f"✅ Successfully added column '{col}' to '{table_name}'")
                        except Exception as e:
                            error_msg = str(e).lower()
                            # Column might already exist due to race condition
                            if "already exists" in error_msg or "duplicate" in error_msg:
                                print(f"ℹ️ Column '{col}' already exists in '{table_name}' (race condition)")
                            # Handle constraint violations for NOT NULL columns on tables with data
                            elif "violates not-null constraint" in error_msg or ("not null" in error_msg and "default" not in definition.lower()):
                                print(f"⚠️ Cannot add NOT NULL column '{col}' to '{table_name}' with existing data without a default. Error: {e}")
                            else:
                                print(f"⚠️ Failed to add column '{col}' to '{table_name}': {e}")
                            conn.rollback()
                    # Column exists, silently continue
                        
            except Exception as e:
                print(f"⚠️ Could not inspect/update table '{table_name}': {e}")
                continue

        print(f"✅ Column check complete: {tables_checked} tables checked, {columns_added} columns added.")

# Note: ensure_columns_exist() is not called here because tables might not exist yet.
# It should be called after Base.metadata.create_all() in server.py or startup

# --------------------------------
# Dependency: get_db()
# --------------------------------
def get_db():
    """Provide a SQLAlchemy database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------
# Optional SAP database (for Generative AI context only)
# --------------------------------
_sap_engine = None
_sap_session_factory = None


def get_sap_engine():
    """Create or return the SAP database engine. Returns None if SAP_DATABASE_URL is not set."""
    global _sap_engine, _sap_session_factory
    if _sap_engine is not None:
        return _sap_engine
    sap_url = os.getenv("SAP_DATABASE_URL") or os.getenv("SAP_DB_URL")
    if not sap_url:
        return None
    try:
        _sap_engine = create_engine(
            sap_url,
            pool_size=2,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            connect_args={"connect_timeout": 15},
        )
        _sap_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_sap_engine)
        return _sap_engine
    except Exception as e:
        print(f"⚠️ SAP database engine creation failed: {e}")
        return None


def get_sap_db():
    """Provide a SQLAlchemy session for the SAP database. Yields None if SAP is not configured."""
    sap_engine = get_sap_engine()
    if sap_engine is None or _sap_session_factory is None:
        yield None
        return
    session = _sap_session_factory()
    try:
        yield session
    finally:
        session.close()


def get_sap_session():
    """Return a new SAP database session. Caller must close it. Returns None if SAP is not configured."""
    sap_engine = get_sap_engine()
    if sap_engine is None or _sap_session_factory is None:
        return None
    return _sap_session_factory()
