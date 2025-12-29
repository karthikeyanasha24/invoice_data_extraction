"""
SAP API Client
Handles communication with SAP ECC REST API
"""
import httpx
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class SAPAPIClient:
    """
    Client for communicating with SAP ECC REST API
    Sends transformed documents and handles responses
    """
    
    def __init__(self):
        # Load SAP API configuration from environment
        self.sap_base_url = os.getenv("SAP_API_BASE_URL", "http://localhost:8001/sap")
        self.sap_api_key = os.getenv("SAP_API_KEY", "test-sap-key-123")
        self.sap_timeout = int(os.getenv("SAP_API_TIMEOUT", "30"))
        
        logger.info(f"🔧 SAP API Client initialized: {self.sap_base_url}")
    
    async def send_document_to_sap(
        self,
        portal_reference_id: str,
        document_type: str,
        sap_xml: str,
        sap_blart: str,
        company_code: str,
        supplier_id: str,
        cfdi_uuid: str
    ) -> Dict[str, Any]:
        """
        Sends a transformed document to SAP ECC (XML format)
        
        Args:
            portal_reference_id: Portal tracking ID
            document_type: INVOICE, PAYMENT, or CREDIT_NOTE
            sap_xml: Transformed SAP XML document
            sap_blart: SAP document type (KR, KG, KZ)
            company_code: SAP company code (e.g., "1000")
            supplier_id: Supplier identifier
            cfdi_uuid: CFDI UUID
        
        Returns:
            SAP API response with document number, status, etc.
        """
        try:
            logger.info(f"📤 Sending {document_type} (BLART: {sap_blart}) to SAP: {portal_reference_id}")
            
            # Determine SAP endpoint based on document type
            endpoint = self._get_sap_endpoint(document_type)
            full_url = f"{self.sap_base_url}{endpoint}"
            
            # Make API call with XML payload
            async with httpx.AsyncClient(timeout=self.sap_timeout) as client:
                response = await client.post(
                    full_url,
                    content=sap_xml,
                    headers={
                        "Content-Type": "application/xml; charset=utf-8",
                        "Authorization": f"Bearer {self.sap_api_key}",
                        "X-Portal-Reference": portal_reference_id,
                        "X-CFDI-UUID": cfdi_uuid,
                        "X-SAP-Document-Type": sap_blart,
                        "X-Company-Code": company_code,
                        "X-Supplier-ID": supplier_id
                    }
                )
                
                # Log response
                logger.info(f"📥 SAP API Response [{response.status_code}]: {portal_reference_id}")
                
                # Handle response (SAP may return JSON or XML)
                if response.status_code in [200, 201, 202]:
                    # Try to parse as JSON first
                    try:
                        sap_response = response.json()
                    except:
                        # If not JSON, treat as success with text response
                        sap_response = {"message": response.text}
                    
                    logger.info(f"✅ SAP accepted document: {portal_reference_id}")
                    return {
                        "success": True,
                        "status_code": response.status_code,
                        "sap_document_number": sap_response.get("documentNumber") or sap_response.get("sapDocumentNumber"),
                        "sap_fiscal_year": sap_response.get("fiscalYear") or sap_response.get("sapFiscalYear"),
                        "sap_posting_date": sap_response.get("postingDate") or sap_response.get("sapPostingDate"),
                        "sap_blart": sap_blart,
                        "sap_message": sap_response.get("message", "Document posted successfully"),
                        "raw_response": sap_response
                    }
                else:
                    error_body = response.text
                    logger.error(f"❌ SAP API Error [{response.status_code}]: {error_body}")
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "error_message": error_body,
                        "error_code": f"SAP_ERROR_{response.status_code}"
                    }
                    
        except httpx.TimeoutException as e:
            logger.error(f"⏱️ SAP API Timeout: {e}")
            return {
                "success": False,
                "error_message": "SAP API timeout",
                "error_code": "SAP_TIMEOUT"
            }
        except Exception as e:
            logger.error(f"❌ SAP API Error: {e}")
            return {
                "success": False,
                "error_message": str(e),
                "error_code": "SAP_CONNECTION_ERROR"
            }
    
    def _get_sap_endpoint(self, document_type: str) -> str:
        """Get SAP endpoint based on document type"""
        endpoints = {
            "INVOICE": "/api/cfdi/invoice",
            "PAYMENT": "/api/cfdi/payment",
            "CREDIT_NOTE": "/api/cfdi/credit-note"
        }
        return endpoints.get(document_type, "/api/cfdi/document")
    
    async def send_trial_balance_to_sap(
        self,
        trial_balance,
        xml_payload: str
    ) -> Dict[str, Any]:
        """
        Send Trial Balance (merged documents) to SAP.
        Following ChatGPT pattern: one call with aggregated data per vendor per period.
        
        Args:
            trial_balance: SATTrialBalance model instance
            xml_payload: Generated SAP XML for trial balance
            
        Returns:
            SAP API response
        """
        try:
            logger.info(f"📤 Sending Trial Balance to SAP: {trial_balance.vendor_rfc} {trial_balance.fiscal_year}-{trial_balance.fiscal_period:02d}")
            
            # Use dedicated trial balance endpoint
            endpoint = "/api/sat/trial-balance"
            full_url = f"{self.sap_base_url}{endpoint}"
            
            # Make API call
            async with httpx.AsyncClient(timeout=self.sap_timeout) as client:
                response = await client.post(
                    full_url,
                    content=xml_payload,
                    headers={
                        "Content-Type": "application/xml; charset=utf-8",
                        "Authorization": f"Bearer {self.sap_api_key}",
                        "X-Company-Code": trial_balance.company_code,
                        "X-Fiscal-Year": str(trial_balance.fiscal_year),
                        "X-Fiscal-Period": str(trial_balance.fiscal_period).zfill(2),
                        "X-Vendor-RFC": trial_balance.vendor_rfc,
                        "X-Net-Balance": str(trial_balance.net_balance),
                        "X-Document-Count": str(trial_balance.document_count)
                    }
                )
                
                logger.info(f"📥 SAP API Response [{response.status_code}] for Trial Balance: {trial_balance.vendor_rfc}")
                
                if response.status_code in [200, 201, 202]:
                    try:
                        sap_response = response.json()
                    except:
                        sap_response = {"message": response.text}
                    
                    logger.info(f"✅ SAP accepted trial balance: {trial_balance.vendor_rfc}")
                    
                    return {
                        "success": True,
                        "status_code": response.status_code,
                        "documentNumber": sap_response.get("documentNumber") or sap_response.get("sapDocumentNumber"),
                        "fiscalYear": sap_response.get("fiscalYear") or sap_response.get("sapFiscalYear"),
                        "message": sap_response.get("message", "Trial balance posted successfully"),
                        "raw_response": sap_response
                    }
                else:
                    error_body = response.text
                    logger.error(f"❌ SAP API Error [{response.status_code}]: {error_body}")
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "error_message": error_body,
                        "error_code": f"SAP_ERROR_{response.status_code}"
                    }
                    
        except httpx.TimeoutException as e:
            logger.error(f"⏱️ SAP API Timeout: {e}")
            return {
                "success": False,
                "error_message": "SAP API timeout",
                "error_code": "SAP_TIMEOUT"
            }
        except Exception as e:
            logger.error(f"❌ SAP API Error: {e}")
            return {
                "success": False,
                "error_message": str(e),
                "error_code": "SAP_CONNECTION_ERROR"
            }
    
    async def check_sap_health(self) -> bool:
        """
        Check if SAP API is reachable
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{self.sap_base_url}/health",
                    headers={"Authorization": f"Bearer {self.sap_api_key}"}
                )
                return response.status_code == 200
        except:
            return False
    
    async def send_canonical_to_sap(
        self,
        canonical,
        xml_payload: str
    ) -> Dict[str, Any]:
        """
        Send a canonical merged document to SAP.
        This is ONE unified XML containing merged data from INVOICE + PAYMENT + CREDIT_NOTE.
        
        Args:
            canonical: SATCanonicalMerged object
            xml_payload: The transformed SAP XML
            
        Returns:
            SAP response dict
        """
        from app.models.sat_canonical_merged import SATCanonicalMerged
        
        logger.info(f"📤 Sending canonical merged document {canonical.id} to SAP")
        logger.info(f"   Vendor: {canonical.vendor_rfc} | Period: {canonical.fiscal_year}-{canonical.fiscal_period:02d}")
        logger.info(f"   Net Amount: {canonical.net_amount} {canonical.currency}")
        
        endpoint = "/api/cfdi/canonical"  # New dedicated endpoint for canonical documents
        full_url = f"{self.sap_base_url}{endpoint}"
        
        try:
            async with httpx.AsyncClient(timeout=self.sap_timeout) as client:
                response = await client.post(
                    full_url,
                    content=xml_payload,
                    headers={
                        "Content-Type": "application/xml; charset=utf-8",
                        "Authorization": f"Bearer {self.sap_api_key}",
                        "X-Canonical-ID": str(canonical.id),
                        "X-Company-Code": canonical.company_code,
                        "X-Fiscal-Year": str(canonical.fiscal_year),
                        "X-Fiscal-Period": str(canonical.fiscal_period),
                        "X-Vendor-RFC": canonical.vendor_rfc,
                        "X-Document-Type": "CANONICAL_MERGED",
                        "X-CFDI-UUIDs": ','.join(canonical.cfdi_uuids) if canonical.cfdi_uuids else '',
                        "X-Net-Amount": str(canonical.net_amount),
                        "X-Currency": canonical.currency
                    }
                )
                
                logger.info(f"📥 SAP Response [{response.status_code}] for canonical {canonical.id}")
                
                if response.status_code in [200, 201, 202]:
                    try:
                        sap_data = response.json()
                    except:
                        sap_data = {"message": response.text}
                    
                    logger.info(f"✅ SAP accepted canonical document {canonical.id}")
                    
                    return {
                        "success": True,
                        "status_code": response.status_code,
                        "documentNumber": sap_data.get("documentNumber") or sap_data.get("sapDocumentNumber"),
                        "fiscalYear": sap_data.get("fiscalYear") or sap_data.get("sapFiscalYear"),
                        "message": sap_data.get("message", "Canonical document posted successfully"),
                        "sap_response": sap_data
                    }
                else:
                    error_body = response.text
                    logger.error(f"❌ SAP rejected canonical {canonical.id}: [{response.status_code}] {error_body}")
                    
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "error_message": error_body,
                        "error_code": f"SAP_CANONICAL_ERROR_{response.status_code}"
                    }
                    
        except httpx.TimeoutException:
            logger.error(f"⏱️ SAP request timeout for canonical {canonical.id}")
            return {
                "success": False,
                "error_message": "SAP request timed out",
                "error_code": "SAP_TIMEOUT"
            }
        except Exception as e:
            logger.error(f"❌ Error sending canonical {canonical.id} to SAP: {e}")
            return {
                "success": False,
                "error_message": str(e),
                "error_code": "SAP_CONNECTION_ERROR"
            }


# Singleton instance
sap_api_client = SAPAPIClient()

