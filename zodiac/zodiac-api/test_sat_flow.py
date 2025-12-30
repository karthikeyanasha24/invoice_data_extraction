"""
Test SAT Flow: Create sample documents for testing
Run this to simulate suppliers sending documents
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from datetime import datetime
import uuid

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not set")
    sys.exit(1)

if DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

engine = create_engine(DATABASE_URL)

print("=" * 70)
print("Creating Test SAT Documents")
print("=" * 70)

# Auto-fetch the first active user
with engine.connect() as conn:
    result = conn.execute(text("SELECT id, email FROM zodiac_users ORDER BY id LIMIT 1"))
    user_row = result.fetchone()
    
    if not user_row:
        print("\n❌ No users found in database!")
        print("Please create a user account first by logging in to the app.")
        sys.exit(1)
    
    user_id = user_row[0]
    user_email = user_row[1]
    print(f"\n✅ Using user: {user_email} (ID: {user_id})")

company_code = "MX01"

# Test data
test_documents = [
    {
        "portal_ref_id": f"TEST-INV-{uuid.uuid4().hex[:8]}",
        "cfdi_uuid": str(uuid.uuid4()),
        "doc_type": "INVOICE",
        "supplier_rfc": "ABC123456789",
        "supplier_name": "Proveedor Test S.A. de C.V.",
        "receiver_rfc": "XYZ987654321",
        "receiver_name": "Mi Empresa S.A.",
        "serie": "A",
        "folio": "1001",
        "fecha": "2025-12-15",
        "subtotal": "10000.00",
        "total": "11600.00",
        "moneda": "MXN",
        "fiscal_year": 2025,
        "fiscal_period": 12,
        "xml_content": "<Comprobante>Sample Invoice XML</Comprobante>"
    },
    {
        "portal_ref_id": f"TEST-CRN-{uuid.uuid4().hex[:8]}",
        "cfdi_uuid": str(uuid.uuid4()),
        "doc_type": "CREDIT_NOTE",
        "supplier_rfc": "ABC123456789",
        "supplier_name": "Proveedor Test S.A. de C.V.",
        "receiver_rfc": "XYZ987654321",
        "receiver_name": "Mi Empresa S.A.",
        "serie": "A",
        "folio": "1002",
        "fecha": "2025-12-16",
        "subtotal": "1000.00",
        "total": "1160.00",
        "moneda": "MXN",
        "fiscal_year": 2025,
        "fiscal_period": 12,
        "xml_content": "<Comprobante>Sample Credit Note XML</Comprobante>"
    },
    {
        "portal_ref_id": f"TEST-PAY-{uuid.uuid4().hex[:8]}",
        "cfdi_uuid": str(uuid.uuid4()),
        "doc_type": "PAYMENT",
        "supplier_rfc": "ABC123456789",
        "supplier_name": "Proveedor Test S.A. de C.V.",
        "receiver_rfc": "XYZ987654321",
        "receiver_name": "Mi Empresa S.A.",
        "serie": "P",
        "folio": "2001",
        "fecha": "2025-12-17",
        "subtotal": "0.00",
        "total": "10440.00",
        "moneda": "MXN",
        "fiscal_year": 2025,
        "fiscal_period": 12,
        "xml_content": "<Comprobante>Sample Payment XML</Comprobante>"
    }
]

try:
    with engine.connect() as conn:
        print(f"\n📝 Creating {len(test_documents)} test documents for user {user_id}...")
        
        for doc in test_documents:
            insert_sql = text("""
                INSERT INTO sat_documents (
                    user_id, portal_ref_id, cfdi_uuid, doc_type,
                    supplier_rfc, supplier_name, receiver_rfc, receiver_name,
                    serie, folio, fecha, subtotal, total, moneda,
                    status, fiscal_year, fiscal_period, xml_content,
                    received_at, updated_at
                ) VALUES (
                    :user_id, :portal_ref_id, :cfdi_uuid, :doc_type,
                    :supplier_rfc, :supplier_name, :receiver_rfc, :receiver_name,
                    :serie, :folio, :fecha, :subtotal, :total, :moneda,
                    'VALIDATED', :fiscal_year, :fiscal_period, :xml_content,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute(insert_sql, {
                "user_id": user_id,
                **doc
            })
            print(f"✅ Created {doc['doc_type']}: {doc['serie']}-{doc['folio']}")
        
        conn.commit()
        
        print("\n" + "=" * 70)
        print("✅ Test documents created successfully!")
        print("=" * 70)
        print("\n📋 Next Steps:")
        print("1. Go to http://localhost:3000/sat-documents")
        print("2. Click 'Documents' tab to see the 3 test documents")
        print("3. Click 'Canonical Merged' tab")
        print("4. Select Year: 2025, Period: 12")
        print("5. Click 'Generate Canonical' button")
        print("6. Click 'Send to SAP' to see the JSON preview modal")
        print("7. Click 'Confirm & Send to SAP' to complete the flow")
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

