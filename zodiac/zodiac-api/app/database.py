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
