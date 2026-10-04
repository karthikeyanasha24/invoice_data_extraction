"""
EDINation API Integration for X12 Validation
Uses EDINation API to validate X12 EDI content
"""
import logging
import requests
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger("zodiac-api.edination")

# EDINation API Configuration
EDINATION_API_KEY = "3ecf6b1c5cf34bd797a5f4c57951a1cf"
EDINATION_BASE_URL = "https://api.edination.com/v1"


async def validate_x12_with_edination(x12_content: str) -> Tuple[bool, str, List[Dict]]:
    """
    Validate X12 content using EDINation API
    
    Args:
        x12_content: The X12 EDI content to validate
        
    Returns:
        Tuple of (is_valid, message, errors)
        - is_valid: Boolean indicating if validation passed
        - message: Success or error message
        - errors: List of validation error dictionaries
    """
    logger.info("🔍 Starting EDINation X12 validation")
    
    try:
        # EDINation validation endpoint
        validation_url = f"{EDINATION_BASE_URL}/x12/validate"
        
        headers = {
            "Authorization": f"Bearer {EDINATION_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "content": x12_content,
            "syntax": "X12",
            "version": "004010"  # X12 version 4010
        }
        
        logger.info(f"📤 Sending X12 content to EDINation API")
        logger.info(f"🌐 URL: {validation_url}")
        logger.info(f"📊 Content length: {len(x12_content)} characters")
        
        response = requests.post(
            validation_url,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        logger.info(f"📥 EDINation API response: Status {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            
            # Check validation result
            if result.get("valid", False):
                logger.info("✅ EDINation validation passed")
                return True, "X12 validation passed", []
            else:
                # Extract validation errors
                errors = result.get("errors", [])
                error_messages = [err.get("message", "Unknown error") for err in errors]
                error_summary = "; ".join(error_messages[:3])  # First 3 errors
                
                logger.warning(f"⚠️ EDINation validation failed: {error_summary}")
                return False, f"X12 validation failed: {error_summary}", errors
                
        elif response.status_code == 401:
            logger.error("❌ EDINation API authentication failed")
            return False, "EDINation API authentication failed - invalid API key", []
            
        elif response.status_code == 400:
            error_msg = response.json().get("message", "Bad request")
            logger.error(f"❌ EDINation API bad request: {error_msg}")
            return False, f"X12 validation failed: {error_msg}", []
            
        else:
            logger.error(f"❌ EDINation API error: Status {response.status_code}")
            return False, f"EDINation API error: {response.status_code}", []
            
    except requests.exceptions.Timeout:
        logger.error("❌ EDINation API timeout")
        return False, "EDINation API timeout - validation took too long", []
        
    except requests.exceptions.ConnectionError:
        logger.error("❌ EDINation API connection error")
        return False, "EDINation API connection error - unable to reach service", []
        
    except Exception as e:
        logger.error(f"❌ EDINation validation error: {str(e)}")
        return False, f"EDINation validation error: {str(e)}", []


async def validate_x12_basic(x12_content: str) -> Tuple[bool, str, List[Dict]]:
    """
    Basic X12 format validation (fallback if EDINation is unavailable)
    Checks basic X12 structure and segments
    
    Args:
        x12_content: The X12 EDI content to validate
        
    Returns:
        Tuple of (is_valid, message, errors)
    """
    logger.info("🔍 Starting basic X12 validation")
    
    errors = []
    
    try:
        # Check if content is not empty
        if not x12_content or len(x12_content.strip()) == 0:
            errors.append({
                "error_code": "EMPTY_CONTENT",
                "message": "X12 content is empty",
                "severity": "ERROR"
            })
            return False, "X12 content is empty", errors
        
        # Check for ISA segment (interchange header)
        if not x12_content.startswith("ISA"):
            errors.append({
                "error_code": "MISSING_ISA",
                "message": "Missing ISA (Interchange Header) segment",
                "severity": "ERROR"
            })
        
        # Check for IEA segment (interchange trailer)
        if "IEA" not in x12_content:
            errors.append({
                "error_code": "MISSING_IEA",
                "message": "Missing IEA (Interchange Trailer) segment",
                "severity": "ERROR"
            })
        
        # Check for segment terminators
        if "~" not in x12_content:
            errors.append({
                "error_code": "MISSING_TERMINATORS",
                "message": "Missing segment terminators (~)",
                "severity": "ERROR"
            })
        
        # Check minimum content length
        if len(x12_content) < 100:
            errors.append({
                "error_code": "CONTENT_TOO_SHORT",
                "message": "X12 content appears too short to be valid",
                "severity": "WARNING"
            })
        
        if errors:
            error_summary = "; ".join([e["message"] for e in errors if e["severity"] == "ERROR"])
            if error_summary:
                logger.warning(f"⚠️ Basic X12 validation failed: {error_summary}")
                return False, f"X12 validation failed: {error_summary}", errors
        
        logger.info("✅ Basic X12 validation passed")
        return True, "X12 basic validation passed", []
        
    except Exception as e:
        logger.error(f"❌ Basic X12 validation error: {str(e)}")
        return False, f"X12 validation error: {str(e)}", []

