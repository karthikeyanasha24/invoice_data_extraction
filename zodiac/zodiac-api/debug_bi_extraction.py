#!/usr/bin/env python3
"""
Debug Business Intelligence Extraction

Check what data is being extracted from invoices
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.invoice import ZodiacInvoiceSuccessEdi
from app.models.invoice_business_data import InvoiceBusinessData
from app.services.business_intelligence_service import business_intelligence_extractor
from app.services.file_service import read_file_from_storage
import json

def debug_bi_extraction():
    """Check BI extraction for sample invoices"""
    
    print("=" * 70)
    print("Debug Business Intelligence Extraction")
    print("=" * 70)
    print()
    
    db = SessionLocal()
    
    try:
        # Get a few sample invoices
        print("📊 Fetching sample invoices...")
        invoices = db.query(ZodiacInvoiceSuccessEdi).limit(5).all()
        
        if not invoices:
            print("❌ No invoices found in database")
            return
        
        print(f"Found {len(invoices)} sample invoices\n")
        
        for idx, invoice in enumerate(invoices, 1):
            print(f"\n{'=' * 70}")
            print(f"INVOICE {idx}: ID={invoice.id}, Tracking ID={invoice.tracking_id}")
            print(f"{'=' * 70}")
            print(f"XML Path: {invoice.xml_path}")
            print(f"User ID: {invoice.user_id}")
            print()
            
            # Try to read XML file
            if not invoice.xml_path:
                print("⚠️ No XML path found for this invoice")
                continue
            
            try:
                xml_content = read_file_from_storage(invoice.xml_path)
                if not xml_content:
                    print(f"❌ Could not read XML file: {invoice.xml_path}")
                    continue
                
                print(f"✅ XML file read successfully ({len(xml_content)} bytes)")
                print()
                
                # Extract BI data
                print("🔍 Extracting business intelligence data...")
                bi_data = business_intelligence_extractor.extract_from_xml(xml_content)
                
                # Display extracted data
                print("\n📋 EXTRACTED DATA:")
                print("-" * 70)
                
                print(f"\n👤 CUSTOMER:")
                print(f"  ID: {bi_data.get('customer_id')}")
                print(f"  Name: {bi_data.get('customer_name')}")
                print(f"  Country: {bi_data.get('customer_country')}")
                print(f"  City: {bi_data.get('customer_city')}")
                
                print(f"\n🏢 SUPPLIER:")
                print(f"  ID: {bi_data.get('supplier_id')}")
                print(f"  Name: {bi_data.get('supplier_name')}")
                print(f"  Country: {bi_data.get('supplier_country')}")
                
                print(f"\n📦 PRODUCTS:")
                products = bi_data.get('products', [])
                if products:
                    for i, product in enumerate(products[:3], 1):  # Show first 3
                        print(f"  {i}. {product.get('name')} - Qty: {product.get('quantity')} - Price: ${product.get('unit_price')}")
                    if len(products) > 3:
                        print(f"  ... and {len(products) - 3} more products")
                else:
                    print("  ⚠️ No products extracted")
                
                print(f"\n🏭 INDUSTRY:")
                print(f"  Classification: {bi_data.get('industry')}")
                print(f"  Confidence: {bi_data.get('industry_confidence')}")
                if bi_data.get('industry_keywords_matched'):
                    print(f"  Keywords: {', '.join(bi_data.get('industry_keywords_matched', [])[:5])}")
                
                print(f"\n💰 FINANCIAL:")
                print(f"  Invoice Number: {bi_data.get('invoice_number')}")
                print(f"  Total Amount: ${bi_data.get('total_amount')}")
                print(f"  Currency: {bi_data.get('currency')}")
                
            except Exception as e:
                print(f"❌ Error extracting BI data: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # Check what's in the BI table
        print(f"\n\n{'=' * 70}")
        print("BI TABLE STATUS")
        print(f"{'=' * 70}")
        
        bi_records = db.query(InvoiceBusinessData).limit(5).all()
        print(f"\nFound {len(bi_records)} records in invoice_business_data table")
        
        if bi_records:
            print("\nSample records:")
            for record in bi_records:
                print(f"\n  Record ID: {record.id}")
                print(f"    Customer: {record.customer_name} ({record.customer_id})")
                print(f"    Supplier: {record.supplier_name}")
                print(f"    Industry: {record.industry}")
                print(f"    Products: {record.product_count} products")
                print(f"    Total Amount: ${record.total_amount}")
        else:
            print("⚠️ BI table is empty - backfill may have failed")
        
    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    debug_bi_extraction()

