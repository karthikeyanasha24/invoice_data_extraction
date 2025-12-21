#!/usr/bin/env python3
"""
Script to check for invoices pushed from backend ERP (vs web uploads)
"""
import os
import sys
from sqlalchemy import create_engine, text
from datetime import datetime

# Update with your database credentials
DATABASE_URL = "postgresql://postgres:Test.1234!@localhost:5432/mydatabase"
engine = create_engine(DATABASE_URL)

def check_invoices_by_source():
    """Check invoices grouped by request source (web vs api)"""
    print("=" * 70)
    print("📊 INVOICE SOURCE ANALYSIS")
    print("=" * 70)
    
    try:
        with engine.connect() as conn:
            # Count by source type
            result = conn.execute(text("""
                SELECT 
                    'Success' as table_name,
                    request_type,
                    COUNT(*) as count,
                    MAX(uploaded_at) as latest_upload
                FROM zodiac_invoice_success_edi
                WHERE deleted_at IS NULL
                GROUP BY request_type
                
                UNION ALL
                
                SELECT 
                    'Failed' as table_name,
                    request_type,
                    COUNT(*) as count,
                    MAX(uploaded_at) as latest_upload
                FROM zodiac_invoice_failed_edi
                WHERE deleted_at IS NULL
                GROUP BY request_type
                
                ORDER BY table_name, request_type
            """))
            
            rows = result.fetchall()
            
            if not rows:
                print("\n❌ No invoices found in database!")
                return
            
            print("\n📈 INVOICE COUNTS BY SOURCE:\n")
            total_web = 0
            total_api = 0
            
            for row in rows:
                table = row.table_name
                source = row.request_type
                count = row.count
                latest = row.latest_upload.strftime('%Y-%m-%d %H:%M:%S') if row.latest_upload else 'N/A'
                
                icon = "🌐" if source == 'web' else "🔌"
                print(f"{icon} {table:8} | {source.upper():4} | Count: {count:4} | Latest: {latest}")
                
                if source == 'web':
                    total_web += count
                elif source == 'api':
                    total_api += count
            
            print("\n" + "-" * 70)
            print(f"📊 TOTALS:")
            print(f"   🌐 Web Uploads:     {total_web}")
            print(f"   🔌 API/ERP Pushes: {total_api}")
            print(f"   📦 Total Invoices:  {total_web + total_api}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print(f"   Make sure your DATABASE_URL is correct in line 9")

def show_recent_api_invoices():
    """Show recent invoices pushed from backend/ERP"""
    print("\n" + "=" * 70)
    print("🔌 RECENT BACKEND/ERP INVOICES (request_type = 'api')")
    print("=" * 70)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    'Success' as status,
                    id,
                    tracking_id,
                    uploaded_at,
                    xml_path,
                    target_file_format,
                    request_type
                FROM zodiac_invoice_success_edi
                WHERE request_type = 'api' AND deleted_at IS NULL
                
                UNION ALL
                
                SELECT 
                    'Failed' as status,
                    id,
                    tracking_id,
                    uploaded_at,
                    xml_path,
                    target_file_format,
                    request_type
                FROM zodiac_invoice_failed_edi
                WHERE request_type = 'api' AND deleted_at IS NULL
                
                ORDER BY uploaded_at DESC
                LIMIT 10
            """))
            
            rows = result.fetchall()
            
            if not rows:
                print("\n❌ No backend/ERP invoices found!")
                print("   This means the ERP has NOT successfully pushed any invoices.")
                print("\n💡 TROUBLESHOOTING:")
                print("   1. Check if ERP is using correct endpoint: /api/v1/invoices/api/process")
                print("   2. Verify API key is included in request headers")
                print("   3. Check ERP logs for API call responses")
                return
            
            print(f"\n✅ Found {len(rows)} backend/ERP invoices:\n")
            
            for row in rows:
                status_icon = "✅" if row.status == 'Success' else "❌"
                print(f"{status_icon} {row.status:7} | ID: {row.id:4} | {row.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Tracking: {row.tracking_id}")
                print(f"   Format:   {row.target_file_format or 'N/A'}")
                print(f"   File:     {row.xml_path}")
                print("-" * 70)
                
    except Exception as e:
        print(f"\n❌ Error: {e}")

def show_recent_web_invoices():
    """Show recent invoices uploaded via web interface"""
    print("\n" + "=" * 70)
    print("🌐 RECENT WEB UPLOADS (request_type = 'web')")
    print("=" * 70)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    'Success' as status,
                    id,
                    tracking_id,
                    uploaded_at,
                    xml_path,
                    target_file_format
                FROM zodiac_invoice_success_edi
                WHERE request_type = 'web' AND deleted_at IS NULL
                
                UNION ALL
                
                SELECT 
                    'Failed' as status,
                    id,
                    tracking_id,
                    uploaded_at,
                    xml_path,
                    target_file_format
                FROM zodiac_invoice_failed_edi
                WHERE request_type = 'web' AND deleted_at IS NULL
                
                ORDER BY uploaded_at DESC
                LIMIT 5
            """))
            
            rows = result.fetchall()
            
            if not rows:
                print("\n❌ No web uploads found!")
                return
            
            print(f"\n✅ Found {len(rows)} web uploads (showing last 5):\n")
            
            for row in rows:
                status_icon = "✅" if row.status == 'Success' else "❌"
                print(f"{status_icon} {row.status:7} | ID: {row.id:4} | {row.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Tracking: {row.tracking_id}")
                print(f"   Format:   {row.target_file_format or 'N/A'}")
                print("-" * 70)
                
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    print("\n" + "🔍 CHECKING FOR BACKEND ERP INVOICES...\n")
    
    # First check overall counts
    check_invoices_by_source()
    
    # Then show recent API invoices
    show_recent_api_invoices()
    
    # Show recent web uploads for comparison
    show_recent_web_invoices()
    
    print("\n" + "=" * 70)
    print("✅ CHECK COMPLETE")
    print("=" * 70)
    print()

