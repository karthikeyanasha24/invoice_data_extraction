"""Database boundary for model-chosen SQL, independent of prompt obedience."""
from __future__ import annotations

import re
from typing import Any

from sqlglot import exp, parse
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.schema import MappingSchema

from .adaptive_trusted_scope import USER_SCOPED_TABLES, get_trusted_scope

MAX_RESULT_ROWS = 200
_SECRET_COLUMN = re.compile(
    r"(?:password|passwd|secret|credential|private_key|api_key|access_token|refresh_token|"
    r"auth_token|token_hash|\btoken\b|jwt|connection_string|database_url|certificate_key)", re.I,
)
_PRIVATE_TABLE = re.compile(
    r"(?:^|_)(?:users?|credentials?|secrets?|tokens?|sessions?|certificates?|"
    r"permissions?|roles?|settings|connections?)(?:_|$)", re.I,
)
_ANONYMOUS_FUNCTIONS = {
    "TO_CHAR", "DATE_PART", "DATE_TRUNC", "MAKE_DATE", "REGEXP_REPLACE",
    "REGEXP_MATCH", "REGEXP_MATCHES", "SPLIT_PART", "CONCAT_WS", "STRING_AGG",
    "JSONB_EXTRACT_PATH_TEXT", "JSON_EXTRACT_PATH_TEXT", "JSONB_ARRAY_LENGTH",
    "JSON_ARRAY_LENGTH", "AGE", "ISFINITE", "MD5", "BTRIM", "LTRIM", "RTRIM",
}


def queryable_schema(schema: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Credential/config tables and secret columns never enter model SQL tools."""
    result = {}
    for table, columns in schema.items():
        if _PRIVATE_TABLE.search(table) or table.lower().startswith(("pg_", "sql_")):
            continue
        safe = []
        for column in columns:
            name = str(column.get("col") or column.get("name") or "")
            if name and not _SECRET_COLUMN.search(name):
                safe.append({"col": name, "type": str(column.get("type") or "text")})
        if safe:
            result[table] = safe
    return result


def _sql_tree(sql: str):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 24000:
        raise ValueError("Provide one SELECT query of at most 24000 characters")
    statements = [tree for tree in parse(sql, read="postgres") if tree is not None]
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("Only one read-only SELECT or WITH query is allowed")
    tree = statements[0]
    forbidden = {"Insert", "Delete", "Update", "Merge", "Create", "Drop", "Alter", "Command", "Into", "Lock", "Copy", "Transaction"}
    for node in tree.walk():
        if type(node).__name__ in forbidden:
            raise ValueError("Writes, SELECT INTO, locks, and commands are not allowed")
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise ValueError("Recursive queries are not available to the analyst")
        if isinstance(node, (exp.Placeholder, exp.Parameter)):
            raise ValueError("Model SQL cannot supply execution parameters")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).upper()
            if name.startswith(("PG_", "DBLINK", "LO_")) or name in {"SET_CONFIG", "SLEEP", "CURRENT_SETTING", "CURRENT_USER", "SESSION_USER"}:
                raise ValueError("Database administration and external-access functions are not allowed")
            if isinstance(node, exp.Anonymous) and name not in _ANONYMOUS_FUNCTIONS:
                raise ValueError(f"Function {name} is not an approved analytical function")
    return tree


def validate_agent_sql(sql: str, schema: dict[str, Any]) -> tuple[str, list[str]]:
    """Resolve sources/columns against the exact tool-visible schema, then bound rows."""
    tree = _sql_tree(sql)
    safe_schema = queryable_schema(schema)
    table_index = {name.lower(): name for name in safe_schema}
    sources = []
    for scope in traverse_scope(tree):
        for _alias, (_node, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table):
                continue  # CTE/subquery sources have their own checked scopes.
            if source.catalog or source.db or not isinstance(source.this, exp.Identifier):
                raise ValueError("Use unqualified tables from the connected catalog")
            actual = table_index.get(source.name.lower())
            if actual is None:
                raise ValueError(f"Table {source.name} is not available to the analyst SQL tool")
            source.set("this", exp.to_identifier(actual, quoted=True))
            if actual not in sources:
                sources.append(actual)
    if not sources:
        raise ValueError("Use the calculator for arithmetic; SQL must read a catalog table")
    mapping = MappingSchema(
        {table: {col["col"]: "TEXT" for col in cols} for table, cols in safe_schema.items()},
        dialect="postgres", normalize=False,
    )
    # Expanding stars against safe_schema prevents SELECT * leaking credentials.
    tree = qualify(tree, dialect="postgres", schema=mapping, infer_schema=False)
    limit = tree.args.get("limit")
    if limit:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int or int(value.this) < 1:
            raise ValueError("LIMIT must be a positive integer")
        bound = min(int(value.this), MAX_RESULT_ROWS + 1)
    else:
        bound = MAX_RESULT_ROWS + 1
    tree = tree.limit(bound, copy=False)
    offset = tree.args.get("offset")
    if offset and (not isinstance(offset.expression, exp.Literal) or not offset.expression.is_int or not 0 <= int(offset.expression.this) <= 10000):
        raise ValueError("OFFSET must be an integer between 0 and 10000")
    return tree.sql(dialect="postgres"), sources


def enforce_agent_user_scope(sql: str, schema: dict[str, Any]) -> tuple[str, dict[str, int]]:
    """Filter every physical owner-scoped relation before joins, CTEs, OR, or UNION."""
    # Validation happened before execution sanitization. Re-parse its result and
    # wrap base sources rather than injecting a predicate in the outer SELECT.
    tree = parse(sql, read="postgres")[0]
    index = {name.lower(): (name, columns) for name, columns in schema.items()}
    parameters = {}
    trusted = get_trusted_scope()
    sources = []
    for scope in traverse_scope(tree):
        for _alias, (_node, source) in scope.selected_sources.items():
            if isinstance(source, exp.Table):
                sources.append(source)
    for source in sources:
        actual, columns = index.get(source.name.lower(), (source.name, []))
        owner = next((str(c.get("col") or c.get("name")) for c in columns if str(c.get("col") or c.get("name") or "").lower() == "user_id"), None)
        if actual.lower() in USER_SCOPED_TABLES and not owner:
            raise PermissionError("User-scoped table is missing its ownership field")
        if not owner:
            continue
        if trusted is None or trusted.user_id <= 0:
            raise PermissionError("Authenticated execution scope is required for application data")
        parameters["_trusted_agent_user_id"] = int(trusted.user_id)
        base = source.copy()
        base.set("alias", None)
        filtered = exp.select("*").from_(base).where(exp.EQ(
            this=exp.column(owner, quoted=True),
            expression=exp.Placeholder(this="_trusted_agent_user_id"),
        ))
        source.replace(filtered.subquery(alias=source.alias_or_name))
    return tree.sql(dialect="postgres"), parameters
