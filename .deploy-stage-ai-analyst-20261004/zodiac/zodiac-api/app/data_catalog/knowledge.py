"""Controlled SAP concept research. Never produces SQL. Database schema wins."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .physical import has_column, has_table, table_entry_physical
from .registry import GLOSSARY, get_table_entry

logger = logging.getLogger("zodiac-api.data_catalog.knowledge")

_CACHE_PATH = Path(__file__).resolve().parent / "knowledge_cache.json"
_SAFE_TERM = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,30}$")


def _load_cache() -> Dict[str, Any]:
    if not _CACHE_PATH.exists():
        return {"entries": []}
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"entries": []}
    except Exception:
        return {"entries": []}


def _save_cache(data: Dict[str, Any]) -> None:
    _CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_cached(term: str) -> Optional[Dict[str, Any]]:
    key = (term or "").strip().upper()
    for row in _load_cache().get("entries") or []:
        if str(row.get("term") or "").upper() == key:
            return row
    return None


def local_resolve(term: str) -> Dict[str, Any]:
    """Resolve a table/field term from catalog + physical schema only."""
    t = (term or "").strip()
    if not t:
        return {"term": t, "verified": False, "exists": False, "source": "empty"}
    physical = table_entry_physical(t)
    entry = get_table_entry(t)
    gloss = GLOSSARY.get(t.upper())
    exists = bool(physical.get("exists"))
    return {
        "term": t.upper(),
        "exists": exists,
        "meaning": (entry or {}).get("description") or (gloss or {}).get("meaning"),
        "domain": (entry or {}).get("primary_domain") or (gloss or {}).get("domain"),
        "grain": (entry or {}).get("grain") or (gloss or {}).get("grain"),
        "columns_present": [c["col"] for c in physical.get("columns") or []][:80],
        "source": "local_catalog+schema_full",
        "confidence": "verified" if exists else "absent",
        "verified": exists,
        "evidence": physical.get("evidence"),
        "verified_flag_for_production": exists and bool(entry),
    }


def propose_from_external(term: str) -> Optional[Dict[str, Any]]:
    """Optional LLM meaning proposal. Never trusted for columns or SQL."""
    if not _SAFE_TERM.match(term or ""):
        return None
    if os.getenv("R5_EXTERNAL_KNOWLEDGE", "").strip().lower() not in {"1", "true", "yes"}:
        return None
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            max_tokens=400,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Explain the SAP table or field as structured JSON with keys "
                        "term, meaning, domain, grain, typical_relationships. "
                        "Do not invent that it exists in a specific customer database. "
                        "Do not output SQL."
                    ),
                },
                {"role": "user", "content": f"SAP object: {term}"},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        logger.info(
            "schema_knowledge_lookup term=%s provider=openai verified=false sql=false",
            term.upper(),
        )
        proposal = {
            "term": term.upper(),
            "meaning": text[:2000],
            "source": "external_llm",
            "confidence": "unverified",
            "verified": False,
            "sql": None,
        }
        cache = _load_cache()
        entries = list(cache.get("entries") or [])
        entries = [e for e in entries if str(e.get("term") or "").upper() != term.upper()]
        entries.append(
            {
                **proposal,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        cache["entries"] = entries
        _save_cache(cache)
        return proposal
    except Exception as exc:  # noqa: BLE001
        logger.info("schema_knowledge_lookup failed term=%s err=%s", term, type(exc).__name__)
        return None


def resolve_knowledge(term: str, allow_external: bool = False) -> Dict[str, Any]:
    local = local_resolve(term)
    if local.get("exists") or not allow_external:
        return local
    cached = get_cached(term)
    if cached:
        return {
            **local,
            "external_proposal": cached,
            "verified": False,
            "note": "External proposal is not production schema. Database remains authoritative.",
        }
    proposal = propose_from_external(term)
    if proposal:
        return {
            **local,
            "external_proposal": proposal,
            "verified": False,
            "note": "External proposal must be admin-verified before becoming authoritative.",
        }
    return local


def verify_proposed_column(table: str, column: str) -> bool:
    """Physical schema always wins. External knowledge cannot invent columns."""
    return has_table(table) and has_column(table, column)
