"""Create test documents for user ID 3"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import uuid

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

engine = create_engine(DATABASE_URL)

user_id = 3

docs = [
    {
        "portal_ref_id": f"TEST-INV-{uuid.uuid4().hex[:8]}",
        "cfdi_uuid": str(uuid.uuid4()),
        "doc_type": "INVOICE",
        "serie": "A",
        "folio": "1001",
        "fecha": "2025-12-15",
        "subtotal": "10000.00",
        "total": "11600.00"
    },
    {
        "portal_ref_id": f"TEST-CRN-{uuid.uuid4().hex[:8]}",
        "cfdi_uuid": str(uuid.uuid4()),
        "doc_type": "CREDIT_NOTE",
        "serie": "A",
        "folio": "1002",
        "fecha": "2025-12-16",
        "subtotal": "1000.00",
        "total": "1160.00"
    },
    {
        "portal_ref_id": f"TEST-PAY-{uuid.uuid4().hex[:8]}",
        "cfdi_uuid": str(uuid.uuid4()),
        "doc_type": "PAYMENT",
        "serie": "P",
        "folio": "2001",
        "fecha": "2025-12-17",
        "subtotal": "0.00",
        "total": "10440.00"
    }
]

print(f"\n📝 Creating 3 documents for user ID {user_id}...")

with engine.connect() as conn:
    for doc in docs:
        conn.execute(text("""
            INSERT INTO sat_documents (
                user_id, portal_ref_id, cfdi_uuid, doc_type,
                supplier_rfc, supplier_name, receiver_rfc, receiver_name,
                serie, folio, fecha, subtotal, total, moneda,
                status, fiscal_year, fiscal_period, xml_content,
                received_at, updated_at
            ) VALUES (
                :user_id, :portal_ref_id, :cfdi_uuid, :doc_type,
                'ABC123456789', 'Proveedor Test S.A.', 'XYZ987654321', 'Mi Empresa',
                :serie, :folio, :fecha, :subtotal, :total, 'MXN',
                'VALIDATED', 2025, 12, '<XML/>',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {
            "user_id": user_id,
            **doc
        })
        print(f"✅ Created {doc['doc_type']}: {doc['serie']}-{doc['folio']}")
    
    conn.commit()

print(f"\n✅ Success! Run: python test_endpoint.py")

