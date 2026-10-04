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
from .ai_query_plan import extract_query_plan, fingerprints_compatible

logger = logging.getLogger(__name__)

# Fuzzy reuse floor — score alone is insufficient; plan fingerprints must also match (R5).
MEMORY_REUSE_SCORE_THRESHOLD = 24

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

# These entities represent specific dimensional intent. Reusing a stored SQL that
# introduces one of these dimensions when the new question does not ask for it
# causes "industry/country/etc." drift and irrelevant answers.
SCOPED_DIMENSION_ENTITIES = {"industry", "country", "profit_center", "plant"}

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
    if not target_entities and (candidate_entities & SCOPED_DIMENSION_ENTITIES):
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


def _plan_fingerprint_for_question(question: str, sql: str = "") -> str:
    return extract_query_plan(question or "", sql or "").fingerprint()


def _memory_entry_is_suspicious(question: str, sql: str) -> bool:
    """
    Soft-classify contaminated memory without deleting rows.
    Suspicious entries must never be reused.
    """
    q = (question or "").strip()
    s = (sql or "").strip().lower()
    if not q or not s:
        return True
    # Raw SQL stored as the "question"
    if re.match(r"^\s*select\b", q, re.I):
        return True
    # Known contaminated industry mapping via material master
    if "mara" in s and "mbrsh" in s and any(
        t in q.lower() for t in ("industry", "sector", "customer")
    ):
        return True
    if "gjahr" in s and re.search(r"\b((?:19|20)\d{2})\b", q):
        return True
    # Extremely long instructional blobs are not reusable questions
    if len(q) > 500 and "select" in q.lower():
        return True
    return False


def _sql_is_poisoned_for_question(question: str, sql: str) -> bool:
    """
    Return True if this cached SQL contains patterns incompatible with the current question.
    Used as a gate before any cached SQL is reused, preventing "query contamination" where
    an old approved query leaks irrelevant tables/logic into a new, unrelated question.

    Checks (all are definite wrong-answer sources):
    1. T016T (industry table) in SQL when question does not mention industry/sector.
    2. VBRK.gjahr used for billing-year filter (always unreliable — should use fkdat).
    3. vbrp.posnr in GROUP BY when question asks for invoice count (item-level inflation).
    4. Hardcoded year in SQL that conflicts with a different year in the question.
    5. SQL has vbrp.netwr in WHERE for zero/negative invoice intent (header-level bug).
    """
    if not sql or not question:
        return False
    q = question.lower()
    s = sql.lower()

    # 1. Industry table leakage
    asks_industry = any(tok in q for tok in ("industry", "sector", "brsch"))
    if '"t016t"' in s and not asks_industry:
        logger.info("Cache poison: T016T in SQL but question does not ask for industry. Rejecting.")
        return True

    # 2. VBRK.gjahr used as billing-year filter (data is often '0000' — always unreliable)
    if ('"vbrk"' in s or 'vbrk' in s) and '"gjahr"' in s:
        if 'fkdat' not in s:
            logger.info("Cache poison: VBRK.gjahr without fkdat — unreliable year logic. Rejecting.")
            return True

    # 3. Item-level invoice count via vbrp.posnr grouping
    asks_invoice_count = "invoice count" in q or ("count" in q and "invoice" in q)
    if asks_invoice_count and '"posnr"' in s:
        logger.info("Cache poison: vbrp.posnr in SQL for invoice-count question. Rejecting.")
        return True

    # 4. Hardcoded year in SQL conflicts with a different year in the question
    sql_years = _extract_years_from_sql(sql)
    q_years = _extract_years_from_text(question)
    if q_years and sql_years and not q_years.intersection(sql_years):
        logger.info(
            "Cache poison: SQL has years %s but question asks for years %s. Rejecting.",
            sql_years, q_years,
        )
        return True

    # 5. Zero/negative invoice: SQL filters on vbrp.netwr instead of VBRK.netwr
    asks_zero_negative = any(tok in q for tok in ("zero", "negative")) and any(
        tok in q for tok in ("invoice", "billing")
    )
    if asks_zero_negative:
        # SQL should have WHERE on VBRK.netwr, not group/aggregate on vbrp
        if '"vbrp"' in s and '"vbrk"' not in s:
            logger.info("Cache poison: zero/negative invoice query uses vbrp without VBRK. Rejecting.")
            return True
        has_vbrk_where_filter = bool(
            re.search(r'\bwhere\b[\s\S]{0,800}vbrk[\s\S]{0,60}netwr', s)
        )
        if not has_vbrk_where_filter and '"vbrk"' in s:
            logger.info("Cache poison: zero/negative query missing VBRK.netwr WHERE filter. Rejecting.")
            return True

    # 6. Contaminated / suspicious memory entries
    if _memory_entry_is_suspicious(question, sql):
        logger.info("Cache poison: suspicious memory entry rejected.")
        return True

    # 7. Plan fingerprint mismatch (metric/dims/years/grain/operation)
    try:
        q_fp = _plan_fingerprint_for_question(question)
        # Fingerprint the stored SQL's implied question using both texts when available
        # Compatibility is checked in find_similar against record question fingerprint.
    except Exception:
        q_fp = ""

    return False


def find_similar_stored_query(
    db: Session,
    question: str,
    user_id: Optional[int] = None,
    mark_used: bool = True,
) -> Optional[str]:
    """
    Find a stored SQL for a similar question. Shared across all users.
    Uses conservative business-shape matching + R5 plan fingerprints:
    - Exact normalized match first
    - Otherwise require compatible years, time scope, entities, and metrics
    - Plan fingerprints must match (metric/dimensions/filters/grain/operation)
    - Then score candidates; reuse only if score >= MEMORY_REUSE_SCORE_THRESHOLD
    - Poison-check: cached SQL incompatible with this question is rejected
    """
    try:
        from ..models.ai_query_memory import AiQueryMemory
    except ImportError:
        return None

    q_norm = _normalize_question(question)
    if not q_norm:
        return None

    question_fp = _plan_fingerprint_for_question(question)

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
        candidate_sql = rec.sql_query or ""
        record_q = rec.original_question or rec.question_pattern or ""
        record_fp = _plan_fingerprint_for_question(record_q, candidate_sql)
        if _sql_is_poisoned_for_question(question, candidate_sql):
            logger.warning(
                "Exact-match cache hit rejected by poison-check for question: %r", q_norm[:80]
            )
        elif not fingerprints_compatible(question_fp, record_fp):
            logger.warning(
                "Exact-match cache hit rejected by plan fingerprint mismatch: %s vs %s",
                question_fp,
                record_fp,
            )
        else:
            if mark_used:
                rec.mark_used()
                db.commit()
            return candidate_sql

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
        candidate_sql = rec.sql_query or ""
        if _sql_is_poisoned_for_question(question, candidate_sql):
            continue
        record_fp = _plan_fingerprint_for_question(record_question, candidate_sql)
        if not fingerprints_compatible(question_fp, record_fp):
            continue
        score = _similarity_score(
            question=question,
            record_question=record_question,
            record_sql=candidate_sql,
            source=rec.source or "",
            use_count=int(rec.use_count or 0),
        )
        if score > best_score:
            best_score = score
            best_record = rec

    if best_record is not None and best_score >= MEMORY_REUSE_SCORE_THRESHOLD:
        if mark_used:
            best_record.mark_used()
            db.commit()
        logger.info(
            "Reused stored SQL with scored+fingerprint match: score=%s pattern=%r fp=%s",
            best_score,
            (best_record.question_pattern or "")[:80],
            question_fp,
        )
        return best_record.sql_query

    return None


def classify_memory_entry(question: str, sql: str) -> str:
    """
    Classify a memory row for cleanup tooling: valid | suspicious | incompatible | raw_sql.
    Non-destructive — does not delete.
    """
    q = (question or "").strip()
    s = (sql or "").strip()
    if re.match(r"^\s*select\b", q, re.I):
        return "raw_sql"
    if _memory_entry_is_suspicious(q, s):
        return "suspicious"
    if _sql_is_poisoned_for_question(q, s):
        return "incompatible"
    is_valid, _err = _validate_sql_safe(s)
    if not is_valid:
        return "incompatible"
    return "valid"


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
