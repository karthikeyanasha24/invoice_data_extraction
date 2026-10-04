"""
Reusable adaptive context for Generative AI: question intent, result shape, and summary binding.

Used by SQL prompt hints, chart selection, and narrative guardrails — not phrase-specific patches.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .ai_intent_classifier import IntentClassification, classify_intent
from .explicit_table_sql import extract_explicit_table_identifiers

# Column name hints (lowercase)
_TIME_LIKE_NAMES: Set[str] = {
    "fkdat",
    "budat",
    "bldat",
    "bedat",
    "erdat",
    "billing_date",
    "posting_date",
    "date",
    "month",
    "year_month",
    "period",
    "calmonth",
    "calendar_year",
    "billing_year",
    "year",
    "gjahr",
    "fiscal_year",
    "fisc_year",
}

_CURRENCY_NAMES: Set[str] = {"waerk", "waers", "currency", "curr", "hwaer", "rtcur"}

_MEASURE_NAME_FRAGMENTS: Tuple[str, ...] = (
    "total",
    "sum",
    "amount",
    "revenue",
    "sales",
    "netwr",
    "rmwwr",
    "count",
    "qty",
    "quantity",
    "value",
    "balance",
    "price",
    "cost",
    "avg",
    "average",
    "min",
    "max",
)


def _is_raw_row_inspection_question(q: str) -> bool:
    ql = (q or "").lower()
    if re.search(r"\b(compare|vs\.?|versus)\b", ql):
        return False
    return bool(
        re.search(r"\b(last|first|top)\s+\d+\s+rows?\b", ql)
        or re.search(r"\blist\s+(\d+\s+)?(the\s+)?rows?\b", ql)
        or re.search(r"\bshow\s+(me\s+)?(all\s+)?rows?\b", ql)
        or re.search(r"\b(raw\s+)?(data|rows?)\s+(please|only)?\b", ql)
        or re.search(r"\b(sample|preview|snippet)\s+(of\s+)?(rows?|records?)\b", ql)
        or re.search(r"\b(display|dump)\s+rows?\b", ql)
    )


def _is_trend_question(q: str) -> bool:
    ql = (q or "").lower()
    return bool(
        re.search(r"\b(trend|over\s+time|time\s*series|each\s+day|daily|weekly)\b", ql)
        or re.search(r"\b(evol|growth)\b.*\b(time|month|year)\b", ql)
    )


def _is_distribution_question(q: str) -> bool:
    ql = (q or "").lower()
    return bool(
        re.search(r"\b(share|distribution|proportion|breakdown|percent|percentage)\b", ql)
    )


def _is_user_scoped_question(q: str) -> bool:
    ql = (q or "").lower()
    return bool(
        re.search(r"\b(my|our)\s+(rows?|records?|invoices?|data|queries?)\b", ql)
        or re.search(r"\buser_?id\b|\bprofile\s*id\b|\bcurrent\s+user\b", ql)
    )


def _resolve_primary_kind(
    q: str,
    tags: Set[str],
) -> str:
    """Single coarse kind for routing charts + summary tone (not mutually exclusive with tags)."""
    if _is_raw_row_inspection_question(q):
        return "raw_inspection"
    if "compare" in tags or _two_calendar_years(q):
        return "compare"
    if _is_trend_question(q) or "time_bucket_month" in tags:
        return "trend"
    if "rank" in tags:
        return "rank"
    if _is_distribution_question(q):
        return "distribution"
    if "list_detail" in tags:
        return "list_detail"
    if "aggregate" in tags or "count" in tags:
        return "aggregate"
    return "general"


def _two_calendar_years(q: str) -> bool:
    ys = set(re.findall(r"\b((?:19|20)\d{2})\b", q or ""))
    return len(ys) >= 2


def build_adaptive_query_profile(question: str) -> Dict[str, Any]:
    """
    Structured profile: explicit tables, intent tags, primary kind, flags.
    Safe to log and send to the frontend (no secrets).
    """
    q = question or ""
    ic: IntentClassification = classify_intent(q)
    tags = list(ic.tags)
    tag_set = set(tags)
    explicit = extract_explicit_table_identifiers(q)
    kind = _resolve_primary_kind(q, tag_set)
    return {
        "kind": kind,
        "tags": tags,
        "explicit_tables": explicit[:12],
        "flags": {
            "raw_row_inspection": _is_raw_row_inspection_question(q),
            "user_scoped": _is_user_scoped_question(q),
            "two_calendar_years": _two_calendar_years(q),
            "needs_clarification": bool(ic.clarification_questions),
        },
        "clarification_questions": ic.clarification_questions[:3],
        "time_bucket": ic.time_bucket,
        "shape_hint": ic.shape_hint,
    }


def _column_numeric_score(rows: List[Dict[str, Any]], key: str, sample: int = 8) -> float:
    n = 0
    num = 0
    for row in rows[:sample]:
        if not isinstance(row, dict):
            continue
        n += 1
        v = row.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            num += 1
    return (num / n) if n else 0.0


def _mixed_currency(rows: List[Dict[str, Any]], curr_cols: List[str]) -> bool:
    if not curr_cols:
        return False
    seen: Set[str] = set()
    for row in rows[:400]:
        if not isinstance(row, dict):
            continue
        for c in curr_cols:
            v = row.get(c)
            if v is not None and str(v).strip():
                seen.add(str(v).strip())
                if len(seen) > 1:
                    return True
    return False


def analyze_sql_result_shape(
    rows: List[Dict[str, Any]],
    sql: str = "",
) -> Dict[str, Any]:
    """Infer dimensions, measures, time axes, and cardinality from executed rows."""
    if not rows or not isinstance(rows[0], dict):
        return {
            "row_count": len(rows or []),
            "column_count": 0,
            "columns": [],
            "time_columns": [],
            "measure_columns": [],
            "dimension_columns": [],
            "currency_columns": [],
            "mixed_currency": False,
            "sql_tables_mentioned": _tables_from_sql(sql),
        }
    cols = list(rows[0].keys())
    time_cols: List[str] = []
    currency_cols: List[str] = []
    measure_cols: List[str] = []
    dimension_cols: List[str] = []
    for key in cols:
        lk = str(key).lower()
        if lk in _TIME_LIKE_NAMES or lk.endswith("_date") or lk.endswith("date"):
            time_cols.append(key)
        elif lk in _CURRENCY_NAMES:
            currency_cols.append(key)
        elif _column_numeric_score(rows, key) >= 0.6:
            if any(p in lk for p in _MEASURE_NAME_FRAGMENTS) or _column_numeric_score(rows, key) >= 0.9:
                measure_cols.append(key)
        elif isinstance(rows[0].get(key), str) or rows[0].get(key) is None:
            dimension_cols.append(key)
    # Any numeric column not yet classified
    for key in cols:
        if key in measure_cols or key in time_cols or key in currency_cols:
            continue
        if _column_numeric_score(rows, key) >= 0.6:
            measure_cols.append(key)

    dimension_cols = [k for k in dimension_cols if k not in time_cols and k not in currency_cols]
    measure_cols = [k for k in measure_cols if k not in currency_cols]

    wide_inspection = len(cols) >= 10 and len(rows) <= 80

    return {
        "row_count": len(rows),
        "column_count": len(cols),
        "columns": cols,
        "time_columns": time_cols,
        "measure_columns": measure_cols,
        "dimension_columns": dimension_cols,
        "currency_columns": currency_cols,
        "mixed_currency": _mixed_currency(rows, currency_cols),
        "wide_row_inspection": wide_inspection,
        "sql_tables_mentioned": _tables_from_sql(sql),
    }


def _tables_from_sql(sql: str) -> List[str]:
    if not sql:
        return []
    found: List[str] = []
    seen: Set[str] = set()
    for m in re.finditer(
        r'(?i)\b(?:from|join)\s+(?:[\w"]+\.)?["`]?([A-Za-z_][A-Za-z0-9_]*)["`]?',
        sql,
    ):
        t = m.group(1)
        if t.lower() not in seen and len(t) > 1:
            seen.add(t.lower())
            found.append(t)
    return found[:16]


def choose_dimension_column(shape: Dict[str, Any]) -> Optional[str]:
    """Prefer human-readable labels over raw IDs when multiple dimensions exist."""
    dims: List[str] = shape.get("dimension_columns") or []
    if not dims:
        return None
    preferred_tokens = ("name", "label", "text", "desc", "maktx", "country", "land", "region", "city", "industry", "sector")
    for d in dims:
        dl = d.lower()
        if any(t in dl for t in preferred_tokens):
            return d
    for d in dims:
        dl = d.lower()
        if re.search(r"_(id|nr|num|no)$", dl) and len(dims) > 1:
            continue
        return d
    return dims[0]


def wants_table_first(profile: Dict[str, Any], shape: Dict[str, Any]) -> bool:
    if profile.get("kind") in ("raw_inspection", "list_detail"):
        return True
    if profile["flags"].get("raw_row_inspection"):
        return True
    if shape.get("wide_row_inspection") and profile.get("kind") == "general":
        return True
    return False


def build_result_bound_summary_block(profile: Dict[str, Any], shape: Dict[str, Any]) -> str:
    """Inject into LLM prompts so narratives stay tied to executed rows."""
    kind = profile.get("kind", "general")
    tags = ", ".join(profile.get("tags") or []) or "(none)"
    cols = shape.get("columns") or []
    col_preview = ", ".join(cols[:14])
    if len(cols) > 14:
        col_preview += ", …"
    lines = [
        "ADAPTIVE CONTEXT — RESULT-BOUND ANSWER (mandatory):",
        f"- Question kind: **{kind}** (tags: {tags}).",
        f"- Result: **{shape.get('row_count', 0)}** row(s), **{shape.get('column_count', 0)}** column(s).",
        f"- Columns: {col_preview or '(none)'}",
    ]
    if shape.get("time_columns"):
        lines.append(f"- Time-like fields: {', '.join(shape['time_columns'])}.")
    if shape.get("measure_columns"):
        lines.append(f"- Numeric measures: {', '.join(shape['measure_columns'][:10])}.")
    if shape.get("mixed_currency"):
        lines.append(
            "- **Mixed currencies** in rows: call this out; do not present a single-currency headline total."
        )
    ext = profile.get("explicit_tables") or []
    if ext:
        lines.append(
            f"- User referenced table identifier(s): **{', '.join(ext)}** — stay aligned with SQL against those objects."
        )
    if kind == "raw_inspection":
        lines.append(
            "- Reply with **concise factual** row/field descriptions only; **no** generic strategy or recommendations."
        )
    elif kind == "compare":
        lines.append(
            "- **Compare** numerically using values present in the result; never claim periods/years are absent if they appear in rows or time columns."
        )
    elif kind == "trend":
        lines.append(
            "- Describe **trend using the time axis** present in the data; do not invent a time grain not in the result."
        )
    elif kind == "rank":
        lines.append(
            "- Focus on **ordering and relative magnitudes** from the rows; avoid unrelated KPI storytelling."
        )
    elif kind == "distribution":
        lines.append(
            "- Describe **shares or breakdown** using the dimension + measure columns returned."
        )
    elif kind == "aggregate":
        lines.append(
            "- Prefer **direct totals/averages** from the result; avoid diluting with unrelated dimensions."
        )
    lines.append(
        "- **Forbidden**: saying required information is “not in the data” when it appears in the column list or sample rows."
    )
    lines.append(
        "- **Recommendations**: only if they are **one short** sentence and **directly implied** by the numbers shown; otherwise omit."
    )
    return "\n".join(lines)


def extend_intent_sql_prompt_lines(question: str) -> List[str]:
    """Extra lines for schema-driven SQL (called from build_intent_sql_prompt_block)."""
    p = build_adaptive_query_profile(question)
    lines = [
        f"- Primary question kind: **{p['kind']}** — SQL must answer this kind (not a looser default aggregate).",
    ]
    if p["kind"] == "compare":
        lines.append(
            "- Comparison: return **side-by-side or grouped** periods/dimensions so values can be compared in one result (or use separate year-scoped queries if the pipeline splits)."
        )
    if p["kind"] == "rank":
        lines.append(
            "- Ranking: **ORDER BY** the requested metric and **LIMIT** to the requested N; SELECT must expose the sort key."
        )
    if p["kind"] == "trend":
        lines.append(
            "- Trend: include a **time bucket** column (month/day/year from the correct date field) and aggregate per bucket."
        )
    if p["kind"] in ("raw_inspection", "list_detail"):
        lines.append(
            "- Row listing: prefer **SELECT * or explicit columns** with modest **LIMIT**; avoid collapsing into a single SUM unless the user asked for a total."
        )
    if p["flags"].get("user_scoped"):
        lines.append(
            "- User-scoped: apply **current user / tenant** filters required by app tables (e.g. user_id) when querying app data."
        )
    if p.get("explicit_tables"):
        lines.append(
            f"- User referenced table(s): **{', '.join(p['explicit_tables'][:6])}** — use them in FROM/JOIN unless impossible."
        )
    return lines
