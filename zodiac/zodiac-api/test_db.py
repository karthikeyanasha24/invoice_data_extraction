#!/usr/bin/env python3
import os
import sys
from sqlalchemy import create_engine, text

# Set up database connection
DATABASE_URL = "postgresql://myuser:mypassword@localhost:5432/mydatabase"
engine = create_engine(DATABASE_URL)

def check_failed_invoices():
    """Check if there are any failed invoices with processing_steps_error data"""
    try:
        with engine.connect() as conn:
            # Check failed invoices
            result = conn.execute(text("""
                SELECT id, tracking_id, processing_steps_error, 
                       xml_validation_pass, edi_convert_pass
                FROM zodiac_invoice_failed_edi 
                WHERE deleted_at IS NULL 
                ORDER BY uploaded_at DESC 
                LIMIT 5
            """))
            
            rows = result.fetchall()
            print(f"Found {len(rows)} failed invoices:")
            
            for row in rows:
                print(f"\nInvoice ID: {row.id}")
                print(f"Tracking ID: {row.tracking_id}")
                print(f"XML Validation Pass: {row.xml_validation_pass}")
                print(f"EDI Convert Pass: {row.edi_convert_pass}")
                print(f"Processing Steps Error: {row.processing_steps_error}")
                print("-" * 50)
                
    except Exception as e:
        print(f"Error checking failed invoices: {e}")

def check_success_invoices():
    """Check if there are any success invoices with processing_steps_error data"""
    try:
        with engine.connect() as conn:
            # Check success invoices
            result = conn.execute(text("""
                SELECT id, tracking_id, processing_steps_error, 
                       xml_validation_pass, edi_convert_pass
                FROM zodiac_invoice_success_edi 
                WHERE deleted_at IS NULL 
                ORDER BY uploaded_at DESC 
                LIMIT 5
            """))
            
            rows = result.fetchall()
            print(f"Found {len(rows)} success invoices:")
            
            for row in rows:
                print(f"\nInvoice ID: {row.id}")
                print(f"Tracking ID: {row.tracking_id}")
                print(f"XML Validation Pass: {row.xml_validation_pass}")
                print(f"EDI Convert Pass: {row.edi_convert_pass}")
                print(f"Processing Steps Error: {row.processing_steps_error}")
                print("-" * 50)
                
    except Exception as e:
        print(f"Error checking success invoices: {e}")

if __name__ == "__main__":
    print("=== Checking Failed Invoices ===")
    check_failed_invoices()
    
    print("\n=== Checking Success Invoices ===")
    check_success_invoices()



