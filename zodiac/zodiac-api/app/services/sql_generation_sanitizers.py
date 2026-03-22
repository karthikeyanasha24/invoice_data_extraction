"""
Post-process LLM / stored SQL before validation and execution.

- GJAHR: In this DB VBRK.gjahr is often '0000' for all rows — never use it for year logic.
- NETWR: vbrp.netwr is TEXT — SUM() needs NULLIF(TRIM(...::text),'')::NUMERIC.
- SQLAlchemy text(): escape PostgreSQL :: casts (otherwise :text is treated as a bind).

Used by ai_analysis_orchestrator, sap_sql_precision_validator (approve-query path), and dashboard suggest-sql.
"""
from __future__ import annotations

import re


def escape_postgres_casts_for_sqlalchemy(sql: str) -> str:
    """
    SQLAlchemy's text() treats :name as bind parameters. PostgreSQL casts use ::text,
    ::numeric, etc. — the second colon starts :text which gets replaced and corrupts SQL.

    Doubling backslash-colon is the documented workaround: \\:\\: → :: in the final SQL.
    """
    if not sql:
        return sql
    return sql.replace("::", r"\:\:")


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


def sanitize_generated_sap_sql(sql: str) -> str:
    """Apply gjahr then netwr rewrites (order matters: gjahr first)."""
    if not sql:
        return sql
    return sanitize_netwr_sql(sanitize_gjahr_sql(sql))
