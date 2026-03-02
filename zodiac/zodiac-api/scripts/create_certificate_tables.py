"""
Create certificate management tables.
Run this script to initialize the certificate lifecycle management database schema.

Usage:
    python scripts/create_certificate_tables.py
"""
import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine, ensure_columns_exist
from app.models.customer_certificate import CustomerCertificate
from app.models.certificate_renewal_request import CertificateRenewalRequest
from app.models.certificate_revocation import CertificateRevocation


def create_certificate_tables():
    """Create all certificate-related tables"""
    print("=" * 60)
    print("Creating Certificate Management Tables")
    print("=" * 60)
    
    try:
        # Create all tables
        print("\n1. Creating tables from models...")
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created/verified successfully")
        
        # Ensure all columns exist
        print("\n2. Ensuring all columns exist...")
        ensure_columns_exist()
        
        print("\n" + "=" * 60)
        print("✅ Certificate tables initialized successfully!")
        print("=" * 60)
        print("\nTables created:")
        print("  - customer_certificates")
        print("  - certificate_renewal_requests")
        print("  - certificate_revocation_list")
        print("\nYou can now use the certificate management APIs.")
        
        return True
    except Exception as e:
        print(f"\n❌ Error creating certificate tables: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = create_certificate_tables()
    sys.exit(0 if success else 1)
