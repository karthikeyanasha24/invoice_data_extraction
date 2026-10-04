"""
SAP Bulk Sender - Send all documents (canonical + simple merge) together
Follows client's format from 'multiplefiles' example.
Uses same CSRF + session pattern as sap_api_client for SAP compatibility.
"""
import httpx
import logging
from typing import Dict, Any, List
from datetime import datetime
from base64 import b64encode
from sqlalchemy.orm import Session

from ..models.sat_canonical_merged import SATCanonicalMerged
from ..models.sat_simple_merged import SATSimpleMerged
from ..services.sap_transformer import SAPTransformer

logger = logging.getLogger("zodiac-api.sap_bulk_sender")

class SAPBulkSender:
    def __init__(self, db: Session):
        self.db = db
        self.transformer = SAPTransformer(db)
        
        # SAP Configuration from client's credentials
        self.sap_url = "https://saperp.abor-tech.online/pisf_bill_srv/billing_integration"
        self.sap_client = "800"
        self.username = "andix"
        self.password = "init1234"

    def _get_auth_header(self) -> str:
        """Basic Auth header for SAP."""
        credentials = f"{self.username}:{self.password}"
        return f"Basic {b64encode(credentials.encode()).decode()}"
    
    async def send_all_to_sap(
        self,
        user_id: int,
        fiscal_year: int,
        fiscal_period: int
    ) -> Dict[str, Any]:
        """
        Send all pending documents to SAP in one batch.
        Combines canonical and simple merge documents.
        """
        logger.info(f"🚀 Starting bulk send to SAP for period {fiscal_year}-{fiscal_period:02d}")
        
        # 1. Fetch all pending canonical documents
        canonical_docs = self.db.query(SATCanonicalMerged).filter(
            SATCanonicalMerged.user_id == user_id,
            SATCanonicalMerged.fiscal_year == fiscal_year,
            SATCanonicalMerged.fiscal_period == fiscal_period,
            SATCanonicalMerged.status == 'MERGED',
            SATCanonicalMerged.sap_document_number == None
        ).all()
        
        # 2. Fetch all pending simple merge documents
        simple_docs = self.db.query(SATSimpleMerged).filter(
            SATSimpleMerged.user_id == user_id,
            SATSimpleMerged.fiscal_year == fiscal_year,
            SATSimpleMerged.fiscal_period == fiscal_period,
            SATSimpleMerged.sent_to_sap == False
        ).all()
        
        total_docs = len(canonical_docs) + len(simple_docs)
        
        if total_docs == 0:
            logger.info("📭 No pending documents to send")
            return {
                "success": True,
                "message": "No pending documents to send",
                "documents_sent": 0
            }
        
        logger.info(f"📦 Found {total_docs} documents: {len(canonical_docs)} canonical, {len(simple_docs)} simple")
        
        # 3. Transform all documents to SAP format
        sap_payload = []
        
        # Add canonical documents
        for doc in canonical_docs:
            transformed = self.transformer.transform_canonical_to_sap_format(doc)
            sap_payload.extend(transformed)  # canonical returns list of documents
        
        # Add simple merge documents
        for doc in simple_docs:
            transformed = self.transformer.transform_simple_to_sap_format(doc)
            sap_payload.extend(transformed)  # simple returns list of documents
        
        logger.info(f"📝 Transformed {len(sap_payload)} total documents for SAP")
        
        # 4. Send to SAP (with CSRF token + same session, same as single-doc flow)
        try:
            endpoint = f"{self.sap_url}?sap-client={self.sap_client}"
            auth_header = self._get_auth_header()
            async with httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True) as client:
                # Step 1: Fetch CSRF token (establishes session/cookies)
                logger.info("   Fetching CSRF token for bulk send...")
                get_headers = {
                    "Authorization": auth_header,
                    "x-csrf-token": "fetch",
                }
                csrf_response = await client.get(endpoint, headers=get_headers)
                if csrf_response.status_code != 200:
                    raise Exception(f"Failed to fetch CSRF token: {csrf_response.status_code} - {csrf_response.text[:300]}")
                csrf_token = csrf_response.headers.get("x-csrf-token")
                if not csrf_token or csrf_token == "fetch":
                    raise Exception("No CSRF token returned from SAP")
                logger.info("   CSRF token obtained, sending POST...")
                # Step 2: POST with CSRF token and session cookies
                post_headers = {
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "x-csrf-token": csrf_token,
                }
                response = await client.post(
                    endpoint,
                    headers=post_headers,
                    json=sap_payload,
                )
                response.raise_for_status()
                sap_response = response.json() if response.content else {}
                logger.info(f"✅ SAP Response: {response.status_code}")
                
        except httpx.HTTPStatusError as e:
            error_msg = f"SAP returned error {e.response.status_code}: {e.response.text[:500]}"
            logger.error(f"❌ {error_msg}")
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Failed to connect to SAP: {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise Exception(error_msg)
        
        # 5. Mark all documents as sent
        now = datetime.utcnow()
        sap_doc_number = f"BULK-{fiscal_year}{fiscal_period:02d}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        for doc in canonical_docs:
            doc.status = 'SAP_SENT'
            doc.sap_document_number = sap_doc_number
            doc.sent_to_sap_at = now
            doc.sap_response = str(sap_response)
        
        for doc in simple_docs:
            doc.sent_to_sap = True
            doc.status = 'SAP_SENT'
            doc.sap_document_number = sap_doc_number
            doc.sent_to_sap_at = now
            doc.sap_response = str(sap_response)
        
        self.db.commit()
        
        logger.info(f"✅ Successfully sent {total_docs} documents to SAP")
        
        return {
            "success": True,
            "message": f"Successfully sent {total_docs} documents to SAP",
            "documents_sent": total_docs,
            "canonical_sent": len(canonical_docs),
            "simple_sent": len(simple_docs),
            "sap_document_number": sap_doc_number,
            "sent_at": now.isoformat()
        }

