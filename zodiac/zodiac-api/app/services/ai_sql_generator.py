from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from .schema_context_builder import build_schema_context

try:
    from openai import OpenAI
    _openai_available = True
except ImportError:  # pragma: no cover - runtime dependency
    OpenAI = None  # type: ignore
    _openai_available = False


def _get_openai_client() -> "OpenAI":
    """
    Lazily create an OpenAI client.

    ImportError is handled at module import time so that missing `openai`
    does not break API startup (e.g. on Vercel where the package might
    not be installed). Instead, we fail only when this functionality is
    actually invoked.
    """
    if not _openai_available or OpenAI is None:
        raise RuntimeError(
            "OpenAI Python package is not installed. "
            "AI SQL generation is currently unavailable."
        )

    return OpenAI()


def generate_sql(question: str) -> str:
    """
    Use the OpenAI API to generate a SELECT-only PostgreSQL query
    based on the current schema and a natural-language question.
    """
    schema_context = build_schema_context()

    prompt = f"""
You are a PostgreSQL expert.

Generate a SQL query for the user question below.

Rules:
- Use ONLY the tables and columns listed in the schema.
- Use proper joins between tables.
- PostgreSQL syntax.
- SELECT queries ONLY (no INSERT/UPDATE/DELETE/DDL).
- Prefer including a LIMIT 50 when returning many rows.

Schema:
{schema_context}

Question:
{question}

Return ONLY the SQL. No explanation, no markdown.
"""

    client = _get_openai_client()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    sql = (response.choices[0].message.content or "").strip()
    return sql


def run_sql(db: Session, sql: str) -> List[Dict[str, Any]]:
    """
    Execute a generated SQL query safely against the given SQLAlchemy Session.
    Only SELECT statements are allowed.
    """
    lowered = sql.strip().lower()
    if not lowered.startswith("select"):
        raise ValueError("Only SELECT statements are allowed")

    # Basic safety: reject obviously dangerous keywords
    forbidden = [" update ", " delete ", " insert ", " drop ", " alter ", " truncate "]
    if any(k in lowered for k in forbidden):
        raise ValueError("Refusing to execute potentially dangerous SQL")

    result = db.execute(text(sql)).mappings().all()
    return [dict(row) for row in result]

