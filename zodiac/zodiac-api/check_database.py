"""
Check what's actually in the database
"""
import sys
sys.path.append('.')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.sat_document import SATDocument
import os
from dotenv import load_dotenv

load_dotenv()

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

print("="*70)
print("🔍 Checking SAT Documents in Database")
print("="*70)

try:
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Get latest documents
    documents = session.query(SATDocument).order_by(SATDocument.created_at.desc()).limit(3).all()
    
    print(f"\n✅ Found {len(documents)} recent documents\n")
    
    for i, doc in enumerate(documents, 1):
        print(f"{'='*70}")
        print(f"Document {i}: {doc.portal_reference_id}")
        print(f"{'='*70}")
        print(f"📄 Type: {doc.document_type}")
        print(f"📊 Status: {doc.status}")
        print(f"\n🔷 CFDI Information:")
        print(f"  cfdi_version: {doc.cfdi_version}")
        print(f"  serie: {doc.serie}")
        print(f"  folio: {doc.folio}")
        print(f"  fecha: {doc.fecha}")
        print(f"  tipo_de_comprobante: {doc.tipo_de_comprobante}")
        print(f"  cfdi_uuid: {doc.cfdi_uuid}")
        
        print(f"\n💰 Financial:")
        print(f"  subtotal: {doc.subtotal}")
        print(f"  total: {doc.total}")
        print(f"  moneda: {doc.moneda}")
        
        print(f"\n🏢 Supplier:")
        print(f"  supplier_id: {doc.supplier_id}")
        print(f"  supplier_name: {doc.supplier_name}")
        print(f"  supplier_rfc: {doc.supplier_rfc}")
        
        print(f"\n👤 Customer:")
        print(f"  customer_name: {doc.customer_name}")
        print(f"  customer_rfc: {doc.customer_rfc}")
        
        print(f"\n✅ SAP:")
        print(f"  sap_document_number: {doc.sap_document_number}")
        print(f"  sap_fiscal_year: {doc.sap_fiscal_year}")
        print()
    
    session.close()
    
except Exception as e:
    print(f"\n❌ Error checking database: {e}")
    import traceback
    traceback.print_exc()

