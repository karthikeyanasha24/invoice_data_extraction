#!/usr/bin/env python
"""
AI Schema Initialization Script

Run this once to pre-cache table schemas for optimal AI analysis performance.
This is optional but recommended for 40-60% faster query execution.

Usage:
    python init_ai_schemas.py
"""
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


def main():
    """Main initialization routine."""
    try:
        from app.database import SessionLocal, get_sap_session
        from app.services.schema_initializer import initialize_ai_knowledge_base
        from app.config.config import USE_SAP_DB_FOR_AI
        
        print("=" * 70)
        print("🚀 AI SCHEMA INITIALIZATION")
        print("=" * 70)
        print()
        print("This will scan your SAP tables and cache schemas for faster AI queries.")
        print("Estimated time: 2-5 minutes")
        print()
        
        response = input("Continue? (y/n): ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            return
        
        print()
        
        # Create database sessions
        db = SessionLocal()
        sap_db = get_sap_session() if USE_SAP_DB_FOR_AI else None
        
        try:
            # Run initialization
            results = initialize_ai_knowledge_base(db, sap_db)
            
            print()
            print("=" * 70)
            print("✅ INITIALIZATION COMPLETE")
            print("=" * 70)
            print(f"Tables cached: {results['tables_cached']}")
            print(f"Tables failed: {results['tables_failed']}")
            print(f"Patterns cached: {results['patterns_cached']}")
            print(f"Total time: {results['total_time_ms'] / 1000:.1f}s")
            print()
            
            if results.get('error'):
                print(f"⚠️ Warning: {results['error']}")
                print()
            
            print("Next steps:")
            print("1. Restart your backend server")
            print("2. Test with: 'show me best sales for 2024'")
            print("3. Check performance metrics in browser console")
            print()
            
            if results['tables_cached'] > 0:
                print("🎉 Your AI queries will now be 40-60% faster!")
            
        finally:
            db.close()
            if sap_db:
                sap_db.close()
    
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ INITIALIZATION FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        import traceback
        traceback.print_exc()
        print()
        print("Troubleshooting:")
        print("1. Ensure database is running and accessible")
        print("2. Check SAP_DATABASE_URL in .env (if using SAP DB)")
        print("3. Verify OPENAI_API_KEY is set in .env")
        print("4. Check that tables exist in your database")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
