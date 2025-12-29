"""
Create test SAT documents directly in database with VALIDATED status
This ensures they're ready to be merged into canonical format
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.sat_document import SATDocument, DocumentType, ProcessingStatus
from dotenv import load_dotenv
from datetime import datetime
import os
import uuid

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

print("\n" + "=" * 70)
print("🚀 Creating Test SAT Documents (March & December 2025)")
print("=" * 70 + "\n")

# Test user ID (adjust if needed)
TEST_USER_ID = 3

# ==================== MARCH 2025 DOCUMENTS ====================
print("📅 Creating March 2025 documents...")
print("-" * 70)

# Create INVOICE (March)
invoice_mar = SATDocument(
    id=uuid.uuid4(),
    user_id=TEST_USER_ID,
    company_code="MX01",
    portal_reference_id=f"TEST-INV-MAR-{uuid.uuid4().hex[:8]}",
    document_type=DocumentType.INVOICE,
    supplier_id="SUPP001",
    supplier_rfc="ABC123456789",
    supplier_name="Proveedores Industriales SA de CV",
    customer_rfc="MES123456ABC",
    customer_name="Mi Empresa SA de CV",
    cfdi_uuid=str(uuid.uuid4()).upper(),
    cfdi_version="4.0",
    serie="A",
    folio="12345",
    fecha=datetime(2025, 3, 15, 10, 30, 0),
    subtotal="10000.00",
    total="11600.00",
    moneda="MXN",
    tipo_de_comprobante="I",
    status=ProcessingStatus.VALIDATED,
    is_duplicate=False,
    original_xml='<?xml version="1.0"?><cfdi:Comprobante Version="4.0"></cfdi:Comprobante>',
    original_xml_hash=uuid.uuid4().hex
)
session.add(invoice_mar)
print(f"✅ Created INVOICE (March): {invoice_mar.cfdi_uuid}")
print(f"   Amount: $11,600.00 MXN")
print(f"   Status: VALIDATED")
print(f"   Date: 2025-03-15")

# Create PAYMENT (March)
payment_mar = SATDocument(
    id=uuid.uuid4(),
    user_id=TEST_USER_ID,
    company_code="MX01",
    portal_reference_id=f"TEST-PAY-MAR-{uuid.uuid4().hex[:8]}",
    document_type=DocumentType.PAYMENT,
    supplier_id="SUPP001",
    supplier_rfc="ABC123456789",
    supplier_name="Proveedores Industriales SA de CV",
    customer_rfc="MES123456ABC",
    customer_name="Mi Empresa SA de CV",
    cfdi_uuid=str(uuid.uuid4()).upper(),
    cfdi_version="4.0",
    serie="P",
    folio="67890",
    fecha=datetime(2025, 3, 16, 11, 0, 0),
    subtotal="0.00",
    total="11600.00",
    moneda="MXN",
    tipo_de_comprobante="P",
    status=ProcessingStatus.VALIDATED,
    is_duplicate=False,
    original_xml='<?xml version="1.0"?><cfdi:Comprobante Version="4.0"></cfdi:Comprobante>',
    original_xml_hash=uuid.uuid4().hex
)
session.add(payment_mar)
print(f"\n✅ Created PAYMENT (March): {payment_mar.cfdi_uuid}")
print(f"   Amount: $11,600.00 MXN")
print(f"   Status: VALIDATED")
print(f"   Date: 2025-03-16")

# Create CREDIT_NOTE (March)
credit_note_mar = SATDocument(
    id=uuid.uuid4(),
    user_id=TEST_USER_ID,
    company_code="MX01",
    portal_reference_id=f"TEST-CN-MAR-{uuid.uuid4().hex[:8]}",
    document_type=DocumentType.CREDIT_NOTE,
    supplier_id="SUPP001",
    supplier_rfc="ABC123456789",
    supplier_name="Proveedores Industriales SA de CV",
    customer_rfc="MES123456ABC",
    customer_name="Mi Empresa SA de CV",
    cfdi_uuid=str(uuid.uuid4()).upper(),
    cfdi_version="4.0",
    serie="CN",
    folio="11111",
    fecha=datetime(2025, 3, 17, 14, 20, 0),
    subtotal="2000.00",
    total="2320.00",
    moneda="MXN",
    tipo_de_comprobante="E",
    status=ProcessingStatus.VALIDATED,
    is_duplicate=False,
    original_xml='<?xml version="1.0"?><cfdi:Comprobante Version="4.0"></cfdi:Comprobante>',
    original_xml_hash=uuid.uuid4().hex
)
session.add(credit_note_mar)
print(f"\n✅ Created CREDIT_NOTE (March): {credit_note_mar.cfdi_uuid}")
print(f"   Amount: $2,320.00 MXN")
print(f"   Status: VALIDATED")
print(f"   Date: 2025-03-17")

# ==================== DECEMBER 2025 DOCUMENTS ====================
print("\n\n📅 Creating December 2025 documents...")
print("-" * 70)

# Create INVOICE (December)
invoice_dec = SATDocument(
    id=uuid.uuid4(),
    user_id=TEST_USER_ID,
    company_code="MX01",
    portal_reference_id=f"TEST-INV-DEC-{uuid.uuid4().hex[:8]}",
    document_type=DocumentType.INVOICE,
    supplier_id="SUPP001",
    supplier_rfc="ABC123456789",
    supplier_name="Proveedores Industriales SA de CV",
    customer_rfc="MES123456ABC",
    customer_name="Mi Empresa SA de CV",
    cfdi_uuid=str(uuid.uuid4()).upper(),
    cfdi_version="4.0",
    serie="A",
    folio="99001",
    fecha=datetime(2025, 12, 10, 9, 15, 0),
    subtotal="25000.00",
    total="29000.00",
    moneda="MXN",
    tipo_de_comprobante="I",
    status=ProcessingStatus.VALIDATED,
    is_duplicate=False,
    original_xml='<?xml version="1.0"?><cfdi:Comprobante Version="4.0"></cfdi:Comprobante>',
    original_xml_hash=uuid.uuid4().hex
)
session.add(invoice_dec)
print(f"✅ Created INVOICE (December): {invoice_dec.cfdi_uuid}")
print(f"   Amount: $29,000.00 MXN")
print(f"   Status: VALIDATED")
print(f"   Date: 2025-12-10")

# Create PAYMENT (December)
payment_dec = SATDocument(
    id=uuid.uuid4(),
    user_id=TEST_USER_ID,
    company_code="MX01",
    portal_reference_id=f"TEST-PAY-DEC-{uuid.uuid4().hex[:8]}",
    document_type=DocumentType.PAYMENT,
    supplier_id="SUPP001",
    supplier_rfc="ABC123456789",
    supplier_name="Proveedores Industriales SA de CV",
    customer_rfc="MES123456ABC",
    customer_name="Mi Empresa SA de CV",
    cfdi_uuid=str(uuid.uuid4()).upper(),
    cfdi_version="4.0",
    serie="P",
    folio="99002",
    fecha=datetime(2025, 12, 15, 16, 45, 0),
    subtotal="0.00",
    total="29000.00",
    moneda="MXN",
    tipo_de_comprobante="P",
    status=ProcessingStatus.VALIDATED,
    is_duplicate=False,
    original_xml='<?xml version="1.0"?><cfdi:Comprobante Version="4.0"></cfdi:Comprobante>',
    original_xml_hash=uuid.uuid4().hex
)
session.add(payment_dec)
print(f"\n✅ Created PAYMENT (December): {payment_dec.cfdi_uuid}")
print(f"   Amount: $29,000.00 MXN")
print(f"   Status: VALIDATED")
print(f"   Date: 2025-12-15")

# Create CREDIT_NOTE (December)
credit_note_dec = SATDocument(
    id=uuid.uuid4(),
    user_id=TEST_USER_ID,
    company_code="MX01",
    portal_reference_id=f"TEST-CN-DEC-{uuid.uuid4().hex[:8]}",
    document_type=DocumentType.CREDIT_NOTE,
    supplier_id="SUPP001",
    supplier_rfc="ABC123456789",
    supplier_name="Proveedores Industriales SA de CV",
    customer_rfc="MES123456ABC",
    customer_name="Mi Empresa SA de CV",
    cfdi_uuid=str(uuid.uuid4()).upper(),
    cfdi_version="4.0",
    serie="CN",
    folio="99003",
    fecha=datetime(2025, 12, 20, 10, 30, 0),
    subtotal="5000.00",
    total="5800.00",
    moneda="MXN",
    tipo_de_comprobante="E",
    status=ProcessingStatus.VALIDATED,
    is_duplicate=False,
    original_xml='<?xml version="1.0"?><cfdi:Comprobante Version="4.0"></cfdi:Comprobante>',
    original_xml_hash=uuid.uuid4().hex
)
session.add(credit_note_dec)
print(f"\n✅ Created CREDIT_NOTE (December): {credit_note_dec.cfdi_uuid}")
print(f"   Amount: $5,800.00 MXN")
print(f"   Status: VALIDATED")
print(f"   Date: 2025-12-20")

# Commit all
session.commit()

print("\n" + "=" * 70)
print("✅ All test documents created successfully!")
print("=" * 70 + "\n")

print("📋 Summary:")
print(f"   User ID: {TEST_USER_ID}")
print(f"   Company: MX01")
print(f"   Vendor: ABC123456789")
print(f"   Total Documents: 6")
print()
print("   Period 1: 2025-03 (March)")
print("      - 3 documents (INVOICE, PAYMENT, CREDIT_NOTE)")
print("      - Total Amount: $11,600.00 - $11,600.00 - $2,320.00 = -$2,320.00")
print()
print("   Period 2: 2025-12 (December)")
print("      - 3 documents (INVOICE, PAYMENT, CREDIT_NOTE)")
print("      - Total Amount: $29,000.00 - $29,000.00 - $5,800.00 = -$5,800.00")
print()
print("   Status: VALIDATED (ready to merge)")
print()
print("🔄 Next Steps:")
print("   1. Go to http://localhost:3000/sat-documents")
print("   2. Click 'Canonical Merged' tab")
print()
print("   Test March 2025:")
print("      - Select Year: 2025, Period: 3")
print("      - You should see 3 documents preview")
print("      - Click 'Generate Canonical'")
print()
print("   Test December 2025:")
print("      - Select Year: 2025, Period: 12")
print("      - You should see 3 documents preview")
print("      - Click 'Generate Canonical'")
print()

session.close()

