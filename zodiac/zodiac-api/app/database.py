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
    print("Available environment variables:")
    for key, value in os.environ.items():
        if 'DATABASE' in key or 'API' in key or 'CORS' in key:
            print(f"  {key}={value}")
    raise ValueError("DATABASE_URL environment variable is required")

# Convert asyncpg URL to psycopg2 URL for synchronous SQLAlchemy
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "10"))
DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "20"))

# --------------------------------
# Create SQLAlchemy engine + Base
# --------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
    echo=False
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
# Ensure new columns exist (safe + idempotent)
# ------------------------------------------
def ensure_columns_exist():
    """Check if external_status and external_message exist; create them if not."""
    table_name = "zodiac_invoice_success_edi"
    required_columns = {
        "external_status": "VARCHAR DEFAULT 'False'",
        "external_message": "VARCHAR DEFAULT 'No msg'"
    }

    with engine.connect() as conn:
        inspector = inspect(conn)
        try:
            existing_columns = [col["name"] for col in inspector.get_columns(table_name)]
        except Exception as e:
            print(f"⚠️ Could not inspect table '{table_name}': {e}")
            return

        for col, definition in required_columns.items():
            if col not in existing_columns:
                print(f"🛠️ Adding missing column '{col}' to '{table_name}'...")
                try:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col} {definition};"))
                except Exception as e:
                    print(f"⚠️ Failed to add column {col}: {e}")

        conn.commit()
        print("✅ Column check complete.")

# Run check once when this file loads
ensure_columns_exist()

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
