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
SAP_PATH = "/pisf_bill_srv/billing_integration"
SAP_CLIENT = "800"
SAP_USERNAME = "andix"
SAP_PASSWORD = "init1234"

class SAPAPIClient:
    """Client for sending documents to SAP ERP"""
    
    def __init__(self):
        self.base_url = SAP_BASE_URL
        self.path = SAP_PATH
        self.sap_client = SAP_CLIENT
        self.username = SAP_USERNAME
        self.password = SAP_PASSWORD
        self.timeout = 60.0  # 60 seconds timeout
        # Build full endpoint URL with query parameter
        self.endpoint = f"{self.base_url}{self.path}?sap-client={self.sap_client}"
    
    def _get_auth_header(self) -> str:
        """Generate Basic Auth header"""
        credentials = f"{self.username}:{self.password}"
        encoded = b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
    
    async def _fetch_csrf_token(self, ds_uuid: str = None) -> Optional[str]:
        """
        Fetch CSRF token from SAP.
        Simple GET request to base endpoint with x-csrf-token: fetch header.
        
        Returns:
            CSRF token string from response headers or None if fetch fails
        """
        try:
            # Simple GET URL - no ds_uuid needed!
            get_url = f"{self.base_url}{self.path}?sap-client={self.sap_client}"
            
            logger.info(f"🔑 Fetching CSRF token from SAP...")
            logger.info(f"   GET URL: {get_url}")
            
            # Minimal headers - only what's needed
            headers = {
                "Authorization": self._get_auth_header(),
                "x-csrf-token": "fetch"  # This tells SAP to return CSRF token
            }
            
            logger.info(f"   Request headers: Authorization + x-csrf-token: fetch")
            
            # Make simple GET request
            async with httpx.AsyncClient(
                timeout=30.0,
                verify=False,  # Disable SSL verification
                follow_redirects=True
            ) as client:
                response = await client.get(get_url, headers=headers)
                
                logger.info(f"   Response status: {response.status_code}")
                
                # Check if request was successful
                if response.status_code != 200:
                    logger.error(f"❌ SAP GET request failed: {response.status_code}")
                    logger.error(f"   Response body: {response.text[:500]}")
                    return None
                
                # CSRF token is in response headers (not body!)
                csrf_token = response.headers.get("x-csrf-token")
                
                if csrf_token and csrf_token != "fetch":
                    logger.info(f"✅ CSRF token fetched: {csrf_token}")
                    return csrf_token
                else:
                    logger.warning(f"⚠️ No valid CSRF token in response")
                    logger.info(f"   x-csrf-token header value: {csrf_token}")
                    logger.info(f"   All response headers: {dict(response.headers)}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Failed to fetch CSRF token: {e}", exc_info=True)
            return None
    
    async def send_json_to_sap_with_session(
        self,
        payload: Any,
        document_type: str = "CANONICAL",
        portal_reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send JSON payload to SAP using session-based CSRF token.
        Fetches CSRF token and uses the same session (cookies) for POST.
        
        Args:
            payload: JSON payload (can be single dict or list of dicts)
            document_type: Type of document (CANONICAL, SIMPLE, etc.)
            portal_reference: Reference ID from portal
            
        Returns:
            Dict with success status and SAP response
        """
        try:
            logger.info(f"🚀 Sending {document_type} document to SAP (with session)...")
            logger.info(f"   Full Endpoint: {self.endpoint}")
            
            # Ensure payload is a list
            if isinstance(payload, dict):
                json_payload = [payload]
            elif isinstance(payload, list):
                json_payload = payload
            else:
                raise ValueError(f"Invalid payload type: {type(payload)}")
            
            # Use same client for both GET and POST to maintain session/cookies
            async with httpx.AsyncClient(
                timeout=self.timeout,
                verify=False,
                follow_redirects=True,
                http2=False
            ) as client:
                
                # Step 1: Fetch CSRF token (establishes session)
                logger.info("   Step 1: Fetching CSRF token...")
                get_url = f"{self.base_url}{self.path}?sap-client={self.sap_client}"
                
                get_headers = {
                    "Authorization": self._get_auth_header(),
                    "x-csrf-token": "fetch"
                }
                
                csrf_response = await client.get(get_url, headers=get_headers)
                
                logger.info(f"   CSRF GET status: {csrf_response.status_code}")
                
                if csrf_response.status_code != 200:
                    logger.error(f"❌ Failed to fetch CSRF token: {csrf_response.status_code}")
                    return {
                        "success": False,
                        "error": f"Failed to fetch CSRF token: {csrf_response.status_code}"
                    }
                
                # Extract CSRF token from response headers
                csrf_token = csrf_response.headers.get("x-csrf-token")
                
                if not csrf_token or csrf_token == "fetch":
                    logger.error(f"❌ No valid CSRF token in response")
                    return {
                        "success": False,
                        "error": "No CSRF token returned from SAP"
                    }
                
                logger.info(f"   CSRF token: {csrf_token}")
                logger.info(f"   Session cookies: {client.cookies}")
                
                # Step 2: Send POST with CSRF token and session cookies
                logger.info("   Step 2: Sending POST request...")
                
                post_headers = {
                    "Authorization": self._get_auth_header(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "x-csrf-token": csrf_token  # Use fetched token
                }
                
                # Cookies are automatically sent by same client!
                response = await client.post(
                    self.endpoint,
                    headers=post_headers,
                    json=json_payload
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
                    f"{self.base_url}{self.path}?sap-client={self.sap_client}&ds_uuid={ds_uuid}",
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

