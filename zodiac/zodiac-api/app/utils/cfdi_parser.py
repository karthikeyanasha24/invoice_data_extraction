"""
CFDI Parser - Mexican SAT Tax Document Parser
Supports CFDI 3.3 and 4.0
"""
from lxml import etree
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


# CFDI Namespaces
NAMESPACES_33 = {
    'cfdi': 'http://www.sat.gob.mx/cfd/3',
    'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital',
    'pago10': 'http://www.sat.gob.mx/Pagos',
    'pago20': 'http://www.sat.gob.mx/Pagos20'
}

NAMESPACES_40 = {
    'cfdi': 'http://www.sat.gob.mx/cfd/4',
    'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital',
    'pago10': 'http://www.sat.gob.mx/Pagos',
    'pago20': 'http://www.sat.gob.mx/Pagos20'
}


class CFDIParser:
    """
    Parser for Mexican CFDI (Comprobante Fiscal Digital por Internet)
    Extracts all relevant fields from CFDI XML documents
    """
    
    def __init__(self):
        self.namespaces = None
        self.version = None
    
    def parse(self, xml_content: str) -> Dict[str, Any]:
        """
        Parse CFDI XML and extract all fields
        
        Returns:
            Dictionary with extracted CFDI fields
        """
        try:
            # Parse XML
            if isinstance(xml_content, str):
                xml_bytes = xml_content.encode('utf-8')
            else:
                xml_bytes = xml_content
            
            root = etree.fromstring(xml_bytes)
            
            # Detect CFDI version
            self.version = self._detect_version(root)
            self.namespaces = NAMESPACES_40 if self.version == "4.0" else NAMESPACES_33
            
            logger.info(f"📄 Parsing CFDI version {self.version}")
            
            # Extract all sections
            result = {
                'version': self.version,
                'comprobante': self._parse_comprobante(root),
                'emisor': self._parse_emisor(root),
                'receptor': self._parse_receptor(root),
                'conceptos': self._parse_conceptos(root),
                'impuestos': self._parse_impuestos(root),
                'complemento': self._parse_complemento(root),
                'timbre_fiscal': self._parse_timbre_fiscal(root)
            }
            
            logger.info(f"✅ CFDI parsed successfully: UUID {result['timbre_fiscal'].get('UUID')}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error parsing CFDI: {e}")
            raise
    
    def _detect_version(self, root: etree.Element) -> str:
        """Detect CFDI version from XML"""
        version = root.get('Version') or root.get('version')
        if version:
            return version
        
        # Try to detect from namespace
        namespace = root.nsmap.get(None) or root.nsmap.get('cfdi')
        if namespace and 'cfd/4' in namespace:
            return "4.0"
        elif namespace and 'cfd/3' in namespace:
            return "3.3"
        
        return "3.3"  # Default
    
    def _parse_comprobante(self, root: etree.Element) -> Dict[str, Any]:
        """Parse Comprobante (main document) attributes"""
        return {
            'Version': root.get('Version'),
            'Serie': root.get('Serie'),
            'Folio': root.get('Folio'),
            'Fecha': root.get('Fecha'),
            'Sello': root.get('Sello'),
            'FormaPago': root.get('FormaPago') or root.get('FormaDePago'),
            'NoCertificado': root.get('NoCertificado'),
            'Certificado': root.get('Certificado'),
            'CondicionesDePago': root.get('CondicionesDePago'),
            'SubTotal': root.get('SubTotal'),
            'Descuento': root.get('Descuento'),
            'Moneda': root.get('Moneda'),
            'TipoCambio': root.get('TipoCambio'),
            'Total': root.get('Total'),
            'TipoDeComprobante': root.get('TipoDeComprobante'),
            'MetodoPago': root.get('MetodoPago') or root.get('MetodoDePago'),
            'LugarExpedicion': root.get('LugarExpedicion'),
            'Confirmacion': root.get('Confirmacion')
        }
    
    def _parse_emisor(self, root: etree.Element) -> Dict[str, Any]:
        """Parse Emisor (issuer/supplier) information"""
        emisor = root.find('cfdi:Emisor', self.namespaces)
        if emisor is None:
            return {}
        
        return {
            'Rfc': emisor.get('Rfc'),
            'Nombre': emisor.get('Nombre'),
            'RegimenFiscal': emisor.get('RegimenFiscal')
        }
    
    def _parse_receptor(self, root: etree.Element) -> Dict[str, Any]:
        """Parse Receptor (receiver/customer) information"""
        receptor = root.find('cfdi:Receptor', self.namespaces)
        if receptor is None:
            return {}
        
        result = {
            'Rfc': receptor.get('Rfc'),
            'Nombre': receptor.get('Nombre'),
            'UsoCFDI': receptor.get('UsoCFDI'),
            'ResidenciaFiscal': receptor.get('ResidenciaFiscal'),
            'NumRegIdTrib': receptor.get('NumRegIdTrib')
        }
        
        # CFDI 4.0 specific fields
        if self.version == "4.0":
            result['DomicilioFiscalReceptor'] = receptor.get('DomicilioFiscalReceptor')
            result['RegimenFiscalReceptor'] = receptor.get('RegimenFiscalReceptor')
        
        return result
    
    def _parse_conceptos(self, root: etree.Element) -> List[Dict[str, Any]]:
        """Parse Conceptos (line items)"""
        conceptos_node = root.find('cfdi:Conceptos', self.namespaces)
        if conceptos_node is None:
            return []
        
        conceptos = []
        for concepto in conceptos_node.findall('cfdi:Concepto', self.namespaces):
            item = {
                'ClaveProdServ': concepto.get('ClaveProdServ'),
                'NoIdentificacion': concepto.get('NoIdentificacion'),
                'Cantidad': concepto.get('Cantidad'),
                'ClaveUnidad': concepto.get('ClaveUnidad'),
                'Unidad': concepto.get('Unidad'),
                'Descripcion': concepto.get('Descripcion'),
                'ValorUnitario': concepto.get('ValorUnitario'),
                'Importe': concepto.get('Importe'),
                'Descuento': concepto.get('Descuento')
            }
            
            # CFDI 4.0 specific
            if self.version == "4.0":
                item['ObjetoImp'] = concepto.get('ObjetoImp')
            
            conceptos.append(item)
        
        return conceptos
    
    def _parse_impuestos(self, root: etree.Element) -> Dict[str, Any]:
        """Parse Impuestos (taxes)"""
        impuestos_node = root.find('cfdi:Impuestos', self.namespaces)
        if impuestos_node is None:
            return {}
        
        result = {
            'TotalImpuestosRetenidos': impuestos_node.get('TotalImpuestosRetenidos'),
            'TotalImpuestosTrasladados': impuestos_node.get('TotalImpuestosTrasladados'),
            'Retenciones': [],
            'Traslados': []
        }
        
        # Parse Retenciones
        retenciones_node = impuestos_node.find('cfdi:Retenciones', self.namespaces)
        if retenciones_node is not None:
            for retencion in retenciones_node.findall('cfdi:Retencion', self.namespaces):
                result['Retenciones'].append({
                    'Impuesto': retencion.get('Impuesto'),
                    'Importe': retencion.get('Importe')
                })
        
        # Parse Traslados
        traslados_node = impuestos_node.find('cfdi:Traslados', self.namespaces)
        if traslados_node is not None:
            for traslado in traslados_node.findall('cfdi:Traslado', self.namespaces):
                result['Traslados'].append({
                    'Impuesto': traslado.get('Impuesto'),
                    'TipoFactor': traslado.get('TipoFactor'),
                    'TasaOCuota': traslado.get('TasaOCuota'),
                    'Importe': traslado.get('Importe')
                })
        
        return result
    
    def _parse_complemento(self, root: etree.Element) -> Dict[str, Any]:
        """Parse Complemento section"""
        complemento_node = root.find('cfdi:Complemento', self.namespaces)
        if complemento_node is None:
            return {}
        
        result = {}
        
        # Check for Pagos complement
        pagos_node = (
            complemento_node.find('pago20:Pagos', self.namespaces) or
            complemento_node.find('pago10:Pagos', self.namespaces)
        )
        
        if pagos_node is not None:
            result['Pagos'] = self._parse_pagos(pagos_node)
        
        return result
    
    def _parse_pagos(self, pagos_node: etree.Element) -> Dict[str, Any]:
        """Parse Pagos complement (for payment documents)"""
        # Determine namespace (2.0 or 1.0)
        ns = None
        for prefix, uri in pagos_node.nsmap.items():
            if 'Pagos20' in uri:
                ns = {'pago': uri}
                break
            elif 'Pagos' in uri:
                ns = {'pago': uri}
                break
        
        if not ns:
            return {}
        
        pagos = []
        for pago in pagos_node.findall('pago:Pago', ns):
            pagos.append({
                'FechaPago': pago.get('FechaPago'),
                'FormaDePagoP': pago.get('FormaDePagoP'),
                'MonedaP': pago.get('MonedaP'),
                'TipoCambioP': pago.get('TipoCambioP'),
                'Monto': pago.get('Monto'),
                'NumOperacion': pago.get('NumOperacion')
            })
        
        return {'Pagos': pagos, 'Version': pagos_node.get('Version')}
    
    def _parse_timbre_fiscal(self, root: etree.Element) -> Dict[str, Any]:
        """Parse TimbreFiscalDigital (SAT stamp)"""
        complemento_node = root.find('cfdi:Complemento', self.namespaces)
        if complemento_node is None:
            return {}
        
        timbre = complemento_node.find('tfd:TimbreFiscalDigital', self.namespaces)
        if timbre is None:
            return {}
        
        return {
            'Version': timbre.get('Version'),
            'UUID': timbre.get('UUID'),
            'FechaTimbrado': timbre.get('FechaTimbrado'),
            'RfcProvCertif': timbre.get('RfcProvCertif'),
            'SelloCFD': timbre.get('SelloCFD'),
            'NoCertificadoSAT': timbre.get('NoCertificadoSAT'),
            'SelloSAT': timbre.get('SelloSAT')
        }
    
    def validate_structure(self, xml_content: str) -> Dict[str, Any]:
        """
        Validate CFDI structure and mandatory fields
        
        Returns:
            Validation report with errors and warnings
        """
        errors = []
        warnings = []
        
        try:
            # Parse the document
            parsed = self.parse(xml_content)
            
            # Check mandatory fields
            comprobante = parsed.get('comprobante', {})
            
            # Version check
            if not comprobante.get('Version'):
                errors.append("Missing mandatory field: Version")
            
            # Fecha check
            if not comprobante.get('Fecha'):
                errors.append("Missing mandatory field: Fecha")
            
            # SubTotal check
            if not comprobante.get('SubTotal'):
                errors.append("Missing mandatory field: SubTotal")
            
            # Total check
            if not comprobante.get('Total'):
                errors.append("Missing mandatory field: Total")
            
            # TipoDeComprobante check
            if not comprobante.get('TipoDeComprobante'):
                errors.append("Missing mandatory field: TipoDeComprobante")
            else:
                tipo = comprobante.get('TipoDeComprobante')
                if tipo not in ['I', 'E', 'T', 'N', 'P']:
                    errors.append(f"Invalid TipoDeComprobante: {tipo}")
            
            # Emisor checks
            emisor = parsed.get('emisor', {})
            if not emisor.get('Rfc'):
                errors.append("Missing mandatory field: Emisor.Rfc")
            if not emisor.get('Nombre'):
                warnings.append("Missing recommended field: Emisor.Nombre")
            
            # Receptor checks
            receptor = parsed.get('receptor', {})
            if not receptor.get('Rfc'):
                errors.append("Missing mandatory field: Receptor.Rfc")
            
            # Timbre Fiscal check
            timbre = parsed.get('timbre_fiscal', {})
            if not timbre.get('UUID'):
                errors.append("Missing mandatory field: TimbreFiscalDigital.UUID")
            
            # Conceptos check
            conceptos = parsed.get('conceptos', [])
            if not conceptos:
                errors.append("At least one Concepto is required")
            
            return {
                'valid': len(errors) == 0,
                'errors': errors,
                'warnings': warnings,
                'parsed_data': parsed
            }
            
        except Exception as e:
            return {
                'valid': False,
                'errors': [f"XML parsing error: {str(e)}"],
                'warnings': [],
                'parsed_data': None
            }


def extract_cfdi_fields(xml_content: str) -> Dict[str, Any]:
    """
    Helper function to extract CFDI fields
    
    Returns:
        Dictionary with extracted fields for database storage
    """
    parser = CFDIParser()
    
    try:
        parsed = parser.parse(xml_content)
        
        comprobante = parsed.get('comprobante', {})
        emisor = parsed.get('emisor', {})
        receptor = parsed.get('receptor', {})
        timbre = parsed.get('timbre_fiscal', {})
        conceptos = parsed.get('conceptos', [])
        
        # Calculate totals
        total_conceptos = sum(
            float(c.get('Importe', 0) or 0) 
            for c in conceptos
        )
        
        return {
            # CFDI Core
            'cfdi_version': parsed.get('version'),
            'serie': comprobante.get('Serie'),
            'folio': comprobante.get('Folio'),
            'fecha': comprobante.get('Fecha'),
            'subtotal': comprobante.get('SubTotal'),
            'total': comprobante.get('Total'),
            'moneda': comprobante.get('Moneda'),
            'tipo_de_comprobante': comprobante.get('TipoDeComprobante'),
            'metodo_pago': comprobante.get('MetodoPago'),
            'forma_pago': comprobante.get('FormaPago'),
            'lugar_expedicion': comprobante.get('LugarExpedicion'),
            
            # Emisor/Supplier
            'supplier_rfc': emisor.get('Rfc'),
            'supplier_name': emisor.get('Nombre'),
            'supplier_regimen_fiscal': emisor.get('RegimenFiscal'),
            
            # Receptor/Customer
            'customer_rfc': receptor.get('Rfc'),
            'customer_name': receptor.get('Nombre'),
            'customer_uso_cfdi': receptor.get('UsoCFDI'),
            
            # Timbre Fiscal
            'cfdi_uuid': timbre.get('UUID'),
            'fecha_timbrado': timbre.get('FechaTimbrado'),
            'rfc_prov_certif': timbre.get('RfcProvCertif'),
            
            # Line Items
            'conceptos_count': len(conceptos),
            'conceptos': conceptos,
            'total_conceptos': total_conceptos,
            
            # Full parsed data
            'full_parsed': parsed
        }
        
    except Exception as e:
        logger.error(f"❌ Error extracting CFDI fields: {e}")
        raise

