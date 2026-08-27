"""
Declare fact / join / aggregation grain for deep SQL.

Monetary queries must stay on billing_item (vbrp) and only attach N:1 dimensions.
MATNR bridges to purchase are never allowed to multiply NETWR/WAVWR.
Inventory snapshot tables (MBEW/MARD) must never join into VBRP before SUM(NETWR).
"""
from __future__ import annotations

import re
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

_INV_JOIN_RE = re.compile(r'\bJOIN\s+"?(MBEW|MARD)"?', re.I)


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
            "join_grain": "MBEW GROUP BY MATNR[+BWKEY]",
            "aggregation_grain": "product / valuation_area",
            "monetary_source": "MBEW.SALK3 snapshot; qty = MBEW.LBKUM",
            "fanout_safe": True,
            "note": "Snapshot — not billing grain. Do not join into VBRP before aggregating.",
        }
    if intent in {"inventory_sales_comparison", "inventory_risk_analysis"}:
        grain = "product_group" if "product_group" in dims else "product"
        return {
            "fact_grain": "sales_agg ⋈ inventory_agg",
            "join_grain": f"independent GROUP BY {grain} then JOIN",
            "aggregation_grain": grain,
            "monetary_source": "VBRP.NETWR/WAVWR/FKIMG independently of MBEW.SALK3/LBKUM",
            "fanout_safe": True,
            "note": "Never FROM vbrp JOIN MARD/MBEW SUM(NETWR).",
        }
    if intent in {"inventory_by_plant"}:
        return {
            "fact_grain": "storage_location_stock",
            "join_grain": "MARD GROUP BY MATNR+WERKS (or WERKS)",
            "aggregation_grain": "plant_code",
            "monetary_source": "MARD.LABST unrestricted qty — plant codes, no T001W text",
            "fanout_safe": True,
            "note": "Inventory is not customer/region owned. Sales plant grain only via independent VBRP.WERKS agg.",
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
    raw = sql or ""
    if "NETWR" not in s and "WAVWR" not in s:
        return False
    if "VBRP" not in s and '"VBRP"' not in s and "vbrp" not in raw.lower():
        return False
    for t in UNSAFE_MONETARY_JOINS:
        if t in s and "VBRP" in s:
            return True
    # Billing fact joined to inventory snapshot before aggregation → fan-out.
    # Independent CTEs (FROM "MBEW" inside WITH, then JOIN aliases) are allowed.
    if _INV_JOIN_RE.search(raw):
        return True
    return False
