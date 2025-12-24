#!/usr/bin/env python3
"""
Clear empty BI records and re-run backfill with fixed code
"""

import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.invoice_business_data import InvoiceBusinessData
from app.models.invoice import ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi
from app.services.bi_database_service import save_business_intelligence_data
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def clear_and_rebackfill():
    """Clear empty BI records and re-extract with fixed code"""
    
    print("=" * 70)
    print("Clear Empty BI Records and Re-Backfill")
    print("=" * 70)
    print()
    
    db = SessionLocal()
    
    try:
        # Step 1: Clear existing BI records
        print("🗑️  Clearing existing BI records...")
        deleted_count = db.query(InvoiceBusinessData).delete()
        db.commit()
        print(f"✅ Deleted {deleted_count} existing records")
        print()
        
        # Step 2: Re-run backfill with fixed code
        print("📊 Re-processing all invoices with FIXED extraction...")
        print()
        
        # Process successful invoices
        successful_invoices = db.query(ZodiacInvoiceSuccessEdi).all()
        print(f"Found {len(successful_invoices)} successful invoices")
        
        success_count = 0
        for invoice in successful_invoices:
            try:
                processing_steps = []
                if invoice.processing_steps:
                    if isinstance(invoice.processing_steps, str):
                        processing_steps = json.loads(invoice.processing_steps)
                    else:
                        processing_steps = invoice.processing_steps
                
                await save_business_intelligence_data(
                    db=db,
                    tracking_id=invoice.tracking_id,
                    user_id=invoice.user_id,
                    xml_path=invoice.xml_path,
                    processing_steps=processing_steps,
                    external_status=invoice.external_status,
                    request_type=invoice.request_type or 'web',
                    target_format=invoice.target_file_format,
                    is_failed=False,
                    success_invoice_id=invoice.id
                )
                success_count += 1
                
                if success_count % 10 == 0:
                    print(f"  ✅ Processed {success_count}/{len(successful_invoices)} successful invoices...")
                    
            except Exception as e:
                logger.error(f"  ⚠️ Failed to process invoice {invoice.id}: {e}")
                continue
        
        print(f"✅ Processed {success_count}/{len(successful_invoices)} successful invoices")
        print()
        
        # Process failed invoices
        failed_invoices = db.query(ZodiacInvoiceFailedEdi).all()
        print(f"Found {len(failed_invoices)} failed invoices")
        
        failed_count = 0
        for invoice in failed_invoices:
            try:
                processing_steps = []
                if invoice.processing_steps:
                    if isinstance(invoice.processing_steps, str):
                        processing_steps = json.loads(invoice.processing_steps)
                    else:
                        processing_steps = invoice.processing_steps
                
                await save_business_intelligence_data(
                    db=db,
                    tracking_id=invoice.tracking_id,
                    user_id=invoice.user_id,
                    xml_path=invoice.xml_path,
                    processing_steps=processing_steps,
                    external_status=None,
                    request_type=invoice.request_type or 'web',
                    target_format=invoice.target_file_format,
                    is_failed=True,
                    failed_invoice_id=invoice.id
                )
                failed_count += 1
                
                if failed_count % 10 == 0:
                    print(f"  ✅ Processed {failed_count}/{len(failed_invoices)} failed invoices...")
                    
            except Exception as e:
                logger.error(f"  ⚠️ Failed to process invoice {invoice.id}: {e}")
                continue
        
        print(f"✅ Processed {failed_count}/{len(failed_invoices)} failed invoices")
        print()
        
        # Verify results
        print("=" * 70)
        print("VERIFICATION")
        print("=" * 70)
        
        bi_records = db.query(InvoiceBusinessData).limit(5).all()
        print(f"\nChecking first 5 BI records:\n")
        
        for record in bi_records:
            print(f"  ✅ Record ID: {record.id}")
            print(f"     Customer: {record.customer_name} ({record.customer_id})")
            print(f"     Supplier: {record.supplier_name}")
            print(f"     Industry: {record.industry}")
            print(f"     Products: {record.product_count} products")
            print(f"     Total Amount: ${record.total_amount}")
            print()
        
        print("=" * 70)
        print("RE-BACKFILL COMPLETE!")
        print("=" * 70)
        print(f"✅ Total invoices processed: {success_count + failed_count}")
        print()
        print("🎉 Business intelligence data should now have REAL customer/product data!")
        print("   Refresh your dashboard to see the analytics.")
        print()
        
    except Exception as e:
        logger.error(f"❌ Re-backfill failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(clear_and_rebackfill())

