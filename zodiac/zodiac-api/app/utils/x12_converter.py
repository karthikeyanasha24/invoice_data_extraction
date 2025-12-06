"""
X12 to EDIFACT Converter using EDINation API
Converts X12 format to EDIFACT format via JSON intermediate
"""
import logging
import requests
import json
from typing import Optional

logger = logging.getLogger("zodiac-api.x12_converter")

logger = logging.getLogger("zodiac-api.x12_converter")


class X12Converter:
    """Handle X12 to EDIFACT conversions using EDINation API"""
    
    def __init__(self, api_key: str):
        """
        Initialize converter with API key.
        
        Args:
            api_key (str): EDINation API subscription key
        """
        self.api_key = api_key
        self.base_url = "https://api.edination.com/v2"
        
    def x12_to_edi(self, x12_content: str) -> tuple[bool, Optional[str], str]:
        """
        Convert X12 to EDI format (X12 → JSON → X12 EDI).
        This follows the same pattern as read_write.py.
        
        Args:
            x12_content (str): Raw X12 EDI content
            
        Returns:
            tuple: (success, edi_content, message)
        """
        try:
            logger.info("🔄 Converting X12 to JSON...")
            
            # Step 1: Convert X12 to JSON using EDINation API
            url = f"{self.base_url}/x12/read"
            headers = {
                'Ocp-Apim-Subscription-Key': self.api_key,
                'Content-Type': 'application/octet-stream'
            }
            
            response = requests.post(
                url, 
                headers=headers, 
                data=x12_content.encode('utf-8'),
                timeout=30
            )
            
            if response.status_code != 200:
                error_msg = f"X12 read API failed with status {response.status_code}: {response.text}"
                logger.error(f"❌ {error_msg}")
                return False, None, error_msg
            
            json_data = response.json()
            logger.info("✅ X12 to JSON conversion successful")
            
            # Handle both single object and array responses
            if isinstance(json_data, list) and json_data:
                interchange_payload = json_data[0]
            else:
                interchange_payload = json_data
            
            logger.info("🔄 Converting JSON back to X12 EDI format...")
            
            # Step 2: Convert JSON back to X12 EDI using EDINation API
            write_url = f"{self.base_url}/x12/write"
            write_headers = {
                'Ocp-Apim-Subscription-Key': self.api_key
            }
            
            write_response = requests.post(
                write_url,
                headers=write_headers,
                json=interchange_payload,
                timeout=30
            )
            
            if write_response.status_code != 200:
                error_msg = f"X12 write API failed with status {write_response.status_code}: {write_response.text}"
                logger.error(f"❌ {error_msg}")
                return False, None, error_msg
            
            edi_content = write_response.text
            logger.info(f"✅ X12 to EDI conversion successful - EDI length: {len(edi_content)}")
            return True, edi_content, "X12 successfully converted to EDI format"
                
        except requests.Timeout:
            error_msg = "X12 conversion timeout - API took too long to respond"
            logger.error(f"⏱️ {error_msg}")
            return False, None, error_msg
            
        except Exception as e:
            error_msg = f"X12 to EDI conversion error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, None, error_msg
    
    def x12_to_json(self, x12_content: str) -> tuple[bool, Optional[dict], str]:
        """
        Convert X12 content to JSON format.
        
        Args:
            x12_content (str): Raw X12 EDI content
            
        Returns:
            tuple: (success, json_data, message)
        """
        try:
            logger.info("🔄 Converting X12 to JSON...")
            
            url = f"{self.base_url}/x12/read"
            headers = {
                'Ocp-Apim-Subscription-Key': self.api_key,
                'Content-Type': 'application/octet-stream'
            }
            
            response = requests.post(
                url, 
                headers=headers, 
                data=x12_content.encode('utf-8'),
                timeout=30
            )
            
            if response.status_code == 200:
                json_data = response.json()
                logger.info("✅ X12 to JSON conversion successful")
                
                # Handle both single object and array responses
                if isinstance(json_data, list) and json_data:
                    return True, json_data[0], "X12 to JSON conversion successful"
                else:
                    return True, json_data, "X12 to JSON conversion successful"
            else:
                error_msg = f"X12 read API failed with status {response.status_code}: {response.text}"
                logger.error(f"❌ {error_msg}")
                return False, None, error_msg
                
        except requests.Timeout:
            error_msg = "X12 conversion timeout - API took too long to respond"
            logger.error(f"⏱️ {error_msg}")
            return False, None, error_msg
            
        except Exception as e:
            error_msg = f"X12 to JSON conversion error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, None, error_msg
    
    def json_to_edifact(self, json_data: dict) -> tuple[bool, Optional[str], str]:
        """
        Convert JSON to EDIFACT format.
        
        Args:
            json_data (dict): JSON representation of EDI data
            
        Returns:
            tuple: (success, edifact_content, message)
        """
        try:
            logger.info("🔄 Converting JSON to EDIFACT...")
            
            url = f"{self.base_url}/edifact/write"
            headers = {
                'Ocp-Apim-Subscription-Key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                url,
                headers=headers,
                json=json_data,
                timeout=30
            )
            
            if response.status_code == 200:
                edifact_content = response.text
                logger.info("✅ JSON to EDIFACT conversion successful")
                return True, edifact_content, "JSON to EDIFACT conversion successful"
            else:
                error_msg = f"EDIFACT write API failed with status {response.status_code}: {response.text}"
                logger.error(f"❌ {error_msg}")
                return False, None, error_msg
                
        except requests.Timeout:
            error_msg = "EDIFACT conversion timeout - API took too long to respond"
            logger.error(f"⏱️ {error_msg}")
            return False, None, error_msg
            
        except Exception as e:
            error_msg = f"JSON to EDIFACT conversion error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, None, error_msg
    
    def x12_to_edifact(self, x12_content: str) -> tuple[bool, Optional[str], str]:
        """
        Convert X12 content directly to EDIFACT format.
        
        Args:
            x12_content (str): Raw X12 EDI content
            
        Returns:
            tuple: (success, edifact_content, message)
        """
        logger.info("🔄 Starting X12 to EDIFACT conversion...")
        
        # Step 1: Convert X12 to JSON
        success, json_data, message = self.x12_to_json(x12_content)
        if not success:
            return False, None, f"X12 to JSON failed: {message}"
        
        # Step 2: Convert JSON to EDIFACT
        success, edifact_content, message = self.json_to_edifact(json_data)
        if not success:
            return False, None, f"JSON to EDIFACT failed: {message}"
        
        logger.info("✅ X12 to EDIFACT conversion completed successfully")
        return True, edifact_content, "X12 successfully converted to EDIFACT"
    
    def validate_x12_via_api(self, x12_content: str) -> tuple[bool, str]:
        """
        Validate X12 by attempting to parse it via API.
        
        Args:
            x12_content (str): Raw X12 EDI content
            
        Returns:
            tuple: (is_valid, message)
        """
        logger.info("🔍 Validating X12 via API...")
        
        success, json_data, message = self.x12_to_json(x12_content)
        
        if success:
            logger.info("✅ X12 validation via API passed")
            return True, "X12 format is valid"
        else:
            logger.error(f"❌ X12 validation via API failed: {message}")
            return False, f"X12 validation failed: {message}"


# Convenience function for quick conversion
def convert_x12_to_edifact(x12_content: str, api_key: str) -> tuple[bool, Optional[str], str]:
    """
    Quick function to convert X12 to EDIFACT.
    
    Args:
        x12_content (str): Raw X12 EDI content
        api_key (str): EDINation API key
        
    Returns:
        tuple: (success, edifact_content, message)
    """
    converter = X12Converter(api_key)
    return converter.x12_to_edifact(x12_content)

