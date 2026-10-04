"""
Smart Query Learner — auto-promotion, pre-joined views, failure feedback.

Three responsibilities:
1. ensure_sap_billing_view(sap_db)
   Creates `sap_billing_lines_v`, a permanent pre-joined VBRP+VBRK view.
   Every billing query can SELECT from this view instead of repeating the JOIN,
   which is the most common repeated structure in the SAP analytics workload.

2. auto_promote_successful_query(db, user_query, sql, row_count)
   When a query succeeds, extract its structural "shape" and save it as a
   learned pattern in ai_learned_patterns (usage-counted).  High-hit patterns
   can later be promoted to query_optimizer BUILTIN_PATTERNS.

3. log_query_failure(db, user_query, sql_attempted, failure_reason)
   Persists failures with a human-readable suggestion so the team can review
   and feed corrections back into the system (closes the training loop the
   previous architect described).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pre-joined SAP billing view
# ─────────────────────────────────────────────────────────────────────────────

_SAP_BILLING_VIEW_SQL = """
CREATE OR REPLACE VIEW sap_billing_lines_v AS
SELECT
    v."vbeln"  AS billing_doc,
    v."posnr"  AS line_item,
    v."netwr"  AS netwr_raw,
    v."fkimg"  AS quantity,
    v."meins"  AS unit,
    v."matnr"  AS material,
    v."arktx"  AS item_description,
    k."fkdat"  AS billing_date,
    k."waerk"  AS currency,
    k."kunag"  AS sold_to_party,
    k."fktyp"  AS billing_category,
    k."fkart"  AS billing_type,
    k."spart"  AS division,
    k."vkorg"  AS sales_org,
    k."vtweg"  AS distribution_channel,
    CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC) AS netwr_num,
    SUBSTRING(TRIM(k."fkdat"), 1, 4) AS billing_year,
    SUBSTRING(TRIM(k."fkdat"), 1, 6) AS billing_yearmonth
FROM "VBRP" v
JOIN "VBRK" k
  ON LPAD(TRIM(v."vbeln"), 10, '0') = LPAD(TRIM(k."vbeln"), 10, '0')
"""


def ensure_sap_billing_view(sap_db: Any) -> bool:
    """
    Create or replace the sap_billing_lines_v convenience view on the SAP database.

    Returns True on success, False on failure (safe to call on every startup —
    uses CREATE OR REPLACE so it is idempotent).
    """
    try:
        from sqlalchemy import text
        # Check that both base tables exist first to avoid errors on non-SAP DBs
        check = sap_db.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name IN ('VBRP','VBRK') AND table_schema = current_schema()"
            )
        ).scalar()
        if (check or 0) < 2:
            logger.debug("smart_query_learner: VBRP/VBRK not present — skipping billing view")
            return False

        sap_db.execute(text(_SAP_BILLING_VIEW_SQL))
        sap_db.commit()
        logger.info("✅ sap_billing_lines_v view created/refreshed")
        return True
    except Exception as exc:
        logger.warning("smart_query_learner: could not create billing view: %s", exc)
        try:
            sap_db.rollback()
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Auto-promote successful queries
# ─────────────────────────────────────────────────────────────────────────────

_ENSURE_LEARNED_PATTERNS_TABLE = """
CREATE TABLE IF NOT EXISTS ai_learned_patterns (
    id             BIGSERIAL PRIMARY KEY,
    pattern_hash   VARCHAR(16) NOT NULL UNIQUE,
    user_query_tpl TEXT NOT NULL,
    sql_template   TEXT NOT NULL,
    hit_count      INTEGER NOT NULL DEFAULT 1,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    avg_row_count  FLOAT NOT NULL DEFAULT 0,
    tables_used    JSONB NOT NULL DEFAULT '[]'
)
"""


def _ensure_learned_table(db: Any) -> None:
    from sqlalchemy import text
    try:
        db.execute(text(_ENSURE_LEARNED_PATTERNS_TABLE))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _extract_sql_tables(sql: str) -> List[str]:
    """Best-effort: extract table names FROM/JOIN clauses."""
    found = re.findall(r'\b(?:FROM|JOIN)\s+"?([A-Za-z0-9_]+)"?', sql, re.IGNORECASE)
    return sorted(set(t.upper() for t in found))


def _query_to_pattern_template(user_query: str) -> str:
    """
    Replace concrete values (years, currency codes, customer IDs) with placeholders
    to produce a reusable structural template.
    e.g.  "show me CAD sales for 2003"
        → "show me {currency} sales for {year}"
    """
    q = user_query or ""
    q = re.sub(r"\b(19|20)\d{2}\b", "{year}", q)
    q = re.sub(
        r"\b(USD|EUR|GBP|KRW|INR|JPY|AUD|CAD|CHF|CNY|SEK|NOK|DKK|BRL|MXN)\b",
        "{currency}",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"\b\d{6,}\b", "{id}", q)  # long numeric IDs
    return q.strip()


def _sql_to_template(sql: str) -> str:
    """Replace literal values with placeholders in SQL."""
    s = sql or ""
    s = re.sub(r"'(19|20)\d{2}'", "'{year}'", s)
    s = re.sub(
        r"'(USD|EUR|GBP|KRW|INR|JPY|AUD|CAD|CHF|CNY|SEK|NOK|DKK|BRL|MXN)'",
        "'{currency}'",
        s,
        flags=re.IGNORECASE,
    )
    return s


def _short_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]


def auto_promote_successful_query(
    db: Any,
    user_query: str,
    sql: str,
    row_count: int = 0,
) -> bool:
    """
    After a successful query, distil it into a pattern template and upsert
    into ai_learned_patterns (incrementing hit_count on repeat structures).

    This closes the "learning loop" — high-frequency patterns can later be
    promoted to BUILTIN_PATTERNS in query_optimizer.py.
    """
    try:
        _ensure_learned_table(db)
        from sqlalchemy import text

        query_tpl = _query_to_pattern_template(user_query)
        sql_tpl = _sql_to_template(sql)
        tables = _extract_sql_tables(sql)
        h = _short_hash(query_tpl.lower())
        now = datetime.now(timezone.utc)

        # Upsert: if same structural pattern seen before, increment hit_count
        upsert_sql = text("""
            INSERT INTO ai_learned_patterns
                (pattern_hash, user_query_tpl, sql_template, hit_count,
                 first_seen_at, last_used_at, avg_row_count, tables_used)
            VALUES
                (:ph, :qt, :st, 1, :now, :now, :rc, :tables)
            ON CONFLICT (pattern_hash) DO UPDATE SET
                hit_count    = ai_learned_patterns.hit_count + 1,
                last_used_at = EXCLUDED.last_used_at,
                avg_row_count = (ai_learned_patterns.avg_row_count *
                                 ai_learned_patterns.hit_count + EXCLUDED.avg_row_count)
                                / (ai_learned_patterns.hit_count + 1),
                sql_template = EXCLUDED.sql_template
        """)
        db.execute(upsert_sql, {
            "ph": h,
            "qt": query_tpl[:1000],
            "st": sql_tpl[:4000],
            "now": now,
            "rc": float(row_count),
            "tables": json.dumps(tables),
        })
        db.commit()
        logger.debug("smart_query_learner: promoted pattern %s (%s)", h, query_tpl[:60])
        return True
    except Exception as exc:
        logger.debug("smart_query_learner.auto_promote failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Failure logging with suggestions
# ─────────────────────────────────────────────────────────────────────────────

_ENSURE_FAILURE_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS ai_query_failures (
    id              BIGSERIAL PRIMARY KEY,
    user_query      TEXT NOT NULL,
    sql_attempted   TEXT,
    failure_reason  TEXT NOT NULL,
    suggestion      TEXT,
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure_failure_table(db: Any) -> None:
    from sqlalchemy import text
    try:
        db.execute(text(_ENSURE_FAILURE_LOG_TABLE))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _generate_failure_suggestion(user_query: str, sql_attempted: str, failure_reason: str) -> str:
    """
    Rule-based suggestion generation for common failure patterns.
    This allows the team to review and feed corrections back without LLM cost.
    """
    r = failure_reason or ""
    q = (user_query or "").lower()
    s = (sql_attempted or "").lower()

    suggestions: List[str] = []

    if "missing fkdat" in r.lower() or "year filter" in r.lower():
        suggestions.append(
            "Add a FKDAT-based year filter: WHERE SUBSTRING(TRIM(k.\"fkdat\"),1,4) = '<year>'"
        )
    if "waerk" in r.lower() or "currency filter" in r.lower():
        suggestions.append(
            "Add currency filter: WHERE k.\"waerk\" = '<code>'  (or IN ('CAD','USD') for multi-currency)"
        )
    if "sum()" in r.lower() or "no sum" in r.lower():
        suggestions.append(
            "Wrap netwr in SUM: SUM(CAST(NULLIF(TRIM(CAST(netwr AS TEXT)),'') AS NUMERIC))"
        )
    if "vbrp" not in s and ("invoice" in q or "line" in q or "netwr" in q):
        suggestions.append(
            "Query may need VBRP for line-item data. "
            "Try: FROM sap_billing_lines_v WHERE billing_year = '<year>'"
        )
    if "does not exist" in r.lower() or "relation" in r.lower():
        tables = re.findall(r'"([A-Z0-9_]+)"', sql_attempted or "")
        suggestions.append(
            f"Table not found. Confirm these tables exist in the SAP schema: {tables}. "
            "Check sap_table_schemas for available tables."
        )
    if not suggestions:
        suggestions.append(
            "Review the SQL and compare against sap_table_schemas. "
            "Common fixes: correct table names, add FKDAT year filter, "
            "add WAERK currency filter, use LPAD join for VBELN keys."
        )

    return "  |  ".join(suggestions)


def log_query_failure(
    db: Any,
    user_query: str,
    sql_attempted: Optional[str],
    failure_reason: str,
) -> bool:
    """
    Persist a query failure with an auto-generated suggestion.
    Reviewable via: SELECT * FROM ai_query_failures WHERE resolved = FALSE ORDER BY created_at DESC;
    """
    try:
        _ensure_failure_table(db)
        from sqlalchemy import text

        suggestion = _generate_failure_suggestion(user_query, sql_attempted or "", failure_reason)
        db.execute(
            text("""
                INSERT INTO ai_query_failures
                    (user_query, sql_attempted, failure_reason, suggestion, created_at)
                VALUES
                    (:uq, :sa, :fr, :sg, :now)
            """),
            {
                "uq": (user_query or "")[:2000],
                "sa": (sql_attempted or "")[:4000],
                "fr": (failure_reason or "")[:2000],
                "sg": suggestion[:2000],
                "now": datetime.now(timezone.utc),
            },
        )
        db.commit()
        logger.debug("smart_query_learner: logged failure for %r", (user_query or "")[:80])
        return True
    except Exception as exc:
        logger.debug("smart_query_learner.log_query_failure failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Top patterns report (for promotion to BUILTIN_PATTERNS)
# ─────────────────────────────────────────────────────────────────────────────

def get_top_learned_patterns(db: Any, min_hits: int = 3, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Return the most frequently used query patterns — these are candidates for
    promotion to query_optimizer.BUILTIN_PATTERNS.
    """
    try:
        from sqlalchemy import text
        rows = db.execute(
            text("""
                SELECT pattern_hash, user_query_tpl, sql_template,
                       hit_count, avg_row_count, tables_used, last_used_at
                FROM ai_learned_patterns
                WHERE hit_count >= :min_hits
                ORDER BY hit_count DESC, last_used_at DESC
                LIMIT :lim
            """),
            {"min_hits": min_hits, "lim": limit},
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("smart_query_learner.get_top_learned_patterns failed: %s", exc)
        return []
