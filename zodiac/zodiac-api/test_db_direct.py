#!/usr/bin/env python3
"""
Direct database test to check processing_steps_error field using the new consolidated migration system
"""
import os
import sys
from dotenv import load_dotenv

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database_init import get_database_status, DatabaseInitializer

load_dotenv()

def test_database_migrations():
    """Test the consolidated database migration system"""
    print("🔍 Testing Database Migration System")
    print("=" * 50)
    
    try:
        # Get migration status
        print("📊 Getting database migration status...")
        status = get_database_status()
        
        print("\n📋 Migration Status:")
        print(f"  Deleted At Columns:")
        print(f"    Success Table: {status['deleted_at_columns']['zodiac_invoice_success_edi']}")
        print(f"    Failed Table: {status['deleted_at_columns']['zodiac_invoice_failed_edi']}")
        
        print(f"  Processing Steps Columns:")
        print(f"    Success Table: {status['processing_steps_columns']['zodiac_invoice_success_edi']}")
        print(f"    Failed Table: {status['processing_steps_columns']['zodiac_invoice_failed_edi']}")
        
        print(f"  Indexes:")
        print(f"    Deleted At Indexes: {all(status['indexes']['deleted_at_indexes'])}")
        print(f"    Processing Steps Indexes: {all(status['indexes']['processing_steps_indexes'])}")
        
        # Check if all migrations are complete
        all_complete = (
            all(status['deleted_at_columns'].values()) and
            all(status['processing_steps_columns'].values()) and
            all(status['indexes']['deleted_at_indexes']) and
            all(status['indexes']['processing_steps_indexes'])
        )
        
        if all_complete:
            print("\n✅ All migrations are complete!")
            return True
        else:
            print("\n⚠️ Some migrations are incomplete")
            return False
            
    except Exception as e:
        print(f"\n❌ Error testing migrations: {e}")
        return False

if __name__ == "__main__":
    success = test_database_migrations()
    sys.exit(0 if success else 1)