"""
Debug endpoint to test source parameter directly
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging

from ..database import get_db
from ..api.supplier_auth import get_supplier_token
from ..models.supplier_token import SupplierToken
from ..models.sat_document import SATDocument

logger = logging.getLogger("zodiac-api.sat_debug")

router = APIRouter(prefix="/sat-debug", tags=["SAT Debug"])


class DebugSourceRequest(BaseModel):
    test_value: str


@router.post("/test-source")
async def test_source_parameter(
    request: DebugSourceRequest,
    supplier_token: SupplierToken = Depends(get_supplier_token),
    db: Session = Depends(get_db)
):
    """
    Test endpoint to verify source parameter is being passed correctly.
    This endpoint explicitly sets source='supplier' and checks what gets saved.
    """
    try:
        import uuid
        from datetime import datetime
        
        logger.info("=" * 80)
        logger.info("🧪 DEBUG TEST - Source Parameter")
        logger.info("=" * 80)
        
        logger.info(f"📥 Received request from supplier: {supplier_token.supplier_rfc}")
        logger.info(f"📥 Test value: {request.test_value}")
        
        # Create a test document with EXPLICIT source='supplier'
        logger.info("📝 Creating test SATDocument with source='supplier'...")
        
        test_doc = SATDocument(
            id=uuid.uuid4(),
            user_id=supplier_token.created_by,
            portal_ref_id=f"TEST-DEBUG-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            cfdi_uuid=f"test-{uuid.uuid4()}",
            doc_type="INVOICE",
            supplier_rfc=supplier_token.supplier_rfc,
            supplier_name=supplier_token.supplier_name or "Test Supplier",
            receiver_rfc="XAXX010101000",
            receiver_name="Test Receiver",
            fecha=datetime.utcnow(),
            total="1000.00",
            moneda="MXN",
            status="TEST",
            source='supplier',  # 🔴 EXPLICIT VALUE
            xml_content=f"<!-- Test XML: {request.test_value} -->",
            xml_hash="test_hash",
            file_size=100,
            received_at=datetime.utcnow()
        )
        
        logger.info(f"✅ SATDocument object created with source='{test_doc.source}'")
        
        # Save to database
        logger.info("💾 Saving to database...")
        db.add(test_doc)
        db.commit()
        db.refresh(test_doc)
        
        logger.info(f"✅ Saved to database. Document ID: {test_doc.id}")
        logger.info(f"🔍 CHECKING: After db.refresh(), source = '{test_doc.source}'")
        
        # Query back from database to triple-check
        logger.info("🔍 Querying back from database to verify...")
        db_doc = db.query(SATDocument).filter(SATDocument.id == test_doc.id).first()
        
        if db_doc:
            logger.info(f"✅ Found in database: ID={db_doc.id}")
            logger.info(f"🔴 SOURCE VALUE IN DB: '{db_doc.source}'")
        else:
            logger.error("❌ Could not find document in database!")
        
        logger.info("=" * 80)
        
        return {
            "success": True,
            "message": "Debug test completed",
            "document_id": str(test_doc.id),
            "source_before_save": 'supplier',
            "source_after_save": test_doc.source,
            "source_from_db_query": db_doc.source if db_doc else "NOT_FOUND",
            "expected": "supplier",
            "test_passed": db_doc.source == 'supplier' if db_doc else False,
            "details": {
                "supplier_rfc": supplier_token.supplier_rfc,
                "portal_ref_id": test_doc.portal_ref_id,
                "test_value": request.test_value
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Debug test failed: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Debug test error: {str(e)}"
        )


@router.get("/check-source/{portal_ref_id}")
async def check_document_source(
    portal_ref_id: str,
    db: Session = Depends(get_db)
):
    """
    Check the source value of a specific document by portal_ref_id.
    Use this to verify what's actually in the database.
    """
    try:
        doc = db.query(SATDocument).filter(
            SATDocument.portal_ref_id == portal_ref_id
        ).first()
        
        if not doc:
            raise HTTPException(
                status_code=404,
                detail=f"Document with portal_ref_id '{portal_ref_id}' not found"
            )
        
        return {
            "portal_ref_id": doc.portal_ref_id,
            "source": doc.source,
            "supplier_rfc": doc.supplier_rfc,
            "doc_type": doc.doc_type,
            "received_at": doc.received_at.isoformat() if doc.received_at else None,
            "user_id": doc.user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Check source failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error: {str(e)}"
        )
