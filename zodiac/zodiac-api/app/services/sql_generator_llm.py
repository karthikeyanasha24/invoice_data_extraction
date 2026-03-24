"""
Schema-driven SQL generation: LLM writes PostgreSQL SQL from question + selected tables + schema.
Uses semantic dictionary (entities, joins, metrics) for correct table/column/aggregation.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


def _get_semantic_context(question: Optional[str] = None) -> str:
    """Semantic dictionary context for the LLM (entities, metrics, joins, templates).
    When question is margin/profitability-related, appends margin semantic context."""
    try:
        from .query_resolver import get_semantic_context_for_prompt
        block = get_semantic_context_for_prompt()
        if question:
            try:
                from .premium_analysis_service import (
                    is_margin_or_profitability_question,
                    get_margin_semantic_context,
                )
                if is_margin_or_profitability_question(question):
                    margin_ctx = get_margin_semantic_context()
                    if margin_ctx:
                        block = (block or "") + "\n\n" + margin_ctx
            except Exception:
                pass
        return block or ""
    except Exception:
        return ""


def _build_entity_filter_block(question: str) -> str:
    """
    Detect a named entity (customer, vendor, product) in the question and return
    a MANDATORY filter instruction for the LLM prompt.
    Returns an empty string when no specific entity is found.
    """
    try:
        from .invoice_bot_helpers import get_specific_entity_request
        entity = get_specific_entity_request(question)
        if not entity:
            return ""
        entity_type = entity.get("entity", "")
        entity_value = entity.get("value", "")
        if not entity_value:
            return ""
        safe = entity_value.replace("'", "''")
        if entity_type == "customer":
            return (
                f"\n⚠️  MANDATORY FILTER — DO NOT IGNORE:\n"
                f"   The question asks specifically about customer '{entity_value}'.\n"
                f"   You MUST include this exact clause: WHERE \"KNA1\".name1 ILIKE '%{safe}%'\n"
                f"   NEVER use exact match (= '{safe}') — always use ILIKE for name comparisons.\n"
                f"   The customer name in the DB may include extra words (e.g. 'Siemens AG', 'SIEMENS CORP').\n"
                f"   If KNA1 is not yet joined, add: JOIN \"KNA1\" ON \"VBRK\".kunag = \"KNA1\".kunnr\n"
                f"   and ensure VBRK is joined to VBRP via: JOIN \"VBRK\" ON \"VBRK\".vbeln = vbrp.vbeln\n"
                f"   FAILURE to include this filter makes the query WRONG — do not skip it.\n"
            )
        if entity_type == "vendor":
            return (
                f"\n⚠️  MANDATORY FILTER — DO NOT IGNORE:\n"
                f"   The question asks specifically about vendor '{entity_value}'.\n"
                f"   You MUST include this exact clause: WHERE \"LFA1\".name1 ILIKE '%{safe}%'\n"
                f"   NEVER use exact match (= '{safe}') — always use ILIKE for name comparisons.\n"
                f"   The vendor name in the DB may include extra words (e.g. 'Bosch GmbH', 'BOSCH AG').\n"
                f"   If LFA1 is not yet joined, add: JOIN \"LFA1\" ON \"RBKP\".lifnr = \"LFA1\".lifnr  (or EKKO.lifnr)\n"
                f"   FAILURE to include this filter makes the query WRONG — do not skip it.\n"
            )
        if entity_type == "product":
            return (
                f"\n⚠️  MANDATORY FILTER — DO NOT IGNORE:\n"
                f"   The question asks specifically about product '{entity_value}'.\n"
                f"   You MUST include: WHERE \"MAKT\".maktx ILIKE '%{safe}%' AND \"MAKT\".spras = 'E'\n"
                f"   NEVER use exact match (= '{safe}') — always use ILIKE for name comparisons.\n"
                f"   The product description in the DB may include extra words (e.g. 'Harley leather jacket').\n"
                f"   If MAKT is not yet joined, add: JOIN \"MAKT\" ON <fact_table>.matnr = \"MAKT\".matnr\n"
                f"   FAILURE to include this filter makes the query WRONG — do not skip it.\n"
            )
    except Exception:
        pass
    return ""


def generate_sql(
    question: str,
    tables: List[str],
    schema_text: str,
    client: OpenAI,
    similar_examples: Optional[List[tuple]] = None,
    model: str = "gpt-4o-mini",
    intent_context: Optional[str] = None,
) -> Optional[str]:
    """
    Ask the LLM to write a PostgreSQL SQL query for the question using only the given tables.
    similar_examples: optional list of (question, sql) for few-shot.
    """
    if not question or not tables or not client:
        return None

    examples_block = ""
    if similar_examples:
        examples_block = "\nSimilar past queries (use as style reference):\n"
        for q, sql in similar_examples[:3]:
            examples_block += f"\nQuestion: {q}\nSQL:\n{sql}\n"

    semantic_block = _get_semantic_context(question)
    if semantic_block:
        semantic_block = semantic_block + "\n\n"

    # Build entity-specific filter block (empty string when no entity detected)
    entity_filter_block = _build_entity_filter_block(question)

    intent_block = ""
    if intent_context and intent_context.strip():
        intent_block = intent_context.strip() + "\n\n"

    # Restrict schema to selected tables only (subset of full schema)
    prompt = f"""You are a PostgreSQL SAP expert. Write a single SQL query to answer the user's question.

╔══════════════════════════════════════════════════════════════════╗
║  MANDATORY DATA RULES — THESE ARE CONFIRMED DATABASE FACTS      ║
║  Ignoring these rules will produce WRONG or EMPTY results.      ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. GJAHR IS BROKEN — ALL 53,170 rows have gjahr = '0000'.      ║
║     NEVER filter on gjahr. It will always return 0 rows or      ║
║     return every row as year 0000.                              ║
║     ✗ Wrong:   WHERE r."gjahr" = '2000'                         ║
║     ✓ Correct: WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000' ║
║                                                                  ║
║  2. NETWR IS TEXT — stored as character varying, not numeric.   ║
║     NEVER use SUM(v.netwr) directly — it will fail.             ║
║     ✗ Wrong:   SUM(v."netwr")                                   ║
║     ✓ Correct: SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) ║
║                                                                  ║
║  3. JOIN WITH LPAD to avoid leading-zero mismatches:            ║
║     ON LPAD(TRIM(v."vbeln"), 10, '0') =                         ║
║        LPAD(TRIM(r."vbeln"), 10, '0')                           ║
║                                                                  ║
║  4. NEGATIVE / LOWEST SALES — individual billing lines (credit  ║
║     memos) have negative netwr. "Negative sales" or "lowest    ║
║     sales" means LINE ITEMS, NOT year group totals.             ║
║     ✓ Correct: WHERE CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) < 0 ║
║     ✗ WRONG (0 rows always): HAVING SUM(netwr) < 0              ║
║       — no year has a negative TOTAL in this database           ║
║     For "lowest sales": ORDER BY netwr ASC (no HAVING needed)   ║
║                                                                  ║
║  5. "Negative OR lowest for year YYYY" → LINE ITEMS in that year║
║     (ORDER BY netwr ASC). Do NOT return GROUP BY calendar year   ║
║     totals across all years — that answers a different question.║
╚══════════════════════════════════════════════════════════════════╝

{semantic_block}{intent_block}{entity_filter_block}User question:
{question}

Relevant tables (use ONLY these):
{", ".join(tables)}

Schema for these tables:
{schema_text}
{examples_block}

Rules:
- Return ONLY the SQL query, no explanation.
- Use PostgreSQL syntax (e.g. LIMIT not TOP, :: for cast, ILIKE for case-insensitive like).
- Always add LIMIT 100 (or a reasonable limit).
- ENTITY FILTER (CRITICAL): If the question names a specific customer (e.g. "for customer Siemens"), add WHERE KNA1.name1 ILIKE '%Siemens%' and JOIN KNA1 if needed. If it names a vendor (e.g. "vendor named Bosch"), add WHERE LFA1.name1 ILIKE '%Bosch%'. If it names a product (e.g. "Harley", "jacket"), add WHERE MAKT.maktx ILIKE '%Harley%'. NEVER return a broad unfiltered result when a specific entity is requested.
- For "cost by profit center" or "postings by profit center": use FAGLFLEXA, group by prctr, SUM(hsl) as total_cost.
- For "jacket" or product name filter: use MAKT.MAKTX ILIKE '%jacket%' and MAKT.SPRAS = 'E' when MAKT is in tables.
- For sales/revenue: use VBRK (header), VBRP (items); join on VBELN with LPAD; NETWR must be cast (see box above); FKDAT is billing date (TEXT, format YYYYMMDD). For customer join: VBRK.kunag = KNA1.kunnr.
- YEAR FILTERING: ALWAYS use FKDAT (see mandatory box above). NEVER use gjahr.
- NEVER use SQLAlchemy bind parameters like %(year)s or :year in generated SQL — always inline literal values.
- For purchases / purchase order: use EKPO (columns: matnr, menge, netpr). Total quantity = SUM(menge), total cost = SUM(menge * netpr). Always include EKPO for "purchase order totals", "PO totals", "vendor spend by material".
- For "purchase order totals by material": SELECT EKPO.matnr (or p.matnr) AS material, MAKT.maktx AS material_name, SUM(EKPO.menge) AS total_quantity, SUM(EKPO.menge * EKPO.netpr) AS total_purchase_cost FROM EKPO LEFT JOIN MAKT ON EKPO.matnr = MAKT.matnr AND (MAKT.spras = 'E' OR MAKT.spras IS NULL) GROUP BY EKPO.matnr, MAKT.maktx ORDER BY total_purchase_cost DESC LIMIT 100. Use actual table/column casing from schema (e.g. lowercase if schema shows lowercase).
- Use double quotes for identifiers only if needed (e.g. "vbrp" when table is lowercase).
- If the schema cannot fully answer (e.g. no link between FAGLFLEXA and MAKT), still return a valid query for the part that is possible (e.g. cost by profit center from FAGLFLEXA only).
- AUFK (internal orders): aufnr=order number, ktext=description, prctr=profit center, kostl=cost center, objnr=link to COEP/COSP. For cost by order use JOIN COEP ON AUFK.objnr = COEP.objnr and SUM(COEP.wtgbtr or wogbtr). Group by aufnr, ktext or by prctr, kostl.
- BSAD (cleared customer items): kunnr=customer, dmbtr/wrbtr=amount, augdt=clearing date. SUM(dmbtr) GROUP BY kunnr for payments by customer. Join KNA1 on kunnr for customer name.
- BSEG (accounting line items): dmbtr/wrbtr=amount, koart=account type (D=customer, K=vendor). For vendor spend: WHERE koart='K', SUM(dmbtr) GROUP BY lifnr. For customer revenue: WHERE koart='D', GROUP BY kunnr. For cost by cost center: GROUP BY kostl; for profit center: GROUP BY prctr.
- CEPC (profit center master): prctr, name1. List profit centers: SELECT prctr, name1, bukrs, segment FROM CEPC. Cost by profit center: BSEG c JOIN CEPC p ON c.prctr = p.prctr, SUM(c.dmbtr) GROUP BY c.prctr, p.name1. GROUP BY bukrs, segment, land1, verak.
- CKHS (cost estimate header): kalnr, hwges/fwges=total cost, gjahr. SUM(hwges) GROUP BY bukrs, gjahr, kostl. Join CKIS on kalnr for component breakdown. Product cost by company: CKHS h JOIN CKIS i ON h.kalnr = i.kalnr, SUM(i.wertn) GROUP BY h.bukrs.
- CKIS (cost estimate items): wertn=total cost (TEXT column — MUST cast safely), gpreis=unit cost (also TEXT). CRITICAL: wertn and gpreis are stored as TEXT in the DB. ALWAYS use SUM(NULLIF(TRIM(i.wertn::text), '')::NUMERIC) NOT SUM(CAST(COALESCE(wertn, 0) AS NUMERIC)) — that fails with "COALESCE types text and integer cannot be matched". GROUP BY matnr, werks, kostl, lifnr, prctr. Join CKHS on kalnr; CEPC on prctr for profit center name; CKIT on kalnr+posnr for ltext (description). Safe subquery template: (SELECT matnr, SUM(NULLIF(TRIM(wertn::text), '')::NUMERIC) AS total_cost FROM "CKIS" GROUP BY matnr) c.
- For profit margin by product: SELECT vbrp.matnr, COALESCE(m.maktx, vbrp.matnr::text) AS product_name, SUM(NULLIF(TRIM(vbrp.netwr::text), '')::NUMERIC) AS revenue, COALESCE(c.total_cost, 0::NUMERIC) AS cost, SUM(NULLIF(TRIM(vbrp.netwr::text), '')::NUMERIC) - COALESCE(c.total_cost, 0::NUMERIC) AS margin FROM vbrp LEFT JOIN "VBRK" vk ON TRIM(vbrp.vbeln) = TRIM(vk.vbeln) LEFT JOIN "MAKT" m ON vbrp.matnr = m.matnr AND m.spras = 'E' LEFT JOIN (SELECT matnr, SUM(NULLIF(TRIM(wertn::text), '')::NUMERIC) AS total_cost FROM "CKIS" GROUP BY matnr) c ON vbrp.matnr = c.matnr GROUP BY vbrp.matnr, m.maktx, c.total_cost ORDER BY margin DESC NULLS LAST LIMIT 100.
- CKIT (cost component texts): join CKIS ON i.kalnr = t.kalnr AND i.posnr = t.posnr for matnr, ltext, wertn. Filter spras for language.
- CKMLCR (material ledger values): salk3=inventory value, stprs=standard price, pvprs=periodic price. Join CKMLHD on kalnr; SUM(c.salk3) GROUP BY h.matnr for inventory value by material. GROUP BY bdatj, poper for period.
- CKMLHD (material ledger header): kalnr links to CKMLCR (values) and CKMLPP (quantities). Join CKMLCR, GROUP BY h.matnr, SUM(c.salk3) for inventory value by material. Join CKMLPP, SUM(p.lbkum) for stock by material.
- CKMLPP (material ledger period): lbkum=stock, zukumo=receipts, abkumo=consumption. Join CKMLHD on kalnr; SUM(p.lbkum) GROUP BY h.matnr for stock by material. Receipts vs consumption: SUM(zukumo), SUM(abkumo).
"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        sql = _extract_sql(text)
        if sql:
            logger.info("sql_generator_llm: generated SQL (first 120 chars): %s", (sql or "")[:120])
        return sql
    except Exception as e:
        logger.warning("sql_generator_llm: LLM call failed: %s", e)
        return None


def _extract_sql(text: str) -> Optional[str]:
    """Extract SQL from LLM response (may be wrapped in markdown or prose)."""
    if not text:
        return None
    text = text.strip()
    # Remove markdown code block if present
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    # Take first statement (up to semicolon or end)
    first = text.split(";")[0].strip()
    if first.upper().startswith("SELECT"):
        return first + ";"
    if "SELECT" in first.upper():
        return first + ";"
    return text if ("SELECT" in text.upper()) else None

