"""
Schema-driven table selection: LLM chooses relevant tables from the schema given the question.
No keyword rules — the model reasons over the schema.
"""
from __future__ import annotations

import logging
import re
from typing import List, Set

from openai import OpenAI
from .schema_index import build_canonical_schema_index

logger = logging.getLogger(__name__)

# Known SAP table names (uppercase) for validating LLM output
KNOWN_SAP_TABLES: Set[str] = {
    "AUFK", "BSAD", "BSEG", "CEPC", "CKHS", "CKIS", "CKIT", "CKMLCR", "CKMLHD", "CKMLPP",
    "COEP", "COSP", "CRHD", "CSKS", "EBAN", "EKKO", "EKPO", "FAGLFLEXA", "KEKO", "KEPH",
    "KNA1", "KNVP", "KNVV", "KONV", "LFA1", "LFB1", "LFM1", "LIKP", "LIPS", "LSEG",
    "MARA", "MAKT", "MARC", "MARM", "MEAN", "MKPF", "MVKE", "RBKP", "RESB", "RSEG",
    "STKO", "STPO", "T016T", "VBAK", "VBAP", "VBEP", "VBFA", "VBRK", "VBRP",
}

TABLE_SYNONYMS = {
    "profit center": ["FAGLFLEXA", "CEPC", "COEP", "CSKS"],
    "invoice amount": ["VBRK", "VBRP", "RBKP", "RSEG"],
    "customer": ["KNA1", "VBRK", "KNVV", "KNVP"],
    "vendor": ["LFA1", "RBKP", "RSEG", "EKKO", "EKPO", "LFB1"],
    "material": ["MAKT", "MARA", "VBRP", "EKPO", "MARC"],
    "purchase": ["EKKO", "EKPO", "LFA1"],
    "delivery": ["LIKP", "LIPS", "VBRP"],
    "sales order": ["VBAK", "VBAP"],
    "stock": ["MARD", "MCHB", "MBEW", "MARC"],
    "inventory": ["MARD", "MCHB", "MBEW", "CKMLCR"],
    "general ledger": ["BSEG", "FAGLFLEXA", "BKPF"],
    "ledger": ["FAGLFLEXA", "BSEG"],
    "posting": ["BSEG", "BKPF", "FAGLFLEXA"],
    "pricing": ["KONV", "VBRK", "EKKO"],
    "bom": ["STKO", "STPO", "MAKT"],
    "cost estimate": ["CKHS", "CKIS", "KEKO"],
}


def select_tables(
    question: str,
    schema_text: str,
    client: OpenAI,
    available_tables: List[str],
    model: str = "gpt-4o-mini",
) -> List[str]:
    """
    Ask the LLM to select the minimum tables needed to answer the question.
    Schema drives the decision; no keyword rules.
    """
    if not question or not schema_text or not client:
        return []

    q_low = (question or "").lower()
    bootstrap_tables: List[str] = []
    available_upper = {t.upper(): t for t in available_tables}
    for phrase, candidates in TABLE_SYNONYMS.items():
        if phrase in q_low:
            for cand in candidates:
                if cand in available_upper and available_upper[cand] not in bootstrap_tables:
                    bootstrap_tables.append(available_upper[cand])
    # Also use canonical schema aliases for mentions + NL relevance ranking (metadata overlap).
    index = build_canonical_schema_index(include_non_sap=True)
    for tok in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", question or ""):
        resolved = index.resolve_table_name(tok)
        if resolved and resolved.upper() in available_upper:
            actual = available_upper[resolved.upper()]
            if actual not in bootstrap_tables:
                bootstrap_tables.append(actual)

    priority_tables: List[str] = list(bootstrap_tables)
    for tbl, sc in index.score_tables_for_natural_language(question, available_tables):
        if sc < 0.95:
            continue
        actual = available_upper.get((tbl or "").strip().upper())
        if actual and actual not in priority_tables:
            priority_tables.append(actual)
    priority_tables = priority_tables[:18]

    prompt = f"""You are a SAP data expert. Given a user question and the database schema, select the MINIMUM set of tables needed to answer the question.

User question:
{question}

Database schema:
{schema_text}

Rules:
- Select only tables that exist in the schema above.
- If bootstrap candidates are relevant, include them first: {", ".join(priority_tables) if priority_tables else "none"}.
- Prefer fewer tables when possible (e.g. for "cost by profit center" use FAGLFLEXA only; for "sales by product" use VBRK, VBRP, MAKT).
- For profit center / cost / GL: use FAGLFLEXA (has prctr, hsl, racct).
- For sales / revenue / billing: use VBRK, VBRP; add KNA1 for customer, MAKT for material name.
- For PURCHASING: use EKPO (purchase order items: matnr, menge, netpr), add MAKT for material name. Use EKKO only if question asks for order header. Keywords: "purchase order", "order totals", "PO totals", "vendor spend", "purchased", "procurement", "buy", "purchase".
- For "purchase order totals by material" or "PO totals by material": you MUST return EKPO, MAKT.
- For material description or product name filter: include MAKT (maktx = description).
- Internal orders / project orders / cost by internal order: use AUFK (aufnr, ktext, kostl, prctr, objnr). Join COEP on objnr for actual costs.
- Cleared customer invoices / payments received / AR cleared: use BSAD (kunnr, dmbtr, augdt). Join KNA1 on kunnr for customer name.
- All accounting line items / GL postings / vendor or customer from FI: use BSEG (dmbtr, koart, kunnr, lifnr, kostl, prctr). Filter koart='K' for vendor, 'D' for customer.
- Profit center master / list profit centers / profit centers by segment or country: use CEPC (prctr, name1, bukrs, segment, land1, verak). Join BSEG or FAGLFLEXA on prctr for costs.
- Product cost estimates / cost estimate header: use CKHS (kalnr, hwges, gjahr, bukrs, kostl). Join CKIS on kalnr for component breakdown.
- Cost estimate components / product cost breakdown / cost by material or vendor: use CKIS (kalnr, posnr, matnr, wertn, prctr). Join CKHS on kalnr, CEPC on prctr, CKIT on kalnr+posnr for descriptions.
- Cost component texts: use CKIT with CKIS (kalnr, posnr, ltext, spras).
- Material ledger / inventory value / standard price / material valuation: use CKMLHD (kalnr, matnr) + CKMLCR (salk3, stprs, pvprs) or CKMLPP (lbkum, receipts, consumption). Join CKMLHD with CKMLCR or CKMLPP on kalnr.

Return ONLY a comma-separated list of table names, e.g.:
FAGLFLEXA, MAKT
or
VBRK, VBRP, KNA1
"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Parse: extract table names (uppercase identifiers)
        tables = _parse_table_list(text, available_tables)
        if tables:
            logger.info("table_selector_llm: selected tables %s for question (first 50 chars)", tables)
        return tables
    except Exception as e:
        logger.warning("table_selector_llm: LLM call failed: %s", e)
        return []


def _parse_table_list(text: str, available_tables: List[str]) -> List[str]:
    """Extract table names from LLM response. Prefer names that exist in available_tables."""
    available_upper = {}
    for t in available_tables:
        available_upper.setdefault((t or "").upper(), t)
    # Find words that look like table names (all caps or PascalCase, 2–20 chars)
    candidates = re.findall(r"\b([A-Z][A-Z0-9_]{1,19})\b", text.upper())
    result = []
    seen = set()
    for c in candidates:
        if c in seen:
            continue
        if c in available_upper:
            seen.add(c)
            result.append(available_upper[c])
    # If no candidates found, try comma/split
    if not result and text:
        for part in re.split(r"[\s,;\n]+", text):
            part = part.strip().upper()
            if len(part) >= 2 and part in available_upper and part not in seen:
                seen.add(part)
                result.append(available_upper[part])
    return result
