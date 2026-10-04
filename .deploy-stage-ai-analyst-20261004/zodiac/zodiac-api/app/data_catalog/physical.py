"""Physical schema from the migrated extract. Database schema wins over glossary."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_SCHEMA_FULL = Path(__file__).resolve().parents[2] / "schema_full.json"

_APP_PREFIXES = (
    "ai_",
    "zodiac_",
    "sat_",
    "invoice_",
    "customer_",
    "converted_",
    "certificate_",
    "correction_",
    "user_",
    "v2_",
    "supplier_",
)


def _norm(name: str) -> str:
    return (name or "").strip()


def _lookup_key(schema: Dict[str, Any], table: str) -> Optional[str]:
    if table in schema:
        return table
    upper = table.upper()
    lower = table.lower()
    for k in schema:
        if k.upper() == upper or k.lower() == lower:
            return k
    return None


@lru_cache(maxsize=1)
def load_physical_schema() -> Dict[str, List[Dict[str, str]]]:
    if not _SCHEMA_FULL.exists():
        return {}
    raw = json.loads(_SCHEMA_FULL.read_text(encoding="utf-8"))
    out: Dict[str, List[Dict[str, str]]] = {}
    if isinstance(raw, dict):
        for table, cols in raw.items():
            if not isinstance(cols, list):
                continue
            normalized = []
            for c in cols:
                if isinstance(c, dict) and c.get("col"):
                    normalized.append(
                        {"col": str(c["col"]), "type": str(c.get("type") or "")}
                    )
                elif isinstance(c, str):
                    normalized.append({"col": c, "type": ""})
            out[str(table)] = normalized
    return out


def catalog_table_names() -> List[str]:
    return sorted(load_physical_schema().keys(), key=lambda t: t.upper())


def sap_business_tables() -> List[str]:
    names = []
    for t in catalog_table_names():
        low = t.lower()
        if any(low.startswith(p) for p in _APP_PREFIXES):
            continue
        if low in {"customers"}:
            continue
        names.append(t)
    return names


def has_table(table: str) -> bool:
    return _lookup_key(load_physical_schema(), table) is not None


def column_names(table: str) -> List[str]:
    schema = load_physical_schema()
    key = _lookup_key(schema, table)
    if not key:
        return []
    return [c["col"] for c in schema[key]]


def has_column(table: str, column: str) -> bool:
    want = (column or "").lower()
    return any(c.lower() == want for c in column_names(table))


def table_entry_physical(table: str) -> Dict[str, Any]:
    schema = load_physical_schema()
    key = _lookup_key(schema, table)
    cols = schema.get(key or "", [])
    return {
        "table": key or table,
        "exists": key is not None,
        "columns": cols,
        "source": "database/schema_full.json",
        "confidence": "verified" if key is not None else "absent",
        "evidence": "VERIFIED FROM DATABASE" if key is not None else "ABSENT FROM MIGRATED SCHEMA",
    }


def resolve_table_name(table: str) -> Optional[str]:
    return _lookup_key(load_physical_schema(), table)
