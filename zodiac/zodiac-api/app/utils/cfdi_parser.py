"""
CFDI XML Parser Utility
Parses Mexican CFDI (Comprobante Fiscal Digital por Internet) XML documents
Supports versions 3.3 and 4.0
"""
import logging
from lxml import etree
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger("zodiac-api.cfdi_parser")

# CFDI XML Namespaces
NAMESPACES = {
    'cfdi': 'http://www.sat.gob.mx/cfd/3',
    'cfdi4': 'http://www.sat.gob.mx/cfd/4',
    'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital',
    'pago20': 'http://www.sat.gob.mx/Pagos20',
    'pago10': 'http://www.sat.gob.mx/Pagos'
}


class CFDIParser:
    """Parser for CFDI XML documents"""
    
    @staticmethod
    def parse_cfdi(xml_content: str) -> Dict:
        """
        Parse CFDI XML and extract key fields.
        Returns a dictionary with extracted data.
        """
        try:
            # Parse XML
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Detect CFDI version
            version = root.get('Version', '3.3')
            ns_prefix = 'cfdi4' if version.startswith('4') else 'cfdi'
            
            # Determine document type
            tipo_comprobante = root.get('TipoDeComprobante', 'I')
            doc_type = CFDIParser._map_tipo_comprobante(tipo_comprobante)
            
            # Extract basic data
            data = {
                'version': version,
                'doc_type': doc_type,
                'tipo_comprobante': tipo_comprobante,
                'serie': root.get('Serie'),
                'folio': root.get('Folio'),
                'fecha': CFDIParser._parse_datetime(root.get('Fecha')),
                'subtotal': root.get('SubTotal'),
                'total': root.get('Total'),
                'moneda': root.get('Moneda', 'MXN'),
                'tipo_cambio': root.get('TipoCambio'),
                'forma_pago': root.get('FormaPago'),
                'metodo_pago': root.get('MetodoPago'),
                'lugar_expedicion': root.get('LugarExpedicion'),
            }
            
            # Debug logging for total extraction
            if not data.get('total'):
                import logging
                logger = logging.getLogger('zodiac-api.cfdi_parser')
                logger.warning(f"⚠️ Total not found in CFDI root. Root attributes: {root.attrib}")
            
            # Extract Emisor (Supplier)
            emisor = root.find(f'{ns_prefix}:Emisor', NAMESPACES)
            if emisor is not None:
                data['supplier_rfc'] = emisor.get('Rfc')
                data['supplier_name'] = emisor.get('Nombre')
                data['supplier_regimen'] = emisor.get('RegimenFiscal')
            
            # Extract Receptor (Receiver)
            receptor = root.find(f'{ns_prefix}:Receptor', NAMESPACES)
            if receptor is not None:
                data['receiver_rfc'] = receptor.get('Rfc')
                data['receiver_name'] = receptor.get('Nombre')
                data['receiver_uso_cfdi'] = receptor.get('UsoCFDI')
                data['receiver_domicilio'] = receptor.get('DomicilioFiscalReceptor')
            
            # Extract UUID from TimbreFiscalDigital
            complemento = root.find(f'{ns_prefix}:Complemento', NAMESPACES)
            if complemento is not None:
                tfd = complemento.find('tfd:TimbreFiscalDigital', NAMESPACES)
                if tfd is not None:
                    data['cfdi_uuid'] = tfd.get('UUID')
                    data['fecha_timbrado'] = CFDIParser._parse_datetime(tfd.get('FechaTimbrado'))
                
                # Check for payment complement
                pago = complemento.find('pago20:Pagos', NAMESPACES)
                if pago is None:
                    pago = complemento.find('pago10:Pagos', NAMESPACES)
                
                if pago is not None:
                    data['has_payment_complement'] = True
                    data['payment_data'] = CFDIParser._extract_payment_data(pago)
            
            # Extract related documents (for credit notes and payments)
            relacionados = root.find(f'{ns_prefix}:CfdiRelacionados', NAMESPACES)
            if relacionados is not None:
                related_uuids = []
                for rel in relacionados.findall(f'{ns_prefix}:CfdiRelacionado', NAMESPACES):
                    uuid = rel.get('UUID')
                    if uuid:
                        related_uuids.append(uuid)
                data['related_cfdi_uuids'] = related_uuids
                data['tipo_relacion'] = relacionados.get('TipoRelacion')
            
            # Extract line items (Conceptos)
            conceptos = root.find(f'{ns_prefix}:Conceptos', NAMESPACES)
            if conceptos is not None:
                data['line_items'] = CFDIParser._extract_line_items(conceptos, ns_prefix)
            
            # Calculate fiscal period
            if data.get('fecha'):
                data['fiscal_year'] = data['fecha'].year
                data['fiscal_period'] = data['fecha'].month
            
            return data
            
        except Exception as e:
            logger.error(f"❌ Failed to parse CFDI XML: {e}")
            raise ValueError(f"Invalid CFDI XML: {str(e)}")
    
    @staticmethod
    def _map_tipo_comprobante(tipo: str) -> str:
        """Map TipoDeComprobante to our internal doc_type"""
        mapping = {
            'I': 'INVOICE',         # Ingreso (Invoice)
            'E': 'CREDIT_NOTE',     # Egreso (Credit Note)
            'P': 'PAYMENT',         # Pago (Payment)
            'T': 'TRANSFER',        # Traslado (Transfer)
            'N': 'PAYROLL'          # Nómina (Payroll)
        }
        return mapping.get(tipo, 'UNKNOWN')
    
    @staticmethod
    def _parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
        """Parse CFDI datetime string"""
        if not date_str:
            return None
        
        try:
            # Try ISO format first
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            try:
                # Try common CFDI format
                return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S')
            except:
                logger.warning(f"Could not parse date: {date_str}")
                return None
    
    @staticmethod
    def _extract_line_items(conceptos_node, ns_prefix: str) -> List[Dict]:
        """Extract line items from Conceptos node"""
        items = []
        
        for concepto in conceptos_node.findall(f'{ns_prefix}:Concepto', NAMESPACES):
            item = {
                'clave_prod_serv': concepto.get('ClaveProdServ'),
                'no_identificacion': concepto.get('NoIdentificacion'),
                'cantidad': concepto.get('Cantidad'),
                'clave_unidad': concepto.get('ClaveUnidad'),
                'unidad': concepto.get('Unidad'),
                'descripcion': concepto.get('Descripcion'),
                'valor_unitario': concepto.get('ValorUnitario'),
                'importe': concepto.get('Importe'),
                'descuento': concepto.get('Descuento')
            }
            items.append(item)
        
        return items
    
    @staticmethod
    def _extract_payment_data(pago_node) -> Dict:
        """Extract payment complement data"""
        payment_data = {}
        
        # Check if it's Pagos 2.0 or 1.0
        ns = 'pago20' if 'Pagos20' in pago_node.tag else 'pago10'
        
        pagos = pago_node.findall(f'{ns}:Pago', NAMESPACES)
        if pagos:
            pago = pagos[0]  # Get first payment
            payment_data['fecha_pago'] = pago.get('FechaPago')
            payment_data['forma_pago'] = pago.get('FormaDePagoP')
            payment_data['moneda'] = pago.get('MonedaP')
            payment_data['monto'] = pago.get('Monto')
            
            # Extract related documents
            doc_relacionados = pago.findall(f'{ns}:DoctoRelacionado', NAMESPACES)
            related_docs = []
            for doc in doc_relacionados:
                related_docs.append({
                    'id_documento': doc.get('IdDocumento'),
                    'moneda': doc.get('MonedaDR'),
                    'metodo_pago': doc.get('MetodoDePagoDR'),
                    'imp_saldo_ant': doc.get('ImpSaldoAnt'),
                    'imp_pagado': doc.get('ImpPagado'),
                    'imp_saldo_insoluto': doc.get('ImpSaldoInsoluto')
                })
            payment_data['related_documents'] = related_docs
        
        return payment_data
    
    @staticmethod
    def validate_cfdi_structure(xml_content: str) -> tuple[bool, Optional[str]]:
        """
        Validate basic CFDI XML structure.
        Returns (is_valid, error_message)
        """
        try:
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Check for Comprobante root
            if 'Comprobante' not in root.tag:
                return False, "Root element must be 'Comprobante'"
            
            # Check for Version attribute
            version = root.get('Version')
            if not version:
                return False, "Missing 'Version' attribute"
            
            # Check for required elements
            ns_prefix = 'cfdi4' if version.startswith('4') else 'cfdi'
            
            emisor = root.find(f'{ns_prefix}:Emisor', NAMESPACES)
            if emisor is None:
                return False, "Missing 'Emisor' element"
            
            receptor = root.find(f'{ns_prefix}:Receptor', NAMESPACES)
            if receptor is None:
                return False, "Missing 'Receptor' element"
            
            # Check for UUID in TimbreFiscalDigital
            complemento = root.find(f'{ns_prefix}:Complemento', NAMESPACES)
            if complemento is not None:
                tfd = complemento.find('tfd:TimbreFiscalDigital', NAMESPACES)
                if tfd is not None:
                    uuid = tfd.get('UUID')
                    if not uuid:
                        return False, "Missing UUID in TimbreFiscalDigital"
                else:
                    return False, "Missing TimbreFiscalDigital in Complemento"
            else:
                return False, "Missing Complemento element"
            
            return True, None
            
        except etree.XMLSyntaxError as e:
            return False, f"XML syntax error: {str(e)}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

