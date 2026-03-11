from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import json
import logging
import re

from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover - runtime/env dependent
    OpenAI = None  # type: ignore


logger = logging.getLogger(__name__)


@dataclass
class SqlAgentResult:
    sql: str
    rows: List[Dict[str, Any]]


def _get_openai_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. `pip install openai` is required.")
    return OpenAI()


def _inspect_schema(session: Session) -> Dict[str, List[str]]:
    """
    Inspect the live database via SQLAlchemy and build a simple schema mapping:

        { "table_name": ["col1", "col2", ...], ... }

    Table and column names are preserved exactly as reported by the inspector.
    """
    engine = session.get_bind()
    if engine is None:
        raise RuntimeError("Session is not bound to an engine.")

    inspector = inspect(engine)
    schema: Dict[str, List[str]] = {}

    for table_name in inspector.get_table_names():
        cols = inspector.get_columns(table_name)
        col_names: List[str] = []
        for col in cols:
            name = col.get("name")
            if isinstance(name, str):
                col_names.append(name)
        schema[table_name] = col_names

    return schema


def _build_schema_prompt(schema: Dict[str, List[str]]) -> str:
    """
    Turn the inspected schema into a compact text prompt.

    Format:
        Database schema:
        table_a(col1, col2, col3)
        table_b(col1, col2)
    """
    lines = ["Database schema:"]
    for table, cols in sorted(schema.items()):
        col_list = ", ".join(cols)
        lines.append(f'{table}({col_list})')
    return "\n".join(lines)


def _gen_sql_from_question(question: str, schema_prompt: str, client: OpenAI) -> str:
    """
    Ask the LLM to turn a natural language question into a single SQL SELECT query.
    """
    prompt = f"""
You are a PostgreSQL expert.

You are given the full database schema.
Your task is to convert the user's natural language question into ONE executable SQL query.

Rules:
* Use only tables and columns listed in the schema.
* Column names are case sensitive.
* Always quote identifiers like "table"."column".
* Never invent tables or columns.
* If searching text, use ILIKE with wildcard patterns.
* Only generate SELECT queries.
* Do not generate INSERT, UPDATE, DELETE, DROP, or ALTER statements.
* Return SQL only with no explanation.

{schema_prompt}

User question:
{question}
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        top_p=1,
        max_tokens=800,
    )
    sql = (resp.choices[0].message.content or "").strip()
    # Strip accidental markdown fences if the model added them anyway
    if "```" in sql:
        m = re.search(r"```(?:sql)?\s*(.*?)```", sql, flags=re.DOTALL | re.IGNORECASE)
        if m:
            sql = m.group(1).strip()
    return sql


_DML_DDL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER)\b",
    flags=re.IGNORECASE,
)


def _validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Basic safety validation:
    - Non-empty
    - Starts with SELECT (ignoring whitespace and parentheses)
    - Does not contain dangerous DML/DDL verbs.
    """
    cleaned = sql.strip()
    if not cleaned:
        return False, "Empty SQL generated."

    # Allow for leading parentheses/newlines but require SELECT as first keyword.
    leading = re.sub(r"^[\s(]+", "", cleaned)
    if not leading.upper().startswith("SELECT"):
        return False, "Only SELECT queries are allowed."

    if _DML_DDL_PATTERN.search(cleaned):
        return False, "DML/DDL statements are not allowed."

    return True, ""


def _run_sql(session: Session, sql: str) -> List[Dict[str, Any]]:
    """
    Execute SQL and return list[dict] rows.
    """
    logger.info("Executing SQL:\n%s", sql)
    result = session.execute(text(sql))
    rows = result.fetchall()
    keys = list(result.keys())
    out: List[Dict[str, Any]] = []
    for row in rows:
        record: Dict[str, Any] = {}
        for k, v in zip(keys, row):
            # Basic JSON-safe conversion
            try:
                json.dumps(v)
                record[k] = v
            except TypeError:
                record[k] = str(v)
        out.append(record)
    logger.info("SQL returned %s row(s).", len(out))
    return out


def run_sap_sql_agent(question: str, session: Session) -> SqlAgentResult:
    """
    Natural language -> SQL -> DB -> rows pipeline.

    This function:
        1. Inspects the live database schema.
        2. Builds a schema prompt.
        3. Uses an LLM to generate a single SQL SELECT query.
        4. Validates the SQL.
        5. Executes it via SQLAlchemy.
        6. Returns SqlAgentResult(sql, rows).
    """
    schema = _inspect_schema(session)
    schema_prompt = _build_schema_prompt(schema)

    client = _get_openai_client()
    sql = _gen_sql_from_question(question, schema_prompt, client)

    logger.info("Generated SQL:\n%s", sql)
    is_valid, reason = _validate_sql(sql)
    if not is_valid:
        logger.warning("Rejected SQL: %s", reason)
        return SqlAgentResult(sql=sql, rows=[])

    try:
        rows = _run_sql(session, sql)
    except Exception as exc:  # pragma: no cover - runtime DB errors
        logger.exception("SQL execution failed: %s", exc)
        return SqlAgentResult(sql=sql, rows=[])

    return SqlAgentResult(sql=sql, rows=rows)

