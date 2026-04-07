"""
Post-process LLM / stored SQL before validation and execution.

- GJAHR: In this DB VBRK.gjahr is often '0000' for all rows — never use it for year logic.
- NETWR: vbrp.netwr is TEXT — SUM() needs CAST(NULLIF(TRIM(CAST(x AS TEXT)),'') AS NUMERIC).
- SQLAlchemy text(): must convert PostgreSQL ::type shorthand to CAST(expr AS type).
  The backslash-escape approach (\\:\\:) does NOT work reliably — SQLAlchemy removes the
  backslash but keeps the colon, so psycopg2 receives \\: which is invalid SQL.
  The correct fix is to eliminate ::type entirely before passing to text().

Used by ai_analysis_orchestrator, sap_sql_precision_validator (approve-query path), and dashboard suggest-sql.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# SQL function names that can appear before '(' in a CAST-target expression
_SQL_FUNC_NAMES = frozenset({
    "NULLIF", "TRIM", "COALESCE", "CAST", "SUM", "MAX", "MIN", "AVG", "COUNT",
    "UPPER", "LOWER", "SUBSTRING", "LEFT", "RIGHT", "REPLACE", "TO_CHAR",
    "TO_DATE", "TO_NUMBER", "LENGTH", "LPAD", "RPAD", "LTRIM", "RTRIM",
    "ROUND", "FLOOR", "CEIL", "CEILING", "ABS", "NULLIF", "GREATEST", "LEAST",
    "CONCAT", "SPLIT_PART", "REGEXP_REPLACE", "EXTRACT", "DATE_PART",
    "DATE_TRUNC", "TO_TIMESTAMP", "NOW", "CURRENT_DATE", "ARRAY_AGG",
    "STRING_AGG", "ARRAY_LENGTH", "UNNEST",
})


def _find_expr_start(buf: str) -> int:
    """
    Given a buffer ending with an atom (identifier, quoted string, or ')'),
    return the index where that atom starts so it can be wrapped in CAST().

    Handles:
    - Simple identifiers: word chars, dots, underscores
    - Quoted identifiers: "col", alias."col"
    - Parenthesized expressions ending with ')', including the function name before '('
    """
    stripped = buf.rstrip()
    if not stripped:
        return len(buf)

    last = stripped[-1]

    if last == ')':
        # Find matching '(' — respects nesting, string literals, quoted identifiers
        depth = 0
        k = len(stripped) - 1
        while k >= 0:
            c = stripped[k]
            if c == ')':
                depth += 1
                k -= 1
            elif c == '(':
                depth -= 1
                if depth == 0:
                    break
                k -= 1
            elif c == '"':
                # Scan past quoted identifier (backwards)
                k -= 1
                while k >= 0 and stripped[k] != '"':
                    k -= 1
                k -= 1
            elif c == "'":
                # Scan past string literal (backwards)
                k -= 1
                while k >= 0 and stripped[k] != "'":
                    k -= 1
                k -= 1
            else:
                k -= 1

        # k is at the opening '(' — check for function name before it
        func_end = k - 1
        while func_end >= 0 and stripped[func_end] == ' ':
            func_end -= 1
        func_start = func_end
        while func_start > 0 and (stripped[func_start - 1].isalnum() or stripped[func_start - 1] == '_'):
            func_start -= 1
        candidate_func = stripped[func_start:func_end + 1].upper()
        if candidate_func in _SQL_FUNC_NAMES:
            expr_start = func_start
        else:
            expr_start = k  # just the parenthesized expression without function name

        return expr_start + (len(buf) - len(stripped))  # adjust for trailing whitespace

    # Identifier / quoted identifier / string literal at end
    k = len(stripped)
    while k > 0:
        c = stripped[k - 1]
        if c.isalnum() or c == '_':
            k -= 1
        elif c == '"':
            # Double-quoted identifier — find opening '"'
            k -= 1
            while k > 0 and stripped[k - 1] != '"':
                k -= 1
            k -= 1  # skip opening '"'
        elif c == "'":
            # Single-quoted string literal — find opening "'"
            k -= 1
            while k > 0:
                if stripped[k - 1] == "'":
                    # Could be '' (escaped quote) — peek further
                    if k >= 2 and stripped[k - 2] == "'":
                        k -= 2  # skip ''
                        continue
                    k -= 1  # skip opening "'"
                    break
                k -= 1
        elif c == '.':
            # Qualified name separator (alias.column)
            k -= 1
        else:
            break

    return k + (len(buf) - len(stripped))


def convert_pg_casts_to_ansi(sql: str) -> str:
    """
    Convert every PostgreSQL ::typename shorthand to ANSI CAST(expr AS TYPENAME).

    This eliminates all '::' sequences before the SQL is handed to SQLAlchemy text(),
    which would otherwise mis-parse ':typename' as a named bind parameter and replace it
    with an empty string, corrupting the SQL entirely.

    Handles:
    - Simple identifiers:          p."netwr"::text   →  CAST(p."netwr" AS TEXT)
    - Parenthesized expressions:   NULLIF(...)::NUMERIC → CAST(NULLIF(...) AS NUMERIC)
    - String literals:             ''::text          →  CAST('' AS TEXT)
    - Skips content inside single-quoted strings and double-quoted identifiers.
    """
    if not sql or '::' not in sql:
        return sql

    result: List[str] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # ── Single-quoted string literal — copy verbatim ──────────────────────
        if ch == "'":
            result.append(ch)
            i += 1
            while i < n:
                c = sql[i]
                result.append(c)
                i += 1
                if c == "'":
                    # '' is an escaped quote — keep going
                    if i < n and sql[i] == "'":
                        result.append(sql[i])
                        i += 1
                    else:
                        break
            continue

        # ── Double-quoted identifier — copy verbatim ─────────────────────────
        if ch == '"':
            result.append(ch)
            i += 1
            while i < n and sql[i] != '"':
                result.append(sql[i])
                i += 1
            if i < n:
                result.append(sql[i])
                i += 1
            continue

        # ── PostgreSQL ::typename ─────────────────────────────────────────────
        if ch == ':' and i + 1 < n and sql[i + 1] == ':':
            # Require a letter or underscore after :: (true typename, not :: operator misuse)
            if i + 2 < n and (sql[i + 2].isalpha() or sql[i + 2] == '_'):
                # Extract the typename
                j = i + 2
                while j < n and (sql[j].isalnum() or sql[j] == '_'):
                    j += 1
                typename = sql[i + 2:j].upper()

                # Find the expression preceding :: in the accumulated result
                buf = ''.join(result)
                expr_start = _find_expr_start(buf)
                prefix = buf[:expr_start]
                expr = buf[expr_start:]

                if expr.strip():
                    result = [prefix, f'CAST({expr.strip()} AS {typename})']
                else:
                    # Nothing recognisable before :: — keep the :: and move on
                    result.append('::')
                i = j
                continue

        result.append(ch)
        i += 1

    return ''.join(result)


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


def escape_postgres_casts_for_sqlalchemy(sql: str) -> str:
    """
    DEPRECATED: Use convert_pg_casts_to_ansi() instead.
    Kept for backward compatibility — now delegates to the proper CAST converter.
    """
    return convert_pg_casts_to_ansi(sql)


def prepare_sql_for_sqlalchemy_text_execution(sql: str) -> str:
    """
    Full prep before db.execute(text(...)) with NO second argument:
    1) Convert PostgreSQL ::type shorthand to ANSI CAST(expr AS type) — eliminates
       the SQLAlchemy bind-param confusion that corrupts ::text → :'' in executed SQL.
    2) Replace :limit-style placeholders that would otherwise corrupt LIMIT.
    """
    if not sql:
        return sql
    s = convert_pg_casts_to_ansi(sql)
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
    Skips expressions that already use NULLIF or CAST.

    Uses ANSI CAST() syntax — never :: shorthand — so the output is safe to pass
    to SQLAlchemy text() without any further escaping.
    """
    if not sql:
        return sql

    def _already_cast(expr: str) -> bool:
        low = expr.lower()
        return "cast(" in low or "nullif" in low

    def _replace_alias_netwr(m: re.Match) -> str:
        full = m.group(0)
        if _already_cast(full):
            return full
        alias = m.group(1)
        return f"SUM(CAST(NULLIF(TRIM(CAST({alias}.\"netwr\" AS TEXT)), '') AS NUMERIC))"

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
        return "SUM(CAST(NULLIF(TRIM(CAST(netwr AS TEXT)), '') AS NUMERIC))"

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
