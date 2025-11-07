import requests
import re


def extract_invoice_info(url: str):
    """
    Downloads an EDI X12 file and extracts Invoice ID and Buyer Name.
    Handles messy spacing and hidden characters.
    """
    response = requests.get(url)
    response.raise_for_status()
    content = response.text

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