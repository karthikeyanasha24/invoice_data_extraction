from __future__ import annotations

import csv
import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .schema_index import CanonicalColumn, CanonicalSchemaIndex, CanonicalTable, build_canonical_schema_index

# Primary schema source (authoritative for NL→SQL prompts)
TABLES_COLUMNS_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "tables_columns.csv"

# Legacy fallback schema source (kept for compatibility)
TABLE_MAP_PATH = Path(__file__).resolve().parent.parent / "db_table_mapping.json"

# Common SAP / app join keys — surfaced after question-hot columns so prompts stay join-safe.
_JOIN_KEY_PRIORITY: Tuple[str, ...] = (
    "mandt",
    "bukrs",
    "rbukrs",
    "werks",
    "lgort",
    "vkorg",
    "vtweg",
    "spart",
    "vbeln",
    "posnr",
    "ebeln",
    "ebelp",
    "kunnr",
    "lifnr",
    "matnr",
    "charg",
    "belnr",
    "buzei",
    "gjahr",
    "poper",
    "fkdat",
    "aedat",
    "budat",
    "aufnr",
    "kokrs",
    "kostl",
    "prctr",
)

# Column names this short match too many tables if used alone; skip auto table-boost.
_SKIP_AUTO_COLUMN_TOKENS: frozenset[str] = frozenset({"mandt"})

# SAP column tokens (length >= 4) that users often paste literally — map to owning tables via CSV.
_COLUMN_NAME_TOKEN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "vbeln",
        "posnr",
        "ebeln",
        "ebelp",
        "kunnr",
        "lifnr",
        "matnr",
        "werks",
        "lgort",
        "bukrs",
        "rbukrs",
        "belnr",
        "buzei",
        "gjahr",
        "poper",
        "fkdat",
        "budat",
        "aedat",
        "netwr",
        "mwsbk",
        "waerk",
        "waers",
        "dmbtr",
        "wrbtr",
        "hsl",
        "racct",
        "prctr",
        "kostl",
    }
)


@lru_cache(maxsize=1)
def _column_to_tables_map() -> Dict[str, Tuple[str, ...]]:
    """
    Inverted index: lowercased column name -> tables that contain it (from CSV-backed index).
    Used for fast column-token → table boosting and join-hint lines in prompts.
    """
    idx = build_canonical_schema_index(include_non_sap=True)
    acc: Dict[str, List[str]] = {}
    for tname, tbl in idx.tables.items():
        for c in tbl.columns:
            if not c.name:
                continue
            k = str(c.name).lower().strip()
            if not k:
                continue
            acc.setdefault(k, []).append(tname)
    return {k: tuple(sorted(set(v))) for k, v in acc.items()}


@lru_cache(maxsize=1)
def _known_column_names_lower() -> frozenset[str]:
    """Every distinct column name in the CSV-backed catalog (lowercase)."""
    return frozenset(_column_to_tables_map().keys())


# Tokens that are real English (or SQL-ish) words and also appear as rare 4-char column names — ignore for auto column match.
_TOKEN_FALSE_POSITIVES: frozenset[str] = frozenset(
    {
        "name",
        "type",
        "date",
        "time",
        "user",
        "text",
        "data",
        "flag",
        "item",
        "order",
        "table",
        "group",
        "class",
        "field",
        "value",
        "amount",
        "total",
        "count",
        "first",
        "last",
        "high",
        "low",
        "open",
        "free",
        "work",
        "plant",
        "site",
        "area",
        "unit",
        "role",
        "host",
        "port",
        "guid",
        "duns",
        "with",
        "from",
        "where",
        "when",
        "then",
        "than",
        "into",
        "each",
        "that",
        "this",
        "what",
        "your",
        "sales",
        "show",
        "list",
        "give",
        "find",
        "most",
        "best",
        "also",
        "only",
        "like",
        "have",
        "been",
        "were",
        "they",
        "them",
    }
)


@lru_cache(maxsize=1)
def _column_names_bucket2() -> Dict[str, Tuple[str, ...]]:
    """Column name (lower) grouped by first two characters — keeps fuzzy search small."""
    out: Dict[str, List[str]] = {}
    for col in _known_column_names_lower():
        if len(col) < 2:
            continue
        out.setdefault(col[:2], []).append(col)
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


@lru_cache(maxsize=1)
def _column_names_bucket3() -> Dict[str, Tuple[str, ...]]:
    """First three characters — used when the 2-char bucket is very large."""
    out: Dict[str, List[str]] = {}
    for col in _known_column_names_lower():
        if len(col) < 3:
            continue
        out.setdefault(col[:3], []).append(col)
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


def _column_pool_for_fuzzy(token_lower: str) -> Tuple[str, ...]:
    if len(token_lower) < 2:
        return ()
    b2 = _column_names_bucket2()
    b3 = _column_names_bucket3()
    p2 = token_lower[:2]
    pool2 = b2.get(p2, ())
    if len(pool2) > 220 and len(token_lower) >= 3:
        p3 = token_lower[:3]
        pool3 = b3.get(p3, ())
        if pool3:
            return pool3
    return pool2


def _fuzzy_column_corrections_from_tokens(tokens: Iterable[str]) -> List[str]:
    """
    Map likely typos (e.g. netwar → netwr) to real column names from the catalog.
    Appended to the expanded question so ranking / column slices follow CSV truth.
    """
    known = _known_column_names_lower()
    skip = _SKIP_AUTO_COLUMN_TOKENS | _TOKEN_FALSE_POSITIVES
    out: List[str] = []
    seen: set[str] = set()
    for raw in tokens:
        tl = str(raw).lower().strip()
        if not tl or tl in skip or tl in known:
            continue
        if len(tl) < 5 or len(tl) > 28:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", tl):
            continue
        pool = _column_pool_for_fuzzy(tl)
        if not pool:
            continue
        hits = difflib.get_close_matches(tl, list(pool), n=1, cutoff=0.86)
        if not hits:
            continue
        h = hits[0]
        if h == tl:
            continue
        if abs(len(h) - len(tl)) > 4:
            continue
        if difflib.SequenceMatcher(None, tl, h).ratio() < 0.88:
            continue
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _expand_question_for_schema_hints(question: str) -> str:
    """
    Append SAP-ish tokens when business phrases match query_resolver synonyms
    (e.g. 'net value' → netwr) so table/column ranking and join hints align with CSV.

    If the text contains a 4-digit year (19xx/20xx), appends common date/posting field
    names (gjahr, fkdat, budat, …) so those columns rank higher in the prompt slice.

    Quarter / month phrases (``Q2``, ``quarterly``, ``March``, ``by month``) append
    ``poper``, ``monat``, and related tokens so FI/CO period columns surface in the slice.

    Near-miss **column** spellings (e.g. netwar → netwr) are corrected via a bucketed
    fuzzy match against catalog column names.
    """
    base = (question or "").strip()
    if not base:
        return ""
    ql = base.lower()
    extra: List[str] = []
    try:
        from .query_resolver import _TERM_SYNONYMS as _syn_map
    except ImportError:
        _syn_map = {}
    for terms in _syn_map.values():
        for term in terms:
            if not isinstance(term, str) or len(term) < 2:
                continue
            if term.lower() in ql:
                for w in terms:
                    if isinstance(w, str) and len(w) > 1:
                        extra.append(w)
                break
    if extra:
        base = f"{base} {' '.join(dict.fromkeys(extra))}".strip()
    # Literal calendar / fiscal years in the question → surface common FI/SD date fields in CSV.
    if re.search(r"\b(19|20)\d{2}\b", ql):
        base = f"{base} gjahr fkdat budat poper aedat erdat".strip()
    # Fiscal quarter / period language → posting period columns (see e.g. BKPF, BSEG, FAGLFLEXA).
    if re.search(r"\b(q[1-4]|quarter|quarterly|fiscal quarter)\b", ql):
        base = f"{base} poper gjahr monat budat".strip()
    # Calendar month phrasing → month fields present on many FI tables in this catalog.
    if re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b",
        ql,
    ) or re.search(r"\b(per month|by month|monthly|each month)\b", ql):
        base = f"{base} monat gjahr fkdat budat".strip()
    col_corr = _fuzzy_column_corrections_from_tokens(_tokenize_question(ql))
    if col_corr:
        base = f"{base} {' '.join(col_corr)}".strip()
    return base[:8000]


def _compact_join_hints_for_tokens(want: set[str], *, max_tokens: int = 5, max_tables_per_col: int = 8) -> str:
    """One-line hint when the same column name exists on multiple tables (join candidates)."""
    if not want:
        return ""
    c2t = _column_to_tables_map()
    chunks: List[str] = []
    for tok in sorted(want)[:max_tokens]:
        tbls = c2t.get(tok, ())
        if len(tbls) <= 1:
            continue
        shown = ",".join(_quote_table_if_needed(t) for t in tbls[:max_tables_per_col])
        if len(tbls) > max_tables_per_col:
            shown += ",…"
        chunks.append(f"{tok}→{shown}")
    if not chunks:
        return ""
    return "Shared columns (join candidates): " + " | ".join(chunks)


def _column_ownership_hints_for_tokens(
    want: set[str],
    *,
    max_tokens: int = 8,
    max_tables_per_col: int = 7,
) -> str:
    """
    Compact "column -> owning tables" line for schema-structure questions such as:
    - which table has netwr?
    - where does fkdat exist?
    """
    if not want:
        return ""
    c2t = _column_to_tables_map()
    chunks: List[str] = []
    for tok in sorted(want)[:max_tokens]:
        tbls = c2t.get(tok, ())
        if not tbls:
            continue
        shown = ",".join(_quote_table_if_needed(t) for t in tbls[:max_tables_per_col])
        if len(tbls) > max_tables_per_col:
            shown += ",…"
        chunks.append(f"{tok}→{shown}")
    if not chunks:
        return ""
    return "Column ownership hints: " + " | ".join(chunks)


def _shared_columns_for_named_tables(
    named_tables: Sequence[str],
    index: CanonicalSchemaIndex,
    *,
    max_pairs: int = 4,
    max_shared_cols: int = 7,
) -> str:
    """
    Pairwise shared-column summary for explicitly named tables.
    Helps the model answer structure-only questions and pick plausible join keys.
    """
    tables = [t for t in named_tables if t and index.get_table(t)]
    if len(tables) < 2:
        return ""
    lines: List[str] = []
    pairs = 0
    for i in range(len(tables)):
        if pairs >= max_pairs:
            break
        ta = index.get_table(tables[i])
        if not ta or not ta.columns:
            continue
        a_cols = {str(c.name).lower().strip() for c in ta.columns if c.name}
        for j in range(i + 1, len(tables)):
            if pairs >= max_pairs:
                break
            tb = index.get_table(tables[j])
            if not tb or not tb.columns:
                continue
            b_cols = {str(c.name).lower().strip() for c in tb.columns if c.name}
            shared = sorted(c for c in (a_cols & b_cols) if c)
            if not shared:
                continue
            shown = ", ".join(shared[:max_shared_cols])
            if len(shared) > max_shared_cols:
                shown += ", …"
            lines.append(
                f"{_quote_table_if_needed(tables[i])}↔{_quote_table_if_needed(tables[j])}: {shown}"
            )
            pairs += 1
    if not lines:
        return ""
    return "Shared columns across named tables: " + " | ".join(lines)


def _interesting_column_tokens_from_question(question: str) -> set[str]:
    """Tokens that may be SAP column names mentioned verbatim in the question."""
    q = (question or "").strip().lower()
    if not q:
        return set()
    toks = set(_tokenize_question(q))
    known = _known_column_names_lower()
    out: set[str] = set()
    for t in toks:
        if t in _SKIP_AUTO_COLUMN_TOKENS or t in _TOKEN_FALSE_POSITIVES:
            continue
        if len(t) >= 5:
            out.add(t)
        elif t in _COLUMN_NAME_TOKEN_ALLOWLIST:
            out.add(t)
        elif len(t) >= 4 and t in known:
            # Any 4+ char token that is an exact column name in tables_columns.csv (e.g. btyp, otyp).
            out.add(t)
    return out


def _tables_from_explicit_column_tokens(
    question: str,
    schema: Dict[str, List[str]],
    index: CanonicalSchemaIndex,
    skip: set[str],
    *,
    max_add: int = 14,
) -> List[str]:
    """
    If the user names real column identifiers (e.g. netwr, fkdat) without naming tables,
    prefer tables that actually contain those columns per tables_columns.csv.
    """
    want = _interesting_column_tokens_from_question(question)
    if not want:
        return []
    c2t = _column_to_tables_map()
    nl = dict(index.score_tables_for_natural_language(question, list(schema.keys())))
    hit_tables: Dict[str, float] = {}
    for tok in want:
        for tbl in c2t.get(tok, ()):
            if tbl in skip or tbl not in schema:
                continue
            hit_tables[tbl] = hit_tables.get(tbl, 0.0) + 14.0
    scored = [(b + nl.get(tbl, 0.0), tbl) for tbl, b in hit_tables.items()]
    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    return [t for _, t in scored[:max_add]]


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
    # Canonical source shared with schema_loader/sap_sql_agent.
    # For context building we include all tables so the AI can handle app + SAP queries.
    schema = build_canonical_schema_index(include_non_sap=True).get_table_columns_map()
    if schema:
        return schema
    csv_schema = _load_schema_from_csv(TABLES_COLUMNS_CSV_PATH)
    if csv_schema:
        return csv_schema
    return _load_schema_from_json(TABLE_MAP_PATH)


def _fuzzy_resolve_table_token(tok: str, table_set_lower: Dict[str, str]) -> Optional[str]:
    """
    Map a near-miss token (e.g. vbrick) to a real catalog table name (VBRK).
    Conservative: short SAP-style identifiers only, strong similarity, similar length.
    """
    tl = (tok or "").strip().lower()
    if len(tl) < 4 or len(tl) > 18:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9_]*", tl):
        return None
    keys = list(table_set_lower.keys())
    # Loose cutoff: close_matches is conservative on length skew (e.g. vbrick vs vbrk).
    hits = difflib.get_close_matches(tl, keys, n=1, cutoff=0.72)
    if not hits:
        return None
    h = hits[0]
    if abs(len(h) - len(tl)) > 3:
        return None
    ratio = difflib.SequenceMatcher(None, tl, h).ratio()
    if ratio < 0.78:
        return None
    return table_set_lower.get(h)


def _extract_table_mentions(question: str, all_tables: Sequence[str]) -> List[str]:
    """
    Try to detect explicit table mentions like KNA1, KNVV, "VBRK", vbrp, public.KNA1.
    Near-miss spellings (e.g. vbrick → VBRK) are resolved when similarity is high.
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
        t = table_set_lower.get(tok.lower()) or _fuzzy_resolve_table_token(tok, table_set_lower)
        if t and t not in out:
            out.append(t)

    # Also attempt schema-qualified mentions: public.KNA1
    for m in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", q):
        _, tbl = m
        t = table_set_lower.get(tbl.lower()) or _fuzzy_resolve_table_token(tbl, table_set_lower)
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


def _score_table_relevance(
    table: str,
    columns: Sequence[str],
    q_tokens: Sequence[str],
    nl_boost: float = 0.0,
) -> int:
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

    score += int(min(nl_boost * 2.8, 120))
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
    idx = build_canonical_schema_index(include_non_sap=True)
    nl_scores = dict(idx.score_tables_for_natural_language(question, list(schema.keys())))

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
        scored.append((_score_table_relevance(t, cols, q_tokens, nl_scores.get(t, 0.0)), t))

    scored.sort(key=lambda it: (-it[0], it[1].lower()))
    ranked = preferred + [t for _, t in scored if t not in seen]
    return ranked[:max_tables]


def _format_table_block(table: str, columns: Sequence[str], max_cols: int = 60) -> str:
    cols = list(columns)[:max_cols]
    col_list = ", ".join(cols)
    return f"{_quote_table_if_needed(table)}: {col_list}"


def _format_column_for_prompt(col: CanonicalColumn) -> str:
    """Include CSV data_type so the LLM avoids impossible casts and picks join keys sensibly."""
    name = _normalize_column_name(col.name)
    if not name:
        return ""
    dt = (col.data_type or "").strip().lower()
    if dt:
        return f"{name} ({dt})"
    return name


def _score_column_for_question(question: str, col: CanonicalColumn) -> int:
    """
    Higher = more likely the user cares about this column for the current question.
    Used to reorder columns within each table so the LLM sees the best hints first.
    """
    q = (question or "").strip().lower()
    if not q:
        return 0
    toks = set(_tokenize_question(q))
    s = 0
    cn = (col.name or "").lower()
    if cn and cn in toks:
        s += 55
    elif len(cn) > 3 and cn in re.sub(r"\s+", "", q):
        s += 28
    for t in toks:
        if len(t) > 3 and t in cn:
            s += 10
        elif len(cn) > 4 and cn in t:
            s += 5
    desc = (col.description or "").lower()
    if desc:
        for tok in toks:
            if len(tok) > 2 and tok in desc:
                s += 9
    for al in col.aliases or []:
        al2 = str(al).lower().strip()
        if len(al2) > 2 and al2 in q:
            s += 38
    return s


def _columns_ordered_for_question(table: CanonicalTable, question: Optional[str], max_cols: int) -> List[CanonicalColumn]:
    """
    Order: (with question) top columns by question score, then standard join keys
    present on this table, then remaining columns by score. Without a question:
    join keys first, then CSV column order.
    """
    cols = [c for c in table.columns if c.name]
    if not cols:
        return []
    by_lower = {c.name.lower(): c for c in cols}
    pinned = [by_lower[k] for k in _JOIN_KEY_PRIORITY if k in by_lower]

    if not (question or "").strip():
        out: List[CanonicalColumn] = []
        seen: set[str] = set()
        for c in pinned[: min(10, max_cols)]:
            ln = c.name.lower()
            if ln not in seen:
                seen.add(ln)
                out.append(c)
        for c in cols:
            if len(out) >= max_cols:
                break
            ln = c.name.lower()
            if ln not in seen:
                seen.add(ln)
                out.append(c)
        return out

    head_n = min(12, max(4, max_cols // 3))
    scored_order = [
        c
        for _, c in sorted(
            enumerate(cols),
            key=lambda ic: (-_score_column_for_question(question, ic[1]), ic[0]),
        )
    ]
    out = []
    seen: set[str] = set()
    for c in scored_order[:head_n]:
        ln = c.name.lower()
        if ln not in seen:
            seen.add(ln)
            out.append(c)
    for c in pinned:
        if len(out) >= max_cols:
            break
        ln = c.name.lower()
        if ln not in seen:
            seen.add(ln)
            out.append(c)
    for c in scored_order:
        if len(out) >= max_cols:
            break
        ln = c.name.lower()
        if ln not in seen:
            seen.add(ln)
            out.append(c)
    return out


def _nl_rank_line_for_tables(
    index: CanonicalSchemaIndex,
    q_rank: str,
    table_names: Sequence[str],
    *,
    max_items: int = 8,
) -> str:
    """
    One-line summary of NL relevance scores for the tables included in this prompt slice.
    Surfaces which tables the retrieval layer considers strongest for the question.
    """
    if not (q_rank or "").strip() or not table_names:
        return ""
    nl = dict(index.score_tables_for_natural_language(q_rank, list(table_names)))
    pairs = [(float(nl.get(t, 0.0)), t) for t in table_names]
    pairs.sort(key=lambda x: (-x[0], x[1].lower()))
    items: List[str] = []
    for s, t in pairs[:max_items]:
        if s <= 0.0:
            continue
        items.append(f"{_quote_table_if_needed(t)} ({s:.1f})")
    if not items:
        return ""
    return "Table relevance for this question (higher = stronger match): " + ", ".join(items)


def _format_table_block_from_canonical(
    table: CanonicalTable,
    max_cols: int = 60,
    *,
    question: Optional[str] = None,
) -> str:
    pieces: List[str] = []
    for c in _columns_ordered_for_question(table, question, max_cols):
        s = _format_column_for_prompt(c)
        if s:
            pieces.append(s)
    col_list = ", ".join(pieces)
    if not col_list:
        return f"{_quote_table_if_needed(table.name)}:"
    return f"{_quote_table_if_needed(table.name)}: {col_list}"


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
      TABLE_NAME: col1 (type1), col2 (type2), ...

    Column types come from tables_columns.csv (and mapping merge) so the model can
    reason about text vs numeric fields. Bounded by max_tables / max_cols_per_table.

    When ``question`` is set, columns within each table are ordered by relevance to
    that question so high-signal fields appear first in the prompt window.

    When several tables are named explicitly, ``max_tables`` / ``max_cols_per_table``
    are raised automatically (within caps) so join queries still see every needed
    table. Mentioned tables are always included in the slice (up to the effective cap).

    When the question contains **verbatim SAP column tokens** (e.g. ``netwr``, ``fkdat``)
    that appear in ``tables_columns.csv``, tables owning those columns are boosted into
    the priority list even if the user never typed the table name.

    When such a column exists on **multiple** tables, a short **join-candidates** line is
    added to the preamble (from the CSV-backed inverted column→tables index).

    A **table relevance** line summarizes NL scores for the tables actually included in
    this slice (same scoring as shortlisting), so the model can prioritize joins and FROM clauses.

    Business phrases from ``query_resolver._TERM_SYNONYMS`` (e.g. *net value*, *sold to*)
    are expanded to related SAP tokens for ranking only; the user-facing referenced-table
    line still reflects table names typed explicitly in the original question.
    """
    index = build_canonical_schema_index(include_non_sap=True)
    schema = index.get_table_columns_map()
    if not schema:
        return ""

    all_tables = sorted(schema.keys(), key=lambda s: s.lower())

    q_rank = _expand_question_for_schema_hints(question or "")
    mentioned_raw = _extract_table_mentions(question or "", all_tables) if question else []
    mentioned_rank = _extract_table_mentions(q_rank, all_tables) if q_rank else []

    eff_max_tables = max_tables
    eff_max_cols = max_cols_per_table
    n_mentioned = len(set(mentioned_raw) | set(mentioned_rank))
    if n_mentioned:
        eff_max_tables = min(72, max(max_tables, n_mentioned + 20))
    if n_mentioned >= 3:
        eff_max_cols = min(85, max(max_cols_per_table, max_cols_per_table + 12))

    prioritized: List[str] = []
    for t in (focus_tables or []):
        tn = _normalize_table_name(str(t))
        if tn and tn in schema and tn not in prioritized:
            prioritized.append(tn)
    for t in mentioned_raw:
        if t in schema and t not in prioritized:
            prioritized.append(t)
    for t in mentioned_rank:
        if t in schema and t not in prioritized:
            prioritized.append(t)

    col_token_tables = _tables_from_explicit_column_tokens(
        q_rank,
        schema,
        index,
        set(prioritized),
        max_add=14,
    )
    for t in col_token_tables:
        if t in schema and t not in prioritized:
            prioritized.append(t)
    if col_token_tables:
        eff_max_tables = min(72, max(eff_max_tables, len(prioritized) + 16))

    # Soft defaults (not required; only used if question is empty/vague)
    # These do NOT hardcode a fixed set to always include; they only seed ranking.
    core_seed = ["VBRK", "VBRP", "KNA1", "KNVV", "VBAK", "VBAP", "MAKT", "MARC", "MVKE"]
    for t in core_seed:
        if t in schema and t not in prioritized:
            prioritized.append(t)

    ranked_tables = _rank_tables_by_relevance(
        question=q_rank,
        schema=schema,
        prefer=prioritized,
        max_tables=eff_max_tables,
    )
    # Never drop a table the user named explicitly — prepend then cap.
    merged: List[str] = []
    seen_t: set[str] = set()
    for t in mentioned_raw:
        if t in schema and t not in seen_t:
            seen_t.add(t)
            merged.append(t)
    for t in mentioned_rank:
        if t in schema and t not in seen_t:
            seen_t.add(t)
            merged.append(t)
    for t in ranked_tables:
        if t in schema and t not in seen_t:
            seen_t.add(t)
            merged.append(t)
    ranked_tables = merged[:eff_max_tables]

    parts: List[str] = []
    for t in ranked_tables:
        cols = schema.get(t) or []
        if not cols:
            continue
        tbl = index.get_table(t)
        if tbl and tbl.columns:
            parts.append(
                _format_table_block_from_canonical(tbl, max_cols=eff_max_cols, question=q_rank)
            )
        else:
            parts.append(_format_table_block(t, cols, max_cols=eff_max_cols))

    if not parts:
        return ""
    preamble_lines = [
        "Schema contract: use ONLY the tables and columns that appear in this block — do not "
        "invent, rename, or abbreviate identifiers (no made-up field names). If the exact "
        "measure or dimension you want is not listed, pick the closest named column here or "
        "narrow the question so this slice can cover it.",
        "Values are often stored as text — CAST to numeric or date before SUM/AVG or strict "
        "date comparisons when the column type shows text.",
    ]
    if mentioned_raw:
        preamble_lines.append(
            "User-referenced tables (prefer these in FROM/JOIN when relevant): "
            + ", ".join(_quote_table_if_needed(m) for m in mentioned_raw if m in schema)
        )
    named_tables_line = _shared_columns_for_named_tables(
        [t for t in mentioned_raw if t in schema],
        index,
        max_pairs=4,
        max_shared_cols=7,
    )
    if named_tables_line:
        preamble_lines.append(named_tables_line[:700])
    want_cols = _interesting_column_tokens_from_question(q_rank)
    ownership_hint = _column_ownership_hints_for_tokens(want_cols, max_tokens=8, max_tables_per_col=7)
    if ownership_hint:
        preamble_lines.append(ownership_hint[:700])
    join_hint = _compact_join_hints_for_tokens(want_cols)
    if join_hint:
        preamble_lines.append(join_hint[:520])
    if (q_rank or "").strip():
        rank_line = _nl_rank_line_for_tables(index, q_rank, ranked_tables, max_items=8)
        if rank_line:
            preamble_lines.append(rank_line[:650])
    preamble = "\n".join(preamble_lines) + "\n"
    return preamble + "\n".join(parts)

