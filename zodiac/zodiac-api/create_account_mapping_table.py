"""
Create SAT-SAP Account Mapping Table
Run this script to create the account mapping table in your database
"""
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

engine = create_engine(DATABASE_URL)

# SQL to create the table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sat_sap_account_mapping (
    id SERIAL PRIMARY KEY,
    clave_prod_serv VARCHAR(10) NOT NULL UNIQUE,
    sap_gl_account VARCHAR(20) NOT NULL,
    code_group VARCHAR(5) NOT NULL,
    description VARCHAR(255),
    description_en VARCHAR(255),
    account_type VARCHAR(50),
    sat_category VARCHAR(100),
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_default BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_sat_sap_mapping_clave ON sat_sap_account_mapping(clave_prod_serv);
CREATE INDEX IF NOT EXISTS ix_sat_sap_mapping_gl_account ON sat_sap_account_mapping(sap_gl_account);
CREATE INDEX IF NOT EXISTS ix_sat_sap_mapping_code_group ON sat_sap_account_mapping(code_group);
CREATE INDEX IF NOT EXISTS ix_sat_sap_mapping_active ON sat_sap_account_mapping(is_active);
CREATE INDEX IF NOT EXISTS ix_sat_sap_mapping_account_type ON sat_sap_account_mapping(account_type);

-- Insert default fallback mapping
INSERT INTO sat_sap_account_mapping (
    clave_prod_serv, 
    sap_gl_account, 
    code_group, 
    description, 
    description_en,
    account_type, 
    is_default, 
    is_active
)
VALUES (
    '01010101',
    '409999',
    '99',
    'Genérico / Desconocido',
    'Generic / Unknown Product',
    'Generic',
    TRUE,
    TRUE
)
ON CONFLICT (clave_prod_serv) DO NOTHING;
"""

print("\n" + "=" * 70)
print("🚀 Creating SAT-SAP Account Mapping Table")
print("=" * 70 + "\n")

try:
    with engine.connect() as conn:
        # Execute the SQL
        conn.execute(text(CREATE_TABLE_SQL))
        conn.commit()
        
        print("✅ Table 'sat_sap_account_mapping' created successfully!")
        print("✅ Indexes created successfully!")
        print("✅ Default fallback mapping inserted!")
        
        # Verify table was created
        result = conn.execute(text("SELECT COUNT(*) FROM sat_sap_account_mapping"))
        count = result.scalar()
        print(f"\n📊 Current mappings in table: {count}")
        
except Exception as e:
    print(f"❌ Error creating table: {e}")
    raise

print("\n" + "=" * 70)
print("✅ Setup Complete!")
print("=" * 70)
print("\nNext Steps:")
print("1. Upload your Excel mapping file via the API or admin UI")
print("2. Use the /api/v1/sat/account-mapping/upload-excel endpoint")
print("3. Or manually add mappings via the admin UI")
print("\nDefault Mapping Created:")
print("  ClaveProdServ: 01010101")
print("  SAP G/L Account: 409999")
print("  Code Group: 99")
print("  Description: Generic / Unknown Product")
print()

