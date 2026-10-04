"""
Accuracy helpers: year-in-SQL checks + compact query telemetry for logs and API.

Used by multi_stage_planner (dashboard AI chat) and ai_analysis_orchestrator (LangGraph).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def calendar_years_in_question(question: str) -> List[str]:
    """4-digit calendar years mentioned in natural language (deduped, stable order)."""
    if not (question or "").strip():
        return []
    try:
        from .intent_extractor import _extract_years

        years = list(_extract_years(question))
    except Exception:
        years = []
    if not years:
        years = re.findall(r"\b((?:19|20)\d{2})\b", question or "")
    # dedupe preserving order
    seen: set = set()
    out: List[str] = []
    for y in years:
        if y not in seen:
            seen.add(y)
            out.append(y)
    return out


def sql_reflects_calendar_years(question: str, sql: str) -> Tuple[bool, List[str], List[str]]:
    """
    Return (ok, years_found, years_missing_from_sql).

    Heuristic: each year from the question must appear somewhere in the SQL text
    (case-insensitive). Good enough to flag obvious year drops in LangGraph output.
    """
    years = calendar_years_in_question(question)
    if not years:
        return True, [], []
    blob = (sql or "").upper()
    missing: List[str] = []
    for y in years:
        if y in blob:
            continue
        missing.append(y)
    return (len(missing) == 0), years, missing


def build_query_telemetry(
    *,
    question: str,
    pipeline: str,
    reason: str,
    sql: str,
    preview_row_count: int,
    total_ms: Optional[int] = None,
    sql_repair_count: int = 0,
    node_log_count: int = 0,
    execution_error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact, JSON-safe telemetry for API + structured logs."""
    years_ok, years_q, years_miss = sql_reflects_calendar_years(question, sql)
    sql_blob = (sql or "").strip()
    sql_hash = hashlib.sha256(sql_blob.encode("utf-8", errors="ignore")).hexdigest()[:16]
    tel: Dict[str, Any] = {
        "pipeline": pipeline,
        "reason": reason,
        "preview_row_count": int(preview_row_count),
        "total_ms": int(total_ms) if total_ms is not None else None,
        "sql_repair_count": int(sql_repair_count),
        "node_log_count": int(node_log_count),
        "sql_sha256_16": sql_hash,
        "calendar_years_in_question": years_q,
        "sql_reflects_all_question_years": years_ok,
        "calendar_years_missing_in_sql": years_miss,
        "execution_error": ((execution_error or "")[:400] or None),
    }
    if extra:
        tel["extra"] = extra
    return tel


def log_query_telemetry(telemetry: Dict[str, Any], *, question_snip: str = "") -> None:
    """Single-line JSON for log aggregators (grep: ai_query_telemetry)."""
    try:
        payload = dict(telemetry)
        if question_snip:
            payload["question_snip"] = (question_snip or "")[:200]
        logger.info("ai_query_telemetry %s", json.dumps(payload, default=str))
    except Exception as exc:
        logger.debug("log_query_telemetry failed: %s", exc)


def evaluate_golden_sql_checks(sql: str, checks: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Golden-case SQL substring checks (all upper-case matching).

    checks schema (optional keys):
      must_contain_any: [ ["2004"], ["FKDAT","BUDAT"] ]  — each inner list is OR
      must_contain_all: ["GROUP BY", "KUNAG"]
      must_not_contain: ["GJAHR = '2004'"]
    """
    failures: List[str] = []
    if not checks:
        return True, failures
    u = (sql or "").upper()
    for group in checks.get("must_contain_any") or ():
        if not group:
            continue
        if not any((str(alt) or "").upper() in u for alt in group if alt):
            failures.append(f"must_contain_any failed for {group!r}")
    for need in checks.get("must_contain_all") or ():
        if need and str(need).upper() not in u:
            failures.append(f"must_contain_all missing {need!r}")
    for ban in checks.get("must_not_contain") or ():
        if ban and str(ban).upper() in u:
            failures.append(f"must_not_contain violated {ban!r}")
    return (len(failures) == 0), failures
