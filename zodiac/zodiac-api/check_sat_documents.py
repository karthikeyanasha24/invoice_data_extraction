"""
Quick script to check what SAT documents exist in the database
"""
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

engine = create_engine(DATABASE_URL)

print("\n" + "=" * 70)
print("📊 SAT Documents in Database")
print("=" * 70 + "\n")

with engine.connect() as conn:
    # Check total documents
    result = conn.execute(text("SELECT COUNT(*) as count FROM sat_documents"))
    total = result.fetchone()[0]
    print(f"Total SAT Documents: {total}\n")
    
    if total > 0:
        # Show document details
        result = conn.execute(text("""
            SELECT 
                id,
                user_id,
                company_code,
                document_type,
                supplier_rfc,
                supplier_name,
                fecha,
                EXTRACT(YEAR FROM fecha) as year,
                EXTRACT(MONTH FROM fecha) as month,
                total,
                status,
                is_duplicate,
                cfdi_uuid
            FROM sat_documents
            ORDER BY fecha DESC
            LIMIT 20
        """))
        
        print("Recent Documents:")
        print("-" * 170)
        print(f"{'UserID':<8} {'Co':<5} {'Type':<15} {'RFC':<15} {'Date':<12} {'Yr':<5} {'Mo':<4} {'Total':<12} {'Status':<15} {'Dup':<4} {'UUID':<40}")
        print("-" * 170)
        
        for row in result:
            is_dup = "YES" if row[11] else "NO"
            print(f"{row[1]:<8} {row[2]:<5} {row[3]:<15} {row[4]:<15} {str(row[6])[:10]:<12} {int(row[7]):<5} {int(row[8]):<4} ${row[9] or 0:<11} {row[10]:<15} {is_dup:<4} {row[12][:36] if row[12] else 'N/A':<40}")
        
        # Show grouping by period
        print("\n" + "=" * 70)
        print("📅 Documents by Period (Year-Month)")
        print("=" * 70 + "\n")
        
        result = conn.execute(text("""
            SELECT 
                EXTRACT(YEAR FROM fecha) as year,
                EXTRACT(MONTH FROM fecha) as month,
                document_type,
                COUNT(*) as count,
                supplier_rfc
            FROM sat_documents
            GROUP BY EXTRACT(YEAR FROM fecha), EXTRACT(MONTH FROM fecha), document_type, supplier_rfc
            ORDER BY year DESC, month DESC, supplier_rfc
        """))
        
        print(f"{'Year':<6} {'Month':<6} {'Type':<15} {'RFC':<15} {'Count':<6}")
        print("-" * 70)
        for row in result:
            print(f"{int(row[0]):<6} {int(row[1]):<6} {row[2]:<15} {row[4]:<15} {row[3]:<6}")
        
        # Show what would be merged for period 2025-03
        print("\n" + "=" * 70)
        print("🔍 Checking Merge Eligibility for 2025-03")
        print("=" * 70 + "\n")
        
        result = conn.execute(text("""
            SELECT 
                user_id,
                company_code,
                document_type,
                supplier_rfc,
                status,
                is_duplicate,
                EXTRACT(YEAR FROM fecha) as year,
                EXTRACT(MONTH FROM fecha) as month
            FROM sat_documents
            WHERE EXTRACT(YEAR FROM fecha) = 2025
              AND EXTRACT(MONTH FROM fecha) = 3
        """))
        
        print("Documents in 2025-03:")
        print(f"{'UserID':<8} {'Co':<5} {'Type':<15} {'RFC':<15} {'Status':<15} {'Duplicate':<10} {'Mergeable?':<12}")
        print("-" * 100)
        
        for row in result:
            user_id, company_code, doc_type, rfc, status, is_dup, year, month = row
            is_dup_str = "YES" if is_dup else "NO"
            
            # Check merge criteria
            valid_status = status in ['VALIDATED', 'NORMALIZED', 'ENRICHING', 'READY_FOR_SAP', 'SENT_TO_SAP', 'SAP_CONFIRMED']
            not_duplicate = not is_dup
            mergeable = "✅ YES" if (valid_status and not_duplicate) else "❌ NO"
            
            if not valid_status:
                mergeable += f" (status={status})"
            if is_dup:
                mergeable += " (duplicate)"
            
            print(f"{user_id:<8} {company_code:<5} {doc_type:<15} {rfc:<15} {status:<15} {is_dup_str:<10} {mergeable:<12}")
    else:
        print("⚠️  No documents found in database!")
        print("\nRun this to add test documents:")
        print("  python test_supplier_send.py")

print("\n" + "=" * 70 + "\n")

