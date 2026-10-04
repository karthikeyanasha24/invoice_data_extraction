"""Capability report: discovered vs queryable vs AI-mapped. Schema is source of truth."""
from __future__ import annotations

from typing import Any, Dict, List

from ...data_catalog.physical import column_names, has_table, sap_business_tables
from ...data_catalog.registry import RELATIONSHIPS, get_table_entry

_PROBE = [
    "VBAK", "VBAP", "VBEP", "VBED", "VBRK", "vbrp", "KNA1", "LFA1",
    "EKKO", "EKPO", "AFKO", "MARA", "MAKT", "BKPF", "BSEG", "COEP",
    "CEPC", "T016T",
]


def _row(name: str) -> Dict[str, Any]:
    exists = has_table(name)
    entry = get_table_entry(name) or {}
    mapped = bool(entry.get("business_name") or entry.get("primary_domain"))
    rels = [
        r for r in RELATIONSHIPS
        if str(r.get("source_table")).upper() == name.upper()
        or str(r.get("target_table")).upper() == name.upper()
    ]
    note = None
    if name.upper() == "VBED" and not exists:
        note = "Not in imported schema. Schedule lines are VBEP."
    elif not exists:
        note = "Absent from imported schema"
    return {
        "table": name,
        "discovered": exists,
        "queryable": exists,
        "ai_mapped": mapped and exists,
        "domain": entry.get("primary_domain") or ("absent" if not exists else "unclassified"),
        "columns": len(column_names(name)) if exists else 0,
        "relationships": len(rels),
        "note": note,
    }


def schema_capabilities() -> Dict[str, Any]:
    discovered = sap_business_tables()
    rows = [_row(n) for n in _PROBE]
    seen = {r["table"].upper() for r in rows}
    for t in discovered:
        if t.upper() not in seen:
            rows.append(_row(t))
            seen.add(t.upper())
    domains: Dict[str, int] = {}
    for t in discovered:
        d = (get_table_entry(t) or {}).get("primary_domain") or "unclassified"
        domains[d] = domains.get(d, 0) + 1
    return {
        "table_count": len(discovered),
        "domains": domains,
        "tables": rows,
        "vbed_present": has_table("VBED"),
        "vbep_present": has_table("VBEP"),
    }
