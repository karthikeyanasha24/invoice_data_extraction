"""Credit-free billing breakdowns: by customer, country, material, or industry.

Rankings and year/month series stay on their existing templates. Each amount is
split by billing currency so a row can be opened into invoices.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..data_catalog.physical import has_column, has_table, resolve_table_name
from .adaptive_structured_sql import (
    _COUNTRY_CODES,
    _sap_year_predicate,
    extract_question_years,
    numeric_cast_expr,
)

_RANK = re.compile(
    r"\b(top|bottom|highest|lowest|most|least|best|worst|largest|biggest|smallest|leading|rank|ranking)\b",
    re.I,
)
_PERIOD = re.compile(r"\b(?:by|per|each)\s+(?:months?|quarters?|years?)\b|\b(?:monthly|quarterly|yearly|annual)\b", re.I)
_MONEY = re.compile(r"\b(sales|revenue|billing|billed|turnover)\b", re.I)
_CURRENCY = re.compile(r"\b(DEM|USD|EUR|GBP|INR|JPY|CHF|AUD|CAD)\b")


def build_grouped_billing_sql(
    question: str,
    tables: List[str],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    q = question or ""
    if _RANK.search(q) or _PERIOD.search(q) or not _MONEY.search(q):
        return None
    if not has_table("VBRK") or not has_column("VBRK", "netwr"):
        return None
    hdr = resolve_table_name("VBRK") or "VBRK"
    low = q.lower()
    if (
        re.search(r"\bcustomers?\b", low)
        and re.search(r"\b(?:no|without|none|zero)\b", low)
        and has_table("KNA1")
    ):
        return _customers_without_billing(question, hdr)

    dim = _dimension(low)
    country = _country(low)
    currency = _CURRENCY.search(q)
    currency = currency.group(1).upper() if currency else None
    if dim is None and country is None:
        return None
    if dim is None:
        dim = "currency"
    wants_average = bool(re.search(r"\b(average|avg|mean)\b", low))
    if dim == "material":
        return _material_sql(question, hdr, wants_average, currency)
    return _header_sql(question, hdr, dim, country, currency, wants_average)


def _dimension(q: str) -> Optional[str]:
    if re.search(r"\b(?:by|per|each)\s+customers?\b", q):
        return "customer"
    if re.search(r"\b(?:by|per|each)\s+countr", q):
        return "country"
    if re.search(r"\b(?:by|per|each)\s+(?:materials?|products?)\b", q):
        return "material"
    if re.search(r"\b(?:by|per|each)\s+industr", q):
        return "industry"
    return None


def _country(q: str) -> Optional[str]:
    for name, iso in sorted(_COUNTRY_CODES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(name)}\b", q):
            return iso
    return None


def _customers_without_billing(question: str, hdr: str) -> str:
    year_sql = ""
    if has_column(hdr, "fkdat"):
        pred = _sap_year_predicate("k", "fkdat", extract_question_years(question))
        if pred:
            year_sql = f"\n      AND {pred}"
    return (
        'SELECT TRIM(CAST(c."kunnr" AS TEXT)) AS "customer_id", TRIM(CAST(c."name1" AS TEXT)) AS "customer_name"\n'
        'FROM "KNA1" c\n'
        "WHERE NULLIF(TRIM(CAST(c.\"kunnr\" AS TEXT)), '') IS NOT NULL\n"
        "  AND NOT EXISTS (\n"
        f'    SELECT 1 FROM "{hdr}" k\n'
        "    WHERE LPAD(TRIM(CAST(k.\"kunag\" AS TEXT)), 10, '0') = LPAD(TRIM(CAST(c.\"kunnr\" AS TEXT)), 10, '0')"
        f"{year_sql}\n"
        "  )\n"
        'ORDER BY "customer_name" ASC\n'
        "LIMIT 200"
    )


def _header_sql(question: str, hdr: str, dim: str, country: Optional[str], currency: Optional[str], wants_average: bool) -> Optional[str]:
    net = numeric_cast_expr(hdr, "netwr").replace(f'"{hdr}".', "k.")
    amount_name = "average_invoice_value" if wants_average else "total_sales"
    amount = f"AVG({net})" if wants_average else f"SUM({net})"
    where = [f"{net} IS NOT NULL"]
    if has_column(hdr, "fkdat"):
        pred = _sap_year_predicate("k", "fkdat", extract_question_years(question))
        if pred:
            where.append(pred)
    if currency and has_column(hdr, "waerk"):
        where.append(f"TRIM(CAST(k.\"waerk\" AS TEXT)) = '{currency}'")
    select: List[str] = []
    group: List[str] = []
    joins: List[str] = []
    needs_customer = dim in {"customer", "country", "industry"} or country is not None
    if needs_customer:
        if not has_table("KNA1"):
            return None
        joins.append(
            'LEFT JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\')'
        )
    if dim == "customer":
        select += ['TRIM(CAST(c."kunnr" AS TEXT)) AS "customer_id"', 'TRIM(CAST(c."name1" AS TEXT)) AS "customer_name"']
        group += ['TRIM(CAST(c."kunnr" AS TEXT))', 'TRIM(CAST(c."name1" AS TEXT))']
    elif dim == "country":
        if not has_column("KNA1", "land1"):
            return None
        select.append('TRIM(CAST(c."land1" AS TEXT)) AS "country"')
        group.append('TRIM(CAST(c."land1" AS TEXT))')
    elif dim == "industry":
        if not has_column("KNA1", "brsch") or not has_table("T016T"):
            return None
        joins.append(
            'LEFT JOIN "T016T" t ON LPAD(TRIM(CAST(c."brsch" AS TEXT)), 10, \'0\') = LPAD(TRIM(CAST(t."brsch" AS TEXT)), 10, \'0\')'
        )
        select.append('TRIM(CAST(t."brtxt" AS TEXT)) AS "industry"')
        group.append('TRIM(CAST(t."brtxt" AS TEXT))')
    if country and has_column("KNA1", "land1"):
        where.append(f"TRIM(CAST(c.\"land1\" AS TEXT)) = '{country}'")
    if has_column(hdr, "waerk"):
        select.append('TRIM(CAST(k."waerk" AS TEXT)) AS "currency"')
        group.append('TRIM(CAST(k."waerk" AS TEXT))')
    select.append(f'{amount} AS "{amount_name}"')
    if wants_average and has_column(hdr, "vbeln"):
        select.append('COUNT(DISTINCT TRIM(CAST(k."vbeln" AS TEXT))) AS "invoice_count"')
    return (
        "SELECT " + ", ".join(select) + "\n"
        f'FROM "{hdr}" k\n'
        + ("\n".join(joins) + "\n" if joins else "")
        + "WHERE " + "\n  AND ".join(where) + "\n"
        "GROUP BY " + ", ".join(group) + "\n"
        f'ORDER BY "{amount_name}" DESC NULLS LAST\n'
        "LIMIT 200"
    )


def _material_sql(question: str, hdr: str, wants_average: bool, currency: Optional[str]) -> Optional[str]:
    item = resolve_table_name("VBRP") or "VBRP"
    if not has_table(item) or not has_column(item, "netwr") or not has_column(item, "matnr"):
        return None
    item_net = numeric_cast_expr(item, "netwr").replace(f'"{item}".', "i.")
    amount_name = "average_invoice_value" if wants_average else "total_sales"
    amount = f"AVG({item_net})" if wants_average else f"SUM({item_net})"
    where = [f"{item_net} IS NOT NULL"]
    joins = [
        f'JOIN "{hdr}" k ON i."mandt" = k."mandt" AND LPAD(TRIM(CAST(i."vbeln" AS TEXT)), 10, \'0\') = LPAD(TRIM(CAST(k."vbeln" AS TEXT)), 10, \'0\')'
    ]
    if has_column(hdr, "fkdat"):
        pred = _sap_year_predicate("k", "fkdat", extract_question_years(question))
        if pred:
            where.append(pred)
    if currency and has_column(hdr, "waerk"):
        where.append(f"TRIM(CAST(k.\"waerk\" AS TEXT)) = '{currency}'")
    select = ['TRIM(CAST(i."matnr" AS TEXT)) AS "material_id"']
    group = ['TRIM(CAST(i."matnr" AS TEXT))']
    if has_table("MAKT") and has_column("MAKT", "maktx"):
        joins.append('LEFT JOIN "MAKT" m ON LPAD(TRIM(CAST(i."matnr" AS TEXT)), 18, \'0\') = LPAD(TRIM(CAST(m."matnr" AS TEXT)), 18, \'0\')')
        select.append('TRIM(CAST(m."maktx" AS TEXT)) AS "material_name"')
        group.append('TRIM(CAST(m."maktx" AS TEXT))')
    if has_column(hdr, "waerk"):
        select.append('TRIM(CAST(k."waerk" AS TEXT)) AS "currency"')
        group.append('TRIM(CAST(k."waerk" AS TEXT))')
    select.append(f'{amount} AS "{amount_name}"')
    return (
        "SELECT " + ", ".join(select) + "\n"
        f'FROM "{item}" i\n'
        + "\n".join(joins) + "\n"
        "WHERE " + "\n  AND ".join(where) + "\n"
        "GROUP BY " + ", ".join(group) + "\n"
        f'ORDER BY "{amount_name}" DESC NULLS LAST\n'
        "LIMIT 200"
    )
