"""
Schema-driven SQL generation: LLM writes PostgreSQL SQL from question + selected tables + schema.
No keyword rules — the model reasons over the schema and question.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


def generate_sql(
    question: str,
    tables: List[str],
    schema_text: str,
    client: OpenAI,
    similar_examples: Optional[List[tuple]] = None,
    model: str = "gpt-4o-mini",
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

    # Restrict schema to selected tables only (subset of full schema)
    prompt = f"""You are a PostgreSQL SAP expert. Write a single SQL query to answer the user's question.

User question:
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
- For "cost by profit center" or "postings by profit center": use FAGLFLEXA, group by prctr, SUM(hsl) as total_cost.
- For "jacket" or product name filter: use MAKT.MAKTX ILIKE '%jacket%' and MAKT.SPRAS = 'E' when MAKT is in tables.
- For sales/revenue: use VBRK, VBRP; join on VBELN; NETWR is amount; FKDAT is billing date; use KNA1 for customer (KUNAG = KUNNR).
- For purchases / purchase order: use EKPO (columns: matnr, menge, netpr). Total quantity = SUM(menge), total cost = SUM(menge * netpr). Always include EKPO for "purchase order totals", "PO totals", "vendor spend by material".
- For "purchase order totals by material": SELECT EKPO.matnr (or p.matnr) AS material, MAKT.maktx AS material_name, SUM(EKPO.menge) AS total_quantity, SUM(EKPO.menge * EKPO.netpr) AS total_purchase_cost FROM EKPO LEFT JOIN MAKT ON EKPO.matnr = MAKT.matnr AND (MAKT.spras = 'E' OR MAKT.spras IS NULL) GROUP BY EKPO.matnr, MAKT.maktx ORDER BY total_purchase_cost DESC LIMIT 100. Use actual table/column casing from schema (e.g. lowercase if schema shows lowercase).
- Use double quotes for identifiers only if needed (e.g. "vbrp" when table is lowercase).
- If the schema cannot fully answer (e.g. no link between FAGLFLEXA and MAKT), still return a valid query for the part that is possible (e.g. cost by profit center from FAGLFLEXA only).
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
