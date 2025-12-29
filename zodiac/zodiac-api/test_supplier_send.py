"""
Simulate a SUPPLIER sending CFDI documents to BridgeEDI Portal
This script acts like a real supplier's system sending invoices via API
"""
import requests
import json
import time
from datetime import datetime
import random
import string
import uuid

# Configuration
PORTAL_URL = "http://localhost:8000"
SUPPLIER_ID = "SUPP001"
COMPANY_CODE = "MX01"

# Login credentials (your BridgeEDI account)
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"

def generate_unique_portal_ref_id():
    """Generate a unique portal reference ID"""
    timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"PRT-{timestamp_str}-{random_suffix}"

def login():
    """Login to BridgeEDI portal"""
    print("🔐 Logging in to BridgeEDI Portal...")
    response = requests.post(
        f"{PORTAL_URL}/api/v1/user/auth/login",
        json={"email": EMAIL, "password": PASSWORD}
    )
    
    if response.status_code == 200:
        token = response.json()['access_token']
        print(f"✅ Login successful!")
        return token
    else:
        print(f"❌ Login failed: {response.status_code}")
        print(response.text)
        return None

def send_invoice(token):
    """Send a CFDI Invoice (like a supplier would)"""
    print("\n" + "="*70)
    print("📤 SUPPLIER: Sending INVOICE to BridgeEDI Portal")
    print("="*70)
    
    # Realistic Invoice XML with complete customer data
    invoice_xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0"
    Serie="A"
    Folio="12345"
    Fecha="2025-12-15T10:30:00"
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
            UUID="{cfdi_uuid}"
            FechaTimbrado="2025-12-15T10:35:00"
            SelloCFD="SELLO_CFD_EJEMPLO"
            NoCertificadoSAT="00001000000123456789"
            SelloSAT="SELLO_SAT_EJEMPLO"/>
    </cfdi:Complemento>
</cfdi:Comprobante>""".format(cfdi_uuid=str(uuid.uuid4()).upper())
    
    payload = {
        "documentType": "INVOICE",
        "supplierId": SUPPLIER_ID,
        "companyCode": COMPANY_CODE,
        "xmlContent": invoice_xml
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"📄 Document Type: INVOICE")
    print(f"👤 Supplier: Proveedores Industriales SA de CV")
    print(f"🏢 Customer: Mi Empresa SA de CV")
    print(f"💰 Total: $11,600.00 MXN")
    print(f"📝 Folio: A-12345 (December 2025)")
    print(f"\n🚀 Sending to portal...")
    
    response = requests.post(
        f"{PORTAL_URL}/api/v1/sat/intake",
        json=payload,
        headers=headers
    )
    
    print(f"\n📡 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ SUCCESS! Document accepted")
        print(f"   Portal Reference: {result['portalReferenceId']}")
        print(f"   Document ID: {result['satDocumentId']}")
        print(f"   Status: {result['status']}")
        print(f"   CFDI UUID: {result.get('cfdiUuid', 'N/A')}")
        return result['satDocumentId']
    else:
        print(f"❌ FAILED!")
        print(f"   Error: {response.text}")
        return None

def send_payment(token):
    """Send a CFDI Payment (like a supplier would)"""
    print("\n" + "="*70)
    print("💳 SUPPLIER: Sending PAYMENT to BridgeEDI Portal")
    print("="*70)
    
    payment_xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
    xmlns:pago20="http://www.sat.gob.mx/Pagos20"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    Version="4.0"
    Serie="P"
    Folio="67890"
    Fecha="2025-12-16T11:00:00"
    TipoDeComprobante="P"
    Exportacion="01"
    LugarExpedicion="06000"
    SubTotal="0.00"
    Total="0.00"
    Moneda="XXX">
    
    <cfdi:Emisor Rfc="ABC123456789" Nombre="Proveedores Industriales SA de CV" RegimenFiscal="601"/>
    
    <cfdi:Receptor 
        Rfc="MES123456ABC" 
        Nombre="Mi Empresa SA de CV"
        DomicilioFiscalReceptor="64000"
        RegimenFiscalReceptor="601"
        UsoCFDI="CP01"/>
    
    <cfdi:Conceptos>
        <cfdi:Concepto 
            ClaveProdServ="84111506" 
            Cantidad="1" 
            ClaveUnidad="ACT" 
            Descripcion="Pago" 
            ValorUnitario="0" 
            Importe="0"
            ObjetoImp="01"/>
    </cfdi:Conceptos>
    
    <cfdi:Complemento>
        <pago20:Pagos Version="2.0">
            <pago20:Totales TotalTrasladosBaseIVA16="10000.00" TotalTrasladosImpuestoIVA16="1600.00" MontoTotalPagos="11600.00"/>
            <pago20:Pago FechaPago="2025-12-16T11:00:00" FormaDePagoP="03" MonedaP="MXN" Monto="11600.00">
                <pago20:DoctoRelacionado IdDocumento="A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D" 
                    MonedaDR="MXN" NumParcialidad="1" ImpSaldoAnt="11600.00" ImpPagado="11600.00" ImpSaldoInsoluto="0.00"
                    ObjetoImpDR="02">
                    <pago20:ImpuestosDR>
                        <pago20:TrasladosDR>
                            <pago20:TrasladoDR BaseDR="10000.00" ImpuestoDR="002" TipoFactorDR="Tasa" 
                                TasaOCuotaDR="0.160000" ImporteDR="1600.00"/>
                        </pago20:TrasladosDR>
                    </pago20:ImpuestosDR>
                </pago20:DoctoRelacionado>
            </pago20:Pago>
        </pago20:Pagos>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            Version="1.1"
            UUID="{cfdi_uuid}"
            FechaTimbrado="2025-12-16T11:05:00"
            SelloCFD="SELLO_CFD_PAY"
            NoCertificadoSAT="00001000000123456789"
            SelloSAT="SELLO_SAT_PAY"/>
    </cfdi:Complemento>
</cfdi:Comprobante>""".format(cfdi_uuid=str(uuid.uuid4()).upper())
    
    payload = {
        "documentType": "PAYMENT",
        "supplierId": SUPPLIER_ID,
        "companyCode": COMPANY_CODE,
        "xmlContent": payment_xml
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"📄 Document Type: PAYMENT")
    print(f"👤 Supplier: Proveedores Industriales SA de CV")
    print(f"🏢 Customer: Mi Empresa SA de CV")
    print(f"💰 Payment Amount: $11,600.00 MXN")
    print(f"📝 Folio: P-67890")
    print(f"\n🚀 Sending to portal...")
    
    response = requests.post(
        f"{PORTAL_URL}/api/v1/sat/intake",
        json=payload,
        headers=headers
    )
    
    print(f"\n📡 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ SUCCESS! Payment accepted")
        print(f"   Portal Reference: {result['portalReferenceId']}")
        print(f"   Document ID: {result['satDocumentId']}")
        print(f"   Status: {result['status']}")
        return result['satDocumentId']
    else:
        print(f"❌ FAILED!")
        print(f"   Error: {response.text}")
        return None

def send_credit_note(token):
    """Send a CFDI Credit Note (like a supplier would)"""
    print("\n" + "="*70)
    print("📋 SUPPLIER: Sending CREDIT NOTE to BridgeEDI Portal")
    print("="*70)
    
    credit_note_xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    Version="4.0"
    Serie="NC"
    Folio="54321"
    Fecha="2025-12-17T14:20:00"
    FormaPago="99"
    MetodoPago="PPD"
    TipoDeComprobante="E"
    Exportacion="01"
    LugarExpedicion="06000"
    SubTotal="2000.00"
    Total="2320.00"
    Moneda="MXN">
    
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
            Cantidad="20.00" 
            ClaveUnidad="H87" 
            Unidad="Pieza"
            Descripcion="Devolucion - Computadora Laptop Dell defectuosa" 
            ValorUnitario="100.00" 
            Importe="2000.00" 
            ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado 
                        Base="2000.00" 
                        Impuesto="002" 
                        TipoFactor="Tasa" 
                        TasaOCuota="0.160000" 
                        Importe="320.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    
    <cfdi:Impuestos TotalImpuestosTrasladados="320.00">
        <cfdi:Traslados>
            <cfdi:Traslado Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="320.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            Version="1.1"
            UUID="{cfdi_uuid}"
            FechaTimbrado="2025-12-17T14:25:00"
            SelloCFD="SELLO_CFD_CN"
            NoCertificadoSAT="00001000000123456789"
            SelloSAT="SELLO_SAT_CN"/>
    </cfdi:Complemento>
</cfdi:Comprobante>""".format(cfdi_uuid=str(uuid.uuid4()).upper())
    
    payload = {
        "documentType": "CREDIT_NOTE",
        "supplierId": SUPPLIER_ID,
        "companyCode": COMPANY_CODE,
        "xmlContent": credit_note_xml
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"📄 Document Type: CREDIT NOTE")
    print(f"👤 Supplier: Proveedores Industriales SA de CV")
    print(f"🏢 Customer: Mi Empresa SA de CV")
    print(f"💰 Credit Amount: $2,320.00 MXN")
    print(f"📝 Folio: NC-54321")
    print(f"\n🚀 Sending to portal...")
    
    response = requests.post(
        f"{PORTAL_URL}/api/v1/sat/intake",
        json=payload,
        headers=headers
    )
    
    print(f"\n📡 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ SUCCESS! Credit Note accepted")
        print(f"   Portal Reference: {result['portalReferenceId']}")
        print(f"   Document ID: {result['satDocumentId']}")
        print(f"   Status: {result['status']}")
        return result['satDocumentId']
    else:
        print(f"❌ FAILED!")
        print(f"   Error: {response.text}")
        return None

def check_status(token, document_id):
    """Check document status"""
    print(f"\n🔍 Checking status for document: {document_id}")
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{PORTAL_URL}/api/v1/sat/documents/{document_id}",
        headers=headers
    )
    
    if response.status_code == 200:
        doc = response.json()
        print(f"   Status: {doc['status']}")
        print(f"   SAP Doc #: {doc.get('sapDocumentNumber', 'Pending')}")
        return doc['status']
    else:
        print(f"   ❌ Could not fetch status")
        return None

def main():
    print("\n" + "="*70)
    print("🚀 SUPPLIER SIMULATION - Sending CFDI Documents to BridgeEDI")
    print("="*70)
    print(f"Portal: {PORTAL_URL}")
    print(f"Supplier ID: {SUPPLIER_ID}")
    print(f"Company Code: {COMPANY_CODE}")
    print("="*70)
    
    # Login
    token = login()
    if not token:
        return
    
    # Send documents
    invoice_id = send_invoice(token)
    time.sleep(2)  # Wait for processing
    
    payment_id = send_payment(token)
    time.sleep(2)
    
    credit_note_id = send_credit_note(token)
    time.sleep(2)
    
    # Check statuses
    print("\n" + "="*70)
    print("📊 CHECKING DOCUMENT STATUSES")
    print("="*70)
    
    if invoice_id:
        check_status(token, invoice_id)
    if payment_id:
        check_status(token, payment_id)
    if credit_note_id:
        check_status(token, credit_note_id)
    
    # Final instructions
    print("\n" + "="*70)
    print("✅ TESTING COMPLETE!")
    print("="*70)
    print("\n📱 NOW CHECK THE FRONTEND:")
    print("   1. Go to http://localhost:3000")
    print("   2. Click 'SAT Documents' in sidebar")
    print("   3. You should see 3 new documents:")
    print("      • Invoice: Proveedores Industriales SA")
    print("      • Payment: Proveedores Industriales SA")
    print("      • Credit Note: Proveedores Industriales SA")
    print("   4. Click 'View' to see full details")
    print("   5. Customer Name should be: 'Mi Empresa SA de CV' ✅")
    print("\n🎉 All documents sent successfully!")

if __name__ == "__main__":
    main()

