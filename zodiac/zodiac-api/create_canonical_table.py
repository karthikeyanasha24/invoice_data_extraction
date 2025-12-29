"""
Create SAT Canonical Merged Table
Run this to create the canonical merged documents table
"""
from sqlalchemy import create_engine
from app.models.sat_canonical_merged import SATCanonicalMerged
from app.database import Base
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

engine = create_engine(DATABASE_URL)

print("\n" + "=" * 70)
print("🚀 Creating sat_canonical_merged table...")
print("=" * 70 + "\n")

try:
    Base.metadata.create_all(engine, tables=[SATCanonicalMerged.__table__])
    print("✅ sat_canonical_merged table created successfully!")
except Exception as e:
    print(f"❌ Error creating table: {e}")

print("\n" + "=" * 70)
print("✅ Done! You can now merge SAT documents into canonical format.")
print("=" * 70 + "\n")

