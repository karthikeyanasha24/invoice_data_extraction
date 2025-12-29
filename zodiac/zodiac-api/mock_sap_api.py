"""
Mock SAP ECC REST API
For testing SAP integration without actual SAP connection
Run this on port 8001: uvicorn mock_sap_api:app --host 0.0.0.0 --port 8001

Now accepts XML payload (SAP BLART format: KR, KG, KZ)
"""
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
import random
from lxml import etree

app = FastAPI(title="Mock SAP ECC API", version="1.0.0")


class SAPDocumentResponse(BaseModel):
    success: bool
    documentNumber: Optional[str] = None
    fiscalYear: Optional[str] = None
    postingDate: Optional[str] = None
    sapBlart: Optional[str] = None  # SAP Document Type (KR, KG, KZ)
    message: str
    portalReferenceId: str
    accountingDocument: Optional[str] = None


@app.get("/sap/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Mock SAP ECC API",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.post("/sap/api/cfdi/invoice", response_model=SAPDocumentResponse)
async def post_invoice(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_cfdi_uuid: Optional[str] = Header(None),
    x_sap_document_type: Optional[str] = Header(None),
    x_company_code: Optional[str] = Header(None),
    x_supplier_id: Optional[str] = Header(None)
):
    """
    Mock SAP Invoice Posting Endpoint (XML format)
    Simulates SAP ECC invoice creation (BLART: KR)
    """
    print(f"\n{'=' * 70}")
    print(f"📥 Received INVOICE XML from Portal")
    print(f"{'=' * 70}")
    print(f"Portal Reference: {x_portal_reference}")
    print(f"CFDI UUID: {x_cfdi_uuid}")
    print(f"SAP BLART: {x_sap_document_type}")
    print(f"Supplier: {x_supplier_id}")
    print(f"Company Code: {x_company_code}")
    print(f"Authorization: {authorization}")
    
    # Validate authorization
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized: Missing or invalid API key")
    
    # Read XML body
    xml_body = await request.body()
    xml_string = xml_body.decode('utf-8')
    
    # Parse XML to extract key fields
    try:
        root = etree.fromstring(xml_body)
        folio = root.findtext("FOLIO", "N/A")
        total = root.findtext("TOTAL", "0.00")
        moneda = root.findtext("MONEDA", "MXN")
        cfdi_uuid_from_xml = root.findtext("CFDI_UUID", x_cfdi_uuid)
        
        print(f"\n📄 XML Data Extracted:")
        print(f"Folio: {folio}")
        print(f"Total: {total} {moneda}")
        print(f"CFDI UUID: {cfdi_uuid_from_xml}")
    except Exception as e:
        print(f"⚠️  XML parsing error: {e}")
        folio = "N/A"
        total = "0.00"
        moneda = "MXN"
    
    # Simulate SAP document number generation (KR document type)
    doc_number = f"50{random.randint(10000000, 99999999)}"
    fiscal_year = str(datetime.now().year)
    posting_date = datetime.now().strftime("%Y-%m-%d")
    accounting_doc = f"10{random.randint(10000000, 99999999)}"
    
    print(f"\n✅ SAP Document Posted!")
    print(f"Document Type (BLART): KR (Vendor Invoice)")
    print(f"Document Number: {doc_number}")
    print(f"Fiscal Year: {fiscal_year}")
    print(f"Accounting Document: {accounting_doc}")
    print(f"{'=' * 70}\n")
    
    return SAPDocumentResponse(
        success=True,
        documentNumber=doc_number,
        fiscalYear=fiscal_year,
        postingDate=posting_date,
        sapBlart="KR",
        message=f"Invoice {folio} posted successfully to SAP (BLART: KR)",
        portalReferenceId=x_portal_reference or "UNKNOWN",
        accountingDocument=accounting_doc
    )


@app.post("/sap/api/cfdi/payment", response_model=SAPDocumentResponse)
async def post_payment(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_cfdi_uuid: Optional[str] = Header(None),
    x_sap_document_type: Optional[str] = Header(None),
    x_company_code: Optional[str] = Header(None),
    x_supplier_id: Optional[str] = Header(None)
):
    """
    Mock SAP Payment Posting Endpoint (XML format)
    Simulates SAP ECC payment clearing (BLART: KZ)
    """
    print(f"\n{'=' * 70}")
    print(f"📥 Received PAYMENT XML from Portal")
    print(f"{'=' * 70}")
    print(f"Portal Reference: {x_portal_reference}")
    print(f"CFDI UUID: {x_cfdi_uuid}")
    print(f"SAP BLART: {x_sap_document_type}")
    print(f"Supplier: {x_supplier_id}")
    print(f"Company Code: {x_company_code}")
    
    # Read XML body
    xml_body = await request.body()
    
    # Parse XML
    try:
        root = etree.fromstring(xml_body)
        folio = root.findtext("FOLIO", "N/A")
        print(f"\n📄 XML Data Extracted:")
        print(f"Folio: {folio}")
    except Exception as e:
        print(f"⚠️  XML parsing error: {e}")
        folio = "N/A"
    
    # Simulate SAP clearing document (KZ document type)
    doc_number = f"51{random.randint(10000000, 99999999)}"
    fiscal_year = str(datetime.now().year)
    posting_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"\n✅ SAP Payment Cleared!")
    print(f"Document Type (BLART): KZ (Vendor Payment)")
    print(f"Clearing Document: {doc_number}")
    print(f"{'=' * 70}\n")
    
    return SAPDocumentResponse(
        success=True,
        documentNumber=doc_number,
        fiscalYear=fiscal_year,
        postingDate=posting_date,
        sapBlart="KZ",
        message=f"Payment {folio} cleared successfully in SAP (BLART: KZ)",
        portalReferenceId=x_portal_reference or "UNKNOWN"
    )


@app.post("/sap/api/cfdi/canonical", response_model=SAPDocumentResponse)
async def post_canonical_merged(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_canonical_id: Optional[str] = Header(None),
    x_company_code: Optional[str] = Header(None),
    x_fiscal_year: Optional[str] = Header(None),
    x_fiscal_period: Optional[str] = Header(None),
    x_vendor_rfc: Optional[str] = Header(None),
    x_document_type: Optional[str] = Header(None),
    x_cfdi_uuids: Optional[str] = Header(None),
    x_net_amount: Optional[str] = Header(None),
    x_currency: Optional[str] = Header(None)
):
    """
    Mock SAP Canonical Merged Document Endpoint (XML format)
    Simulates SAP ECC receiving merged INVOICE + PAYMENT + CREDIT_NOTE
    This is the MAIN endpoint for SAT Trial Balance integration
    """
    print(f"\n{'=' * 70}")
    print(f"📥 Received CANONICAL MERGED XML from Portal")
    print(f"{'=' * 70}")
    print(f"Canonical ID: {x_canonical_id}")
    print(f"Vendor RFC: {x_vendor_rfc}")
    print(f"Fiscal Period: {x_fiscal_period} / {x_fiscal_year}")
    print(f"Company Code: {x_company_code}")
    print(f"Net Amount: {x_net_amount} {x_currency}")
    print(f"CFDIs Included: {x_cfdi_uuids[:100] if x_cfdi_uuids else 'None'}...")
    print(f"Authorization: {authorization[:30]}..." if authorization else "None")
    
    # Validate authorization
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized: Missing or invalid API key")
    
    # Read XML body
    xml_body = await request.body()
    xml_string = xml_body.decode('utf-8')
    
    # Parse XML to extract key fields
    try:
        root = etree.fromstring(xml_body)
        rfc = root.findtext("RFC", x_vendor_rfc or "N/A")
        vendor_name = root.findtext("NOMBRE", "N/A")
        total_invoices = root.findtext("TOTAL_INVOICES", "0.00")
        total_credits = root.findtext("TOTAL_CREDITS", "0.00")
        total_payments = root.findtext("TOTAL_PAYMENTS", "0.00")
        net_amount = root.findtext("NET_AMOUNT", x_net_amount or "0.00")
        currency = root.findtext("MONEDA", x_currency or "MXN")
        gl_account = root.findtext("GL_ACCOUNT", "210999")
        
        print(f"\n📄 Canonical Merged Data Extracted:")
        print(f"Vendor: {vendor_name} ({rfc})")
        print(f"Total Invoices: {total_invoices} {currency}")
        print(f"Total Credits: {total_credits} {currency}")
        print(f"Total Payments: {total_payments} {currency}")
        print(f"Net Amount: {net_amount} {currency}")
        print(f"G/L Account: {gl_account}")
        
        # Count UUIDs in XML
        uuids = root.findall(".//CFDI_UUID")
        if not uuids:
            uuids = root.findall(".//UUID")
        print(f"Included CFDIs: {len(uuids)} documents")
        
    except Exception as e:
        print(f"⚠️  XML parsing error: {e}")
        vendor_name = "Unknown Vendor"
        net_amount = x_net_amount or "0.00"
        currency = x_currency or "MXN"
    
    # Simulate SAP document number generation for Trial Balance entry
    doc_number = f"TB{random.randint(1000000, 9999999)}"
    fiscal_year = x_fiscal_year or str(datetime.now().year)
    posting_date = datetime.now().strftime("%Y-%m-%d")
    accounting_doc = f"90{random.randint(10000000, 99999999)}"
    
    print(f"\n✅ SAP Trial Balance Entry Created!")
    print(f"Document Type: CANONICAL_MERGED (Trial Balance)")
    print(f"Document Number: {doc_number}")
    print(f"Fiscal Year: {fiscal_year}")
    print(f"Period: {x_fiscal_period}")
    print(f"Accounting Document: {accounting_doc}")
    print(f"Status: Stored in ZEDI_RAW_INBOUND → ZEDI_DOCS → ZEDI_FACTS")
    print(f"Next: SAP will generate Trial Balance report (Balanza)")
    print(f"{'=' * 70}\n")
    
    return SAPDocumentResponse(
        success=True,
        documentNumber=doc_number,
        fiscalYear=fiscal_year,
        postingDate=posting_date,
        sapBlart="CANONICAL",
        message=f"Canonical merged document for {vendor_name} posted successfully. SAP will generate Trial Balance.",
        portalReferenceId=x_canonical_id or "UNKNOWN",
        accountingDocument=accounting_doc
    )


@app.post("/sap/api/cfdi/credit-note", response_model=SAPDocumentResponse)
async def post_credit_note(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_cfdi_uuid: Optional[str] = Header(None),
    x_sap_document_type: Optional[str] = Header(None),
    x_company_code: Optional[str] = Header(None),
    x_supplier_id: Optional[str] = Header(None)
):
    """
    Mock SAP Credit Note Posting Endpoint (XML format)
    Simulates SAP ECC credit memo creation (BLART: KG)
    """
    print(f"\n{'=' * 70}")
    print(f"📥 Received CREDIT NOTE XML from Portal")
    print(f"{'=' * 70}")
    print(f"Portal Reference: {x_portal_reference}")
    print(f"CFDI UUID: {x_cfdi_uuid}")
    print(f"SAP BLART: {x_sap_document_type}")
    print(f"Supplier: {x_supplier_id}")
    print(f"Company Code: {x_company_code}")
    
    # Read XML body
    xml_body = await request.body()
    
    # Parse XML
    try:
        root = etree.fromstring(xml_body)
        folio = root.findtext("FOLIO", "N/A")
        total = root.findtext("TOTAL", "0.00")
        print(f"\n📄 XML Data Extracted:")
        print(f"Folio: {folio}")
        print(f"Total: {total}")
    except Exception as e:
        print(f"⚠️  XML parsing error: {e}")
        folio = "N/A"
        total = "0.00"
    
    # Simulate SAP credit memo document (KG document type)
    doc_number = f"52{random.randint(10000000, 99999999)}"
    fiscal_year = str(datetime.now().year)
    posting_date = datetime.now().strftime("%Y-%m-%d")
    accounting_doc = f"10{random.randint(10000000, 99999999)}"
    
    print(f"\n✅ SAP Credit Memo Posted!")
    print(f"Document Type (BLART): KG (Vendor Credit Memo)")
    print(f"Credit Memo: {doc_number}")
    print(f"Accounting Document: {accounting_doc}")
    print(f"{'=' * 70}\n")
    
    return SAPDocumentResponse(
        success=True,
        documentNumber=doc_number,
        fiscalYear=fiscal_year,
        postingDate=posting_date,
        sapBlart="KG",
        message=f"Credit note {folio} posted successfully to SAP (BLART: KG)",
        portalReferenceId=x_portal_reference or "UNKNOWN",
        accountingDocument=accounting_doc
    )


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 70)
    print("🚀 Starting Mock SAP ECC API")
    print("=" * 70)
    print("📍 Running on: http://localhost:8001")
    print("🏥 Health Check: http://localhost:8001/sap/health")
    print("=" * 70 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8001)

