"""
SAT Canonical Merge Service
Merges 3 SAT documents (INVOICE, PAYMENT, CREDIT_NOTE) into 1 canonical format for SAP
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Dict, Optional
from datetime import datetime
import logging
from decimal import Decimal
import uuid

from app.models.sat_document import SATDocument, DocumentType
from app.models.sat_canonical_merged import SATCanonicalMerged
from app.services.sat_supplier_mapping_service import SATSupplierMappingService

logger = logging.getLogger(__name__)


class SATCanonicalMergeService:
    """
    Merges multiple SAT documents into ONE canonical document for SAP.
    
    Flow:
    1. Fetch all INVOICE, PAYMENT, CREDIT_NOTE for a vendor + period
    2. Extract and aggregate all canonical fields
    3. Create ONE merged document with:
       - All CFDIs listed
       - Aggregated amounts (invoices - credits - payments)
       - Tax information
       - Payment details
       - Line items from all documents
    4. Send to SAP as ONE unified XML
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def merge_documents_for_period(
        self,
        user_id: int,
        company_code: str,
        fiscal_year: int,
        fiscal_period: int
    ) -> List[SATCanonicalMerged]:
        """
        Merge all SAT documents for a given period into canonical format.
        Creates ONE canonical document per vendor.
        
        Args:
            user_id: User ID
            company_code: Company code (e.g., "MX01")
            fiscal_year: Year (e.g., 2025)
            fiscal_period: Month 1-12 (e.g., 12 for December)
            
        Returns:
            List of canonical merged documents (one per vendor)
        """
        logger.info(f"🔄 Merging SAT documents for {company_code} {fiscal_year}-{fiscal_period:02d}")
        
        # Fetch all documents for this period
        # Include more statuses to allow merging even if some were already sent
        documents = self.db.query(SATDocument).filter(
            SATDocument.user_id == user_id,
            SATDocument.company_code == company_code,
            extract('year', SATDocument.fecha) == fiscal_year,
            extract('month', SATDocument.fecha) == fiscal_period,
            SATDocument.is_duplicate == False,
            SATDocument.status.in_(['VALIDATED', 'NORMALIZED', 'ENRICHING', 'READY_FOR_SAP', 'SENT_TO_SAP', 'SAP_CONFIRMED'])
        ).all()
        
        if not documents:
            logger.info(f"⚠️ No documents found for {fiscal_year}-{fiscal_period:02d}")
            return []
        
        # Group by vendor
        vendor_groups: Dict[str, List[SATDocument]] = {}
        for doc in documents:
            vendor_groups.setdefault(doc.supplier_rfc, []).append(doc)
        
        merged_documents = []
        
        for vendor_rfc, vendor_docs in vendor_groups.items():
            logger.info(f"📦 Merging {len(vendor_docs)} documents for vendor {vendor_rfc}")
            
            canonical = self._merge_vendor_documents(
                user_id=user_id,
                company_code=company_code,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                vendor_rfc=vendor_rfc,
                documents=vendor_docs
            )
            
            merged_documents.append(canonical)
        
        logger.info(f"✅ Created {len(merged_documents)} canonical merged documents")
        return merged_documents
    
    def _merge_vendor_documents(
        self,
        user_id: int,
        company_code: str,
        fiscal_year: int,
        fiscal_period: int,
        vendor_rfc: str,
        documents: List[SATDocument]
    ) -> SATCanonicalMerged:
        """
        Merge all documents for a single vendor into ONE canonical document.
        """
        # Initialize aggregated values
        cfdi_uuids = []
        related_cfdi_uuids = []
        linked_document_ids = []
        
        total_invoices = Decimal('0.00')
        total_credits = Decimal('0.00')
        total_payments = Decimal('0.00')
        total_tax_base = Decimal('0.00')
        total_tax_amount = Decimal('0.00')
        
        vendor_name = ""
        currency = "MXN"
        exchange_rate = Decimal('1.0')
        earliest_date = None
        latest_payment_date = None
        
        # Process each document
        for doc in documents:
            # Collect UUIDs
            if doc.cfdi_uuid:
                cfdi_uuids.append(doc.cfdi_uuid)
            linked_document_ids.append(str(doc.id))
            
            # Vendor info
            if not vendor_name and doc.supplier_name:
                vendor_name = doc.supplier_name
            
            # Currency
            if doc.moneda:
                currency = doc.moneda
            # Exchange rate defaults to 1.0 (no tipo_cambio field in model)
            
            # Dates
            if doc.fecha:
                if not earliest_date or doc.fecha < earliest_date:
                    earliest_date = doc.fecha
            
            # Aggregate amounts by document type
            doc_total = Decimal(str(doc.total or 0))
            doc_subtotal = Decimal(str(doc.subtotal or 0))
            
            if doc.document_type == DocumentType.INVOICE:
                total_invoices += doc_total
                total_tax_base += doc_subtotal
                
            elif doc.document_type == DocumentType.CREDIT_NOTE:
                total_credits += doc_total
                
            elif doc.document_type == DocumentType.PAYMENT:
                total_payments += doc_total
                if doc.fecha:
                    if not latest_payment_date or doc.fecha > latest_payment_date:
                        latest_payment_date = doc.fecha
                # Note: forma_pago field doesn't exist in model, skip payment method collection
                # Extract related invoice UUIDs from payment
                if doc.original_xml:
                    related_uuids = self._extract_related_uuids_from_payment(doc.original_xml)
                    related_cfdi_uuids.extend(related_uuids)
            
            # Collect line items (note: line_items_json field doesn't exist in current model)
            # Line items would need to be extracted from original_xml if needed
        
        # Calculate tax amount (estimate as difference between total and subtotal for invoices)
        total_tax_amount = total_invoices - total_tax_base
        
        # Calculate net amount
        net_amount = total_invoices - total_credits - total_payments
        
        # Amount signed (following SAP convention: positive = customer owes vendor)
        amount_signed = net_amount
        
        # Check if canonical document already exists for this vendor + period
        existing = self.db.query(SATCanonicalMerged).filter(
            SATCanonicalMerged.user_id == user_id,
            SATCanonicalMerged.company_code == company_code,
            SATCanonicalMerged.fiscal_year == fiscal_year,
            SATCanonicalMerged.fiscal_period == fiscal_period,
            SATCanonicalMerged.vendor_rfc == vendor_rfc
        ).first()
        
        if existing:
            # Update existing
            canonical = existing
            canonical.updated_at = datetime.utcnow()
        else:
            # Create new
            canonical = SATCanonicalMerged(
                id=uuid.uuid4(),
                user_id=user_id,
                company_code=company_code,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                vendor_rfc=vendor_rfc,
                created_at=datetime.utcnow()
            )
            self.db.add(canonical)
        
        # Populate canonical fields
        canonical.vendor_name = vendor_name
        canonical.cfdi_uuids = cfdi_uuids
        canonical.related_cfdi_uuids = list(set(related_cfdi_uuids)) if related_cfdi_uuids else []
        canonical.linked_document_ids = linked_document_ids
        canonical.doc_type = 'MERGED'
        canonical.doc_date = earliest_date
        canonical.posting_date = datetime.utcnow()
        canonical.currency = currency
        canonical.exchange_rate = exchange_rate
        canonical.total_invoices = total_invoices
        canonical.total_credits = total_credits
        canonical.total_payments = total_payments
        canonical.net_amount = net_amount
        canonical.amount_signed = amount_signed
        canonical.tax_base = total_tax_base
        canonical.tax_amount = total_tax_amount
        canonical.payment_date = latest_payment_date
        canonical.payment_method = None  # Payment method not available in current model
        canonical.line_items = []  # Line items not available in current model
        canonical.status = 'READY'
        canonical.merged_at = datetime.utcnow()
        canonical.received_ts = datetime.utcnow()
        
        # ✅ Lookup and apply SAP G/L Account mapping
        mapping_service = SATSupplierMappingService(self.db)
        mapping = mapping_service.get_mapping_by_rfc(vendor_rfc)
        
        if mapping:
            canonical.sap_gl_account = mapping.sap_gl_account
            logger.info(f"✅ Mapped RFC {vendor_rfc} → GL Account {mapping.sap_gl_account}")
        else:
            # Get or create default mapping
            default_mapping = mapping_service.get_or_create_default_mapping()
            canonical.sap_gl_account = default_mapping.sap_gl_account
            logger.warning(f"⚠️ No mapping found for RFC {vendor_rfc}, using default GL Account {default_mapping.sap_gl_account}")
        
        self.db.commit()
        self.db.refresh(canonical)
        
        logger.info(f"✅ Merged canonical: {vendor_rfc} | Net: {net_amount} {currency}")
        return canonical
    
    def _extract_related_uuids_from_payment(self, xml_content: str) -> List[str]:
        """
        Extract related invoice UUIDs from payment complement XML.
        """
        try:
            from lxml import etree
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Payment complement namespace
            ns = {
                'pago20': 'http://www.sat.gob.mx/Pagos20'
            }
            
            uuids = []
            for doc_relacionado in root.xpath('.//pago20:DoctoRelacionado', namespaces=ns):
                uuid_attr = doc_relacionado.get('IdDocumento')
                if uuid_attr:
                    uuids.append(uuid_attr)
            
            return uuids
        except Exception as e:
            logger.warning(f"⚠️ Could not extract related UUIDs from payment: {e}")
            return []
    
    def get_canonical_documents(
        self,
        user_id: int,
        company_code: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[int] = None,
        vendor_rfc: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Dict:
        """
        Get canonical merged documents with filters.
        """
        query = self.db.query(SATCanonicalMerged).filter(
            SATCanonicalMerged.user_id == user_id
        )
        
        if company_code:
            query = query.filter(SATCanonicalMerged.company_code == company_code)
        if fiscal_year:
            query = query.filter(SATCanonicalMerged.fiscal_year == fiscal_year)
        if fiscal_period:
            query = query.filter(SATCanonicalMerged.fiscal_period == fiscal_period)
        if vendor_rfc:
            query = query.filter(SATCanonicalMerged.vendor_rfc.ilike(f"%{vendor_rfc}%"))
        if status:
            query = query.filter(SATCanonicalMerged.status == status)
        
        total = query.count()
        documents = query.order_by(
            SATCanonicalMerged.fiscal_year.desc(),
            SATCanonicalMerged.fiscal_period.desc(),
            SATCanonicalMerged.vendor_rfc
        ).offset(skip).limit(limit).all()
        
        return {"total": total, "documents": documents}
    
    def get_canonical_by_id(self, user_id: int, canonical_id: str) -> Optional[SATCanonicalMerged]:
        """
        Get a single canonical document by ID.
        """
        return self.db.query(SATCanonicalMerged).filter(
            SATCanonicalMerged.user_id == user_id,
            SATCanonicalMerged.id == canonical_id
        ).first()
    
    def update_status(
        self,
        user_id: int,
        canonical_id: str,
        new_status: str,
        sap_response: Optional[Dict] = None
    ) -> Optional[SATCanonicalMerged]:
        """
        Update the status of a canonical document.
        """
        canonical = self.get_canonical_by_id(user_id, canonical_id)
        if canonical:
            canonical.status = new_status
            canonical.updated_at = datetime.utcnow()
            
            if new_status == 'SENT':
                canonical.sent_to_sap_at = datetime.utcnow()
            
            if sap_response:
                canonical.sap_response = sap_response
                if sap_response.get('documentNumber'):
                    canonical.sap_document_number = sap_response['documentNumber']
                if sap_response.get('fiscalYear'):
                    canonical.sap_fiscal_year = sap_response['fiscalYear']
                if new_status == 'CONFIRMED':
                    canonical.status = 'CONFIRMED'
            
            self.db.commit()
            self.db.refresh(canonical)
        
        return canonical

