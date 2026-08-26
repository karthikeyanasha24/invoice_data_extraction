"""
Governed VBRK.FKDAT time expressions.

FKDAT is TEXT in YYYYMMDD form in this extract (documented in RAG/sql_catalog).
Never CAST FKDAT AS DATE for extraction — use SUBSTRING on trimmed text.

Labels:
  year         → YYYY
  year_month   → YYYY-MM
  year_quarter → YYYY-Q1..Q4
"""
from __future__ import annotations


def fkdat_text(alias: str = "vk") -> str:
    return f'TRIM(CAST({alias}."fkdat" AS TEXT))'


def fkdat_valid_predicate(alias: str = "vk") -> str:
    """Reject NULL/empty/short/non-numeric year-month fragments."""
    t = fkdat_text(alias)
    return (
        f'{alias}."fkdat" IS NOT NULL'
        f" AND {t} <> ''"
        f" AND LENGTH({t}) >= 6"
        f" AND SUBSTRING({t}, 1, 4) ~ '^[12][0-9]{{3}}$'"
        f" AND SUBSTRING({t}, 5, 2) ~ '^(0[1-9]|1[0-2])$'"
    )


def year_sql(alias: str = "vk") -> str:
    return f"SUBSTRING({fkdat_text(alias)}, 1, 4)"


def month_num_sql(alias: str = "vk") -> str:
    return f"SUBSTRING({fkdat_text(alias)}, 5, 2)"


def year_month_sql(alias: str = "vk") -> str:
    """Governed month label YYYY-MM."""
    t = fkdat_text(alias)
    return f"(SUBSTRING({t}, 1, 4) || '-' || SUBSTRING({t}, 5, 2))"


def year_quarter_sql(alias: str = "vk") -> str:
    """Governed quarter label YYYY-Q1..Q4 (year-aware)."""
    t = fkdat_text(alias)
    qnum = f"(((CAST(SUBSTRING({t}, 5, 2) AS INTEGER) - 1) / 3) + 1)"
    return f"(SUBSTRING({t}, 1, 4) || '-Q' || CAST({qnum} AS TEXT))"


def year_filter_sql(years, alias: str = "vk") -> str:
    if not years:
        return ""
    ys = ", ".join(f"'{int(y)}'" for y in years)
    return (
        f" AND {fkdat_valid_predicate(alias)}"
        f" AND {year_sql(alias)} IN ({ys})"
    )
