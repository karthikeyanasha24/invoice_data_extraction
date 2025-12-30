"""Check what documents exist in the database"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT id, doc_type, supplier_rfc, total, status, fiscal_year, fiscal_period
        FROM sat_documents 
        WHERE user_id = 1 
        ORDER BY received_at DESC
        LIMIT 10
    """))
    
    rows = result.fetchall()
    
    print(f"\n📊 Found {len(rows)} documents in database:\n")
    
    if rows:
        for row in rows:
            print(f"  - {row[1]}: RFC={row[2]}, Total={row[3]}, Status={row[4]}, Period={row[5]}-{row[6]}")
    else:
        print("  ❌ NO DOCUMENTS FOUND!")
        print("\n  Run: python test_sat_flow.py")

