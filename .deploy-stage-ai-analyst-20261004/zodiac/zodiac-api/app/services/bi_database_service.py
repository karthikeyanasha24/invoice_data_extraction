"""
Business Intelligence Database Service

Handles saving and updating business intelligence data in the database
"""
import logging
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID

from ..models.invoice_business_data import InvoiceBusinessData
from ..services.business_intelligence_service import business_intelligence_extractor
from ..services.file_service import read_file_from_storage

logger = logging.getLogger(__name__)


def determine_lifecycle_stage(processing_steps: list, external_status: str, is_failed: bool) -> Dict:
    """
    Determine the current lifecycle stage and status based on processing steps
    
    Args:
        processing_steps: List of processing steps from invoice
        external_status: External status from invoice
        is_failed: Whether invoice failed
        
    Returns:
        Dict with current_stage, stage_status, failed_at_stage, lifecycle_stages
    """
    lifecycle_stages = {}
    current_stage = 'RECEIVED'
    stage_status = 'SUCCESS'
    failed_at_stage = None
    
    if not processing_steps:
        return {
            'current_stage': current_stage,
            'stage_status': stage_status,
            'failed_at_stage': failed_at_stage,
            'lifecycle_stages': lifecycle_stages
        }
    
    # Map processing steps to lifecycle stages
    stage_mapping = {
        'File Upload': 'RECEIVED',
        'Early XML Check': 'RECEIVED',
        'XML Validation': 'VALIDATED',
        'Format Conversion': 'CONVERTED',
        '3rd Party Endpoint': 'SENT',
        'PDF Embed': 'CONVERTED',
    }
    
    # Process each step
    for step in processing_steps:
        step_name = step.get('step_name', '')
        success = step.get('success', False)
        message = step.get('message', '')
        
        # Map to lifecycle stage
        lifecycle_stage = stage_mapping.get(step_name, current_stage)
        
        # Update lifecycle stages
        if lifecycle_stage not in lifecycle_stages:
            lifecycle_stages[lifecycle_stage] = {
                'status': 'SUCCESS' if success else 'FAILED',
                'timestamp': datetime.utcnow().isoformat(),
                'message': message
            }
        
        # Track current stage
        if success:
            current_stage = lifecycle_stage
        else:
            # Failed at this stage
            failed_at_stage = lifecycle_stage
            stage_status = 'FAILED'
            lifecycle_stages[lifecycle_stage]['status'] = 'FAILED'
            lifecycle_stages[lifecycle_stage]['error'] = step.get('error_details', message)
            break
    
    # Check external status for ACKNOWLEDGED stage
    if external_status and external_status.lower() == 'success':
        lifecycle_stages['ACKNOWLEDGED'] = {
            'status': 'SUCCESS',
            'timestamp': datetime.utcnow().isoformat(),
            'message': 'External system acknowledged receipt'
        }
        current_stage = 'ACKNOWLEDGED'
    elif external_status and external_status.lower() in ['failed', 'error']:
        lifecycle_stages['ACKNOWLEDGED'] = {
            'status': 'FAILED',
            'timestamp': datetime.utcnow().isoformat(),
            'message': 'External system rejected'
        }
        failed_at_stage = 'ACKNOWLEDGED'
        stage_status = 'FAILED'
    
    # If invoice is marked as failed, ensure status reflects that
    if is_failed and stage_status == 'SUCCESS':
        stage_status = 'FAILED'
        if not failed_at_stage:
            failed_at_stage = current_stage
    
    return {
        'current_stage': current_stage,
        'stage_status': stage_status,
        'failed_at_stage': failed_at_stage,
        'lifecycle_stages': lifecycle_stages
    }


async def save_business_intelligence_data(
    db: Session,
    tracking_id: UUID,
    user_id: int,
    xml_path: Optional[str],
    processing_steps: Optional[list],
    external_status: Optional[str],
    request_type: str,
    target_format: Optional[str],
    is_failed: bool = False,
    success_invoice_id: Optional[int] = None,
    failed_invoice_id: Optional[int] = None,
    blob_xml_path: Optional[str] = None
) -> Optional[InvoiceBusinessData]:
    """
    Extract and save business intelligence data for an invoice
    
    Args:
        db: Database session
        tracking_id: Invoice tracking ID
        user_id: User ID
        xml_path: Path to XML file (for extracting BI data) - can be dict or string
        processing_steps: Processing steps from invoice
        external_status: External status
        request_type: 'web' or 'api'
        target_format: Target format
        is_failed: Whether invoice failed
        success_invoice_id: ID from success table (if successful)
        failed_invoice_id: ID from failed table (if failed)
        blob_xml_path: Blob storage URL for XML file (for production)
        
    Returns:
        InvoiceBusinessData object or None if extraction failed
    """
    try:
        logger.info(f"📊 Extracting business intelligence for tracking_id: {tracking_id}")
        logger.info(f"🔍 BI Extraction - xml_path type: {type(xml_path)}, blob_xml_path: {blob_xml_path}")
        
        # Extract business data from XML
        business_data = {}
        if xml_path or blob_xml_path:
            try:
                # Use blob_xml_path if available (production), otherwise xml_path (local/test)
                xml_content = await read_file_from_storage(
                    file_path=xml_path,
                    blob_xml_path=blob_xml_path,
                    blob_edi_path=None
                )
                if xml_content:
                    logger.info(f"✅ Successfully read XML content ({len(xml_content)} bytes)")
                    business_data = business_intelligence_extractor.extract_from_xml(xml_content)
                    logger.info(f"✅ Extracted BI data: customer={business_data.get('customer_name')}, products={business_data.get('product_count')}, industry={business_data.get('industry')}")
                else:
                    logger.warning(f"⚠️ Could not read XML file: xml_path={xml_path}, blob_xml_path={blob_xml_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not extract BI data from XML: {e}", exc_info=True)
        
        # Determine lifecycle stage
        lifecycle_data = determine_lifecycle_stage(
            processing_steps or [],
            external_status,
            is_failed
        )
        
        # Determine failure reason
        failure_reason = None
        if is_failed and processing_steps:
            for step in reversed(processing_steps):
                if not step.get('success', True):
                    failure_reason = step.get('message') or step.get('error_details')
                    break
        
        # Create business intelligence record
        bi_data = InvoiceBusinessData(
            tracking_id=tracking_id,
            user_id=user_id,
            success_invoice_id=success_invoice_id,
            failed_invoice_id=failed_invoice_id,
            
            # Customer data
            customer_id=business_data.get('customer_id'),
            customer_name=business_data.get('customer_name'),
            customer_country=business_data.get('customer_country'),
            customer_city=business_data.get('customer_city'),
            customer_address=business_data.get('customer_address'),
            customer_tax_id=business_data.get('customer_tax_id'),
            
            # Supplier data
            supplier_id=business_data.get('supplier_id'),
            supplier_name=business_data.get('supplier_name'),
            supplier_country=business_data.get('supplier_country'),
            
            # Product data
            products=business_data.get('products'),
            product_count=business_data.get('product_count', 0),
            
            # Industry
            industry=business_data.get('industry'),
            industry_confidence=business_data.get('industry_confidence'),
            industry_keywords_matched=business_data.get('industry_keywords_matched'),
            
            # Financial data
            invoice_number=business_data.get('invoice_number'),
            invoice_date=business_data.get('invoice_date'),
            due_date=business_data.get('due_date'),
            total_amount=business_data.get('total_amount'),
            tax_amount=business_data.get('tax_amount'),
            currency=business_data.get('currency', 'USD'),
            
            # Lifecycle tracking
            current_stage=lifecycle_data['current_stage'],
            stage_status=lifecycle_data['stage_status'],
            failed_at_stage=lifecycle_data['failed_at_stage'],
            failure_reason=failure_reason,
            lifecycle_stages=lifecycle_data['lifecycle_stages'],
            
            # Metadata
            source_format=business_data.get('source_format', 'XML'),
            target_format=target_format,
            request_type=request_type
        )
        
        db.add(bi_data)
        db.commit()
        db.refresh(bi_data)
        
        logger.info(f"✅ Business intelligence data saved for tracking_id: {tracking_id}")
        logger.info(f"   Customer: {bi_data.customer_name}, Industry: {bi_data.industry}, Stage: {bi_data.current_stage}")
        
        return bi_data
        
    except Exception as e:
        logger.error(f"❌ Failed to save business intelligence data: {e}")
        db.rollback()
        return None

