"""Schema-gated cross-fact comparisons for the four-stage query pipeline.

Raw facts are deduplicated at their document/material keys and aggregated
independently. Unsupported filters are left to normal query planning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..data_catalog.physical import has_column, has_table, resolve_table_name
from .adaptive_structured_sql import extract_question_years, extract_ranking_limit
from .analytical_deep_dive import wants_supplier_concentration
from .inventory_sales import wants_inventory_vs_sales


@dataclass
class SchemaBackedComparison:
    intent: str
    sql: str
    columns: Dict[str, List[str]]
    explanation: str
    limitation: str


def _supported_scope(question: str) -> bool:
    # These choices need additional joins, predicates, or reference resolution.
    # Never silently turn a constrained request into an all-data comparison.
    return not re.search(
        r"\b(?:those|these|their|same|above|previous|last|latest|recent|current|this|"
        r"between|from|until|since|excluding|exclude|without|only|where|customer|lowest|bottom|least|"
        r"country|region|plant|warehouse|group|category|material\s+\d+)\b|"
        r"\bfor\s+(?!\d{4}\b|all\b|each\b|every\b)|\b(?:by|per|each)\s+(?:year|month|quarter)\b", question, re.I,
    )


def _schema_present(columns: Dict[str, List[str]]) -> bool:
    return all(has_table(table) and all(has_column(table, col) for col in cols)
               for table, cols in columns.items())


def _date_filter(question: str, alias: str, column: str) -> str:
    years = extract_question_years(question)
    if not years:
        return ''
    return ' AND (' + ' OR '.join(
        f"TRIM(CAST({alias}.\"{column}\" AS TEXT)) LIKE '{year}%'" for year in years
    ) + ')'


def _currency_filter(question: str, alias: str, column: str) -> str:
    match = re.search(r'\b(?:in|currency)\s+([A-Z]{3})\b', question)
    return f" AND TRIM(CAST({alias}.\"{column}\" AS TEXT)) = '{match[1]}'" if match else ''


def build_schema_backed_comparison(question: str) -> Optional[SchemaBackedComparison]:
    if not _supported_scope(question):
        return None
    q = question.lower()
    if wants_supplier_concentration(q):
        if re.search(r'\b(?:sales|revenue|inventory|risk|single[ -]?source|profit|paid|lowest|bottom|least)\b', q):
            return None
        return _supplier_share(question)
    if wants_inventory_vs_sales(q) and not re.search(r'\b(?:value|turnover|aging|risk|high|low)\b', q):
        return _inventory_sales(question)
    return None


def _supplier_share(question: str) -> Optional[SchemaBackedComparison]:
    columns = {
        'EKPO': ['mandt', 'ebeln', 'ebelp', 'matnr', 'netwr', 'loekz'],
        'EKKO': ['mandt', 'ebeln', 'lifnr', 'waers', 'bedat', 'loekz'],
        'LFA1': ['mandt', 'lifnr', 'name1'],
    }
    if not _schema_present(columns):
        return None
    limit = extract_ranking_limit(question)
    sql = f"""
WITH items AS (
  SELECT DISTINCT p.mandt, p.ebeln, p.ebelp, p.matnr, p.netwr, p.loekz FROM "EKPO" p
), headers AS (
  SELECT DISTINCT h.mandt, h.ebeln, h.lifnr, h.waers, h.bedat, h.loekz FROM "EKKO" h
), supplier_names AS (
  SELECT mandt, lifnr, MAX(name1) AS supplier_name FROM "LFA1" GROUP BY mandt, lifnr
), supplier_totals AS (
  SELECT h.mandt AS client, TRIM(CAST(h.lifnr AS TEXT)) AS supplier,
         MAX(n.supplier_name) AS supplier_name, TRIM(CAST(h.waers AS TEXT)) AS currency,
         SUM(CAST(NULLIF(TRIM(CAST(p.netwr AS TEXT)), '') AS NUMERIC)) AS purchase_value,
         COUNT(DISTINCT p.ebeln) AS purchase_order_count,
         COUNT(DISTINCT p.matnr) AS product_count
  FROM items p JOIN headers h ON p.mandt = h.mandt AND p.ebeln = h.ebeln
  LEFT JOIN supplier_names n ON h.mandt = n.mandt AND h.lifnr = n.lifnr
  WHERE NULLIF(TRIM(CAST(h.lifnr AS TEXT)), '') IS NOT NULL
    AND COALESCE(TRIM(CAST(p.loekz AS TEXT)), '') = ''
    AND COALESCE(TRIM(CAST(h.loekz AS TEXT)), '') = ''
    {_date_filter(question, 'h', 'bedat')}{_currency_filter(question, 'h', 'waers')}
  GROUP BY h.mandt, TRIM(CAST(h.lifnr AS TEXT)), TRIM(CAST(h.waers AS TEXT))
), ranked AS (
  SELECT supplier_totals.*,
         ROW_NUMBER() OVER (PARTITION BY client, currency ORDER BY purchase_value DESC NULLS LAST, supplier) AS rank_within_currency,
         ROUND(100.0 * purchase_value / NULLIF(SUM(purchase_value) OVER (PARTITION BY client, currency), 0), 2) AS share_of_po_value_pct
  FROM supplier_totals
)
SELECT * FROM ranked WHERE rank_within_currency <= {limit}
ORDER BY client, currency, rank_within_currency
""".strip()
    return SchemaBackedComparison(
        'supplier_concentration', sql, columns,
        'Supplier share is purchase-order item value divided by the complete eligible purchase-order value within each client and currency. Deleted purchase orders/items are excluded. The share denominator is computed before selecting the top suppliers.',
        'Currencies are kept separate. Purchase-order value is not supplier profit or paid invoice spend; signed source values are retained. Exact duplicate source rows are collapsed at document/item keys.',
    )


def _inventory_sales(question: str) -> Optional[SchemaBackedComparison]:
    item = resolve_table_name('VBRP') or 'vbrp'
    columns = {
        'MBEW': ['mandt', 'matnr', 'bwkey', 'bwtar', 'lbkum'],
        'MARA': ['mandt', 'matnr', 'meins'],
        item: ['mandt', 'vbeln', 'posnr', 'matnr', 'meins', 'fklmg', 'netwr'],
        'VBRK': ['mandt', 'vbeln', 'waerk', 'fkdat'],
    }
    if not _schema_present(columns):
        return None
    limit = extract_ranking_limit(question)
    sql = f"""
WITH stock_source AS (
  SELECT DISTINCT b.mandt, b.matnr, b.bwkey, b.bwtar, b.lbkum FROM "MBEW" b
), material_units AS (
  SELECT DISTINCT m.mandt, m.matnr, m.meins FROM "MARA" m
), inventory AS (
  SELECT s.mandt AS client, s.matnr AS product, m.meins AS base_unit,
         SUM(CAST(NULLIF(TRIM(CAST(s.lbkum AS TEXT)), '') AS NUMERIC)) AS stock_qty
  FROM stock_source s JOIN material_units m ON s.mandt = m.mandt AND s.matnr = m.matnr
  WHERE COALESCE(TRIM(CAST(s.bwtar AS TEXT)), '') = ''
     OR NOT EXISTS (SELECT 1 FROM stock_source total_stock
                    WHERE total_stock.mandt = s.mandt AND total_stock.matnr = s.matnr
                      AND total_stock.bwkey = s.bwkey AND COALESCE(TRIM(CAST(total_stock.bwtar AS TEXT)), '') = '')
  GROUP BY s.mandt, s.matnr, m.meins
), billing_items AS (
  SELECT DISTINCT p.mandt, p.vbeln, p.posnr, p.matnr, p.meins, p.fklmg, p.netwr FROM "{item}" p
), billing_headers AS (
  SELECT DISTINCT h.mandt, h.vbeln, h.waerk, h.fkdat FROM "VBRK" h
), sales AS (
  SELECT p.mandt AS client, p.matnr AS product, p.meins AS base_unit,
         TRIM(CAST(h.waerk AS TEXT)) AS currency,
         SUM(CAST(NULLIF(TRIM(CAST(p.fklmg AS TEXT)), '') AS NUMERIC)) AS billed_qty,
         SUM(CAST(NULLIF(TRIM(CAST(p.netwr AS TEXT)), '') AS NUMERIC)) AS total_sales
  FROM billing_items p JOIN billing_headers h ON p.mandt = h.mandt AND p.vbeln = h.vbeln
  WHERE NULLIF(TRIM(CAST(p.matnr AS TEXT)), '') IS NOT NULL
    {_date_filter(question, 'h', 'fkdat')}{_currency_filter(question, 'h', 'waerk')}
  GROUP BY p.mandt, p.matnr, p.meins, TRIM(CAST(h.waerk AS TEXT))
)
SELECT COALESCE(i.client, s.client) AS client, COALESCE(i.product, s.product) AS product,
       COALESCE(i.base_unit, s.base_unit) AS base_unit, s.currency,
       i.stock_qty, s.billed_qty, s.total_sales,
       CASE WHEN i.product IS NULL THEN 'No stock snapshot matched'
            WHEN s.product IS NULL THEN 'No billing activity matched'
            ELSE 'Stock and billing activity matched' END AS comparison_status
FROM inventory i FULL OUTER JOIN sales s
  ON i.client = s.client AND i.product = s.product AND i.base_unit = s.base_unit
ORDER BY i.stock_qty DESC NULLS LAST, client, product, currency
LIMIT {limit}
""".strip()
    return SchemaBackedComparison(
        'inventory_sales_comparison', sql, columns,
        'Valuated stock quantity in the extract snapshot (MBEW.LBKUM) is compared with billed quantity in base units (VBRP.FKLMG/MEINS). Stock and billing are aggregated independently before matching on client, material, and unit. The result is a limited preview ordered by stock quantity. Sales amounts are separated by billing currency.',
        'Stock is an undated snapshot in the connected extract; its as-of date is not verified. Billing is historical activity for the requested years or all available years. This is not inventory turnover. Stock quantity repeats where a material has billing in several currencies and must not be added across those rows. Missing stock or billing stays NULL rather than being presented as zero.',
    )
