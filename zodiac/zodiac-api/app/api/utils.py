import requests
import re
import os
from pathlib import Path
import logging

# Initialize logger
logger = logging.getLogger("zodiac-api.utils")


def extract_invoice_info(url: str):
    """
    Downloads an EDI file (X12 or EDIFACT) and extracts Invoice ID and Buyer Name.
    Handles both blob URLs and local file paths.
    Handles messy spacing and hidden characters.
    
    Supports:
    - X12 format: Looks for BIG (invoice) and N1+BY (buyer) segments
    - EDIFACT format: Looks for BGM (invoice) and NAD+BY (buyer) segments
    """
    try:
        logger.info(f"🔍 extract_invoice_info called with: {url}")
        
        # Check if it's a blob URL (Azure/cloud storage)
        if url and (url.startswith('http://') or url.startswith('https://')):
            logger.info(f"📥 Downloading from blob URL: {url}")
            response = requests.get(url)
            response.raise_for_status()
            content = response.text
            logger.info(f"✅ Downloaded {len(content)} characters from blob")
        else:
            # Local file path
            logger.info(f"📁 Reading from local file: {url}")
            
            # Try multiple path variations
            possible_paths = [
                Path(url),  # Direct path
                Path.cwd() / url,  # Relative to current directory
                Path.cwd() / 'uploads' / Path(url).name,  # In uploads folder
                Path.cwd() / 'converted' / Path(url).name,  # In converted folder
            ]
            
            file_path = None
            for path in possible_paths:
                logger.info(f"🔍 Trying path: {path}")
                if path.exists():
                    file_path = path
                    logger.info(f"✅ Found file at: {path}")
                    break
            
            if not file_path:
                logger.warning(f"⚠️ File not found in any location. Tried: {[str(p) for p in possible_paths]}")
                return {"invoice_id": None, "customer_name": None}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"✅ Read {len(content)} characters from local file")
        
        # Log a sample of the content
        logger.info(f"📄 Content preview (first 200 chars): {content[:200]}")
        
        # Detect format: X12 or EDIFACT
        is_edifact = 'UNB+' in content or 'UNH+' in content
        is_x12 = 'ISA*' in content or 'GS*' in content
        
        invoice_id = None
        buyer_name = None
        
        if is_edifact:
            logger.info(f"📋 Detected EDIFACT format")
            # EDIFACT uses ' as segment terminator and + as field separator
            # Remove extra whitespace but preserve structure
            content_clean = re.sub(r'\s+', '', content)
            segments = content_clean.split("'")
            
            logger.info(f"📊 Found {len(segments)} EDIFACT segments")
            
            for i, segment in enumerate(segments):
                parts = segment.split('+')
                
                # BGM segment contains invoice number (BGM+380+INVOICE_ID+9)
                if parts[0] == 'BGM' and len(parts) >= 3:
                    invoice_id = parts[2]
                    logger.info(f"✅ Found invoice_id in BGM segment {i}: {invoice_id}")
                
                # NAD segment with BY qualifier contains buyer name
                # NAD+BY+ID::9++BUYER_NAME+...
                elif parts[0] == 'NAD' and len(parts) >= 5 and parts[1] == 'BY':
                    buyer_name = parts[4]
                    logger.info(f"✅ Found buyer_name in NAD segment {i}: {buyer_name}")
        
        elif is_x12:
            logger.info(f"📋 Detected X12 format")
            # X12 uses ~ as segment terminator and * as field separator
            content_clean = re.sub(r'\s+', '', content)
            segments = content_clean.split('~')
            
            logger.info(f"📊 Found {len(segments)} X12 segments")
            
            for i, segment in enumerate(segments):
                parts = segment.split('*')
                
                # BIG segment contains invoice number
                if parts[0] == 'BIG' and len(parts) >= 3:
                    invoice_id = parts[2]
                    logger.info(f"✅ Found invoice_id in BIG segment {i}: {invoice_id}")
                
                # N1 segment with BY qualifier contains buyer name
                elif parts[0] == 'N1' and len(parts) >= 3 and parts[1] == 'BY':
                    buyer_name = parts[2]
                    logger.info(f"✅ Found buyer_name in N1 segment {i}: {buyer_name}")
        
        else:
            logger.warning(f"⚠️ Could not detect EDI format (neither X12 nor EDIFACT)")
        
        result = {
            "invoice_id": invoice_id,
            "customer_name": buyer_name
        }
        
        logger.info(f"📊 Final extraction result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error extracting invoice info from {url}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return {
            "invoice_id": None,
            "customer_name": None
        }
