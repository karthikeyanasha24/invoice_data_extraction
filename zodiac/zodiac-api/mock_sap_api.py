"""
Mock SAP API Server
Simulates SAP ECC REST API endpoints for testing CFDI integration
"""
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn
import random
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock-sap-api")

app = FastAPI(title="Mock SAP API", version="1.0.0")


class SAPDocumentResponse(BaseModel):
    success: bool
    sap_document_number: str
    message: str
    timestamp: str


@app.post("/sap/api/cfdi/invoice", response_model=SAPDocumentResponse)
async def post_cfdi_invoice(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_cfdi_uuid: Optional[str] = Header(None),
    x_supplier_rfc: Optional[str] = Header(None),
    x_document_type: Optional[str] = Header(None)
):
    """
    Mock endpoint for receiving CFDI INVOICE documents
    """
    body = await request.body()
    logger.info("=" * 80)
    logger.info("📨 MOCK SAP: Received INVOICE")
    logger.info(f"Headers:")
    logger.info(f"  Authorization: {authorization}")
    logger.info(f"  Portal Reference: {x_portal_reference}")
    logger.info(f"  CFDI UUID: {x_cfdi_uuid}")
    logger.info(f"  Supplier RFC: {x_supplier_rfc}")
    logger.info(f"  Document Type: {x_document_type}")
    logger.info(f"Body length: {len(body)} bytes")
    
    # Simulate SAP document number generation
    doc_number = f"KR{random.randint(1000000, 9999999)}"
    
    logger.info(f"✅ Generated SAP Document Number: {doc_number}")
    logger.info("=" * 80)
    
    return SAPDocumentResponse(
        success=True,
        sap_document_number=doc_number,
        message="CFDI Invoice posted successfully",
        timestamp=datetime.utcnow().isoformat()
    )


@app.post("/sap/api/cfdi/payment", response_model=SAPDocumentResponse)
async def post_cfdi_payment(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_cfdi_uuid: Optional[str] = Header(None),
    x_supplier_rfc: Optional[str] = Header(None),
    x_document_type: Optional[str] = Header(None)
):
    """
    Mock endpoint for receiving CFDI PAYMENT documents
    """
    body = await request.body()
    logger.info("=" * 80)
    logger.info("💰 MOCK SAP: Received PAYMENT")
    logger.info(f"Headers:")
    logger.info(f"  Authorization: {authorization}")
    logger.info(f"  Portal Reference: {x_portal_reference}")
    logger.info(f"  CFDI UUID: {x_cfdi_uuid}")
    logger.info(f"  Supplier RFC: {x_supplier_rfc}")
    logger.info(f"  Document Type: {x_document_type}")
    logger.info(f"Body length: {len(body)} bytes")
    
    # Simulate SAP document number generation
    doc_number = f"KG{random.randint(1000000, 9999999)}"
    
    logger.info(f"✅ Generated SAP Document Number: {doc_number}")
    logger.info("=" * 80)
    
    return SAPDocumentResponse(
        success=True,
        sap_document_number=doc_number,
        message="CFDI Payment posted successfully",
        timestamp=datetime.utcnow().isoformat()
    )


@app.post("/sap/api/cfdi/credit-note", response_model=SAPDocumentResponse)
async def post_cfdi_credit_note(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_cfdi_uuid: Optional[str] = Header(None),
    x_supplier_rfc: Optional[str] = Header(None),
    x_document_type: Optional[str] = Header(None)
):
    """
    Mock endpoint for receiving CFDI CREDIT NOTE documents
    """
    body = await request.body()
    logger.info("=" * 80)
    logger.info("📝 MOCK SAP: Received CREDIT NOTE")
    logger.info(f"Headers:")
    logger.info(f"  Authorization: {authorization}")
    logger.info(f"  Portal Reference: {x_portal_reference}")
    logger.info(f"  CFDI UUID: {x_cfdi_uuid}")
    logger.info(f"  Supplier RFC: {x_supplier_rfc}")
    logger.info(f"  Document Type: {x_document_type}")
    logger.info(f"Body length: {len(body)} bytes")
    
    # Simulate SAP document number generation
    doc_number = f"KZ{random.randint(1000000, 9999999)}"
    
    logger.info(f"✅ Generated SAP Document Number: {doc_number}")
    logger.info("=" * 80)
    
    return SAPDocumentResponse(
        success=True,
        sap_document_number=doc_number,
        message="CFDI Credit Note posted successfully",
        timestamp=datetime.utcnow().isoformat()
    )


@app.post("/sap/api/cfdi/canonical", response_model=SAPDocumentResponse)
async def post_canonical_merged(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_portal_reference: Optional[str] = Header(None),
    x_vendor_rfc: Optional[str] = Header(None),
    x_fiscal_period: Optional[str] = Header(None),
    x_fiscal_year: Optional[str] = Header(None),
    x_company_code: Optional[str] = Header(None)
):
    """
    Mock endpoint for receiving CANONICAL MERGED documents
    """
    body = await request.body()
    body_str = body.decode('utf-8')
    
    logger.info("=" * 80)
    logger.info("📦 MOCK SAP: Received CANONICAL MERGED DOCUMENT")
    logger.info(f"Headers:")
    logger.info(f"  Authorization: {authorization}")
    logger.info(f"  Portal Reference: {x_portal_reference}")
    logger.info(f"  Vendor RFC: {x_vendor_rfc}")
    logger.info(f"  Fiscal Period: {x_fiscal_period}")
    logger.info(f"  Fiscal Year: {x_fiscal_year}")
    logger.info(f"  Company Code: {x_company_code}")
    logger.info(f"Body length: {len(body)} bytes")
    
    # Try to extract key fields from XML
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body_str)
        
        # Extract some key fields
        vendor_rfc = root.findtext('.//RFC', 'N/A')
        total = root.findtext('.//TOTAL', 'N/A')
        gl_account = root.findtext('.//GL_ACCOUNT', 'N/A')
        
        logger.info(f"Extracted Fields:")
        logger.info(f"  Vendor RFC: {vendor_rfc}")
        logger.info(f"  Total Amount: {total}")
        logger.info(f"  GL Account: {gl_account}")
    except Exception as e:
        logger.warning(f"Could not parse XML: {e}")
    
    # Simulate SAP document number generation for Trial Balance entry
    doc_number = f"TB{random.randint(1000000, 9999999)}"
    
    logger.info(f"✅ Generated SAP Trial Balance Document Number: {doc_number}")
    logger.info("=" * 80)
    
    return SAPDocumentResponse(
        success=True,
        sap_document_number=doc_number,
        message="Canonical merged document posted successfully to Trial Balance",
        timestamp=datetime.utcnow().isoformat()
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Mock SAP API", "version": "1.0.0"}


if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Starting Mock SAP API Server")
    print("=" * 80)
    print("📍 Endpoints:")
    print("   POST http://localhost:9000/sap/api/cfdi/invoice")
    print("   POST http://localhost:9000/sap/api/cfdi/payment")
    print("   POST http://localhost:9000/sap/api/cfdi/credit-note")
    print("   POST http://localhost:9000/sap/api/cfdi/canonical")
    print("   GET  http://localhost:9000/health")
    print("=" * 80)
    print("💡 This mock API simulates SAP ECC REST endpoints for testing")
    print("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")

