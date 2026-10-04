"""
SAT Canonical Merge Service
Merges multiple SAT documents (INVOICE, PAYMENT, CREDIT_NOTE) into a single canonical document
based on vendor RFC, fiscal year, and fiscal period.
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Numeric
from datetime import datetime
from decimal import Decimal
import uuid

from ..models.sat_document import SATDocument
from ..models.sat_canonical_merged import SATCanonicalMerged
from ..services.sat_supplier_mapping_service import SATSupplierMappingService

logger = logging.getLogger("zodiac-api.sat_canonical_merge")


class SATCanonicalMergeService:
    def __init__(self, db: Session):
        self.db = db
        self.supplier_mapping_service = SATSupplierMappingService(db)
    
    def merge_documents_for_period(
        self,
        user_id: int,
        company_code: str,
        fiscal_year: int,
        fiscal_period: int
    ) -> dict:
        """
        Merge all VALIDATED SAT documents for the given period by vendor RFC.
        Returns a summary of merged documents.
        """
        logger.info(f"🔄 Starting canonical merge for {fiscal_year}-{fiscal_period}")
        
        # Get all VALIDATED documents for this period
        documents = self.db.query(SATDocument).filter(
            SATDocument.user_id == user_id,
            SATDocument.fiscal_year == fiscal_year,
            SATDocument.fiscal_period == fiscal_period,
            SATDocument.status == 'VALIDATED',
            SATDocument.canonical_merged_id == None
        ).all()
        
        if not documents:
            logger.warning(f"⚠️ No VALIDATED documents found for {fiscal_year}-{fiscal_period}")
            return {"total": 0, "documents": []}
        
        logger.info(f"📋 Found {len(documents)} documents to merge")
        
        # Group by vendor RFC
        vendors = {}
        for doc in documents:
            if doc.supplier_rfc not in vendors:
                vendors[doc.supplier_rfc] = []
            vendors[doc.supplier_rfc].append(doc)
        
        logger.info(f"👥 Grouping into {len(vendors)} vendors")
        
        # Merge each vendor's documents
        merged_docs = []
        for vendor_rfc, vendor_docs in vendors.items():
            try:
                canonical = self._merge_vendor_documents(
                    user_id, company_code, fiscal_year, fiscal_period,
                    vendor_rfc, vendor_docs
                )
                merged_docs.append(canonical)
                logger.info(f"✅ Merged {len(vendor_docs)} docs for vendor {vendor_rfc}")
            except Exception as e:
                logger.error(f"❌ Failed to merge docs for vendor {vendor_rfc}: {e}")
                continue
        
        return {
            "total": len(merged_docs),
            "documents": [
                {
                    "id": str(doc.id),
                    "vendor_rfc": doc.vendor_rfc,
                    "vendor_name": doc.vendor_name,
                    "fiscal_year": doc.fiscal_year,
                    "fiscal_period": doc.fiscal_period,
                    "total_invoices": float(doc.total_invoices or 0),
                    "total_credits": float(doc.total_credits or 0),
                    "total_payments": float(doc.total_payments or 0),
                    "net_amount": float(doc.net_amount or 0),
                    "currency": doc.currency,
                    "sap_gl_account": doc.sap_gl_account,
                    "status": doc.status,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None
                }
                for doc in merged_docs
            ]
        }
    
    def _merge_vendor_documents(
        self,
        user_id: int,
        company_code: str,
        fiscal_year: int,
        fiscal_period: int,
        vendor_rfc: str,
        documents: List[SATDocument]
    ) -> SATCanonicalMerged:
        """Merge documents for a single vendor into canonical format."""
        
        # Calculate aggregated amounts
        total_invoices = Decimal('0')
        total_credits = Decimal('0')
        total_payments = Decimal('0')
        
        cfdi_uuids = []
        related_uuids = []
        doc_ids = []
        vendor_name = None
        currency = 'MXN'
        payment_method = None
        
        for doc in documents:
            doc_ids.append(str(doc.id))
            cfdi_uuids.append(doc.cfdi_uuid)
            
            if doc.related_cfdi_uuid:
                related_uuids.append(doc.related_cfdi_uuid)
            
            if not vendor_name and doc.supplier_name:
                vendor_name = doc.supplier_name
            
            if doc.moneda:
                currency = doc.moneda
            
            if doc.metodo_pago and not payment_method:
                payment_method = doc.metodo_pago
            
            # Parse amount
            try:
                amount = Decimal(doc.total) if doc.total else Decimal('0')
            except:
                amount = Decimal('0')
            
            # Aggregate by doc type
            if doc.doc_type == 'INVOICE':
                total_invoices += amount
            elif doc.doc_type == 'CREDIT_NOTE':
                total_credits += amount
            elif doc.doc_type == 'PAYMENT':
                total_payments += amount
        
        # Calculate net amount
        net_amount = total_invoices - total_credits - total_payments
        
        # Lookup SAP G/L Account mapping
        mapping = self.supplier_mapping_service.get_mapping_by_rfc(vendor_rfc)
        sap_gl_account = None
        if mapping:
            sap_gl_account = mapping.sap_gl_account
            logger.info(f"✅ Mapped RFC {vendor_rfc} to GL Account {sap_gl_account}")
        else:
            # Try to get default mapping
            default_mapping = self.supplier_mapping_service.get_or_create_default_mapping()
            if default_mapping:
                sap_gl_account = default_mapping.sap_gl_account
                logger.warning(f"⚠️ No mapping found for RFC {vendor_rfc}. Using default GL Account {sap_gl_account}")
        
        # Create canonical merged document
        canonical = SATCanonicalMerged(
            id=uuid.uuid4(),
            user_id=user_id,
            company_code=company_code,
            vendor_rfc=vendor_rfc,
            vendor_name=vendor_name,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            total_invoices=total_invoices,
            total_credits=total_credits,
            total_payments=total_payments,
            net_amount=net_amount,
            currency=currency,
            payment_method=payment_method,
            cfdi_uuids=cfdi_uuids,
            related_cfdi_uuids=related_uuids,
            linked_document_ids=doc_ids,
            sap_gl_account=sap_gl_account,
            status='MERGED'
        )
        
        self.db.add(canonical)
        
        # Update source documents
        for doc in documents:
            doc.canonical_merged_id = canonical.id
            doc.merged_at = datetime.utcnow()
            doc.status = 'MERGED'
        
        self.db.commit()
        self.db.refresh(canonical)
        
        return canonical
    
    def get_canonical_documents(
        self,
        user_id: int,
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[int] = None,
        skip: int = 0,
        limit: int = 100
    ) -> dict:
        """Get list of canonical merged documents."""
        
        query = self.db.query(SATCanonicalMerged).filter(
            SATCanonicalMerged.user_id == user_id
        )
        
        if fiscal_year:
            query = query.filter(SATCanonicalMerged.fiscal_year == fiscal_year)
        if fiscal_period:
            query = query.filter(SATCanonicalMerged.fiscal_period == fiscal_period)
        
        total = query.count()
        documents = query.order_by(
            SATCanonicalMerged.fiscal_year.desc(),
            SATCanonicalMerged.fiscal_period.desc(),
            SATCanonicalMerged.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return {
            "total": total,
            "documents": [
                {
                    "id": str(doc.id),
                    "vendor_rfc": doc.vendor_rfc,
                    "vendor_name": doc.vendor_name,
                    "fiscal_year": doc.fiscal_year,
                    "fiscal_period": doc.fiscal_period,
                    "total_invoices": float(doc.total_invoices or 0),
                    "total_credits": float(doc.total_credits or 0),
                    "total_payments": float(doc.total_payments or 0),
                    "net_amount": float(doc.net_amount or 0),
                    "currency": doc.currency,
                    "sap_gl_account": doc.sap_gl_account,
                    "status": doc.status,
                    "sap_document_number": doc.sap_document_number,
                    "sent_to_sap_at": doc.sent_to_sap_at.isoformat() if doc.sent_to_sap_at else None,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None
                }
                for doc in documents
            ]
        }
    
    def get_canonical_by_id(self, user_id: int, canonical_id: str) -> Optional[SATCanonicalMerged]:
        """Get a single canonical document by ID."""
        try:
            canonical_uuid = uuid.UUID(canonical_id)
        except ValueError:
            return None
        
        return self.db.query(SATCanonicalMerged).filter(
            SATCanonicalMerged.id == canonical_uuid,
            SATCanonicalMerged.user_id == user_id
        ).first()

