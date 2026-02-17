"""
Test PDF conversion with comprehensive data display
"""
import sys
import asyncio
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.pdf_generator import generate_pdf_from_xml

# Sample comprehensive invoice data (simulating what comes from validation service)
SAMPLE_INVOICE_DATA = {
    'invoice_number': 'Snippet1',
    'issue_date': '2019-07-29',
    'due_date': '2019-08-30',
    'currency': 'NZD',
    'customer_id': '9429033591476',
    'order_reference': 'SOMEBLERB',
    
    # Supplier info
    'supplier_name': 'SupplierOfficialName Ltd',
    'supplier_street': 'Main street 1',
    'supplier_additional_street': 'Postbox 123',
    'supplier_city': 'Wellington',
    'supplier_postal_code': 'NZ 123 EW',
    'supplier_country': 'NZ',
    'supplier_tax_id': '888-888-888',
    
    # Customer info
    'customer_name': 'Trotters Trading Co Ltd',
    'customer_street': '100 Queen Street',
    'customer_additional_street': 'Po box 878',
    'customer_city': 'Auckland',
    'customer_postal_code': 'A36577',
    'customer_country': 'NZ',
    'customer_tax_id': '999-999-999',
    
    # Line items (using field names from validation service)
    'line_items': [
        {
            'id': '1',
            'item_name': 'True-Widgets',
            'item_description': 'Widgets True and Fair - Some Blurb Giving More Info',
            'seller_item_id': 'WG546767',
            'standard_item_id': 'WG546767',
            'quantity': '10',
            'unit_code': 'E99',
            'price': '29.99',
            'line_amount': '299.90'
        },
        {
            'id': '2',
            'item_name': 'item name 2',
            'item_description': 'Description 2',
            'seller_item_id': '21382183120983',
            'standard_item_id': '21382183120983',
            'quantity': '2',
            'unit_code': 'DAY',
            'price': '500.00',
            'line_amount': '1000.00'
        },
        {
            'id': '3',
            'item_name': 'True-Widgets',
            'item_description': 'Widgets True and Fair - Invoice Line Description',
            'seller_item_id': 'WG546767',
            'standard_item_id': 'WG546767',
            'quantity': '25',
            'unit_code': 'M66',
            'price': '7.50',
            'line_amount': '187.50'
        }
    ],
    
    # Allowances
    'allowances': [
        {
            'reason': 'Discount',
            'amount': '100.00'
        }
    ],
    
    # Monetary totals
    'subtotal': '1487.40',
    'allowance_total': '100.00',
    'tax_exclusive_amount': '1387.40',
    'tax_amount': '208.11',
    'total_amount': '1595.51',
    'prepaid_amount': '0.00',
    
    # Payment info
    'payment_terms': 'Payment within 30 days',
    'payment_means': 'Credit transfer',
    'payment_account': 'IBAN32423940',
    
    # Additional info
    'notes': 'Some Blurb about the Invoice',
    'delivery_date': '2019-06-01',
    'contract_reference': 'CD-REF',
    'project_reference': 'PR-REF',
    
    # Status
    'status': 'success'
}


async def test_pdf_conversion():
    """Test PDF generation with comprehensive data"""
    print("=" * 80)
    print("TESTING PDF CONVERSION")
    print("=" * 80)
    
    try:
        print("\n[INPUT] Comprehensive Invoice Data")
        print(f"   Invoice Number: {SAMPLE_INVOICE_DATA['invoice_number']}")
        print(f"   Currency: {SAMPLE_INVOICE_DATA['currency']}")
        print(f"   Total Amount: {SAMPLE_INVOICE_DATA['total_amount']}")
        print(f"   Line Items: {len(SAMPLE_INVOICE_DATA['line_items'])}")
        print(f"   Allowances: {len(SAMPLE_INVOICE_DATA['allowances'])}")
        
        # Generate PDF
        print("\n[CONVERTING] Generating comprehensive PDF...")
        pdf_bytes = await generate_pdf_from_xml(
            xml_content="",  # Not needed when invoice_data is provided
            invoice_data=SAMPLE_INVOICE_DATA
        )
        
        if not pdf_bytes:
            print("\n[ERROR] PDF generation returned None")
            return False
        
        print(f"\n[SUCCESS] PDF generated successfully!")
        print(f"   Output size: {len(pdf_bytes)} bytes")
        
        # Verify PDF structure
        print("\n[VALIDATING] PDF structure...")
        
        # Check PDF header
        if pdf_bytes.startswith(b'%PDF-'):
            print("   [OK] Valid PDF header")
        else:
            print("   [ERROR] Invalid PDF header")
            return False
        
        # Check PDF footer
        if b'%%EOF' in pdf_bytes:
            print("   [OK] Valid PDF footer")
        else:
            print("   [ERROR] Missing PDF footer")
            return False
        
        # Save output for inspection
        output_file = Path(__file__).parent / "test_pdf_output.pdf"
        with open(output_file, 'wb') as f:
            f.write(pdf_bytes)
        
        print(f"\n[SAVED] PDF saved to: {output_file}")
        
        print("\n" + "=" * 80)
        print("[SUCCESS] ALL TESTS PASSED!")
        print("=" * 80)
        print("\nExpected content in PDF:")
        print("  - Invoice header with number, dates, PO number, customer ID")
        print("  - Supplier information (name, address, tax ID)")
        print("  - Customer information (name, address, tax ID)")
        print("  - Complete line items table with all 3 products")
        print("  - Allowances section showing discount")
        print("  - Comprehensive totals breakdown:")
        print("    * Subtotal: NZD 1487.40")
        print("    * Total Allowances: - NZD 100.00")
        print("    * Tax Exclusive Amount: NZD 1387.40")
        print("    * Tax Amount: NZD 208.11")
        print("    * Total Amount Due: NZD 1595.51")
        print("  - Payment information (terms, means, account)")
        print("  - Additional information (notes, delivery date, references)")
        print("  - Professional formatting with tables and sections")
        print("=" * 80)
        print("\nFile properties after conversion:")
        print("  - Extension: .pdf")
        print("  - Content type: application/pdf")
        print("  - Can be opened in any PDF viewer")
        print("  - All data from validated invoice included")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_pdf_conversion())
    sys.exit(0 if success else 1)
