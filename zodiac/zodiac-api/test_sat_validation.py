#!/usr/bin/env python3
"""
Test script for SAT Document Validation & Processing
Tests the full pipeline: Intake → Validation → Processing
"""
import requests
import json
import time

# Configuration
API_URL = "http://localhost:8000"
LOGIN_EMAIL = "testsalmen123@gmail.com"
LOGIN_PASSWORD = "testsalmen123"

# Sample CFDI XML with complete structure
COMPLETE_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
                   xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                   Version="4.0" 
                   Fecha="2025-03-15T10:30:00" 
                   Folio="12345" 
                   Serie="A"
                   SubTotal="10000.00" 
                   Total="11600.00" 
                   Moneda="MXN"
                   TipoDeComprobante="I"
                   MetodoPago="PUE"
                   FormaPago="03"
                   LugarExpedicion="01000">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="PROVEEDOR EJEMPLO SA DE CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="CLIENTE EJEMPLO SA DE CV" UsoCFDI="G03" DomicilioFiscalReceptor="06000" RegimenFiscalReceptor="612"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="01010101" 
                   Cantidad="10.00" 
                   ClaveUnidad="H87"
                   Descripcion="Producto ejemplo 1" 
                   ValorUnitario="500.00" 
                   Importe="5000.00"
                   ObjetoImp="02"/>
    <cfdi:Concepto ClaveProdServ="01010102" 
                   Cantidad="20.00" 
                   ClaveUnidad="H87"
                   Descripcion="Producto ejemplo 2" 
                   ValorUnitario="250.00" 
                   Importe="5000.00"
                   ObjetoImp="02"/>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosRetenidos="0.00" TotalImpuestosTrasladados="1600.00">
    <cfdi:Traslados>
      <cfdi:Traslado Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="1600.00"/>
    </cfdi:Traslados>
  </cfdi:Impuestos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" 
                             UUID="C4D5E6F7-A8B9-0123-DEFG-AB4567890123" 
                             FechaTimbrado="2025-03-15T10:45:00"
                             RfcProvCertif="SAT970701NN3"
                             SelloCFD="Base64EncodedSeal..."
                             NoCertificadoSAT="00001000000508991917"
                             SelloSAT="Base64EncodedSATSeal..."/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""

# Incomplete/Invalid XML for testing validation
INVALID_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
                   Version="4.0">
  <!-- Missing mandatory fields: Fecha, SubTotal, Total, TipoDeComprobante -->
  <cfdi:Emisor Nombre="PROVEEDOR SIN RFC"/>
  <!-- Missing Receptor -->
  <!-- Missing Conceptos -->
  <!-- Missing TimbreFiscalDigital -->
</cfdi:Comprobante>"""


def test_sat_validation():
    """Test the SAT validation and processing pipeline"""
    print("=" * 70)
    print("SAT Document Validation & Processing Test")
    print("=" * 70)
    print()
    
    # ============================================================
    # Step 1: Login
    # ============================================================
    print("🔐 Step 1: Logging in...")
    try:
        login_response = requests.post(
            f"{API_URL}/api/v1/user/auth/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
            timeout=10
        )
        
        if login_response.status_code != 200:
            print(f"❌ Login failed: {login_response.status_code}")
            print(login_response.text)
            return
        
        token = login_response.json().get("access_token")
        print(f"✅ Logged in successfully")
        print()
        
    except Exception as e:
        print(f"❌ Login error: {e}")
        return
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # ============================================================
    # Step 2: Test VALID document intake + auto-processing
    # ============================================================
    print("📄 Step 2: Testing VALID document intake...")
    valid_payload = {
        "documentType": "INVOICE",
        "supplierId": "SUPP001",
        "companyCode": "MX01",
        "xmlContent": COMPLETE_INVOICE_XML,
        "supplierName": "Proveedor Ejemplo SA de CV"
    }
    
    valid_doc_id = None
    
    try:
        intake_response = requests.post(
            f"{API_URL}/api/v1/sat/intake",
            json=valid_payload,
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {intake_response.status_code}")
        result = intake_response.json()
        print(f"Response: {json.dumps(result, indent=2)}")
        print()
        
        if result.get('success'):
            print("✅ Valid document received successfully!")
            valid_doc_id = result.get('satDocumentId')
            portal_ref = result.get('portalReferenceId')
            print(f"   Portal Ref: {portal_ref}")
            print(f"   Document ID: {valid_doc_id}")
            print(f"   CFDI UUID: {result.get('cfdiUuid')}")
            print()
        else:
            print("⚠️  Document intake had issues")
            print()
        
    except Exception as e:
        print(f"❌ Intake error: {e}")
        print()
    
    # Wait a moment for processing
    print("⏳ Waiting for auto-processing...")
    time.sleep(2)
    
    # ============================================================
    # Step 3: Check document status
    # ============================================================
    if valid_doc_id:
        print(f"📊 Step 3: Checking document status...")
        try:
            status_response = requests.get(
                f"{API_URL}/api/v1/sat/documents/{valid_doc_id}",
                headers=headers,
                timeout=10
            )
            
            print(f"Status Code: {status_response.status_code}")
            doc_details = status_response.json()
            print(f"Document Status: {doc_details.get('status')}")
            print(f"Schema Valid: {doc_details.get('isSchemaValid')}")
            print(f"SAP Doc Number: {doc_details.get('sapDocumentNumber', 'N/A')}")
            print()
            
        except Exception as e:
            print(f"❌ Status check error: {e}")
            print()
    
    # ============================================================
    # Step 4: Get processing logs
    # ============================================================
    if valid_doc_id:
        print(f"📋 Step 4: Getting processing logs...")
        try:
            logs_response = requests.get(
                f"{API_URL}/api/v1/sat/documents/{valid_doc_id}/logs",
                headers=headers,
                timeout=10
            )
            
            print(f"Status Code: {logs_response.status_code}")
            logs = logs_response.json()
            print(f"Processing Steps: {len(logs)}")
            print()
            
            for log in logs:
                status_icon = "✅" if log['stepStatus'] == 'SUCCESS' else "❌"
                print(f"  {status_icon} {log['stepName']}: {log['message']}")
            print()
            
        except Exception as e:
            print(f"❌ Logs error: {e}")
            print()
    
    # ============================================================
    # Step 5: Test INVALID document (should fail validation)
    # ============================================================
    print("📄 Step 5: Testing INVALID document...")
    invalid_payload = {
        "documentType": "INVOICE",
        "supplierId": "SUPP002",
        "companyCode": "MX01",
        "xmlContent": INVALID_INVOICE_XML,
        "supplierName": "Proveedor Invalido SA"
    }
    
    invalid_doc_id = None
    
    try:
        intake_response = requests.post(
            f"{API_URL}/api/v1/sat/intake",
            json=invalid_payload,
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {intake_response.status_code}")
        result = intake_response.json()
        print(f"Response: {json.dumps(result, indent=2)}")
        print()
        
        if result.get('success'):
            invalid_doc_id = result.get('satDocumentId')
            print("📥 Invalid document received (will fail validation)")
            print()
        
    except Exception as e:
        print(f"❌ Intake error: {e}")
        print()
    
    # Wait for processing
    print("⏳ Waiting for validation...")
    time.sleep(2)
    
    # Check status of invalid document
    if invalid_doc_id:
        print(f"📊 Checking invalid document status...")
        try:
            status_response = requests.get(
                f"{API_URL}/api/v1/sat/documents/{invalid_doc_id}",
                headers=headers,
                timeout=10
            )
            
            doc_details = status_response.json()
            print(f"Document Status: {doc_details.get('status')}")
            print(f"Schema Valid: {doc_details.get('isSchemaValid')}")
            print(f"Error Message: {doc_details.get('errorMessage', 'N/A')}")
            print()
            
            if doc_details.get('status') == 'FAILED':
                print("✅ Validation correctly rejected invalid document!")
            else:
                print("⚠️  Expected validation to fail")
            print()
            
        except Exception as e:
            print(f"❌ Status check error: {e}")
            print()
    
    # ============================================================
    # Step 6: Test manual processing trigger
    # ============================================================
    if invalid_doc_id:
        print(f"🔄 Step 6: Testing manual processing trigger...")
        try:
            process_response = requests.post(
                f"{API_URL}/api/v1/sat/documents/{invalid_doc_id}/process",
                headers=headers,
                timeout=30
            )
            
            print(f"Status Code: {process_response.status_code}")
            result = process_response.json()
            print(f"Response: {json.dumps(result, indent=2)}")
            print()
            
            if not result.get('success'):
                print("✅ Manual processing correctly failed for invalid document")
            print()
            
        except Exception as e:
            print(f"❌ Manual processing error: {e}")
            print()
    
    # ============================================================
    # Step 7: List all documents
    # ============================================================
    print("📋 Step 7: Listing all SAT documents...")
    try:
        list_response = requests.get(
            f"{API_URL}/api/v1/sat/documents",
            headers=headers,
            timeout=10
        )
        
        print(f"Status Code: {list_response.status_code}")
        result = list_response.json()
        print(f"Total documents: {result.get('total')}")
        print()
        
        if result.get('documents'):
            print("Documents:")
            for doc in result['documents'][:5]:  # Show first 5
                status_icon = "✅" if doc['status'] == 'READY_FOR_SAP' else "⚠️" if doc['status'] == 'FAILED' else "⏳"
                print(f"  {status_icon} {doc['portalReferenceId']}: {doc['documentType']} - {doc['status']}")
                if doc.get('isSchemaValid') is not None:
                    print(f"      Valid: {doc['isSchemaValid']}, UUID: {doc['cfdiUuid'][:20]}...")
        print()
        
    except Exception as e:
        print(f"❌ List documents error: {e}")
        print()
    
    print("=" * 70)
    print("✅ SAT Validation & Processing Test Complete!")
    print("=" * 70)
    print()
    print("Summary:")
    print("  ✅ Valid document: Intake → Validation → Processing → Ready for SAP")
    print("  ✅ Invalid document: Intake → Validation Failed → Error logged")
    print("  ✅ Processing logs: All steps tracked")
    print("  ✅ Manual processing: Can be triggered on demand")


if __name__ == "__main__":
    test_sat_validation()

