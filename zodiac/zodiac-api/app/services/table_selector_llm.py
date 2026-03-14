"""
Schema-driven table selection: LLM chooses relevant tables from the schema given the question.
No keyword rules — the model reasons over the schema.
"""
from __future__ import annotations

import logging
import re
from typing import List, Set

from openai import OpenAI

logger = logging.getLogger(__name__)

# Known SAP table names (uppercase) for validating LLM output
KNOWN_SAP_TABLES: Set[str] = {
    "AUFK", "BSAD", "BSEG", "CEPC", "CKHS", "CKIS", "CKIT", "CKMLCR", "CKMLHD", "CKMLPP",
    "COEP", "COSP", "CRHD", "CSKS", "EBAN", "EKKO", "EKPO", "FAGLFLEXA", "KEKO", "KEPH",
    "KNA1", "KNVP", "KNVV", "KONV", "LFA1", "LFB1", "LFM1", "LIKP", "LIPS", "LSEG",
    "MAKT", "MARC", "MARM", "MEAN", "MKPF", "MVKE", "RBKP", "RESB", "RSEG",
    "STKO", "STPO", "T016T", "VBAK", "VBAP", "VBEP", "VBFA", "VBRK", "VBRP",
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

    prompt = f"""You are a SAP data expert. Given a user question and the database schema, select the MINIMUM set of tables needed to answer the question.

User question:
{question}

Database schema:
{schema_text}

Rules:
- Select only tables that exist in the schema above.
- Prefer fewer tables when possible (e.g. for "cost by profit center" use FAGLFLEXA only; for "sales by product" use VBRK, VBRP, MAKT).
- For profit center / cost / GL: use FAGLFLEXA (has prctr, hsl, racct).
- For sales / revenue / billing: use VBRK, VBRP; add KNA1 for customer, MAKT for material name.
- For purchases / orders: use EKKO, EKPO; add MAKT for material name, LFA1 for vendor.
- For material description or product name filter: include MAKT (maktx = description).

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
