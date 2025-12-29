#!/usr/bin/env python3
"""
Migration script to create SAT document tables
Run this to add tables for Mexican SAT document processing
"""
import sys
import os

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import Base, engine
from app.models.sat_document import (
    SATDocument, 
    SATProcessingLog, 
    SATDuplicateCheck, 
    SATCompanyMapping
)

def run_migration():
    """Create SAT document tables"""
    print("=" * 70)
    print("SAT Documents Migration")
    print("=" * 70)
    print()
    
    print("📊 Creating SAT document tables...")
    print()
    
    try:
        # Create all SAT-related tables
        Base.metadata.create_all(
            bind=engine,
            tables=[
                SATDocument.__table__,
                SATProcessingLog.__table__,
                SATDuplicateCheck.__table__,
                SATCompanyMapping.__table__
            ]
        )
        
        print("✅ Successfully created tables:")
        print("   - sat_documents")
        print("   - sat_processing_logs")
        print("   - sat_duplicate_checks")
        print("   - sat_company_mappings")
        print()
        print("=" * 70)
        print("✅ Migration Complete!")
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_migration()

