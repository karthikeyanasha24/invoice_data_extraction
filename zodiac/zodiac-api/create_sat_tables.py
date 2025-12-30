"""
Create SAT-related database tables directly.
Run this script to set up the SAT document processing tables.
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
print("Creating SAT Database Tables")
print("=" * 70)

# Create sat_documents table
create_sat_documents = """
CREATE TABLE IF NOT EXISTS sat_documents (
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
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sat_documents_id ON sat_documents(id);
CREATE INDEX IF NOT EXISTS idx_sat_documents_user_id ON sat_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_sat_documents_cfdi_uuid ON sat_documents(cfdi_uuid);
CREATE INDEX IF NOT EXISTS idx_sat_documents_doc_type ON sat_documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_sat_documents_supplier_rfc ON sat_documents(supplier_rfc);
CREATE INDEX IF NOT EXISTS idx_sat_documents_fecha ON sat_documents(fecha);
CREATE INDEX IF NOT EXISTS idx_sat_documents_status ON sat_documents(status);
CREATE INDEX IF NOT EXISTS idx_sat_documents_related_uuid ON sat_documents(related_cfdi_uuid);
CREATE INDEX IF NOT EXISTS idx_sat_documents_canonical_id ON sat_documents(canonical_merged_id);
CREATE INDEX IF NOT EXISTS idx_sat_documents_xml_hash ON sat_documents(xml_hash);
CREATE INDEX IF NOT EXISTS idx_sat_documents_fiscal_year ON sat_documents(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_sat_documents_fiscal_period ON sat_documents(fiscal_period);
CREATE INDEX IF NOT EXISTS idx_sat_user_status ON sat_documents(user_id, status);
CREATE INDEX IF NOT EXISTS idx_sat_supplier_period ON sat_documents(supplier_rfc, fiscal_year, fiscal_period);
CREATE INDEX IF NOT EXISTS idx_sat_canonical_merge ON sat_documents(canonical_merged_id, status);
"""

# Create sat_canonical_merged table
create_canonical_merged = """
CREATE TABLE IF NOT EXISTS sat_canonical_merged (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL,
    company_code VARCHAR(10) DEFAULT 'MX01',
    vendor_rfc VARCHAR(13) NOT NULL,
    vendor_name VARCHAR(255),
    fiscal_year INTEGER NOT NULL,
    fiscal_period INTEGER NOT NULL,
    total_invoices NUMERIC(15, 2) DEFAULT 0,
    total_credits NUMERIC(15, 2) DEFAULT 0,
    total_payments NUMERIC(15, 2) DEFAULT 0,
    net_amount NUMERIC(15, 2) DEFAULT 0,
    currency VARCHAR(3) DEFAULT 'MXN',
    payment_method VARCHAR(50),
    cfdi_uuids TEXT[],
    related_cfdi_uuids TEXT[],
    linked_document_ids TEXT[],
    line_items JSONB,
    sap_gl_account VARCHAR(20),
    status VARCHAR(20) DEFAULT 'MERGED',
    sap_document_number VARCHAR(50),
    sent_to_sap_at TIMESTAMP,
    sap_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_canonical_id ON sat_canonical_merged(id);
CREATE INDEX IF NOT EXISTS idx_canonical_user_id ON sat_canonical_merged(user_id);
CREATE INDEX IF NOT EXISTS idx_canonical_vendor_rfc ON sat_canonical_merged(vendor_rfc);
CREATE INDEX IF NOT EXISTS idx_canonical_fiscal_year ON sat_canonical_merged(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_canonical_fiscal_period ON sat_canonical_merged(fiscal_period);
CREATE INDEX IF NOT EXISTS idx_canonical_status ON sat_canonical_merged(status);
CREATE INDEX IF NOT EXISTS idx_canonical_sap_gl ON sat_canonical_merged(sap_gl_account);
CREATE INDEX IF NOT EXISTS idx_canonical_vendor_period ON sat_canonical_merged(vendor_rfc, fiscal_year, fiscal_period);
CREATE INDEX IF NOT EXISTS idx_canonical_user_status ON sat_canonical_merged(user_id, status);
"""

# Create sat_supplier_account_mapping table
create_supplier_mapping = """
CREATE TABLE IF NOT EXISTS sat_supplier_account_mapping (
    id SERIAL PRIMARY KEY,
    supplier_rfc VARCHAR(13) UNIQUE NOT NULL,
    sap_gl_account VARCHAR(20) NOT NULL,
    account_description VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    created_by VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_supplier_mapping_rfc ON sat_supplier_account_mapping(supplier_rfc);
CREATE INDEX IF NOT EXISTS idx_supplier_mapping_gl ON sat_supplier_account_mapping(sap_gl_account);
CREATE INDEX IF NOT EXISTS idx_supplier_mapping_active ON sat_supplier_account_mapping(is_active, supplier_rfc);

-- Insert default mapping
INSERT INTO sat_supplier_account_mapping (supplier_rfc, sap_gl_account, account_description, is_active, is_default)
VALUES ('DEFAULT', '9999999999', 'Default unmapped supplier account', TRUE, TRUE)
ON CONFLICT (supplier_rfc) DO NOTHING;
"""

try:
    with engine.connect() as conn:
        print("\n📝 Creating sat_documents table...")
        conn.execute(text(create_sat_documents))
        conn.commit()
        print("✅ sat_documents table created")
        
        print("\n📝 Creating sat_canonical_merged table...")
        conn.execute(text(create_canonical_merged))
        conn.commit()
        print("✅ sat_canonical_merged table created")
        
        print("\n📝 Creating sat_supplier_account_mapping table...")
        conn.execute(text(create_supplier_mapping))
        conn.commit()
        print("✅ sat_supplier_account_mapping table created")
        
    print("\n" + "=" * 70)
    print("✅ All SAT tables created successfully!")
    print("=" * 70)
    
except Exception as e:
    print(f"\n❌ Error creating tables: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

