"""
Converted Invoices API Router
Handles conversion of successful invoices to customer-specific formats
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import json
from io import BytesIO

from ..database import get_db
from ..models.user import ZodiacUser
from ..models.converted_invoice import ConvertedInvoice
from ..models.user_customer import UserCustomer
from ..api.auth import get_current_user
from ..services.invoice_conversion_service import InvoiceConversionService
from ..services.file_service import read_file_from_storage
from ..schemas.converted_invoice import (
    ConversionRequest,
    ConversionBatchResult,
    ConversionResult,
    ValidationOverrideRequest,
    ConvertedInvoiceListResponse,
    ConvertedInvoiceResponse
)

router = APIRouter(prefix="/converted-invoices", tags=["converted-invoices"])
logger = logging.getLogger("zodiac-api.converted_invoices")


def _customer_user_can_access_converted(
    db: Session, current_user: ZodiacUser, converted: ConvertedInvoice
) -> bool:
    """If current user is a customer user, return True only when converted.customer_id is in their assigned customers."""
    if not getattr(current_user, "is_customer_user", False):
        return True
    customer_ids = [r[0] for r in db.query(UserCustomer.customer_id).filter(UserCustomer.user_id == current_user.id).all()]
    if not customer_ids or not converted.customer_id:
        return False
    return str(converted.customer_id).strip() in {str(c).strip() for c in customer_ids}


@router.post("/convert", response_model=ConversionBatchResult)
async def convert_invoices(
    request: ConversionRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """
    Convert one or more successful invoices to their target formats.
    Validates fields against customer configuration if customer exists.
    """
    logger.info(f"🔄 Convert request for {len(request.validated_invoice_ids)} invoices")
    
    try:
        service = InvoiceConversionService(db)
        results = []
        
        successful_count = 0
        failed_count = 0
        mismatch_count = 0
        
        for validated_id in request.validated_invoice_ids:
            logger.info(f"📋 Processing invoice ID: {validated_id}")
            
            result_data = await service.convert_invoice(
                validated_invoice_id=validated_id,
                override_validation=False
            )
            
            conversion_result = ConversionResult(
                validated_invoice_id=validated_id,
                status=result_data.get("status"),
                converted_invoice_id=result_data.get("converted_invoice_id"),
                target_format=result_data.get("target_format"),
                error_message=result_data.get("error_message"),
                validation_mismatches=result_data.get("validation_mismatches"),
                steps=result_data.get("steps", [])
            )
            
            results.append(conversion_result)
            
            # Count statuses
            if result_data.get("status") == "success":
                successful_count += 1
            elif result_data.get("status") == "validation_mismatch":
                mismatch_count += 1
            else:
                failed_count += 1
        
        logger.info(f"✅ Batch conversion completed: {successful_count} success, {failed_count} failed, {mismatch_count} mismatches")
        
        return ConversionBatchResult(
            total_requested=len(request.validated_invoice_ids),
            successful=successful_count,
            failed=failed_count,
            validation_mismatches=mismatch_count,
            results=results
        )
        
    except Exception as e:
        logger.error(f"❌ Batch conversion error: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Conversion failed: {str(e)}"
        )


@router.post("/{validated_invoice_id}/override", response_model=ConversionResult)
async def override_validation_and_convert(
    validated_invoice_id: int,
    override_request: ValidationOverrideRequest,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """
    Override validation mismatch and force conversion.
    Optionally update customer validation fields with invoice values.
    """
    logger.info(f"🔓 Override validation for invoice {validated_invoice_id}")
    logger.info(f"   Update customer fields: {override_request.update_customer_fields}")
    
    try:
        service = InvoiceConversionService(db)
        
        # If updating customer fields, do it first
        if override_request.update_customer_fields:
            # Get invoice data
            from ..models.invoice_v2_validated import InvoiceV2Validated
            validated = db.query(InvoiceV2Validated).filter(
                InvoiceV2Validated.id == validated_invoice_id
            ).first()
            
            if validated and validated.invoice_data.get("customer_id"):
                await service.update_customer_validation_fields(
                    customer_id=validated.invoice_data["customer_id"],
                    invoice_data=validated.invoice_data
                )
        
        # Convert with override
        result_data = await service.convert_invoice(
            validated_invoice_id=validated_invoice_id,
            override_validation=True
        )
        
        return ConversionResult(
            validated_invoice_id=validated_invoice_id,
            status=result_data.get("status"),
            converted_invoice_id=result_data.get("converted_invoice_id"),
            target_format=result_data.get("target_format"),
            error_message=result_data.get("error_message"),
            validation_mismatches=result_data.get("validation_mismatches"),
            steps=result_data.get("steps", [])
        )
        
    except Exception as e:
        logger.error(f"❌ Override conversion error: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Override conversion failed: {str(e)}"
        )


@router.get("/list/for-customer-user", response_model=ConvertedInvoiceListResponse)
async def list_converted_invoices_for_customer_user(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Number of records to return"),
    status_filter: Optional[str] = Query(None, description="Filter by status: success, failed"),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """Get paginated list of converted invoices for customer users (only assigned customer_ids)."""
    if not getattr(current_user, "is_customer_user", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for customer users only",
        )
    customer_ids = [r[0] for r in db.query(UserCustomer.customer_id).filter(UserCustomer.user_id == current_user.id).all()]
    if not customer_ids:
        return ConvertedInvoiceListResponse(total=0, skip=skip, limit=limit, converted_invoices=[])
    try:
        service = InvoiceConversionService(db)
        converted_invoices, total = service.get_converted_invoices_for_customer_user(
            skip, limit, status_filter, customer_ids
        )
        logger.info(f"✅ Retrieved {len(converted_invoices)} converted invoices for customer user (total: {total})")
        return ConvertedInvoiceListResponse(
            total=total,
            skip=skip,
            limit=limit,
            converted_invoices=converted_invoices,
        )
    except Exception as e:
        logger.error(f"❌ Error fetching converted invoices for customer user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch converted invoices: {str(e)}",
        )


@router.get("/list", response_model=ConvertedInvoiceListResponse)
async def list_converted_invoices(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Number of records to return"),
    status_filter: Optional[str] = Query(None, description="Filter by status: success, failed"),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """Get paginated list of converted invoices"""
    logger.info(f"📋 Fetching converted invoices - skip: {skip}, limit: {limit}, filter: {status_filter}")
    
    try:
        service = InvoiceConversionService(db)
        converted_invoices, total = service.get_converted_invoices(skip, limit, status_filter)
        
        logger.info(f"✅ Retrieved {len(converted_invoices)} converted invoices (total: {total})")
        
        return ConvertedInvoiceListResponse(
            total=total,
            skip=skip,
            limit=limit,
            converted_invoices=converted_invoices
        )
        
    except Exception as e:
        logger.error(f"❌ Error fetching converted invoices: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch converted invoices: {str(e)}"
        )


@router.get("/{converted_id}/download")
async def download_converted_invoice(
    converted_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """Download a converted invoice file"""
    logger.info(f"📥 Download request for converted invoice: {converted_id}")
    
    try:
        service = InvoiceConversionService(db)
        converted = service.get_converted_invoice(converted_id)
        
        if not converted:
            logger.error(f"❌ Converted invoice not found: {converted_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Converted invoice {converted_id} not found"
            )
        if not _customer_user_can_access_converted(db, current_user, converted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this converted invoice",
            )
        logger.info(f"📦 Converted invoice found:")
        logger.info(f"   Format: {converted.target_format}")
        logger.info(f"   Local path: {converted.converted_file_path}")
        logger.info(f"   Blob path: {converted.blob_converted_path}")
        
        # Check if file paths exist
        if not converted.blob_converted_path and not converted.converted_file_path:
            logger.error(f"❌ No file path found for converted invoice: {converted_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No file path found for this converted invoice"
            )
        
        # Read file from storage
        try:
            if converted.blob_converted_path:
                file_bytes = await read_file_from_storage(
                    file_path=converted.blob_converted_path,
                    blob_xml_path=converted.blob_converted_path
                )
            else:
                file_bytes = await read_file_from_storage(
                    file_path=converted.converted_file_path,
                    blob_xml_path=None
                )
            
            logger.info(f"✅ File loaded: {len(file_bytes)} bytes")
            
        except Exception as e:
            logger.error(f"❌ Failed to read file from storage: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read converted file: {str(e)}"
            )
        
        # Determine content type and filename
        content_type_map = {
            "X12": "application/edi-x12",
            "EDIFACT": "application/edifact",
            "PDF": "application/pdf",
            "XML": "application/xml",
            "UBL": "application/xml",
            "CFDI": "application/xml",
            "PIDX": "application/xml"
        }
        
        extension_map = {
            "X12": "edi",
            "EDIFACT": "edi",
            "PDF": "pdf",
            "XML": "xml",
            "UBL": "xml",
            "CFDI": "xml",
            "PIDX": "xml"
        }
        
        content_type = content_type_map.get(converted.target_format, "application/octet-stream")
        file_extension = extension_map.get(converted.target_format, "bin")
        
        # Get invoice number from validated invoice (load separately since no relationship)
        invoice_number = "unknown"
        try:
            from ..models.invoice_v2_validated import InvoiceV2Validated
            validated = db.query(InvoiceV2Validated).filter(
                InvoiceV2Validated.id == converted.validated_invoice_id
            ).first()
            
            if validated and validated.invoice_data:
                invoice_number = validated.invoice_data.get("invoice_number", "unknown")
        except Exception as e:
            logger.warning(f"⚠️ Could not load invoice number: {e}")
        
        filename = f"invoice_{invoice_number}_{converted.target_format}.{file_extension}"
        
        # Return file as streaming response
        return StreamingResponse(
            BytesIO(file_bytes),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Download error: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download failed: {str(e)}"
        )


@router.get("/{converted_id}/info", response_model=ConvertedInvoiceResponse)
async def get_converted_invoice_info(
    converted_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """Get information about a converted invoice (for debugging)"""
    logger.info(f"ℹ️ Getting info for converted invoice: {converted_id}")
    
    try:
        service = InvoiceConversionService(db)
        converted = service.get_converted_invoice(converted_id)
        
        if not converted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Converted invoice {converted_id} not found"
            )
        if not _customer_user_can_access_converted(db, current_user, converted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this converted invoice",
            )
        return converted
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting converted invoice info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get info: {str(e)}"
        )


@router.delete("/{converted_id}")
async def delete_converted_invoice(
    converted_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user)
):
    """Delete a converted invoice and its associated file"""
    logger.info(f"🗑️ Delete request for converted invoice: {converted_id}")
    
    try:
        service = InvoiceConversionService(db)
        converted = service.get_converted_invoice(converted_id)
        
        if not converted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Converted invoice {converted_id} not found"
            )
        if not _customer_user_can_access_converted(db, current_user, converted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this converted invoice",
            )
        # Delete the converted file from storage if it exists
        if converted.converted_file_path:
            try:
                import os
                file_path = converted.converted_file_path
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"✅ Deleted file: {file_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not delete file: {e}")
        
        # Delete from blob storage if exists
        if converted.blob_converted_path:
            try:
                from ..services.file_service import delete_file_from_storage
                await delete_file_from_storage(converted.blob_converted_path)
                logger.info(f"✅ Deleted blob file: {converted.blob_converted_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not delete blob file: {e}")
        
        # Delete the database record
        db.delete(converted)
        db.commit()
        
        logger.info(f"✅ Converted invoice {converted_id} deleted successfully")
        
        return {
            "message": "Converted invoice deleted successfully",
            "converted_id": converted_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Delete error: {e}")
        logger.exception(e)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete converted invoice: {str(e)}"
        )
