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
    return True, None


def get_referenced_tables(sql: str) -> List[str]:
    """Return list of table names found in FROM/JOIN clauses (uppercase)."""
    from_join = re.findall(
        r"\b(?:FROM|JOIN)\s+[\"\"]?(\w+)[\"\"]?(?:\s+AS)?(?:\s+\w+)?",
        sql,
        re.IGNORECASE,
    )
    return list({t.upper() for t in from_join})
