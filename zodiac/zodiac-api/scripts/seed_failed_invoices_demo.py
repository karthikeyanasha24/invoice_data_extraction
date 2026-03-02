#!/usr/bin/env python3
"""
Seed Failed Invoices Demo (for Dashboard From ERP – Failed Invoices Analysis).

Creates 2–3 sample failed validations so the Failed Invoices Analysis section
has data to display. Uses configurable customer IDs (env CUSTOMER_IDS or defaults).
Inserts directly into v2_invoice_documents and v2_validated_invoices (no file storage).
For demo/testing only.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.invoice_v2_document import InvoiceV2Document
from app.models.invoice_v2_validated import InvoiceV2Validated


def get_demo_user_id(db):
    """First user in DB, or 1 as fallback."""
    from app.models.user import ZodiacUser
    u = db.query(ZodiacUser).first()
    return u.id if u else 1


def main():
    customer_ids_raw = os.getenv("CUSTOMER_IDS", "CUST-001,CUST-002,CUST-002,CUST-003")
    customer_ids = [x.strip() for x in customer_ids_raw.split(",") if x.strip()]
    if not customer_ids:
        customer_ids = ["CUST-001", "CUST-002", "CUST-002", "CUST-003"]

    db = SessionLocal()
    try:
        user_id = get_demo_user_id(db)
        now = datetime.utcnow()
        base_date = (now - timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)

        # 1) Missing required fields (customer_name, tax_percentage) – 2 invoices
        # 2) Invalid date format – 1 invoice
        # 3) Invalid currency code – 1 invoice
        # CUST-002 appears twice → repetitive
        samples = [
            {
                "filename": "demo_failed_missing_fields_1.xml",
                "customer_id": customer_ids[0] if len(customer_ids) > 0 else "CUST-001",
                "customer_name": "Demo Customer One",
                "total": 500.25,
                "currency": "USD",
                "missing_fields": ["customer_name", "tax_percentage"],
                "validation_errors": [],
            },
            {
                "filename": "demo_failed_missing_fields_2.xml",
                "customer_id": customer_ids[1] if len(customer_ids) > 1 else "CUST-002",
                "customer_name": "",
                "total": 750.25,
                "currency": "USD",
                "missing_fields": ["customer_name", "tax_percentage"],
                "validation_errors": [],
            },
            {
                "filename": "demo_failed_invalid_date.xml",
                "customer_id": customer_ids[2] if len(customer_ids) > 2 else "CUST-002",
                "customer_name": "Demo Customer Two",
                "total": 2000.0,
                "currency": "MXN",
                "missing_fields": [],
                "validation_errors": [
                    {"field": "issue_date", "message": "Invalid date format. Expected YYYY-MM-DD, got: 04/11/2015"}
                ],
            },
            {
                "filename": "demo_failed_invalid_currency.xml",
                "customer_id": customer_ids[3] if len(customer_ids) > 3 else "CUST-003",
                "customer_name": "Demo Customer Three",
                "total": 15000.0,
                "currency": "MXN",
                "missing_fields": [],
                "validation_errors": [
                    {"field": "currency", "message": "Invalid currency code. Expected 3-letter code, got: MX"}
                ],
            },
        ]

        created = 0
        for i, s in enumerate(samples):
            doc = InvoiceV2Document(
                tracking_id=uuid.uuid4(),
                user_id=user_id,
                source="manual",
                filename=s["filename"],
                xml_path=f"demo/{s['filename']}",
                blob_xml_path=None,
                validation_status="validated",
                uploaded_at=base_date + timedelta(hours=i * 6),
            )
            db.add(doc)
            db.flush()

            inv_data = {
                "invoice_number": f"DEMO-FAIL-{i+1}",
                "issue_date": (base_date + timedelta(hours=i * 6)).strftime("%Y-%m-%d"),
                "currency": s["currency"],
                "customer_id": s["customer_id"],
                "customer_name": s.get("customer_name") or "",
                "supplier_id": "SUP-001",
                "supplier_name": "Demo Supplier",
                "total": s["total"],
                "tax_percentage": "0" if s.get("missing_fields") else "0",
            }
            validated = InvoiceV2Validated(
                document_id=doc.id,
                status="failed",
                invoice_data=inv_data,
                missing_fields=s["missing_fields"] if s["missing_fields"] else None,
                validation_errors=s["validation_errors"] if s["validation_errors"] else None,
                validation_notes="Demo seed for Failed Invoices Analysis.",
                validated_at=doc.uploaded_at,
            )
            db.add(validated)
            created += 1

        db.commit()
        print(f"Created {created} demo failed invoice(s) for user_id={user_id}. Run Dashboard From ERP and open Failed Invoices Analysis.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
