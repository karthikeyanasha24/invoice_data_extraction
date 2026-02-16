"""
Script to clean up Invoice V2 data for a specific user
Safer option that only removes data for one user
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from app.database import DATABASE_URL

def cleanup_invoice_v2_by_user():
    """Remove Invoice V2 data for a specific user"""
    
    print("=" * 70)
    print("CLEANUP: Remove Invoice V2 Data by User")
    print("=" * 70)
    
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # List all users with Invoice V2 data
        print("\n📋 Users with Invoice V2 data:")
        
        users = conn.execute(text("""
            SELECT DISTINCT u.id, u.email, COUNT(d.id) as doc_count
            FROM zodiac_users u
            JOIN v2_invoice_documents d ON d.user_id = u.id
            GROUP BY u.id, u.email
            ORDER BY u.id
        """)).fetchall()
        
        if not users:
            print("   No users with Invoice V2 data found.")
            return
        
        for user_id, email, doc_count in users:
            print(f"   {user_id}. {email} ({doc_count} documents)")
        
        # Ask which user to clean
        user_input = input("\nEnter user ID to clean (or 'all' for all users, 'cancel' to abort): ")
        
        if user_input.lower() == 'cancel':
            print("\n❌ Cleanup cancelled.")
            return
        
        if user_input.lower() == 'all':
            user_id = None
            confirm_text = "DELETE ALL USERS DATA"
        else:
            try:
                user_id = int(user_input)
                # Verify user exists
                user_email = conn.execute(
                    text("SELECT email FROM zodiac_users WHERE id = :id"),
                    {"id": user_id}
                ).scalar()
                
                if not user_email:
                    print(f"\n❌ User ID {user_id} not found.")
                    return
                
                confirm_text = f"DELETE USER {user_id}"
                print(f"\nSelected user: {user_email}")
            except ValueError:
                print("\n❌ Invalid user ID.")
                return
        
        # Count records for this user
        if user_id:
            docs_count = conn.execute(
                text("SELECT COUNT(*) FROM v2_invoice_documents WHERE user_id = :id"),
                {"id": user_id}
            ).scalar() or 0
            
            validated_count = conn.execute(text("""
                SELECT COUNT(*) FROM v2_validated_invoices v
                JOIN v2_invoice_documents d ON v.document_id = d.id
                WHERE d.user_id = :id
            """), {"id": user_id}).scalar() or 0
            
            try:
                bi_count = conn.execute(
                    text("SELECT COUNT(*) FROM invoice_v2_business_data WHERE user_id = :id"),
                    {"id": user_id}
                ).scalar() or 0
            except:
                bi_count = 0
        else:
            docs_count = conn.execute(text("SELECT COUNT(*) FROM v2_invoice_documents")).scalar() or 0
            validated_count = conn.execute(text("SELECT COUNT(*) FROM v2_validated_invoices")).scalar() or 0
            try:
                bi_count = conn.execute(text("SELECT COUNT(*) FROM invoice_v2_business_data")).scalar() or 0
            except:
                bi_count = 0
        
        print(f"\n📊 Data to delete:")
        print(f"   Documents: {docs_count}")
        print(f"   Validated Invoices: {validated_count}")
        print(f"   BI Records: {bi_count}")
        
        if docs_count == 0:
            print("\n✅ No data to clean up!")
            return
        
        # Confirmation
        response = input(f"\n⚠️  Type '{confirm_text}' to confirm: ")
        if response != confirm_text:
            print("\n❌ Cleanup cancelled.")
            return
        
        try:
            print("\n🗑️  Starting cleanup...")
            
            # Delete BI data
            if user_id:
                conn.execute(
                    text("DELETE FROM invoice_v2_business_data WHERE user_id = :id"),
                    {"id": user_id}
                )
            else:
                conn.execute(text("DELETE FROM invoice_v2_business_data"))
            conn.commit()
            print(f"   ✅ Deleted {bi_count} BI records")
            
            # Delete validated invoices
            if user_id:
                conn.execute(text("""
                    DELETE FROM v2_validated_invoices
                    WHERE document_id IN (
                        SELECT id FROM v2_invoice_documents WHERE user_id = :id
                    )
                """), {"id": user_id})
            else:
                conn.execute(text("DELETE FROM v2_validated_invoices"))
            conn.commit()
            print(f"   ✅ Deleted {validated_count} validated invoices")
            
            # Delete documents
            if user_id:
                conn.execute(
                    text("DELETE FROM v2_invoice_documents WHERE user_id = :id"),
                    {"id": user_id}
                )
            else:
                conn.execute(text("DELETE FROM v2_invoice_documents"))
            conn.commit()
            print(f"   ✅ Deleted {docs_count} documents")
            
            print("\n" + "=" * 70)
            print("✅ CLEANUP COMPLETED!")
            print("=" * 70)
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            conn.rollback()
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    cleanup_invoice_v2_by_user()
