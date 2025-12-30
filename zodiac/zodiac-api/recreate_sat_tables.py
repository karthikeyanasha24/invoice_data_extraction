"""
Drop and recreate SAT tables with correct schema
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL environment variable not set")
    sys.exit(1)

# Convert asyncpg to psycopg2 if needed
if DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

engine = create_engine(DATABASE_URL)

print("=" * 70)
print("⚠️  WARNING: This will DELETE all SAT data!")
print("=" * 70)
response = input("Are you sure you want to continue? (yes/no): ")

if response.lower() != "yes":
    print("❌ Operation cancelled")
    sys.exit(0)

print("\n🗑️  Dropping existing tables...")

drop_tables = """
DROP TABLE IF EXISTS sat_documents CASCADE;
DROP TABLE IF EXISTS sat_canonical_merged CASCADE;
DROP TABLE IF EXISTS sat_supplier_account_mapping CASCADE;
"""

# Create sat_documents table with CORRECT column names matching the model
create_sat_documents = """
CREATE TABLE sat_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL,
    portal_ref_id VARCHAR(100) UNIQUE NOT NULL,
    cfdi_uuid VARCHAR(36) UNIQUE NOT NULL,
    doc_type VARCHAR(20) NOT NULL,
    supplier_rfc VARCHAR(13) NOT NULL,
    supplier_name VARCHAR(255),
    receiver_rfc VARCHAR(13) NOT NULL,
    receiver_name VARCHAR(255),
    serie VARCHAR(25),
    folio VARCHAR(40),
    fecha TIMESTAMP NOT NULL,
    subtotal VARCHAR(50),
    total VARCHAR(50),
    moneda VARCHAR(3) DEFAULT 'MXN',
    tipo_cambio VARCHAR(20),
    forma_pago VARCHAR(50),
    metodo_pago VARCHAR(50),
    related_cfdi_uuid VARCHAR(36),
    status VARCHAR(20) DEFAULT 'RECEIVED',
    validation_errors TEXT,
    sap_document_number VARCHAR(50),
    sent_to_sap_at TIMESTAMP,
    sap_response TEXT,
    canonical_merged_id UUID,
    merged_at TIMESTAMP,
    xml_content TEXT,
    xml_hash VARCHAR(64),
    file_size INTEGER,
    fiscal_year INTEGER,
    fiscal_period INTEGER,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sat_documents_user_id ON sat_documents(user_id);
CREATE INDEX idx_sat_documents_cfdi_uuid ON sat_documents(cfdi_uuid);
CREATE INDEX idx_sat_documents_doc_type ON sat_documents(doc_type);
CREATE INDEX idx_sat_documents_supplier_rfc ON sat_documents(supplier_rfc);
CREATE INDEX idx_sat_documents_status ON sat_documents(status);
"""

create_canonical_merged = """
CREATE TABLE sat_canonical_merged (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL,
    company_code VARCHAR(10) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_period INTEGER NOT NULL,
    vendor_rfc VARCHAR(13) NOT NULL,
    vendor_name VARCHAR(255),
    total_invoices NUMERIC(18, 2) DEFAULT 0,
    total_credits NUMERIC(18, 2) DEFAULT 0,
    total_payments NUMERIC(18, 2) DEFAULT 0,
    net_amount NUMERIC(18, 2) DEFAULT 0,
    currency VARCHAR(3) DEFAULT 'MXN',
    payment_method VARCHAR(50),
    cfdi_uuids TEXT[],
    related_cfdi_uuids TEXT[],
    linked_document_ids UUID[],
    sap_gl_account VARCHAR(20),
    status VARCHAR(20) DEFAULT 'MERGED',
    sap_document_number VARCHAR(50),
    sent_to_sap_at TIMESTAMP,
    sap_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(vendor_rfc, fiscal_year, fiscal_period, company_code)
);

CREATE INDEX idx_canonical_user_id ON sat_canonical_merged(user_id);
CREATE INDEX idx_canonical_vendor_rfc ON sat_canonical_merged(vendor_rfc);
CREATE INDEX idx_canonical_period ON sat_canonical_merged(fiscal_year, fiscal_period);
"""

create_supplier_mapping = """
CREATE TABLE sat_supplier_account_mapping (
    id SERIAL PRIMARY KEY,
    supplier_rfc VARCHAR(13) UNIQUE NOT NULL,
    sap_gl_account VARCHAR(20) NOT NULL,
    account_description VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_supplier_mapping_rfc ON sat_supplier_account_mapping(supplier_rfc);
CREATE INDEX idx_supplier_mapping_active ON sat_supplier_account_mapping(is_active);

-- Insert default mapping
INSERT INTO sat_supplier_account_mapping (supplier_rfc, sap_gl_account, account_description, is_active, is_default)
VALUES ('DEFAULT', '9999999999', 'Default unmapped supplier account', TRUE, TRUE);
"""

try:
    with engine.connect() as conn:
        # Drop tables
        conn.execute(text(drop_tables))
        conn.commit()
        print("✅ Old tables dropped")
        
        # Create sat_documents
        print("\n📝 Creating sat_documents table...")
        conn.execute(text(create_sat_documents))
        conn.commit()
        print("✅ sat_documents table created")
        
        # Create sat_canonical_merged
        print("\n📝 Creating sat_canonical_merged table...")
        conn.execute(text(create_canonical_merged))
        conn.commit()
        print("✅ sat_canonical_merged table created")
        
        # Create sat_supplier_account_mapping
        print("\n📝 Creating sat_supplier_account_mapping table...")
        conn.execute(text(create_supplier_mapping))
        conn.commit()
        print("✅ sat_supplier_account_mapping table created")
        
    print("\n" + "=" * 70)
    print("✅ All SAT tables recreated successfully!")
    print("=" * 70)
    print("\n🔄 Now restart your backend:")
    print("   python -m uvicorn app.server:app --reload --port 8000")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

