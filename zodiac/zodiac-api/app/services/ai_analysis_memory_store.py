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
    knowledge_json: str = "{}"
    updated_at: Optional[datetime] = None

    def last_rows(self) -> list[dict]:
        try:
            val = json.loads(self.last_rows_json or "[]")
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
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_analysis_memory (
              user_id BIGINT PRIMARY KEY,
              last_user_query TEXT NULL,
              last_sql TEXT NULL,
              last_rows_json TEXT NULL,
              knowledge_json TEXT NULL,
              updated_at TIMESTAMPTZ NULL
            )
            """
        )
    )
    db.commit()


def load_memory(db: Session, user_id: int) -> AiAnalysisMemory:
    try:
        ensure_ai_analysis_memory_table(db)
        row = db.execute(
            text(
                """
                SELECT user_id, last_user_query, last_sql, last_rows_json, knowledge_json, updated_at
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
            knowledge_json=row.get("knowledge_json") or "{}",
            updated_at=row.get("updated_at"),
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
                INSERT INTO ai_analysis_memory (user_id, last_user_query, last_sql, last_rows_json, knowledge_json, updated_at)
                VALUES (:user_id, :last_user_query, :last_sql, :last_rows_json, :knowledge_json, :updated_at)
                ON CONFLICT (user_id) DO UPDATE SET
                  last_user_query = EXCLUDED.last_user_query,
                  last_sql = EXCLUDED.last_sql,
                  last_rows_json = EXCLUDED.last_rows_json,
                  knowledge_json = EXCLUDED.knowledge_json,
                  updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "user_id": mem.user_id,
                "last_user_query": mem.last_user_query,
                "last_sql": mem.last_sql,
                "last_rows_json": mem.last_rows_json,
                "knowledge_json": mem.knowledge_json,
                "updated_at": mem.updated_at,
            },
        )
        db.commit()
        _IN_MEMORY_FALLBACK[mem.user_id] = mem
    except Exception as e:
        logger.warning("AI memory save failed; using in-memory fallback: %s", e)
        _IN_MEMORY_FALLBACK[mem.user_id] = mem


def upsert_knowledge(db: Session, user_id: int, key: str, value: Any) -> AiAnalysisMemory:
    mem = load_memory(db, user_id)
    knowledge = mem.knowledge()
    knowledge[key] = value
    mem.knowledge_json = json.dumps(knowledge, default=str)
    save_memory(db, mem)
    return mem

