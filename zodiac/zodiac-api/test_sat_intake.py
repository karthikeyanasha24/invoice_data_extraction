#!/usr/bin/env python3
"""
Test script for SAT Document Intake API
Tests the intake endpoint with sample CFDI documents
"""
import requests
import json

# Configuration
API_URL = "http://localhost:8000"
LOGIN_EMAIL = "testsalmen123@gmail.com"  # Update with your email
LOGIN_PASSWORD = "testsalmen123"  # Update with your password

# Sample CFDI XML (minimal version for testing)
SAMPLE_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
                   xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                   Version="4.0" 
                   Fecha="2025-03-15T10:30:00" 
                   Folio="123" 
                   Serie="A"
                   SubTotal="1000.00" 
                   Total="1160.00" 
                   Moneda="MXN"
                   TipoDeComprobante="I">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="PROVEEDOR EJEMPLO SA DE CV"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="CLIENTE EJEMPLO SA DE CV"/>
  <cfdi:Conceptos>
    <cfdi:Concepto Cantidad="1" Descripcion="Producto de prueba" ValorUnitario="1000.00" Importe="1000.00"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" 
                             UUID="A1B2C3D4-E5F6-7890-ABCD-EF1234567890" 
                             FechaTimbrado="2025-03-15T10:45:00"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""

SAMPLE_PAYMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
                   xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                   xmlns:pago20="http://www.sat.gob.mx/Pagos20"
                   Version="4.0" 
                   Fecha="2025-03-16T11:00:00" 
                   Folio="456" 
                   Serie="P"
                   SubTotal="0.00" 
                   Total="0.00" 
                   Moneda="XXX"
                   TipoDeComprobante="P">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="PROVEEDOR EJEMPLO SA DE CV"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="CLIENTE EJEMPLO SA DE CV"/>
  <cfdi:Conceptos>
    <cfdi:Concepto Cantidad="1" Descripcion="Pago" ValorUnitario="0.00" Importe="0.00"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <pago20:Pagos Version="2.0">
      <pago20:Pago FechaPago="2025-03-16T11:00:00" FormaDePagoP="03" MonedaP="MXN" Monto="1160.00"/>
    </pago20:Pagos>
    <tfd:TimbreFiscalDigital Version="1.1" 
                             UUID="B2C3D4E5-F6A7-8901-BCDE-FA2345678901" 
                             FechaTimbrado="2025-03-16T11:15:00"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""

SAMPLE_CREDIT_NOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" 
                   xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                   Version="4.0" 
                   Fecha="2025-03-17T12:00:00" 
                   Folio="789" 
                   Serie="NC"
                   SubTotal="500.00" 
                   Total="580.00" 
                   Moneda="MXN"
                   TipoDeComprobante="E">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="PROVEEDOR EJEMPLO SA DE CV"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="CLIENTE EJEMPLO SA DE CV"/>
  <cfdi:Conceptos>
    <cfdi:Concepto Cantidad="1" Descripcion="Nota de credito" ValorUnitario="500.00" Importe="500.00"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" 
                             UUID="C3D4E5F6-A7B8-9012-CDEF-AB3456789012" 
                             FechaTimbrado="2025-03-17T12:15:00"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""


def test_sat_intake():
    """Test the SAT intake endpoint"""
    print("=" * 70)
    print("SAT Document Intake API Test")
    print("=" * 70)
    print()
    
    # ============================================================
    # Step 1: Login to get token
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
    # Step 2: Test INVOICE intake
    # ============================================================
    print("📄 Step 2: Testing INVOICE intake...")
    invoice_payload = {
        "documentType": "INVOICE",
        "supplierId": "SUPP001",
        "companyCode": "MX01",
        "xmlContent": SAMPLE_INVOICE_XML,
        "supplierName": "Proveedor Ejemplo SA de CV"
    }
    
    try:
        invoice_response = requests.post(
            f"{API_URL}/api/v1/sat/intake",
            json=invoice_payload,
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {invoice_response.status_code}")
        print(f"Response: {json.dumps(invoice_response.json(), indent=2)}")
        print()
        
        if invoice_response.status_code == 200:
            print("✅ INVOICE intake successful!")
        else:
            print(f"⚠️  INVOICE intake returned status {invoice_response.status_code}")
        print()
        
    except Exception as e:
        print(f"❌ INVOICE intake error: {e}")
        print()
    
    # ============================================================
    # Step 3: Test PAYMENT intake
    # ============================================================
    print("💳 Step 3: Testing PAYMENT intake...")
    payment_payload = {
        "documentType": "PAYMENT",
        "supplierId": "SUPP001",
        "companyCode": "MX01",
        "xmlContent": SAMPLE_PAYMENT_XML,
        "supplierName": "Proveedor Ejemplo SA de CV"
    }
    
    try:
        payment_response = requests.post(
            f"{API_URL}/api/v1/sat/intake",
            json=payment_payload,
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {payment_response.status_code}")
        print(f"Response: {json.dumps(payment_response.json(), indent=2)}")
        print()
        
        if payment_response.status_code == 200:
            print("✅ PAYMENT intake successful!")
        else:
            print(f"⚠️  PAYMENT intake returned status {payment_response.status_code}")
        print()
        
    except Exception as e:
        print(f"❌ PAYMENT intake error: {e}")
        print()
    
    # ============================================================
    # Step 4: Test CREDIT_NOTE intake
    # ============================================================
    print("📝 Step 4: Testing CREDIT_NOTE intake...")
    credit_note_payload = {
        "documentType": "CREDIT_NOTE",
        "supplierId": "SUPP001",
        "companyCode": "MX01",
        "xmlContent": SAMPLE_CREDIT_NOTE_XML,
        "supplierName": "Proveedor Ejemplo SA de CV"
    }
    
    try:
        credit_note_response = requests.post(
            f"{API_URL}/api/v1/sat/intake",
            json=credit_note_payload,
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {credit_note_response.status_code}")
        print(f"Response: {json.dumps(credit_note_response.json(), indent=2)}")
        print()
        
        if credit_note_response.status_code == 200:
            print("✅ CREDIT_NOTE intake successful!")
        else:
            print(f"⚠️  CREDIT_NOTE intake returned status {credit_note_response.status_code}")
        print()
        
    except Exception as e:
        print(f"❌ CREDIT_NOTE intake error: {e}")
        print()
    
    # ============================================================
    # Step 5: Test duplicate detection (resend invoice)
    # ============================================================
    print("🔄 Step 5: Testing duplicate detection...")
    try:
        duplicate_response = requests.post(
            f"{API_URL}/api/v1/sat/intake",
            json=invoice_payload,  # Same invoice as step 2
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {duplicate_response.status_code}")
        print(f"Response: {json.dumps(duplicate_response.json(), indent=2)}")
        print()
        
        result = duplicate_response.json()
        if result.get("isDuplicate"):
            print("✅ Duplicate detection working!")
        else:
            print("⚠️  Duplicate was not detected")
        print()
        
    except Exception as e:
        print(f"❌ Duplicate test error: {e}")
        print()
    
    # ============================================================
    # Step 6: List all documents
    # ============================================================
    print("📋 Step 6: Listing all SAT documents...")
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
            for doc in result['documents']:
                print(f"  - {doc['portalReferenceId']}: {doc['documentType']} ({doc['status']})")
        print()
        
    except Exception as e:
        print(f"❌ List documents error: {e}")
        print()
    
    print("=" * 70)
    print("✅ SAT Intake API Test Complete!")
    print("=" * 70)


if __name__ == "__main__":
    test_sat_intake()

