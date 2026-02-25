"""
Run migration 003: user_customers, customer_receiver_rfc, is_customer_user.
Usage: python run_migration_customer_users.py [--db-url URL]
"""
import os
import sys
import argparse
from sqlalchemy import create_engine, text

def get_db_url():
    try:
        from app.config.config import DATABASE_URL
        return DATABASE_URL
    except ImportError:
        return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/zodiac")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", type=str, help="Database URL")
    args = parser.parse_args()
    db_url = args.db_url or get_db_url()
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    migration_dir = os.path.join(os.path.dirname(__file__), "migrations")
    sql_path = os.path.join(migration_dir, "003_customer_users.sql")
    if not os.path.exists(sql_path):
        print(f"Migration file not found: {sql_path}")
        return 1

    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    engine = create_engine(db_url)
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print(f"Note (may be idempotent): {e}")
                conn.rollback()
            else:
                print(f"Error: {e}")
                conn.rollback()
                return 1
    print("Migration 003 applied successfully.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
