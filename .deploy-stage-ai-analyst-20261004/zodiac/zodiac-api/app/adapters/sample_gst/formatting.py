"""
Sample GST — transform + wire formatting (country-owned).

Deliberately different from Mexico's SAP uppercase JSON list:
- Target shape is a single camelCase government-style envelope.
- Includes HSN-level tax breakup and IRN, not DS_UUID / GL_ACCOUNT fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .config import SampleGstConfig


def transform_document(
    document: Dict[str, Any],
    mapping: Dict[str, Any],
    rules_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Internal model → government-oriented structure (still not the wire string)."""
    line_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(document.get("line_items") or [], start=1):
        if not isinstance(item, dict):
            continue
        amount = float(item.get("amount") or 0)
        rate = float(item.get("tax_rate") or 0)
        tax_amount = round(amount * rate, 2)
        line_items.append(
            {
                "lineNo": idx,
                "hsnCode": str(item.get("hsn")),
                "description": item.get("description") or "",
                "taxableAmount": amount,
                "taxRate": rate,
                "taxAmount": tax_amount,
            }
        )

    return {
        "irn": document.get("irn"),
        "documentType": str(document.get("document_type") or "").upper(),
        "documentNumber": document.get("document_number"),
        "documentDate": document.get("document_date"),
        "currency": document.get("currency"),
        "supplyType": mapping.get("supply_type"),
        "sellerGstin": mapping.get("seller_gstin"),
        "buyerGstin": mapping.get("buyer_gstin"),
        "ledgerAccount": mapping.get("ledger_account"),
        "placeOfSupply": mapping.get("place_of_supply"),
        "ewayBillId": document.get("eway_bill_id"),
        "totalTaxableAmount": rules_meta.get("taxable_amount"),
        "totalAmount": float(document.get("total_amount") or 0),
        "lineItems": line_items,
        "originalIrn": document.get("original_irn"),
    }


def format_payload(
    transformed: Dict[str, Any],
    config: SampleGstConfig,
    *,
    correlation_id: str,
) -> Dict[str, Any]:
    """Wrap the transformed document in the sample wire envelope."""
    return {
        "schema": "sample-gst-einvoice",
        "schemaVersion": "1.0",
        "correlationId": correlation_id,
        "submittedAt": datetime.now(timezone.utc).isoformat(),
        "endpointRef": config.endpoint_url_ref,
        "authRef": config.auth_secret_ref,
        "invoice": transformed,
    }
