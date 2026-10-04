"""
Sample GST — party / ledger mapping (country-owned).

Deliberately different from Mexico's RFC → SAP GL mapping service:
- Uses GSTIN as the tax identifier.
- Mapping table lives in workspace adapter config (no SATSupplierMappingService).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .config import SampleGstConfig


def map_parties(document: Dict[str, Any], config: SampleGstConfig) -> Dict[str, Any]:
    """Resolve seller GSTIN to a ledger account using workspace config."""
    seller = document.get("seller") or {}
    buyer = document.get("buyer") or {}
    seller_gstin = str(seller.get("gstin") or "").upper()
    buyer_gstin = str(buyer.get("gstin") or "").upper()

    ledger = config.tax_id_ledger_map.get(seller_gstin)
    used_default = ledger is None
    if used_default:
        ledger = config.default_ledger

    return {
        "seller_gstin": seller_gstin,
        "buyer_gstin": buyer_gstin,
        "seller_name": seller.get("name"),
        "buyer_name": buyer.get("name"),
        "ledger_account": ledger,
        "used_default_ledger": used_default,
        "place_of_supply": document.get("place_of_supply"),
        "supply_type": _infer_supply_type(seller_gstin, buyer_gstin, document),
    }


def _infer_supply_type(
    seller_gstin: str, buyer_gstin: str, document: Dict[str, Any]
) -> str:
    explicit = document.get("supply_type")
    if explicit:
        return str(explicit).upper()
    if len(seller_gstin) >= 2 and len(buyer_gstin) >= 2:
        if seller_gstin[:2] == buyer_gstin[:2]:
            return "INTRA_STATE"
        return "INTER_STATE"
    return "UNKNOWN"
