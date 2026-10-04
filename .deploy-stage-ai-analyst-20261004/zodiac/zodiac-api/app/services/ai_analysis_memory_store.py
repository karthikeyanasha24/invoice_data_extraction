import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class AiAnalysisMemory:
    user_id: int
    last_user_query: str = ""
    last_sql: str = ""
    last_rows_json: str = "[]"
    last_reply: str = ""
    last_charts_json: str = "[]"
    knowledge_json: str = "{}"
    updated_at: Optional[datetime] = None
    # Conversation context fields — carry forward currency/year across follow-up queries
    last_currency: str = ""   # e.g. "CAD", "EUR", "USD"
    last_year: str = ""       # e.g. "2000", "2003"

    def last_rows(self) -> list[dict]:
        try:
            val = json.loads(self.last_rows_json or "[]")
            return val if isinstance(val, list) else []
        except Exception:
            return []
    
    def last_charts(self) -> list[dict]:
        try:
            val = json.loads(self.last_charts_json or "[]")
            return val if isinstance(val, list) else []
        except Exception:
            return []

    def knowledge(self) -> Dict[str, Any]:
        try:
            val = json.loads(self.knowledge_json or "{}")
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}


_IN_MEMORY_FALLBACK: dict[int, AiAnalysisMemory] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_ai_analysis_memory_table(db: Session) -> None:
    """
    Create the memory table if it doesn't exist.
    We do this at runtime because this repo doesn't use migrations,
    and serverless deploys need idempotent startup.
    """
    try:
        # Roll back any failed transaction first
        db.rollback()
        
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ai_analysis_memory (
                  user_id BIGINT PRIMARY KEY,
                  last_user_query TEXT NULL,
                  last_sql TEXT NULL,
                  last_rows_json TEXT NULL,
                  last_reply TEXT NULL,
                  last_charts_json TEXT NULL,
                  knowledge_json TEXT NULL,
                  updated_at TIMESTAMPTZ NULL
                )
                """
            )
        )
        # Add new columns if they don't exist (for existing tables)
        db.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'ai_analysis_memory' AND column_name = 'last_reply'
                    ) THEN
                        ALTER TABLE ai_analysis_memory ADD COLUMN last_reply TEXT NULL;
                    END IF;
                    IF NOT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'ai_analysis_memory' AND column_name = 'last_charts_json'
                    ) THEN
                        ALTER TABLE ai_analysis_memory ADD COLUMN last_charts_json TEXT NULL;
                    END IF;
                    IF NOT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'ai_analysis_memory' AND column_name = 'last_currency'
                    ) THEN
                        ALTER TABLE ai_analysis_memory ADD COLUMN last_currency TEXT NULL;
                    END IF;
                    IF NOT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'ai_analysis_memory' AND column_name = 'last_year'
                    ) THEN
                        ALTER TABLE ai_analysis_memory ADD COLUMN last_year TEXT NULL;
                    END IF;
                END $$;
                """
            )
        )
        db.commit()
    except Exception as e:
        logger.debug(f"Could not ensure memory table: {e}")
        db.rollback()


def load_memory(db: Session, user_id: int) -> AiAnalysisMemory:
    try:
        ensure_ai_analysis_memory_table(db)
        row = db.execute(
            text(
                """
                SELECT user_id, last_user_query, last_sql, last_rows_json, last_reply,
                       last_charts_json, knowledge_json, updated_at,
                       last_currency, last_year
                FROM ai_analysis_memory
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        if not row:
            mem = AiAnalysisMemory(user_id=user_id, updated_at=_now_utc())
            save_memory(db, mem)
            return mem
        return AiAnalysisMemory(
            user_id=int(row["user_id"]),
            last_user_query=row.get("last_user_query") or "",
            last_sql=row.get("last_sql") or "",
            last_rows_json=row.get("last_rows_json") or "[]",
            last_reply=row.get("last_reply") or "",
            last_charts_json=row.get("last_charts_json") or "[]",
            knowledge_json=row.get("knowledge_json") or "{}",
            updated_at=row.get("updated_at"),
            last_currency=row.get("last_currency") or "",
            last_year=row.get("last_year") or "",
        )
    except Exception as e:
        logger.warning("AI memory load failed; using in-memory fallback: %s", e)
        return _IN_MEMORY_FALLBACK.get(user_id) or AiAnalysisMemory(user_id=user_id, updated_at=_now_utc())


def save_memory(db: Session, mem: AiAnalysisMemory) -> None:
    mem.updated_at = _now_utc()
    try:
        ensure_ai_analysis_memory_table(db)
        db.execute(
            text(
                """
                INSERT INTO ai_analysis_memory (user_id, last_user_query, last_sql, last_rows_json,
                       last_reply, last_charts_json, knowledge_json, updated_at, last_currency, last_year)
                VALUES (:user_id, :last_user_query, :last_sql, :last_rows_json,
                       :last_reply, :last_charts_json, :knowledge_json, :updated_at, :last_currency, :last_year)
                ON CONFLICT (user_id) DO UPDATE SET
                  last_user_query = EXCLUDED.last_user_query,
                  last_sql = EXCLUDED.last_sql,
                  last_rows_json = EXCLUDED.last_rows_json,
                  last_reply = EXCLUDED.last_reply,
                  last_charts_json = EXCLUDED.last_charts_json,
                  knowledge_json = EXCLUDED.knowledge_json,
                  updated_at = EXCLUDED.updated_at,
                  last_currency = EXCLUDED.last_currency,
                  last_year = EXCLUDED.last_year
                """
            ),
            {
                "user_id": mem.user_id,
                "last_user_query": mem.last_user_query,
                "last_sql": mem.last_sql,
                "last_rows_json": mem.last_rows_json,
                "last_reply": mem.last_reply,
                "last_charts_json": mem.last_charts_json,
                "knowledge_json": mem.knowledge_json,
                "updated_at": mem.updated_at,
                "last_currency": mem.last_currency,
                "last_year": mem.last_year,
            },
        )
        db.commit()
        _IN_MEMORY_FALLBACK[mem.user_id] = mem
    except Exception as e:
        logger.warning("AI memory save failed; using in-memory fallback: %s", e)
        _IN_MEMORY_FALLBACK[mem.user_id] = mem


def extract_query_currency(question: str) -> str:
    """
    Extract ISO 4217 currency code from a user question.
    Returns empty string if none found.
    Examples: "show me CAD sales" → "CAD", "revenue in EUR" → "EUR"
    """
    import re
    _CURRENCIES = {
        "CAD", "USD", "EUR", "GBP", "MXN", "JPY", "AUD", "CHF", "CNY", "BRL",
        "INR", "KRW", "SEK", "NOK", "DKK", "SGD", "HKD", "PLN", "CZK", "HUF",
        "TRY", "ZAR", "RUB", "NZD", "IDR", "MYR", "THB", "PHP",
    }
    q = question or ""
    # Match: "in CAD", "currency CAD", "CAD sales", "CAD dollars", etc.
    for pattern in (
        r"\bin\s+([A-Z]{3})\b",
        r"\bcurrency\s*[=:]?\s*([A-Z]{3})\b",
        r"\b([A-Z]{3})\s+(?:sales|revenue|dollars|currency|amount)\b",
        r"\b([A-Z]{3})\b",  # bare 3-letter currency as last resort
    ):
        for m in re.finditer(pattern, q):
            code = m.group(1).upper()
            if code in _CURRENCIES:
                return code
    return ""


def extract_query_year(question: str) -> str:
    """
    Extract 4-digit year from a user question.
    Returns empty string if none found.
    """
    import re
    m = re.search(r"\b((?:19|20)\d{2})\b", question or "")
    return m.group(1) if m else ""


def detect_follow_up_clarification(
    current_query: str,
    mem: "AiAnalysisMemory",
) -> Optional[str]:
    """
    Detect when a follow-up query is underspecified given conversation context.

    Returns a clarifying question string if clarification is needed, or None if the
    query is self-contained and should proceed to SQL generation.

    Examples:
    - User asked "show me CAD sales 2000", then asks "show me 2003"
      → "Are you still looking for CAD sales? Or would you like a different currency?"
    - User asked "show me 2003 revenue", then asks "what about EUR?"
      → "Should I show you EUR revenue for 2003, or a different year?"
    """
    import re

    cur_q = (current_query or "").strip()
    if not cur_q:
        return None

    # Only trigger for short/partial queries — if the question is long it's probably self-contained
    if len(cur_q.split()) > 12:
        return None

    last_q = (mem.last_user_query or "").strip()
    if not last_q:
        return None

    # Extract from both queries
    cur_currency = extract_query_currency(cur_q)
    cur_year = extract_query_year(cur_q)
    prev_currency = mem.last_currency or extract_query_currency(last_q)
    prev_year = mem.last_year or extract_query_year(last_q)

    # Pattern 1: current has year but no currency; previous had currency
    if cur_year and not cur_currency and prev_currency:
        return (
            f"Just to confirm — are you still looking for **{prev_currency}** sales "
            f"(from your previous question), but now for **{cur_year}**? "
            f"Or would you like a different currency?"
        )

    # Pattern 2: current has currency but no year; previous had year
    if cur_currency and not cur_year and prev_year:
        return (
            f"Got it. Should I show **{cur_currency}** data for **{prev_year}** "
            f"(same year as before), or a different year?"
        )

    # Pattern 3: very short query with just a year ("show me 2003", "what about 2005")
    short_year_only = bool(
        re.match(r"^(?:show me|what about|and|also|for|now|try)\s+((?:19|20)\d{2})\b.*$", cur_q, re.IGNORECASE)
        and not cur_currency
        and len(cur_q.split()) <= 5
    )
    if short_year_only and prev_currency:
        return (
            f"Are you still asking about **{prev_currency}** sales? "
            f"Just confirming before I run the query for **{cur_year or ''}**."
        )

    return None


def upsert_knowledge(db: Session, user_id: int, key: str, value: Any) -> AiAnalysisMemory:
    mem = load_memory(db, user_id)
    knowledge = mem.knowledge()
    knowledge[key] = value
    mem.knowledge_json = json.dumps(knowledge, default=str)
    save_memory(db, mem)
    return mem


SCHEMA_CHAT_KNOWLEDGE_KEY = "schema_chat"
_MAX_SCHEMA_CHAT_SNAPSHOT_MESSAGES = 50


def schema_chat_messages_from_knowledge(mem: AiAnalysisMemory, thread_id: str) -> list[dict]:
    """
    Backup transcript stored in knowledge_json (ai_analysis_memory) for Schema Chat.
    Used when ai_chat_turns is empty or unavailable for the same thread_id.
    """
    try:
        block = mem.knowledge().get(SCHEMA_CHAT_KNOWLEDGE_KEY) or {}
        if not isinstance(block, dict):
            return []
        if (block.get("thread_id") or "") != thread_id:
            return []
        msgs = block.get("messages") or []
        if not isinstance(msgs, list):
            return []
        out: list[dict] = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role, content = m.get("role"), m.get("content")
            if role in ("user", "assistant") and content and str(content).strip():
                out.append({"role": role, "content": str(content)[:8000]})
        return out
    except Exception:
        return []


def save_schema_chat_snapshot_to_memory(
    db: Session,
    user_id: int,
    thread_id: str,
    messages: list[dict],
) -> None:
    """Mirror schema-chat into ai_analysis_memory.knowledge_json (per-user, survives tab switches)."""
    try:
        mem = load_memory(db, user_id)
        k = mem.knowledge()
        clean: list[dict] = []
        for m in messages[-_MAX_SCHEMA_CHAT_SNAPSHOT_MESSAGES:]:
            if not isinstance(m, dict):
                continue
            role, content = m.get("role"), m.get("content")
            if role in ("user", "assistant") and content and str(content).strip():
                clean.append({"role": role, "content": str(content)[:8000]})
        k[SCHEMA_CHAT_KNOWLEDGE_KEY] = {
            "thread_id": thread_id,
            "messages": clean,
            "updated_at": _now_utc().isoformat(),
        }
        mem.knowledge_json = json.dumps(k, default=str)
        save_memory(db, mem)
    except Exception as exc:
        logger.warning("save_schema_chat_snapshot_to_memory failed: %s", exc)

