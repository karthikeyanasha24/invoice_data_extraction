"""
Chat Thread Store — persistent per-user, per-session turn storage.

Each "thread" is one contiguous chat session.  Within a thread, every turn
stores enough structured context so that a follow-up query can be answered
WITHOUT re-running SQL:

  - The narrative reply (markdown text shown to the user)
  - The executed SQL (if any)
  - A compressed result snapshot: aggregates + first N rows + column names
  - Warnings that were raised (mixed currency, risky aggregate, etc.)
  - Key metrics computed at answer time (total, count, currency breakdown)
  - Session metadata: time_scope, date range, dominant currency/year

The follow-up prompt is built from these stored artifacts, not from
rebuilding full context.  This is the "ChatGPT-style memory" the user asked
for — follow-up answers stay grounded in the *same result set* as the
previous question.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_TURNS_TABLE = """
CREATE TABLE IF NOT EXISTS ai_chat_turns (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    thread_id       TEXT NOT NULL,
    turn_index      INTEGER NOT NULL,
    role            TEXT NOT NULL,           -- 'user' | 'assistant'
    content         TEXT NOT NULL,           -- raw message text
    -- Structured result artifact (assistant turns only)
    sql_executed    TEXT,
    result_rows     JSONB,                   -- first 30 rows
    result_columns  JSONB,                   -- list of column names
    key_metrics     JSONB,                   -- e.g. {total_sales: 1.5B, row_count: 34}
    warnings        JSONB,                   -- list of warning strings
    charts          JSONB,                   -- chart specs
    -- Session metadata
    time_scope      TEXT,
    date_range      TEXT,
    dominant_currency TEXT,
    dominant_year   TEXT,
    query_mode      TEXT,                    -- 'new' | 'follow_up'
    action          TEXT,                    -- orchestrator action
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, thread_id, turn_index, role)
)
"""

_CREATE_THREADS_TABLE = """
CREATE TABLE IF NOT EXISTS ai_chat_threads (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    thread_id       TEXT NOT NULL UNIQUE,
    title           TEXT,                    -- auto-generated from first question
    turn_count      INTEGER NOT NULL DEFAULT 0,
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def ensure_chat_tables(db: Any) -> None:
    """Idempotent — safe to call on every startup."""
    from sqlalchemy import text
    try:
        db.execute(text(_CREATE_THREADS_TABLE))
        db.execute(text(_CREATE_TURNS_TABLE))
        # Index for fast per-user thread lookup
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chat_turns_user_thread "
            "ON ai_chat_turns (user_id, thread_id, turn_index)"
        ))
        db.commit()
        # Required for save_turn ON CONFLICT if the table predates the inline UNIQUE
        try:
            db.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_chat_turns_user_tid_idx_role "
                "ON ai_chat_turns (user_id, thread_id, turn_index, role)"
            ))
            db.commit()
        except Exception as idx_exc:
            logger.debug("chat_thread_store unique index (optional): %s", idx_exc)
            try:
                db.rollback()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("chat_thread_store.ensure_chat_tables: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Write helpers
# ─────────────────────────────────────────────────────────────────────────────

def _j(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return None


def save_turn(
    db: Any,
    *,
    user_id: int,
    thread_id: str,
    turn_index: int,
    role: str,                          # 'user' | 'assistant'
    content: str,
    sql_executed: Optional[str] = None,
    result_rows: Optional[List[Dict]] = None,
    result_columns: Optional[List[str]] = None,
    key_metrics: Optional[Dict] = None,
    warnings: Optional[List[str]] = None,
    charts: Optional[Any] = None,
    time_scope: Optional[str] = None,
    date_range: Optional[str] = None,
    dominant_currency: Optional[str] = None,
    dominant_year: Optional[str] = None,
    query_mode: Optional[str] = None,
    action: Optional[str] = None,
) -> bool:
    """Upsert one turn.  Returns True on success."""
    from sqlalchemy import text
    try:
        ensure_chat_tables(db)
        now = datetime.now(timezone.utc)

        db.execute(text("""
            INSERT INTO ai_chat_turns
                (user_id, thread_id, turn_index, role, content,
                 sql_executed, result_rows, result_columns, key_metrics,
                 warnings, charts, time_scope, date_range,
                 dominant_currency, dominant_year, query_mode, action, created_at)
            VALUES
                (:uid, :tid, :ti, :role, :content,
                 :sql, :rows, :cols, :metrics,
                 :warns, :charts, :ts, :dr,
                 :dc, :dy, :qm, :act, :now)
            ON CONFLICT (user_id, thread_id, turn_index, role) DO UPDATE SET
                content            = EXCLUDED.content,
                sql_executed       = EXCLUDED.sql_executed,
                result_rows        = EXCLUDED.result_rows,
                result_columns     = EXCLUDED.result_columns,
                key_metrics        = EXCLUDED.key_metrics,
                warnings           = EXCLUDED.warnings,
                charts             = EXCLUDED.charts,
                time_scope         = EXCLUDED.time_scope,
                date_range         = EXCLUDED.date_range,
                dominant_currency  = EXCLUDED.dominant_currency,
                dominant_year      = EXCLUDED.dominant_year,
                query_mode         = EXCLUDED.query_mode,
                action             = EXCLUDED.action
        """), {
            "uid": user_id, "tid": thread_id, "ti": turn_index,
            "role": role, "content": (content or "")[:10000],
            "sql": (sql_executed or "")[:5000] or None,
            "rows": _j(result_rows[:30] if result_rows else None),
            "cols": _j(result_columns),
            "metrics": _j(key_metrics),
            "warns": _j(warnings),
            "charts": _j(charts),
            "ts": time_scope, "dr": date_range,
            "dc": dominant_currency, "dy": dominant_year,
            "qm": query_mode, "act": action,
            "now": now,
        })

        # Keep thread metadata up to date
        db.execute(text("""
            INSERT INTO ai_chat_threads
                (user_id, thread_id, title, turn_count, last_active_at, created_at)
            VALUES (:uid, :tid, :title, 1, :now, :now)
            ON CONFLICT (thread_id) DO UPDATE SET
                turn_count    = GREATEST(ai_chat_threads.turn_count + 1, EXCLUDED.turn_count),
                last_active_at = EXCLUDED.last_active_at,
                title = COALESCE(ai_chat_threads.title, EXCLUDED.title)
        """), {
            "uid": user_id, "tid": thread_id,
            "title": (content or "")[:100], "now": now,
        })

        db.commit()
        return True
    except Exception as exc:
        logger.warning("chat_thread_store.save_turn failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_thread(
    db: Any,
    user_id: int,
    thread_id: str,
    last_n: int = 10,
) -> List[Dict[str, Any]]:
    """Return the last N turns for a thread, ordered oldest-first."""
    from sqlalchemy import text
    try:
        ensure_chat_tables(db)
        rows = db.execute(text("""
            SELECT role, content, sql_executed, result_rows, result_columns,
                   key_metrics, warnings, charts, dominant_currency, dominant_year,
                   time_scope, query_mode, action, turn_index
            FROM ai_chat_turns
            WHERE user_id = :uid AND thread_id = :tid
            ORDER BY turn_index DESC
            LIMIT :n
        """), {"uid": user_id, "tid": thread_id, "n": last_n}).mappings().all()

        def _decode(row: Any) -> Dict:
            r = dict(row)
            for key in ("result_rows", "result_columns", "key_metrics", "warnings", "charts"):
                v = r.get(key)
                if isinstance(v, str):
                    try:
                        r[key] = json.loads(v)
                    except Exception:
                        r[key] = None
            return r

        return list(reversed([_decode(r) for r in rows]))
    except Exception as exc:
        logger.debug("chat_thread_store.load_thread: %s", exc)
        return []


def get_last_assistant_turn(
    db: Any,
    user_id: int,
    thread_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent assistant turn (with full result artifact)."""
    turns = load_thread(db, user_id, thread_id, last_n=20)
    for t in reversed(turns):
        if t.get("role") == "assistant":
            return t
    return None


def next_turn_index(
    db: Any,
    user_id: int,
    thread_id: str,
) -> int:
    """Return the next sequential turn index for this thread."""
    from sqlalchemy import text
    try:
        ensure_chat_tables(db)
        result = db.execute(text("""
            SELECT COALESCE(MAX(turn_index), -1) + 1
            FROM ai_chat_turns
            WHERE user_id = :uid AND thread_id = :tid
        """), {"uid": user_id, "tid": thread_id}).scalar()
        return int(result or 0)
    except Exception:
        return 0


def thread_owner_user_id(db: Any, thread_id: str) -> Optional[int]:
    """If the thread exists in ai_chat_threads, return its user_id; else None."""
    from sqlalchemy import text
    try:
        ensure_chat_tables(db)
        row = db.execute(
            text("SELECT user_id FROM ai_chat_threads WHERE thread_id = :tid"),
            {"tid": thread_id},
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def latest_schema_chat_thread_id(db: Any, user_id: int) -> Optional[str]:
    """
    Most recently touched Schema Chat thread (sch_*) for this user.
    Used when the browser sends thread_id=null but still has in-memory history.
    """
    from sqlalchemy import text
    try:
        ensure_chat_tables(db)
        row = db.execute(
            text(
                """
                SELECT thread_id FROM ai_chat_threads
                WHERE user_id = :uid AND thread_id ~ '^sch_'
                ORDER BY last_active_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            ),
            {"uid": user_id},
        ).scalar()
        return str(row).strip() if row else None
    except Exception as exc:
        logger.debug("latest_schema_chat_thread_id: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Follow-up prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def build_followup_prompt(
    user_query: str,
    thread_turns: List[Dict[str, Any]],
) -> str:
    """
    Build the LLM prompt for a follow-up question.
    Grounds the answer in the structured artifacts from the last assistant turn
    (result rows, SQL, key metrics, warnings) instead of re-running SQL.
    """
    # Find the most recent assistant turn with result data
    last_assistant = None
    for t in reversed(thread_turns):
        if t.get("role") == "assistant" and (t.get("result_rows") or t.get("content")):
            last_assistant = t
            break

    # Build conversation snippet (last 6 turns)
    convo_lines: List[str] = []
    for t in thread_turns[-6:]:
        role_label = "User" if t["role"] == "user" else "Assistant"
        convo_lines.append(f"{role_label}: {(t['content'] or '')[:400]}")
    convo_block = "\n".join(convo_lines) if convo_lines else "(no prior turns)"

    # Build result artifact block
    artifact_block = "(no prior result data)"
    if last_assistant:
        parts: List[str] = []

        metrics = last_assistant.get("key_metrics") or {}
        if metrics:
            parts.append("**Key metrics from last query:**")
            for k, v in metrics.items():
                parts.append(f"  - {k}: {v}")

        sql = last_assistant.get("sql_executed")
        if sql:
            parts.append(f"\n**SQL that was run:**\n```sql\n{sql[:1500]}\n```")

        cols = last_assistant.get("result_columns") or []
        rows = last_assistant.get("result_rows") or []
        if rows:
            parts.append(f"\n**Result sample ({len(rows)} rows, columns: {cols}):**")
            parts.append(json.dumps(rows[:15], default=str)[:3000])

        warns = last_assistant.get("warnings") or []
        if warns:
            parts.append("\n**Warnings from that query:**")
            for w in warns:
                parts.append(f"  ⚠️ {w}")

        meta_parts = []
        if last_assistant.get("dominant_currency"):
            meta_parts.append(f"currency={last_assistant['dominant_currency']}")
        if last_assistant.get("dominant_year"):
            meta_parts.append(f"year={last_assistant['dominant_year']}")
        if last_assistant.get("time_scope"):
            meta_parts.append(f"scope={last_assistant['time_scope']}")
        if meta_parts:
            parts.append(f"\n**Query context:** {', '.join(meta_parts)}")

        artifact_block = "\n".join(parts) if parts else "(assistant turn had no structured data)"

    prompt = f"""You are a helpful business analyst assistant answering a follow-up question.

The user is continuing a conversation. Do NOT run new SQL — answer only from the conversation
history and the result data already loaded (shown below).

If the user's question genuinely cannot be answered from the existing data (e.g. they ask for
a different year, different filter, or data not in the result), say so clearly and suggest they
switch to "New question" mode to run a fresh query.

──────────────────────────────────────
CONVERSATION SO FAR:
{convo_block}
──────────────────────────────────────
PRIOR RESULT DATA:
{artifact_block}
──────────────────────────────────────
FOLLOW-UP QUESTION:
{user_query}
──────────────────────────────────────

Answer concisely. Use **bold** for numbers. Use > blockquotes for key takeaways.
Prefix numerical answers with the correct currency symbol ($ USD, ₩ KRW, € EUR, £ GBP)
or 3-letter code — never $ for non-USD.
If you cite a number, state which query/result it came from.
If answering requires NEW data not in the result above, respond with:
  "This follow-up needs fresh data — please switch to **New question** mode and ask: [reworded question]"
"""
    return prompt
