"""
PDF Generator for Invoice XML
Converts XML invoice to PDF format using ReportLab with comprehensive data display
"""
import logging
from typing import Optional, Dict, List, Any
import base64
from io import BytesIO
from lxml import etree
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger("zodiac-api.pdf_generator")

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("⚠️ ReportLab not available - PDF generation will use placeholder")


async def generate_pdf_from_xml(xml_content: str, invoice_data: dict = None) -> Optional[bytes]:
    """
    Generate professional comprehensive PDF invoice from extracted invoice data
    
    Args:
        xml_content: The UBL XML invoice content (used as fallback)
        invoice_data: Pre-extracted invoice data from validation (preferred - contains ALL fields)
        
    Returns:
        PDF content as bytes, or None if generation fails
    """
    logger.info("📄 Starting comprehensive PDF generation")
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
        
        # Generate comprehensive PDF using ReportLab
        pdf_bytes = _create_comprehensive_invoice_pdf(invoice_data)
        
        logger.info("✅ Comprehensive PDF generated successfully")
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
    (Fallback if invoice_data not provided)
    """
    try:
        root = etree.fromstring(xml_content.encode('utf-8'))
        
        # Define namespaces
        ns = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        }
        
        # Extract basic data (simplified version)
        invoice_id = root.find('.//cbc:ID', ns)
        issue_date = root.find('.//cbc:IssueDate', ns)
        due_date = root.find('.//cbc:DueDate', ns)
        currency = root.find('.//cbc:DocumentCurrencyCode', ns)
        
        # Extract supplier
        supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', ns)
        supplier_name = supplier_party.find('.//cbc:Name', ns) if supplier_party is not None else None
        
        # Extract customer
        customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', ns)
        customer_name = customer_party.find('.//cbc:Name', ns) if customer_party is not None else None
        
        # Extract line items
        lines = []
        for line in root.findall('.//cac:InvoiceLine', ns):
            line_id = line.find('cbc:ID', ns)
            quantity = line.find('cbc:InvoicedQuantity', ns)
            unit_code = quantity.get('unitCode') if quantity is not None else ''
            item_name = line.find('.//cac:Item/cbc:Name', ns)
            item_desc = line.find('.//cac:Item/cbc:Description', ns)
            seller_item = line.find('.//cac:Item/cac:SellersItemIdentification/cbc:ID', ns)
            standard_item = line.find('.//cac:Item/cac:StandardItemIdentification/cbc:ID', ns)
            price = line.find('.//cac:Price/cbc:PriceAmount', ns)
            line_total = line.find('cbc:LineExtensionAmount', ns)
            
            lines.append({
                'id': line_id.text if line_id is not None else '',
                'quantity': quantity.text if quantity is not None else '0',
                'unit_code': unit_code,
                'item_name': item_name.text if item_name is not None else '',
                'item_description': item_desc.text if item_desc is not None else '',
                'seller_item_id': seller_item.text if seller_item is not None else '',
                'standard_item_id': standard_item.text if standard_item is not None else '',
                'price': price.text if price is not None else '0',
                'line_amount': line_total.text if line_total is not None else '0'
            })
        
        # Extract totals
        payable = root.find('.//cac:LegalMonetaryTotal/cbc:PayableAmount', ns)
        tax_total = root.find('.//cac:TaxTotal/cbc:TaxAmount', ns)
        
        # Extract order reference
        order_ref = root.find('.//cac:OrderReference/cbc:ID', ns)
        
        invoice_data = {
            'invoice_number': invoice_id.text if invoice_id is not None else 'N/A',
            'issue_date': issue_date.text if issue_date is not None else 'N/A',
            'due_date': due_date.text if due_date is not None else '',
            'currency': currency.text if currency is not None else 'USD',
            'order_reference': order_ref.text if order_ref is not None else '',
            'supplier_name': supplier_name.text if supplier_name is not None else 'N/A',
            'customer_name': customer_name.text if customer_name is not None else 'N/A',
            'line_items': lines,
            'total_amount': payable.text if payable is not None else '0',
            'tax_amount': tax_total.text if tax_total is not None else '0',
            'status': 'success'  # Assume success if parsing from XML directly
        }
        
        logger.info(f"✅ Parsed basic invoice data from XML")
        return invoice_data
        
    except Exception as e:
        logger.error(f"❌ Error parsing XML invoice: {str(e)}")
        return None


def _create_comprehensive_invoice_pdf(invoice_data: dict) -> bytes:
    """
    Create comprehensive professional invoice PDF with ALL available data
    
    Args:
        invoice_data: Complete invoice data from validation service
        
    Returns:
        PDF content as bytes
    """
    buffer = BytesIO()
    
    # Create PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=30
    )
    
    # Container for PDF elements
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#1a73e8'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    section_heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1a73e8'),
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold'
    )
    
    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666'),
        fontName='Helvetica-Bold'
    )
    
    value_style = ParagraphStyle(
        'Value',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#333333'),
        fontName='Helvetica'
    )
    
    # ============ HEADER ============
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Spacer(1, 0.1*inch))
    
    # Add invoice status badge if failed validation
    status = invoice_data.get('status', 'unknown')
    if status == 'failed':
        status_text = '<para align="center" backColor="#fff3cd" borderColor="#ffc107" borderPadding="5" borderWidth="1">' \
                     '<font color="#856404" size="10"><b>⚠ VALIDATION ISSUES PRESENT</b></font></para>'
        elements.append(Paragraph(status_text, styles['Normal']))
        elements.append(Spacer(1, 0.1*inch))
    
    # ============ BASIC INVOICE INFO ============
    # Get currency (try both field names)
    currency = invoice_data.get('currency') or invoice_data.get('currency_code', 'N/A')
    
    # Get PO number (try multiple field names)
    po_number = (invoice_data.get('order_reference') or 
                 invoice_data.get('purchase_order_number') or 
                 invoice_data.get('purchase_order', 'N/A'))
    
    invoice_info_data = [
        [Paragraph('<b>Invoice Number:</b>', label_style), 
         Paragraph(str(invoice_data.get('invoice_number', 'N/A')), value_style),
         Paragraph('<b>Issue Date:</b>', label_style),
         Paragraph(str(invoice_data.get('issue_date', 'N/A')), value_style)],
        [Paragraph('<b>Customer ID:</b>', label_style),
         Paragraph(str(invoice_data.get('customer_id', 'N/A')), value_style),
         Paragraph('<b>Due Date:</b>', label_style),
         Paragraph(str(invoice_data.get('due_date', 'N/A')), value_style)],
        [Paragraph('<b>Currency:</b>', label_style),
         Paragraph(str(currency), value_style),
         Paragraph('<b>PO Number:</b>', label_style),
         Paragraph(str(po_number), value_style)],
    ]
    
    info_table = Table(invoice_info_data, colWidths=[1.2*inch, 1.8*inch, 1*inch, 2*inch])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # ============ SUPPLIER & CUSTOMER INFO ============
    supplier_text = f"<b>{invoice_data.get('supplier_name', 'N/A')}</b><br/>"
    if invoice_data.get('supplier_street'):
        supplier_text += f"{invoice_data.get('supplier_street', '')}<br/>"
    if invoice_data.get('supplier_additional_street'):
        supplier_text += f"{invoice_data.get('supplier_additional_street', '')}<br/>"
    supplier_text += f"{invoice_data.get('supplier_city', '')}, {invoice_data.get('supplier_postal_code', '')}<br/>"
    supplier_text += f"{invoice_data.get('supplier_country', '')}"
    if invoice_data.get('supplier_tax_id'):
        supplier_text += f"<br/>Tax ID: {invoice_data.get('supplier_tax_id', '')}"
    
    customer_text = f"<b>{invoice_data.get('customer_name', 'N/A')}</b><br/>"
    if invoice_data.get('customer_street'):
        customer_text += f"{invoice_data.get('customer_street', '')}<br/>"
    if invoice_data.get('customer_additional_street'):
        customer_text += f"{invoice_data.get('customer_additional_street', '')}<br/>"
    customer_text += f"{invoice_data.get('customer_city', '')}, {invoice_data.get('customer_postal_code', '')}<br/>"
    customer_text += f"{invoice_data.get('customer_country', '')}"
    if invoice_data.get('customer_tax_id'):
        customer_text += f"<br/>Tax ID: {invoice_data.get('customer_tax_id', '')}"
    
    party_data = [
        [Paragraph('<font size="11"><b>FROM (SUPPLIER)</b></font>', label_style),
         Paragraph('<font size="11"><b>BILL TO (CUSTOMER)</b></font>', label_style)],
        [Paragraph(supplier_text, value_style),
         Paragraph(customer_text, value_style)]
    ]
    
    party_table = Table(party_data, colWidths=[3.25*inch, 3.25*inch])
    party_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.white),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#dee2e6')),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # ============ LINE ITEMS ============
    elements.append(Paragraph("LINE ITEMS", section_heading_style))
    
    line_items = invoice_data.get('line_items', [])
    
    if line_items:
        # Table header
        line_data = [[
            Paragraph('<b>Line</b>', label_style),
            Paragraph('<b>Description</b>', label_style),
            Paragraph('<b>Product Code</b>', label_style),
            Paragraph('<b>Qty</b>', label_style),
            Paragraph('<b>Unit</b>', label_style),
            Paragraph('<b>Unit Price</b>', label_style),
            Paragraph('<b>Line Total</b>', label_style)
        ]]
        
        # Add line items
        for line in line_items:
            # Get line number (could be 'id' or 'line_number')
            line_num = line.get('id') or line.get('line_number', '')
            
            # Get description (try multiple fields)
            description = line.get('item_description') or line.get('item_name') or line.get('description', 'N/A')
            
            # Get product code (try multiple ID fields)
            product_code = (line.get('seller_item_id') or 
                          line.get('standard_item_id') or 
                          line.get('buyer_item_id') or 
                          line.get('product_code', 'N/A'))
            
            # Get price (could be 'price' or 'unit_price')
            unit_price = line.get('price') or line.get('unit_price', 0)
            
            # Get line total (could be 'line_amount' or 'line_total')
            line_total = line.get('line_amount') or line.get('line_total', 0)
            
            line_data.append([
                Paragraph(str(line_num), value_style),
                Paragraph(str(description)[:80], value_style),
                Paragraph(str(product_code)[:20], value_style),
                Paragraph(str(line.get('quantity', '0')), value_style),
                Paragraph(str(line.get('unit_code', ''))[:10], value_style),
                Paragraph(f"{_format_amount(unit_price)}", value_style),
                Paragraph(f"{_format_amount(line_total)}", value_style)
            ])
        
        line_table = Table(line_data, colWidths=[0.4*inch, 2.2*inch, 1*inch, 0.6*inch, 0.5*inch, 0.9*inch, 0.9*inch])
        line_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # Qty
            ('ALIGN', (4, 1), (4, -1), 'CENTER'),  # Unit
            ('ALIGN', (5, 1), (-1, -1), 'RIGHT'),  # Amounts
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('TOPPADDING', (0, 1), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(line_table)
    else:
        elements.append(Paragraph("<i>No line items available</i>", value_style))
    
    elements.append(Spacer(1, 0.25*inch))
    
    # ============ ALLOWANCES/CHARGES ============
    allowances = invoice_data.get('allowances', [])
    charges = invoice_data.get('charges', [])
    
    if allowances or charges:
        elements.append(Paragraph("ALLOWANCES & CHARGES", section_heading_style))
        
        if allowances:
            allowance_data = [['Type', 'Reason', 'Amount']]
            for allowance in allowances:
                allowance_data.append([
                    'Allowance',
                    str(allowance.get('reason', 'N/A')),
                    f"-{_format_amount(allowance.get('amount', 0))}"
                ])
            
            allowance_table = Table(allowance_data, colWidths=[1.5*inch, 3*inch, 2*inch])
            allowance_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            elements.append(allowance_table)
        
        if charges:
            charge_data = [['Type', 'Reason', 'Amount']]
            for charge in charges:
                charge_data.append([
                    'Charge',
                    str(charge.get('reason', 'N/A')),
                    f"+{_format_amount(charge.get('amount', 0))}"
                ])
            
            charge_table = Table(charge_data, colWidths=[1.5*inch, 3*inch, 2*inch])
            charge_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            elements.append(charge_table)
        
        elements.append(Spacer(1, 0.15*inch))
    
    # ============ TOTALS ============
    # Get currency for totals section
    currency = invoice_data.get('currency') or invoice_data.get('currency_code', '')
    
    totals_data = []
    
    # Subtotal
    if invoice_data.get('subtotal'):
        totals_data.append(['Subtotal:', f"{currency} {_format_amount(invoice_data.get('subtotal', 0))}"])
    
    # Allowance total
    if invoice_data.get('allowance_total'):
        totals_data.append(['Total Allowances:', f"- {currency} {_format_amount(invoice_data.get('allowance_total', 0))}"])
    
    # Charge total
    if invoice_data.get('charge_total'):
        totals_data.append(['Total Charges:', f"+ {currency} {_format_amount(invoice_data.get('charge_total', 0))}"])
    
    # Tax exclusive amount
    if invoice_data.get('tax_exclusive_amount'):
        totals_data.append(['Tax Exclusive Amount:', f"{currency} {_format_amount(invoice_data.get('tax_exclusive_amount', 0))}"])
    
    # Tax amount
    tax_amount = invoice_data.get('tax_amount', 0)
    if tax_amount:
        totals_data.append(['Tax Amount:', f"{currency} {_format_amount(tax_amount)}"])
    
    # Prepaid amount
    if invoice_data.get('prepaid_amount'):
        totals_data.append(['Prepaid Amount:', f"- {currency} {_format_amount(invoice_data.get('prepaid_amount', 0))}"])
    
    # Total amount (payable)
    total_amount = invoice_data.get('total_amount', 0)
    totals_data.append(['<b>TOTAL AMOUNT DUE:</b>', f"<b>{currency} {_format_amount(total_amount)}</b>"])
    
    totals_table = Table(totals_data, colWidths=[2.5*inch, 2*inch], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -2), 10),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#1a73e8')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e3f2fd')),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # ============ PAYMENT INFORMATION ============
    if invoice_data.get('payment_terms') or invoice_data.get('payment_means'):
        elements.append(Paragraph("PAYMENT INFORMATION", section_heading_style))
        
        payment_info_data = []
        
        if invoice_data.get('payment_terms'):
            payment_info_data.append([
                Paragraph('<b>Payment Terms:</b>', label_style),
                Paragraph(str(invoice_data.get('payment_terms', '')), value_style)
            ])
        
        if invoice_data.get('payment_means'):
            payment_info_data.append([
                Paragraph('<b>Payment Means:</b>', label_style),
                Paragraph(str(invoice_data.get('payment_means', '')), value_style)
            ])
        
        if invoice_data.get('payment_account'):
            payment_info_data.append([
                Paragraph('<b>Payment Account:</b>', label_style),
                Paragraph(str(invoice_data.get('payment_account', '')), value_style)
            ])
        
        if payment_info_data:
            payment_table = Table(payment_info_data, colWidths=[1.5*inch, 5*inch])
            payment_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ]))
            elements.append(payment_table)
            elements.append(Spacer(1, 0.15*inch))
    
    # ============ ADDITIONAL INFORMATION ============
    additional_fields = []
    
    if invoice_data.get('notes'):
        additional_fields.append(('Notes', invoice_data.get('notes')))
    
    if invoice_data.get('delivery_date'):
        additional_fields.append(('Delivery Date', invoice_data.get('delivery_date')))
    
    if invoice_data.get('contract_reference'):
        additional_fields.append(('Contract Reference', invoice_data.get('contract_reference')))
    
    if invoice_data.get('project_reference'):
        additional_fields.append(('Project Reference', invoice_data.get('project_reference')))
    
    if additional_fields:
        elements.append(Paragraph("ADDITIONAL INFORMATION", section_heading_style))
        
        additional_data = []
        for field_name, field_value in additional_fields:
            additional_data.append([
                Paragraph(f'<b>{field_name}:</b>', label_style),
                Paragraph(str(field_value), value_style)
            ])
        
        additional_table = Table(additional_data, colWidths=[1.5*inch, 5*inch])
        additional_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ]))
        elements.append(additional_table)
    
    # ============ FOOTER ============
    elements.append(Spacer(1, 0.3*inch))
    footer_text = f"<para align='center'><font size='8' color='#666666'>" \
                 f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | " \
                 f"Invoice #{invoice_data.get('invoice_number', 'N/A')}" \
                 f"</font></para>"
    elements.append(Paragraph(footer_text, styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    
    # Get PDF bytes
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    logger.info(f"✅ Generated comprehensive PDF with {len(elements)} elements")
    return pdf_bytes


def _format_amount(value) -> str:
    """Format monetary amount with 2 decimal places"""
    try:
        if value is None:
            return "0.00"
        if isinstance(value, str):
            value = float(value)
        return f"{float(value):.2f}"
    except:
        return "0.00"


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
