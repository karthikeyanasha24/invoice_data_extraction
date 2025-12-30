"""
SAT Document Processor Service
Handles intake, validation, and storage of SAT CFDI documents
"""
import logging
import hashlib
import uuid
from typing import Dict, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from ..models.sat_document import SATDocument
from ..utils.cfdi_parser import CFDIParser

logger = logging.getLogger("zodiac-api.sat_processor")


class SATDocumentProcessor:
    """Process and store SAT CFDI documents"""
    
    def __init__(self, db: Session):
        self.db = db
        self.parser = CFDIParser()
    
    def process_cfdi_document(
        self,
        user_id: int,
        xml_content: str
    ) -> Dict:
        """
        Process a CFDI document: validate, parse, store.
        Returns processing result with document ID and status.
        """
        try:
            logger.info(f"📨 Processing CFDI document for user {user_id}")
            
            # Step 1: Validate XML structure
            is_valid, error_msg = self.parser.validate_cfdi_structure(xml_content)
            if not is_valid:
                logger.error(f"❌ CFDI validation failed: {error_msg}")
                return {
                    "success": False,
                    "status": "VALIDATION_FAILED",
                    "error": error_msg
                }
            
            # Step 2: Parse CFDI data
            try:
                cfdi_data = self.parser.parse_cfdi(xml_content)
            except Exception as e:
                logger.error(f"❌ CFDI parsing failed: {e}")
                return {
                    "success": False,
                    "status": "PARSING_FAILED",
                    "error": str(e)
                }
            
            # Step 3: Check for duplicates (by UUID)
            cfdi_uuid = cfdi_data.get('cfdi_uuid')
            if not cfdi_uuid:
                return {
                    "success": False,
                    "status": "VALIDATION_FAILED",
                    "error": "Missing CFDI UUID"
                }
            
            existing = self.db.query(SATDocument).filter(
                SATDocument.cfdi_uuid == cfdi_uuid
            ).first()
            
            if existing:
                logger.warning(f"⚠️ Duplicate CFDI UUID: {cfdi_uuid}")
                return {
                    "success": False,
                    "status": "DUPLICATE",
                    "error": f"Document with UUID {cfdi_uuid} already exists",
                    "existing_id": str(existing.id)
                }
            
            # Step 4: Calculate XML hash for integrity
            xml_hash = hashlib.sha256(xml_content.encode('utf-8')).hexdigest()
            
            # Step 5: Generate portal reference ID
            portal_ref_id = f"SAT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            
            # Step 6: Create SAT document record
            sat_doc = SATDocument(
                id=uuid.uuid4(),
                user_id=user_id,
                portal_ref_id=portal_ref_id,
                cfdi_uuid=cfdi_uuid,
                doc_type=cfdi_data['doc_type'],
                supplier_rfc=cfdi_data.get('supplier_rfc'),
                supplier_name=cfdi_data.get('supplier_name'),
                receiver_rfc=cfdi_data.get('receiver_rfc'),
                receiver_name=cfdi_data.get('receiver_name'),
                serie=cfdi_data.get('serie'),
                folio=cfdi_data.get('folio'),
                fecha=cfdi_data.get('fecha'),
                subtotal=cfdi_data.get('subtotal'),
                total=cfdi_data.get('total'),
                moneda=cfdi_data.get('moneda', 'MXN'),
                tipo_cambio=cfdi_data.get('tipo_cambio'),
                forma_pago=cfdi_data.get('forma_pago'),
                metodo_pago=cfdi_data.get('metodo_pago'),
                related_cfdi_uuid=cfdi_data.get('related_cfdi_uuids', [None])[0] if cfdi_data.get('related_cfdi_uuids') else None,
                status='VALIDATED',  # Set to VALIDATED after successful parsing
                xml_content=xml_content,
                xml_hash=xml_hash,
                file_size=len(xml_content.encode('utf-8')),
                fiscal_year=cfdi_data.get('fiscal_year'),
                fiscal_period=cfdi_data.get('fiscal_period'),
                received_at=datetime.utcnow()
            )
            
            self.db.add(sat_doc)
            self.db.commit()
            self.db.refresh(sat_doc)
            
            logger.info(f"✅ CFDI document stored: {sat_doc.id} | UUID: {cfdi_uuid} | Type: {sat_doc.doc_type}")
            
            return {
                "success": True,
                "status": "VALIDATED",
                "document_id": str(sat_doc.id),
                "portal_ref_id": portal_ref_id,
                "cfdi_uuid": cfdi_uuid,
                "doc_type": sat_doc.doc_type,
                "supplier_rfc": sat_doc.supplier_rfc,
                "total": sat_doc.total,
                "currency": sat_doc.moneda,
                "fiscal_year": sat_doc.fiscal_year,
                "fiscal_period": sat_doc.fiscal_period
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Failed to process CFDI document: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "status": "PROCESSING_ERROR",
                "error": str(e)
            }
    
    def get_document_by_id(self, user_id: int, document_id: str) -> Optional[SATDocument]:
        """Get a SAT document by ID"""
        try:
            doc_uuid = uuid.UUID(document_id)
        except ValueError:
            return None
        
        return self.db.query(SATDocument).filter(
            SATDocument.id == doc_uuid,
            SATDocument.user_id == user_id
        ).first()
    
    def list_documents(
        self,
        user_id: int,
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[int] = None,
        doc_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Dict:
        """List SAT documents with filters"""
        
        query = self.db.query(SATDocument).filter(
            SATDocument.user_id == user_id
        )
        
        if fiscal_year:
            query = query.filter(SATDocument.fiscal_year == fiscal_year)
        if fiscal_period:
            query = query.filter(SATDocument.fiscal_period == fiscal_period)
        if doc_type:
            query = query.filter(SATDocument.doc_type == doc_type)
        if status:
            query = query.filter(SATDocument.status == status)
        
        total = query.count()
        documents = query.order_by(
            SATDocument.received_at.desc()
        ).offset(skip).limit(limit).all()
        
        return {
            "total": total,
            "documents": [
                {
                    "id": str(doc.id),
                    "portal_ref_id": doc.portal_ref_id,
                    "cfdi_uuid": doc.cfdi_uuid,
                    "doc_type": doc.doc_type,
                    "supplier_rfc": doc.supplier_rfc,
                    "supplier_name": doc.supplier_name,
                    "receiver_rfc": doc.receiver_rfc,
                    "receiver_name": doc.receiver_name,
                    "serie": doc.serie,
                    "folio": doc.folio,
                    "fecha": doc.fecha.isoformat() if doc.fecha else None,
                    "total": doc.total,
                    "moneda": doc.moneda,
                    "status": doc.status,
                    "fiscal_year": doc.fiscal_year,
                    "fiscal_period": doc.fiscal_period,
                    "received_at": doc.received_at.isoformat() if doc.received_at else None,
                    "sap_document_number": doc.sap_document_number,
                    "sent_to_sap_at": doc.sent_to_sap_at.isoformat() if doc.sent_to_sap_at else None
                }
                for doc in documents
            ]
        }

