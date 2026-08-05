"""
Sample GST — validation rules (country-owned).

Deliberately different from Mexico CFDI validation:
- Input is JSON (not XML with TimbreFiscalDigital/UUID).
- Seller/buyer identified by GSTIN (15-char alphanumeric), not RFC.
- Requires an IRN (invoice reference number) instead of a CFDI UUID.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import SAMPLE_GST_DOCUMENT_TYPES, SAMPLE_GST_SCHEMA_VERSION

# Rough GSTIN shape: 2 digits + 10 PAN-like + 1 entity + 1 Z + 1 checksum.
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_IRN_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def parse_payload(payload: Any) -> Dict[str, Any]:
    """Normalize str/bytes/dict payloads into a document dict."""
    if payload is None:
        raise ValueError("No document payload supplied")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            raise ValueError("Empty document payload")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Sample GST documents must be JSON: {exc}") from exc
    elif isinstance(payload, dict):
        data = payload
    else:
        raise ValueError(f"Unsupported payload type: {type(payload)!r}")

    if not isinstance(data, dict):
        raise ValueError("Sample GST document root must be a JSON object")
    return data


def validate_document(
    document: Dict[str, Any],
    *,
    expected_currency: str = "INR",
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Structural validation for the sample GST schema.

    Returns (is_valid, primary_error, all_errors).
    """
    errors: List[str] = []

    version = str(document.get("schema_version") or "")
    if version != SAMPLE_GST_SCHEMA_VERSION:
        errors.append(
            f"Unsupported schema_version '{version}' (expected '{SAMPLE_GST_SCHEMA_VERSION}')"
        )

    doc_type = str(document.get("document_type") or "").upper()
    if doc_type not in SAMPLE_GST_DOCUMENT_TYPES:
        errors.append(
            f"document_type must be one of {', '.join(SAMPLE_GST_DOCUMENT_TYPES)}"
        )

    irn = document.get("irn")
    if not irn or not _IRN_RE.match(str(irn)):
        errors.append("irn must be a 64-character hex invoice reference number")

    seller = document.get("seller") or {}
    buyer = document.get("buyer") or {}
    if not isinstance(seller, dict) or not _GSTIN_RE.match(str(seller.get("gstin") or "").upper()):
        errors.append("seller.gstin is missing or not a valid 15-character GSTIN")
    if not isinstance(buyer, dict) or not _GSTIN_RE.match(str(buyer.get("gstin") or "").upper()):
        errors.append("buyer.gstin is missing or not a valid 15-character GSTIN")

    currency = str(document.get("currency") or "").upper()
    if currency != expected_currency.upper():
        errors.append(f"currency must be '{expected_currency}' for this workspace")

    try:
        total = float(document.get("total_amount"))
        if total <= 0:
            errors.append("total_amount must be greater than zero")
    except (TypeError, ValueError):
        errors.append("total_amount must be a number")

    line_items = document.get("line_items")
    if not isinstance(line_items, list) or not line_items:
        errors.append("line_items must be a non-empty array")
    else:
        for idx, item in enumerate(line_items):
            if not isinstance(item, dict):
                errors.append(f"line_items[{idx}] must be an object")
                continue
            if not item.get("hsn"):
                errors.append(f"line_items[{idx}].hsn is required")
            try:
                if float(item.get("amount", 0)) <= 0:
                    errors.append(f"line_items[{idx}].amount must be > 0")
            except (TypeError, ValueError):
                errors.append(f"line_items[{idx}].amount must be a number")

    if errors:
        return False, errors[0], errors
    return True, None, []
