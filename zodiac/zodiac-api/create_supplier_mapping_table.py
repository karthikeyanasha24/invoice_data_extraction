"""
Create SAT Supplier Account Mapping Table
Standalone script to create the sat_supplier_account_mapping table
"""
import sys
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in .env file")
    sys.exit(1)

# Replace asyncpg with psycopg2 for synchronous operations
if "postgresql+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

print(f"📊 Connecting to database...")
engine = create_engine(DATABASE_URL)

# SQL to create table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sat_supplier_account_mapping (
    id SERIAL PRIMARY KEY,
    supplier_rfc VARCHAR(13) NOT NULL UNIQUE,
    sap_gl_account VARCHAR(20) NOT NULL,
    account_description VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_sat_supplier_mapping_active 
    ON sat_supplier_account_mapping(is_active);
    
CREATE INDEX IF NOT EXISTS ix_sat_supplier_mapping_account 
    ON sat_supplier_account_mapping(sap_gl_account);

CREATE INDEX IF NOT EXISTS ix_sat_supplier_mapping_rfc 
    ON sat_supplier_account_mapping(supplier_rfc);
"""

# SQL to insert default mapping
INSERT_DEFAULT_SQL = """
INSERT INTO sat_supplier_account_mapping 
    (supplier_rfc, sap_gl_account, account_description, is_default, is_active)
VALUES 
    ('DEFAULT', '210999', 'Unknown Supplier / Proveedor Desconocido', TRUE, TRUE)
ON CONFLICT (supplier_rfc) DO NOTHING;
"""

try:
    with engine.begin() as conn:
        print("🔨 Creating sat_supplier_account_mapping table...")
        conn.execute(text(CREATE_TABLE_SQL))
        print("✅ Table created successfully!")
        
        print("📝 Inserting default mapping...")
        conn.execute(text(INSERT_DEFAULT_SQL))
        print("✅ Default mapping created!")
        
    print("\n✅ Supplier mapping table setup complete!")
    print("\n📋 Table structure:")
    print("   - supplier_rfc (VARCHAR13, UNIQUE)")
    print("   - sap_gl_account (VARCHAR20)")
    print("   - account_description (VARCHAR255)")
    print("   - is_active (BOOLEAN)")
    print("   - is_default (BOOLEAN)")
    print("   - notes (TEXT)")
    print("   - created_at (TIMESTAMP)")
    print("   - updated_at (TIMESTAMP)")
    print("\n✅ Default mapping:")
    print("   RFC: DEFAULT → Account: 210999 (Unknown Supplier)")
    
except Exception as e:
    print(f"❌ Error creating table: {e}")
    sys.exit(1)

