"""
analyst_pipeline.py
===================
Multi-Stage AI Analyst Pipeline — complete re-architecture.

Stages:
  1.  Intent Understanding  — extract domain, metrics, dimensions, time, viz hint
  2.  Domain Classification — map question to a business domain
  3.  Schema Category       — pick category bucket(s) from the catalog
  4.  Table Selection       — load only relevant tables (not the whole schema)
  5.  Column Discovery      — load columns only for selected tables
  6.  Column Ranking        — score columns by relevance, drop noise
  7.  Relationship Graph    — graph-based join path, never hallucinate FKs
  8.  SQL Generation        — dialect-aware, production-grade SQL
  9.  SQL Validation        — verify tables/columns/joins exist before execution
  10. Smart Execution       — adaptive strategy: full / paginated / aggregated / KPI-only
  11. Result Summarization  — AI analyst pass: patterns, anomalies, trends, KPIs
  12. Visualization Engine  — auto-select best chart type(s) per data shape
  13. Multi-Viz Output      — produce multiple chart configs from one result
  14. Dashboard Assembly    — merge KPI cards + charts + table + insights
  15. Adaptive Learning     — log query for semantic memory (best-effort)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("zodiac-api.analyst-pipeline")


# ─── LLM client ──────────────────────────────────────────────────────────────

def _get_openai_client():
    from openai import OpenAI
    from ..config.config import OPENAI_API_KEY
    return OpenAI(api_key=OPENAI_API_KEY)


def _chat(messages: list, model: str = "gpt-4o", temperature: float = 0.0,
          max_tokens: int = 2000, json_mode: bool = False) -> str:
    client = _get_openai_client()
    kwargs: Dict[str, Any] = dict(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


# ─── Domain / Category catalog ───────────────────────────────────────────────

DOMAIN_TABLE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "sales_billing": {
        "description": "Sales orders, billing documents, revenue, invoices, customers",
        "tables": ["VBRK", "vbrp", "VBAK", "VBAP", "VBEP", "VBFA", "KONV", "MVKE",
                   "KNA1", "KNVV", "KNVP"],
    },
    "delivery_logistics": {
        "description": "Deliveries, shipments, logistics, stock transfers",
        "tables": ["LIKP", "LIPS", "LSEG"],
    },
    "purchasing_procurement": {
        "description": "Purchase orders, vendors, procurement, goods receipt, invoices",
        "tables": ["EKKO", "EKPO", "EBAN", "EINA", "EINE", "RBKP", "RSEG", "RESB",
                   "LFA1", "LFB1", "LFM1"],
    },
    "inventory_material": {
        "description": "Materials, stock levels, warehouses, BOM, batches",
        "tables": ["MARA", "MARC", "MARD", "MAKT", "MARM", "MBEW", "MBEWH", "MCHB",
                   "MEAN", "MKPF", "MLAN", "MSLB", "STKO", "STPO", "CABN", "AUSP", "KLAH"],
    },
    "finance_fi": {
        "description": "Accounting documents, GL postings, FI, payments, open items",
        "tables": ["BKPF", "BSEG", "BSAD", "FAGLFLEXA", "DFKKOP", "T016T"],
    },
    "controlling_co": {
        "description": "Cost centers, profit centers, internal orders, CO postings",
        "tables": ["COEP", "COSP", "COSS", "CEPC", "CSKS", "CSKT", "CRHD",
                   "AUFK", "AFKO", "AFPO"],
    },
    "costing_copc": {
        "description": "Product costing, cost estimates, material ledger",
        "tables": ["CKIS", "CKHS", "CKIT", "KEKO", "KEPH", "CKMLCR", "CKMLHD",
                   "CKMLPP", "CKMLPR", "TCKH1", "TCKH2"],
    },
    "copa": {
        "description": "CO-PA profitability analysis, segment reporting",
        "tables": ["CE1BGIS", "CE1IDEA", "CE1INT1", "CE1PR22", "CE1R300",
                   "CE1S_AL", "CE1S_CP", "CE1S_GO", "CE2BGIS", "CE2IDEA",
                   "CE2S_AL", "CE2S_CP", "CS2S_GO"],
    },
    "sat_inbound": {
        "description": "SAT CFDI inbound documents, Mexican e-invoices, certificates",
        "tables": ["sat_documents", "sat_canonical_merged", "sat_company_mappings",
                   "sat_duplicate_checks", "sat_processing_logs", "sat_sap_account_mapping",
                   "sat_simple_merged", "sat_supplier_account_mapping",
                   "certificate_renewal_requests", "certificate_revocation_list",
                   "customer_certificates", "customer_delivery_settings",
                   "customer_receiver_rfc", "customer_tokens", "supplier_tokens",
                   "user_customers"],
    },
    "zodiac_edi": {
        "description": "Zodiac EDI conversions, outbound invoices, failed success EDI, invoice business data, supplier amounts",
        "tables": ["invoice_business_data", "invoice_v2_business_data",
                   "zodiac_invoice_failed_edi", "zodiac_invoice_success_edi", "zodiac_customers",
                   "converted_invoices", "customers", "invoice_v2_correction_cache",
                   "invoice_v2_documents", "invoice_v2_validated", "v2_correction_cache",
                   "v2_invoice_documents", "v2_validated_invoices", "zodiac_users",
                   "ai_analysis_memory", "ai_query_embeddings", "ai_query_memory",
                   "ai_training_data", "correction_cache"],
    },
}

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "sales_billing":         ["sales", "billing", "revenue", "customer", "sales order",
                               "vbrk", "vbak", "amount", "sold", "selling", "top customer",
                               "sap invoice", "sap billing"],
    "delivery_logistics":    ["delivery", "shipment", "logistics", "ship", "dispatch", "likp"],
    "purchasing_procurement":["purchase order", "vendor invoice", "procurement", "po ", "goods receipt",
                               "ekko", "ekpo", "rbkp", "rseg", "buying", "spend", "payable",
                               "vendor master", "lfa1"],
    "inventory_material":    ["material", "stock", "inventory", "warehouse", "batch", "mara",
                               "marc", "mard", "bom", "component"],
    "finance_fi":            ["gl", "accounting", "finance", "open item", "bkpf",
                               "bseg", "ledger", "posting", "fiscal", "tax", "balance"],
    "controlling_co":        ["cost center", "profit center", "controlling", "internal order",
                               "coep", "csks", "cepc", "overhead"],
    "costing_copc":          ["costing", "cost estimate", "product cost", "ckis", "keko",
                               "material ledger", "standard cost"],
    "copa":                  ["copa", "profitability", "segment", "ce1", "ce2", "contribution"],
    "sat_inbound":           ["sat", "cfdi", "inbound sat", "inbound document", "sat document",
                               "mexico", "canonical", "supplier token", "certificate",
                               "sat_documents", "rfc", "emisor", "receptor",
                               "inbound vs outbound", "sat vs"],
    "zodiac_edi":            ["edi", "zodiac", "failed invoice", "outbound invoice", "outbound",
                               "converted invoice", "zodiac_invoice", "v2 invoice",
                               "invoice conversion", "inbound vs outbound", "vs outbound",
                               "bridge edi", "failed edi", "success edi",
                               "supplier invoice", "invoice amount", "invoice total",
                               "failure reason", "failed at", "invoice failure",
                               "highest invoice", "total invoice"],
}

# SAP-specific override terms — if any of these are present, prioritise SAP domains
_SAP_OVERRIDE_TERMS = [
    "sales order", "billing document", "purchase order", "goods receipt",
    "cost center", "profit center", "gl posting", "open item",
    "vbrk", "vbak", "bkpf", "ekko", "ekpo", "rbkp", "rseg", "lfa1",
    "vbeln", "matnr", "kunnr", "lifnr", "mandt", "bukrs",
]

def _detect_app_domains(question: str) -> List[str]:
    """
    Detect if question is clearly about Zodiac/SAT app tables (not raw SAP).
    Returns list of app domain keys that should get the +20 boost.
    If SAP-specific terms are detected, return empty so SAP domains win via keyword scoring.
    """
    q = question.lower()

    # Hard-exit: if the question contains explicit SAP structural terms, don't boost app domains
    if any(term in q for term in _SAP_OVERRIDE_TERMS):
        return []

    app_domains: List[str] = []

    sat_signals = [
        "sat", "cfdi", "inbound sat", "sat document", "canonical",
        "rfc", "emisor", "receptor", "folio", "serie", "moneda",
    ]
    zodiac_signals = [
        "edi", "zodiac", "outbound", "converted invoice", "failed invoice",
        "v2 invoice", "bridge", "invoice conversion", "success edi", "failed edi",
        "invoice failure", "failure reason", "invoice amount", "invoice total",
        "supplier invoice", "highest invoice", "invoice business",
    ]
    # "supplier" + invoice context → zodiac (not SAP RBKP)
    supplier_invoice = "supplier" in q and any(
        w in q for w in ["invoice", "amount", "total", "document", "count"]
    ) and not any(t in q for t in _SAP_OVERRIDE_TERMS)

    # "customer" + revenue/amount context → zodiac (use invoice_v2_business_data, not empty VBRK)
    customer_revenue = "customer" in q and any(
        w in q for w in ["revenue", "amount", "total", "top", "highest", "sales"]
    ) and "sales order" not in q and "billing document" not in q

    if any(s in q for s in sat_signals):
        app_domains.append("sat_inbound")
    if any(s in q for s in zodiac_signals) or supplier_invoice or customer_revenue:
        app_domains.append("zodiac_edi")
    return app_domains

# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class IntentObject:
    raw_question: str = ""
    domain: str = ""
    intent: str = ""
    metrics: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    time_range: str = ""
    visualization: str = "auto"
    categories: List[str] = field(default_factory=list)
    selected_tables: List[str] = field(default_factory=list)
    selected_columns: Dict[str, List[str]] = field(default_factory=dict)
    sql: str = ""
    sql_strategy: str = "full"
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    total_rows_in_db: int = -1
    summary: str = ""
    key_findings: List[str] = field(default_factory=list)
    charts: List[Dict[str, Any]] = field(default_factory=list)
    kpis: List[Dict[str, Any]] = field(default_factory=list)
    pipeline_ms: int = 0
    warnings: List[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Intent Understanding
# ══════════════════════════════════════════════════════════════════════════════

def stage1_intent(question: str) -> IntentObject:
    prompt = (
        'You are a business data analyst. Analyze this question and extract structured intent.\n\n'
        f'Question: "{question}"\n\n'
        'Return ONLY valid JSON (no markdown fences):\n'
        '{\n'
        '  "domain": "<sales|procurement|inventory|finance|controlling|costing|copa|sat|edi|general>",\n'
        '  "intent": "<ranking|trend|count|detail|comparison|kpi|distribution|correlation>",\n'
        '  "metrics": ["<measure or concept>"],\n'
        '  "dimensions": ["<grouping or concept>"],\n'
        '  "time_range": "<last_week|last_month|last_quarter|last_year|ytd|all_time|none>",\n'
        '  "visualization": "<bar|line|pie|table|kpi|combo|auto>"\n'
        '}'
    )
    try:
        raw = _chat([{"role": "user", "content": prompt}], json_mode=True,
                    model="gpt-4o-mini", max_tokens=500)
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning("Stage1 parse failed: %s", e)
        parsed = {}

    obj = IntentObject(raw_question=question)
    obj.domain        = str(parsed.get("domain", "general"))
    obj.intent        = str(parsed.get("intent", "detail"))
    obj.metrics       = list(parsed.get("metrics") or [])
    obj.dimensions    = list(parsed.get("dimensions") or [])
    obj.time_range    = str(parsed.get("time_range", "none"))
    obj.visualization = str(parsed.get("visualization", "auto"))
    return obj


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Domain Classification
# ══════════════════════════════════════════════════════════════════════════════

def stage2_domain(intent: IntentObject) -> IntentObject:
    q_lower = intent.raw_question.lower()
    scores: Dict[str, int] = {d: 0 for d in DOMAIN_KEYWORDS}

    # Check for explicit app-domain signals first (SAT / Zodiac EDI)
    app_hits = _detect_app_domains(intent.raw_question)
    for d in app_hits:
        scores[d] += 20   # strong boost — these are real app tables

    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                scores[domain] += 2
        if intent.domain and intent.domain in domain:
            scores[domain] += 5

    # If both sat_inbound AND zodiac_edi detected, keep both
    if scores.get("sat_inbound", 0) >= 20 and scores.get("zodiac_edi", 0) >= 20:
        intent.domain = "sat_inbound"   # primary; zodiac_edi added in stage3
    else:
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        top = [d for d, s in ranked[:2] if s > 0]
        if not top:
            top = ["zodiac_edi", "sat_inbound"]
        intent.domain = top[0]
    return intent


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — Schema Category Discovery
# ══════════════════════════════════════════════════════════════════════════════

def stage3_category(intent: IntentObject) -> IntentObject:
    q_lower = intent.raw_question.lower()

    # Always start from explicit app-domain detection
    hits: List[str] = list(dict.fromkeys(_detect_app_domains(intent.raw_question)))

    for cat_key, cat_info in DOMAIN_TABLE_CATEGORIES.items():
        if cat_key in hits:
            continue
        desc = cat_info["description"].lower()
        # 1. domain string match (e.g. intent.domain="sales" matches "sales_billing")
        if intent.domain and intent.domain.replace("_", " ") in cat_key.replace("_", " "):
            hits.append(cat_key)
        # 2. explicit SAP table name token in question (e.g. "vbrk", "ekko")
        elif any(
            re.search(r'\b' + re.escape(t.lower()) + r'\b', q_lower)
            for t in cat_info["tables"]
            if len(t) >= 4 and t.upper() == t  # only uppercase (SAP) table names
        ):
            hits.append(cat_key)
        # 3. lowercase app table names (exact word boundary match to avoid "customers" false-hits)
        elif any(
            re.search(r'\b' + re.escape(t.lower()) + r'\b', q_lower)
            for t in cat_info["tables"]
            if t.lower() == t  # only lowercase (app) table names
        ):
            hits.append(cat_key)
        # 4. description keyword match (words >4 chars from category description)
        elif any(word in q_lower for word in desc.split() if len(word) > 5):
            hits.append(cat_key)

    if not hits:
        hits = ["zodiac_edi", "sat_inbound"]
    intent.categories = hits[:3]
    return intent


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — Intelligent Table Selection
# ══════════════════════════════════════════════════════════════════════════════

def stage4_tables(intent: IntentObject, schema_map: Dict[str, List[str]]) -> IntentObject:
    candidates: List[str] = []
    for cat in intent.categories:
        for t in DOMAIN_TABLE_CATEGORIES.get(cat, {}).get("tables", []):
            if t in schema_map and t not in candidates:
                candidates.append(t)
    if not candidates:
        q_lower = intent.raw_question.lower()
        scored = []
        for tname, cols in schema_map.items():
            score = sum(
                10 if tok in tname.lower() else
                sum(2 for col in cols[:30] if len(tok) >= 4 and tok in col.lower())
                for tok in re.findall(r'\w+', q_lower) if len(tok) >= 3
            )
            if score > 0:
                scored.append((score, tname))
        scored.sort(key=lambda x: -x[0])
        candidates = [t for _, t in scored[:25]]

    index_lines = [
        f"{t}: {', '.join(schema_map.get(t, [])[:15])}"
        for t in candidates[:40]
    ]
    prompt = (
        f'Identify tables needed to answer: "{intent.raw_question}"\n\n'
        'Available tables:\n' + '\n'.join(index_lines) +
        '\n\nReturn ONLY a JSON array of table names. No explanation.'
    )
    try:
        raw = _chat([{"role": "user", "content": prompt}], model="gpt-4o-mini",
                    max_tokens=300)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        selected = json.loads(raw)
        if not isinstance(selected, list):
            raise ValueError("not a list")
        selected = [t for t in selected if t in schema_map][:12]
    except Exception as e:
        logger.warning("Stage4 LLM failed: %s — using keyword fallback", e)
        selected = candidates[:10]
    intent.selected_tables = selected if selected else candidates[:8]
    return intent


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5+6 — Column Discovery & Ranking
# ══════════════════════════════════════════════════════════════════════════════

_NOISE_COLS = frozenset({
    "mandt", "created_by", "createdon", "changed_by", "changedon",
    "ernam", "aenam", "erdat", "aedat", "lastchanged", "modified_at",
    "internal_code", "lock_ind", "del_ind", "loekz"
})
_JOIN_KEYS = frozenset({
    "vbeln", "posnr", "matnr", "kunnr", "lifnr", "bukrs",
    "belnr", "gjahr", "poper", "ebeln", "ebelp", "mandt"
})
_VALUE_KEYS = frozenset({
    "netwr", "dmbtr", "wrbtr", "amount", "value",
    "waerk", "waers", "qty", "menge", "betrag"
})

def stage5_columns(intent: IntentObject, schema_map: Dict[str, List[str]]) -> IntentObject:
    for t in intent.selected_tables:
        intent.selected_columns[t] = schema_map.get(t, [])
    return intent


def stage6_rank_columns(intent: IntentObject) -> IntentObject:
    q_lower = intent.raw_question.lower()
    q_tokens = set(re.findall(r'\w{3,}', q_lower))
    for m in intent.metrics + intent.dimensions:
        q_tokens.update(re.findall(r'\w{3,}', m.lower()))

    ranked: Dict[str, List[str]] = {}
    for table, cols in intent.selected_columns.items():
        scored = []
        for col in cols:
            cl = col.lower()
            if cl in _NOISE_COLS:
                continue
            score = 0
            if cl in q_tokens:
                score += 100
            for tok in q_tokens:
                if tok in cl:
                    score += 20
            if cl in _JOIN_KEYS:
                score += 10
            if any(x in cl for x in _VALUE_KEYS):
                score += 15
            scored.append((score, col))
        scored.sort(key=lambda x: (-x[0], x[1].lower()))
        ranked[table] = [col for _, col in scored[:40]]
    intent.selected_columns = ranked
    return intent


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 7 — Relationship Graph
# ══════════════════════════════════════════════════════════════════════════════

_STATIC_EDGES: List[Tuple[str, str, str]] = [
    ("VBRK",  "vbrp",  "VBRK.vbeln = vbrp.vbeln AND VBRK.mandt = vbrp.mandt"),
    ("VBRK",  "KNA1",  "VBRK.kunag = KNA1.kunnr AND VBRK.mandt = KNA1.mandt"),
    ("vbrp",  "MAKT",  "vbrp.matnr = MAKT.matnr AND MAKT.spras = 'E'"),
    ("VBAK",  "VBAP",  "VBAK.vbeln = VBAP.vbeln AND VBAK.mandt = VBAP.mandt"),
    ("VBAK",  "KNA1",  "VBAK.kunnr = KNA1.kunnr AND VBAK.mandt = KNA1.mandt"),
    ("VBAP",  "MAKT",  "VBAP.matnr = MAKT.matnr AND MAKT.spras = 'E'"),
    ("LIKP",  "LIPS",  "LIKP.vbeln = LIPS.vbeln AND LIKP.mandt = LIPS.mandt"),
    ("EKKO",  "EKPO",  "EKKO.ebeln = EKPO.ebeln AND EKKO.mandt = EKPO.mandt"),
    ("EKKO",  "LFA1",  "EKKO.lifnr = LFA1.lifnr AND EKKO.mandt = LFA1.mandt"),
    ("RBKP",  "RSEG",  "RBKP.belnr = RSEG.belnr AND RBKP.gjahr = RSEG.gjahr AND RBKP.mandt = RSEG.mandt"),
    ("BKPF",  "BSEG",  "BKPF.belnr = BSEG.belnr AND BKPF.gjahr = BSEG.gjahr AND BKPF.bukrs = BSEG.bukrs"),
    ("BSEG",  "FAGLFLEXA", "BSEG.belnr = FAGLFLEXA.belnr AND BSEG.gjahr = FAGLFLEXA.gjahr"),
    ("COEP",  "CSKS",  "COEP.kostl = CSKS.kostl AND COEP.kokrs = CSKS.kokrs"),
    ("COEP",  "CEPC",  "COEP.prctr = CEPC.prctr AND COEP.kokrs = CEPC.kokrs"),
    ("sat_documents", "sat_canonical_merged", "sat_documents.uuid = sat_canonical_merged.uuid"),
    ("sat_documents", "sat_simple_merged",    "sat_documents.uuid = sat_simple_merged.uuid"),
    ("zodiac_invoice_failed_edi",  "zodiac_customers",     "zodiac_invoice_failed_edi.customer_id = zodiac_customers.id"),
    ("zodiac_invoice_success_edi", "zodiac_customers",     "zodiac_invoice_success_edi.customer_id = zodiac_customers.id"),
    ("invoice_v2_documents",       "customers",            "invoice_v2_documents.customer_id = customers.id"),
    ("invoice_v2_validated",       "invoice_v2_documents", "invoice_v2_validated.document_id = invoice_v2_documents.id"),
    ("converted_invoices",         "customers",            "converted_invoices.customer_id = customers.id"),
]

def stage7_relationship_graph(intent: IntentObject) -> Dict[str, str]:
    tables_lower = {t.lower() for t in intent.selected_tables}
    joins: Dict[str, str] = {}
    for left, right, on in _STATIC_EDGES:
        if left.lower() in tables_lower and right.lower() in tables_lower:
            key = f"{left}--{right}"
            if key not in joins:
                joins[key] = on
    return joins


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 8 — SQL Generation
# ══════════════════════════════════════════════════════════════════════════════

def _schema_block(intent: IntentObject, join_map: Dict[str, str]) -> str:
    lines = ["DATABASE SCHEMA (PostgreSQL — use ONLY what is listed):"]
    for table, cols in intent.selected_columns.items():
        lines.append(f"  {table}: {', '.join(cols[:40])}")
    if join_map:
        lines.append("\nVERIFIED JOIN PATHS (use ONLY these, never invent ON clauses):")
        for pair, on in join_map.items():
            lines.append(f"  {pair.replace('--', ' JOIN ')} ON {on}")
    return "\n".join(lines)


def stage8_generate_sql(intent: IntentObject, join_map: Dict[str, str],
                        sql_strategy: str = "full") -> str:
    schema = _schema_block(intent, join_map)
    if sql_strategy == "aggregated":
        strategy_note = "Dataset is large — write an AGGREGATED query (GROUP BY + SUM/COUNT/AVG). Do NOT return raw rows."
    elif sql_strategy == "paginated":
        strategy_note = "Add LIMIT 500 OFFSET 0."
    elif sql_strategy == "kpi_only":
        strategy_note = "Return only scalar KPIs: totals, counts, averages. Single-row preferred."
    else:
        strategy_note = "Return all matching rows — do NOT add an arbitrary LIMIT unless the question asks for a specific number."

    # Add context hints for common Zodiac/SAT patterns
    context_hints = []
    q_low = intent.raw_question.lower()

    # ── SAT / CFDI hints (real column names from sat_documents) ──
    if "sat" in q_low or "cfdi" in q_low or "inbound" in q_low:
        context_hints.append(
            "sat_documents real columns: id(uuid), cfdi_uuid, doc_type, supplier_rfc, supplier_name, "
            "receiver_rfc, receiver_name, fecha(timestamp), subtotal(text), total(text), moneda, "
            "status, received_at(timestamp), source. "
            "Date ordering: ORDER BY received_at DESC or fecha DESC. "
            "NEVER filter sat_documents with source='inbound' — valid source values are only 'admin' and 'supplier'. "
            "The word 'inbound' in questions means SAT pipeline direction, not a column value. "
            "Supplier counts: GROUP BY supplier_rfc, supplier_name ORDER BY COUNT(*) DESC. "
            "Document type: GROUP BY doc_type (values: invoice, credit_note, payment complement, etc). "
            "Missing UUID: WHERE cfdi_uuid IS NULL OR cfdi_uuid = ''. "
            "Total / subtotal are TEXT — cast to NUMERIC for math: CAST(total AS NUMERIC)."
        )
        context_hints.append(
            "sat_canonical_merged real columns: id(uuid), vendor_rfc, vendor_name, fiscal_year, "
            "fiscal_period, total_invoices, total_credits, total_payments, net_amount, currency, "
            "status, sent_to_sap_at(timestamp nullable), created_at. "
            "sent_to_sap_at IS NOT NULL means sent to SAP; IS NULL means pending/not sent. "
            "Sent vs pending: SELECT "
            "  COUNT(*) FILTER (WHERE sent_to_sap_at IS NOT NULL) AS sent_to_sap, "
            "  COUNT(*) FILTER (WHERE sent_to_sap_at IS NULL) AS pending "
            "FROM sat_canonical_merged. "
            "sat_simple_merged: vendor_rfc, vendor_name, document_count, total_amount, sent_to_sap(boolean). "
            "sent_to_sap = TRUE means sent; FALSE means pending."
        )
        context_hints.append(
            "For 'SAT summary / totals / top suppliers sent to SAP vs pending': "
            "WITH totals AS ( "
            "  SELECT supplier_name, supplier_rfc, COUNT(*) AS doc_count "
            "  FROM sat_documents GROUP BY supplier_name, supplier_rfc "
            "), sap_status AS ( "
            "  SELECT vendor_name, vendor_rfc, "
            "    SUM(total_invoices) AS total_invoices, "
            "    COUNT(*) FILTER (WHERE sent_to_sap_at IS NOT NULL) AS sent_to_sap, "
            "    COUNT(*) FILTER (WHERE sent_to_sap_at IS NULL) AS pending "
            "  FROM sat_canonical_merged GROUP BY vendor_name, vendor_rfc "
            ") "
            "SELECT t.supplier_name, t.doc_count, "
            "  COALESCE(s.sent_to_sap, 0) AS sent_to_sap, "
            "  COALESCE(s.pending, 0) AS pending "
            "FROM totals t LEFT JOIN sap_status s ON t.supplier_rfc = s.vendor_rfc "
            "ORDER BY t.doc_count DESC LIMIT 20."
        )

    # ── Zodiac invoice / EDI hints (real column names) ──
    if "outbound" in q_low or "edi" in q_low or "converted" in q_low:
        context_hints.append(
            "zodiac_invoice_failed_edi real columns: id, tracking_id, user_id, uploaded_at(timestamptz), "
            "xml_validation_pass(boolean), xml_convert_message(text), edi_convert_pass(boolean), "
            "edi_convert_message(text), invoice_number, request_type, target_file_format, processing_steps(json). "
            "Failure reason is in xml_convert_message (XML issues) or edi_convert_message (EDI issues). "
            "zodiac_invoice_success_edi: same columns plus external_status, external_message."
        )

    # ── Failed invoice / failure analysis hints ──
    if "fail" in q_low or "failure" in q_low or "error" in q_low or "reason" in q_low:
        context_hints.append(
            "BEST TABLE for failed invoice analysis: invoice_business_data — columns: "
            "supplier_name, customer_name, total_amount(numeric), currency, invoice_number, "
            "invoice_date, current_stage, stage_status, failed_at_stage, failure_reason(text), "
            "source_format, target_format, created_at. "
            "For failure reasons: SELECT failure_reason, COUNT(*) FROM invoice_business_data "
            "WHERE stage_status = 'failed' AND created_at >= NOW()-INTERVAL '30 days' "
            "GROUP BY failure_reason ORDER BY COUNT(*) DESC."
        )

    # ── Supplier invoice amount hints ──
    if "supplier" in q_low and any(w in q_low for w in ["amount", "total", "invoice", "highest", "revenue"]):
        context_hints.append(
            "BEST TABLE for supplier invoice totals: invoice_business_data or invoice_v2_business_data. "
            "invoice_business_data columns: supplier_name, supplier_id, total_amount(numeric), currency, "
            "invoice_date, current_stage. "
            "Query: SELECT supplier_name, SUM(total_amount) AS total, COUNT(*) AS invoice_count "
            "FROM invoice_business_data GROUP BY supplier_name ORDER BY total DESC LIMIT 10."
        )

    # ── Customer revenue/amount hints (Zodiac invoice data, not empty SAP VBRK) ──
    if "customer" in q_low and any(w in q_low for w in ["revenue", "amount", "total", "top", "highest"]):
        context_hints.append(
            "BEST TABLE for customer revenue/totals in this system: invoice_v2_business_data. "
            "Columns: customer_name, supplier_name, total_amount(numeric), currency, invoice_number, "
            "invoice_date, current_stage, stage_status, created_at. "
            "Query: SELECT customer_name, SUM(total_amount) AS total_revenue, COUNT(*) AS invoice_count "
            "FROM invoice_v2_business_data GROUP BY customer_name ORDER BY total_revenue DESC LIMIT 10. "
            "NOTE: SAP VBRK/VBAK billing tables are not populated in this environment — use invoice_v2_business_data."
        )

    # ── Comparison / vs hints ──
    if "vs" in q_low or "compare" in q_low or "comparing" in q_low:
        context_hints.append(
            "For SAT vs outbound comparison: "
            "WITH sat AS (SELECT supplier_name, COUNT(*) AS sat_count FROM sat_documents GROUP BY supplier_name), "
            "edi AS (SELECT supplier_name, COUNT(*) AS edi_count FROM invoice_business_data GROUP BY supplier_name) "
            "SELECT COALESCE(sat.supplier_name, edi.supplier_name) AS supplier, "
            "COALESCE(sat.sat_count,0) AS sat_docs, COALESCE(edi.edi_count,0) AS outbound_invoices "
            "FROM sat FULL OUTER JOIN edi USING (supplier_name) ORDER BY sat_docs DESC."
        )

    # ── Count/trend by time period hints ──
    if ("month" in q_low or "week" in q_low or "day" in q_low) and any(
        w in q_low for w in ["count", "by month", "per month", "trend", "over time", "sales order", "invoice"]
    ):
        context_hints.append(
            "For monthly invoice/order counts: use invoice_v2_business_data or invoice_business_data. "
            "Query: SELECT date_trunc('month', invoice_date) AS month, COUNT(*) AS count "
            "FROM invoice_v2_business_data GROUP BY 1 ORDER BY 1 DESC. "
            "NOTE: SAP VBAK/EKKO tables are not populated — use invoice_v2_business_data for order/invoice trends."
        )

    # ── Billing document hints ──
    if "billing" in q_low and any(w in q_low for w in ["document", "amount", "currency"]):
        context_hints.append(
            "For billing document data: use invoice_v2_business_data. "
            "Columns: invoice_number, invoice_date, total_amount(numeric), currency, "
            "supplier_name, customer_name, current_stage. "
            "NOTE: SAP VBRK billing tables are not populated in this environment."
        )

    # ── Purchase order / vendor hints ──
    if ("purchase order" in q_low or "open order" in q_low) and "vendor" in q_low:
        context_hints.append(
            "For purchase order / vendor data: SAP EKKO/EKPO tables are not populated. "
            "Use zodiac_invoice_failed_edi or invoice_business_data as proxy for open/pending items. "
            "Query: SELECT supplier_name, COUNT(*) AS open_count FROM invoice_business_data "
            "WHERE stage_status = 'pending' GROUP BY supplier_name ORDER BY open_count DESC."
        )

    # ── This week / received date hints ──
    if "week" in q_low or "today" in q_low or "recent" in q_low or "latest" in q_low:
        context_hints.append(
            "For 'this week': WHERE received_at >= date_trunc('week', CURRENT_DATE) (for sat_documents). "
            "For 'today': WHERE received_at::date = CURRENT_DATE. "
            "For 'last 30 days': WHERE received_at >= CURRENT_DATE - INTERVAL '30 days'."
        )
    hints_block = ("\n\nDOMAIN HINTS:\n" + "\n".join(f"- {h}" for h in context_hints)) if context_hints else ""

    system = (
        schema + hints_block + "\n\nINSTRUCTIONS:\n"
        "- Return ONLY raw SQL — no markdown, no fences, no explanation.\n"
        "- Use ONLY the tables and columns listed above.\n"
        "- Use ONLY the verified join paths — never guess ON clauses.\n"
        "- Cast TEXT columns to NUMERIC or DATE for math/comparisons.\n"
        "- Double-quote UPPERCASE identifiers: \"VBELN\". Lowercase identifiers need no quotes.\n"
        f"- {strategy_note}\n"
        "- For time filters use CURRENT_DATE, date_trunc(), or appropriate PostgreSQL date functions.\n"
        "- If the question is unanswerable from this schema, return exactly: CANNOT_ANSWER"
    )
    try:
        sql = _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"Question: {intent.raw_question}"}],
            model="gpt-4o", temperature=0, max_tokens=1500,
        )
    except Exception as e:
        logger.error("Stage8 SQL gen failed: %s", e)
        return "CANNOT_ANSWER"
    sql = re.sub(r"^```[a-z]*\n?", "", sql.strip(), flags=re.IGNORECASE)
    sql = re.sub(r"\n?```$", "", sql.strip())
    return sql.strip()


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 9 — SQL Validation
# ══════════════════════════════════════════════════════════════════════════════

def stage9_validate_sql(sql: str, intent: IntentObject) -> Tuple[bool, str]:
    if not sql or sql.strip().upper().startswith("CANNOT_ANSWER"):
        return False, "CANNOT_ANSWER"
    sql_up = sql.upper()
    for kw in ["DELETE", "UPDATE", "DROP", "ALTER", "TRUNCATE",
               "INSERT", "CREATE", "EXEC", "GRANT", "REVOKE"]:
        if re.search(r'\b' + kw + r'\b', sql_up):
            return False, f"Forbidden keyword: {kw}"
    if not (sql_up.strip().startswith("SELECT") or "WITH" in sql_up[:20]):
        return False, "SQL does not start with SELECT"
    return True, "ok"


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 10 — Smart Execution
# ══════════════════════════════════════════════════════════════════════════════

_HUGE_THRESHOLD   = 100_000
_LARGE_THRESHOLD  = 5_000

def stage10_execute(sql: str, db_session, intent: IntentObject) -> Tuple[List[Dict], int, str]:
    from sqlalchemy import text

    total_count = -1
    try:
        s = sql.rstrip(";").strip()
        s_no_order = re.sub(r'\bORDER\s+BY\b[^;]*$', '', s, flags=re.IGNORECASE).strip()
        count_sql = f"SELECT COUNT(*) FROM ({s_no_order}) AS _cnt"
        res = db_session.execute(text(count_sql))
        row = res.fetchone()
        total_count = int(row[0]) if row else -1
    except Exception:
        total_count = -1

    final_sql = sql
    if total_count > _HUGE_THRESHOLD:
        strategy = "aggregated"
        agg = stage8_generate_sql(intent, {}, sql_strategy="aggregated")
        ok, _ = stage9_validate_sql(agg, intent)
        if ok:
            final_sql = agg
    elif total_count > _LARGE_THRESHOLD:
        strategy = "paginated"
        if "LIMIT" not in final_sql.upper():
            final_sql = final_sql.rstrip(";").strip() + f"\nLIMIT {_LARGE_THRESHOLD}"
    else:
        strategy = "full"

    result = db_session.execute(text(final_sql))
    keys = list(result.keys())
    rows = [dict(zip(keys, r)) for r in result.fetchall()]
    return rows, total_count, strategy


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 11 — Result Summarization
# ══════════════════════════════════════════════════════════════════════════════

def stage11_summarize(intent: IntentObject, rows: List[Dict], sql: str,
                      total_count: int) -> Tuple[str, List[str], List[Dict]]:
    if not rows:
        return "No data returned for this query.", ["No results found."], []
    sample_str = json.dumps(rows[:50], default=str, ensure_ascii=False)[:6000]
    prompt = (
        'You are a senior business data analyst. Analyze this query result and provide insights.\n\n'
        f'Question: "{intent.raw_question}"\n'
        f'SQL: {sql[:600]}\n'
        f'Total rows in DB: {total_count if total_count >= 0 else len(rows)}\n'
        f'Result sample ({min(len(rows), 50)} rows shown):\n{sample_str}\n\n'
        'Respond in JSON (no fences):\n'
        '{\n'
        '  "executive_summary": "2-4 sentence business narrative",\n'
        '  "key_findings": ["Finding 1 with numbers", "Finding 2", "Finding 3 anomaly/trend"],\n'
        '  "kpis": [{"label": "Total Revenue", "value": "1.23M", "change": "+12%"}],\n'
        '  "business_impact": "1-2 sentences on implications",\n'
        '  "recommended_actions": ["Action 1", "Action 2"]\n'
        '}'
    )
    try:
        raw = _chat([{"role": "user", "content": prompt}],
                    model="gpt-4o", max_tokens=1200, json_mode=True)
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning("Stage11 summarize failed: %s", e)
        parsed = {}

    summary = parsed.get("executive_summary", f"Query returned {len(rows)} row(s).")
    findings = list(parsed.get("key_findings") or [])
    kpis     = list(parsed.get("kpis") or [])
    impact   = str(parsed.get("business_impact") or "")
    actions  = list(parsed.get("recommended_actions") or [])

    if impact:
        summary += "\n\n**Business Impact:** " + impact
    if actions:
        summary += "\n\n**Recommended Actions:**\n" + "\n".join(f"- {a}" for a in actions)
    return summary, findings, kpis


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 12+13 — Automatic Visualization Engine
# ══════════════════════════════════════════════════════════════════════════════

def _col_types(rows: List[Dict]) -> Dict[str, str]:
    if not rows:
        return {}
    types: Dict[str, str] = {}
    sample = rows[:20]
    for col in sample[0].keys():
        vals = [r[col] for r in sample if r.get(col) is not None]
        if not vals:
            types[col] = "text"; continue
        num = sum(1 for v in vals if _to_float(v) is not None)
        if num / len(vals) >= 0.7:
            types[col] = "numeric"; continue
        dt = sum(1 for v in vals if re.search(r'\d{4}[-/]\d{1,2}', str(v)))
        if dt / len(vals) >= 0.5:
            types[col] = "date"; continue
        types[col] = "text"
    return types


def _to_float(v: Any) -> Optional[float]:
    if v is None: return None
    try: return float(str(v).replace(",", "").replace("%", "").strip())
    except Exception: return None


def stage12_13_visualize(intent: IntentObject, rows: List[Dict]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    ct = _col_types(rows)
    all_cols = list(rows[0].keys())
    num_cols  = [c for c in all_cols if ct.get(c) == "numeric"]
    text_cols = [c for c in all_cols if ct.get(c) == "text"]
    date_cols = [c for c in all_cols if ct.get(c) == "date"]

    q = intent.raw_question.lower()
    charts: List[Dict[str, Any]] = []

    def bar(lc: str, vc: str, title: str, limit: int = 20) -> Dict:
        lim = rows[:limit]
        return {"type": "bar", "title": title,
                "labels": [str(r.get(lc, "")) for r in lim],
                "datasets": [{"label": vc, "data": [_to_float(r.get(vc)) for r in lim]}],
                "options": {"indexAxis": "y" if limit > 12 else "x",
                             "plugins": {"legend": {"display": False}}}}

    def line(lc: str, vcs: List[str], title: str) -> Dict:
        return {"type": "line", "title": title,
                "labels": [str(r.get(lc, "")) for r in rows],
                "datasets": [{"label": vc, "data": [_to_float(r.get(vc)) for r in rows]} for vc in vcs],
                "options": {}}

    def pie(lc: str, vc: str, title: str, limit: int = 12) -> Dict:
        lim = rows[:limit]
        return {"type": "pie", "title": title,
                "labels": [str(r.get(lc, "")) for r in lim],
                "datasets": [{"label": vc, "data": [_to_float(r.get(vc)) for r in lim]}],
                "options": {}}

    # Trend / time-series
    if date_cols and num_cols:
        charts.append(line(date_cols[0], num_cols[:2],
                           f"Trend: {', '.join(num_cols[:2])} over time"))

    # Ranking / top-N
    if text_cols and num_cols and (intent.intent in ("ranking", "comparison", "count")
                                    or any(w in q for w in ["top", "rank", "best", "most", "highest"])):
        charts.append(bar(text_cols[0], num_cols[0],
                          f"Top {min(len(rows), 20)} by {num_cols[0]}"))

    # Distribution / share
    if text_cols and num_cols and len(rows) <= 15:
        if intent.intent in ("distribution",) or any(w in q for w in ["share", "percent", "breakdown", "portion"]):
            charts.append(pie(text_cols[0], num_cols[0],
                              f"Share: {num_cols[0]} by {text_cols[0]}"))

    # Multi-metric comparison
    if len(num_cols) >= 2 and text_cols:
        charts.append({
            "type": "bar", "title": f"Compare: {num_cols[0]} vs {num_cols[1]}",
            "labels": [str(r.get(text_cols[0], "")) for r in rows[:20]],
            "datasets": [{"label": nc, "data": [_to_float(r.get(nc)) for r in rows[:20]]} for nc in num_cols[:2]],
            "options": {"grouped": True},
        })

    # viz override
    if intent.visualization == "line" and not date_cols and text_cols and num_cols:
        charts = [line(text_cols[0], num_cols[:2], intent.raw_question)]
    elif intent.visualization == "pie" and text_cols and num_cols:
        charts = [pie(text_cols[0], num_cols[0], intent.raw_question)]
    elif intent.visualization == "bar" and text_cols and num_cols:
        charts = [bar(text_cols[0], num_cols[0], intent.raw_question)]
    elif intent.visualization == "kpi":
        charts = []

    # deduplicate
    seen: set = set()
    out = []
    for c in charts:
        k = c.get("type", "") + c.get("title", "")
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out[:4]


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 15 — Adaptive Learning
# ══════════════════════════════════════════════════════════════════════════════

def stage15_learn(intent: IntentObject, success: bool, db_session) -> None:
    try:
        from sqlalchemy import text
        db_session.execute(text("""
            INSERT INTO ai_query_memory
              (question, domain, tables_used, sql, success, row_count, created_at)
            VALUES
              (:question, :domain, :tables_used, :sql, :success, :row_count, NOW())
            ON CONFLICT DO NOTHING
        """), {
            "question":    intent.raw_question[:500],
            "domain":      intent.domain,
            "tables_used": json.dumps(intent.selected_tables),
            "sql":         intent.sql[:2000],
            "success":     success,
            "row_count":   intent.row_count,
        })
        db_session.commit()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_analyst_pipeline(
    question: str,
    db_session,
    schema_map: Optional[Dict[str, List[str]]] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    t0 = time.time()
    logger.info("[pipeline] START question=%s", question[:80])

    if schema_map is None:
        try:
            from .schema_context_builder import load_schema
            schema_map = load_schema()
        except Exception as e:
            logger.error("Could not load schema: %s", e)
            schema_map = {}

    intent = stage1_intent(question)
    intent = stage2_domain(intent)
    intent = stage3_category(intent)
    intent = stage4_tables(intent, schema_map)
    intent = stage5_columns(intent, schema_map)
    intent = stage6_rank_columns(intent)
    join_map = stage7_relationship_graph(intent)

    logger.info("[pipeline] domain=%s categories=%s tables=%s joins=%d",
                intent.domain, intent.categories, intent.selected_tables, len(join_map))

    sql = "CANNOT_ANSWER"
    rows: List[Dict] = []
    total_count = -1
    strategy = "full"
    exec_error: Optional[str] = None

    for attempt in range(max_retries):
        sql = stage8_generate_sql(intent, join_map, sql_strategy=strategy)
        ok, reason = stage9_validate_sql(sql, intent)
        if not ok:
            if reason == "CANNOT_ANSWER":
                # On first CANNOT_ANSWER, try a simpler fallback: just count rows from primary table
                if attempt == 0 and intent.selected_tables:
                    primary = intent.selected_tables[0]
                    logger.warning("[pipeline] CANNOT_ANSWER — fallback count for table %s", primary)
                    sql = f"SELECT COUNT(*) AS total_rows FROM {primary}"
                    ok2, _ = stage9_validate_sql(sql, intent)
                    if ok2:
                        try:
                            rows, total_count, strategy = stage10_execute(sql, db_session, intent)
                            exec_error = None
                            intent.warnings.append(
                                f"Original question was too complex — showing row count for {primary} instead."
                            )
                            break
                        except Exception as e:
                            exec_error = str(e)
                break
            logger.warning("[pipeline] S9 invalid attempt=%d: %s", attempt + 1, reason)
            continue
        logger.info("[pipeline] attempt=%d sql_preview=%s", attempt + 1, sql[:200].replace('\n', ' '))
        try:
            rows, total_count, strategy = stage10_execute(sql, db_session, intent)
            exec_error = None
            break
        except Exception as e:
            exec_error = str(e)
            logger.warning("[pipeline] S10 error attempt=%d: %s", attempt + 1, e)
            if attempt == max_retries - 1:
                intent.warnings.append(f"Execution error: {exec_error}")

    intent.sql = sql
    intent.sql_strategy = strategy
    intent.rows = rows
    intent.row_count = len(rows)
    intent.total_rows_in_db = total_count

    summary, findings, kpis = stage11_summarize(intent, rows, sql, total_count)
    intent.summary      = summary
    intent.key_findings = findings
    intent.kpis         = kpis
    intent.charts       = stage12_13_visualize(intent, rows)
    intent.pipeline_ms  = int((time.time() - t0) * 1000)

    logger.info("[pipeline] DONE ms=%d rows=%d charts=%d",
                intent.pipeline_ms, len(rows), len(intent.charts))

    try:
        stage15_learn(intent, success=bool(rows), db_session=db_session)
    except Exception:
        pass

    # If no rows returned, add a warning with the generated SQL for debugging
    if not intent.rows and intent.sql and not intent.sql.startswith("CANNOT_ANSWER"):
        intent.warnings.append(f"Query returned 0 rows. SQL: {intent.sql[:400]}")
        intent.summary = (
            "No data was returned. This may mean:\n"
            "- The tables exist but are empty in this environment\n"
            "- The filters did not match any records\n"
            "- Try rephrasing or asking about a different time period\n\n"
            f"**SQL generated:**\n```sql\n{intent.sql}\n```"
        )

    return {
        "sql":         intent.sql,
        "data":        intent.rows,
        "rowCount":    intent.row_count,
        "totalCount":  intent.total_rows_in_db,
        "sqlStrategy": intent.sql_strategy,
        "summary":     intent.summary,
        "keyFindings": intent.key_findings,
        "kpis":        intent.kpis,
        "charts":      intent.charts,
        "meta": {
            "domain":        intent.domain,
            "intent":        intent.intent,
            "categories":    intent.categories,
            "schema_tables": intent.selected_tables,
            "pipeline_ms":   intent.pipeline_ms,
            "warnings":      intent.warnings,
            "time_range":    intent.time_range,
        },
    }
