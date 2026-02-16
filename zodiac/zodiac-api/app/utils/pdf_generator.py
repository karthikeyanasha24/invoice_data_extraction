"""
PDF Generator for Invoice XML
Converts XML invoice to PDF format using ReportLab
"""
import logging
from typing import Optional
import base64
from io import BytesIO
from lxml import etree
from datetime import datetime

logger = logging.getLogger("zodiac-api.pdf_generator")

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("⚠️ ReportLab not available - PDF generation will use placeholder")


async def generate_pdf_from_xml(xml_content: str, invoice_data: dict = None) -> Optional[bytes]:
    """
    Generate professional PDF invoice from XML content or extracted invoice data
    
    Args:
        xml_content: The UBL XML invoice content
        invoice_data: Optional pre-extracted invoice data (preferred for comprehensive coverage)
        
    Returns:
        PDF content as bytes, or None if generation fails
    """
    logger.info("📄 Starting PDF generation")
    if invoice_data:
        logger.info(f"📊 Using pre-extracted invoice data with {len(invoice_data)} fields")
    else:
        logger.info(f"📊 Parsing XML content ({len(xml_content)} characters)")
    
    if not REPORTLAB_AVAILABLE:
        logger.warning("⚠️ ReportLab not available - using placeholder PDF")
        return _generate_placeholder_pdf()
    
    try:
        # Use provided invoice_data if available, otherwise parse XML
        if not invoice_data:
            invoice_data = _parse_xml_invoice(xml_content)
        
        if not invoice_data:
            logger.error("❌ Failed to get invoice data")
            return _generate_placeholder_pdf()
        
        # Generate PDF using ReportLab
        pdf_bytes = _create_invoice_pdf(invoice_data)
        
        logger.info("✅ PDF generated successfully")
        logger.info(f"📊 PDF size: {len(pdf_bytes)} bytes")
        
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"❌ PDF generation error: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return _generate_placeholder_pdf()


def _parse_xml_invoice(xml_content: str) -> Optional[dict]:
    """
    Parse UBL XML invoice and extract relevant data
    
    Args:
        xml_content: The UBL XML content
        
    Returns:
        Dictionary with invoice data, or None if parsing fails
    """
    try:
        root = etree.fromstring(xml_content.encode('utf-8'))
        
        # Define namespaces
        ns = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        }
        
        # Extract invoice header
        invoice_id = root.find('.//cbc:ID', ns)
        issue_date = root.find('.//cbc:IssueDate', ns)
        due_date = root.find('.//cbc:DueDate', ns)
        currency = root.find('.//cbc:DocumentCurrencyCode', ns)
        
        # Extract supplier (seller)
        supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', ns)
        supplier_name = supplier_party.find('.//cbc:Name', ns) if supplier_party is not None else None
        supplier_street = supplier_party.find('.//cac:PostalAddress/cbc:StreetName', ns) if supplier_party is not None else None
        supplier_city = supplier_party.find('.//cac:PostalAddress/cbc:CityName', ns) if supplier_party is not None else None
        supplier_postal = supplier_party.find('.//cac:PostalAddress/cbc:PostalZone', ns) if supplier_party is not None else None
        supplier_country = supplier_party.find('.//cac:PostalAddress/cac:Country/cbc:IdentificationCode', ns) if supplier_party is not None else None
        
        # Extract customer (buyer)
        customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', ns)
        customer_name = customer_party.find('.//cbc:Name', ns) if customer_party is not None else None
        customer_street = customer_party.find('.//cac:PostalAddress/cbc:StreetName', ns) if customer_party is not None else None
        customer_city = customer_party.find('.//cac:PostalAddress/cbc:CityName', ns) if customer_party is not None else None
        customer_postal = customer_party.find('.//cac:PostalAddress/cbc:PostalZone', ns) if customer_party is not None else None
        customer_country = customer_party.find('.//cac:PostalAddress/cac:Country/cbc:IdentificationCode', ns) if customer_party is not None else None
        
        # Extract line items
        invoice_lines = []
        for line in root.findall('.//cac:InvoiceLine', ns):
            line_id = line.find('cbc:ID', ns)
            quantity = line.find('cbc:InvoicedQuantity', ns)
            item_name = line.find('.//cac:Item/cbc:Name', ns)
            price = line.find('.//cac:Price/cbc:PriceAmount', ns)
            line_total = line.find('cbc:LineExtensionAmount', ns)
            
            invoice_lines.append({
                'id': line_id.text if line_id is not None else '',
                'quantity': quantity.text if quantity is not None else '0',
                'description': item_name.text if item_name is not None else 'N/A',
                'unit_price': price.text if price is not None else '0',
                'total': line_total.text if line_total is not None else '0'
            })
        
        # Extract totals
        tax_total = root.find('.//cac:TaxTotal/cbc:TaxAmount', ns)
        line_extension = root.find('.//cac:LegalMonetaryTotal/cbc:LineExtensionAmount', ns)
        tax_exclusive = root.find('.//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount', ns)
        tax_inclusive = root.find('.//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount', ns)
        payable = root.find('.//cac:LegalMonetaryTotal/cbc:PayableAmount', ns)
        
        invoice_data = {
            'invoice_id': invoice_id.text if invoice_id is not None else 'N/A',
            'issue_date': issue_date.text if issue_date is not None else 'N/A',
            'due_date': due_date.text if due_date is not None else 'N/A',
            'currency': currency.text if currency is not None else 'USD',
            'supplier': {
                'name': supplier_name.text if supplier_name is not None else 'N/A',
                'street': supplier_street.text if supplier_street is not None else '',
                'city': supplier_city.text if supplier_city is not None else '',
                'postal': supplier_postal.text if supplier_postal is not None else '',
                'country': supplier_country.text if supplier_country is not None else ''
            },
            'customer': {
                'name': customer_name.text if customer_name is not None else 'N/A',
                'street': customer_street.text if customer_street is not None else '',
                'city': customer_city.text if customer_city is not None else '',
                'postal': customer_postal.text if customer_postal is not None else '',
                'country': customer_country.text if customer_country is not None else ''
            },
            'lines': invoice_lines,
            'totals': {
                'subtotal': line_extension.text if line_extension is not None else '0',
                'tax': tax_total.text if tax_total is not None else '0',
                'total': payable.text if payable is not None else '0'
            }
        }
        
        logger.info(f"✅ Parsed invoice data: ID={invoice_data['invoice_id']}, Lines={len(invoice_lines)}")
        return invoice_data
        
    except Exception as e:
        logger.error(f"❌ Error parsing XML invoice: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return None


def _create_invoice_pdf(invoice_data: dict) -> bytes:
    """
    Create professional invoice PDF using ReportLab
    
    Args:
        invoice_data: Parsed invoice data dictionary
        
    Returns:
        PDF content as bytes
    """
    buffer = BytesIO()
    
    # Create PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18
    )
    
    # Container for PDF elements
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a73e8'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12
    )
    
    # Title
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Invoice details table (header)
    invoice_header_data = [
        ['Invoice #:', invoice_data['invoice_id'], 'Date:', invoice_data['issue_date']],
        ['', '', 'Due Date:', invoice_data['due_date']],
    ]
    
    invoice_header_table = Table(invoice_header_data, colWidths=[1.2*inch, 2*inch, 1*inch, 1.8*inch])
    invoice_header_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#333333')),
    ]))
    elements.append(invoice_header_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # From/To section
    from_to_data = [
        [
            Paragraph('<b>From:</b><br/>' + 
                     f'{invoice_data["supplier"]["name"]}<br/>' +
                     f'{invoice_data["supplier"]["street"]}<br/>' +
                     f'{invoice_data["supplier"]["city"]}, {invoice_data["supplier"]["postal"]}<br/>' +
                     f'{invoice_data["supplier"]["country"]}', styles['Normal']),
            Paragraph('<b>Bill To:</b><br/>' +
                     f'{invoice_data["customer"]["name"]}<br/>' +
                     f'{invoice_data["customer"]["street"]}<br/>' +
                     f'{invoice_data["customer"]["city"]}, {invoice_data["customer"]["postal"]}<br/>' +
                     f'{invoice_data["customer"]["country"]}', styles['Normal'])
        ]
    ]
    
    from_to_table = Table(from_to_data, colWidths=[3*inch, 3*inch])
    from_to_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(from_to_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Line items table
    line_items_data = [['Item', 'Description', 'Qty', 'Unit Price', 'Total']]
    
    for line in invoice_data['lines']:
        line_items_data.append([
            line['id'],
            line['description'],
            line['quantity'],
            f"{float(line['unit_price']):.2f}",
            f"{float(line['total']):.2f}"
        ])
    
    line_items_table = Table(line_items_data, colWidths=[0.5*inch, 2.5*inch, 0.8*inch, 1.2*inch, 1*inch])
    line_items_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
    ]))
    elements.append(line_items_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Totals table (right-aligned)
    currency = invoice_data['currency']
    totals_data = [
        ['Subtotal:', f"{currency} {float(invoice_data['totals']['subtotal']):.2f}"],
        ['Tax:', f"{currency} {float(invoice_data['totals']['tax']):.2f}"],
        ['<b>Total Due:</b>', f"<b>{currency} {float(invoice_data['totals']['total']):.2f}</b>"],
    ]
    
    totals_table = Table(totals_data, colWidths=[1.5*inch, 1.5*inch], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#1a73e8')),
    ]))
    elements.append(totals_table)
    
    # Build PDF
    doc.build(elements)
    
    # Get PDF bytes
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes


def _generate_placeholder_pdf() -> bytes:
    """Generate a simple placeholder PDF when ReportLab is not available"""
    pdf_placeholder = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Invoice PDF Placeholder) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000315 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
408
%%EOF"""
        
    logger.info("✅ Generated placeholder PDF")
    return pdf_placeholder


def encode_to_base64(content: bytes) -> str:
    """
    Encode binary content to base64 string
    
    Args:
        content: Binary content to encode
        
    Returns:
        Base64 encoded string
    """
    try:
        encoded = base64.b64encode(content).decode('utf-8')
        logger.info(f"✅ Content encoded to base64: {len(encoded)} characters")
        return encoded
    except Exception as e:
        logger.error(f"❌ Base64 encoding error: {str(e)}")
        raise


def decode_from_base64(encoded_content: str) -> bytes:
    """
    Decode base64 string to binary content
    
    Args:
        encoded_content: Base64 encoded string
        
    Returns:
        Decoded binary content
    """
    try:
        decoded = base64.b64decode(encoded_content)
        logger.info(f"✅ Content decoded from base64: {len(decoded)} bytes")
        return decoded
    except Exception as e:
        logger.error(f"❌ Base64 decoding error: {str(e)}")
        raise
