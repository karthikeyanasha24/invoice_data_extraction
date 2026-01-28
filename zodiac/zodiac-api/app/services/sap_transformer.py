"""
SAP Transformer Service
Transforms SAT canonical merged documents into SAP ECC XML format.
Also transforms to client's JSON format for bulk sending.
"""
import logging
from typing import Dict, List, Any
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from ..models.sat_canonical_merged import SATCanonicalMerged
from ..models.sat_simple_merged import SATSimpleMerged
from ..models.sat_document import SATDocument
from ..models.sat_supplier_account_mapping import SATSupplierAccountMapping

logger = logging.getLogger("zodiac-api.sap_transformer")


class SAPTransformer:
    """Transform canonical documents to SAP XML format"""
    
    def __init__(self, db: Session = None):
        self.db = db
    
    def _to_float(self, value) -> float:
        """Safely convert any value to float"""
        if value is None or value == '':
            return 0.0
        try:
            # Handle string conversion
            if isinstance(value, str):
                # Remove any currency symbols, commas, etc.
                cleaned = value.replace(',', '').replace('$', '').strip()
                return float(cleaned)
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    def _clean_numeric(self, value, precision: int = 2) -> float:
        """Convert numeric value to clean float with specified precision"""
        return round(self._to_float(value), precision)
    
    def _datetime_to_int(self, dt: datetime = None) -> int:
        """Convert datetime to integer format: YYYYMMDDHHmmss"""
        if dt is None:
            dt = datetime.now()
        return int(dt.strftime("%Y%m%d%H%M%S"))
    
    def _get_supplier_mapping(self, supplier_rfc: str):
        """Fetch supplier account mapping from database"""
        if not self.db:
            return None
        try:
            return self.db.query(SATSupplierAccountMapping).filter(
                SATSupplierAccountMapping.supplier_rfc == supplier_rfc.upper(),
                SATSupplierAccountMapping.is_active == True
            ).first()
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch mapping for {supplier_rfc}: {e}")
            return None
    
    def transform_canonical_to_sap_xml(self, canonical: SATCanonicalMerged) -> str:
        """
        Transform a canonical merged document to SAP XML format.
        Returns XML string ready to send to SAP.
        """
        try:
            # Fetch linked documents to get CFDI details
            cfdi_details = []
            if self.db and canonical.linked_document_ids:
                linked_docs = self.db.query(SATDocument).filter(
                    SATDocument.id.in_([str(doc_id) for doc_id in canonical.linked_document_ids])
                ).all()
                
                # Build detailed CFDI list with types
                for doc in linked_docs:
                    cfdi_details.append({
                        'UUID': doc.cfdi_uuid,
                        'TYPE': doc.doc_type,
                        'TOTAL': str(doc.total) if doc.total else '0.00',
                        'CURRENCY': doc.moneda or 'MXN',
                        'DATE': doc.fecha.isoformat() if doc.fecha else ''
                    })
            
            # Build invoice data dictionary
            invoice_data = {
                'INVOICE': {
                    'COMPANY_CODE': canonical.company_code or 'MX01',
                    'VENDOR_RFC': canonical.vendor_rfc,
                    'VENDOR_NAME': canonical.vendor_name or '',
                    'FISCAL_YEAR': str(canonical.fiscal_year),
                    'FISCAL_PERIOD': str(canonical.fiscal_period).zfill(2),
                    'CURRENCY': canonical.currency or 'MXN',
                    'TOTAL_INVOICES': str(canonical.total_invoices or '0.00'),
                    'TOTAL_CREDITS': str(canonical.total_credits or '0.00'),
                    'TOTAL_PAYMENTS': str(canonical.total_payments or '0.00'),
                    'NET_AMOUNT': str(canonical.net_amount or '0.00'),
                    'GL_ACCOUNT': canonical.sap_gl_account or '',
                    'PAYMENT_METHOD': canonical.payment_method or 'PPD',
                    'CFDI_UUIDS': ','.join(canonical.cfdi_uuids or []),
                    'CFDI_DETAILS': cfdi_details,  # Add detailed CFDI info
                    'RELATED_UUIDS': ','.join(canonical.related_cfdi_uuids or []),
                    'DOCUMENT_COUNT': str(len(canonical.linked_document_ids or [])),
                    'PORTAL_REF_ID': str(canonical.id)
                }
            }
            
            # Convert to XML
            xml = self._dict_to_xml(invoice_data)
            
            logger.info(f"✅ Transformed canonical {canonical.id} to SAP XML ({len(xml)} bytes)")
            return xml
            
        except Exception as e:
            logger.error(f"❌ Failed to transform canonical to SAP XML: {e}")
            raise
    
    def _dict_to_xml(self, data: Dict, root_name: str = 'SAP_CANONICAL_DOCUMENT') -> str:
        """Convert dictionary to XML string"""
        xml_parts = [f'<?xml version="1.0" encoding="UTF-8"?>']
        xml_parts.append(f'<{root_name}>')
        
        for key, value in data.items():
            if isinstance(value, dict):
                xml_parts.append(f'  <{key}>')
                for sub_key, sub_value in value.items():
                    # Handle CFDI_DETAILS as a list of CFDI elements
                    if sub_key == 'CFDI_DETAILS' and isinstance(sub_value, list):
                        xml_parts.append(f'    <{sub_key}>')
                        for cfdi in sub_value:
                            xml_parts.append(f'      <CFDI>')
                            for cfdi_key, cfdi_val in cfdi.items():
                                xml_parts.append(f'        <{cfdi_key}>{self._escape_xml(str(cfdi_val))}</{cfdi_key}>')
                            xml_parts.append(f'      </CFDI>')
                        xml_parts.append(f'    </{sub_key}>')
                    elif isinstance(sub_value, list):
                        # Handle other lists (if any)
                        xml_parts.append(f'    <{sub_key}>')
                        for item in sub_value:
                            xml_parts.append(f'      <ITEM>{self._escape_xml(str(item))}</ITEM>')
                        xml_parts.append(f'    </{sub_key}>')
                    else:
                        xml_parts.append(f'    <{sub_key}>{self._escape_xml(str(sub_value))}</{sub_key}>')
                xml_parts.append(f'  </{key}>')
            else:
                xml_parts.append(f'  <{key}>{self._escape_xml(str(value))}</{key}>')
        
        xml_parts.append(f'</{root_name}>')
        return '\n'.join(xml_parts)
    
    def _escape_xml(self, text: str) -> str:
        """Escape special XML characters"""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))
    
    def transform_canonical_to_sap_format(self, canonical: SATCanonicalMerged) -> List[Dict[str, Any]]:
        """
        Transform canonical document to client's JSON format.
        Returns a list of documents (one canonical document).
        Follows format from client's 'multiplefiles' example.
        """
        try:
            # Fetch supplier mapping data
            mapping = self._get_supplier_mapping(canonical.vendor_rfc)
            
            # Fetch linked documents to build items
            items = []
            if self.db and canonical.linked_document_ids:
                linked_docs = self.db.query(SATDocument).filter(
                    SATDocument.id.in_([str(doc_id) for doc_id in canonical.linked_document_ids])
                ).all()
                
                for idx, doc in enumerate(linked_docs, 1):
                    # Convert string fields to floats safely
                    doc_subtotal = self._to_float(doc.subtotal)
                    doc_total = self._to_float(doc.total)
                    doc_tax = doc_total - doc_subtotal
                    
                    item = {
                        "DS_UUID": doc.cfdi_uuid,
                        "DOCUMENT_TYPE": "C",  # Canonical
                        "DOC_NUMBER": doc.folio or "",
                        "DOC_ITEM_NO": str(idx),
                        "AMOUNT": 0,
                        "PRODUCTID": "",
                        "DESCRIPTION": f"{doc.doc_type} - {doc.serie}-{doc.folio}",
                        "PRODUCTSERVICECODE": "",
                        "QUANTITY": 1.000,
                        "TAXOBJECT": "",
                        "UNITCODE": "",
                        "UNITDESCRIPTION": "",
                        "UNITPRICE": self._clean_numeric(doc_total),
                        "LINEAMOUNT": self._clean_numeric(doc_total),
                        "TAXTYPE": "",
                        "TAXRATE": 0.16,
                        "BASEAMOUNT": self._clean_numeric(doc_subtotal),
                        "TAXAMOUNT": self._clean_numeric(doc_tax)
                    }
                    items.append(item)
            
            # Build canonical document in client's format
            doc = {
                "DS_UUID": str(canonical.id),
                "DOCUMENT_TYPE": "C",  # C for Canonical
                "DOC_NUMBER": f"{canonical.fiscal_year}{canonical.fiscal_period:02d}",
                "VERSION": "4.0",
                "ISSUE_DATETIME": self._datetime_to_int(),  # Integer format
                "DOC_SERIES": f"CANONICAL_{canonical.fiscal_year}",
                "CURRENCY": canonical.currency or "MXN",
                "EXCHANGE_RATE": 1.00000,  # 5 decimals like client's example
                "SUBTOTAL_AMOUNT": self._clean_numeric(canonical.net_amount or 0),
                "TOTAL_AMOUNT": self._clean_numeric(canonical.net_amount or 0),
                "PAYMENT_METHOD_CODE": "99",
                "PAYMENT_METHOD": canonical.payment_method or "PPD",
                "PAYMENT_CONDITION": "",
                "PLACE_OF_ISSUE_ZIP": "",
                "EXPORT_INDICATOR": "01",
                "DIGITAL_CERTIFICATE": "",
                "CERTIFICATE_NUMBER": "",
                "ISSUER_NAME": canonical.vendor_name or "",
                "ISSUER_TAX_ID": canonical.vendor_rfc,
                "ISSUER_TAX_REGION": "601",
                "RECEIVER_NAME": "",
                "RECEIVER_TAX_ID": "",
                "RECEIVER_CFDI_USER": "G03",
                "RECEIVER_TAX_ZIP": "",
                "RECEIVER_TAX_REGION": "601",
                "PAYMENT_AMOUNT": 0,
                "PAYMENT_CURRENCY": "",
                "TOTAL_TRANSFERRED": self._clean_numeric(0),
                "TAX_TYPE": "VAT",
                "TAX_CODE": "",
                "TAX_RATE": 0.16,
                "TAX_BASE_AMOUNT": self._clean_numeric(canonical.net_amount or 0),
                "TAX_AMOUNT": 0,
                "TAX_RATE_TYPE": "RATE",
                "CERT_PROVIDER_TAX": "",
                "DS_STAMP_DATETIME": self._datetime_to_int(),  # Integer format
                "DS_SAT_CERT_NUMBER": "",
                "DS_CFDI_SEAL": "",
                # New mapping fields
                "COMPANY_CODE": mapping.company_code if mapping else "",
                "GL_ACCOUNT": mapping.sap_gl_account if mapping else canonical.sap_gl_account or "",
                "FISCAL_YEAR": mapping.fiscal_year if mapping else canonical.fiscal_year,
                "CURRENCY_MAPPING": mapping.currency if mapping else canonical.currency or "MXN",
                "OPENING_BALANCE": self._clean_numeric(mapping.opening_balance if mapping else 0),
                "CREDIT_AMOUNT": self._clean_numeric(mapping.credit_amount if mapping else 0),
                "DEBIT_AMOUNT": self._clean_numeric(mapping.debit_amount if mapping else 0),
                "CLOSING_BALANCE": self._clean_numeric(mapping.closing_balance if mapping else 0),
                "ITEMS": items
            }
            
            return [doc]  # Return as list (canonical = 1 document)
            
        except Exception as e:
            logger.error(f"❌ Failed to transform canonical to SAP format: {e}")
            raise
    
    def transform_simple_to_sap_format(self, simple: SATSimpleMerged) -> List[Dict[str, Any]]:
        """
        Transform simple merged document to client's JSON format.
        Returns a list of documents (all individual CFDI documents).
        Follows format from client's 'multiplefiles' example.
        """
        try:
            documents = []
            
            # Fetch all linked documents
            if self.db and simple.cfdi_uuids:
                linked_docs = self.db.query(SATDocument).filter(
                    SATDocument.cfdi_uuid.in_(simple.cfdi_uuids)
                ).all()
                
                for sat_doc in linked_docs:
                    # Fetch supplier mapping data for each document
                    mapping = self._get_supplier_mapping(sat_doc.supplier_rfc or "")
                    
                    # Map doc_type to client's format
                    doc_type_map = {
                        'I': 'I',  # Invoice
                        'E': 'C',  # Credit Note (Egreso) -> C in client format
                        'P': 'P',  # Payment
                        'T': 'I',  # Traslado -> I
                        'N': 'I'   # Nomina -> I
                    }
                    doc_type = doc_type_map.get(sat_doc.doc_type, 'I')
                    
                    # Safely convert all string fields to proper types FIRST
                    subtotal_val = self._to_float(sat_doc.subtotal)
                    total_val = self._to_float(sat_doc.total)
                    tipo_cambio_val = self._to_float(sat_doc.tipo_cambio) if sat_doc.tipo_cambio else 1.0
                    tax_amount = total_val - subtotal_val
                    
                    # Build items list
                    items = [{
                        "DS_UUID": sat_doc.cfdi_uuid,
                        "DOCUMENT_TYPE": doc_type,
                        "DOC_NUMBER": sat_doc.folio or "",
                        "DOC_ITEM_NO": "1",
                        "AMOUNT": 0,
                        "PRODUCTID": "",
                        "DESCRIPTION": sat_doc.supplier_name or "Document",
                        "PRODUCTSERVICECODE": "",
                        "QUANTITY": 1.000,
                        "TAXOBJECT": "",
                        "UNITCODE": "",
                        "UNITDESCRIPTION": "",
                        "UNITPRICE": self._clean_numeric(subtotal_val),
                        "LINEAMOUNT": self._clean_numeric(subtotal_val),
                        "TAXTYPE": "",
                        "TAXRATE": 0.16,
                        "BASEAMOUNT": self._clean_numeric(subtotal_val),
                        "TAXAMOUNT": self._clean_numeric(tax_amount)
                    }]
                    
                    doc = {
                        "DS_UUID": sat_doc.cfdi_uuid,
                        "DOCUMENT_TYPE": doc_type,
                        "DOC_NUMBER": sat_doc.folio or "",
                        "VERSION": "4.0",
                        "ISSUE_DATETIME": self._datetime_to_int(sat_doc.fecha) if sat_doc.fecha else self._datetime_to_int(),
                        "DOC_SERIES": sat_doc.serie or "",
                        "CURRENCY": sat_doc.moneda or "MXN",
                        "EXCHANGE_RATE": round(tipo_cambio_val, 5),  # 5 decimals: 19.48000
                        "SUBTOTAL_AMOUNT": self._clean_numeric(subtotal_val),
                        "TOTAL_AMOUNT": self._clean_numeric(total_val),
                        "PAYMENT_METHOD_CODE": sat_doc.forma_pago or "99",
                        "PAYMENT_METHOD": sat_doc.metodo_pago or "PPD",
                        "PAYMENT_CONDITION": "",
                        "PLACE_OF_ISSUE_ZIP": "",
                        "EXPORT_INDICATOR": "01",
                        "DIGITAL_CERTIFICATE": "",
                        "CERTIFICATE_NUMBER": "",
                        "ISSUER_NAME": sat_doc.supplier_name or "",
                        "ISSUER_TAX_ID": sat_doc.supplier_rfc or "",
                        "ISSUER_TAX_REGION": "601",
                        "RECEIVER_NAME": sat_doc.receiver_name or "",
                        "RECEIVER_TAX_ID": sat_doc.receiver_rfc or "",
                        "RECEIVER_CFDI_USER": "G03",
                        "RECEIVER_TAX_ZIP": "",
                        "RECEIVER_TAX_REGION": "601",
                        "PAYMENT_AMOUNT": 0,
                        "PAYMENT_CURRENCY": "",
                        "TOTAL_TRANSFERRED": self._clean_numeric(0),
                        "TAX_TYPE": "VAT",
                        "TAX_CODE": "",
                        "TAX_RATE": 0.16,
                        "TAX_BASE_AMOUNT": self._clean_numeric(subtotal_val),
                        "TAX_AMOUNT": 0,
                        "TAX_RATE_TYPE": "RATE",
                        "CERT_PROVIDER_TAX": "",
                        "DS_STAMP_DATETIME": self._datetime_to_int(),
                        "DS_SAT_CERT_NUMBER": "",
                        "DS_CFDI_SEAL": "",
                        "ITEMS": items
                    }
                    
                    documents.append(doc)
            
            return documents  # Return list of all documents
            
        except Exception as e:
            logger.error(f"❌ Failed to transform simple to SAP format: {e}")
            raise

