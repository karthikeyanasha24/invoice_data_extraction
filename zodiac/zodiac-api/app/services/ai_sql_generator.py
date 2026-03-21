from typing import Any, Dict, List

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from .schema_context_builder import build_schema_context


client = OpenAI()


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


