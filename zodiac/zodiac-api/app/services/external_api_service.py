import uuid
import httpx
import xml.etree.ElementTree as ET
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("zodiac-api.external_api_service")
# Third party API token management
_third_party_token: Optional[str] = None
_third_party_token_expiry: Optional[datetime] = None

async def get_third_party_token() -> Optional[str]:
    """Get or refresh third party API token
    
    Returns:
        Bearer token string or None if failed
    """
    global _third_party_token, _third_party_token_expiry
    
    # Check if we have a valid token
    if _third_party_token and _third_party_token_expiry:
        # Add 5 minute buffer before expiry
        from datetime import timedelta
        if datetime.now() < (_third_party_token_expiry - timedelta(minutes=5)):
            logger.info("✅ Using cached third party token")
            return _third_party_token
    
    # Need to get new token
    login_url = "https://dbnasender.cfdise.com/PeppolSoftDBNA/auth/login"
    
    try:
        logger.info("🔑 Requesting new third party API token...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                login_url,
                json={
                    "user": "peppolsoft",
                    "password": "t3st2025"
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                # Try different possible token field names
                _third_party_token = token_data.get("accessToken") or token_data.get("token") or token_data.get("access_token")
                
                if _third_party_token:
                    # Token is valid for ~1 year based on the provided token
                    # Set expiry to 30 days to be safe
                    from datetime import timedelta
                    _third_party_token_expiry = datetime.now() + timedelta(days=30)
                    logger.info("✅ Successfully obtained third party API token")
                    return _third_party_token
                else:
                    logger.error(f"❌ Token not found in response: {token_data}")
                    return None
            else:
                logger.error(f"❌ Failed to get token. Status: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"❌ Error getting third party token: {str(e)}")
        return None



async def send_to_third_party_endpoint(edi_content: str, tracking_id: uuid.UUID) -> tuple[bool, str, dict]:
    """Send EDI content to third party endpoint
    
    Args:
        edi_content: The EDI/X12 content to send
        tracking_id: Tracking ID for logging
        
    Returns:
        Tuple of (success, message, response_data)
    """
    logger.info(f"🌐 ===== SENDING TO THIRD PARTY ENDPOINT =====")
    logger.info(f"🆔 Tracking ID: {tracking_id}")
    
    endpoint_url = "https://dbnasender.cfdise.com/PeppolSoftDBNA/v1/xml/generateDocument"
    
    # Get authentication token
    token = await get_third_party_token()
    if not token:
        error_msg = "Failed to obtain third party API token"
        logger.error(f"❌ {error_msg}")
        return False, error_msg, {"error": "authentication_failed"}
    
    try:
        logger.info(f"📤 Sending EDI content to: {endpoint_url}")
        logger.info(f"📊 Content length: {len(edi_content)} bytes")
        logger.info(f"🔑 Using Bearer token authentication")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                endpoint_url,
                content=edi_content,
                headers={
                    "Content-Type": "application/xml",
                    "Authorization": f"Bearer {token}"
                }
            )
            
            logger.info(f"📥 Response status: {response.status_code}")
            logger.info(f"📥 Response headers: {dict(response.headers)}")
            
            # Parse XML response for code 201 or 200
            if response.status_code in [200, 201]:
                try:
                    # Parse XML response
                    response_xml = ET.fromstring(response.content)
                    code_elem = response_xml.find('code')
                    message_elem = response_xml.find('message')
                    xml_elem = response_xml.find('xml')
                    
                    code = code_elem.text if code_elem is not None else None
                    message = message_elem.text if message_elem is not None else None
                    xml_data = xml_elem.text if xml_elem is not None else None
                    
                    response_data = {
                        "code": code,
                        "message": message,
                        "xml": xml_data
                    }
                    
                    logger.info(f"📥 Parsed response - Code: {code}, Message: {message}")
                    
                    # Check if code is "100" for success
                    if code == "100":
                        logger.info(f"✅ Successfully sent to third party endpoint - Code 100")
                        return True, message or "Document sent successfully", response_data
                    else:
                        error_msg = f"Third party endpoint returned code {code}: {message}"
                        logger.error(f"❌ {error_msg}")
                        return False, message or error_msg, response_data
                        
                except ET.ParseError as e:
                    # Fallback if XML parsing fails
                    logger.warning(f"⚠️ Failed to parse XML response: {e}")
                    response_data = {"text": response.text}
                    logger.info(f"📥 Response text: {response.text[:500]}")
                    return True, "Successfully sent to 3rd party endpoint", response_data
                except Exception as e:
                    logger.warning(f"⚠️ Error parsing response: {e}")
                    response_data = {"text": response.text}
                    return True, "Successfully sent to 3rd party endpoint", response_data
            else:
                # Handle non-success status codes
                try:
                    response_data = response.json()
                except:
                    response_data = {"text": response.text}
                    
                error_msg = f"Third party endpoint returned status {response.status_code}, response body: {response.text}"
                logger.error(f"❌ {error_msg}")
                return False, error_msg, response_data
                
    except httpx.TimeoutException:
        error_msg = "Third party endpoint request timed out after 30 seconds"
        logger.error(f"❌ {error_msg}")
        return False, error_msg, {"error": "timeout"}
    except httpx.RequestError as e:
        error_msg = f"Network error connecting to third party endpoint: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg, {"error": str(e)}
    except Exception as e:
        error_msg = f"Unexpected error sending to third party endpoint: {str(e)}"
        logger.error(f"❌ {error_msg}")
        logger.error(f"🔍 Error type: {type(e).__name__}")
        return False, error_msg, {"error": str(e)}

