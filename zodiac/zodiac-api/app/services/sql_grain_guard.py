"""
Declare fact / join / aggregation grain for deep SQL.

Monetary queries must stay on billing_item (vbrp) and only attach N:1 dimensions.
MATNR bridges to purchase are never allowed to multiply NETWR/WAVWR.
"""
from __future__ import annotations

from typing import Any, Dict, List

SAFE_MONETARY_JOINS = {
    ("vbrp", "VBRK", "vbeln"),
    ("VBRK", "KNA1", "kunag/kunnr"),
    ("vbrp", "MAKT", "matnr"),
    ("vbrp", "MARA", "matnr"),
    ("KNA1", "T016T", "brsch"),
}

UNSAFE_MONETARY_JOINS = {
    "EKPO",
    "EKKO",
    "LFA1",
    "VBFA",
    "LIPS",
    "LIKP",
    "KONV",
    "BSEG",
    "FAGLFLEXA",
    "COEP",
}


def grain_contract(intent: str, dimensions: List[str]) -> Dict[str, Any]:
    dims = set(dimensions or [])
    if intent in {"suppliers_of_selection", "purchase_cost_by_product"}:
        return {
            "fact_grain": "po_item",
            "join_grain": "EKPO⋈EKKO⋈LFA1",
            "aggregation_grain": "supplier/product",
            "monetary_source": "EKPO.NETWR (purchase value, not invoice COGS)",
            "fanout_safe": True,
        }
    if intent in {"inventory_analysis"}:
        return {
            "fact_grain": "material_valuation",
            "join_grain": "MBEW/MARD",
            "aggregation_grain": "product",
            "monetary_source": "MBEW.SALK3 snapshot",
            "fanout_safe": True,
        }
    if any(d in dims for d in ("supplier",)):
        return {
            "fact_grain": "po_item",
            "join_grain": "material bridge",
            "aggregation_grain": ",".join(sorted(dims)),
            "monetary_source": "purchase NETWR only",
            "fanout_safe": True,
            "note": "Do not join suppliers into billing amount queries",
        }
    return {
        "fact_grain": "billing_item",
        "join_grain": "vbrp⋈VBRK (+ N:1 KNA1/MAKT/MARA)",
        "aggregation_grain": ",".join(sorted(dims)) or "product,currency",
        "monetary_source": "vbrp.NETWR / vbrp.WAVWR",
        "fanout_safe": True,
    }


def sql_has_unsafe_monetary_fanout(sql: str) -> bool:
    s = (sql or "").upper()
    if "NETWR" not in s and "WAVWR" not in s:
        return False
    if "VBRP" not in s and '"VBRP"' not in s and "vbrp" not in (sql or "").lower():
        return False
    for t in UNSAFE_MONETARY_JOINS:
        if t in s and "VBRP" in s:
            return True
    return False
