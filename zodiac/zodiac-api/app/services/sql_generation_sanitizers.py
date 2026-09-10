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


def sanitize_trim_type_safety_sql(sql: str) -> str:
    """
    Wrap bare `TRIM(alias.column)` arguments in `CAST(... AS TEXT)`.

    Root cause this fixes: some SAP replica columns that catalog/generated SQL
    assumes are TEXT (e.g. matnr) are actually stored as NUMERIC in this DB.
    Postgres' TRIM()/btrim() only accepts text input, so a bare
    `TRIM(v.matnr)` raises `function pg_catalog.btrim(numeric) does not exist`
    whenever that column happens to be numeric — and this was being thrown
    inside a try/except in the catalog/operational paths and silently
    swallowed, so the query falls through to a weaker fallback engine
    instead of surfacing the real error.

    `CAST(x AS TEXT)` is safe and idempotent for both TEXT and NUMERIC
    columns (and NULL), so wrapping every bare `alias.column` TRIM argument
    this way fixes the crash regardless of the column's actual stored type,
    without needing to know in advance which columns are numeric.

    Skips arguments that are already a function call / CAST / nested
    expression (only rewrites the simple `alias.column` or bare `column`
    case) to avoid double-wrapping or mangling more complex expressions.
    """
    if not sql or "trim(" not in sql.lower():
        return sql

    def _replace(m: re.Match) -> str:
        arg = m.group(1)
        return f"TRIM(CAST({arg} AS TEXT))"

    # alias.column or bare column — simple identifier(s) only, no nested parens/commas
    sql = re.sub(
        r'\bTRIM\(\s*("?[A-Za-z_][A-Za-z0-9_]*"?(?:\s*\.\s*"?[A-Za-z_][A-Za-z0-9_]*"?)?)\s*\)',
        _replace,
        sql,
        flags=re.IGNORECASE,
    )
    return sql


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


# ── SAP amount columns stored as TEXT that need CAST for aggregate functions ──
# These are the known SAP columns in this PostgreSQL database that are stored as
# TEXT but represent numeric amounts and fail with SUM()/AVG() without a cast.
_SAP_NUMERIC_TEXT_COLUMNS: frozenset = frozenset({
    # GL / Finance (FAGLFLEXA, BSEG, BSAD, etc.)
    "hsl", "ksl", "msl", "wsl", "hsl0", "ksl0", "msl0", "wsl0",
    "dmbtr", "wrbtr", "dmbe2", "hwbe2", "pswbt", "pswsl",
    "shkzg",  # debit/credit indicator — sometimes summed as signed
    # Billing / Sales (VBRK, VBRP, KONV)
    "netwr", "mwsbp", "wavwr", "stawn", "kwert", "kbetr",
    "kzwi1", "kzwi2", "kzwi3", "kzwi4", "kzwi5", "kzwi6",
    "kursk", "kursk_m", "menge", "fklmg", "kwmeng",
    # Purchasing / Invoice (RBKP, RSEG, EKKO, EKPO)
    "rmwwr", "rmwsk", "netpr", "netwr_p", "brtwr",
    # Controlling / Costing (COEP, CKIS, KEPH, CKMLPR)
    "wkg001", "wkg002", "wkg003", "wkg004", "wkg005",
    "wkg006", "wkg007", "wkg008", "wkg009", "wkg010",
    "wkg011", "wkg012",
    "objnr", "lstar", "kstar",  # sometimes used in SUM-adjacent context
    # Material / Valuation (MBEW, CKMLCR, CKMLPP)
    "stprs", "verpr", "salk3", "salkv", "lbkum", "pvprs",
    "lfgja", "bklas",
    # Customer / Vendor balance
    "umskz",
})

# Aggregate functions that need CAST when applied to TEXT columns
_AGGREGATE_FUNCS = re.compile(r'\b(SUM|AVG|MIN|MAX)\s*\(', re.IGNORECASE)


def _wrap_text_column_in_cast(alias: str, col: str, func: str) -> str:
    """Return: FUNC(CAST(NULLIF(TRIM(CAST(alias."col" AS TEXT)), '') AS NUMERIC))"""
    inner = f'CAST({alias}."{col}" AS TEXT)' if alias else f'CAST("{col}" AS TEXT)'
    nullif = f'CAST(NULLIF(TRIM({inner}), \'\') AS NUMERIC)'
    return f'{func.upper()}({nullif})'


def sanitize_sap_amount_columns_sql(sql: str) -> str:
    """
    Wrap all known SAP numeric-text amount columns in CAST(NULLIF(TRIM(...)) AS NUMERIC)
    when they appear inside aggregate functions (SUM, AVG, MIN, MAX).

    This is needed because SAP columns like hsl, dmbtr, wrbtr etc. are stored as
    TEXT in this PostgreSQL instance, so bare SUM(alias."hsl") raises:
        function sum(text) does not exist

    Also fixes HAVING clause alias references:
        HAVING SUM(f."hsl") > 0  — which would fail after wrapping — to use the inline cast.
    """
    if not sql:
        return sql

    def _already_cast(expr: str) -> bool:
        low = expr.lower()
        return "cast(" in low or "nullif(" in low or "trim(" in low

    def _replace_aggregate(m: re.Match) -> str:
        """Called for each FUNC( occurrence; peeks ahead to find the argument."""
        func = m.group(1)
        pos_after_paren = m.end()
        # Find the content of the aggregate call: track nesting depth
        depth = 1
        i = pos_after_paren
        while i < len(sql) and depth > 0:
            c = sql[i]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        # i is at the closing ')'
        arg = sql[pos_after_paren:i].strip()
        closing = i  # index of ')'

        if _already_cast(arg):
            return m.group(0)  # already handled

        # Match: "TBL"."col", alias."col", alias.col, "col", col
        col_match = re.fullmatch(
            r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.\s*"?([A-Za-z_][A-Za-z0-9_]*)"?'  # "TBL".col
            r'|([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?([A-Za-z_][A-Za-z0-9_]*)"?'  # alias.col
            r'|"([A-Za-z_][A-Za-z0-9_]*)"'   # "col"
            r'|([A-Za-z_][A-Za-z0-9_]*)',     # bare col
            arg,
        )
        if not col_match:
            return m.group(0)

        if col_match.group(1) and col_match.group(2):
            alias_name, col_name = f'"{col_match.group(1)}"', col_match.group(2)
        elif col_match.group(3) and col_match.group(4):
            alias_name, col_name = col_match.group(3), col_match.group(4)
        elif col_match.group(5):
            alias_name, col_name = '', col_match.group(5)
        elif col_match.group(6):
            alias_name, col_name = '', col_match.group(6)
        else:
            return m.group(0)

        if col_name.lower() not in _SAP_NUMERIC_TEXT_COLUMNS:
            return m.group(0)

        return _wrap_text_column_in_cast(alias_name, col_name, func)

    # We can't use re.sub with a function that peeks at the full string easily,
    # so use a position-tracking loop instead.
    result_parts: List[str] = []
    last_end = 0

    for agg_match in _AGGREGATE_FUNCS.finditer(sql):
        func = agg_match.group(1)
        pos_after_paren = agg_match.end()
        # Find closing ')' of this aggregate call using depth tracking
        depth = 1
        i = pos_after_paren
        while i < len(sql) and depth > 0:
            c = sql[i]
            if c == '(':
                depth += 1
                i += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    # i is at the closing ')' — do NOT increment yet
                    break
                i += 1
            elif c == "'":
                # Skip string literals
                i += 1
                while i < len(sql) and sql[i] != "'":
                    i += 1
                if i < len(sql):
                    i += 1  # skip closing quote
            elif c == '"':
                # Skip quoted identifiers
                i += 1
                while i < len(sql) and sql[i] != '"':
                    i += 1
                if i < len(sql):
                    i += 1  # skip closing quote
            else:
                i += 1

        # i is at the closing ')' of the aggregate call
        # arg is everything between the opening '(' and this ')'
        arg = sql[pos_after_paren:i].strip()
        # end_of_call is the position AFTER the closing ')'
        end_of_call = i + 1

        if _already_cast(arg):
            # Already has a cast — copy unchanged up to end_of_call
            result_parts.append(sql[last_end:end_of_call])
            last_end = end_of_call
            continue

        col_match = re.fullmatch(
            r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.\s*"?([A-Za-z_][A-Za-z0-9_]*)"?'
            r'|([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"?([A-Za-z_][A-Za-z0-9_]*)"?'
            r'|"([A-Za-z_][A-Za-z0-9_]*)"'
            r'|([A-Za-z_][A-Za-z0-9_]*)',
            arg,
        )
        if not col_match:
            result_parts.append(sql[last_end:end_of_call])
            last_end = end_of_call
            continue

        if col_match.group(1) and col_match.group(2):
            alias_name, col_name = f'"{col_match.group(1)}"', col_match.group(2)
        elif col_match.group(3) and col_match.group(4):
            alias_name, col_name = col_match.group(3), col_match.group(4)
        elif col_match.group(5):
            alias_name, col_name = '', col_match.group(5)
        elif col_match.group(6):
            alias_name, col_name = '', col_match.group(6)
        else:
            result_parts.append(sql[last_end:end_of_call])
            last_end = end_of_call
            continue

        if col_name.lower() not in _SAP_NUMERIC_TEXT_COLUMNS:
            result_parts.append(sql[last_end:end_of_call])
            last_end = end_of_call
            continue

        # Replace the full aggregate call (from SUM start to closing ')' inclusive)
        result_parts.append(sql[last_end:agg_match.start()])
        result_parts.append(_wrap_text_column_in_cast(alias_name, col_name, func))
        last_end = end_of_call  # skip past the original closing ')'

    result_parts.append(sql[last_end:])
    normalized = ''.join(result_parts)

    # Final safety net: direct regex rewrite for plain aggregate calls that may
    # slip through the parser when formatting is unusual.
    col_alt = "|".join(sorted((re.escape(c) for c in _SAP_NUMERIC_TEXT_COLUMNS), key=len, reverse=True))
    strict_agg = re.compile(
        rf'\b(?P<func>SUM|AVG|MIN|MAX)\s*\(\s*'
        rf'(?:'
        rf'"(?P<qtbl>[A-Za-z_][A-Za-z0-9_]*)"\s*\.\s*'
        rf'|(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*'
        rf')?'
        rf'"?(?P<col>{col_alt})"?'
        rf'\s*\)',
        re.IGNORECASE,
    )

    def _strict_replace(m: re.Match) -> str:
        whole = m.group(0)
        if _already_cast(whole):
            return whole
        func = m.group("func") or "SUM"
        qtbl = (m.group("qtbl") or "").strip()
        alias = (m.group("alias") or "").strip()
        col = (m.group("col") or "").strip()
        qual = f'"{qtbl}"' if qtbl else alias
        return _wrap_text_column_in_cast(qual, col, func)

    normalized = strict_agg.sub(_strict_replace, normalized)
    return normalized


def _find_agg_aliases_in_select(sql: str) -> dict:
    """
    Scan the SELECT clause and build a mapping { alias_lower → aggregate_expression }.
    Handles nested parentheses (e.g. SUM(CAST(NULLIF(...))) AS alias).
    """
    alias_to_expr: dict = {}
    # Find SELECT ... FROM
    select_match = re.search(r'\bSELECT\b([\s\S]*?)\bFROM\b', sql, re.IGNORECASE)
    if not select_match:
        return alias_to_expr
    select_clause = select_match.group(1)

    # Walk through looking for FUNC( ... ) AS alias patterns
    agg_pat = re.compile(r'\b(SUM|AVG|MIN|MAX)\s*\(', re.IGNORECASE)
    i = 0
    while i < len(select_clause):
        m = agg_pat.search(select_clause, i)
        if not m:
            break
        func_start = m.start()
        paren_start = m.end()  # right after '('
        # Find matching closing ')'
        depth = 1
        j = paren_start
        while j < len(select_clause) and depth > 0:
            c = select_clause[j]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            elif c == "'":
                j += 1
                while j < len(select_clause) and select_clause[j] != "'":
                    j += 1
            elif c == '"':
                j += 1
                while j < len(select_clause) and select_clause[j] != '"':
                    j += 1
            j += 1
        # j is at closing ')' of the aggregate
        agg_expr = select_clause[func_start:j + 1]
        rest = select_clause[j + 1:]
        # Look for AS alias right after
        alias_m = re.match(r'\s+AS\s+"?([a-zA-Z_][a-zA-Z0-9_]*)"?', rest, re.IGNORECASE)
        if alias_m:
            alias = alias_m.group(1)
            alias_to_expr[alias.lower()] = agg_expr
        i = j + 1

    return alias_to_expr


def sanitize_having_alias_references(sql: str) -> str:
    """
    Fix HAVING clauses that reference SELECT-level column aliases.
    PostgreSQL does not allow SELECT aliases in HAVING (only in ORDER BY).

    Strategy: scan SELECT clause for aliased aggregates, then replace bare alias
    references in HAVING with the actual aggregate expression.
    """
    if not sql or "HAVING" not in sql.upper():
        return sql

    alias_to_expr = _find_agg_aliases_in_select(sql)
    if not alias_to_expr:
        return sql

    def _replace_having_alias(having_match: re.Match) -> str:
        having_clause = having_match.group(0)
        for alias, expr in alias_to_expr.items():
            # Replace quoted alias "alias_name" first
            having_clause = having_clause.replace(f'"{alias}"', expr)
            # Replace bare alias (not part of longer identifier)
            having_clause = re.sub(
                r'(?<![a-zA-Z0-9_"\'.`])' + re.escape(alias) + r'(?![a-zA-Z0-9_"\'.`])',
                expr,
                having_clause,
                flags=re.IGNORECASE,
            )
        return having_clause

    # Apply only to the HAVING clause
    sql = re.sub(
        r'\bHAVING\b[\s\S]*?(?=\s*(?:\bORDER\s+BY\b|\bLIMIT\b|\bUNION\b|;)\s|$)',
        _replace_having_alias,
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def sanitize_generated_sap_sql(sql: str, question: Optional[str] = None) -> str:
    """
    Apply all SQL sanitization in order:
    1. gjahr → fkdat-based year
    2. netwr CAST (kept for backward compat, now also covered by generic sanitizer)
    3. ALL SAP numeric text columns → CAST(NULLIF(TRIM(...)) AS NUMERIC) in aggregates
    4. Fix HAVING alias references
    5. Optional FKDAT calendar year filter injection
    """
    if not sql:
        return sql
    s = sanitize_trim_type_safety_sql(sql)
    s = sanitize_gjahr_sql(s)
    s = sanitize_netwr_sql(s)
    s = sanitize_sap_amount_columns_sql(s)
    s = sanitize_having_alias_references(s)
    if question:
        s, _notes = inject_fkdat_calendar_year_filter(s, question)
    return s
