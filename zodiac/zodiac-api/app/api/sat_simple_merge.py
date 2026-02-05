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
from ..models.sat_supplier_account_mapping import SATSupplierAccountMapping

logger = logging.getLogger("zodiac-api.sat_simple_merge")

router = APIRouter(prefix="/sat/simple-merge", tags=["SAT Simple Merge"])


# =====================
# Helper Functions
# =====================

def safe_float_conversion(value, default=0.0):
    """
    Safely convert a value to float, handling comma separators and Decimal types.
    
    Args:
        value: The value to convert (string, int, float, Decimal, or None)
        default: Default value if conversion fails (default: 0.0)
    
    Returns:
        float: The converted value or default
    
    Examples:
        safe_float_conversion("1,000") -> 1000.0
        safe_float_conversion("1,000.50") -> 1000.5
        safe_float_conversion("1000") -> 1000.0
        safe_float_conversion(Decimal("100.50")) -> 100.5
        safe_float_conversion(None) -> 0.0
    """
    if value is None:
        return default
    
    # Handle numeric types (int, float, Decimal)
    if isinstance(value, (int, float)):
        return float(value)
    
    # Handle Decimal from SQLAlchemy
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
    except ImportError:
        pass
    
    # Handle string
    if isinstance(value, str):
        # Remove commas and whitespace
        cleaned = value.replace(',', '').strip()
        
        if not cleaned or cleaned == '':
            return default
        
        try:
            return float(cleaned)
        except ValueError:
            logger.warning(f"Could not convert '{value}' to float, using default {default}")
            return default
    
    # Try to convert any other type
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(f"Could not convert '{value}' (type: {type(value)}) to float, using default {default}")
        return default

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

@router.get("/check-merge-requirements/{supplier_rfc}")
async def check_merge_requirements(
    supplier_rfc: str,
    fiscal_year: int,
    fiscal_period: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check if all requirements are met for merging:
    1. All 3 document types exist (INVOICE, PAYMENT, CREDIT_NOTE)
    2. Mapping data exists for this RFC
    
    Returns merge eligibility status and details about what's present/missing.
    """
    try:
        logger.info(f"Checking merge requirements for RFC {supplier_rfc}, period {fiscal_year}-{fiscal_period}")
        
        # Query documents for this supplier and period
        documents = db.query(SATDocument).filter(
            SATDocument.user_id == current_user.id,
            SATDocument.supplier_rfc == supplier_rfc,
            func.extract('year', SATDocument.fecha) == fiscal_year,
            func.extract('month', SATDocument.fecha) == fiscal_period
        ).all()
        
        if not documents:
            return {
                "can_merge": False,
                "has_all_files": False,
                "missing_types": ["INVOICE", "PAYMENT", "CREDIT_NOTE"],
                "mapping_exists": False,
                "mapping_data": None,
                "document_count": 0
            }
        
        # Check which document types are present
        doc_types_present = set(doc.doc_type for doc in documents)
        required_types = {'INVOICE', 'PAYMENT', 'CREDIT_NOTE'}
        has_all_files = required_types.issubset(doc_types_present)
        missing_types = list(required_types - doc_types_present)
        
        logger.info(f"  Documents found: {len(documents)}, Types: {doc_types_present}")
        logger.info(f"  Has all files: {has_all_files}, Missing: {missing_types}")
        
        # Check if mapping exists for this RFC
        mapping = db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.supplier_rfc == supplier_rfc.upper(),
            SATSupplierAccountMapping.is_active == True
        ).first()
        
        mapping_exists = mapping is not None
        logger.info(f"  Mapping exists: {mapping_exists}")
        
        # Build response
        # Can only merge if BOTH all 3 files are present AND mapping data exists
        can_merge = has_all_files and mapping_exists
        logger.info(f"  Can merge: {can_merge} (files: {has_all_files}, mapping: {mapping_exists})")
        
        response = {
            "can_merge": can_merge,  # Require both all 3 files AND mapping data
            "has_all_files": has_all_files,
            "missing_types": missing_types,
            "document_types_present": list(doc_types_present),
            "document_count": len(documents),
            "mapping_exists": mapping_exists,
            "mapping_data": {
                "company_code": mapping.company_code or "",
                "sap_gl_account": mapping.sap_gl_account or "",
                "fiscal_year": mapping.fiscal_year or 0,
                "currency": mapping.currency or "",
                "account_description": mapping.account_description or ""
            } if mapping else None
        }
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Error checking merge requirements: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check merge requirements: {str(e)}"
        )


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
        
        # Validate that all 3 required document types are present
        doc_types_present = set(doc.doc_type for doc in documents)
        required_types = {'INVOICE', 'PAYMENT', 'CREDIT_NOTE'}
        
        if not required_types.issubset(doc_types_present):
            missing_types = list(required_types - doc_types_present)
            logger.warning(f"Cannot merge: Missing required document types: {missing_types}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot merge: Missing required document types: {', '.join(missing_types)}. All 3 types (Invoice, Payment, Credit Note) are required for merging."
            )
        
        logger.info(f"✅ All 3 required document types present: {doc_types_present}")
        
        # Validate that mapping data exists for this RFC
        mapping = db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.supplier_rfc == request.supplier_rfc.upper(),
            SATSupplierAccountMapping.is_active == True
        ).first()
        
        if not mapping:
            logger.warning(f"Cannot merge: No mapping data found for RFC {request.supplier_rfc}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot merge: No mapping data found for RFC {request.supplier_rfc}. Please add mapping data in the supplier mapping table before merging."
            )
        
        logger.info(f"✅ Mapping data exists for RFC {request.supplier_rfc}: GL Account {mapping.sap_gl_account}")
        
        # Check if a merge already exists with the same UUIDs
        # Get all existing merges for this period (allow multiple merges with different UUIDs)
        existing_merges = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.user_id == current_user.id,
            SATSimpleMerged.vendor_rfc == request.supplier_rfc,
            SATSimpleMerged.fiscal_year == request.fiscal_year,
            SATSimpleMerged.fiscal_period == request.fiscal_period
        ).all()
        
        # Build set of current document UUIDs
        current_uuids = set(doc.cfdi_uuid for doc in documents)
        
        # Check if any existing merge has the exact same UUIDs
        for existing_merge in existing_merges:
            existing_uuids = set(existing_merge.cfdi_uuids) if existing_merge.cfdi_uuids else set()
            if current_uuids == existing_uuids:
                logger.info(f"Merge already exists with these exact UUIDs, returning existing: {existing_merge.id}")
                return SimpleMergedResponse(
                    id=str(existing_merge.id),
                    vendor_rfc=existing_merge.vendor_rfc,
                    vendor_name=existing_merge.vendor_name,
                    fiscal_year=existing_merge.fiscal_year,
                    fiscal_period=existing_merge.fiscal_period,
                    document_count=existing_merge.document_count,
                    document_types=existing_merge.document_types,
                    cfdi_uuids=existing_merge.cfdi_uuids,
                    total_amount=safe_float_conversion(existing_merge.total_amount, None),
                    currency=existing_merge.currency,
                    created_at=existing_merge.created_at
                )
        
        # UUIDs are different - allow creating a new merge
        logger.info(f"Creating new merge for RFC {request.supplier_rfc} with different UUIDs")
        
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
                
                # Extract total from XML if not in database
                doc_total = doc.total
                if not doc_total or doc_total == '0' or doc_total == '0.0':
                    # Try to extract from XML root
                    xml_total = doc_xml_root.get('Total')
                    if xml_total:
                        doc_total = xml_total
                        logger.info(f"   📄 Document {doc.id}: Extracted total from XML: {xml_total}")
                
                # Wrap each document with metadata
                doc_wrapper = etree.SubElement(documents_container, "Document")
                etree.SubElement(doc_wrapper, "DocumentID").text = str(doc.id)
                etree.SubElement(doc_wrapper, "DocumentType").text = doc.doc_type
                etree.SubElement(doc_wrapper, "CFDI_UUID").text = doc.cfdi_uuid
                etree.SubElement(doc_wrapper, "Total").text = str(doc_total)
                etree.SubElement(doc_wrapper, "Currency").text = doc.moneda or 'MXN'
                etree.SubElement(doc_wrapper, "Date").text = doc.fecha.isoformat() if doc.fecha else ""
                
                # Add the actual CFDI XML
                xml_content_element = etree.SubElement(doc_wrapper, "CFDIContent")
                xml_content_element.append(doc_xml_root)
                
                # Collect metadata
                if doc.doc_type not in doc_types:
                    doc_types.append(doc.doc_type)
                cfdi_uuids.append(doc.cfdi_uuid)
                doc_total_value = safe_float_conversion(doc_total, 0.0)
                logger.info(f"   📄 Document {doc.id}: type={doc.doc_type}, total={doc_total}, converted={doc_total_value}")
                total_amount += doc_total_value
                
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
            total_amount=round(total_amount, 2) if total_amount > 0 else None,
            currency=currency,
            merged_xml_content=merged_xml_string
        )
        
        db.add(simple_merged)
        db.commit()
        db.refresh(simple_merged)
        
        logger.info(f"✅ Successfully merged {len(documents)} documents. Total amount: {total_amount}, Saved as {simple_merged.id}")
        
        return SimpleMergedResponse(
            id=str(simple_merged.id),
            vendor_rfc=simple_merged.vendor_rfc,
            vendor_name=simple_merged.vendor_name,
            fiscal_year=simple_merged.fiscal_year,
            fiscal_period=simple_merged.fiscal_period,
            document_count=simple_merged.document_count,
            document_types=simple_merged.document_types,
            cfdi_uuids=simple_merged.cfdi_uuids,
            total_amount=safe_float_conversion(simple_merged.total_amount, None),
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
                    total_amount=safe_float_conversion(doc.total_amount, None),
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
            total_amount=safe_float_conversion(document.total_amount, None),
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


@router.post("/{merged_id}/fetch-csrf-token")
async def fetch_csrf_token_for_simple_merge(
    merged_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch CSRF token from SAP for this document.
    Returns the token to display in UI before sending.
    """
    try:
        from ..services.sap_api_client import sap_client
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
        
        # Transform to get DS_UUID
        transformer = SAPTransformer(db)
        sap_payload = transformer.transform_simple_to_sap_format(document)
        
        # Extract first DS_UUID
        ds_uuid = None
        if sap_payload and len(sap_payload) > 0:
            ds_uuid = sap_payload[0].get("DS_UUID")
        
        # Fetch CSRF token
        csrf_token = await sap_client._fetch_csrf_token(ds_uuid)
        
        if not csrf_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch CSRF token from SAP"
            )
        
        logger.info(f"✅ CSRF token fetched for document {merged_id}: {csrf_token[:20]}...")
        
        return {
            "success": True,
            "csrf_token": csrf_token,
            "ds_uuid": ds_uuid,
            "message": "CSRF token fetched successfully. Ready to send to SAP."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to fetch CSRF token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch CSRF token: {str(e)}"
        )


class SendToSAPRequest(BaseModel):
    csrf_token: Optional[str] = None  # CSRF token from frontend


@router.post("/{merged_id}/send-to-sap")
async def send_simple_merge_to_sap(
    merged_id: str,
    request_data: SendToSAPRequest = None,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a simple merged document to SAP.
    Requires CSRF token to be fetched first and passed in request.
    """
    try:
        from ..services.sap_api_client import sap_client
        from ..services.sap_transformer import SAPTransformer
        
        # Extract CSRF token from request body
        csrf_token = None
        if request_data:
            csrf_token = request_data.csrf_token
        
        if not csrf_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSRF token is required. Please fetch CSRF token first."
            )
        
        logger.info(f"📤 Sending simple merged document {merged_id} to SAP...")
        logger.info(f"   Using CSRF token: {csrf_token[:20]}...")
        
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
        
        # Validate source documents have all required fields
        logger.info(f"   Validating source documents...")
        if document.cfdi_uuids:
            linked_docs = db.query(SATDocument).filter(
                SATDocument.cfdi_uuid.in_(document.cfdi_uuids)
            ).all()
            
            validation_errors = []
            for sat_doc in linked_docs:
                doc_errors = []
                if not sat_doc.cfdi_uuid:
                    doc_errors.append("Missing CFDI UUID")
                if not sat_doc.total:
                    doc_errors.append("Missing total amount")
                if not sat_doc.moneda:
                    doc_errors.append("Missing currency")
                if not sat_doc.folio:
                    doc_errors.append("Missing folio")
                if not sat_doc.serie:
                    doc_errors.append("Missing serie")
                if not sat_doc.subtotal:
                    doc_errors.append("Missing subtotal")
                
                if doc_errors:
                    validation_errors.append({
                        "document_id": str(sat_doc.id),
                        "folio": sat_doc.folio or "N/A",
                        "doc_type": sat_doc.doc_type or "N/A",
                        "errors": doc_errors
                    })
            
            if validation_errors:
                error_details = "\n".join([
                    f"- Document {err['doc_type']} (Folio: {err['folio']}): {', '.join(err['errors'])}"
                    for err in validation_errors
                ])
                logger.error(f"❌ Source documents have missing data:\n{error_details}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot send to SAP: Source documents have missing data. Please run the data integrity verification script to fix.\n\nIssues found:\n{error_details}"
                )
        
        logger.info(f"   ✅ All source documents validated successfully")
        
        # Use SAPTransformer to build proper payload with all fields including mapping data
        transformer = SAPTransformer(db)
        sap_payload = transformer.transform_simple_to_sap_format(document)
        
        if not sap_payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to generate SAP payload from document"
            )
        
        logger.info(f"   Prepared {len(sap_payload)} document(s) for SAP with mapping data")
        
        # Send to SAP using session-based approach (handles CSRF + cookies)
        sap_response = await sap_client.send_json_to_sap_with_session(
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


@router.delete("/{merged_id}")
async def delete_simple_merge(
    merged_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a simple merged document.
    Cannot delete if the document has already been sent to SAP.
    """
    try:
        logger.info(f"🗑️ Attempting to delete simple merge {merged_id}")
        
        # Find the merge document
        merge = db.query(SATSimpleMerged).filter(
            SATSimpleMerged.id == merged_id,
            SATSimpleMerged.user_id == current_user.id
        ).first()
        
        if not merge:
            logger.warning(f"Merge {merged_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Simple merged document {merged_id} not found"
            )
        
        # Prevent deletion if already sent to SAP
        if merge.sent_to_sap:
            logger.warning(f"Cannot delete merge {merged_id}: already sent to SAP")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete merge that has been sent to SAP. SAP Document #: {merge.sap_document_number}"
            )
        
        # Delete the merge
        vendor_rfc = merge.vendor_rfc
        fiscal_period = f"{merge.fiscal_year}-{merge.fiscal_period}"
        
        db.delete(merge)
        db.commit()
        
        logger.info(f"✅ Successfully deleted simple merge {merged_id} for RFC {vendor_rfc}, period {fiscal_period}")
        
        return {
            "success": True,
            "message": f"Simple merged document deleted successfully",
            "deleted_id": merged_id,
            "vendor_rfc": vendor_rfc,
            "fiscal_period": fiscal_period
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting simple merge {merged_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete simple merged document: {str(e)}"
        )
