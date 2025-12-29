"""
Quick script to clear SAT test documents
Run before testing to avoid duplicates
"""
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Convert asyncpg URL to psycopg2 if needed
if DATABASE_URL and "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

engine = create_engine(DATABASE_URL)

print("\n" + "=" * 70)
print("🗑️  Clearing SAT Test Documents & Canonical Merged Data")
print("=" * 70 + "\n")

with engine.connect() as conn:
    # Delete canonical merged data
    result0 = conn.execute(text("DELETE FROM sat_canonical_merged WHERE user_id = 3"))
    print(f"✅ Deleted {result0.rowcount} canonical merged records")
    
    # Delete all SAT documents for test user
    result1 = conn.execute(text("DELETE FROM sat_processing_logs WHERE sat_document_id IN (SELECT id FROM sat_documents WHERE user_id = 3)"))
    print(f"✅ Deleted {result1.rowcount} processing logs")
    
    result2 = conn.execute(text("DELETE FROM sat_duplicate_checks WHERE user_id = 3"))
    print(f"✅ Deleted {result2.rowcount} duplicate check entries")
    
    result3 = conn.execute(text("DELETE FROM sat_documents WHERE user_id = 3"))
    print(f"✅ Deleted {result3.rowcount} SAT documents")
    
    conn.commit()

print("\n" + "=" * 70)
print("✅ Test data cleared! You can now run the test.")
print("=" * 70 + "\n")

