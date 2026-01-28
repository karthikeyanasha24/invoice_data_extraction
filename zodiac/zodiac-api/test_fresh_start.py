"""
Fresh Start Testing Script
Resets SAT documents and uploads fresh test data in one command.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import subprocess

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Run complete fresh start test"""
    
    logger.info("=" * 60)
    logger.info("🚀 FRESH START TESTING")
    logger.info("=" * 60)
    
    # Step 1: Reset
    logger.info("\n📋 STEP 1: Reset existing data")
    logger.info("-" * 60)
    response = input("❓ Delete all SAT documents and merges? (yes/no): ")
    
    if response.lower() not in ['yes', 'y']:
        logger.info("❌ Operation cancelled. Using existing data.")
    else:
        logger.info("🔄 Running reset script...")
        try:
            # Import and run reset function
            from reset_sat_documents import reset_sat_data
            # Skip the confirmation prompt inside reset_sat_data
            import builtins
            original_input = builtins.input
            builtins.input = lambda _: 'yes'
            reset_sat_data()
            builtins.input = original_input
            logger.info("✅ Reset complete!")
        except Exception as e:
            logger.error(f"❌ Reset failed: {e}")
            return
    
    # Step 2: Upload documents
    logger.info("\n📋 STEP 2: Upload test documents")
    logger.info("-" * 60)
    logger.info("🔄 Running upload script...")
    try:
        # Import and run upload function
        from test_upload_only import main as upload_main
        upload_main()
        logger.info("✅ Upload complete!")
    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        return
    
    # Step 3: Next steps
    logger.info("\n" + "=" * 60)
    logger.info("✅ FRESH START COMPLETE!")
    logger.info("=" * 60)
    logger.info("\n📋 NEXT STEPS:")
    logger.info("   1. Go to frontend: http://localhost:3000/sat-documents")
    logger.info("   2. Create Simple Merge:")
    logger.info("      - Tab: 'Simple Merged'")
    logger.info("      - Click 'Create Simple Merge'")
    logger.info("      - Select period and RFC")
    logger.info("   3. Create Canonical Merge:")
    logger.info("      - Tab: 'Canonical Merged'")
    logger.info("      - Click 'Create Canonical Merge'")
    logger.info("      - Same period and RFC")
    logger.info("   4. Preview JSON format:")
    logger.info("      - Tab: 'Send to SAP'")
    logger.info("      - Check JSON preview")
    logger.info("   5. Send to SAP:")
    logger.info("      - Click 'Send All to SAP' button")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()

