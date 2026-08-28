"""
Deterministic NL→SQL hardening used by /api/query/adaptive.

Fixes applied here (no extra LLM round-trip):
- CTE aliases are local names, not schema tables
- netwr COALESCE('' → numeric) rewrites
- SAP date empty-string guards
- LPAD key normalization on VBRK↔KNA1 / VBRK↔vbrp joins
- named-customer ILIKE predicates
- LIMIT N + single-currency ranking for catalog/fast-path
- non-business intent gate
- user-facing chart titles (strip internal continuation prompts)
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("zodiac-api.adaptive_hardening")

# Adaptive SQL must not occupy the SAP pool indefinitely (pool_size is small).
# 20s is a safety net; the live p95 gate remains 15s for successful answers.
ADAPTIVE_SQL_TIMEOUT_MS = int(os.getenv("ADAPTIVE_SQL_TIMEOUT_MS", "20000"))

_WORD_N = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
}

_INTERNAL_TITLE_MARKERS = (
    "continuation of an analysis session",
    "generate one new postgresql",
    "follow-up delta while preserving",
)

_SQL_KEYWORDS = {
    "select", "from", "where", "join", "left", "right", "inner", "outer", "full",
    "cross", "lateral", "on", "as", "and", "or", "group", "order", "limit",
    "union", "except", "intersect", "with", "recursive", "values", "unnest",
}

_BUSINESS_TOKENS = (
    "sales", "sale", "revenue", "invoice", "invoices", "billing", "customer",
    "customers", "industry", "product", "products", "material", "materials",
    "year", "years", "top", "lowest", "highest", "biggest", "compare", "versus",
    "vbrk", "vbrp", "kna1", "t016t", "makt", "edi", "failed", "count", "total",
    "bought", "buyer", "sold", "order", "orders", "currency", "eur", "usd",
    "trading", "motomarkt", "rank",
    # Deep analytical metrics / dimensions
    "cogs", "margin", "margins", "profit", "profits", "cost", "goods", "region",
    "regions", "country", "countries", "component", "components", "breakdown",
    "decline", "process", "delivery", "logistics", "freight", "expiry", "expir",
    "history", "buying", "selling", "purchase", "supplier", "inventory",
    "concentration", "vendor", "vendors", "purchasing", "percent", "percentage",
)

_NONSENSE_HINTS = (
    "meaning of life", "drop all tables", "write a poem", "tell me a joke",
    "what is 2+2", "hello world", "lorem ipsum", "sing a song",
    "how are you", "what's your name", "who are you",
    "favorite color", "what's the weather", "weather today",
    "who is the president", "who invented the telephone",
    "ceo of microsoft",
)

_SHORT_FOLLOWUP_TOKENS = {
    "trading", "top", "bottom", "count", "sales", "remove", "filter",
    "compare", "instead", "highest", "lowest", "industry", "invoice",
    "rank", "cogs", "margin", "margins", "profit", "cost", "goods",
    "region", "regions", "country", "customer", "customers", "product",
    "components", "breakdown", "decline", "process", "delivery", "why",
    "history", "buying", "selling", "purchase", "year", "years",
    "supplier", "suppliers", "percent", "percentage", "share", "vendor",
}


class StageTimer:
    """Collect numeric stage spans for adaptive query logging."""

    def __init__(self) -> None:
        self.spans: Dict[str, int] = {}
        self._marks: Dict[str, float] = {}
        self.t0 = time.perf_counter()

    def start(self, name: str) -> None:
        self._marks[name] = time.perf_counter()

    def stop(self, name: str) -> int:
        t1 = time.perf_counter()
        t0 = self._marks.pop(name, t1)
        ms = int((t1 - t0) * 1000)
        self.spans[name] = self.spans.get(name, 0) + ms
        return ms

    def total_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

    def as_dict(self) -> Dict[str, int]:
        out = dict(self.spans)
        out["total"] = self.total_ms()
        return out


def extract_cte_names(sql: str) -> set[str]:
    """Return WITH <alias> AS (...) names, including nested/multi CTEs."""
    if not sql or not re.search(r"\bWITH\b", sql, re.I):
        return set()
    stripped = re.sub(r"'([^']|'')*'", "''", sql)
    names: set[str] = set()
    for m in re.finditer(
        r'(?:([A-Za-z_][A-Za-z0-9_]*)|"([^"]+)")\s+AS\s*\(',
        stripped,
        flags=re.I,
    ):
        names.add((m.group(1) or m.group(2)).lower())
    return names


def extract_subquery_aliases(sql: str) -> set[str]:
    """FROM/JOIN (SELECT ...) [AS] alias — local names, not schema tables."""
    if not sql:
        return set()
    found = re.findall(
        r"\)\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
        sql,
        flags=re.I,
    )
    return {a.lower() for a in found if a.lower() not in _SQL_KEYWORDS}


def local_sql_relation_names(sql: str) -> set[str]:
    return extract_cte_names(sql) | extract_subquery_aliases(sql)


def rewrite_netwr_empty_coalesce(sql: str) -> str:
    """
    COALESCE(netwr, '') is invalid when netwr is numeric ('' cannot cast to numeric).
    Rewrite to NULLIF(TRIM(CAST(netwr AS TEXT)), '').
    """
    if not sql or "netwr" not in sql.lower():
        return sql

    def _col(m: re.Match) -> str:
        expr = m.group(1)
        return f"NULLIF(TRIM(CAST({expr} AS TEXT)), '')"

    sql = re.sub(
        r"TRIM\s*\(\s*COALESCE\s*\(\s*((?:[A-Za-z_][A-Za-z0-9_]*\s*\.\s*)?\"?netwr\"?)\s*,\s*''\s*\)\s*\)",
        _col,
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"COALESCE\s*\(\s*((?:[A-Za-z_][A-Za-z0-9_]*\s*\.\s*)?\"?netwr\"?)\s*,\s*''\s*\)",
        _col,
        sql,
        flags=re.I,
    )
    return sql


def _date_filter_aliases(sql: str) -> List[Tuple[str, str]]:
    """(alias, date_col) pairs that appear in the SQL."""
    cols = ("fkdat", "budat", "audat", "erdat", "lfdat", "bedat", "agdat")
    out: List[Tuple[str, str]] = []
    for col in cols:
        for m in re.finditer(
            rf'\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?{col}"?',
            sql,
            flags=re.I,
        ):
            out.append((m.group(1), col))
    # de-dupe
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for a, c in out:
        key = (a.lower(), c.lower())
        if key not in seen:
            seen.add(key)
            uniq.append((a, c))
    return uniq


def question_asks_date_filter(question: str) -> bool:
    q = (question or "").lower()
    if re.search(r"\b(20\d{2}|19\d{2})\b", q):
        return True
    return bool(re.search(r"\b(year|years|date|period|month|quarter)\b", q))


def inject_sap_date_empty_guards(sql: str, question: str = "") -> str:
    """Add TRIM(date) <> '' when a SAP date column is filtered, or when the question asks for a year."""
    if not sql:
        return sql
    if "<> ''" in sql or "!= ''" in sql:
        # already has some empty-string guard; still add per-date-col if missing
        pass
    aliases = _date_filter_aliases(sql)
    if not aliases:
        return sql
    has_literal_date = bool(re.search(r"(=|>=|<=|>|<|in)\s*\(?\s*'\d{4}", sql, re.I))
    if not has_literal_date and not question_asks_date_filter(question):
        return sql
    extra: List[str] = []
    low = sql.lower()
    for alias, col in aliases:
        needle = f'{alias}."{col}"'
        alt = f"{alias}.{col}"
        guard = f"TRIM(CAST({alias}.\"{col}\" AS TEXT)) <> ''"
        if guard.lower() in low:
            continue
        extra.append(guard)
    if not extra:
        return sql
    cond = " AND ".join(extra)
    m = re.search(r"\bWHERE\b", sql, re.I)
    if m:
        return sql[: m.end()] + " " + cond + " AND" + sql[m.end():]
    m2 = re.search(r"\s+(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.I)
    if m2:
        return sql[: m2.start()] + f" WHERE {cond}" + sql[m2.start():]
    return sql.rstrip().rstrip(";") + f" WHERE {cond}"


def apply_statement_timeout(db: Any, timeout_ms: Optional[int] = None) -> None:
    """Bound this transaction's SQL so a cartesian/unindexed join cannot hang the API."""
    if db is None:
        return
    ms = ADAPTIVE_SQL_TIMEOUT_MS if timeout_ms is None else int(timeout_ms)
    if ms <= 0:
        return
    try:
        from sqlalchemy import text as sa_text

        db.execute(sa_text(f"SET LOCAL statement_timeout = {ms}"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("statement_timeout not applied: %s", exc)


def inject_lpad_join_keys(sql: str) -> str:
    """Normalize VBRK.kunag / KNA1.kunnr / vbeln joins with LPAD(TRIM(...),10,'0')."""
    if not sql or "lpad" in sql.lower():
        return sql
    if not re.search(r"\b(kunag|kunnr|vbeln)\b", sql, re.I):
        return sql

    def _repl(m: re.Match) -> str:
        left_a, left_c, op, right_a, right_c = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        if "lpad" in m.group(0).lower():
            return m.group(0)
        return (
            f"LPAD(TRIM({left_a}.\"{left_c}\"), 10, '0') "
            f"{op} "
            f"LPAD(TRIM({right_a}.\"{right_c}\"), 10, '0')"
        )

    return re.sub(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?(kunag|kunnr|vbeln)"?'
        r'\s*(=)\s*'
        r'([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?(kunag|kunnr|vbeln)"?',
        _repl,
        sql,
        flags=re.I,
    )


def extract_requested_limit(question: str) -> Optional[int]:
    """Explicit top/first/best/biggest N including word numbers. None if not specified."""
    q = (question or "").lower()
    patterns = (
        r"\b(?:top|first|best|worst|bottom)\s+(\d+)\b",
        r"\b(?:top|first|best|worst|bottom)\s+(" + "|".join(_WORD_N) + r")\b",
        r"\b(\d+)\s+(?:largest|biggest|highest|top)\b",
        r"\b(" + "|".join(_WORD_N) + r")\s+(?:largest|biggest|highest|top)\b",
        r"\b(?:largest|biggest|highest|top)\s+(\d+)\b",
        r"\b(?:largest|biggest|highest|top)\s+(" + "|".join(_WORD_N) + r")\b",
        r"\b(?:give me|show(?:\s+me)?)\s+(?:the\s+)?(\d+)\s+(?:biggest|largest|highest|top)\b",
        r"\b(?:give me|show(?:\s+me)?)\s+(?:the\s+)?(" + "|".join(_WORD_N) + r")\s+(?:biggest|largest|highest|top)\b",
    )
    for pat in patterns:
        m = re.search(pat, q)
        if not m:
            continue
        raw = m.group(1)
        if raw.isdigit():
            n = int(raw)
        else:
            n = _WORD_N.get(raw, 0)
        if n >= 1:
            return max(1, min(n, 50))
    return None


def apply_limit_n(sql: str, n: int) -> str:
    if not sql:
        return sql
    n_i = max(1, min(int(n), 50))
    if re.search(r"\bLIMIT\s+\d+", sql, re.I):
        return re.sub(r"\bLIMIT\s+\d+", f"LIMIT {n_i}", sql, count=1, flags=re.I)
    return sql.rstrip().rstrip(";") + f"\nLIMIT {n_i}"


def apply_limit_from_question(sql: str, question: str) -> str:
    n = extract_requested_limit(question)
    if not sql or n is None:
        return sql
    return apply_limit_n(sql, n)


def extract_requested_currency(question: str) -> Optional[str]:
    q = (question or "").upper()
    for code in ("EUR", "USD", "GBP", "INR", "JPY", "CHF"):
        if re.search(rf"\b{code}\b", q):
            return code
    if re.search(r"\beuro|\beur\b|€", (question or ""), re.I):
        return "EUR"
    if re.search(r"\bdollar|\busd\b|\$", (question or ""), re.I):
        return "USD"
    return None


def ranking_wants_single_currency(question: str) -> bool:
    q = (question or "").lower()
    if re.search(r"\b(each currency|by currency|per currency|all currencies|mixed currency)\b", q):
        return False
    return extract_requested_limit(question) is not None


def inject_year_filters_from_question(sql: str, question: str) -> str:
    """Ensure calendar years mentioned in the question appear as fkdat filters in SQL."""
    if not sql:
        return sql
    years = list(dict.fromkeys(re.findall(r"\b((?:19|20)\d{2})\b", question or "")))
    if not years:
        return sql
    if all(y in sql for y in years):
        return sql
    if not re.search(r"\bfkdat\b", sql, re.I):
        return sql
    quoted = ", ".join(f"'{y}'" for y in years)
    m = re.search(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?fkdat"?', sql, re.I)
    if m:
        expr = (
            f'SUBSTRING(TRIM(CAST({m.group(1)}."fkdat" AS TEXT)), 1, 4) IN ({quoted})'
        )
    else:
        expr = f"SUBSTRING(TRIM(CAST(\"fkdat\" AS TEXT)), 1, 4) IN ({quoted})"
    wm = re.search(r"\bWHERE\b", sql, re.I)
    if wm:
        return sql[: wm.end()] + f" {expr} AND" + sql[wm.end() :]
    m2 = re.search(r"\s+(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.I)
    if m2:
        return sql[: m2.start()] + f" WHERE {expr}" + sql[m2.start() :]
    return sql.rstrip().rstrip(";") + f" WHERE {expr}"


def inject_single_currency_filter(sql: str, question: str, default: str = "EUR") -> str:
    if not sql:
        return sql
    explicit = extract_requested_currency(question)
    if not ranking_wants_single_currency(question) and not explicit:
        return sql
    if not re.search(r"\bwaerk\b", sql, re.I):
        return sql
    if re.search(r"waerk\s*=", sql, re.I):
        return sql
    code = explicit or default
    m = re.search(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?waerk"?', sql, re.I)
    alias = m.group(1) if m else None
    cond = f'{alias}."waerk" = \'{code}\'' if alias else f"waerk = '{code}'"
    wm = re.search(r"\bWHERE\b", sql, re.I)
    if wm:
        return sql[: wm.end()] + f" {cond} AND" + sql[wm.end():]
    m2 = re.search(r"\s+(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.I)
    if m2:
        return sql[: m2.start()] + f" WHERE {cond}" + sql[m2.start():]
    return sql.rstrip().rstrip(";") + f" WHERE {cond}"


_BY_CUSTOMER_DIM = re.compile(
    r"\b(by|per|each|every)\s+customers?\b|\bcustomers?\s+and\s+industry\b|\bwith\s+customer\b",
    re.I,
)


def extract_named_customer(question: str) -> Optional[str]:
    """Named customer filter, or None when 'customer' is only a dimension."""
    q = (question or "").strip()
    if not q:
        return None
    if _BY_CUSTOMER_DIM.search(q) and not re.search(r"\bfor\s+customer\b", q, re.I):
        return None
    m = re.search(r"""['\"]([^'\"]{2,80})['\"]""", q)
    if m and not m.group(1).isdigit():
        return m.group(1).strip()
    m = re.search(
        r"\b(?:customer|client|sold-?to)\s+(?:named|called)?\s*([A-Za-z0-9][A-Za-z0-9 ._-]{1,80})",
        q,
        re.I,
    )
    if m:
        name = m.group(1).strip(" .,")
        if name.lower() not in {"and", "industry", "sales", "by", "with"}:
            return name
    m = re.search(
        r"\bfor\s+customer\s+([A-Za-z0-9][A-Za-z0-9 ._-]{1,80})",
        q,
        re.I,
    )
    if m:
        return m.group(1).strip(" .,")
    return None


def inject_customer_name_predicate(sql: str, customer_name: str) -> str:
    if not sql or not customer_name:
        return sql
    if re.search(r"name1.*ilike|ilike.*name1", sql, re.I):
        return sql
    safe = customer_name.replace("'", "''")
    # Prefer aliased name1 if present
    m = re.search(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?name1"?', sql, re.I)
    if m:
        pred = f"{m.group(1)}.\"name1\" ILIKE '%{safe}%'"
    elif re.search(r"\bname1\b", sql, re.I):
        pred = f"name1 ILIKE '%{safe}%'"
    else:
        kn = re.search(r'\b(?:JOIN|FROM)\s+"?KNA1"?\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)', sql, re.I)
        if kn:
            pred = f"{kn.group(1)}.\"name1\" ILIKE '%{safe}%'"
        else:
            m_kunag = re.search(
                r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?kunag"?',
                sql,
                re.I,
            )
            if not m_kunag:
                return sql
            a = m_kunag.group(1)
            pred = (
                f'EXISTS (SELECT 1 FROM "KNA1" _nc WHERE _nc."name1" ILIKE \'%{safe}%\' '
                f'AND LPAD(TRIM(_nc."kunnr"), 10, \'0\') = LPAD(TRIM({a}."kunag"), 10, \'0\'))'
            )
    wm = re.search(r"\bWHERE\b", sql, re.I)
    if wm:
        return sql[: wm.end()] + f" {pred} AND" + sql[wm.end():]
    m2 = re.search(r"\s+(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.I)
    if m2:
        return sql[: m2.start()] + f" WHERE {pred}" + sql[m2.start():]
    return sql.rstrip().rstrip(";") + f" WHERE {pred}"


def sql_has_customer_name_filter(sql: str, customer_name: str) -> bool:
    if not sql or not customer_name:
        return False
    return customer_name.lower() in sql.lower() and "ilike" in sql.lower()


_FKDAT_YEAR_IN = re.compile(
    r"(SUBSTRING\s*\(\s*TRIM\s*\(\s*CAST\s*\([^)]*?fkdat[^)]*?\)\s*\)\s*,\s*1\s*,\s*4\s*\)\s*IN\s*\()([^)]+)(\))",
    re.I | re.S,
)
_BRTXT_ILIKE = re.compile(
    r"\s+AND\s+[A-Za-z_][\w]*\.\"brtxt\"\s+ILIKE\s+'[^']*'",
    re.I,
)


def rewrite_fkdat_year_in_list(sql: str, years: List[str]) -> str:
    if not sql or not years:
        return sql
    quoted = ", ".join("'" + str(y).replace("'", "''") + "'" for y in years)
    if _FKDAT_YEAR_IN.search(sql):
        return _FKDAT_YEAR_IN.sub(lambda m: m.group(1) + quoted + m.group(3), sql, count=1)
    fake_q = "sales " + " ".join(str(y) for y in years)
    return inject_year_filters_from_question(sql, fake_q)


def ensure_year_select_and_group(sql: str) -> str:
    """Add calendar year to SELECT/GROUP BY so period compare is not a mixed-year total."""
    if not sql or re.search(r"\bAS\s+year\b", sql, re.I):
        return sql
    m = re.search(r'([A-Za-z_][\w]*)\s*\.\s*"?fkdat"?', sql, re.I)
    alias = m.group(1) if m else "v"
    expr = f'SUBSTRING(TRIM(CAST({alias}."fkdat" AS TEXT)), 1, 4)'
    out = sql
    if re.match(r"(?is)^\s*SELECT\b", out):
        out = re.sub(r"(?i)^\s*SELECT\b", f"SELECT\n    {expr} AS year,", out, count=1)
    if re.search(r"(?i)\bGROUP BY\b", out):
        out = re.sub(r"(?i)\bGROUP BY\s+", f"GROUP BY {expr}, ", out, count=1)
    out = re.sub(r"\s+LIMIT\s+\d+\s*;?\s*$", "", out, flags=re.I)
    return out


def inject_industry_name_filter(sql: str, industry: str) -> str:
    ind = (industry or "").strip()
    if not sql or not ind:
        return sql
    if re.search(rf"brtxt[^\n]{{0,80}}ILIKE[^\n]{{0,80}}{re.escape(ind)}", sql, re.I):
        return sql
    safe = ind.replace("'", "''")
    pred = f't."brtxt" ILIKE \'%{safe}%\''
    if not re.search(r"\bT016T\b|\bt\.\"brtxt\"", sql, re.I):
        return sql
    wm = re.search(r"\bWHERE\b", sql, re.I)
    if wm:
        return sql[: wm.end()] + f" {pred} AND" + sql[wm.end() :]
    m2 = re.search(r"\s+(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.I)
    if m2:
        return sql[: m2.start()] + f" WHERE {pred}" + sql[m2.start() :]
    return sql.rstrip().rstrip(";") + f" WHERE {pred}"


def strip_industry_ilike_filters(sql: str) -> str:
    if not sql:
        return sql
    return _BRTXT_ILIKE.sub("", sql)


def rewrite_sales_metric_to_invoice_count(sql: str) -> str:
    if not sql or re.search(r"count\s*\(\s*distinct", sql, re.I):
        return sql
    out = re.sub(
        r"SUM\s*\(\s*CAST\s*\(\s*NULLIF\s*\(\s*TRIM\s*\(\s*CAST\s*\(\s*v\.\"netwr\"[^)]*\)\s*\)\s*,\s*''\s*\)\s+AS\s+NUMERIC\s*\)\s*\)\s+AS\s+\w+",
        'COUNT(DISTINCT TRIM(v."vbeln")) AS invoice_count',
        sql,
        count=1,
        flags=re.I,
    )
    if out == sql:
        out = re.sub(
            r"SUM\s*\([^)]*netwr[^)]*\)\s+AS\s+\w+",
            'COUNT(DISTINCT TRIM(v."vbeln")) AS invoice_count',
            sql,
            count=1,
            flags=re.I,
        )
    if re.search(r"invoice_count", out, re.I):
        out = re.sub(r"\bORDER BY\s+total_sales\b", "ORDER BY invoice_count", out, flags=re.I)
        out = re.sub(r"\bORDER BY\s+value\b", "ORDER BY invoice_count", out, flags=re.I)
    return out


def apply_plan_sql_deltas(sql: str, plan: Any) -> str:
    """Deterministically apply QueryPlan deltas onto previous/intent SQL (no LLM)."""
    if not sql or plan is None:
        return sql
    out = sql
    years = list(getattr(plan, "filters", {}).get("years") or [])
    cmp_years = list(getattr(plan, "comparison_years", None) or [])
    operation = str(getattr(plan, "operation", "") or "")
    if operation == "compare" or len(cmp_years) >= 2:
        ys = cmp_years or years
        out = rewrite_fkdat_year_in_list(out, [str(y) for y in ys])
        out = ensure_year_select_and_group(out)
    elif years:
        out = rewrite_fkdat_year_in_list(out, [str(y) for y in years])

    industry = str((getattr(plan, "filters", {}) or {}).get("industry") or "").strip()
    delta_ops = list(getattr(plan, "delta_ops", None) or [])
    if industry:
        out = inject_industry_name_filter(out, industry)
    elif any(str(d).startswith("remove_filter:industry") for d in delta_ops):
        out = strip_industry_ilike_filters(out)

    metric = str(getattr(plan, "metric", "") or "")
    if metric == "count":
        out = rewrite_sales_metric_to_invoice_count(out)

    limit = getattr(plan, "limit", None)
    if limit and operation != "compare":
        out = apply_limit_n(out, int(limit))
        # Inherited default limits from "highest + customer" must not force EUR.
        if any("change_ranking:limit=" in str(d) for d in delta_ops):
            out = inject_single_currency_filter(out, f"top {int(limit)}")
    return out


def apply_ranking_discipline(sql: str, question: str) -> str:
    sql = apply_limit_from_question(sql, question)
    sql = inject_single_currency_filter(sql, question)
    named = extract_named_customer(question)
    if named:
        sql = inject_customer_name_predicate(sql, named)
    return sql


def repair_generated_sql(sql: str, question: str = "") -> str:
    """Local repairs so the first LLM SQL attempt can execute without a retry."""
    if not sql:
        return sql
    out = rewrite_netwr_empty_coalesce(sql)
    out = inject_lpad_join_keys(out)
    out = inject_sap_date_empty_guards(out, question)
    out = inject_year_filters_from_question(out, question)
    named = extract_named_customer(question)
    if named:
        out = inject_customer_name_predicate(out, named)
    out = apply_limit_from_question(out, question)
    return out


def is_supported_business_question(
    question: str,
    has_active_analysis: bool = False,
    previous_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Gate before SQL generation, result narration, and continuation handling.
    Runs on every incoming message, including follow-ups that carry prior context.
    Short analytical follow-ups stay allowed when active analysis exists.
    Returns (allowed, reason).
    """
    q = (question or "").strip()
    if not q:
        return False, "empty_question"
    ql = q.lower()
    if any(h in ql for h in _NONSENSE_HINTS):
        return False, "non_business"
    if re.search(r"\b(drop|truncate|delete from|alter table)\b", ql) and "invoice" not in ql:
        return False, "unsafe_or_non_business"
    # Schema questions are business-adjacent and allowed (answered without SAP fact SQL).
    if re.search(r"\b(which tables?|what columns?|data type|schema|shared columns)\b", ql):
        return True, "schema"
    # Governed deep-analytical follow-ups bypass the generic NL length gate.
    if previous_plan is not None:
        try:
            from .analytical_followup_resolver import is_deep_followup_allowed

            if is_deep_followup_allowed(q, previous_plan):
                return True, "deep_analytical_followup"
        except Exception:
            pass
    tokens = set(re.findall(r"[a-z0-9]+", ql))
    if tokens.intersection({t.lower() for t in _BUSINESS_TOKENS}):
        return True, "business_token"
    if re.search(r"\b(20\d{2}|19\d{2})\b", q):
        return True, "year"
    if has_active_analysis and tokens.intersection(_SHORT_FOLLOWUP_TOKENS):
        return True, "followup_context"
    if len(q) < 12:
        return False, "too_short"
    return False, "no_business_signal"


def clarification_payload(question: str, reason: str) -> Dict[str, Any]:
    summary = (
        "I can answer questions about SAP billing, customers, industries, products, "
        "invoice counts, and year comparisons. Please rephrase as a business question "
        "(for example: 'highest sales in 2004 by customer')."
    )
    return {
        "type": "clarification",
        "answer_status": "CLARIFICATION",
        "sql": "",
        "rowCount": 0,
        "data": [],
        "charts": [],
        "summary": summary,
        "answer": summary,
        "keyFindings": [reason],
        "question": (question or "")[:500],
        "failure_reason": reason,
    }


def customer_not_found_payload(question: str, customer_name: str, sql: str = "") -> Dict[str, Any]:
    summary = (
        f"No matching customer was found for '{customer_name}'. "
        "I did not return an unfiltered customer list. Check the spelling or try another name."
    )
    return {
        "type": "entity_not_found",
        "answer_status": "SUCCESS",
        "entity_not_found": True,
        "sql": sql or "",
        "rowCount": 0,
        "data": [],
        "charts": [],
        "summary": summary,
        "answer": summary,
        "keyFindings": [f"customer_not_found:{customer_name}"],
        "question": (question or "")[:500],
    }


def public_chart_title(question: str, fallback: str = "Results") -> str:
    q = (question or "").strip()
    low = q.lower()
    if any(m in low for m in _INTERNAL_TITLE_MARKERS) or "continuation" in low:
        m = re.search(
            r"New request \(generate ONE new PostgreSQL SELECT for this\):\s*(.+)$",
            q,
            re.I | re.S,
        )
        if m:
            q = m.group(1).strip()
        else:
            q = fallback
    q = q.rstrip("?").strip()
    if not q:
        return fallback
    if len(q) <= 50:
        return q
    for sep in [" by ", " from ", " using ", " between ", " for ", " in ", " of "]:
        idx = q.lower().find(sep)
        if 15 < idx <= 50:
            return q[:idx].strip()
    return q[:50].strip() + "…"


def sanitize_chart_payloads(charts: Optional[Iterable[Dict[str, Any]]], question: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in charts or []:
        if not isinstance(c, dict):
            continue
        item = dict(c)
        title = str(item.get("title") or "")
        if "continuation" in title.lower() or any(m in title.lower() for m in _INTERNAL_TITLE_MARKERS):
            item["title"] = public_chart_title(question, fallback="Results")
        out.append(item)
    return out


def deterministic_summary(question: str, data: List[Dict[str, Any]], sql: str) -> str:
    if not data:
        named = extract_named_customer(question)
        if named:
            return customer_not_found_payload(question, named, sql)["summary"]
        return "The query executed successfully but returned 0 rows."
    row = data[0]
    name = (
        row.get("customer_name")
        or row.get("customer")
        or row.get("material_name")
        or row.get("industry")
        or row.get("industry_name")
        or ""
    )
    amount = row.get("total_sales") or row.get("invoice_count") or row.get("count")
    currency = row.get("currency") or row.get("waerk") or ""
    bits = [f"Top result: {name}"] if name else ["Query returned results."]
    if amount is not None:
        bits.append(f"value {amount}")
    if currency:
        bits.append(str(currency))
    bits.append(f"({len(data)} row(s)).")
    return " ".join(str(b) for b in bits if b)
