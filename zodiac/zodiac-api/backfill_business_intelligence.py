#!/usr/bin/env python3
"""
Backfill Business Intelligence Data

This script extracts BI data from all existing invoices and populates
the invoice_business_data table.
"""

import sys
import os
import asyncio
import json
from datetime import datetime

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.invoice import ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi
from app.services.bi_database_service import save_business_intelligence_data
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_business_intelligence():
    """Extract BI data from all existing invoices"""
    
    print("=" * 70)
    print("Backfill Business Intelligence Data")
    print("=" * 70)
    print()
    
    db = SessionLocal()
    
    try:
        # ============================================================
        # 1. PROCESS SUCCESSFUL INVOICES
        # ============================================================
        print("📊 Processing successful invoices...")
        successful_invoices = db.query(ZodiacInvoiceSuccessEdi).all()
        
        print(f"Found {len(successful_invoices)} successful invoices")
        
        success_count = 0
        for invoice in successful_invoices:
            try:
                # Parse processing steps
                processing_steps = []
                if invoice.processing_steps:
                    if isinstance(invoice.processing_steps, str):
                        processing_steps = json.loads(invoice.processing_steps)
                    else:
                        processing_steps = invoice.processing_steps
                
                # Extract BI data
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
        
        # ============================================================
        # 2. PROCESS FAILED INVOICES
        # ============================================================
        print("📊 Processing failed invoices...")
        failed_invoices = db.query(ZodiacInvoiceFailedEdi).all()
        
        print(f"Found {len(failed_invoices)} failed invoices")
        
        failed_count = 0
        for invoice in failed_invoices:
            try:
                # Parse processing steps
                processing_steps = []
                if invoice.processing_steps:
                    if isinstance(invoice.processing_steps, str):
                        processing_steps = json.loads(invoice.processing_steps)
                    else:
                        processing_steps = invoice.processing_steps
                
                # Extract BI data
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
        
        # ============================================================
        # 3. SUMMARY
        # ============================================================
        print("=" * 70)
        print("BACKFILL COMPLETE!")
        print("=" * 70)
        print(f"✅ Successful invoices processed: {success_count}/{len(successful_invoices)}")
        print(f"✅ Failed invoices processed: {failed_count}/{len(failed_invoices)}")
        print(f"✅ Total invoices with BI data: {success_count + failed_count}")
        print()
        print("🎉 Business intelligence data is now available!")
        print("   Refresh your dashboard to see the analytics.")
        print()
        
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(backfill_business_intelligence())

