"""
Admin API endpoints for maintenance and setup operations
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import json

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.invoice import ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi
from ..models.invoice_business_data import InvoiceBusinessData
from ..api.auth import get_current_user
from ..services.bi_database_service import save_business_intelligence_data

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.post("/backfill-business-intelligence")
async def backfill_business_intelligence(
    background_tasks: BackgroundTasks,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Backfill business intelligence data for all existing invoices.
    This endpoint runs the backfill process for the current user's invoices.
    
    **Note:** This is a one-time setup operation. Future invoices will
    automatically extract BI data during processing.
    """
    try:
        logger.info(f"🔄 Starting BI backfill for user {current_user.id}")
        
        # Check if already has BI data
        existing_count = db.query(InvoiceBusinessData).filter(
            InvoiceBusinessData.user_id == current_user.id
        ).count()
        
        if existing_count > 0:
            return {
                "status": "already_populated",
                "message": f"Business intelligence data already exists ({existing_count} records). If you want to re-process, please contact support.",
                "existing_records": existing_count
            }
        
        # Count invoices to process
        success_count = db.query(ZodiacInvoiceSuccessEdi).filter(
            ZodiacInvoiceSuccessEdi.user_id == current_user.id
        ).count()
        
        failed_count = db.query(ZodiacInvoiceFailedEdi).filter(
            ZodiacInvoiceFailedEdi.user_id == current_user.id
        ).count()
        
        total_invoices = success_count + failed_count
        
        if total_invoices == 0:
            return {
                "status": "no_invoices",
                "message": "No invoices found to process. Upload some invoices first.",
                "total_invoices": 0
            }
        
        # Run backfill in background
        background_tasks.add_task(
            _run_backfill_task,
            db=db,
            user_id=current_user.id
        )
        
        return {
            "status": "processing",
            "message": "Backfill started! This may take a few minutes. Refresh the Business tab in 2-3 minutes to see your analytics.",
            "total_invoices": total_invoices,
            "successful_invoices": success_count,
            "failed_invoices": failed_count,
            "estimated_time_minutes": max(2, total_invoices // 50)  # Rough estimate
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to start BI backfill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start backfill: {str(e)}"
        )


async def _run_backfill_task(db: Session, user_id: int):
    """
    Background task to run the backfill process
    """
    try:
        logger.info(f"📊 Processing BI backfill for user {user_id}")
        
        # Get all successful invoices
        successful_invoices = db.query(ZodiacInvoiceSuccessEdi).filter(
            ZodiacInvoiceSuccessEdi.user_id == user_id
        ).all()
        
        success_processed = 0
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
                success_processed += 1
                
                if success_processed % 10 == 0:
                    logger.info(f"  ✅ Processed {success_processed}/{len(successful_invoices)} successful invoices")
                    
            except Exception as e:
                logger.error(f"  ⚠️ Failed to process invoice {invoice.id}: {e}")
                continue
        
        # Get all failed invoices
        failed_invoices = db.query(ZodiacInvoiceFailedEdi).filter(
            ZodiacInvoiceFailedEdi.user_id == user_id
        ).all()
        
        failed_processed = 0
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
                failed_processed += 1
                
                if failed_processed % 10 == 0:
                    logger.info(f"  ✅ Processed {failed_processed}/{len(failed_invoices)} failed invoices")
                    
            except Exception as e:
                logger.error(f"  ⚠️ Failed to process invoice {invoice.id}: {e}")
                continue
        
        logger.info(f"✅ BI Backfill complete for user {user_id}: {success_processed} successful, {failed_processed} failed invoices processed")
        
    except Exception as e:
        logger.error(f"❌ Backfill task failed for user {user_id}: {e}")


@router.get("/backfill-status")
async def check_backfill_status(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check the status of business intelligence data for the current user
    """
    try:
        # Count BI records
        bi_count = db.query(InvoiceBusinessData).filter(
            InvoiceBusinessData.user_id == current_user.id
        ).count()
        
        # Count invoices
        invoice_count = db.query(ZodiacInvoiceSuccessEdi).filter(
            ZodiacInvoiceSuccessEdi.user_id == current_user.id
        ).count()
        
        invoice_count += db.query(ZodiacInvoiceFailedEdi).filter(
            ZodiacInvoiceFailedEdi.user_id == current_user.id
        ).count()
        
        if bi_count == 0:
            status_type = "needs_backfill"
            message = "No business intelligence data found. Run backfill to extract data from existing invoices."
        elif bi_count < invoice_count:
            status_type = "partial"
            message = f"Partial data: {bi_count}/{invoice_count} invoices processed. Some invoices may be missing BI data."
        else:
            status_type = "complete"
            message = "Business intelligence data is up to date!"
        
        return {
            "status": status_type,
            "message": message,
            "bi_records": bi_count,
            "total_invoices": invoice_count,
            "coverage_percentage": round((bi_count / invoice_count * 100) if invoice_count > 0 else 0, 1)
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to check backfill status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check status: {str(e)}"
        )

