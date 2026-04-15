"""
Validate generated SQL against the actual schema: tables and columns must exist.
Prevents hallucinated table/column names.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def validate_sql(
    sql: str,
    schema: Dict[str, List[str]],
) -> Tuple[bool, Optional[str]]:
    """
    Check that all tables (and optionally columns) referenced in SQL exist in schema.
    Returns (is_valid, error_message).
    """
    if not sql or not schema:
        return False, "Missing SQL or schema"

    sql_clean = (sql or "").strip()
    if not re.match(r"^\s*select\b", sql_clean, flags=re.IGNORECASE):
        return False, "Only SELECT statements are allowed"

    schema_upper = {k.upper(): k for k in schema}
    tables_in_schema = set(schema_upper.keys())

    # Extract table names from FROM and JOIN (simple regex; no full parser)
    # Match: FROM table alias, JOIN table alias, from "table", join "table"
    from_join = re.findall(
        r"\b(?:FROM|JOIN)\s+[\"\"]?(\w+)[\"\"]?(?:\s+AS)?(?:\s+\w+)?",
        sql,
        re.IGNORECASE,
    )
    tables_used = {t.upper() for t in from_join}

    for tbl in tables_used:
        if tbl not in tables_in_schema:
            return False, f"Table '{tbl}' is not in the schema"

    # Build alias -> table map
    alias_matches = re.findall(
        r"\b(?:FROM|JOIN)\s+[\"\"]?(\w+)[\"\"]?(?:\s+AS)?(?:\s+(\w+))?",
        sql,
        re.IGNORECASE,
    )
    alias_to_table: Dict[str, str] = {}
    for table_name, alias in alias_matches:
        t_upper = table_name.upper()
        if t_upper not in schema_upper:
            continue
        actual_table = schema_upper[t_upper]
        alias_to_table[actual_table.lower()] = actual_table
        alias_to_table[actual_table.upper()] = actual_table
        alias_to_table[actual_table] = actual_table
        if alias:
            alias_to_table[alias] = actual_table
            alias_to_table[alias.lower()] = actual_table
            alias_to_table[alias.upper()] = actual_table

    # Validate table.column references where possible
    refs = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.\"?([A-Za-z_][A-Za-z0-9_]*)\"?\b", sql)
    for left, col in refs:
        table_for_ref = alias_to_table.get(left) or alias_to_table.get(left.lower()) or alias_to_table.get(left.upper())
        if not table_for_ref:
            continue
        valid_cols = schema.get(table_for_ref) or []
        valid_lower = {c.lower() for c in valid_cols}
        if col.lower() not in valid_lower:
            return False, f"Column '{table_for_ref}.{col}' is not in the schema"
    return True, None


def get_referenced_tables(sql: str) -> List[str]:
    """Return list of table names found in FROM/JOIN clauses (uppercase)."""
    from_join = re.findall(
        r"\b(?:FROM|JOIN)\s+[\"\"]?(\w+)[\"\"]?(?:\s+AS)?(?:\s+\w+)?",
        sql,
        re.IGNORECASE,
    )
    return list({t.upper() for t in from_join})
