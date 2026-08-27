"""
Machine-readable R3 business graph derived from schema_full.json.

Nothing here invents tables. Status is SUPPORTED / PARTIAL / DATA_GAP / UNSAFE.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Tables confirmed present in schema_full.json (121 tables). ACDOCA is absent.
SCHEMA_TABLES = {
    "billing_header": "VBRK",
    "billing_item": "vbrp",
    "customer": "KNA1",
    "industry_text": "T016T",
    "product": "MARA",
    "product_text": "MAKT",
    "sales_order": "VBAK",
    "sales_order_item": "VBAP",
    "delivery_header": "LIKP",
    "delivery_item": "LIPS",
    "document_flow": "VBFA",
    "purchase_header": "EKKO",
    "purchase_item": "EKPO",
    "vendor": "LFA1",
    "inventory_value": "MBEW",
    "inventory_qty": "MARD",
    "pricing_conditions": "KONV",
    "fi_document": "BKPF",
    "fi_item": "BSEG",
    "gl_actuals": "FAGLFLEXA",
    "co_actuals": "COEP",
    "material_doc_header": "MKPF",
}

ENTITIES: List[Dict[str, Any]] = [
    {
        "entity": "Product",
        "source": "MARA/MAKT/vbrp.MATNR",
        "grain": "material",
        "pk": "MATNR",
        "measures": ["NETWR", "WAVWR", "FKIMG"],
        "dimensions": ["MATKL", "MTART"],
        "confidence": "high",
        "status": "SUPPORTED",
        "limitations": "Brand is not a certified master field in this extract.",
    },
    {
        "entity": "Customer",
        "source": "KNA1 via VBRK.KUNAG",
        "grain": "customer",
        "pk": "KUNNR",
        "measures": [],
        "dimensions": ["BRSCH", "LAND1", "REGIO"],
        "confidence": "high",
        "status": "SUPPORTED",
        "limitations": "Customer segment beyond BRSCH is not modeled.",
    },
    {
        "entity": "Industry",
        "source": "KNA1.BRSCH + T016T",
        "grain": "industry key",
        "pk": "BRSCH",
        "confidence": "high",
        "status": "SUPPORTED",
    },
    {
        "entity": "Country/Region",
        "source": "KNA1.LAND1 / VBRK.LAND1",
        "grain": "country",
        "pk": "LAND1",
        "confidence": "high",
        "status": "SUPPORTED",
        "limitations": "REGIO exists but has no certified BI text join in catalog.",
    },
    {
        "entity": "Supplier/Vendor",
        "source": "LFA1 via EKKO.LIFNR",
        "grain": "vendor",
        "pk": "LIFNR",
        "measures": ["EKPO.NETWR", "EKPO.MENGE", "EKPO.NETPR"],
        "confidence": "medium",
        "status": "PARTIAL",
        "limitations": "Linked to billed products by MATNR only — not document-level to invoice.",
    },
    {
        "entity": "Purchase order",
        "source": "EKKO/EKPO",
        "grain": "PO item",
        "pk": "EBELN+EBELP",
        "date_fields": ["BEDAT"],
        "confidence": "high",
        "status": "SUPPORTED",
        "limitations": "Purchase value is not invoice COGS (WAVWR).",
    },
    {
        "entity": "Sales order / Delivery / Billing",
        "source": "VBAK/VBAP, LIKP/LIPS, VBRK/vbrp, VBFA",
        "grain": "document",
        "confidence": "high",
        "status": "SUPPORTED",
        "limitations": "Process counts and flow links; durations are partial.",
    },
    {
        "entity": "Inventory",
        "source": "MBEW/MARD",
        "grain": "material/plant/storage",
        "measures": ["SALK3", "LBKUM", "LABST"],
        "confidence": "medium",
        "status": "PARTIAL",
        "limitations": "Current snapshot value/qty only. MSEG absent — aging is DATA GAP. No dated snapshots — trend/turnover DATA GAP.",
    },
    {
        "entity": "Expiry/batch",
        "source": "MARA MHDHB/MHDRZ + LIPS.VFDAT",
        "grain": "material/delivery item",
        "confidence": "medium",
        "status": "PARTIAL",
    },
    {
        "entity": "Pricing conditions",
        "source": "VBRK.KNUMV → KONV",
        "grain": "condition line",
        "confidence": "low",
        "status": "UNSAFE",
        "limitations": "KSCHL mapping for discount vs tax vs freight is not certified. Do not expose as Discount.",
    },
    {
        "entity": "Finance / GL / CO",
        "source": "BKPF/BSEG, FAGLFLEXA, COEP",
        "grain": "FI/CO document — not billing item",
        "confidence": "low",
        "status": "DATA_GAP",
        "limitations": "Cannot allocate operating cost to product. Net profit remains DATA GAP.",
    },
    {
        "entity": "Budget/Target",
        "source": None,
        "status": "DATA_GAP",
        "limitations": "No budget/target extract in schema_full.",
    },
    {
        "entity": "Logistics cost",
        "source": "LIKP/LIPS activity only",
        "status": "DATA_GAP",
        "limitations": "No freight amount. KONV freight KSCHL not certified.",
    },
]

RELATIONSHIP_GRAPH: List[Dict[str, Any]] = [
    {
        "source": "billing_item",
        "source_field": "VBELN",
        "target": "billing_header",
        "target_field": "VBELN",
        "type": "ITEM_OF",
        "cardinality": "N:1",
        "grain": "billing_item",
        "confidence": "high",
        "allowed_aggregations": ["SUM NETWR", "SUM WAVWR", "SUM FKIMG"],
        "duplication_risk": "none if grouped by item keys before header dims",
        "meaning": "Invoice line to invoice header",
    },
    {
        "source": "billing_header",
        "source_field": "KUNAG",
        "target": "customer",
        "target_field": "KUNNR",
        "type": "SOLD_TO",
        "cardinality": "N:1",
        "confidence": "high",
        "allowed_aggregations": ["SUM from billing_item"],
        "duplication_risk": "low",
        "meaning": "Billed sold-to party",
    },
    {
        "source": "customer",
        "source_field": "BRSCH",
        "target": "industry",
        "target_field": "BRSCH",
        "type": "HAS_INDUSTRY",
        "cardinality": "N:1",
        "confidence": "high",
        "meaning": "Customer industry",
    },
    {
        "source": "billing_item",
        "source_field": "MATNR",
        "target": "product",
        "target_field": "MATNR",
        "type": "PRODUCT_SOLD",
        "cardinality": "N:1",
        "confidence": "high",
        "meaning": "Billed material",
    },
    {
        "source": "purchase_item",
        "source_field": "EBELN",
        "target": "purchase_header",
        "target_field": "EBELN",
        "type": "PO_ITEM",
        "cardinality": "N:1",
        "confidence": "high",
        "meaning": "PO item to PO header",
    },
    {
        "source": "purchase_header",
        "source_field": "LIFNR",
        "target": "vendor",
        "target_field": "LIFNR",
        "type": "PROCURED_FROM",
        "cardinality": "N:1",
        "confidence": "high",
        "meaning": "PO vendor",
    },
    {
        "source": "billing_item",
        "source_field": "MATNR",
        "target": "purchase_item",
        "target_field": "MATNR",
        "type": "MATERIAL_BRIDGE",
        "cardinality": "N:N",
        "confidence": "low",
        "allowed_aggregations": ["purchase NETWR separately — never fan-out invoice NETWR through this join"],
        "duplication_risk": "high if joined into billing monetary queries",
        "meaning": "Same material appears on invoices and POs",
        "unsafe": True,
    },
    {
        "source": "sales_order",
        "source_field": "VBELN",
        "target": "delivery/billing",
        "target_field": "VBFA",
        "type": "PROCESS_FLOW",
        "cardinality": "N:N",
        "confidence": "medium",
        "meaning": "Order → delivery → billing document flow",
        "duplication_risk": "high if used to multiply amounts",
    },
]

DIMENSIONS: List[Dict[str, Any]] = [
    {"dimension": "product", "status": "SUPPORTED", "source": "vbrp.MATNR", "metrics": ["revenue", "cogs", "gross_profit"]},
    {"dimension": "product_group", "status": "PARTIAL", "source": "MARA.MATKL", "metrics": ["revenue", "cogs"]},
    {"dimension": "customer", "status": "SUPPORTED", "source": "VBRK.KUNAG"},
    {"dimension": "industry", "status": "SUPPORTED", "source": "KNA1.BRSCH"},
    {"dimension": "country", "status": "SUPPORTED", "source": "KNA1.LAND1 / VBRK.LAND1"},
    {"dimension": "year", "status": "SUPPORTED", "source": "VBRK.FKDAT substring (YYYY)"},
    {"dimension": "month", "status": "SUPPORTED", "source": "VBRK.FKDAT substring → YYYY-MM", "ordering": "chronological year_month"},
    {"dimension": "quarter", "status": "SUPPORTED", "source": "VBRK.FKDAT substring → YYYY-Qn", "ordering": "chronological year_quarter"},
    {"dimension": "currency", "status": "SUPPORTED", "source": "VBRK.WAERK"},
    {"dimension": "supplier", "status": "PARTIAL", "source": "EKKO.LIFNR via MATNR bridge", "unsafe_with": ["invoice monetary fan-out"]},
    {"dimension": "warehouse", "status": "PARTIAL", "source": "MARD.LGORT / EKPO.WERKS"},
    {"dimension": "sales_org", "status": "PARTIAL", "source": "VBRK.VKORG", "limitations": "No TVKOT text table in schema_full"},
    {"dimension": "batch/expiry", "status": "PARTIAL", "source": "LIPS.VFDAT / MARA shelf life"},
    {"dimension": "budget", "status": "DATA_GAP"},
    {"dimension": "brand", "status": "DATA_GAP"},
    {"dimension": "sales_employee", "status": "DATA_GAP"},
]

METRICS_R3: List[Dict[str, Any]] = [
    {"metric": "revenue", "status": "SUPPORTED", "formula": "SUM(vbrp.NETWR)", "grain": "billing_item"},
    {"metric": "cogs", "status": "SUPPORTED", "formula": "SUM(vbrp.WAVWR)", "grain": "billing_item"},
    {"metric": "gross_profit", "status": "SUPPORTED", "formula": "revenue - cogs", "grain": "billing_item"},
    {"metric": "gross_margin_pct", "status": "SUPPORTED", "formula": "gross_profit / revenue", "grain": "billing_item"},
    {"metric": "quantity", "status": "SUPPORTED", "formula": "SUM(vbrp.FKIMG)", "grain": "billing_item"},
    {"metric": "invoice_count", "status": "SUPPORTED", "formula": "COUNT DISTINCT VBRK.VBELN", "grain": "billing_header"},
    {"metric": "avg_selling_price", "status": "SUPPORTED", "formula": "revenue / NULLIF(quantity,0)", "grain": "billing_item"},
    {"metric": "purchase_value", "status": "PARTIAL", "formula": "SUM(EKPO.NETWR)", "grain": "po_item", "not": "cogs"},
    {"metric": "purchase_qty", "status": "PARTIAL", "formula": "SUM(EKPO.MENGE)", "grain": "po_item"},
    {"metric": "inventory_value", "status": "PARTIAL", "formula": "SUM(MBEW.SALK3) GROUP BY MATNR[+BWKEY]", "grain": "material/valuation"},
    {"metric": "inventory_qty", "status": "PARTIAL", "formula": "SUM(MBEW.LBKUM); unrestricted SUM(MARD.LABST) by plant/storage", "grain": "material/valuation or material/plant/storage"},
    {"metric": "inventory_aging", "status": "DATA_GAP", "reason": "MSEG absent"},
    {"metric": "inventory_turnover", "status": "DATA_GAP", "reason": "no temporally aligned inventory snapshots"},
    {"metric": "delivery_count", "status": "PARTIAL", "formula": "COUNT LIKP", "grain": "delivery", "not": "logistics_cost"},
    {"metric": "discount", "status": "UNSAFE", "reason": "KONV.KSCHL not certified"},
    {"metric": "tax", "status": "UNSAFE", "reason": "condition/tax procedure not certified"},
    {"metric": "logistics_cost", "status": "DATA_GAP"},
    {"metric": "net_profit", "status": "DATA_GAP"},
    {"metric": "budget", "status": "DATA_GAP"},
    {"metric": "ebitda", "status": "DATA_GAP"},
]


def inventory_payload() -> Dict[str, Any]:
    return {
        "schema_table_count": 121,
        "missing_critical": ["ACDOCA", "MSEG", "COBK", "KONP"],
        "entities": ENTITIES,
        "relationships": RELATIONSHIP_GRAPH,
        "dimensions": DIMENSIONS,
        "metrics": METRICS_R3,
    }


def compose_intent(add_dimensions: List[str]) -> str:
    """Map added dimensions to a governed compiler intent (not phrase patches)."""
    dims = {d for d in add_dimensions if d}
    if "supplier" in dims:
        return "suppliers_of_selection"
    if "product_group" in dims:
        return "product_group_breakdown"
    if {"customer", "industry", "country"} <= dims:
        return "customer_industry_region"
    if "customer" in dims:
        return "customers_of_selection"
    if "industry" in dims and "country" in dims:
        return "product_industry_region"
    if "industry" in dims:
        return "industry_breakdown"
    if "country" in dims:
        return "country_breakdown"
    if "warehouse" in dims or "plant" in dims:
        return "inventory_by_plant"
    if "year" in dims:
        return "period_compare_selection"
    if "quarter" in dims:
        return "quarterly_trend"
    if "month" in dims:
        return "monthly_trend"
    return "dimensional_extend"
