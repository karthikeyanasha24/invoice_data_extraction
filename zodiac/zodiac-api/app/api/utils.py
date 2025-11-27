import requests
import re
import os
from pathlib import Path


def extract_invoice_info(url: str):
    """
    Downloads an EDI X12 file and extracts Invoice ID and Buyer Name.
    Handles both blob URLs and local file paths.
    Handles messy spacing and hidden characters.
    """
    try:
        # Check if it's a local file path
        if url and (url.startswith('/') or url.startswith('converted/') or url.startswith('uploads/')):
            # Local file path
            file_path = Path(url)
            if not file_path.exists():
                # Try relative to current directory
                file_path = Path.cwd() / url
            if not file_path.exists():
                print(f"⚠️ Local file not found: {url}")
                return {"invoice_id": None, "customer_name": None}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            # Blob URL or remote URL
            response = requests.get(url)
            response.raise_for_status()
            content = response.text

        # Remove all whitespace for easier parsing
        content = re.sub(r'\s+', '', content)

        segments = content.split('~')

        invoice_id = None
        buyer_name = None

        for segment in segments:
            parts = segment.split('*')

            if parts[0] == 'BIG' and len(parts) >= 3:
                invoice_id = parts[2]

            # Find the N1 segment where the identifier code = 'BY' (Buyer)
            elif parts[0] == 'N1' and len(parts) >= 3 and parts[1] == 'BY':
                buyer_name = parts[2]

        return {
            "invoice_id": invoice_id,
            "customer_name": buyer_name
        }
    except Exception as e:
        print(f"⚠️ Error extracting invoice info from {url}: {e}")
        return {
            "invoice_id": None,
            "customer_name": None
        }