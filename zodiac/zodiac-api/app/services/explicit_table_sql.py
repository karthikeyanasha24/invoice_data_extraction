"""
Explicit table name handling for AI SQL paths.

When the user names a table (backticks, quotes, FROM/JOIN, or plain identifiers),
that intent must override generic keyword routing (e.g. "last rows" must not
substitute unrelated SAP tables like LFA1).

App tables listed in schema_ai_config.json skip_tables live on the main app DB,
not the SAP read replica — they are excluded from get_schema_dict and must be
queried via Session on the invoice app database.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .schema_loader import _load_schema_ai_config

logger = logging.getLogger(__name__)

# Common English / query noise — not table names (length-3+ tokens only are blocked).
_TABLE_STOPWORDS: Set[str] = {
    "the", "and", "for", "are", "not", "has", "any", "all", "new", "old", "get",
    "set", "sum", "top", "last", "first", "rows", "row", "list", "show", "from",
    "join", "where", "when", "what", "with", "that", "this", "your", "user",
    "data", "sales", "year", "month", "week", "day", "how", "why", "did", "can",
    "our", "out", "but", "may", "now", "use", "see", "way", "too", "sql", "sap",
    "per", "each", "some", "most", "least", "into", "over", "than", "then",
    "between", "having", "group", "order", "limit", "case", "null", "true",
    "false", "like", "ilike", "inner", "left", "right", "full", "outer", "cross",
    "select", "distinct", "count", "avg", "min", "max", "asc", "desc",
}

# Uppercase tokens that look like SAP names but are SQL keywords / common English.
_SAP_UPPER_STOPWORDS: Set[str] = {
    "YEAR", "DATE", "FROM", "JOIN", "WHEN", "THEN", "NULL", "TRUE", "FALSE",
    "CASE", "WITH", "THAT", "THIS", "INTO", "OVER", "LEFT", "FULL", "INNER",
    "OUTER", "CROSS", "DESC", "LIKE", "CAST", "TEXT", "NULLS", "LIST", "SHOW",
    "SOME", "SUCH", "THAN", "ONLY", "ALSO", "VERY", "JUST", "MOST", "MANY",
    "SAME", "BEEN", "EVEN", "MADE", "PART", "AREA", "TYPE", "KIND", "NAME",
    "USER", "DATA", "ROWS", "LAST", "NEXT", "HELP", "OPEN", "CLOSE", "READ",
}


def extract_explicit_table_identifiers(question: str) -> List[str]:
    """
    Extract table-like identifiers the user explicitly referenced.
    Order is stable; duplicates removed (case-insensitive).
    """
    if not question:
        return []
    found: List[str] = []
    seen: Set[str] = set()

    def add(name: Optional[str]) -> None:
        if not name:
            return
        raw = name.strip()
        if len(raw) < 2:
            return
        low = raw.lower()
        if low in _TABLE_STOPWORDS:
            return
        if low not in seen:
            seen.add(low)
            found.append(raw)

    # Quoted / backtick identifiers
    for pattern in (r"`([^`]+)`", r'"([A-Za-z_][A-Za-z0-9_]*)"', r"'([A-Za-z_][A-Za-z0-9_]*)'"):
        for m in re.finditer(pattern, question):
            add(m.group(1))

    # FROM schema.table / JOIN "T" — capture final table segment
    for m in re.finditer(
        r"(?i)\b(?:from|join)\s+(?:[\w.]+\.)?([\"`]?)([A-Za-z_][A-Za-z0-9_]*)\1",
        question,
    ):
        add(m.group(2))

    # Config skip_tables (app DB) — whole-word
    cfg = _load_schema_ai_config()
    for t in cfg.get("skip_tables") or []:
        t = str(t)
        if re.search(rf"\b{re.escape(t)}\b", question, re.I):
            add(t)

    # ai_* application tables
    for m in re.finditer(r"\b(ai_[a-z][a-z0-9_]*)\b", question, re.I):
        add(m.group(1))

    # SAP-style identifiers (letters+digits/underscore, usually uppercase in docs)
    for m in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\b", question):
        w = m.group(1)
        if w in _SAP_UPPER_STOPWORDS:
            continue
        add(w)

    return found


def _app_skip_table_names() -> Set[str]:
    cfg = _load_schema_ai_config()
    return {str(t).lower() for t in (cfg.get("skip_tables") or [])}


def resolve_tables_for_explicit_intent(
    explicit: List[str],
    sap_schema_keys: Set[str],
) -> Tuple[List[str], List[str], List[str]]:
    """
    Partition explicit identifiers into app tables (skip_tables), SAP tables
    present in schema, and unknown names.

    sap_schema_keys: actual table names from get_schema_dict (any casing).
    """
    app_skip = _app_skip_table_names()
    cfg_skip = [str(c) for c in (_load_schema_ai_config().get("skip_tables") or [])]
    app: List[str] = []
    sap: List[str] = []
    unknown: List[str] = []
    seen_app: Set[str] = set()
    seen_sap: Set[str] = set()
    sap_lower = {k.lower(): k for k in sap_schema_keys}

    for raw in explicit:
        low = raw.lower()
        if low in app_skip:
            canon = next((c for c in cfg_skip if c.lower() == low), raw)
            if canon.lower() not in seen_app:
                seen_app.add(canon.lower())
                app.append(canon)
            continue
        sk = sap_lower.get(low)
        if sk:
            if sk not in seen_sap:
                seen_sap.add(sk)
                sap.append(sk)
            continue
        unknown.append(raw)
    return app, sap, unknown


def _pick_order_column(column_names: List[str]) -> Tuple[Optional[str], str]:
    """Return (column_name, human note) for ORDER BY."""
    lowered = {c.lower(): c for c in column_names}
    for pref in ("updated_at", "created_at", "modified_at"):
        if pref in lowered:
            return lowered[pref], f"ordered by {pref} (most recent first)"
    if "id" in lowered:
        return lowered["id"], "ordered by id"
    return None, ""


def _parse_row_limit(question: str) -> Optional[int]:
    q = (question or "").lower()
    m = re.search(r"\b(?:last|first|top)\s+(\d{1,4})\b", q)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,4})\s+rows?\b", q)
    if m:
        return int(m.group(1))
    return None


def _wants_user_scope(question: str) -> bool:
    q = (question or "").lower()
    return bool(
        re.search(
            r"\b(my\s+user|for\s+my\s+user|my\s+account|for\s+me|for\s+my\s+user|current\s+user)\b",
            q,
        )
        or ("my user" in q and "all users" not in q)
    )


def should_clarify_app_table_ordering(db: Session, table_name: str, question: str) -> bool:
    """
    True when the user asked for last/first/top N rows but the table has no
    suitable ORDER BY column (updated_at, created_at, id).
    """
    q = (question or "").lower()
    if not (
        re.search(r"\b(?:last|first|top)\s+\d+", q)
        or re.search(r"\b\d+\s+rows?\b", q)
    ):
        return False
    loaded = load_app_table_columns(db, table_name)
    if not loaded:
        return False
    _, cols = loaded
    oc, _ = _pick_order_column(cols)
    return oc is None


def load_app_table_columns(db: Session, table_name: str) -> Optional[Tuple[str, List[str]]]:
    """Return (actual_table_name, column_names) from the app DB, or None."""
    try:
        insp = inspect(db.bind)
        names = insp.get_table_names()
        lower_map = {t.lower(): t for t in names}
        key = table_name.lower()
        if key not in lower_map:
            return None
        actual = lower_map[key]
        cols = [c["name"] for c in insp.get_columns(actual)]
        return actual, cols
    except Exception as ex:
        logger.debug("load_app_table_columns: %s", ex)
        return None


def try_execute_explicit_app_table_sql(
    db: Session,
    user_id: int,
    question: str,
    table_name: str,
) -> Optional[Tuple[str, List[Dict[str, Any]], str]]:
    """
    Build and run a minimal SELECT for one app (skip_tables) table.

    Returns (sql, rows, order_note) or None if table missing / cannot build SQL.
    """
    loaded = load_app_table_columns(db, table_name)
    if not loaded:
        return None
    actual_table, columns = loaded
    # Quote identifiers for Postgres
    qident = lambda s: '"' + s.replace('"', '""') + '"'
    qtable = qident(actual_table)

    order_col, order_note = _pick_order_column(columns)
    limit = _parse_row_limit(question)
    if limit is None:
        limit = 50

    where_parts: List[str] = []
    params: Dict[str, Any] = {}
    if _wants_user_scope(question):
        col_lower = {c.lower(): c for c in columns}
        if "user_id" in col_lower:
            where_parts.append(f"{qident(col_lower['user_id'])} = :uid")
            params["uid"] = user_id

    if not order_col:
        # "Last N" without a time/id column — caller should ask for clarification
        if re.search(r"\b(?:last|first|top)\s+\d+", (question or "").lower()) or re.search(
            r"\b\d+\s+rows?\b", (question or "").lower()
        ):
            return None

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    order_sql = ""
    if order_col:
        order_sql = f" ORDER BY {qident(order_col)} DESC NULLS LAST"
    limit_sql = f" LIMIT {limit}"

    sql = f"SELECT * FROM {qtable}{where_sql}{order_sql}{limit_sql}"
    try:
        rows = db.execute(text(sql), params).mappings().all()
        out = [dict(r) for r in rows]
        note = order_note or "no monotonic time/id column for ordering"
        return sql, out, note
    except Exception as ex:
        logger.warning("try_execute_explicit_app_table_sql failed: %s", ex)
        return None


def clarification_unknown_tables(unknown: List[str], app_names: List[str], sap_sample: List[str]) -> str:
    unk = ", ".join(f"`{u}`" for u in unknown[:6])
    app_hint = ", ".join(app_names[:8]) if app_names else "(none configured)"
    sap_hint = ", ".join(sorted(sap_sample)[:15]) if sap_sample else "(schema unavailable)"
    return (
        f"I could not resolve these table name(s) in the available catalogs: {unk}.\n\n"
        f"**App tables** (this workspace): {app_hint}\n\n"
        f"**Sample SAP tables** in the current schema: {sap_hint}\n\n"
        "Reply with the exact table name or fix a typo."
    )


def stored_sql_covers_explicit_tables(stored_sql: str, explicit: List[str]) -> bool:
    """Require stored SQL to reference every explicitly named table."""
    if not explicit:
        return True
    s = (stored_sql or "").lower()
    for t in explicit:
        if t.lower() not in s:
            return False
    return True
