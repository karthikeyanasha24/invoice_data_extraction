"""
AI Query Memory Service - Find, store, and reuse user-approved question→SQL pairs.

Andy's training loop:
1. User asks question
2. Check ai_query_memory for similar question
3. If match → use stored SQL
4. If no match and LLM fails → ChatGPT proposes SQL
5. User approves → store in ai_query_memory
6. Execute and return
"""
from __future__ import annotations

import re
import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Safe SQL: only allow SELECT, JOIN, GROUP BY, ORDER BY, LIMIT
DANGEROUS_PATTERNS = [
    r"\bDELETE\b", r"\bUPDATE\b", r"\bDROP\b", r"\bALTER\b", r"\bTRUNCATE\b",
    r"\bINSERT\b", r"\bCREATE\b", r"\bEXEC\b", r"\bEXECUTE\b", r";\s*--",
    r"\bINTO\b", r"\bGRANT\b", r"\bREVOKE\b",
]


def _normalize_question(q: str) -> str:
    """Normalize question for matching: lowercase, collapse whitespace."""
    if not q:
        return ""
    return " ".join(re.split(r"\s+", (q or "").lower().strip()))


def _validate_sql_safe(sql: str) -> Tuple[bool, str]:
    """
    Validate that SQL is safe (read-only). Returns (is_valid, error_message).
    """
    if not sql or not sql.strip():
        return False, "Empty SQL"
    sql_upper = sql.upper()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper, re.IGNORECASE):
            return False, f"SQL contains forbidden operation: {pattern}"
    if not re.search(r"\bSELECT\b", sql_upper):
        return False, "SQL must be a SELECT query"
    return True, ""


def find_similar_stored_query(
    db: Session,
    question: str,
    user_id: int,
) -> Optional[str]:
    """
    Find a stored SQL for a similar question. Uses simple similarity:
    - Exact match on normalized question
    - Substring match if question contains the stored pattern
    """
    try:
        from ..models.ai_query_memory import AiQueryMemory
    except ImportError:
        return None

    q_norm = _normalize_question(question)
    if not q_norm:
        return None

    # 1) Exact match
    records = db.query(AiQueryMemory).filter(
        AiQueryMemory.user_id == user_id,
        AiQueryMemory.question_pattern == q_norm,
    ).order_by(AiQueryMemory.use_count.desc()).limit(1).all()

    if records:
        rec = records[0]
        rec.mark_used()
        db.commit()
        return rec.sql_query

    # 2) Substring match: stored pattern is contained in question
    all_records = db.query(AiQueryMemory).filter(
        AiQueryMemory.user_id == user_id,
    ).all()

    for rec in all_records:
        pattern_norm = _normalize_question(rec.question_pattern)
        if pattern_norm and pattern_norm in q_norm:
            rec.mark_used()
            db.commit()
            return rec.sql_query

    return None


def store_approved_query(
    db: Session,
    user_id: int,
    question: str,
    sql_query: str,
    source: str = "chatgpt",
    model_used: Optional[str] = None,
    tables_used: Optional[List[str]] = None,
) -> bool:
    """Store user-approved question→SQL pair. Returns True on success."""
    try:
        from ..models.ai_query_memory import AiQueryMemory
    except ImportError:
        logger.warning("AiQueryMemory model not available")
        return False

    is_valid, err = _validate_sql_safe(sql_query)
    if not is_valid:
        logger.warning("Rejected store: %s", err)
        return False

    q_norm = _normalize_question(question)
    if not q_norm:
        return False

    rec = AiQueryMemory(
        user_id=user_id,
        question_pattern=q_norm[:500],
        original_question=question[:2000] if question else None,
        sql_query=sql_query,
        tables_used=tables_used,
        source=source,
        model_used=model_used,
        approved_by_user_id=user_id,
    )
    db.add(rec)
    db.commit()
    logger.info("Stored ai_query_memory: user=%s pattern=%r", user_id, q_norm[:80])
    return True


def validate_sql_for_safe_execution(sql: str) -> Tuple[bool, str]:
    """Public API for validating SQL before execution."""
    return _validate_sql_safe(sql)
