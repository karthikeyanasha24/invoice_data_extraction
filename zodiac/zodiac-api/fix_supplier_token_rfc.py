"""
Fix Supplier Token RFC - Remove whitespace
"""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import sys
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Trim whitespace from all supplier RFCs
    result = conn.execute(text("""
        UPDATE supplier_tokens 
        SET supplier_rfc = TRIM(UPPER(supplier_rfc))
        WHERE supplier_rfc != TRIM(UPPER(supplier_rfc))
        RETURNING id, supplier_rfc
    """))
    
    updated = result.fetchall()
    conn.commit()
    
    print(f"Fixed {len(updated)} token(s)")
    for row in updated:
        print(f"  ID {row[0]}: RFC = '{row[1]}'")
    
    if len(updated) == 0:
        print("No tokens needed fixing")
