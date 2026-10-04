"""Catalog entries applied only to tables that exist in the migrated schema.

Evidence tags:
  VERIFIED FROM DATABASE — table/column present in schema_full.json
  VERIFIED FROM DOCUMENTATION — SAP/business meaning from in-repo knowledge files
  INFERRED — join suggested by matching key names, not used for production SQL
  UNVERIFIED — must not be used as fact
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .physical import column_names, has_column, has_table, sap_business_tables

# Domain assignment is documentation-sourced, then intersected with the physical schema.
_DOMAIN_HINTS: Dict[str, Dict[str, Any]] = {
    "VBAK": {"primary": "sales", "secondary": [], "business_name": "Sales document header",
             "grain": "one row per sales document", "doc": "SAP SD header (order/contract/inquiry depending on AUART/VBTYP)"},
    "VBAP": {"primary": "sales", "secondary": ["product"], "business_name": "Sales document item",
             "grain": "one row per sales document item", "doc": "SAP SD item"},
    "VBEP": {"primary": "sales", "secondary": [], "business_name": "Sales document schedule line",
             "grain": "one row per schedule line (VBELN+POSNR+ETENR)", "doc": "SAP SD schedule lines (often called VBEP, not VBED)"},
    "VBFA": {"primary": "sales", "secondary": ["invoice"], "business_name": "Sales document flow",
             "grain": "preceding→subsequent document link", "doc": "SAP document flow"},
    "LIKP": {"primary": "sales", "secondary": [], "business_name": "Delivery header",
             "grain": "one row per delivery", "doc": "SAP LE outbound delivery header"},
    "LIPS": {"primary": "sales", "secondary": ["product"], "business_name": "Delivery item",
             "grain": "one row per delivery item", "doc": "SAP LE outbound delivery item"},
    "VBRK": {"primary": "invoice", "secondary": [], "business_name": "Billing document header",
             "grain": "one row per billing document", "doc": "SAP SD billing header — not a sales order"},
    "vbrp": {"primary": "invoice", "secondary": ["product"], "business_name": "Billing document item",
             "grain": "one row per billing item", "doc": "SAP SD billing item — billed quantity/value"},
    "KNA1": {"primary": "customer", "secondary": [], "business_name": "Customer master (general)",
             "grain": "one row per customer", "doc": "SAP FI/SD customer general data"},
    "KNVV": {"primary": "customer", "secondary": ["sales"], "business_name": "Customer sales area",
             "grain": "customer + sales area", "doc": "SAP SD customer sales data"},
    "KNVP": {"primary": "customer", "secondary": [], "business_name": "Customer partner functions",
             "grain": "partner function row", "doc": "SAP SD partner determination"},
    "KNBK": {"primary": "customer", "secondary": ["finance"], "business_name": "Customer bank details",
             "grain": "customer bank account", "doc": "SAP FI customer bank"},
    "T016T": {"primary": "customer", "secondary": [], "business_name": "Industry key texts",
             "grain": "industry key + language", "doc": "SAP industry description"},
    "MARA": {"primary": "product", "secondary": [], "business_name": "Material master (general)",
             "grain": "one row per material", "doc": "SAP MM material general"},
    "MAKT": {"primary": "product", "secondary": [], "business_name": "Material descriptions",
             "grain": "material + language", "doc": "SAP material text"},
    "MARC": {"primary": "product", "secondary": ["production"], "business_name": "Material plant data",
             "grain": "material + plant", "doc": "SAP MARC"},
    "MARD": {"primary": "product", "secondary": [], "business_name": "Storage location stock",
             "grain": "material + plant + storage location", "doc": "SAP unrestricted stock snapshot"},
    "MBEW": {"primary": "product", "secondary": ["cost"], "business_name": "Material valuation",
             "grain": "material + valuation area", "doc": "SAP current stock value snapshot"},
    "MBEWH": {"primary": "product", "secondary": ["cost"], "business_name": "Material valuation history",
             "grain": "material + valuation area + period", "doc": "SAP historical valuation"},
    "MVKE": {"primary": "product", "secondary": ["sales"], "business_name": "Material sales data",
             "grain": "material + sales org + dist channel", "doc": "SAP MVKE"},
    "EKKO": {"primary": "purchasing", "secondary": [], "business_name": "Purchasing document header",
             "grain": "one row per purchase order", "doc": "SAP MM PO header"},
    "EKPO": {"primary": "purchasing", "secondary": ["product"], "business_name": "Purchasing document item",
             "grain": "one row per PO item", "doc": "SAP MM PO item"},
    "EBAN": {"primary": "purchasing", "secondary": [], "business_name": "Purchase requisition",
             "grain": "one row per requisition item", "doc": "SAP MM PR"},
    "EINA": {"primary": "purchasing", "secondary": ["vendor"], "business_name": "Purchasing info record (general)",
             "grain": "info record", "doc": "SAP EINA"},
    "EINE": {"primary": "purchasing", "secondary": ["vendor"], "business_name": "Purchasing info record (org)",
             "grain": "info record + org", "doc": "SAP EINE"},
    "LFA1": {"primary": "vendor", "secondary": ["purchasing"], "business_name": "Vendor master (general)",
             "grain": "one row per vendor", "doc": "SAP vendor general"},
    "LFB1": {"primary": "vendor", "secondary": ["finance"], "business_name": "Vendor company-code data",
             "grain": "vendor + company code", "doc": "SAP LFB1"},
    "LFM1": {"primary": "vendor", "secondary": ["purchasing"], "business_name": "Vendor purchasing org data",
             "grain": "vendor + purchasing org", "doc": "SAP LFM1"},
    "RBKP": {"primary": "invoice", "secondary": ["purchasing"], "business_name": "Incoming invoice header",
             "grain": "one row per vendor invoice", "doc": "SAP MM logistics invoice header — not SD billing"},
    "RSEG": {"primary": "invoice", "secondary": ["purchasing"], "business_name": "Incoming invoice item",
             "grain": "one row per vendor invoice item", "doc": "SAP MM logistics invoice item"},
    "BKPF": {"primary": "finance", "secondary": [], "business_name": "Accounting document header",
             "grain": "one row per FI document", "doc": "SAP FI header"},
    "BSEG": {"primary": "finance", "secondary": [], "business_name": "Accounting document segment",
             "grain": "one row per FI line", "doc": "SAP FI item"},
    "BSAD": {"primary": "finance", "secondary": ["customer"], "business_name": "Cleared customer items",
             "grain": "cleared AR item", "doc": "SAP FI AR cleared"},
    "FAGLFLEXA": {"primary": "finance", "secondary": ["profit_and_loss"], "business_name": "New G/L line items",
             "grain": "G/L actual line", "doc": "SAP New G/L actuals"},
    "DFKKOP": {"primary": "finance", "secondary": [], "business_name": "Contract accounting items",
             "grain": "FI-CA open item", "doc": "SAP FI-CA"},
    "COEP": {"primary": "cost", "secondary": ["finance"], "business_name": "CO object currency line items",
             "grain": "controlling actual line", "doc": "SAP CO actuals"},
    "COSP": {"primary": "cost", "secondary": [], "business_name": "CO external posting totals",
             "grain": "CO totals", "doc": "SAP COSP"},
    "COSS": {"primary": "cost", "secondary": [], "business_name": "CO internal posting totals",
             "grain": "CO totals", "doc": "SAP COSS"},
    "CKIS": {"primary": "cost", "secondary": ["product"], "business_name": "Costing itemization",
             "grain": "cost estimate item", "doc": "SAP product costing items"},
    "CKHS": {"primary": "cost", "secondary": ["product"], "business_name": "Cost estimate header",
             "grain": "cost estimate", "doc": "SAP CKHS"},
    "KEKO": {"primary": "cost", "secondary": ["product"], "business_name": "Product cost estimate",
             "grain": "cost estimate", "doc": "SAP KEKO"},
    "KEPH": {"primary": "cost", "secondary": ["product"], "business_name": "Cost component view",
             "grain": "cost component", "doc": "SAP KEPH"},
    "AFKO": {"primary": "production", "secondary": [], "business_name": "Order header (PP)",
             "grain": "one production/process order header", "doc": "SAP PP order header"},
    "AFPO": {"primary": "production", "secondary": ["product"], "business_name": "Order item (PP)",
             "grain": "production order item", "doc": "SAP PP order item"},
    "AUFK": {"primary": "production", "secondary": ["cost"], "business_name": "Order master",
             "grain": "one order (PP/PM/CO)", "doc": "SAP order master"},
    "RESB": {"primary": "production", "secondary": ["product"], "business_name": "Reservation/dependent requirements",
             "grain": "reservation item", "doc": "SAP RESB"},
    "CRHD": {"primary": "production", "secondary": [], "business_name": "Work center header",
             "grain": "work center", "doc": "SAP CRHD"},
    "CEPC": {"primary": "profit_and_loss", "secondary": ["finance"], "business_name": "Profit center master",
             "grain": "profit center", "doc": "SAP CEPC"},
    "CSKS": {"primary": "cost", "secondary": [], "business_name": "Cost center master",
             "grain": "cost center", "doc": "SAP CSKS"},
    "MKPF": {"primary": "product", "secondary": ["production"], "business_name": "Material document header",
             "grain": "material document", "doc": "SAP MKPF"},
    "KONV": {"primary": "sales", "secondary": ["invoice"], "business_name": "Pricing conditions",
             "grain": "pricing condition line", "doc": "SAP KONV — join via KNUMV, fan-out risk"},
}

# COPA-like tables present in schema_full — meaning from documentation, usage is PARTIAL.
for _copa in (
    "CE1BGIS", "CE1IDEA", "CE1INT1", "CE1PR22", "CE1R300", "CE1S_AL", "CE1S_CP", "CE1S_GO",
    "CE2BGIS", "CE2IDEA", "CE2S_AL", "CE2S_CP", "CS2S_GO",
):
    _DOMAIN_HINTS[_copa] = {
        "primary": "profit_and_loss",
        "secondary": ["sales"],
        "business_name": "CO-PA actuals/plan extract",
        "grain": "profitability segment line (extract-specific)",
        "doc": "SAP CO-PA operating-concern tables; columns must be taken from this extract only",
    }

GLOSSARY: Dict[str, Dict[str, str]] = {
    "VBAK": {"meaning": "Sales document header", "domain": "sales", "grain": "sales document",
             "source": "VERIFIED FROM DOCUMENTATION"},
    "VBAP": {"meaning": "Sales document item", "domain": "sales", "grain": "sales document item",
             "source": "VERIFIED FROM DOCUMENTATION"},
    "VBEP": {"meaning": "Sales document schedule line", "domain": "sales", "grain": "schedule line",
             "source": "VERIFIED FROM DOCUMENTATION"},
    "VBED": {"meaning": "Not a standard SD header/item table; this extract has VBEP for schedule lines",
             "domain": "sales", "grain": "unknown", "source": "VERIFIED FROM DOCUMENTATION"},
    "VBRK": {"meaning": "Billing document header (invoice)", "domain": "invoice", "grain": "billing document",
             "source": "VERIFIED FROM DOCUMENTATION"},
    "VBRP": {"meaning": "Billing document item", "domain": "invoice", "grain": "billing item",
             "source": "VERIFIED FROM DOCUMENTATION"},
}

# Production SQL joins: only when both tables exist and keys exist on both sides.
_JOIN_CANDIDATES = [
    {"source_table": "VBAK", "source_column": "vbeln", "target_table": "VBAP", "target_column": "vbeln",
     "cardinality": "1:N", "confidence": "verified", "fanout": "header to items — aggregate at item before combining with other facts",
     "source": "VERIFIED FROM DATABASE (matching keys) + DOCUMENTATION"},
    {"source_table": "VBAP", "source_column": "vbeln", "target_table": "VBEP", "target_column": "vbeln",
     "cardinality": "1:N", "confidence": "verified", "fanout": "item to schedule lines — do not SUM VBAP.NETWR after joining VBEP",
     "source": "VERIFIED FROM DATABASE (matching keys) + DOCUMENTATION"},
    {"source_table": "VBAP", "source_column": "posnr", "target_table": "VBEP", "target_column": "posnr",
     "cardinality": "1:N", "confidence": "verified", "fanout": "compound key with vbeln",
     "source": "VERIFIED FROM DATABASE (matching keys) + DOCUMENTATION"},
    {"source_table": "VBAK", "source_column": "kunnr", "target_table": "KNA1", "target_column": "kunnr",
     "cardinality": "N:1", "confidence": "verified", "fanout": "safe after header/item aggregation",
     "source": "VERIFIED FROM DATABASE (matching keys) + DOCUMENTATION"},
    {"source_table": "VBAP", "source_column": "matnr", "target_table": "MAKT", "target_column": "matnr",
     "cardinality": "N:1", "confidence": "verified", "fanout": "safe N:1 text join",
     "source": "VERIFIED FROM DATABASE (matching keys) + DOCUMENTATION"},
    {"source_table": "VBRK", "source_column": "vbeln", "target_table": "vbrp", "target_column": "vbeln",
     "cardinality": "1:N", "confidence": "verified", "fanout": "billing header to items",
     "source": "VERIFIED FROM DATABASE + R3/R4 contract"},
    {"source_table": "VBRK", "source_column": "kunag", "target_table": "KNA1", "target_column": "kunnr",
     "cardinality": "N:1", "confidence": "verified", "fanout": "sold-to — pad keys in SQL",
     "source": "VERIFIED FROM DATABASE + R3/R4 contract"},
    {"source_table": "KNA1", "source_column": "brsch", "target_table": "T016T", "target_column": "brsch",
     "cardinality": "N:1", "confidence": "verified", "fanout": "industry text",
     "source": "VERIFIED FROM DATABASE + R3/R4 contract"},
    {"source_table": "EKKO", "source_column": "ebeln", "target_table": "EKPO", "target_column": "ebeln",
     "cardinality": "1:N", "confidence": "verified", "fanout": "PO header to items",
     "source": "VERIFIED FROM DATABASE + R4-4 contract"},
    {"source_table": "EKKO", "source_column": "lifnr", "target_table": "LFA1", "target_column": "lifnr",
     "cardinality": "N:1", "confidence": "verified", "fanout": "vendor master",
     "source": "VERIFIED FROM DATABASE + R4-4 contract"},
    {"source_table": "AFKO", "source_column": "aufnr", "target_table": "AFPO", "target_column": "aufnr",
     "cardinality": "1:N", "confidence": "inferred", "fanout": "PP header to item — verify before monetary SUM",
     "source": "INFERRED from matching AUFNR"},
    {"source_table": "VBAK", "source_column": "vbeln", "target_table": "VBRK", "target_column": "vbeln",
     "cardinality": "unknown", "confidence": "unverified", "fanout": "document numbers are different objects — do not join as equals",
     "source": "UNVERIFIED / UNSAFE — billing VBELN ≠ sales-order VBELN"},
]


def _important_columns(table: str) -> List[str]:
    cols = {c.lower() for c in column_names(table)}
    preferred = [
        "vbeln", "posnr", "etenr", "audat", "erdat", "fkdat", "bedat", "edatu",
        "kunnr", "kunag", "lifnr", "matnr", "netwr", "waerk", "kwmeng", "wmeng",
        "fkimg", "auart", "vkorg", "vtweg", "spart", "vbtyp", "arktx", "name1",
        "land1", "brsch", "ebeln", "ebelp", "menge", "aufnr", "gamng", "plnbez",
        "bukrs", "belnr", "gjahr", "hkont", "dmbtr",
    ]
    return [c for c in preferred if c in cols]


def _keys(table: str) -> List[str]:
    cols = {c.lower() for c in column_names(table)}
    keys = []
    for k in ("vbeln", "posnr", "etenr", "kunnr", "matnr", "ebeln", "ebelp", "lifnr", "aufnr", "belnr", "buzei"):
        if k in cols:
            keys.append(k)
    return keys


def _build_table_entries() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for table in sap_business_tables():
        hint = _DOMAIN_HINTS.get(table) or _DOMAIN_HINTS.get(table.upper())
        primary = (hint or {}).get("primary") or "unclassified"
        entry = {
            "table": table,
            "domain": primary,
            "primary_domain": primary,
            "secondary_domains": list((hint or {}).get("secondary") or []),
            "business_name": (hint or {}).get("business_name") or table,
            "description": (hint or {}).get("doc") or "",
            "grain": (hint or {}).get("grain") or "unknown — inspect columns",
            "keys": _keys(table),
            "important_columns": _important_columns(table),
            "date_columns": [c for c in column_names(table) if c.lower() in {
                "audat", "erdat", "fkdat", "bedat", "edatu", "budat", "aedat", "gstrp", "gltrp",
            }],
            "customer_columns": [c for c in column_names(table) if c.lower() in {"kunnr", "kunag", "kunrg"}],
            "product_columns": [c for c in column_names(table) if c.lower() in {"matnr", "plnbez"}],
            "status_columns": [c for c in column_names(table) if c.lower() in {"gbsta", "lfsta", "fksak", "abstk"}],
            "source": "database/schema_full.json",
            "confidence": "verified",
            "evidence_physical": "VERIFIED FROM DATABASE",
            "evidence_meaning": "VERIFIED FROM DOCUMENTATION" if hint else "UNVERIFIED",
        }
        out[table] = entry
        out[table.upper()] = entry
    return out


TABLE_ENTRIES = _build_table_entries()


def get_table_entry(table: str) -> Optional[Dict[str, Any]]:
    if not table:
        return None
    return TABLE_ENTRIES.get(table) or TABLE_ENTRIES.get(table.upper()) or TABLE_ENTRIES.get(table.lower())


def domain_for_table(table: str) -> str:
    entry = get_table_entry(table)
    return (entry or {}).get("primary_domain") or "unclassified"


def tables_for_domain(domain: str) -> List[str]:
    want = (domain or "").lower()
    seen = set()
    out = []
    for table, entry in TABLE_ENTRIES.items():
        if table != entry.get("table"):
            continue
        domains = [entry.get("primary_domain"), *entry.get("secondary_domains", [])]
        if want in {str(d).lower() for d in domains if d} and table not in seen:
            seen.add(table)
            out.append(table)
    return out


def _build_relationships() -> List[Dict[str, Any]]:
    rels = []
    for cand in _JOIN_CANDIDATES:
        src, tgt = cand["source_table"], cand["target_table"]
        if not has_table(src) or not has_table(tgt):
            continue
        if not has_column(src, cand["source_column"]) or not has_column(tgt, cand["target_column"]):
            continue
        rels.append({**cand, "usable_in_sql": cand["confidence"] in {"verified"}})
    return rels


RELATIONSHIPS = _build_relationships()

METRICS: Dict[str, Dict[str, Any]] = {
    "sales_order_count": {
        "metric_name": "sales_order_count",
        "business_meaning": "Count of sales documents (VBAK.VBELN)",
        "authoritative_domain": "sales",
        "authoritative_tables": ["VBAK"],
        "required_fields": ["vbeln"],
        "aggregation": "COUNT(DISTINCT VBAK.VBELN)",
        "grain": "sales document header",
        "allowed_dimensions": ["year", "customer", "sales_org"],
        "date_semantics": "VBAK.AUDAT (document date) when populated, else ERDAT",
        "limitations": "Not invoice count. AUART/VBTYP may include non-order sales documents.",
        "join_requirements": [],
        "fan_out_protections": "Do not count VBAP rows as orders.",
        "substitutes_forbidden": ["billing invoice count"],
    },
    "sales_order_value": {
        "metric_name": "sales_order_value",
        "business_meaning": "Sales-order item net value (VBAP.NETWR)",
        "authoritative_domain": "sales",
        "authoritative_tables": ["VBAP", "VBAK"],
        "required_fields": ["netwr"],
        "aggregation": "SUM(VBAP.NETWR)",
        "grain": "sales document item",
        "allowed_dimensions": ["customer", "product", "country", "industry", "year"],
        "date_semantics": "VBAK.AUDAT",
        "limitations": "Not billed revenue. Currency = VBAP.WAERK / VBAK.WAERK when present.",
        "join_requirements": ["VBAK.vbeln = VBAP.vbeln"],
        "fan_out_protections": "Do not join VBEP or VBRP before SUM(NETWR).",
        "substitutes_forbidden": ["VBRP.NETWR"],
    },
    "sales_quantity": {
        "metric_name": "sales_quantity",
        "business_meaning": "Order quantity (VBAP.KWMENG)",
        "authoritative_domain": "sales",
        "authoritative_tables": ["VBAP"],
        "required_fields": ["kwmeng"],
        "aggregation": "SUM(VBAP.KWMENG)",
        "grain": "sales document item",
        "allowed_dimensions": ["product", "customer", "year"],
        "date_semantics": "VBAK.AUDAT",
        "limitations": "Confirmed/target qty fields exist separately (ZMENG).",
        "join_requirements": [],
        "fan_out_protections": "Do not join VBEP before summing KWMENG.",
        "substitutes_forbidden": ["FKIMG"],
    },
    "billing_revenue": {
        "metric_name": "billing_revenue",
        "business_meaning": "Billed net value (VBRP/VBRK NETWR) — R3/R4 frozen definition of unqualified 'sales'",
        "authoritative_domain": "invoice",
        "authoritative_tables": ["vbrp", "VBRK"],
        "required_fields": ["netwr"],
        "aggregation": "SUM(NETWR)",
        "grain": "billing item",
        "allowed_dimensions": ["customer", "product", "country", "industry", "year"],
        "date_semantics": "VBRK.FKDAT",
        "limitations": "This is invoiced value, not sales-order value.",
        "join_requirements": ["VBRK.vbeln = vbrp.vbeln"],
        "fan_out_protections": "Never join EKPO/MBEW/VBFA before SUM(NETWR).",
        "substitutes_forbidden": ["VBAP.NETWR as billed revenue"],
    },
    "invoice_count": {
        "metric_name": "invoice_count",
        "business_meaning": "Count of billing documents",
        "authoritative_domain": "invoice",
        "authoritative_tables": ["VBRK"],
        "required_fields": ["vbeln"],
        "aggregation": "COUNT(DISTINCT VBRK.VBELN)",
        "grain": "billing header",
        "allowed_dimensions": ["year", "customer"],
        "date_semantics": "VBRK.FKDAT",
        "limitations": "Not sales-order count.",
        "join_requirements": [],
        "fan_out_protections": "Do not count vbrp rows as invoices.",
        "substitutes_forbidden": ["VBAK count"],
    },
    "purchase_value": {
        "metric_name": "purchase_value",
        "business_meaning": "PO item net value (EKPO.NETWR)",
        "authoritative_domain": "purchasing",
        "authoritative_tables": ["EKPO", "EKKO"],
        "required_fields": ["netwr"],
        "aggregation": "SUM(EKPO.NETWR)",
        "grain": "purchase-order item",
        "allowed_dimensions": ["vendor", "product", "year"],
        "date_semantics": "EKKO.BEDAT",
        "limitations": "Not invoice COGS.",
        "join_requirements": ["EKKO.ebeln = EKPO.ebeln"],
        "fan_out_protections": "Never join VBRP before SUM.",
        "substitutes_forbidden": ["billing NETWR"],
    },
    "production_quantity": {
        "metric_name": "production_quantity",
        "business_meaning": "Production order total quantity (AFKO.GAMNG) when present",
        "authoritative_domain": "production",
        "authoritative_tables": ["AFKO"],
        "required_fields": ["gamng"],
        "aggregation": "SUM(AFKO.GAMNG)",
        "grain": "production order header",
        "allowed_dimensions": ["product", "year"],
        "date_semantics": "AFKO date fields when populated",
        "limitations": "Not sales quantity. Confirm column population in extract.",
        "join_requirements": [],
        "fan_out_protections": "Do not join AFPO before SUM(GAMNG) unless grain is item.",
        "substitutes_forbidden": ["VBAP.KWMENG"],
    },
    "cogs": {
        "metric_name": "cogs",
        "business_meaning": "Invoice document cost WAVWR (R3/R4 proxy) — not true COGS ledger",
        "authoritative_domain": "cost",
        "authoritative_tables": ["vbrp"],
        "required_fields": ["wavwr"],
        "aggregation": "SUM(WAVWR)",
        "grain": "billing item",
        "allowed_dimensions": ["product", "year"],
        "date_semantics": "VBRK.FKDAT",
        "limitations": "Proxy only. Frozen R3/R4 contract.",
        "join_requirements": [],
        "fan_out_protections": "Same as billing_revenue.",
        "substitutes_forbidden": [],
    },
    "gross_profit": {
        "metric_name": "gross_profit",
        "business_meaning": "Billing NETWR − WAVWR",
        "authoritative_domain": "profit_and_loss",
        "authoritative_tables": ["vbrp"],
        "required_fields": ["netwr", "wavwr"],
        "aggregation": "SUM(NETWR) − SUM(WAVWR)",
        "grain": "billing item",
        "allowed_dimensions": ["product", "customer", "industry"],
        "date_semantics": "VBRK.FKDAT",
        "limitations": "Not net profit. Frozen R3/R4.",
        "join_requirements": [],
        "fan_out_protections": "Same as billing_revenue.",
        "substitutes_forbidden": ["CO-PA unless separately governed"],
    },
    "inventory_quantity": {
        "metric_name": "inventory_quantity",
        "business_meaning": "Current unrestricted or valuated quantity snapshot",
        "authoritative_domain": "product",
        "authoritative_tables": ["MARD", "MBEW"],
        "required_fields": ["labst"],
        "aggregation": "SUM(MARD.LABST) / MBEW.LBKUM",
        "grain": "material snapshot",
        "allowed_dimensions": ["product", "plant"],
        "date_semantics": "current snapshot only",
        "limitations": "No MSEG aging. Frozen R4-3.",
        "join_requirements": [],
        "fan_out_protections": "Never join VBRP before aggregating inventory.",
        "substitutes_forbidden": [],
    },
}

DIMENSIONS: Dict[str, Dict[str, Any]] = {
    "customer": {
        "concept": "customer",
        "sales_order": {"table": "VBAK", "column": "kunnr", "name_table": "KNA1", "name_column": "name1"},
        "invoice": {"table": "VBRK", "column": "kunag", "name_table": "KNA1", "name_column": "name1"},
    },
    "country": {
        "concept": "country",
        "sales_order": {"table": "KNA1", "column": "land1"},
        "invoice": {"table": "KNA1", "column": "land1"},
    },
    "industry": {
        "concept": "industry",
        "sales_order": {"table": "KNA1", "column": "brsch", "text_table": "T016T", "text_column": "brtxt"},
        "invoice": {"table": "KNA1", "column": "brsch", "text_table": "T016T", "text_column": "brtxt"},
    },
    "product": {
        "concept": "product",
        "sales_order": {"table": "VBAP", "column": "matnr", "name_table": "MAKT", "name_column": "maktx"},
        "invoice": {"table": "vbrp", "column": "matnr", "name_table": "MAKT", "name_column": "maktx"},
    },
    "year": {
        "concept": "year",
        "sales_order": {"table": "VBAK", "column": "audat"},
        "invoice": {"table": "VBRK", "column": "fkdat"},
        "purchasing": {"table": "EKKO", "column": "bedat"},
    },
    "vendor": {
        "concept": "vendor",
        "purchasing": {"table": "EKKO", "column": "lifnr", "name_table": "LFA1", "name_column": "name1"},
    },
}


def get_metric(name: str) -> Optional[Dict[str, Any]]:
    return METRICS.get(name)


def available_domains() -> List[str]:
    domains = sorted({e["primary_domain"] for e in TABLE_ENTRIES.values() if e.get("table")})
    return domains
