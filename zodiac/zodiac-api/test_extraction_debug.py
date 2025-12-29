"""
Debug CFDI field extraction
"""
import sys
sys.path.append('.')

from app.utils.cfdi_parser import extract_cfdi_fields
import uuid

# Test Invoice XML
TEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0"
    Serie="A"
    Folio="12345"
    Fecha="2025-03-15T10:30:00"
    FormaPago="99"
    MetodoPago="PPD"
    TipoDeComprobante="I"
    Exportacion="01"
    LugarExpedicion="06000"
    SubTotal="10000.00"
    Total="11600.00"
    Moneda="MXN"
    TipoCambio="1.0">
    
    <cfdi:Emisor Rfc="ABC123456789" Nombre="Proveedores Industriales SA de CV" RegimenFiscal="601"/>
    
    <cfdi:Receptor 
        Rfc="MES123456ABC" 
        Nombre="Mi Empresa SA de CV"
        DomicilioFiscalReceptor="64000"
        RegimenFiscalReceptor="601"
        UsoCFDI="G03"/>
    
    <cfdi:Conceptos>
        <cfdi:Concepto 
            ClaveProdServ="43211500" 
            NoIdentificacion="PROD-001" 
            Cantidad="100.00" 
            ClaveUnidad="H87" 
            Unidad="Pieza"
            Descripcion="Computadora Laptop Dell Latitude 5520" 
            ValorUnitario="100.00" 
            Importe="10000.00" 
            ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado 
                        Base="10000.00" 
                        Impuesto="002" 
                        TipoFactor="Tasa" 
                        TasaOCuota="0.160000" 
                        Importe="1600.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    
    <cfdi:Impuestos TotalImpuestosTrasladados="1600.00">
        <cfdi:Traslados>
            <cfdi:Traslado Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="1600.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            Version="1.1"
            UUID="{}"
            FechaTimbrado="2025-03-15T10:35:00"
            SelloCFD="SELLO_CFD_EJEMPLO"
            NoCertificadoSAT="00001000000123456789"
            SelloSAT="SELLO_SAT_EJEMPLO"/>
    </cfdi:Complemento>
</cfdi:Comprobante>""".format(str(uuid.uuid4()).upper())

print("="*70)
print("🔍 Testing CFDI Field Extraction")
print("="*70)

try:
    extracted = extract_cfdi_fields(TEST_XML)
    
    print("\n✅ Extraction successful!")
    print("\n📋 Extracted Fields:")
    print("-"*70)
    
    # CFDI Core
    print("\n🔷 CFDI Core:")
    print(f"  cfdi_version: {extracted.get('cfdi_version')}")
    print(f"  serie: {extracted.get('serie')}")
    print(f"  folio: {extracted.get('folio')}")
    print(f"  fecha: {extracted.get('fecha')}")
    print(f"  tipo_de_comprobante: {extracted.get('tipo_de_comprobante')}")
    print(f"  cfdi_uuid: {extracted.get('cfdi_uuid')}")
    
    # Financial
    print("\n💰 Financial:")
    print(f"  subtotal: {extracted.get('subtotal')}")
    print(f"  total: {extracted.get('total')}")
    print(f"  moneda: {extracted.get('moneda')}")
    
    # Supplier
    print("\n🏢 Supplier (Emisor):")
    print(f"  supplier_rfc: {extracted.get('supplier_rfc')}")
    print(f"  supplier_name: {extracted.get('supplier_name')}")
    
    # Customer
    print("\n👤 Customer (Receptor):")
    print(f"  customer_rfc: {extracted.get('customer_rfc')}")
    print(f"  customer_name: {extracted.get('customer_name')}")
    
    # Conceptos
    print("\n📦 Line Items:")
    print(f"  conceptos_count: {extracted.get('conceptos_count')}")
    
    print("\n" + "="*70)
    
    # Check for None values
    none_fields = [k for k, v in extracted.items() if v is None]
    if none_fields:
        print(f"\n⚠️  WARNING: {len(none_fields)} fields are None:")
        for field in none_fields:
            print(f"  - {field}")
    else:
        print("\n✅ All fields extracted successfully!")
    
except Exception as e:
    print(f"\n❌ Extraction failed!")
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

