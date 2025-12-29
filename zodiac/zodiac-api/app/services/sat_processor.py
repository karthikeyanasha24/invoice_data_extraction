"""
SAT Document Processing Service
Orchestrates validation, normalization, and enrichment of SAT documents
"""
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import json

from ..models.sat_document import (
    SATDocument,
    SATProcessingLog,
    ProcessingStatus
)
from ..utils.cfdi_parser import CFDIParser, extract_cfdi_fields
from .sap_transformer import sap_transformer
from .sap_api_client import sap_api_client

logger = logging.getLogger(__name__)


class SATProcessor:
    """
    Processes SAT documents through the pipeline:
    1. Validation
    2. Field Extraction
    3. Normalization
    4. Enrichment
    5. (Future) SAP Integration
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.parser = CFDIParser()
    
    async def process_document(self, sat_document_id: str) -> Dict[str, Any]:
        """
        Process a SAT document through the entire pipeline
        
        Args:
            sat_document_id: UUID of the SAT document
        
        Returns:
            Processing result with status and details
        """
        try:
            # Load document
            doc = self.db.query(SATDocument).filter(
                SATDocument.id == sat_document_id
            ).first()
            
            if not doc:
                raise ValueError(f"Document {sat_document_id} not found")
            
            logger.info(f"🔄 Processing document: {doc.portal_reference_id}")
            
            # Step 1: Validate XML
            validation_result = await self.validate_xml(doc)
            
            if not validation_result['valid']:
                logger.warning(f"⚠️  Validation failed for {doc.portal_reference_id}")
                return validation_result
            
            # Step 2: Extract fields
            extraction_result = await self.extract_fields(doc)
            
            if not extraction_result['success']:
                logger.warning(f"⚠️  Field extraction failed for {doc.portal_reference_id}")
                return extraction_result
            
            # Step 3: Normalize (basic for now)
            normalization_result = await self.normalize_document(doc)
            
            # Step 4: Transform to SAP format
            transformation_result = await self.transform_to_sap(doc, extraction_result.get('extracted_fields', {}))
            
            if not transformation_result['success']:
                logger.warning(f"⚠️  SAP transformation failed for {doc.portal_reference_id}")
                return transformation_result
            
            # Step 5: Send to SAP (now uses XML)
            sap_result = await self.send_to_sap(
                doc, 
                transformation_result['sap_xml'],
                transformation_result['sap_blart']
            )
            
            if sap_result['success']:
                # Update document with SAP response
                doc.sap_document_number = sap_result.get('sap_document_number')
                doc.sap_fiscal_year = sap_result.get('sap_fiscal_year')
                doc.sap_posting_date = sap_result.get('sap_posting_date')
                doc.sap_sent_at = datetime.utcnow()
                doc.sap_confirmed_at = datetime.utcnow()
                
                self._update_status(
                    doc,
                    ProcessingStatus.SAP_CONFIRMED,
                    f"Document posted to SAP: {doc.sap_document_number}"
                )
            else:
                # SAP failed, mark as READY_FOR_SAP for retry
                doc.error_message = sap_result.get('error_message', 'SAP posting failed')
                doc.error_code = sap_result.get('error_code', 'SAP_ERROR')
                
                self._update_status(
                    doc,
                    ProcessingStatus.READY_FOR_SAP,
                    f"Document ready for SAP but posting failed: {doc.error_message}"
                )
            
            self.db.commit()
            
            logger.info(f"✅ Document processed successfully: {doc.portal_reference_id}")
            
            return {
                'success': True,
                'document_id': str(doc.id),
                'portal_reference_id': doc.portal_reference_id,
                'status': doc.status.value,
                'validation': validation_result,
                'extraction': extraction_result,
                'normalization': normalization_result,
                'transformation': transformation_result,
                'sap_result': sap_result
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing document: {e}")
            self.db.rollback()
            
            if doc:
                self._update_status(
                    doc,
                    ProcessingStatus.FAILED,
                    f"Processing error: {str(e)}"
                )
                doc.error_message = str(e)
                self.db.commit()
            
            return {
                'success': False,
                'error': str(e)
            }
    
    async def validate_xml(self, doc: SATDocument) -> Dict[str, Any]:
        """
        Step 1: Validate XML structure and mandatory fields
        """
        logger.info(f"📋 Validating XML for {doc.portal_reference_id}")
        
        try:
            # Update status
            self._update_status(
                doc,
                ProcessingStatus.VALIDATING,
                "Starting XML validation"
            )
            
            # Validate structure
            validation_result = self.parser.validate_structure(doc.original_xml)
            
            # Store validation report
            doc.validation_report = {
                'schemaValid': validation_result['valid'],
                'duplicateCheckPassed': not doc.is_duplicate,
                'errors': validation_result['errors'],
                'warnings': validation_result['warnings'],
                'validatedAt': datetime.utcnow().isoformat()
            }
            doc.is_schema_valid = validation_result['valid']
            
            if validation_result['valid']:
                self._update_status(
                    doc,
                    ProcessingStatus.VALIDATED,
                    f"XML validation passed (0 errors, {len(validation_result['warnings'])} warnings)"
                )
                logger.info(f"✅ Validation passed for {doc.portal_reference_id}")
            else:
                self._update_status(
                    doc,
                    ProcessingStatus.FAILED,
                    f"XML validation failed: {len(validation_result['errors'])} errors"
                )
                doc.error_message = "; ".join(validation_result['errors'])
                doc.error_code = "VALIDATION_FAILED"
                logger.warning(f"⚠️  Validation failed for {doc.portal_reference_id}")
            
            self.db.commit()
            
            return validation_result
            
        except Exception as e:
            logger.error(f"❌ Validation error: {e}")
            self._update_status(
                doc,
                ProcessingStatus.FAILED,
                f"Validation exception: {str(e)}"
            )
            doc.error_message = f"Validation error: {str(e)}"
            doc.error_code = "VALIDATION_ERROR"
            self.db.commit()
            
            return {
                'valid': False,
                'errors': [str(e)],
                'warnings': []
            }
    
    async def extract_fields(self, doc: SATDocument) -> Dict[str, Any]:
        """
        Step 2: Extract all fields from CFDI XML
        """
        logger.info(f"🔍 Extracting fields from {doc.portal_reference_id}")
        
        try:
            # Extract fields
            extracted = extract_cfdi_fields(doc.original_xml)
            
            # Update document with extracted fields
            doc.cfdi_version = extracted.get('cfdi_version')
            doc.serie = extracted.get('serie')
            doc.folio = extracted.get('folio')
            
            # Parse fecha (date)
            fecha_str = extracted.get('fecha')
            if fecha_str:
                try:
                    # CFDI date format: 2025-03-15T10:30:00
                    doc.fecha = datetime.fromisoformat(fecha_str.replace('Z', '+00:00'))
                except:
                    logger.warning(f"Could not parse fecha: {fecha_str}")
            
            doc.subtotal = extracted.get('subtotal')
            doc.total = extracted.get('total')
            doc.moneda = extracted.get('moneda')
            doc.tipo_de_comprobante = extracted.get('tipo_de_comprobante')
            
            # Update UUID if it was temporary
            if doc.cfdi_uuid.startswith('TEMP-'):
                new_uuid = extracted.get('cfdi_uuid')
                if new_uuid:
                    doc.cfdi_uuid = new_uuid
                    logger.info(f"✅ Updated UUID from temporary to: {new_uuid}")
                    
                    # Check for duplicates with real UUID
                    from ..models.sat_document import SATDuplicateCheck
                    existing_dup = self.db.query(SATDuplicateCheck).filter(
                        SATDuplicateCheck.cfdi_uuid == new_uuid,
                        SATDuplicateCheck.user_id == doc.user_id,
                        SATDuplicateCheck.sat_document_id != doc.id
                    ).first()
                    
                    if existing_dup:
                        doc.is_duplicate = True
                        doc.status = ProcessingStatus.DUPLICATE
                        logger.warning(f"⚠️  Duplicate detected after UUID extraction: {new_uuid}")
                        self.db.commit()
                        return {
                            'success': False,
                            'error': 'Duplicate document detected',
                            'duplicate_of': str(existing_dup.sat_document_id)
                        }
                    
                    # Create duplicate check record with real UUID
                    dup_check = SATDuplicateCheck(
                        cfdi_uuid=new_uuid,
                        sat_document_id=doc.id,
                        user_id=doc.user_id,
                        supplier_id=doc.supplier_id,
                        document_type=doc.document_type
                    )
                    self.db.add(dup_check)
            
            # Supplier information
            if not doc.supplier_rfc:
                doc.supplier_rfc = extracted.get('supplier_rfc')
            if not doc.supplier_name:
                doc.supplier_name = extracted.get('supplier_name')
            
            # Customer information
            doc.customer_rfc = extracted.get('customer_rfc')
            doc.customer_name = extracted.get('customer_name')
            
            self._update_status(
                doc,
                ProcessingStatus.VALIDATED,
                f"Extracted {extracted.get('conceptos_count', 0)} line items"
            )
            
            self.db.commit()
            
            logger.info(f"✅ Field extraction complete for {doc.portal_reference_id}")
            
            return {
                'success': True,
                'extracted_fields': extracted
            }
            
        except Exception as e:
            logger.error(f"❌ Field extraction error: {e}")
            self._update_status(
                doc,
                ProcessingStatus.FAILED,
                f"Field extraction error: {str(e)}"
            )
            doc.error_message = f"Field extraction error: {str(e)}"
            doc.error_code = "EXTRACTION_ERROR"
            self.db.commit()
            
            return {
                'success': False,
                'error': str(e)
            }
    
    async def normalize_document(self, doc: SATDocument) -> Dict[str, Any]:
        """
        Step 3: Normalize document to canonical format
        (Basic normalization for now - full implementation later)
        """
        logger.info(f"🔄 Normalizing document {doc.portal_reference_id}")
        
        try:
            # For now, canonical XML is same as original
            # In future, implement full normalization:
            # - Standardize dates to ISO format
            # - Normalize currency codes
            # - Standardize company codes
            # - Clean up formatting
            
            doc.canonical_xml = doc.original_xml
            
            self._update_status(
                doc,
                ProcessingStatus.NORMALIZED,
                "Document normalized (basic)"
            )
            
            self.db.commit()
            
            logger.info(f"✅ Normalization complete for {doc.portal_reference_id}")
            
            return {
                'success': True,
                'message': 'Document normalized successfully'
            }
            
        except Exception as e:
            logger.error(f"❌ Normalization error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def transform_to_sap(self, doc: SATDocument, cfdi_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Step 4: Transform CFDI document to SAP XML format
        """
        logger.info(f"🔄 Transforming to SAP XML format: {doc.portal_reference_id}")
        
        try:
            self._update_status(
                doc,
                ProcessingStatus.ENRICHING,
                "Transforming document to SAP XML format"
            )
            
            # Transform using SAP Transformer (now returns dict, XML, and BLART)
            # Convert enum to string if needed
            doc_type_str = doc.document_type.value if hasattr(doc.document_type, 'value') else str(doc.document_type)
            sap_dict, sap_xml, sap_blart = sap_transformer.transform_to_sap_xml(
                cfdi_data=cfdi_data,
                document_type=doc_type_str
            )
            
            self._update_status(
                doc,
                ProcessingStatus.READY_FOR_SAP,
                f"Document transformed to SAP {doc.document_type} XML (BLART: {sap_blart})"
            )
            
            self.db.commit()
            
            logger.info(f"✅ SAP XML transformation complete for {doc.portal_reference_id}")
            
            return {
                'success': True,
                'sap_dict': sap_dict,
                'sap_xml': sap_xml,
                'sap_blart': sap_blart,
                'message': f'Document transformed to SAP XML successfully (BLART: {sap_blart})'
            }
            
        except Exception as e:
            logger.error(f"❌ SAP transformation error: {e}")
            self._update_status(
                doc,
                ProcessingStatus.FAILED,
                f"SAP transformation error: {str(e)}"
            )
            doc.error_message = f"SAP transformation error: {str(e)}"
            doc.error_code = "SAP_TRANSFORMATION_ERROR"
            self.db.commit()
            
            return {
                'success': False,
                'error': str(e)
            }
    
    async def send_to_sap(self, doc: SATDocument, sap_xml: str, sap_blart: str) -> Dict[str, Any]:
        """
        Step 5: Send transformed document to SAP ECC API (XML format)
        """
        logger.info(f"📤 Sending XML to SAP (BLART: {sap_blart}): {doc.portal_reference_id}")
        
        try:
            self._update_status(
                doc,
                ProcessingStatus.SENT_TO_SAP,
                f"Sending document to SAP ECC (BLART: {sap_blart})"
            )
            
            # Send to SAP using API Client (now sends XML)
            # Convert enum to string if needed
            doc_type_str = doc.document_type.value if hasattr(doc.document_type, 'value') else str(doc.document_type)
            sap_response = await sap_api_client.send_document_to_sap(
                portal_reference_id=doc.portal_reference_id,
                document_type=doc_type_str,
                sap_xml=sap_xml,
                sap_blart=sap_blart,
                company_code=doc.company_code or "1000",
                supplier_id=doc.supplier_id or "UNKNOWN",
                cfdi_uuid=doc.cfdi_uuid
            )
            
            self.db.commit()
            
            if sap_response.get('success'):
                logger.info(f"✅ SAP accepted document: {doc.portal_reference_id}")
            else:
                logger.error(f"❌ SAP rejected document: {doc.portal_reference_id}")
            
            return sap_response
            
        except Exception as e:
            logger.error(f"❌ SAP API error: {e}")
            self._update_status(
                doc,
                ProcessingStatus.FAILED,
                f"SAP API error: {str(e)}"
            )
            doc.error_message = f"SAP API error: {str(e)}"
            doc.error_code = "SAP_API_ERROR"
            self.db.commit()
            
            return {
                'success': False,
                'error': str(e),
                'error_code': 'SAP_API_ERROR'
            }
    
    def _update_status(
        self, 
        doc: SATDocument, 
        new_status: ProcessingStatus,
        message: str
    ):
        """Update document status and create log entry"""
        previous_status = doc.status
        doc.status = new_status
        
        # Create log entry
        log_entry = SATProcessingLog(
            sat_document_id=doc.id,
            step_name=new_status.value,
            step_status="SUCCESS" if new_status != ProcessingStatus.FAILED else "FAILED",
            previous_status=previous_status,
            new_status=new_status,
            message=message
        )
        
        self.db.add(log_entry)
        logger.info(f"📝 {doc.portal_reference_id}: {previous_status.value} → {new_status.value}")


# Helper function for background processing
async def process_sat_document(db: Session, document_id: str) -> Dict[str, Any]:
    """
    Process a SAT document (can be called from background task)
    """
    processor = SATProcessor(db)
    return await processor.process_document(document_id)

