"""
AI Query Memory Service - Find, store, and reuse user-approved question→SQL pairs.
Approved SQL is shared across all users (global).

Andy's training loop:
1. User asks question
2. Check ai_query_memory for similar question (any user's approval)
3. If match → use stored SQL
4. If no match and LLM fails → ChatGPT proposes SQL
5. User approves → store in ai_query_memory (visible to all users)
6. Execute and return
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import case
from sqlalchemy.orm import Session
from .ai_analysis_constraint_validator import extract_user_constraints
from .ai_intent_classifier import classify_intent

logger = logging.getLogger(__name__)

# Safe SQL: only allow SELECT, JOIN, GROUP BY, ORDER BY, LIMIT
DANGEROUS_PATTERNS = [
    r"\bDELETE\b", r"\bUPDATE\b", r"\bDROP\b", r"\bALTER\b", r"\bTRUNCATE\b",
    r"\bINSERT\b", r"\bCREATE\b", r"\bEXEC\b", r"\bEXECUTE\b", r";\s*--",
    r"\bINTO\b", r"\bGRANT\b", r"\bREVOKE\b",
]

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "get",
    "how", "i", "in", "is", "it", "list", "me", "of", "on", "or", "show",
    "the", "to", "what", "which", "with",
}

ENTITY_KEYWORDS = {
    "customer": {"customer", "customers", "client", "clients", "payer", "sold-to"},
    "vendor": {"vendor", "vendors", "supplier", "suppliers", "lifnr"},
    "material": {"material", "materials", "matnr"},
    "product": {"product", "products", "item", "items"},
    "invoice": {"invoice", "invoices", "billing", "billings", "vbrk", "vbrp"},
    "order": {"order", "orders", "purchase order", "po", "sales order"},
    "country": {"country", "countries"},
    "industry": {"industry", "industries", "sector"},
    "profit_center": {"profit center", "profit centres", "prctr"},
    "plant": {"plant", "plants", "werks"},
}

METRIC_KEYWORDS = {
    "revenue": {"revenue", "sales", "turnover", "invoice value", "billing value"},
    "count": {"count", "counts", "number", "volume", "how many"},
    "sum": {"sum", "total", "totals"},
    "average": {"average", "avg", "mean"},
    "quantity": {"quantity", "quantities", "qty", "billed quantity", "invoice quantity"},
    "profit": {"profit", "margin", "profitability"},
    "cost": {"cost", "costs", "cogs", "expense", "expenses", "spend"},
    "discount": {"discount", "discounts", "rebate", "rebates"},
    "trend": {"trend", "trends", "forecast", "forecasts"},
    "top": {"top", "highest", "best", "largest", "most"},
    "bottom": {"bottom", "lowest", "least", "smallest", "worst"},
}


def _normalize_question(q: str) -> str:
    """Normalize question for matching: lowercase, collapse whitespace."""
    if not q:
        return ""
    return " ".join(re.split(r"\s+", (q or "").lower().strip()))


def _tokenize_question(question: str) -> Set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_question(question))
        if token and token not in STOPWORDS and len(token) > 1
    }
    return tokens


def _extract_years_from_text(text: str) -> Set[str]:
    return set(re.findall(r"\b((?:19|20)\d{2})\b", text or ""))


def _extract_years_from_sql(sql: str) -> Set[str]:
    years = set(_extract_years_from_text(sql))
    for compact in re.findall(r"\b((?:19|20)\d{2})(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b", sql or ""):
        years.add(compact)
    return years


def _extract_keyword_hits(text: str, keyword_map: Dict[str, Set[str]]) -> Set[str]:
    normalized = _normalize_question(text)
    hits: Set[str] = set()
    for label, terms in keyword_map.items():
        if any(term in normalized for term in terms):
            hits.add(label)
    return hits


def _infer_time_scope(text: str) -> Optional[str]:
    normalized = _normalize_question(text)
    if _extract_years_from_text(normalized):
        return "specific_year"
    if any(term in normalized for term in {"historical", "history", "1994", "2010"}):
        return "historical"
    if any(term in normalized for term in {"all periods", "all years", "both", "overall"}):
        return "both"
    if any(term in normalized for term in {"current", "recent", "last 30 days", "today", "this month"}):
        return "current"
    return None


def _question_signature(question: str) -> Dict[str, Any]:
    c = extract_user_constraints(question or "")
    intent = classify_intent(question or "")
    return {
        "tokens": _tokenize_question(question),
        "entities": _extract_keyword_hits(question, ENTITY_KEYWORDS),
        "metrics": _extract_keyword_hits(question, METRIC_KEYWORDS),
        "years": _extract_years_from_text(question),
        "time_scope": _infer_time_scope(question),
        "intent_tags": set(intent.tags),
        "filter_fp": {
            "years": sorted(list(c.years)),
            "billing_category": c.billing_category or "",
            "billing_type": c.billing_type or "",
            "currency": c.currency_code or "",
            "wants_count": bool(c.wants_count),
            "wants_sum": bool(c.wants_sum),
            "wants_negative_lines": bool(c.wants_negative_lines),
        },
    }


def _sql_signature(sql: str) -> Dict[str, Any]:
    return {
        "years": _extract_years_from_sql(sql),
        "tables": {table.upper() for table in _extract_table_refs_from_sql(sql)},
    }


def _time_scope_compatible(target_scope: Optional[str], candidate_scope: Optional[str]) -> bool:
    if not target_scope or not candidate_scope:
        return True
    return target_scope == candidate_scope


def _signatures_are_compatible(
    target_signature: Dict[str, Any],
    candidate_signature: Dict[str, Any],
    sql_signature: Dict[str, Any],
) -> bool:
    target_years = set(target_signature["years"])
    candidate_years = set(candidate_signature["years"])
    sql_years = set(sql_signature["years"])

    if target_years:
        if sql_years and sql_years != target_years:
            return False
        if candidate_years and candidate_years != target_years:
            return False
    elif candidate_years or sql_years:
        return False

    if not _time_scope_compatible(target_signature["time_scope"], candidate_signature["time_scope"]):
        return False

    target_entities = set(target_signature["entities"])
    candidate_entities = set(candidate_signature["entities"])
    if target_entities and candidate_entities and not (target_entities & candidate_entities):
        return False

    actor_entities = {"customer", "vendor"}
    target_actors = target_entities & actor_entities
    candidate_actors = candidate_entities & actor_entities
    if target_actors and candidate_actors and target_actors != candidate_actors:
        return False

    # Intent family should overlap to allow paraphrase reuse, but avoid generic collisions.
    target_intents = set(target_signature.get("intent_tags") or set())
    candidate_intents = set(candidate_signature.get("intent_tags") or set())
    if target_intents and candidate_intents and not (target_intents & candidate_intents):
        return False

    # Filter fingerprint must match exactly for constrained fields.
    tf = target_signature.get("filter_fp") or {}
    cf = candidate_signature.get("filter_fp") or {}
    for k in ("years", "billing_category", "billing_type", "currency", "wants_count", "wants_sum", "wants_negative_lines"):
        tv = tf.get(k)
        cv = cf.get(k)
        if tv and cv and tv != cv:
            return False

    return True


def _similarity_score(
    question: str,
    record_question: str,
    record_sql: str,
    source: str,
    use_count: int,
) -> int:
    q_norm = _normalize_question(question)
    record_norm = _normalize_question(record_question)
    target_signature = _question_signature(question)
    candidate_signature = _question_signature(record_question)
    sql_signature = _sql_signature(record_sql)

    if not _signatures_are_compatible(target_signature, candidate_signature, sql_signature):
        return -1

    score = 0
    if q_norm == record_norm:
        score += 100
    elif record_norm and (record_norm in q_norm or q_norm in record_norm):
        score += 25

    token_overlap = len(target_signature["tokens"] & candidate_signature["tokens"])
    entity_overlap = len(target_signature["entities"] & candidate_signature["entities"])
    metric_overlap = len(target_signature["metrics"] & candidate_signature["metrics"])
    year_overlap = len(target_signature["years"] & candidate_signature["years"])

    score += token_overlap * 2
    score += entity_overlap * 10
    score += metric_overlap * 6
    score += year_overlap * 10
    score += min(max(use_count or 0, 0), 5)
    if source == "user":
        score += 3

    return score


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
    user_id: Optional[int] = None,
    mark_used: bool = True,
) -> Optional[str]:
    """
    Find a stored SQL for a similar question. Shared across all users.
    Uses conservative business-shape matching:
    - Exact normalized match first
    - Otherwise require compatible years, time scope, entities, and metrics
    - Then score candidates using token overlap plus usage/source preference
    """
    try:
        from ..models.ai_query_memory import AiQueryMemory
    except ImportError:
        return None

    q_norm = _normalize_question(question)
    if not q_norm:
        return None

    # 1) Exact match — shared globally; prefer user-approved SQL, then use_count, then most recent
    records = db.query(AiQueryMemory).filter(
        AiQueryMemory.question_pattern == q_norm,
    ).order_by(
        case((AiQueryMemory.source == "user", 0), else_=1),
        AiQueryMemory.use_count.desc(),
        AiQueryMemory.created_at.desc(),
    ).limit(1).all()

    if records:
        rec = records[0]
        if mark_used:
            rec.mark_used()
            db.commit()
        return rec.sql_query

    # 2) Conservative semantic-ish match: only reuse when the business shape aligns.
    all_records = db.query(AiQueryMemory).order_by(
        case((AiQueryMemory.source == "user", 0), else_=1),
        AiQueryMemory.use_count.desc(),
        AiQueryMemory.created_at.desc(),
    ).all()

    best_record = None
    best_score = -1
    for rec in all_records:
        record_question = rec.original_question or rec.question_pattern or ""
        score = _similarity_score(
            question=question,
            record_question=record_question,
            record_sql=rec.sql_query or "",
            source=rec.source or "",
            use_count=int(rec.use_count or 0),
        )
        if score > best_score:
            best_score = score
            best_record = rec

    # Require stronger overlap so different filters (year, category, currency) rarely reuse wrong SQL.
    if best_record is not None and best_score >= 17:
        if mark_used:
            best_record.mark_used()
            db.commit()
        logger.info(
            "Reused stored SQL with scored match: score=%s pattern=%r",
            best_score,
            (best_record.question_pattern or "")[:80],
        )
        return best_record.sql_query

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

    # Upsert: one record per question_pattern globally — update if exists, else insert
    existing = db.query(AiQueryMemory).filter(
        AiQueryMemory.question_pattern == q_norm[:500],
    ).first()

    if existing:
        existing.sql_query = sql_query
        existing.original_question = question[:2000] if question else None
        existing.tables_used = tables_used
        existing.source = source
        existing.model_used = model_used
        existing.approved_by_user_id = user_id
        db.commit()
        logger.info("Updated ai_query_memory: user=%s pattern=%r", user_id, q_norm[:80])
    else:
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


def _extract_table_refs_from_sql(sql: str) -> List[str]:
    """Extract table names from FROM and JOIN clauses (handles quoted identifiers)."""
    if not sql or not sql.strip():
        return []
    # Match: FROM "TABLE" / FROM table / JOIN "TABLE" / JOIN table
    # Also: FROM schema.table — we only want the table part for validation
    pattern = r'(?:FROM|JOIN)\s+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*)(?:\s|$|,|\)))'
    refs = []
    for m in re.finditer(pattern, sql, re.IGNORECASE):
        quoted, unquoted = m.group(1), m.group(2)
        name = (quoted or unquoted or "").strip()
        if name and name.upper() not in ("SELECT", "WHERE", "ON", "AND", "OR", "AS"):
            refs.append(name)
    return refs


def validate_sql_tables_against_schema(
    sql: str,
    available_tables: List[str],
) -> Tuple[bool, str]:
    """
    Check that all tables referenced in SQL exist in available_tables.
    Returns (True, "") if valid, else (False, error_message).
    Prevents MARA, MBEW, etc. from being used when not in the schema.
    """
    if not available_tables:
        return True, ""
    avail_upper = {t.upper() for t in available_tables}
    refs = _extract_table_refs_from_sql(sql)
    missing = [r for r in refs if r.upper() not in avail_upper]
    if missing:
        return False, f'SQL references table(s) not in schema: {", ".join(missing)}. Use only: {", ".join(sorted(available_tables)[:30])}{"..." if len(available_tables) > 30 else ""}'
    return True, ""
