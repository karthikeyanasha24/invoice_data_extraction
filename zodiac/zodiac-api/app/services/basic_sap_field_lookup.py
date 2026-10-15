"""Optional Gemini glossary lookup for an unresolved SAP field in Basic.

This supplies a schema-checked hint, never SQL or database evidence. It sends
only the field label to Gemini; customer data and the question stay local.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

from .investigation_budget import current_budget

_KNOWN = {
    "KUNAG", "KUNNR", "NAME1", "CUSTOMER NAME", "CUSTOMER NUMBER",
    "SOLD-TO PARTY", "VBRK", "KNA1",
}
_IGNORE = {"SAP", "SQL", "API", "LLM", "RAG", "DEM", "USD", "EUR", "GBP", "INR", "JPY", "CHF", "AUD", "CAD"}
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_GEMINI_RETRY_AFTER = 0.0


def gemini_field_lookup_enabled() -> bool:
    return (os.getenv("BASIC_GEMINI_FIELD_LOOKUP", "false").strip().lower() in {"1", "true", "yes"}
            and bool((os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or "").strip()))


def unresolved_field(question: str) -> str:
    """Select one field-like term, avoiding entire business questions/filters."""
    q = question or ""
    explicit = re.search(
        r"\b(?:SAP\s+)?(?:field|column|definition|meaning)(?:\s+definition)?\s+(?:for|of|named|called)?\s*['\"]?([A-Za-z][A-Za-z0-9_]{3,31})\b",
        q, re.I,
    )
    if explicit:
        term = explicit.group(1).upper()
        return "" if term in _KNOWN or term in _IGNORE else term
    for term in re.findall(r"\b[A-Z][A-Z0-9_]{3,31}\b", q):
        if term not in _KNOWN and term not in _IGNORE:
            return term
    name = re.search(r"\b([a-z][a-z-]{1,30}\s+name)\b", q, re.I)
    if name:
        term = re.sub(r"\s+", " ", name.group(1)).lower()
        if term.upper() not in _KNOWN:
            return term
    return ""


def has_known_customer_terms(question: str) -> bool:
    return bool(re.search(r"\b(?:KUNAG|KUNNR|NAME1|customer\s+names?)\b", question or "", re.I))


def _live_columns(schema: dict) -> dict:
    return {
        (str(table).lower(), str(col.get("col") or "").lower()): (str(table), str(col.get("col")))
        for table, cols in (schema or {}).items() for col in (cols or []) if isinstance(col, dict)
    }


def _known_customer_hint(question: str, live: dict) -> dict | None:
    if not has_known_customer_terms(question):
        return None
    requested = [("VBRK", "kunag"), ("KNA1", "kunnr"), ("KNA1", "name1")]
    columns = []
    for table, column in requested:
        matched = live.get((table.lower(), column.lower()))
        if matched:
            columns.append({"table": matched[0], "column": matched[1]})
    if len(columns) != len(requested):
        return None
    return {"called": False, "status": "local_glossary", "field": "customer identity/name",
            "meaning": "VBRK.KUNAG is the sold-to customer number; KNA1.KUNNR is the customer master number; KNA1.NAME1 is the customer name. Verify client and relationship before joining.",
            "columns": columns}


def lookup_sap_field(question: str, schema: dict, *, schema_source: str = "live_database_metadata") -> dict:
    """Return only candidates present in the connected schema.

    A snapshot cannot prove a suggested column exists in the current database.
    """
    global _GEMINI_RETRY_AFTER
    target = unresolved_field(question)
    live = _live_columns(schema) if schema_source == "live_database_metadata" else {}
    known_hint = _known_customer_hint(question, live)
    if known_hint and not target:
        return known_hint
    enabled = gemini_field_lookup_enabled()
    key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or "").strip()
    if not target or not enabled or not key or schema_source != "live_database_metadata":
        return {"called": False, "status": "skipped", "field": target}
    if time.monotonic() < _GEMINI_RETRY_AFTER:
        return {"called": False, "status": "provider_cooldown", "field": target}
    budget = current_budget()
    if budget and not budget.allow_llm():
        return {"called": False, "status": "deadline", "field": target}
    model = (os.getenv("BASIC_GEMINI_MODEL") or "gemini-2.5-flash-lite").strip()
    if not re.fullmatch(r"gemini-[a-zA-Z0-9.-]{3,60}", model):
        return {"called": False, "status": "invalid_model", "field": target}
    prompt = (
        "Identify the standard SAP meaning of this field or business label. "
        "Return JSON only: {\"meaning\": string, \"columns\": "
        "[{\"table\": string, \"column\": string}]}. "
        "List at most three likely SAP table/column pairs. If unsure, return an empty columns array. "
        "Do not write SQL, joins, filters, instructions, or business data.\n"
        "Field or label: " + target
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 256, "responseMimeType": "application/json"},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    started = time.monotonic()
    try:
        timeout = min(12.0, budget.llm_timeout_s(default=12.0)) if budget else 12.0
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.post(url, json=body, headers={"x-goog-api-key": key})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        # Provider errors must not reveal request headers or private prompts.
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {401, 403, 404, 429}:
            _GEMINI_RETRY_AFTER = time.monotonic() + 300
        return {"called": True, "status": "provider_unavailable", "field": target}

    if not isinstance(payload, dict):
        return {"called": True, "status": "invalid_response", "field": target}
    usage = payload.get("usageMetadata") or {}
    usage = usage if isinstance(usage, dict) else {}
    inp = int(usage.get("promptTokenCount") or 0)
    out = int(usage.get("candidatesTokenCount") or 0)
    total = int(usage.get("totalTokenCount") or inp + out)
    if budget:
        from .analyst_usage import price
        budget.diagnostics.setdefault("model_usage", []).append({
            "provider": "gemini", "model": model, "purpose": "basic_sap_field_definition",
            "input_tokens": inp, "output_tokens": out, "total_tokens": total,
            "cached_tokens": int(usage.get("cachedContentTokenCount") or 0),
            "cache_write_tokens": 0, "reasoning_tokens": int(usage.get("thoughtsTokenCount") or 0),
            "usage_reported": bool(usage), "estimated_cost_usd": price(model, inp, out, 0, 0) if usage else None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        })
    try:
        parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        parsed = json.loads("".join(str(part.get("text") or "") for part in parts))
    except (ValueError, TypeError, KeyError):
        return {"called": True, "status": "invalid_response", "field": target}
    if not isinstance(parsed, dict):
        return {"called": True, "status": "invalid_response", "field": target}
    columns = []
    suggestions = parsed.get("columns") or []
    for item in suggestions[:3] if isinstance(suggestions, list) else []:
        if not isinstance(item, dict):
            continue
        table, column = str(item.get("table") or ""), str(item.get("column") or "")
        if _FIELD.fullmatch(table) and _FIELD.fullmatch(column):
            matched = live.get((table.lower(), column.lower()))
            if matched and {"table": matched[0], "column": matched[1]} not in columns:
                columns.append({"table": matched[0], "column": matched[1]})
    meaning = re.sub(r"\s+", " ", str(parsed.get("meaning") or ""))[:160]
    return {"called": True, "status": "validated" if columns else "no_schema_match",
            "field": target, "meaning": meaning if columns else "", "columns": columns}
