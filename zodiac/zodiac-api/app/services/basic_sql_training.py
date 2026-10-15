"""Persistent, explicitly manual SQL examples for the separate Basic Training mode."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select, insert, update, delete
from sqlalchemy.orm import Session

metadata = MetaData()
runs = Table("ai_basic_sql_training_runs", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", Integer, nullable=False, index=True),
    Column("scope_digest", String(64), nullable=False), Column("source", String(32), nullable=False),
    Column("question", Text, nullable=False), Column("schema_json", Text, nullable=False),
    Column("sql", Text, nullable=False), Column("status", String(32), nullable=False),
    Column("columns_json", Text, nullable=False), Column("rows_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False))
examples = Table("ai_basic_sql_training_examples", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", Integer, nullable=False, index=True),
    Column("scope_digest", String(64), nullable=False), Column("source", String(32), nullable=False),
    Column("question", Text, nullable=False), Column("schema_json", Text, nullable=False),
    Column("sql", Text, nullable=False), Column("dialect", String(32), nullable=False),
    Column("revision", Integer, nullable=False), Column("history_json", Text, nullable=False),
    Column("validation_status", String(32), nullable=False), Column("updated_at", String(40), nullable=False))


def _digest(scope) -> str:
    from .analyst_drilldown import scope_digest
    return scope_digest(scope)


def ensure_tables(engine):
    metadata.create_all(engine, tables=[runs, examples])


def save_run(engine, scope, run_id: str, question: str) -> dict:
    ensure_tables(engine)
    with Session(engine) as session:
        row = session.execute(select(runs).where(runs.c.id == run_id,
            runs.c.user_id == scope.user_id, runs.c.scope_digest == _digest(scope),
            runs.c.status == "executed")).mappings().first()
        if not row:
            raise PermissionError("Select a successful SQL Training execution owned by your account")
        if question.strip() != row["question"].strip():
            raise ValueError("The saved question must match the question used for this execution")
        identity = hashlib.sha256((str(scope.user_id) + _digest(scope) + row["source"] + row["question"].casefold()).encode()).hexdigest()
        prior = session.execute(select(examples).where(examples.c.id == identity)).mappings().first()
        now = datetime.now(timezone.utc).isoformat()
        values = {"user_id": scope.user_id, "scope_digest": _digest(scope), "source": row["source"],
            "question": row["question"], "schema_json": row["schema_json"], "sql": row["sql"],
            "dialect": "postgres", "revision": 1, "history_json": "[]",
            "validation_status": "executed", "updated_at": now}
        if prior:
            history = json.loads(prior["history_json"] or "[]")
            history.append({"revision": prior["revision"], "sql": prior["sql"], "updated_at": prior["updated_at"]})
            values.update(revision=prior["revision"] + 1, history_json=json.dumps(history[-20:]))
            session.execute(update(examples).where(examples.c.id == identity).values(**values))
        else:
            session.execute(insert(examples).values(id=identity, **values))
        session.commit()
        return {"id": identity, "question": row["question"], "revision": values["revision"], "saved": True}


def list_examples(engine, scope, query=""):
    ensure_tables(engine)
    with Session(engine) as session:
        statement = select(examples).where(examples.c.user_id == scope.user_id,
            examples.c.scope_digest == _digest(scope)).order_by(examples.c.updated_at.desc()).limit(200)
        rows = session.execute(statement).mappings().all()
        needle = query.casefold().strip()
        return [{**{key: row[key] for key in ("id", "source", "question", "sql", "dialect", "revision", "validation_status", "updated_at")},
                 "schema": json.loads(row["schema_json"]), "history": json.loads(row["history_json"] or "[]")}
                for row in rows if not needle or needle in row["question"].casefold() or needle in row["sql"].casefold()]


def edit_example(engine, scope, identifier, sql):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 24000:
        raise ValueError("Enter a SQL statement up to 24000 characters")
    ensure_tables(engine)
    with Session(engine) as session:
        row = session.execute(select(examples).where(examples.c.id == identifier,
            examples.c.user_id == scope.user_id, examples.c.scope_digest == _digest(scope))).mappings().first()
        if not row:
            raise PermissionError("Training example is not available in your workspace")
        history = json.loads(row["history_json"] or "[]")
        history.append({"revision": row["revision"], "sql": row["sql"], "updated_at": row["updated_at"]})
        session.execute(update(examples).where(examples.c.id == identifier).values(
            sql=sql.strip(), revision=row["revision"] + 1, history_json=json.dumps(history[-20:]),
            validation_status="needs_validation", updated_at=datetime.now(timezone.utc).isoformat()))
        session.commit()
    return {"saved": True, "revision": row["revision"] + 1, "validation_status": "needs_validation"}


def delete_example(engine, scope, identifier):
    ensure_tables(engine)
    with Session(engine) as session:
        result = session.execute(delete(examples).where(examples.c.id == identifier,
            examples.c.user_id == scope.user_id, examples.c.scope_digest == _digest(scope)))
        session.commit()
        return bool(result.rowcount)


def selected_schema(schema, selected):
    requested = selected if isinstance(selected, dict) else {}
    output = {}
    index = {str(table).lower(): (str(table), cols) for table, cols in (schema or {}).items()}
    for table_name, requested_cols in requested.items():
        found = index.get(str(table_name).lower())
        if not found or not isinstance(requested_cols, list):
            raise ValueError("Selected tables or columns are not in the accessible schema")
        original, cols = found
        by_name = {str(c.get("col", "")).lower(): c for c in cols if isinstance(c, dict)}
        selected_cols = []
        for name in requested_cols:
            col = by_name.get(str(name).lower())
            if not col:
                raise ValueError("Selected tables or columns are not in the accessible schema")
            selected_cols.append({"col": col.get("col"), "type": col.get("type", "unknown")})
        output[original] = selected_cols
    return output


def check_query_scope(sql: str, selection: dict):
    # Reuse the same SQLGlot boundary as model-generated SQL. It enforces one
    # read-only SELECT/WITH, validates every physical table/column, expands safe
    # stars, and correctly handles CTEs and aliases against the selected subset.
    from .analyst_agent_sql import validate_agent_sql
    from sqlglot.errors import SqlglotError
    try:
        safe_sql, _tables = validate_agent_sql(sql, selection)
        return safe_sql
    except SqlglotError as error:
        raise ValueError("SQL syntax could not be parsed; review the statement and selected schema") from error


def record_run(engine, scope, source, question, schema, sql, result):
    ensure_tables(engine)
    identifier = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    rows = result.get("rows") or []
    with Session(engine) as session:
        session.execute(insert(runs).values(id=identifier, user_id=scope.user_id, scope_digest=_digest(scope),
            source=source, question=question, schema_json=json.dumps(schema), sql=result.get("sql") or sql,
            status="executed" if result.get("ok") else "failed",
            columns_json=json.dumps(list(rows[0].keys()) if rows else []), rows_json=json.dumps(rows[:500], default=str), created_at=now))
        session.commit()
    return identifier
