"""
SAP Transformer Service
Transforms CFDI documents to SAP ECC format (XML output)
Based on SAP transformation template structure
Maps to SAP document types: KR (Invoice), KG (Credit Note), KZ (Payment)
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from lxml import etree

logger = logging.getLogger(__name__)


class SAPTransformer:
    """
    Transforms CFDI documents to SAP ECC compatible format
    Supports 3 document types: INVOICE, PAYMENT, CREDIT_NOTE
    """
    
    def transform_to_sap(
        self, 
        cfdi_data: Dict[str, Any], 
        document_type: str
    ) -> Dict[str, Any]:
        """
        Main transformation method
        Routes to specific transformer based on document type
        
        Args:
            cfdi_data: Parsed CFDI data from CFDIParser
            document_type: INVOICE, PAYMENT, or CREDIT_NOTE
        
        Returns:
            SAP-formatted document ready for API submission
        """
        try:
            logger.info(f"🔄 Transforming {document_type} to SAP format")
            
            if document_type == "INVOICE":
                return self.transform_invoice_to_sap(cfdi_data)
            elif document_type == "PAYMENT":
                return self.transform_payment_to_sap(cfdi_data)
            elif document_type == "CREDIT_NOTE":
                return self.transform_credit_note_to_sap(cfdi_data)
            else:
                raise ValueError(f"Unknown document type: {document_type}")
                
        except Exception as e:
            logger.error(f"❌ SAP transformation error: {e}")
            raise
    
    def transform_invoice_to_sap(self, cfdi_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform INVOICE (TipoDeComprobante = I) to SAP format
        Based on /PSIF/INV_XML_CFDI structure
        """
        comprobante = cfdi_data.get('comprobante', {})
        emisor = cfdi_data.get('emisor', {})
        receptor = cfdi_data.get('receptor', {})
        conceptos = cfdi_data.get('conceptos', [])
        impuestos = cfdi_data.get('impuestos', {})
        timbre = cfdi_data.get('timbre_fiscal', {})
        
        # Parse fecha to extract MESES and ANIO
        fecha_str = comprobante.get('Fecha', '')
        meses, anio = self._extract_month_year(fecha_str)
        
        # Build SAP Invoice structure
        sap_invoice = {
            'INVOICE': {
                # Header - Comprobante attributes
                'EXPORTACION': comprobante.get('Exportacion', ''),
                'FECHA': comprobante.get('Fecha', ''),
                'FOLIO': comprobante.get('Folio', ''),
                'FORMAPAGO': comprobante.get('FormaPago', ''),
                'LUGAREXPEDICION': comprobante.get('LugarExpedicion', ''),
                'METODOPAGO': comprobante.get('MetodoPago', ''),
                'MONEDA': comprobante.get('Moneda', 'MXN'),
                'SERIE': comprobante.get('Serie', ''),
                'SUBTOTAL': comprobante.get('SubTotal', '0.00'),
                'TIPOCAMBIO': comprobante.get('TipoCambio', '1.0'),
                'TIPODECOMPROBANTE': comprobante.get('TipoDeComprobante', 'I'),
                'TOTAL': comprobante.get('Total', '0.00'),
                'MESES': meses,
                'ANIO': anio,
                
                # Emisor (Supplier) information
                'NOMBRE': emisor.get('Nombre', ''),
                'REGIMENFISCAL': emisor.get('RegimenFiscal', ''),
                'RFC': emisor.get('Rfc', ''),
                
                # Receptor (Customer) information
                'DOMICILIOFISCALRECEPTOR': receptor.get('DomicilioFiscalReceptor', ''),
                'NOMBRERECEPTOR': receptor.get('Nombre', ''),
                'REGIMENFISCALRECEPTOR': receptor.get('RegimenFiscalReceptor', ''),
                'RESIDENCIAFISCAL': receptor.get('ResidenciaFiscal', ''),
                'RFCRECEPTOR': receptor.get('Rfc', ''),
                'USOCFDI': receptor.get('UsoCFDI', ''),
                
                # Conceptos (Line Items)
                'CONCEPTOS': self._transform_conceptos(conceptos),
                
                # Impuestos (Taxes)
                'IMPUESTOS': self._transform_impuestos(impuestos),
                
                # Complemento (Timbre Fiscal)
                'CFDI_UUID': timbre.get('UUID', ''),
            }
        }
        
        logger.info(f"✅ Invoice transformed: {sap_invoice['INVOICE']['FOLIO']}")
        return sap_invoice
    
    def transform_payment_to_sap(self, cfdi_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform PAYMENT (TipoDeComprobante = P) to SAP format
        Based on /PSIF/PAYMENT_CFDI structure
        """
        comprobante = cfdi_data.get('comprobante', {})
        emisor = cfdi_data.get('emisor', {})
        receptor = cfdi_data.get('receptor', {})
        complemento = cfdi_data.get('complemento', {})
        timbre = cfdi_data.get('timbre_fiscal', {})
        
        # Extract payment details from Pagos complement
        pagos = complemento.get('Pagos', {})
        pagos_list = pagos.get('Pagos', [])
        
        # Parse fecha
        fecha_str = comprobante.get('Fecha', '')
        meses, anio = self._extract_month_year(fecha_str)
        
        # Build SAP Payment structure
        sap_payment = {
            'PAYMENT': {
                # Header
                'FECHA': comprobante.get('Fecha', ''),
                'FOLIO': comprobante.get('Folio', ''),
                'SERIE': comprobante.get('Serie', ''),
                'LUGAREXPEDICION': comprobante.get('LugarExpedicion', ''),
                'MONEDA': comprobante.get('Moneda', 'XXX'),
                'TIPODECOMPROBANTE': comprobante.get('TipoDeComprobante', 'P'),
                'MESES': meses,
                'ANIO': anio,
                
                # Emisor
                'NOMBRE': emisor.get('Nombre', ''),
                'REGIMENFISCAL': emisor.get('RegimenFiscal', ''),
                'RFC': emisor.get('Rfc', ''),
                
                # Receptor
                'DOMICILIOFISCALRECEPTOR': receptor.get('DomicilioFiscalReceptor', ''),
                'NOMBRERECEPTOR': receptor.get('Nombre', ''),
                'REGIMENFISCALRECEPTOR': receptor.get('RegimenFiscalReceptor', ''),
                'RFCRECEPTOR': receptor.get('Rfc', ''),
                'USOCFDI': receptor.get('UsoCFDI', ''),
                
                # Pagos (Payments)
                'PAGOS': self._transform_pagos(pagos_list),
                
                # Complemento
                'CFDI_UUID': timbre.get('UUID', ''),
                'PAGOS_VERSION': pagos.get('Version', '2.0'),
            }
        }
        
        logger.info(f"✅ Payment transformed: {sap_payment['PAYMENT']['FOLIO']}")
        return sap_payment
    
    def transform_credit_note_to_sap(self, cfdi_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform CREDIT NOTE (TipoDeComprobante = E) to SAP format
        Based on /PSIF/CREDIT_CFDI structure
        """
        comprobante = cfdi_data.get('comprobante', {})
        emisor = cfdi_data.get('emisor', {})
        receptor = cfdi_data.get('receptor', {})
        conceptos = cfdi_data.get('conceptos', [])
        impuestos = cfdi_data.get('impuestos', {})
        timbre = cfdi_data.get('timbre_fiscal', {})
        
        # Parse fecha
        fecha_str = comprobante.get('Fecha', '')
        meses, anio = self._extract_month_year(fecha_str)
        
        # Build SAP Credit Note structure (similar to Invoice but TipoDeComprobante = E)
        sap_credit = {
            'CREDIT_NOTE': {
                # Header
                'FECHA': comprobante.get('Fecha', ''),
                'FOLIO': comprobante.get('Folio', ''),
                'FORMAPAGO': comprobante.get('FormaPago', ''),
                'LUGAREXPEDICION': comprobante.get('LugarExpedicion', ''),
                'METODOPAGO': comprobante.get('MetodoPago', ''),
                'MONEDA': comprobante.get('Moneda', 'MXN'),
                'SERIE': comprobante.get('Serie', ''),
                'SUBTOTAL': comprobante.get('SubTotal', '0.00'),
                'TIPOCAMBIO': comprobante.get('TipoCambio', '1.0'),
                'TIPODECOMPROBANTE': comprobante.get('TipoDeComprobante', 'E'),
                'TOTAL': comprobante.get('Total', '0.00'),
                'MESES': meses,
                'ANIO': anio,
                
                # Emisor
                'NOMBRE': emisor.get('Nombre', ''),
                'REGIMENFISCAL': emisor.get('RegimenFiscal', ''),
                'RFC': emisor.get('Rfc', ''),
                
                # Receptor
                'DOMICILIOFISCALRECEPTOR': receptor.get('DomicilioFiscalReceptor', ''),
                'NOMBRERECEPTOR': receptor.get('Nombre', ''),
                'REGIMENFISCALRECEPTOR': receptor.get('RegimenFiscalReceptor', ''),
                'RESIDENCIAFISCAL': receptor.get('ResidenciaFiscal', ''),
                'RFCRECEPTOR': receptor.get('Rfc', ''),
                'USOCFDI': receptor.get('UsoCFDI', ''),
                
                # Conceptos
                'CONCEPTOS': self._transform_conceptos(conceptos),
                
                # Impuestos
                'IMPUESTOS': self._transform_impuestos(impuestos),
                
                # Complemento
                'CFDI_UUID': timbre.get('UUID', ''),
            }
        }
        
        logger.info(f"✅ Credit Note transformed: {sap_credit['CREDIT_NOTE']['FOLIO']}")
        return sap_credit
    
    def _transform_conceptos(self, conceptos: List[Dict]) -> List[Dict]:
        """Transform CFDI Conceptos to SAP format"""
        sap_conceptos = []
        
        for concepto in conceptos:
            sap_concepto = {
                'CANTIDAD': concepto.get('Cantidad', '0'),
                'CLAVEPRODSERV': concepto.get('ClaveProdServ', ''),
                'CLAVEUNIDAD': concepto.get('ClaveUnidad', ''),
                'DESCRIPCION': concepto.get('Descripcion', ''),
                'VALORUNITARIO': concepto.get('ValorUnitario', '0.00'),
                'IMPORTE': concepto.get('Importe', '0.00'),
                'NOIDENTIFICACION': concepto.get('NoIdentificacion', ''),
                'OBJETOIMP': concepto.get('ObjetoImp', ''),
                'UNIDAD': concepto.get('Unidad', ''),
                
                # Impuestos at line level (if any)
                'IMPUESTOS': {
                    'TRASLADOS': [],
                    'RETENCIONES': [],
                    'TOTALIMPUESTOSRETENIDOS': '0.00',
                    'TOTALIMPUESTOSTRASLADADOS': '0.00',
                    'TOTALTRASLADOSBASEIVA16': '0.00',
                    'TOTALTRASLADOSIMPUESTOIVA16': '0.00',
                }
            }
            
            sap_conceptos.append(sap_concepto)
        
        return sap_conceptos
    
    def _transform_impuestos(self, impuestos: Dict) -> Dict:
        """Transform CFDI Impuestos to SAP format"""
        traslados = impuestos.get('Traslados', [])
        retenciones = impuestos.get('Retenciones', [])
        
        # Transform Traslados
        sap_traslados = []
        total_traslados_base_iva16 = 0.0
        total_traslados_impuesto_iva16 = 0.0
        
        for traslado in traslados:
            sap_traslado = {
                'BASE': '0.00',  # Not in CFDI 4.0 at document level
                'IMPUESTO': traslado.get('Impuesto', ''),
                'TIPOFACTOR': traslado.get('TipoFactor', ''),
                'TASAOCUOTA': traslado.get('TasaOCuota', ''),
                'IMPORTE': traslado.get('Importe', '0.00'),
            }
            sap_traslados.append(sap_traslado)
            
            # Calculate IVA 16% totals
            if traslado.get('Impuesto') == '002' and traslado.get('TasaOCuota') == '0.160000':
                importe = float(traslado.get('Importe', 0))
                total_traslados_impuesto_iva16 += importe
                # Base = Importe / 0.16
                total_traslados_base_iva16 += importe / 0.16 if importe > 0 else 0
        
        # Transform Retenciones
        sap_retenciones = []
        for retencion in retenciones:
            sap_retencion = {
                'BASE': '0.00',
                'IMPUESTO': retencion.get('Impuesto', ''),
                'TIPOFACTOR': 'Tasa',
                'TASAOCUOTA': '0.000000',
                'IMPORTE': retencion.get('Importe', '0.00'),
            }
            sap_retenciones.append(sap_retencion)
        
        return {
            'TRASLADOS': sap_traslados,
            'RETENCIONES': sap_retenciones,
            'TOTALIMPUESTOSRETENIDOS': impuestos.get('TotalImpuestosRetenidos', '0.00'),
            'TOTALIMPUESTOSTRASLADADOS': impuestos.get('TotalImpuestosTrasladados', '0.00'),
            'TOTALTRASLADOSBASEIVA16': f"{total_traslados_base_iva16:.2f}",
            'TOTALTRASLADOSIMPUESTOIVA16': f"{total_traslados_impuesto_iva16:.2f}",
        }
    
    def _transform_pagos(self, pagos_list: List[Dict]) -> List[Dict]:
        """Transform CFDI Pagos to SAP format"""
        sap_pagos = []
        
        for pago in pagos_list:
            sap_pago = {
                'FECHAPAGO': pago.get('FechaPago', ''),
                'FORMADEPAGOP': pago.get('FormaDePagoP', ''),
                'MONEDAP': pago.get('MonedaP', 'MXN'),
                'TIPOCAMBIOP': pago.get('TipoCambioP', '1.0'),
                'MONTO': pago.get('Monto', '0.00'),
                'NUMOPERACION': pago.get('NumOperacion', ''),
            }
            sap_pagos.append(sap_pago)
        
        return sap_pagos
    
    def _extract_month_year(self, fecha_str: str) -> tuple:
        """Extract MESES and ANIO from Fecha field"""
        try:
            # Fecha format: 2025-03-15T10:30:00
            if fecha_str:
                dt = datetime.fromisoformat(fecha_str.replace('Z', '+00:00'))
                return str(dt.month).zfill(2), str(dt.year)
        except:
            pass
        return '01', '2025'  # Default
    
    def get_sap_document_type(self, document_type: str) -> str:
        """
        Map CFDI document type to SAP BLART (Document Type)
        For SAT Trial Balance integration
        """
        mapping = {
            "INVOICE": "KR",      # Vendor Invoice
            "PAYMENT": "KZ",      # Vendor Payment
            "CREDIT_NOTE": "KG"   # Vendor Credit Memo
        }
        return mapping.get(document_type, "SA")  # Default to SA (G/L account document)
    
    def dict_to_xml(self, data: Dict[str, Any], root_name: str = "INVOICE") -> str:
        """
        Convert dictionary to XML string
        Args:
            data: Dictionary structure (e.g., {'INVOICE': {...}})
            root_name: Root element name
        Returns:
            XML string
        """
        def build_element(parent, key, value):
            """Recursively build XML elements"""
            if isinstance(value, dict):
                elem = etree.SubElement(parent, key)
                for k, v in value.items():
                    build_element(elem, k, v)
            elif isinstance(value, list):
                # For lists, create multiple child elements with same tag
                for item in value:
                    if isinstance(item, dict):
                        list_elem = etree.SubElement(parent, key[:-1] if key.endswith('S') else key)
                        for k, v in item.items():
                            build_element(list_elem, k, v)
                    else:
                        elem = etree.SubElement(parent, key)
                        elem.text = str(item) if item is not None else ''
            else:
                elem = etree.SubElement(parent, key)
                elem.text = str(value) if value is not None else ''
        
        # Get the actual data (unwrap if it's wrapped in document type)
        if root_name in data:
            actual_data = data[root_name]
        else:
            actual_data = data
        
        # Create root element
        root = etree.Element(root_name)
        
        # Build XML tree
        for key, value in actual_data.items():
            build_element(root, key, value)
        
        # Convert to string with XML declaration
        xml_string = etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        ).decode('utf-8')
        
        return xml_string
    
    def transform_to_sap_xml(
        self, 
        cfdi_data: Dict[str, Any], 
        document_type: str
    ) -> tuple:
        """
        Transform CFDI to SAP format and return both dict and XML
        
        Args:
            cfdi_data: Parsed CFDI data from CFDIParser
            document_type: INVOICE, PAYMENT, or CREDIT_NOTE
        
        Returns:
            Tuple of (dict_payload, xml_string, sap_blart)
        """
        # First get the dictionary structure
        sap_dict = self.transform_to_sap(cfdi_data, document_type)
        
        # Get SAP document type (BLART)
        sap_blart = self.get_sap_document_type(document_type)
        
        # Determine root name based on document type
        root_name = document_type  # INVOICE, PAYMENT, or CREDIT_NOTE
        
        # Convert to XML
        sap_xml = self.dict_to_xml(sap_dict, root_name)
        
        logger.info(f"✅ Generated SAP XML for {document_type} (BLART: {sap_blart})")
        
        return sap_dict, sap_xml, sap_blart
    
    def transform_trial_balance_to_sap_xml(
        self,
        trial_balance,
        documents: List[Any]
    ) -> str:
        """
        Transform Trial Balance to SAP XML format.
        Following ChatGPT conversation pattern: merge invoices, credits, payments by vendor + period.
        
        Args:
            trial_balance: SATTrialBalance model instance
            documents: List of SATDocument instances linked to this trial balance
            
        Returns:
            SAP-formatted XML string
        """
        logger.info(f"🔄 Transforming Trial Balance to SAP XML: {trial_balance.vendor_rfc} {trial_balance.fiscal_year}-{trial_balance.fiscal_period:02d}")
        
        # Build trial balance structure
        trial_balance_data = {
            'CompanyCode': trial_balance.company_code,
            'FiscalYear': str(trial_balance.fiscal_year),
            'FiscalPeriod': str(trial_balance.fiscal_period).zfill(2),
            'VendorRFC': trial_balance.vendor_rfc,
            'VendorName': trial_balance.vendor_name or '',
            'Currency': trial_balance.currency,
            
            # Aggregated amounts (following ZEDI_FACTS pattern)
            'TotalInvoices': str(trial_balance.total_invoices),
            'TotalCredits': str(trial_balance.total_credits),
            'TotalPayments': str(trial_balance.total_payments),
            'NetBalance': str(trial_balance.net_balance),
            
            # Document count for audit
            'DocumentCount': str(trial_balance.document_count),
            
            # Detailed documents list
            'Documents': []
        }
        
        # Add detailed document list (for SAP audit trail)
        for doc in documents:
            doc_type_map = {
                'INVOICE': 'KR',
                'PAYMENT': 'KZ',
                'CREDIT_NOTE': 'KG'
            }
            
            # Calculate signed amount (following ChatGPT sign logic)
            signed_amount = doc.total or 0
            if doc.document_type.value in ['PAYMENT', 'CREDIT_NOTE']:
                signed_amount = -signed_amount
            
            doc_data = {
                'DocumentType': doc.document_type.value,
                'SAPBLART': doc_type_map.get(doc.document_type.value, 'SA'),
                'UUID': doc.cfdi_uuid,
                'Serie': doc.serie or '',
                'Folio': doc.folio or '',
                'Fecha': doc.fecha.isoformat() if doc.fecha else '',
                'Amount': str(doc.total or 0),
                'AmountSigned': str(signed_amount),
                'Currency': doc.moneda or 'MXN',
            }
            
            trial_balance_data['Documents'].append(doc_data)
        
        # Convert to XML
        xml_string = self.dict_to_xml({'SATTrialBalance': trial_balance_data}, 'SATTrialBalance')
        
        logger.info(f"✅ Generated Trial Balance SAP XML: {trial_balance.vendor_rfc}, Net Balance: {trial_balance.net_balance}")
        
        return xml_string
    
    def transform_canonical_to_sap_xml(self, canonical) -> str:
        """
        Transform a canonical merged document to SAP XML format.
        Following INB_CFDI_INV.xml template structure.
        
        Args:
            canonical: SATCanonicalMerged object
            
        Returns:
            SAP-compatible XML string
        """
        from app.models.sat_canonical_merged import SATCanonicalMerged
        
        logger.info(f"🔄 Transforming canonical merged document {canonical.id} to SAP XML")
        
        # Build INVOICE structure following INB_CFDI_INV.xml template
        invoice_data = {
            'INVOICE': {
                # Header fields
                'EXPORTACION': '01',  # Default: No aplica
                'FECHA': canonical.doc_date.strftime('%Y-%m-%d') if canonical.doc_date else '',
                'FOLIO': str(canonical.id)[:40],  # Use canonical ID as folio
                'FORMAPAGO': canonical.payment_method or '',
                'LUGAREXPEDICION': '',  # Not available in merged
                'METODOPAGO': 'PUE' if canonical.total_payments > 0 else 'PPD',
                'MONEDA': canonical.currency,
                'SERIE': 'MERGED',
                'SUBTOTAL': str(canonical.tax_base or canonical.net_amount),
                'TIPOCAMBIO': str(canonical.exchange_rate or '1.0'),
                'TIPODECOMPROBANTE': 'I',  # Default to Invoice
                'TOTAL': str(canonical.total_invoices),
                'MESES': str(canonical.fiscal_period).zfill(2),
                'ANIO': str(canonical.fiscal_year),
                
                # Vendor (Emisor) - This is the supplier
                'NOMBRE': canonical.vendor_name or '',
                'REGIMENFISCAL': '601',  # General de Ley Personas Morales (default)
                'RFC': canonical.vendor_rfc,
                
                # Customer (Receptor) - This is you (the company receiving the docs)
                'DOMICILIOFISCALRECEPTOR': '',
                'NOMBRERECEPTOR': canonical.company_code,  # Company name
                'REGIMENFISCALRECEPTOR': '601',
                'RESIDENCIAFISCAL': '',
                'RFCRECEPTOR': canonical.company_code,
                'USOCFDI': 'G03',  # Gastos en general
                
                # Line items (CONCEPTOS)
                'CONCEPTOS': [],
                
                # Taxes (IMPUESTOS)
                'IMPUESTOS': {
                    'TRASLADOS': [],
                    'RETENCIONES': [],
                    'TOTALIMPUESTOSRETENIDOS': '0.00',
                    'TOTALIMPUESTOSTRASLADADOS': str(canonical.tax_amount or 0),
                    'TOTALTRASLADOSBASEIVA16': str(canonical.tax_base or 0),
                    'TOTALTRASLADOSIMPUESTOIVA16': str(canonical.tax_amount or 0),
                },
                
                # CFDI Complement (UUID)
                'CFDI_UUID': ','.join(canonical.cfdi_uuids) if canonical.cfdi_uuids else '',
                
                # ✅ Canonical Merged Fields (For SAP Trial Balance)
                'TOTAL_INVOICES': str(canonical.total_invoices),
                'TOTAL_CREDITS': str(canonical.total_credits),
                'TOTAL_PAYMENTS': str(canonical.total_payments),
                'NET_AMOUNT': str(canonical.net_amount),
                'GL_ACCOUNT': canonical.sap_gl_account or '210999',  # Mapped GL Account
            }
        }
        
        # Add line items from merged documents
        if canonical.line_items:
            for line_item_group in canonical.line_items:
                if isinstance(line_item_group, dict) and 'items' in line_item_group:
                    items = line_item_group.get('items', [])
                    if isinstance(items, list):
                        for item in items:
                            concepto = {
                                'CANTIDAD': str(item.get('quantity', 1)),
                                'CLAVEPRODSERV': item.get('product_code', '01010101'),
                                'CLAVEUNIDAD': item.get('unit_code', 'ACT'),
                                'DESCRIPCION': item.get('description', 'Producto/Servicio'),
                                'VALORUNITARIO': str(item.get('unit_price', 0)),
                                'IMPORTE': str(item.get('amount', 0)),
                                'NOIDENTIFICACION': item.get('item_id', ''),
                                'OBJETOIMP': '02',  # Sí objeto de impuesto
                                'UNIDAD': item.get('unit', 'Servicio'),
                                'IMPUESTOS': {
                                    'TRASLADOS': [],
                                    'RETENCIONES': [],
                                    'TOTALIMPUESTOSRETENIDOS': '0.00',
                                    'TOTALIMPUESTOSTRASLADADOS': str(item.get('tax_amount', 0)),
                                    'TOTALTRASLADOSBASEIVA16': str(item.get('amount', 0)),
                                    'TOTALTRASLADOSIMPUESTOIVA16': str(item.get('tax_amount', 0)),
                                }
                            }
                            
                            # Add tax traslado for IVA 16%
                            if item.get('tax_amount', 0) > 0:
                                concepto['IMPUESTOS']['TRASLADOS'].append({
                                    'BASE': str(item.get('amount', 0)),
                                    'IMPUESTO': '002',  # IVA
                                    'TIPOFACTOR': 'Tasa',
                                    'TASAOCUOTA': '0.160000',
                                    'IMPORTE': str(item.get('tax_amount', 0))
                                })
                            
                            invoice_data['INVOICE']['CONCEPTOS'].append(concepto)
        
        # If no line items, create a summary line
        if not invoice_data['INVOICE']['CONCEPTOS']:
            invoice_data['INVOICE']['CONCEPTOS'].append({
                'CANTIDAD': '1',
                'CLAVEPRODSERV': '01010101',
                'CLAVEUNIDAD': 'ACT',
                'DESCRIPCION': f'Resumen consolidado - Facturas: {canonical.total_invoices}, Notas de crédito: {canonical.total_credits}, Pagos: {canonical.total_payments}',
                'VALORUNITARIO': str(canonical.net_amount),
                'IMPORTE': str(canonical.net_amount),
                'NOIDENTIFICACION': 'MERGED',
                'OBJETOIMP': '02',
                'UNIDAD': 'Servicio',
                'IMPUESTOS': {
                    'TRASLADOS': [],
                    'RETENCIONES': [],
                    'TOTALIMPUESTOSRETENIDOS': '0.00',
                    'TOTALIMPUESTOSTRASLADADOS': str(canonical.tax_amount or 0),
                    'TOTALTRASLADOSBASEIVA16': str(canonical.tax_base or 0),
                    'TOTALTRASLADOSIMPUESTOIVA16': str(canonical.tax_amount or 0),
                }
            })
        
        # Add header-level tax traslados
        if canonical.tax_amount and canonical.tax_amount > 0:
            invoice_data['INVOICE']['IMPUESTOS']['TRASLADOS'].append({
                'BASE': str(canonical.tax_base or 0),
                'IMPUESTO': '002',  # IVA
                'TIPOFACTOR': 'Tasa',
                'TASAOCUOTA': '0.160000',
                'IMPORTE': str(canonical.tax_amount)
            })
        
        # Convert to XML
        xml_string = self.dict_to_xml(invoice_data, 'INVOICE')
        
        logger.info(f"✅ Generated Canonical SAP XML: {canonical.vendor_rfc}, Net: {canonical.net_amount} {canonical.currency}")
        
        return xml_string


# Singleton instance
sap_transformer = SAPTransformer()

