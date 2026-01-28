"""
SAP API Client
Sends merged documents (Simple Merge and Canonical Merge) to SAP ERP system.
"""
import logging
import httpx
import json
from typing import Dict, Any, Optional
from base64 import b64encode

logger = logging.getLogger(__name__)

# SAP Configuration (from client)
SAP_BASE_URL = "https://saperp.abor-tech.online"
SAP_ENDPOINT = f"{SAP_BASE_URL}/pisf_bill_srv/billing_integration"
SAP_CLIENT = "800"
SAP_USERNAME = "andix"
SAP_PASSWORD = "init1234"

class SAPAPIClient:
    """Client for sending documents to SAP ERP"""
    
    def __init__(self):
        self.base_url = SAP_BASE_URL
        self.endpoint = SAP_ENDPOINT
        self.sap_client = SAP_CLIENT
        self.username = SAP_USERNAME
        self.password = SAP_PASSWORD
        self.timeout = 60.0  # 60 seconds timeout
        
    def _get_auth_header(self) -> str:
        """Generate Basic Auth header"""
        credentials = f"{self.username}:{self.password}"
        encoded = b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
    
    async def send_json_to_sap(
        self,
        payload: Any,
        document_type: str = "CANONICAL",
        portal_reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send JSON payload to SAP.
        
        Args:
            payload: JSON payload (can be single dict or list of dicts)
            document_type: Type of document (CANONICAL, SIMPLE, etc.)
            portal_reference: Reference ID from portal
            
        Returns:
            Dict with success status and SAP response
        """
        try:
            logger.info(f"🚀 Sending {document_type} document to SAP...")
            logger.info(f"   Endpoint: {self.endpoint}?sap-client={self.sap_client}")
            logger.info(f"   Portal Reference: {portal_reference}")
            
            # Prepare headers
            headers = {
                "Authorization": self._get_auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # Add custom headers if needed
            if portal_reference:
                headers["X-Portal-Reference"] = portal_reference
            headers["X-Document-Type"] = document_type
            
            # Ensure payload is a list (as per client's multiplefiles format)
            if isinstance(payload, dict):
                json_payload = [payload]
            elif isinstance(payload, list):
                json_payload = payload
            else:
                raise ValueError(f"Invalid payload type: {type(payload)}")
            
            logger.info(f"   Payload structure: {len(json_payload)} document(s)")
            logger.debug(f"   Full payload: {json.dumps(json_payload, indent=2)}")
            
            # Send request to SAP
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.endpoint}?sap-client={self.sap_client}",
                    headers=headers,
                    json=json_payload  # Send as JSON
                )
                
                logger.info(f"   SAP Response Status: {response.status_code}")
                logger.info(f"   SAP Response Body: {response.text[:500]}...")  # Log first 500 chars
                
                # Check if request was successful
                if response.status_code in [200, 201, 202]:
                    # Try to parse response
                    try:
                        response_data = response.json()
                    except:
                        response_data = {"raw_response": response.text}
                    
                    logger.info(f"✅ Successfully sent to SAP")
                    
                    return {
                        "success": True,
                        "sap_status_code": response.status_code,
                        "sap_response": response_data,
                        "message": "Document sent to SAP successfully"
                    }
                else:
                    logger.error(f"❌ SAP returned error status: {response.status_code}")
                    logger.error(f"   Response: {response.text}")
                    
                    return {
                        "success": False,
                        "sap_status_code": response.status_code,
                        "sap_response": response.text,
                        "error": f"SAP returned status {response.status_code}"
                    }
                    
        except httpx.TimeoutException as e:
            logger.error(f"❌ Timeout connecting to SAP: {e}")
            return {
                "success": False,
                "error": "Timeout connecting to SAP. Please check SAP server status."
            }
        except httpx.ConnectError as e:
            logger.error(f"❌ Connection error to SAP: {e}")
            return {
                "success": False,
                "error": "Cannot connect to SAP. Please check network/firewall."
            }
        except Exception as e:
            logger.error(f"❌ Unexpected error sending to SAP: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
    
    async def get_document_from_sap(self, ds_uuid: str) -> Dict[str, Any]:
        """
        Retrieve document from SAP by UUID (GET endpoint)
        
        Args:
            ds_uuid: Document UUID to retrieve
            
        Returns:
            Dict with document data from SAP
        """
        try:
            logger.info(f"📥 Fetching document {ds_uuid} from SAP...")
            
            headers = {
                "Authorization": self._get_auth_header(),
                "Accept": "application/json"
            }
            
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.get(
                    f"{self.endpoint}?sap-client={self.sap_client}&ds_uuid={ds_uuid}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Retrieved document from SAP")
                    return {
                        "success": True,
                        "data": response.json()
                    }
                else:
                    logger.error(f"❌ SAP returned error: {response.status_code}")
                    return {
                        "success": False,
                        "error": f"SAP returned status {response.status_code}"
                    }
                    
        except Exception as e:
            logger.error(f"❌ Error getting document from SAP: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


# Singleton instance
sap_client = SAPAPIClient()

