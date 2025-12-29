"""
Test SAP Integration End-to-End
Tests the complete flow from CFDI intake to SAP posting
"""
import requests
import json
import time
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000"
SAP_URL = "http://localhost:8001"
TOKEN = ""  # Will be filled after login

# Test INVOICE XML (CFDI 4.0)
TEST_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0"
    Serie="A"
    Folio="12345"
    Fecha="2025-03-15T10:30:00"
    FormaPago="01"
    MetodoPago="PUE"
    TipoDeComprobante="I"
    Exportacion="01"
    LugarExpedicion="06000"
    SubTotal="1000.00"
    Total="1160.00"
    Moneda="MXN"
    TipoCambio="1.0">
    
    <cfdi:Emisor Rfc="EEM9712171Z0" Nombre="Empresa de Ejemplo SA de CV" RegimenFiscal="601"/>
    
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="Publico en General" 
        DomicilioFiscalReceptor="06000" RegimenFiscalReceptor="616" UsoCFDI="G03"/>
    
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="01010101" NoIdentificacion="PROD001" 
            Cantidad="10.00" ClaveUnidad="H87" Unidad="Pieza"
            Descripcion="Producto de prueba" ValorUnitario="100.00" Importe="1000.00" 
            ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa" 
                        TasaOCuota="0.160000" Importe="160.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            Version="1.1"
            UUID="A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D"
            FechaTimbrado="2025-03-15T10:35:00"
            SelloCFD="SELLO_CFD_EJEMPLO"
            NoCertificadoSAT="00001000000123456789"
            SelloSAT="SELLO_SAT_EJEMPLO"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

# Test CREDIT NOTE XML
TEST_CREDIT_NOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    Version="4.0"
    Serie="NC"
    Folio="54321"
    Fecha="2025-03-16T14:20:00"
    FormaPago="01"
    MetodoPago="PUE"
    TipoDeComprobante="E"
    LugarExpedicion="06000"
    SubTotal="500.00"
    Total="580.00"
    Moneda="MXN">
    
    <cfdi:Emisor Rfc="EEM9712171Z0" Nombre="Empresa de Ejemplo SA de CV" RegimenFiscal="601"/>
    
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="Publico en General" 
        DomicilioFiscalReceptor="06000" RegimenFiscalReceptor="616" UsoCFDI="G03"/>
    
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="01010101" NoIdentificacion="PROD001" 
            Cantidad="5.00" ClaveUnidad="H87" Unidad="Pieza"
            Descripcion="Devolucion producto" ValorUnitario="100.00" Importe="500.00" 
            ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="500.00" Impuesto="002" TipoFactor="Tasa" 
                        TasaOCuota="0.160000" Importe="80.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    
    <cfdi:Impuestos TotalImpuestosTrasladados="80.00">
        <cfdi:Traslados>
            <cfdi:Traslado Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="80.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            Version="1.1"
            UUID="Z9Y8X7W6-V5U4-4T3S-2R1Q-0P9O8N7M6L5K"
            FechaTimbrado="2025-03-16T14:25:00"
            SelloCFD="SELLO_CFD_EJEMPLO_CN"
            NoCertificadoSAT="00001000000123456789"
            SelloSAT="SELLO_SAT_EJEMPLO_CN"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


def print_header(title):
    """Print formatted section header"""
    print(f"\n{'=' * 70}")
    print(f"{title:^70}")
    print(f"{'=' * 70}\n")


def print_step(step_num, description):
    """Print formatted step"""
    print(f"\n{'─' * 70}")
    print(f"Step {step_num}: {description}")
    print(f"{'─' * 70}")


def login():
    """Login and get authentication token"""
    global TOKEN
    
    print_step(1, "Login to BridgeEDI Portal")
    
    response = requests.post(
        f"{API_URL}/api/v1/user/auth/login",
        json={
            "email": "testsalmen123@gmail.com",
            "password": "testsalmen123"
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        TOKEN = data.get("access_token")
        print(f"✅ Login successful!")
        print(f"📝 Token: {TOKEN[:50]}...")
        return True
    else:
        print(f"❌ Login failed: {response.status_code}")
        print(f"Response: {response.text}")
        return False


def check_sap_health():
    """Check if Mock SAP API is running"""
    print_step(2, "Check Mock SAP API Health")
    
    try:
        response = requests.get(f"{SAP_URL}/sap/health", timeout=5)
        if response.status_code == 200:
            print(f"✅ Mock SAP API is healthy!")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            return True
        else:
            print(f"⚠️  Mock SAP API returned: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Mock SAP API is not reachable: {e}")
        print(f"💡 Start it with: python mock_sap_api.py")
        return False


def send_invoice(xml_content, doc_type="INVOICE"):
    """Send a document to SAT intake"""
    print_step(3, f"Send {doc_type} to SAT Intake")
    
    payload = {
        "documentType": doc_type,
        "supplierId": "SUPP001",
        "companyCode": "MX01",
        "xmlContent": xml_content
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    print(f"📤 Sending {doc_type}...")
    response = requests.post(
        f"{API_URL}/api/v1/sat/intake",
        json=payload,
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    
    if response.status_code in [200, 202]:
        data = response.json()
        print(f"✅ {doc_type} accepted!")
        print(f"Response: {json.dumps(data, indent=2)}")
        return data
    else:
        print(f"❌ {doc_type} rejected: {response.status_code}")
        print(f"Response: {response.text}")
        return None


def check_document_status(document_id):
    """Check the processing status of a document"""
    print_step(4, f"Check Document Status")
    
    headers = {
        "Authorization": f"Bearer {TOKEN}"
    }
    
    print(f"🔍 Checking status for document: {document_id}")
    response = requests.get(
        f"{API_URL}/api/v1/sat/documents/{document_id}",
        headers=headers
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Document found!")
        print(f"Portal Ref: {data['portalReferenceId']}")
        print(f"Status: {data['status']}")
        print(f"SAP Document: {data.get('sapDocumentNumber', 'N/A')}")
        print(f"SAP Fiscal Year: {data.get('sapFiscalYear', 'N/A')}")
        return data
    else:
        print(f"❌ Failed to get document: {response.status_code}")
        print(f"Response: {response.text}")
        return None


def check_processing_logs(document_id):
    """Check the processing logs of a document"""
    print_step(5, f"Check Processing Logs")
    
    headers = {
        "Authorization": f"Bearer {TOKEN}"
    }
    
    print(f"📋 Fetching logs for document: {document_id}")
    response = requests.get(
        f"{API_URL}/api/v1/sat/documents/{document_id}/logs",
        headers=headers
    )
    
    if response.status_code == 200:
        logs = response.json()
        print(f"✅ Found {len(logs)} log entries:")
        for i, log in enumerate(logs, 1):
            # Handle both old format (stage/status) and new format (step_name/step_status)
            step = log.get('stage') or log.get('step_name') or log.get('stepName', 'N/A')
            status = log.get('status') or log.get('step_status') or log.get('stepStatus', 'N/A')
            print(f"\n  {i}. [{status}] {step}")
            print(f"     Time: {log.get('timestamp', 'N/A')}")
            print(f"     Message: {log.get('message', 'N/A')}")
        return logs
    else:
        print(f"❌ Failed to get logs: {response.status_code}")
        return None


def list_all_documents():
    """List all SAT documents"""
    print_step(6, "List All SAT Documents")
    
    headers = {
        "Authorization": f"Bearer {TOKEN}"
    }
    
    response = requests.get(
        f"{API_URL}/api/v1/sat/documents",
        headers=headers
    )
    
    if response.status_code == 200:
        documents = response.json()
        if isinstance(documents, list):
            print(f"✅ Found {len(documents)} documents:")
            for doc in documents:
                # Handle both camelCase and snake_case
                portal_ref = doc.get('portalReferenceId') or doc.get('portal_reference_id', 'N/A')
                doc_type = doc.get('documentType') or doc.get('document_type', 'N/A')
                doc_status = doc.get('status', 'N/A')
                sap_doc = doc.get('sapDocumentNumber') or doc.get('sap_document_number', 'N/A')
                created = doc.get('createdAt') or doc.get('created_at', 'N/A')
                
                print(f"\n  • Portal Ref: {portal_ref}")
                print(f"    Type: {doc_type}")
                print(f"    Status: {doc_status}")
                print(f"    SAP Doc: {sap_doc}")
                print(f"    Created: {created}")
            return documents
        else:
            print(f"⚠️  Unexpected response format: {documents}")
            return []
    else:
        print(f"❌ Failed to list documents: {response.status_code}")
        return None


def run_full_test():
    """Run the complete SAP integration test"""
    print_header("🚀 SAP Integration End-to-End Test")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Step 1: Login
    if not login():
        print("\n❌ Test aborted: Login failed")
        return
    
    # Step 2: Check SAP Health
    sap_healthy = check_sap_health()
    if not sap_healthy:
        print("\n⚠️  Warning: Mock SAP API not running. Test will fail at SAP posting.")
        print("   Start it with: python mock_sap_api.py")
        response = input("\n   Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("\n❌ Test aborted by user")
            return
    
    # Step 3: Send INVOICE
    invoice_result = send_invoice(TEST_INVOICE_XML, "INVOICE")
    if not invoice_result:
        print("\n❌ Test aborted: Invoice intake failed")
        return
    
    invoice_id = invoice_result.get('satDocumentId')
    
    # Wait for processing
    print(f"\n⏳ Waiting 3 seconds for background processing...")
    time.sleep(3)
    
    # Step 4: Check Invoice Status
    invoice_status = check_document_status(invoice_id)
    
    # Step 5: Check Invoice Logs
    check_processing_logs(invoice_id)
    
    # Step 6: Send CREDIT NOTE
    print("\n")
    credit_result = send_invoice(TEST_CREDIT_NOTE_XML, "CREDIT_NOTE")
    if credit_result:
        credit_id = credit_result.get('satDocumentId')
        
        # Wait for processing
        print(f"\n⏳ Waiting 3 seconds for background processing...")
        time.sleep(3)
        
        # Check Credit Note Status
        check_document_status(credit_id)
        check_processing_logs(credit_id)
    
    # Step 7: List all documents
    list_all_documents()
    
    # Final Summary
    print_header("✅ Test Complete!")
    print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n📊 Test Summary:")
    print(f"  • INVOICE sent: {invoice_id}")
    if credit_result:
        print(f"  • CREDIT_NOTE sent: {credit_result.get('satDocumentId')}")
    if invoice_status:
        print(f"  • Final Invoice Status: {invoice_status.get('status')}")
        print(f"  • SAP Document Number: {invoice_status.get('sapDocumentNumber', 'N/A')}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_full_test()

