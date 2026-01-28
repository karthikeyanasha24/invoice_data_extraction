from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging
from lxml import etree

from ..database import get_db
from ..api.auth import get_current_user
from ..models.user import ZodiacUser
from ..models.sat_document import SATDocument
from ..models.sat_simple_merged import SATSimpleMerged

logger = logging.getLogger("zodiac-api.sat_simple_merge")

router = APIRouter(prefix="/sat/simple-merge", tags=["SAT Simple Merge"])

# =====================
# Request/Response Models
# =====================

class SimpleMergeRequest(BaseModel):
    fiscal_year: int
    fiscal_period: int  # 1-12
    supplier_rfc: str

class SimpleMergedResponse(BaseModel):
    id: str
    vendor_rfc: str
    vendor_name: Optional[str]
    fiscal_year: int
    fiscal_period: int
    document_count: int
    document_types: Optional[List[str]]
    cfdi_uuids: Optional[List[str]]
    total_amount: Optional[float]
    currency: str
    sent_to_sap: Optional[bool] = False
    sap_document_number: Optional[str] = None
    sent_to_sap_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SimpleMergedListResponse(BaseModel):
    documents: List[SimpleMergedResponse]
    total: int

class SimpleMergedDetailResponse(SimpleMergedResponse):
    merged_xml_content: str


# =====================
# Endpoints
# =====================

@router.post("/merge", response_model=SimpleMergedResponse)
async def merge_documents(
    request: SimpleMergeRequest,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Merge SAT documents for a specific supplier and fiscal period.
    Saves the merged XML to the database.
    """
    try:
        logger.info(f"Merging documents for supplier {request.supplier_rfc}, period {request.fiscal_year}-{request.fiscal_period}")
        
        # Fetch documents for the specified supplier and period
        documents = db.query(SATDocument).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.supplier_rfc == request.supplier_rfc,
            func.extract('year', SATDocument.fecha) == request.fiscal_year,
            func.extract('month', SATDocument.fecha) == request.fiscal_period
        ).all()
        
        if not documents:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No documents found for supplier {request.supplier_rfc} in period {request.fiscal_year}-{request.fiscal_period}"
            )
        
        # Check if a merge already exists
        existing_merge = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.user_id == current_user.id,
            SATSimpleMerged.vendor_rfc == request.supplier_rfc,
            SATSimpleMerged.fiscal_year == request.fiscal_year,
            SATSimpleMerged.fiscal_period == request.fiscal_period
        ).first()
        
        if existing_merge:
            logger.info(f"Merge already exists for this period, returning existing: {existing_merge.id}")
            return SimpleMergedResponse(
                id=str(existing_merge.id),
                vendor_rfc=existing_merge.vendor_rfc,
                vendor_name=existing_merge.vendor_name,
                fiscal_year=existing_merge.fiscal_year,
                fiscal_period=existing_merge.fiscal_period,
                document_count=existing_merge.document_count,
                document_types=existing_merge.document_types,
                cfdi_uuids=existing_merge.cfdi_uuids,
                total_amount=float(existing_merge.total_amount) if existing_merge.total_amount else None,
                currency=existing_merge.currency,
                created_at=existing_merge.created_at
            )
        
        # Build merged XML
        merged_root = etree.Element("MergedSATDocuments")
        
        # Add metadata
        metadata = etree.SubElement(merged_root, "Metadata")
        etree.SubElement(metadata, "VendorRFC").text = request.supplier_rfc
        etree.SubElement(metadata, "VendorName").text = documents[0].supplier_name or request.supplier_rfc
        etree.SubElement(metadata, "FiscalYear").text = str(request.fiscal_year)
        etree.SubElement(metadata, "FiscalPeriod").text = str(request.fiscal_period)
        etree.SubElement(metadata, "DocumentCount").text = str(len(documents))
        etree.SubElement(metadata, "MergedAt").text = datetime.utcnow().isoformat()
        
        # Add documents container
        documents_container = etree.SubElement(merged_root, "Documents")
        
        # Collect data for database record
        doc_types = []
        cfdi_uuids = []
        total_amount = 0.0
        currency = documents[0].moneda or 'MXN'  # Use 'moneda' field, not 'currency'
        vendor_name = documents[0].supplier_name or request.supplier_rfc
        
        for doc in documents:
            if not doc.xml_content:
                logger.warning(f"Document {doc.id} has no XML content stored.")
                continue
            
            try:
                # Parse the individual XML and append its root to the documents container
                doc_xml_root = etree.fromstring(doc.xml_content.encode('utf-8'))
                
                # Wrap each document with metadata
                doc_wrapper = etree.SubElement(documents_container, "Document")
                etree.SubElement(doc_wrapper, "DocumentID").text = str(doc.id)
                etree.SubElement(doc_wrapper, "DocumentType").text = doc.doc_type
                etree.SubElement(doc_wrapper, "CFDI_UUID").text = doc.cfdi_uuid
                etree.SubElement(doc_wrapper, "Total").text = str(doc.total)
                etree.SubElement(doc_wrapper, "Currency").text = doc.moneda or 'MXN'
                etree.SubElement(doc_wrapper, "Date").text = doc.fecha.isoformat() if doc.fecha else ""
                
                # Add the actual CFDI XML
                xml_content_element = etree.SubElement(doc_wrapper, "CFDIContent")
                xml_content_element.append(doc_xml_root)
                
                # Collect metadata
                if doc.doc_type not in doc_types:
                    doc_types.append(doc.doc_type)
                cfdi_uuids.append(doc.cfdi_uuid)
                total_amount += float(doc.total or 0)
                
            except etree.XMLSyntaxError as e:
                logger.error(f"Failed to parse XML for document {doc.id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid XML content for document {doc.id}: {e}"
                )
        
        # Convert to string
        merged_xml_string = etree.tostring(
            merged_root, 
            pretty_print=True, 
            encoding='UTF-8', 
            xml_declaration=True
        ).decode('utf-8')
        
        # Save to database
        simple_merged = SATSimpleMerged(
            user_id=current_user.id,
            vendor_rfc=request.supplier_rfc,
            vendor_name=vendor_name,
            fiscal_year=request.fiscal_year,
            fiscal_period=request.fiscal_period,
            document_count=len(documents),
            document_types=doc_types,
            cfdi_uuids=cfdi_uuids,
            total_amount=total_amount,
            currency=currency,
            merged_xml_content=merged_xml_string
        )
        
        db.add(simple_merged)
        db.commit()
        db.refresh(simple_merged)
        
        logger.info(f"Successfully merged {len(documents)} documents. Saved as {simple_merged.id}")
        
        return SimpleMergedResponse(
            id=str(simple_merged.id),
            vendor_rfc=simple_merged.vendor_rfc,
            vendor_name=simple_merged.vendor_name,
            fiscal_year=simple_merged.fiscal_year,
            fiscal_period=simple_merged.fiscal_period,
            document_count=simple_merged.document_count,
            document_types=simple_merged.document_types,
            cfdi_uuids=simple_merged.cfdi_uuids,
            total_amount=float(simple_merged.total_amount) if simple_merged.total_amount else None,
            currency=simple_merged.currency,
            created_at=simple_merged.created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during simple merge: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during merge: {str(e)}"
        )


@router.get("/", response_model=SimpleMergedListResponse)
async def list_simple_merged_documents(
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all simple merged documents for the current user.
    """
    try:
        query = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.user_id == current_user.id
        )
        
        if fiscal_year:
            query = query.filter(SATSimpleMerged.fiscal_year == fiscal_year)
        if fiscal_period:
            query = query.filter(SATSimpleMerged.fiscal_period == fiscal_period)
        
        total = query.count()
        
        documents = query.order_by(
            SATSimpleMerged.fiscal_year.desc(),
            SATSimpleMerged.fiscal_period.desc(),
            SATSimpleMerged.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return SimpleMergedListResponse(
            documents=[
                SimpleMergedResponse(
                    id=str(doc.id),
                    vendor_rfc=doc.vendor_rfc,
                    vendor_name=doc.vendor_name,
                    fiscal_year=doc.fiscal_year,
                    fiscal_period=doc.fiscal_period,
                    document_count=doc.document_count,
                    document_types=doc.document_types,
                    cfdi_uuids=doc.cfdi_uuids,
                    total_amount=float(doc.total_amount) if doc.total_amount else None,
                    currency=doc.currency,
                    sent_to_sap=doc.sent_to_sap if hasattr(doc, 'sent_to_sap') else False,
                    sap_document_number=doc.sap_document_number if hasattr(doc, 'sap_document_number') else None,
                    sent_to_sap_at=doc.sent_to_sap_at if hasattr(doc, 'sent_to_sap_at') else None,
                    created_at=doc.created_at
                )
                for doc in documents
            ],
            total=total
        )
    except Exception as e:
        logger.error(f"Error listing simple merged documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch simple merged documents: {str(e)}"
        )


@router.get("/{merged_id}", response_model=SimpleMergedDetailResponse)
async def get_simple_merged_document(
    merged_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get details of a specific simple merged document.
    """
    try:
        document = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.id == merged_id,
            SATSimpleMerged.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simple merged document {merged_id} not found"
            )
        
        return SimpleMergedDetailResponse(
            id=str(document.id),
            vendor_rfc=document.vendor_rfc,
            vendor_name=document.vendor_name,
            fiscal_year=document.fiscal_year,
            fiscal_period=document.fiscal_period,
            document_count=document.document_count,
            document_types=document.document_types,
            cfdi_uuids=document.cfdi_uuids,
            total_amount=float(document.total_amount) if document.total_amount else None,
            currency=document.currency,
            created_at=document.created_at,
            merged_xml_content=document.merged_xml_content
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting simple merged document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch document: {str(e)}"
        )


@router.get("/{merged_id}/download", response_class=Response)
async def download_simple_merged_xml(
    merged_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download the merged XML file.
    """
    try:
        document = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.id == merged_id,
            SATSimpleMerged.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simple merged document {merged_id} not found"
            )
        
        filename = f"merged_cfdi_{document.vendor_rfc}_{document.fiscal_year}_{str(document.fiscal_period).zfill(2)}.xml"
        
        return Response(
            content=document.merged_xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading merged XML: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download XML: {str(e)}"
        )


@router.get("/{merged_id}/preview-sap-json")
async def preview_simple_merge_sap_json(
    merged_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate and return the SAP JSON payload for preview before sending.
    """
    try:
        from ..services.sap_transformer import SAPTransformer
        
        # Fetch the document
        document = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.id == merged_id,
            SATSimpleMerged.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simple merged document {merged_id} not found"
            )
        
        # Transform to SAP format
        transformer = SAPTransformer(db)
        sap_payload = transformer.transform_simple_to_sap_format(document)
        
        return {"json_payload": sap_payload}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate preview: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate preview: {str(e)}"
        )


@router.post("/{merged_id}/send-to-sap")
async def send_simple_merge_to_sap(
    merged_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a simple merged document to SAP.
    Converts the XML to the format specified by client (singlefile/multiplefiles).
    """
    try:
        from ..services.sap_api_client import sap_client
        from lxml import etree
        
        logger.info(f"📤 Sending simple merged document {merged_id} to SAP...")
        
        # Fetch the document
        document = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.id == merged_id,
            SATSimpleMerged.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simple merged document {merged_id} not found"
            )
        
        # Check if already sent
        if document.sent_to_sap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document already sent to SAP. SAP Doc #: {document.sap_document_number}"
            )
        
        # Parse the merged XML to extract individual documents
        try:
            merged_root = etree.fromstring(document.merged_xml_content.encode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse merged XML: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid merged XML content: {str(e)}"
            )
        
        # Build JSON payload in client's format (array of documents)
        sap_payload = []
        
        # Extract each document
        for doc_wrapper in merged_root.findall('.//Document'):
            try:
                # Extract metadata from wrapper
                doc_id = doc_wrapper.findtext('DocumentID', 'N/A')
                doc_type = doc_wrapper.findtext('DocumentType', 'I')  # Default to INVOICE
                cfdi_uuid = doc_wrapper.findtext('CFDI_UUID', '')
                total = doc_wrapper.findtext('Total', '0')
                currency = doc_wrapper.findtext('Currency', 'MXN')
                doc_date = doc_wrapper.findtext('Date', '')
                
                # Map document type to SAP format
                # INVOICE → I, CREDIT_NOTE → C, PAYMENT → P
                sap_doc_type = {
                    'INVOICE': 'I',
                    'CREDIT_NOTE': 'C',
                    'PAYMENT': 'P'
                }.get(doc_type, 'I')
                
                # Extract CFDI content
                cfdi_content = doc_wrapper.find('.//CFDIContent')
                if cfdi_content is not None and len(cfdi_content) > 0:
                    cfdi_root = cfdi_content[0]  # Get first child (the actual CFDI)
                    
                    # Extract more fields from CFDI if available
                    # This is a simplified version - adjust based on actual CFDI structure
                    comprobante_ns = cfdi_root.nsmap.get(None, '')
                    
                    # Build document payload matching client's format
                    doc_payload = {
                        "DS_UUID": cfdi_uuid,
                        "DOCUMENT_TYPE": sap_doc_type,
                        "DOC_NUMBER": doc_id,
                        "VERSION": "4.0",
                        "ISSUE_DATETIME": doc_date.replace('-', '').replace(':', '').replace('T', '').replace('.', '')[:14] if doc_date else "",
                        "CURRENCY": currency,
                        "TOTAL_AMOUNT": float(total),
                        "ISSUER_NAME": document.vendor_name or document.vendor_rfc,
                        "ISSUER_TAX_ID": document.vendor_rfc,
                        # Add more fields as needed
                        "ITEMS": []  # Can be extracted from CFDI if needed
                    }
                    
                    sap_payload.append(doc_payload)
                    
            except Exception as e:
                logger.error(f"Error processing document {doc_id}: {e}")
                continue
        
        if not sap_payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid documents found in merged XML"
            )
        
        logger.info(f"   Prepared {len(sap_payload)} document(s) for SAP")
        
        # Send to SAP using the new client
        sap_response = await sap_client.send_json_to_sap(
            payload=sap_payload,
            document_type="SIMPLE_MERGE",
            portal_reference=str(merged_id)
        )
        
        if sap_response.get('success'):
            # Update document status
            document.sent_to_sap = True
            document.sent_to_sap_at = datetime.utcnow()
            
            # Try to extract SAP document number from response
            sap_doc_number = None
            if isinstance(sap_response.get('sap_response'), dict):
                sap_doc_number = sap_response['sap_response'].get('document_number') or sap_response['sap_response'].get('sap_document_number')
            
            # If no document number, generate a reference
            if not sap_doc_number:
                import random
                sap_doc_number = f"SM{random.randint(1000000, 9999999)}"
            
            document.sap_document_number = sap_doc_number
            document.sap_response = str(sap_response)
            
            db.commit()
            db.refresh(document)
            
            logger.info(f"✅ Simple merge {merged_id} sent to SAP successfully. SAP Doc #: {sap_doc_number}")
            
            return {
                "success": True,
                "sap_document_number": sap_doc_number,
                "sent_at": document.sent_to_sap_at.isoformat(),
                "message": "Simple merged document sent to SAP successfully",
                "sap_response": sap_response
            }
        else:
            logger.error(f"❌ Failed to send to SAP: {sap_response.get('error')}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SAP returned error: {sap_response.get('error')}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error sending to SAP: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send to SAP: {str(e)}"
        )
