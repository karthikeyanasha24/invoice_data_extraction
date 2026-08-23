"""
Governed business semantic layer for multi-dimensional GA Chat analysis.

Built ONLY from relationships verified in schema_full / schema_ai_config / sql_catalog.
Does not invent joins or metrics. Unsupported requests must surface as data gaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class EntityDef:
    name: str
    domain: str
    grain: str
    tables: tuple
    business_keys: tuple
    dimensions: tuple
    measures: tuple
    date_fields: tuple
    notes: str = ""


@dataclass(frozen=True)
class RelationshipEdge:
    source: str
    source_field: str
    target: str
    target_field: str
    relationship_type: str
    cardinality: str
    confidence: str  # high | medium | low
    business_meaning: str
    on_sql: str
    unsafe_notes: str = ""


@dataclass(frozen=True)
class MetricDef:
    name: str
    description: str
    aliases: tuple
    status: str  # supported | partial | unavailable
    formula_sql: str
    base_tables: tuple
    grain: str
    currency_field: Optional[str]
    time_field: Optional[str]
    default_dimensions: tuple
    caveats: str = ""
    substitutes_forbidden: tuple = ()


# ── Entities (real SAP objects present in schema_full) ───────────────────────

ENTITIES: Dict[str, EntityDef] = {
    "billing_header": EntityDef(
        name="billing_header",
        domain="sales_billing",
        grain="one row per billing document (VBELN)",
        tables=("VBRK",),
        business_keys=("VBELN",),
        dimensions=("KUNAG", "LAND1", "WAERK", "VKORG", "VTWEG", "SPART", "FKDAT"),
        measures=("NETWR",),
        date_fields=("FKDAT",),
        notes="Billing is the commercial consequence of the sell process.",
    ),
    "billing_item": EntityDef(
        name="billing_item",
        domain="sales_billing",
        grain="one row per billing item (VBELN+POSNR)",
        tables=("vbrp",),
        business_keys=("VBELN", "POSNR"),
        dimensions=("MATNR", "ARKTX", "PRCTR", "WERKS"),
        measures=("NETWR", "FKIMG", "WAVWR"),
        date_fields=(),
        notes="Line net value NETWR; document cost WAVWR used as invoice-level COGS proxy.",
    ),
    "customer": EntityDef(
        name="customer",
        domain="master_data",
        grain="one row per customer (KUNNR)",
        tables=("KNA1",),
        business_keys=("KUNNR",),
        dimensions=("NAME1", "LAND1", "BRSCH", "ORT01", "REGIO"),
        measures=(),
        date_fields=(),
        notes="Industry via BRSCH; country via LAND1. REGIO exists but has limited BI templates.",
    ),
    "industry": EntityDef(
        name="industry",
        domain="master_data",
        grain="industry key text",
        tables=("T016T",),
        business_keys=("BRSCH",),
        dimensions=("BRTXT",),
        measures=(),
        date_fields=(),
    ),
    "product": EntityDef(
        name="product",
        domain="master_data",
        grain="one row per material (MATNR)",
        tables=("MARA", "MAKT"),
        business_keys=("MATNR",),
        dimensions=("MTART", "MATKL", "MEINS", "MAKTX", "MHDHB", "MHDRZ", "SLED_BBD"),
        measures=(),
        date_fields=(),
        notes="Shelf-life fields exist on MARA; operational expiry BI is partial.",
    ),
    "sales_order": EntityDef(
        name="sales_order",
        domain="order_to_cash",
        grain="order header",
        tables=("VBAK", "VBAP"),
        business_keys=("VBELN",),
        dimensions=("KUNNR", "AUART", "VKORG"),
        measures=("NETWR", "KWMENG"),
        date_fields=("ERDAT", "AUDAT"),
    ),
    "delivery": EntityDef(
        name="delivery",
        domain="order_to_cash",
        grain="delivery header / item",
        tables=("LIKP", "LIPS"),
        business_keys=("VBELN",),
        dimensions=("KUNNR", "MATNR", "VFDAT"),
        measures=("LFIMG", "NETWR", "WAVWR"),
        date_fields=("LFDAT", "ERDAT", "VFDAT"),
        notes="LIPS.VFDAT is batch/shelf-life related when populated.",
    ),
    "purchase": EntityDef(
        name="purchase",
        domain="procure_to_pay",
        grain="PO header / item",
        tables=("EKKO", "EKPO", "LFA1"),
        business_keys=("EBELN", "EBELP"),
        dimensions=("LIFNR", "MATNR", "WERKS"),
        measures=("MENGE", "NETPR", "NETWR"),
        date_fields=("BEDAT",),
    ),
    "inventory": EntityDef(
        name="inventory",
        domain="inventory",
        grain="material / plant / storage location",
        tables=("MBEW", "MARD"),
        business_keys=("MATNR", "BWKEY", "WERKS", "LGORT"),
        dimensions=("WERKS", "LGORT"),
        measures=("SALK3", "LBKUM", "LABST", "STPRS", "VERPR"),
        date_fields=(),
    ),
    "document_flow": EntityDef(
        name="document_flow",
        domain="process",
        grain="preceding→subsequent document link",
        tables=("VBFA",),
        business_keys=("VBELV", "POSNV", "VBELN", "POSNN"),
        dimensions=("VBTYP_V", "VBTYP_N"),
        measures=("RFMNG", "RFWRT"),
        date_fields=("ERDAT",),
        notes="Links order → delivery → billing where flow documents exist.",
    ),
}


# ── Approved relationships (from schema_ai_config join_rules + catalog) ──────

RELATIONSHIPS: List[RelationshipEdge] = [
    RelationshipEdge(
        "billing_item", "VBELN", "billing_header", "VBELN",
        "ITEM_OF", "N:1", "high",
        "Billing line belongs to billing document",
        'TRIM(v.vbeln) = TRIM(vk.vbeln)',
    ),
    RelationshipEdge(
        "billing_header", "KUNAG", "customer", "KUNNR",
        "SOLD_TO", "N:1", "high",
        "Billing sold-to customer",
        'TRIM(vk.kunag) = TRIM(k.kunnr)',
    ),
    RelationshipEdge(
        "customer", "BRSCH", "industry", "BRSCH",
        "HAS_INDUSTRY", "N:1", "high",
        "Customer industry classification",
        'TRIM(k.brsch) = TRIM(t.brsch)',
    ),
    RelationshipEdge(
        "billing_item", "MATNR", "product", "MATNR",
        "PRODUCT_SOLD", "N:1", "high",
        "Billing line material",
        "TRIM(v.matnr) = TRIM(m.matnr)",
    ),
    RelationshipEdge(
        "sales_order", "VBELN", "sales_order_item", "VBELN",
        "ORDER_ITEM", "1:N", "high",
        "Sales order header to item",
        'TRIM(vbak.vbeln) = TRIM(vbap.vbeln)',
    ),
    RelationshipEdge(
        "delivery", "VBELN", "delivery_item", "VBELN",
        "DELIVERY_ITEM", "1:N", "high",
        "Delivery header to item",
        'TRIM(likp.vbeln) = TRIM(lips.vbeln)',
    ),
    RelationshipEdge(
        "purchase", "EBELN", "purchase_item", "EBELN",
        "PO_ITEM", "1:N", "high",
        "Purchase order header to item",
        'TRIM(ekko.ebeln) = TRIM(ekpo.ebeln)',
    ),
    RelationshipEdge(
        "document_flow", "VBELV/VBELN", "process_chain", "VBELN",
        "PROCESS_FLOW", "N:N", "medium",
        "SAP document flow linking order/delivery/billing",
        "VBFA links preceding and subsequent documents",
        unsafe_notes="Do not join unrelated docs on VBELN alone without VBFA.",
    ),
    RelationshipEdge(
        "billing_item", "MATNR", "purchase_item", "MATNR",
        "MATERIAL_BRIDGE", "N:N", "low",
        "Material-only bridge between sales and purchase (not document-level)",
        "TRIM(v.matnr) = TRIM(ekpo.matnr)",
        unsafe_notes="Cross-domain matnr bridge can misattribute costs; prefer WAVWR for invoice COGS.",
    ),
]


# ── Governed metrics ─────────────────────────────────────────────────────────

METRICS: Dict[str, MetricDef] = {
    "revenue": MetricDef(
        name="revenue",
        description="Net billing line revenue (not equated to profit)",
        aliases=("revenue", "sales", "net sales", "billed amount", "invoice value"),
        status="supported",
        formula_sql="SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC))",
        base_tables=("vbrp", "VBRK"),
        grain="billing_item",
        currency_field="vk.waerk",
        time_field="vk.fkdat",
        default_dimensions=("product", "customer", "year"),
        caveats="Invoice net value. Do not call this profit.",
        substitutes_forbidden=("profit", "margin", "cogs", "net profit"),
    ),
    "cogs": MetricDef(
        name="cogs",
        description="Document cost from billing item WAVWR (invoice-level COGS proxy)",
        aliases=("cogs", "cost of goods", "cost of goods sold", "cost of goods sold (cogs)", "goods cost", "product cost"),
        status="supported",
        formula_sql="SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC))",
        base_tables=("vbrp", "VBRK"),
        grain="billing_item",
        currency_field="vk.waerk",
        time_field="vk.fkdat",
        default_dimensions=("product", "year"),
        caveats=(
            "Uses vbrp.wavwr (cost in document currency). "
            "This is NOT Universal Journal ACDOCA COGS (ACDOCA not in live schema_full). "
            "Not operating cost / logistics cost."
        ),
        substitutes_forbidden=("net profit", "logistics cost", "opex"),
    ),
    "gross_profit": MetricDef(
        name="gross_profit",
        description="Revenue minus invoice document cost (WAVWR)",
        aliases=("gross profit", "profit", "highest profit", "lowest profit", "profitability"),
        status="supported",
        formula_sql=(
            "SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) "
            "- SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC))"
        ),
        base_tables=("vbrp", "VBRK"),
        grain="billing_item",
        currency_field="vk.waerk",
        time_field="vk.fkdat",
        default_dimensions=("product", "customer", "year"),
        caveats=(
            "Gross profit proxy = NETWR - WAVWR at billing grain. "
            "Not true net profit (no opex allocation)."
        ),
        substitutes_forbidden=("net profit",),
    ),
    "gross_margin_pct": MetricDef(
        name="gross_margin_pct",
        description="Gross profit / revenue * 100",
        aliases=("margin", "margins", "gross margin", "margin %", "lowest margins", "highest margins"),
        status="supported",
        formula_sql=(
            "CASE WHEN SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) > 0 THEN "
            "ROUND(100.0 * (SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) "
            "- SUM(CAST(NULLIF(TRIM(COALESCE(v.wavwr, '0')), '') AS NUMERIC))) "
            "/ SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)), 2) ELSE NULL END"
        ),
        base_tables=("vbrp", "VBRK"),
        grain="billing_item",
        currency_field="vk.waerk",
        time_field="vk.fkdat",
        default_dimensions=("product", "year"),
        caveats="Depends on WAVWR population quality.",
    ),
    "invoice_count": MetricDef(
        name="invoice_count",
        description="Distinct billing documents",
        aliases=("invoice count", "number of invoices", "billing documents"),
        status="supported",
        formula_sql="COUNT(DISTINCT vk.vbeln)",
        base_tables=("VBRK",),
        grain="billing_header",
        currency_field=None,
        time_field="vk.fkdat",
        default_dimensions=("customer", "year"),
    ),
    "quantity": MetricDef(
        name="quantity",
        description="Billed quantity",
        aliases=("quantity", "qty", "volume"),
        status="supported",
        formula_sql="SUM(CAST(NULLIF(TRIM(v.fkimg), '') AS NUMERIC))",
        base_tables=("vbrp",),
        grain="billing_item",
        currency_field=None,
        time_field="vk.fkdat",
        default_dimensions=("product",),
    ),
    "net_profit": MetricDef(
        name="net_profit",
        description="True net profit after operating costs",
        aliases=("net profit", "bottom line", "ebit"),
        status="unavailable",
        formula_sql="",
        base_tables=(),
        grain="",
        currency_field=None,
        time_field=None,
        default_dimensions=(),
        caveats="Operating-cost allocation to product is not linked in live schema_full.",
    ),
    "logistics_cost": MetricDef(
        name="logistics_cost",
        description="Logistics / freight cost",
        aliases=("logistics cost", "freight cost", "shipping cost"),
        status="unavailable",
        formula_sql="",
        base_tables=(),
        grain="",
        currency_field=None,
        time_field=None,
        default_dimensions=(),
        caveats="Delivery headers exist (LIKP/LIPS) but no reliable logistics-cost amount linkage in catalog.",
    ),
    "product_expiry": MetricDef(
        name="product_expiry",
        description="Products expiring / shelf life",
        aliases=("expiring", "expiry", "expired products", "shelf life"),
        status="partial",
        formula_sql="",
        base_tables=("MARA", "LIPS"),
        grain="material/batch",
        currency_field=None,
        time_field="LIPS.VFDAT",
        default_dimensions=("product", "industry"),
        caveats=(
            "MARA shelf-life fields and LIPS.VFDAT exist, but no certified expiry BI template. "
            "Partial support via best-effort queries only."
        ),
    ),
}


DIMENSION_ALIASES: Dict[str, str] = {
    "product": "product",
    "products": "product",
    "material": "product",
    "materials": "product",
    "customer": "customer",
    "customers": "customer",
    "industry": "industry",
    "industries": "industry",
    "region": "country",
    "regions": "country",
    "country": "country",
    "countries": "country",
    "year": "year",
    "years": "year",
    "month": "month",
    "currency": "currency",
}


def resolve_metric(term: str) -> Optional[MetricDef]:
    t = (term or "").strip().lower()
    if not t:
        return None
    key = t.replace(" ", "_")
    if key in METRICS:
        return METRICS[key]
    if t in METRICS:
        return METRICS[t]
    # Exact alias match first (avoid "net profit" matching gross "profit")
    for m in METRICS.values():
        if t == m.name or t in m.aliases:
            return m
    # Phrase containment only for longer aliases (>= 5 chars)
    for m in METRICS.values():
        for a in m.aliases:
            if len(a) >= 5 and (a in t or t in a):
                return m
    return None


def metric_status(name: str) -> str:
    m = METRICS.get(name) or resolve_metric(name)
    return m.status if m else "unavailable"


def available_drilldowns(active_dimensions: Set[str], metrics: Set[str]) -> List[Dict[str, str]]:
    """Suggest next dimensions that are actually supported."""
    catalog = [
        ("customer", "Customer contribution for the current product/revenue set"),
        ("industry", "Industry breakdown via customer BRSCH"),
        ("country", "Country / region (LAND1) breakdown"),
        ("year", "Year comparison / trend"),
        ("product", "Product breakdown"),
        ("cogs", "Invoice document cost (WAVWR) components"),
        ("gross_margin_pct", "Gross margin %"),
        ("process_sell", "Order → delivery → billing process links"),
        ("process_buy", "Purchase order / vendor process for materials"),
    ]
    out: List[Dict[str, str]] = []
    for key, label in catalog:
        if key in active_dimensions or key in metrics:
            continue
        if key in {"cogs", "gross_margin_pct"} and metric_status(key if key != "gross_margin_pct" else "gross_margin_pct") == "unavailable":
            continue
        if key == "process_buy" and "purchase" not in ENTITIES:
            continue
        out.append({"id": key, "label": label})
    return out[:8]


def relationship_summary() -> List[Dict[str, Any]]:
    return [
        {
            "source": e.source,
            "target": e.target,
            "on": f"{e.source_field}→{e.target_field}",
            "type": e.relationship_type,
            "cardinality": e.cardinality,
            "confidence": e.confidence,
            "meaning": e.business_meaning,
            "unsafe": e.unsafe_notes,
        }
        for e in RELATIONSHIPS
    ]


def data_gap_payload(
    requested: str,
    reason: str,
    can_answer: Optional[List[str]] = None,
    prior_analytical_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    qp: Dict[str, Any] = {"deep_analysis": True, "data_gap": True}
    if prior_analytical_context:
        # Preserve prior selection so a data-gap turn does not wipe the chain.
        qp["analytical_context"] = {
            **prior_analytical_context,
            "deep_analysis": True,
            "last_data_gap": reason,
        }
    return {
        "type": "cannot_answer",
        "answer_status": "CANNOT_ANSWER",
        "sql": "",
        "data": [],
        "rowCount": 0,
        "charts": [],
        "query_plan": qp,
        "summary": (
            f"I cannot accurately answer «{requested}» with the currently linked datasets.\n\n"
            f"**Why:** {reason}\n\n"
            + (
                "**What I can answer instead:**\n"
                + "\n".join(f"- {x}" for x in (can_answer or []))
                if can_answer
                else ""
            )
        ),
        "keyFindings": [
            "Data gap — refusing to invent unsupported metrics or joins.",
            reason,
        ],
        "meta": {
            "deep_analysis": True,
            "data_gap": True,
            "requested": requested,
            "reason": reason,
            "can_answer": can_answer or [],
        },
        "pipeline": "deep_multidim",
        "sql_generation_method": "deep_multidim_data_gap",
        "llm_calls": 0,
    }
