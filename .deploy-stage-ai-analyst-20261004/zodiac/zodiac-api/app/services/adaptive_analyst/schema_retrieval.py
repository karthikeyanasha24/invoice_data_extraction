"""Retrieve a relevant subset of the migrated schema (never the full dump)."""
from __future__ import annotations

import re
from typing import List, Set

from ...data_catalog.physical import has_table, sap_business_tables
from ...data_catalog.registry import RELATIONSHIPS, get_table_entry
from ..ai_native_pipeline import catalog_guide_text, columns_guide


_TOKEN = re.compile(r"[a-z0-9]{3,}")

_HINTS = {
    "order": ["VBAK", "VBAP", "VBEP"],
    "vbak": ["VBAK"],
    "vbap": ["VBAP"],
    "vbep": ["VBEP"],
    "vbed": ["VBEP"],
    "invoice": ["VBRK", "vbrp"],
    "billing": ["VBRK", "vbrp"],
    "billed": ["VBRK", "vbrp"],
    "revenue": ["VBRK", "vbrp", "KNA1"],
    "sales": ["VBRK", "vbrp", "VBAK", "VBAP", "KNA1"],
    "customer": ["KNA1", "KNVV", "VBRK"],
    "vendor": ["LFA1", "EKKO", "EKPO"],
    "supplier": ["LFA1", "EKKO", "EKPO"],
    "purchase": ["EKKO", "EKPO", "LFA1"],
    "purchasing": ["EKKO", "EKPO", "LFA1"],
    "product": ["MARA", "MAKT", "VBAP", "vbrp"],
    "material": ["MARA", "MAKT"],
    "production": ["AFKO", "AFPO", "AUFK"],
    "finance": ["BKPF", "BSEG", "FAGLFLEXA"],
    "cost": ["COEP", "COSP", "CKIS"],
    "profit": ["vbrp", "VBRK", "CEPC"],
    "margin": ["vbrp", "VBRK"],
    "credit": ["BSEG", "BSAD", "KNA1"],
    "country": ["KNA1"],
    "industry": ["KNA1", "T016T"],
    "inventory": ["MARD", "MBEW"],
}


def retrieve_candidate_tables(question: str, prior_tables: List[str] | None = None) -> List[str]:
    q = (question or "").lower()
    tokens = set(_TOKEN.findall(q))
    ranked: List[str] = []
    seen: Set[str] = set()

    def add(name: str) -> None:
        if not name or name in seen:
            return
        if has_table(name):
            seen.add(name)
            ranked.append(name)

    for t in prior_tables or []:
        add(t)
    for key, tables in _HINTS.items():
        if key in q or key in tokens:
            for t in tables:
                add(t)
    # named tables in the question
    for t in sap_business_tables():
        if t.lower() in tokens or f" {t.lower()} " in f" {q} ":
            add(t)
    if not ranked:
        for t in ("VBRK", "vbrp", "VBAK", "VBAP", "KNA1", "EKKO", "EKPO", "LFA1", "MARA", "AFKO"):
            add(t)
    # join neighbors
    extra = []
    for rel in RELATIONSHIPS:
        src, tgt = rel.get("source_table"), rel.get("target_table")
        if src in seen:
            extra.append(str(tgt))
        if tgt in seen:
            extra.append(str(src))
    for t in extra:
        add(t)
    return ranked[:18]


def schema_context_for(question: str, prior_tables: List[str] | None = None) -> str:
    tables = retrieve_candidate_tables(question, prior_tables)
    lines = [
        "RETRIEVED SCHEMA SUBSET (authoritative; do not invent tables/columns):",
        "Full catalog exists but is not pasted here. Pick only from this subset plus named tables the user typed.",
        "VBED is not imported. Use VBEP for schedule lines.",
        "Sales orders ≠ billed invoices. VBAK.vbeln ≠ VBRK.vbeln.",
        "",
        columns_guide(tables),
        "",
    ]
    for t in tables:
        entry = get_table_entry(t) or {}
        lines.append(
            f"{t}: {entry.get('business_name') or ''} domain={entry.get('primary_domain') or ''} "
            f"grain={entry.get('grain') or ''}"
        )
    return "\n".join(lines)


def compact_catalog_fallback() -> str:
    # used only if retrieval is empty
    return catalog_guide_text()[:12000]
