"""
X12 EDI File Validator using Selenium
Validates X12 files by uploading to EDINation website
"""
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

logger = logging.getLogger("zodiac-api.x12_validator")


def validate_x12_content(x12_content: str) -> tuple[bool, str, list[dict]]:
    """
    Validate X12 EDI content using basic structural checks.
    
    Note: Full Selenium validation is disabled due to reliability issues.
    This performs basic X12 format validation instead.
    
    Args:
        x12_content (str): The contents of the X12 file to be validated
        
    Returns:
        tuple: (is_valid, message, errors_list)
            - is_valid (bool): True if valid, False if invalid
            - message (str): Success or error message
            - errors_list (list): List of error dictionaries with details
    """
    try:
        logger.info("🔍 Performing basic X12 format validation...")
        
        # Basic X12 validation checks
        errors_list = []
        
        # 1. Check if content is not empty
        if not x12_content or not x12_content.strip():
            errors_list.append({
                "error_number": 1,
                "error_message": "X12 file is empty",
                "severity": "ERROR"
            })
            return False, "X12 file is empty", errors_list
        
        # 2. Check for ISA segment (required starting segment)
        if not x12_content.startswith("ISA"):
            errors_list.append({
                "error_number": 1,
                "error_message": "X12 file must start with ISA segment",
                "severity": "ERROR"
            })
        
        # 3. Check for IEA segment (required ending segment)
        if "IEA" not in x12_content:
            errors_list.append({
                "error_number": len(errors_list) + 1,
                "error_message": "X12 file must contain IEA segment",
                "severity": "ERROR"
            })
        
        # 4. Check for segment terminators (~ or other common terminators)
        if '~' not in x12_content and '\n' not in x12_content:
            errors_list.append({
                "error_number": len(errors_list) + 1,
                "error_message": "X12 file must contain segment terminators",
                "severity": "WARNING"
            })
        
        # 5. Check minimum length (ISA segment alone is 106 characters)
        if len(x12_content) < 100:
            errors_list.append({
                "error_number": len(errors_list) + 1,
                "error_message": "X12 file appears to be too short",
                "severity": "WARNING"
            })
        
        # If there are errors, return them
        if errors_list:
            error_summary = "\n".join([e["error_message"] for e in errors_list])
            logger.warning(f"❌ X12 validation failed: {error_summary}")
            return False, f"X12 validation failed with {len(errors_list)} issues", errors_list
        
        # All checks passed
        logger.info("✅ X12 basic validation passed")
        return True, "X12 validation passed successfully", []
        
    except Exception as e:
        logger.error(f"❌ Error during X12 validation: {e}")
        return False, f"Validation error: {str(e)}", []


def validate_x12_file(file_path: str) -> tuple[bool, str, list[dict]]:
    """
    Validate X12 EDI file by reading from disk.
    
    Args:
        file_path (str): Path to the X12 file
        
    Returns:
        tuple: (is_valid, message, errors_list)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            x12_content = file.read()
        
        return validate_x12_content(x12_content)
        
    except FileNotFoundError:
        logger.error(f"❌ File not found: {file_path}")
        return False, f"File not found: {file_path}", []
        
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        return False, f"Error reading file: {str(e)}", []

