"""Persist returned SQL evidence independently of trusted analytical memory."""
from __future__ import annotations

from typing import Any, Dict


_EVIDENCE_FIELDS = ("sql", "attempted_sql", "source_sql", "sql_status", "failure_class")


def sql_evidence_from_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    """Keep reported query text and status; do not infer execution from an answer."""
    evidence = {
        key: value.strip()
        for key in _EVIDENCE_FIELDS
        if isinstance(value := payload.get(key), str) and value.strip()
    }
    meta = payload.get("meta")
    if not evidence.get("failure_class") and isinstance(meta, dict):
        failure = meta.get("failure_class")
        if isinstance(failure, str) and failure.strip():
            evidence["failure_class"] = failure.strip()
    return evidence


def sql_evidence_from_stored_turn(turn: Dict[str, Any]) -> Dict[str, str]:
    """Restore evidence for disclosure without promoting it to a result anchor."""
    metrics = turn.get("key_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    saved = metrics.get("sql_evidence")
    evidence = sql_evidence_from_payload(saved if isinstance(saved, dict) else {})
    if not evidence.get("sql"):
        legacy_sql = turn.get("sql_executed")
        if isinstance(legacy_sql, str) and legacy_sql.strip():
            evidence["sql"] = legacy_sql.strip()
            # Older adaptive writes used this column for returned SQL without
            # storing its execution status. Preserve the text without claiming
            # it ran, especially when its turn failed validation.
            evidence.setdefault("sql_status", "execution_unverified")
    if not evidence.get("failure_class"):
        failure = sql_evidence_from_payload(metrics).get("failure_class")
        if failure:
            evidence["failure_class"] = failure
    return evidence
