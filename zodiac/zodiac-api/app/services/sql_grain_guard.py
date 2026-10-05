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
    if intent in {"suppliers_of_selection", "purchase_cost_by_product", "supplier_concentration"}:
        return {
            "fact_grain": "po_item",
            "join_grain": "EKPO⋈EKKO⋈LFA1",
            "aggregation_grain": "supplier" if intent == "supplier_concentration" else "supplier/product",
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
    has_billing = "VBRP" in s or "vbrp" in raw.lower()
    # See below: this specific template proves VBFA/VBRP relationships first,
    # then aggregates linked orders back to one row per billing document.
    linked_order_invoice_grain = (
        re.search(r"\binvoice_cohort\s+AS\s*\(", raw, re.I)
        and re.search(r"\border_periods\s+AS\s*\(", raw, re.I)
        and re.search(
            r'GROUP\s+BY\s+l\."billing_document"\s*,\s*i\."currency"', raw, re.I
        )
        and re.search(
            r'LEFT\s+JOIN\s+"?order_periods"?\s+p\s+ON\s+p\."billing_document"\s*=\s*i\."billing_document"',
            raw,
            re.I,
        )
        and not re.search(r"\b(?:SUM|AVG)\s*\(\s*p\.\"order_amount_", raw, re.I)
    )
    if has_billing:
        for t in UNSAFE_MONETARY_JOINS:
            if t in s and not (linked_order_invoice_grain and t == "VBFA"):
                return True
        if _INV_JOIN_RE.search(raw):
            return True
    # Purchase NETWR joined to inventory snapshot before aggregation.
    if "EKPO" in s and _INV_JOIN_RE.search(raw):
        return True
    # The linked-order comparison template keeps monetary sources separate:
    # invoice_cohort has one row per billing document, order_periods aggregates
    # linked order amounts back to that same billing-document grain, and the
    # final projection joins the two one-to-one without aggregating either
    # amount across the other source. This is safe despite naming both SAP
    # money-bearing tables in separate CTEs.
    if linked_order_invoice_grain:
        return False
    # Sales-order monetary grain must not mix with billing or schedule-line fan-out.
    has_order = "VBAK" in s or "VBAP" in s
    if has_order and has_billing:
        return True
    if "VBEP" in s and "VBAP" in s and "NETWR" in s:
        return True
    return False
