"""
Sample GST — business rules (country-owned).

Deliberately different from Mexico merge/dedupe rules:
- No period merge of I+P+C documents.
- Interstate supplies above a configurable threshold require an e-way bill id.
- Credit notes must reference an original IRN.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config import SampleGstConfig


def apply_rules(
    document: Dict[str, Any],
    mapping: Dict[str, Any],
    config: SampleGstConfig,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Apply sample-country business rules.

    Returns (accepted, error, enriched_document_meta).
    """
    violations: List[str] = []
    doc_type = str(document.get("document_type") or "").upper()
    supply_type = str(mapping.get("supply_type") or "UNKNOWN")

    try:
        total = float(document.get("total_amount") or 0)
    except (TypeError, ValueError):
        total = 0.0

    if supply_type == "INTER_STATE" and total >= config.eway_threshold:
        eway = document.get("eway_bill_id")
        if not eway:
            violations.append(
                f"Interstate supply of {total} requires eway_bill_id "
                f"(threshold {config.eway_threshold})"
            )

    if doc_type == "CREDIT_NOTE":
        original = document.get("original_irn")
        if not original:
            violations.append("CREDIT_NOTE requires original_irn referencing the tax invoice")

    taxable = _sum_line_amounts(document)
    if taxable > 0 and abs(taxable - total) > 0.05:
        # Sample rule: total must match line items (Mexico does not enforce this here).
        violations.append(
            f"total_amount {total} does not match line_items sum {taxable}"
        )

    meta = {
        "accepted": not violations,
        "supply_type": supply_type,
        "eway_required": supply_type == "INTER_STATE" and total >= config.eway_threshold,
        "violations": violations,
        "taxable_amount": taxable,
    }

    if violations:
        return False, violations[0], meta
    return True, None, meta


def _sum_line_amounts(document: Dict[str, Any]) -> float:
    total = 0.0
    for item in document.get("line_items") or []:
        if not isinstance(item, dict):
            continue
        try:
            total += float(item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)
