"""
Script to completely clean up all Invoice V2 data (ALL USERS)
Removes: Documents, Validated Invoices, Converted Invoices, BI Data, Files
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from app.database import DATABASE_URL

def cleanup_all_invoice_v2_data():
    """Remove all Invoice V2 related data from database and file system"""
    
    print("=" * 70)
    print("CLEANUP: Remove All Invoice V2 Data (ALL USERS)")
    print("=" * 70)
    print("\nThis will DELETE:")
    print("  - All Invoice V2 Documents (ALL USERS)")
    print("  - All Validated Invoices (Successful + Failed)")
    print("  - All Converted Invoices")
    print("  - All Business Intelligence Data")
    print("  - All uploaded XML files")
    print("  - All converted files")
    print("\n⚠️  WARNING: THIS CANNOT BE UNDONE! ⚠️")
    print("=" * 70)
    
    # Ask for confirmation
    response = input("\nType 'DELETE ALL' to confirm: ")
    if response != 'DELETE ALL':
        print("\n❌ Cleanup cancelled.")
        return
    
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        try:
            print("\n🔍 Checking current data...")
            
            # Count records
            docs_count = conn.execute(text("SELECT COUNT(*) FROM v2_invoice_documents")).scalar() or 0
            validated_count = conn.execute(text("SELECT COUNT(*) FROM v2_validated_invoices")).scalar() or 0
            
            try:
                converted_count = conn.execute(text("SELECT COUNT(*) FROM converted_invoices")).scalar() or 0
            except:
                converted_count = 0
            
            try:
                bi_count = conn.execute(text("SELECT COUNT(*) FROM invoice_v2_business_data")).scalar() or 0
            except:
                bi_count = 0
            
            print(f"\n📊 Current Data:")
            print(f"   Documents: {docs_count}")
            print(f"   Validated Invoices: {validated_count}")
            print(f"   Converted Invoices: {converted_count}")
            print(f"   BI Records: {bi_count}")
            
            if docs_count == 0 and validated_count == 0:
                print("\n✅ No data to clean up!")
                return
            
            # Final confirmation
            response2 = input(f"\n⚠️  Proceed to delete {docs_count + validated_count + converted_count + bi_count} total records? (yes/no): ")
            if response2.lower() != 'yes':
                print("\n❌ Cleanup cancelled.")
                return
            
            print("\n🗑️  Starting cleanup...")
            
            # Step 1: Delete Business Intelligence Data
            if bi_count > 0:
                print("\n1. Deleting Business Intelligence data...")
                conn.execute(text("DELETE FROM invoice_v2_business_data"))
                conn.commit()
                print(f"   ✅ Deleted {bi_count} BI records")
            else:
                print("\n1. No BI data to delete")
            
            # Step 2: Delete Converted Invoices
            if converted_count > 0:
                print("\n2. Deleting Converted Invoices...")
                conn.execute(text("DELETE FROM converted_invoices"))
                conn.commit()
                print(f"   ✅ Deleted {converted_count} converted invoices")
            else:
                print("\n2. No converted invoices to delete")
            
            # Step 3: Delete Validated Invoices
            if validated_count > 0:
                print("\n3. Deleting Validated Invoices...")
                conn.execute(text("DELETE FROM v2_validated_invoices"))
                conn.commit()
                print(f"   ✅ Deleted {validated_count} validated invoices")
            else:
                print("\n3. No validated invoices to delete")
            
            # Step 4: Delete Documents
            if docs_count > 0:
                print("\n4. Deleting Documents...")
                conn.execute(text("DELETE FROM v2_invoice_documents"))
                conn.commit()
                print(f"   ✅ Deleted {docs_count} documents")
            else:
                print("\n4. No documents to delete")
            
            # Step 5: Clean up file system
            print("\n5. Cleaning up file system...")
            cleanup_count = 0
            
            # Clean uploads directory
            uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
            if os.path.exists(uploads_dir):
                try:
                    for filename in os.listdir(uploads_dir):
                        # Delete Invoice V2 and conversion related files
                        if any(x in filename.lower() for x in ['sap_', 'snippet', 'converted_', '.xml', '.edi', '.x12', '.pdf']):
                            try:
                                file_path = os.path.join(uploads_dir, filename)
                                if os.path.isfile(file_path):
                                    os.remove(file_path)
                                    cleanup_count += 1
                            except Exception as e:
                                print(f"   ⚠️  Could not delete {filename}: {e}")
                except Exception as e:
                    print(f"   ⚠️  Could not access uploads directory: {e}")
            
            print(f"   ✅ Cleaned up {cleanup_count} files from uploads directory")
            
            # Note about blob storage
            print("\n   ℹ️  Note: Files in Vercel Blob Storage (if any) are not deleted by this script.")
            
            # Verify cleanup
            print("\n6. Verifying cleanup...")
            docs_after = conn.execute(text("SELECT COUNT(*) FROM v2_invoice_documents")).scalar() or 0
            validated_after = conn.execute(text("SELECT COUNT(*) FROM v2_validated_invoices")).scalar() or 0
            
            try:
                converted_after = conn.execute(text("SELECT COUNT(*) FROM converted_invoices")).scalar() or 0
            except:
                converted_after = 0
            
            try:
                bi_after = conn.execute(text("SELECT COUNT(*) FROM invoice_v2_business_data")).scalar() or 0
            except:
                bi_after = 0
            
            print(f"\n📊 Remaining Data:")
            print(f"   Documents: {docs_after}")
            print(f"   Validated Invoices: {validated_after}")
            print(f"   Converted Invoices: {converted_after}")
            print(f"   BI Records: {bi_after}")
            
            if docs_after == 0 and validated_after == 0 and converted_after == 0 and bi_after == 0:
                print("\n" + "=" * 70)
                print("✅ CLEANUP COMPLETED SUCCESSFULLY!")
                print("=" * 70)
                print(f"\nDeleted:")
                print(f"  • {docs_count} documents")
                print(f"  • {validated_count} validated invoices")
                print(f"  • {converted_count} converted invoices")
                print(f"  • {bi_count} BI records")
                print(f"  • {cleanup_count} files")
                print("\n💡 Invoice V2 is now completely clean. You can start fresh!")
            else:
                print("\n⚠️  Some records may remain. Check database manually.")
            
        except Exception as e:
            print(f"\n❌ Error during cleanup: {e}")
            import traceback
            traceback.print_exc()
            conn.rollback()
            sys.exit(1)

if __name__ == "__main__":
    cleanup_all_invoice_v2_data()
