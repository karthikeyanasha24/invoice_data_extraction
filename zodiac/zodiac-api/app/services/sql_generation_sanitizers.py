"""
Post-process LLM / stored SQL before validation and execution.

- GJAHR: In this DB VBRK.gjahr is often '0000' for all rows — never use it for year logic.
- NETWR: vbrp.netwr is TEXT — SUM() needs NULLIF(TRIM(...::text),'')::NUMERIC.
- SQLAlchemy text(): escape PostgreSQL :: casts (otherwise :text is treated as a bind).

Used by ai_analysis_orchestrator, sap_sql_precision_validator (approve-query path), and dashboard suggest-sql.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple


def escape_postgres_casts_for_sqlalchemy(sql: str) -> str:
    """
    SQLAlchemy's text() treats :name as bind parameters. PostgreSQL casts use ::text,
    ::numeric, etc. — the second colon starts :text which gets replaced and corrupts SQL.

    Doubling backslash-colon is the documented workaround: \\:\\: → :: in the final SQL.
    """
    if not sql:
        return sql
    return sql.replace("::", r"\:\:")


def substitute_literal_sqlalchemy_bind_placeholders(sql: str) -> str:
    """
    When SQL is executed via text(sql) *without* bindparams(), placeholders like
    LIMIT :limit are interpreted as named binds — missing values become empty → LIMIT ''.

    Replace common copy-paste patterns from Python scripts with numeric literals.
    """
    if not sql:
        return sql
    # LIMIT / OFFSET (case-insensitive)
    sql = re.sub(r"(?i)\bLIMIT\s*:limit\b", "LIMIT 100", sql)
    sql = re.sub(r"(?i)\bLIMIT\s*:lim\b", "LIMIT 100", sql)
    sql = re.sub(r"(?i)\bLIMIT\s*:sample_limit\b", "LIMIT 50", sql)
    sql = re.sub(r"(?i)\bOFFSET\s*:offset\b", "OFFSET 0", sql)
    return sql


def prepare_sql_for_sqlalchemy_text_execution(sql: str) -> str:
    """
    Full prep before db.execute(text(...)) with NO second argument:
    1) Escape :: casts
    2) Replace :limit-style placeholders that would otherwise corrupt LIMIT
    """
    if not sql:
        return sql
    s = escape_postgres_casts_for_sqlalchemy(sql)
    s = substitute_literal_sqlalchemy_bind_placeholders(s)
    return s


def sanitize_gjahr_sql(sql: str) -> str:
    """
    Replace gjahr references with FKDAT-based calendar year expression.
    Handles uppercase aliases (R."gjahr") which the old [a-z]-only pattern missed.
    """
    if not sql or "gjahr" not in sql.lower():
        return sql

    # alias."gjahr" or alias."GJAHR" (re.I matches quoted column case)
    sql = re.sub(
        r'(\b[a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*"gjahr"',
        lambda m: f'SUBSTRING(TRIM({m.group(1)}."fkdat"),1,4)',
        sql,
        flags=re.IGNORECASE,
    )
    # Unquoted: alias.gjahr
    sql = re.sub(
        r'(\b[a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*gjahr\b',
        lambda m: f'SUBSTRING(TRIM({m.group(1)}."fkdat"),1,4)',
        sql,
        flags=re.IGNORECASE,
    )
    # Bare gjahr (SELECT gjahr, GROUP BY gjahr) — last resort; assumes fkdat is in scope
    sql = re.sub(
        r'(?<![a-zA-Z0-9_])gjahr(?![a-zA-Z0-9_])',
        'SUBSTRING(TRIM(fkdat),1,4)',
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def _question_needs_fkdat_calendar_year(question: str) -> bool:
    """Match precision validator: year-scoped billing questions that require FKDAT (not gjahr alone)."""
    q = (question or "").lower()
    revenue_intent = bool(
        re.search(
            r"\b(revenue|sales|billing|invoice value|invoice amount|total sales|amount|turnover|net value|netwr)\b",
            q,
        )
    )
    ranking_intent = bool(
        re.search(
            r"\b(top|bottom|highest|lowest|largest|smallest|most|least|rank|ranking|best|worst)\b",
            q,
        )
        and re.search(
            r"\b(customer|customers|material|materials|vendor|vendors|product|products|item|items|article|articles)\b",
            q,
        )
    )
    breakdown_intent = bool(
        re.search(r"\b(by customer|by material|by vendor|by product|per customer|per product)\b", q)
    )
    return bool(revenue_intent or ranking_intent or breakdown_intent)


def _sql_has_fkdat_year_predicate(sql: str, year: str) -> bool:
    s = (sql or "").lower()
    if re.search(r"fkdat[^;]{0,260}(?:19|20)\d{2}", s, re.IGNORECASE):
        return True
    if re.search(
        r"substring\s*\([^)]*fkdat[^)]*1\s*,\s*4[^)]*\)\s*=\s*'" + re.escape(year) + r"'",
        s,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"fkdat\s+between\s*'" + re.escape(year) + r"\d{4}'\s+and\s*'" + re.escape(year) + r"\d{4}'",
        s,
        re.IGNORECASE,
    ):
        return True
    return False


def _infer_vbrk_alias(sql: str) -> Optional[str]:
    """Return alias used for VBRK in FROM/JOIN, or None."""
    if not sql:
        return None
    m = re.search(
        r"(?i)(?:FROM|JOIN)\s+(?:\"?VBRK\"?|\bVBRK\b)\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
        sql,
    )
    if m:
        return m.group(1)
    return None


def inject_fkdat_calendar_year_filter(sql: str, question: Optional[str]) -> Tuple[str, List[str]]:
    """
    When the question names a calendar year and asks for billing ranking/revenue/breakdown,
    ensure VBRK.fkdat is filtered to that year. Best-effort for a single top-level SELECT.
    """
    notes: List[str] = []
    if not sql or not question:
        return sql, notes
    ym = re.search(r"\b((?:19|20)\d{2})\b", question)
    if not ym:
        return sql, notes
    year = ym.group(1)
    sl = sql.lower()
    if "vbrp" not in sl and "vbrk" not in sl:
        return sql, notes
    if not _question_needs_fkdat_calendar_year(question):
        return sql, notes
    if _sql_has_fkdat_year_predicate(sql, year):
        return sql, notes
    alias = _infer_vbrk_alias(sql)
    if not alias:
        return sql, notes
    cond = f'SUBSTRING(TRIM({alias}."fkdat"),1,4) = \'{year}\''
    # Prefer: extend existing WHERE before GROUP BY / ORDER BY / LIMIT
    if re.search(r"\bWHERE\b", sql, re.IGNORECASE):
        new_sql, n = re.subn(
            r"(\bWHERE\b)([\s\S]*?)(\s+(?:GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING)\b)",
            lambda m: m.group(1) + m.group(2) + f" AND ({cond})" + m.group(3),
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if n:
            notes.append(f"Auto-injected FKDAT calendar year filter for {year}.")
            return new_sql, notes
        return sql, notes
    m2 = re.search(r"(\s+)(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.IGNORECASE)
    if m2:
        new_sql = sql[: m2.start()] + f" WHERE ({cond})" + sql[m2.start() :]
        notes.append(f"Auto-injected FKDAT calendar year filter for {year}.")
        return new_sql, notes
    new_sql = sql.rstrip().rstrip(";") + f" WHERE ({cond})"
    notes.append(f"Auto-injected FKDAT calendar year filter for {year}.")
    return new_sql, notes


def sanitize_netwr_sql(sql: str) -> str:
    """
    Replace bare SUM(alias.netwr) with safe TEXT→NUMERIC cast for vbrp.netwr.
    Skips expressions that already use NULLIF or ::numeric.
    """
    if not sql:
        return sql

    def _already_cast(expr: str) -> bool:
        low = expr.lower()
        return "::numeric" in low or "nullif" in low or "::float" in low

    def _replace_alias_netwr(m: re.Match) -> str:
        full = m.group(0)
        if _already_cast(full):
            return full
        alias = m.group(1)
        return f'SUM(NULLIF(TRIM({alias}."netwr"::text),\'\')::NUMERIC)'

    sql = re.sub(
        r'SUM\s*\(\s*(\b[a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*"?netwr"?\s*\)',
        _replace_alias_netwr,
        sql,
        flags=re.IGNORECASE,
    )

    def _replace_bare_netwr(m: re.Match) -> str:
        full = m.group(0)
        if _already_cast(full):
            return full
        return "SUM(NULLIF(TRIM(netwr::text),'')::NUMERIC)"

    sql = re.sub(
        r'SUM\s*\(\s*"?netwr"?\s*\)',
        _replace_bare_netwr,
        sql,
        flags=re.IGNORECASE,
    )

    return sql


def sanitize_generated_sap_sql(sql: str, question: Optional[str] = None) -> str:
    """Apply gjahr then netwr rewrites (order matters: gjahr first), then optional FKDAT year inject."""
    if not sql:
        return sql
    s = sanitize_netwr_sql(sanitize_gjahr_sql(sql))
    if question:
        s, _notes = inject_fkdat_calendar_year_filter(s, question)
    return s
