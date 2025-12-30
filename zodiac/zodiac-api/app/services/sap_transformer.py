"""
SAP Transformer Service
Transforms SAT canonical merged documents into SAP ECC XML format.
"""
import logging
from typing import Dict
from decimal import Decimal
from ..models.sat_canonical_merged import SATCanonicalMerged

logger = logging.getLogger("zodiac-api.sap_transformer")


class SAPTransformer:
    """Transform canonical documents to SAP XML format"""
    
    def transform_canonical_to_sap_xml(self, canonical: SATCanonicalMerged) -> str:
        """
        Transform a canonical merged document to SAP XML format.
        Returns XML string ready to send to SAP.
        """
        try:
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

