from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Primary schema source (authoritative for NL→SQL prompts)
TABLES_COLUMNS_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "tables_columns.csv"

# Legacy fallback schema source (kept for compatibility)
TABLE_MAP_PATH = Path(__file__).resolve().parent.parent / "db_table_mapping.json"


def _normalize_table_name(name: str) -> str:
    return (name or "").strip()


def _normalize_column_name(name: str) -> str:
    return (name or "").strip()


def _quote_table_if_needed(table: str) -> str:
    """
    In PostgreSQL, SAP-style uppercase identifiers should be double-quoted.
    We keep lowercase tables unquoted (e.g. vbrp) to match how the DB is actually used.
    """
    t = _normalize_table_name(table)
    if not t:
        return t
    if t.islower():
        return t
    # If it already contains a schema prefix, quote each identifier part.
    if "." in t:
        parts = [p for p in t.split(".") if p]
        return ".".join([p if p.islower() else f"\"{p}\"" for p in parts])
    return f"\"{t}\""


def _load_schema_from_csv(path: Path) -> Dict[str, List[str]]:
    """
    Load a mapping: table -> [columns...]
    Expects header: schema,table,column,data_type
    """
    table_to_cols: Dict[str, List[str]] = {}
    if not path.exists():
        return table_to_cols

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            table = _normalize_table_name(str(row.get("table") or ""))
            col = _normalize_column_name(str(row.get("column") or ""))
            if not table or not col:
                continue
            cols = table_to_cols.setdefault(table, [])
            # keep stable order; avoid duplicates
            if col not in cols:
                cols.append(col)
    return table_to_cols


def _load_schema_from_json(path: Path) -> Dict[str, List[str]]:
    """
    Legacy: db_table_mapping.json { table: { columns: {col: ...}}}
    """
    table_to_cols: Dict[str, List[str]] = {}
    if not path.exists():
        return table_to_cols
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return table_to_cols
    for table, info in raw.items():
        if not isinstance(info, dict):
            continue
        cols_dict = info.get("columns") or {}
        if not isinstance(cols_dict, dict) or not cols_dict:
            continue
        cols = [_normalize_column_name(c) for c in cols_dict.keys()]
        cols = [c for c in cols if c]
        if cols:
            table_to_cols[_normalize_table_name(str(table))] = cols
    return table_to_cols


@lru_cache(maxsize=1)
def load_schema() -> Dict[str, List[str]]:
    """
    Load schema mapping once per process.
    Prefer tables_columns.csv. Fall back to db_table_mapping.json if needed.
    """
    csv_schema = _load_schema_from_csv(TABLES_COLUMNS_CSV_PATH)
    if csv_schema:
        return csv_schema
    return _load_schema_from_json(TABLE_MAP_PATH)


def _extract_table_mentions(question: str, all_tables: Sequence[str]) -> List[str]:
    """
    Try to detect explicit table mentions like KNA1, KNVV, "VBRK", vbrp, public.KNA1.
    """
    q = (question or "").strip()
    if not q:
        return []

    # Fast path: uppercase tokens are common for SAP tables.
    tokens = set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]{2,}\b", q))
    if not tokens:
        return []

    # Compare case-insensitively against known tables.
    table_set_lower = {t.lower(): t for t in all_tables}
    out: List[str] = []
    for tok in tokens:
        t = table_set_lower.get(tok.lower())
        if t and t not in out:
            out.append(t)

    # Also attempt schema-qualified mentions: public.KNA1
    for m in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", q):
        _, tbl = m
        t = table_set_lower.get(tbl.lower())
        if t and t not in out:
            out.append(t)

    return out


def _tokenize_question(question: str) -> List[str]:
    """
    Lightweight tokenizer for relevance scoring.
    Keeps alnum/_ tokens, lowercased, length>=2.
    """
    q = (question or "").lower()
    toks = re.findall(r"[a-z0-9_]{2,}", q)
    # de-dupe while preserving order
    seen = set()
    out: List[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _score_table_relevance(table: str, columns: Sequence[str], q_tokens: Sequence[str]) -> int:
    """
    Score based on overlaps between question tokens and table/column names.
    Higher is more relevant. This is intentionally simple/fast.
    """
    if not q_tokens:
        return 0
    t_low = (table or "").lower()
    cols_low = [c.lower() for c in (columns or [])]

    score = 0

    # Table name matches get a stronger boost
    for tok in q_tokens:
        if tok in t_low:
            score += 20

    # Column name matches
    for tok in q_tokens:
        for c in cols_low:
            if tok == c:
                score += 8
            elif tok in c:
                score += 4

    # Small boost if question seems to be asking for counts/totals and table has common measure cols
    if any(t in ("count", "total", "sum", "avg", "amount", "value") for t in q_tokens):
        for c in cols_low:
            if any(k in c for k in ("netwr", "dmbtr", "wrbtr", "amount", "value", "qty", "quantity")):
                score += 2
                break

    return score


def _rank_tables_by_relevance(
    *,
    question: str,
    schema: Dict[str, List[str]],
    prefer: Sequence[str],
    max_tables: int,
) -> List[str]:
    """
    Return up to max_tables table names ordered by:
    - explicit preference list (kept in order if present in schema)
    - then descending relevance score
    - tie-breaker: stable alphabetical
    """
    q_tokens = _tokenize_question(question)

    preferred: List[str] = []
    seen = set()
    for t in prefer:
        if t in schema and t not in seen:
            seen.add(t)
            preferred.append(t)

    # Score every other table
    scored: List[Tuple[int, str]] = []
    for t, cols in schema.items():
        if t in seen:
            continue
        scored.append((_score_table_relevance(t, cols, q_tokens), t))

    scored.sort(key=lambda it: (-it[0], it[1].lower()))
    ranked = preferred + [t for _, t in scored if t not in seen]
    return ranked[:max_tables]


def _format_table_block(table: str, columns: Sequence[str], max_cols: int = 60) -> str:
    cols = list(columns)[:max_cols]
    col_list = ", ".join(cols)
    return f"{_quote_table_if_needed(table)}: {col_list}"


def build_schema_context(
    *,
    question: Optional[str] = None,
    focus_tables: Optional[Sequence[str]] = None,
    max_tables: int = 45,
    max_cols_per_table: int = 60,
) -> str:
    """
    Build a prompt-friendly schema description.

    Format (per line):
      TABLE_NAME: col1, col2, col3, ...

    We keep this intentionally bounded (max_tables) to keep prompts stable and fast.
    When a question is provided, we prioritize tables explicitly mentioned in the question.
    """
    schema = load_schema()
    if not schema:
        return ""

    all_tables = sorted(schema.keys(), key=lambda s: s.lower())

    mentioned = _extract_table_mentions(question or "", all_tables) if question else []

    prioritized: List[str] = []
    for t in (focus_tables or []):
        tn = _normalize_table_name(str(t))
        if tn and tn in schema and tn not in prioritized:
            prioritized.append(tn)
    for t in mentioned:
        if t in schema and t not in prioritized:
            prioritized.append(t)

    # Soft defaults (not required; only used if question is empty/vague)
    # These do NOT hardcode a fixed set to always include; they only seed ranking.
    core_seed = ["VBRK", "VBRP", "KNA1", "KNVV", "VBAK", "VBAP", "MAKT", "MARC", "MVKE"]
    for t in core_seed:
        if t in schema and t not in prioritized:
            prioritized.append(t)

    ranked_tables = _rank_tables_by_relevance(
        question=question or "",
        schema=schema,
        prefer=prioritized,
        max_tables=max_tables,
    )

    parts: List[str] = []
    for t in ranked_tables:
        cols = schema.get(t) or []
        if not cols:
            continue
        parts.append(_format_table_block(t, cols, max_cols=max_cols_per_table))

    return "\n".join(parts)

