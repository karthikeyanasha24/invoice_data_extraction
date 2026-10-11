"""Regression checks for coordinated dimensions and normalized agent rankings."""
from decimal import Decimal

import pytest
from sqlglot import parse_one

from app.services.analytical_operations import extract_analytical_operations
from app.services.plan_satisfaction import sql_satisfies_analytical_intent, result_matches_analytical_intent, sql_has_calendar_year
from app.services.sql_structure import has_ranking_bound


@pytest.mark.parametrize("question,dimensions", [
    ("Lowest sales in 2000 by country, customer, and product", {"country", "customer", "material"}),
    ("Highest sales in 2004 with customer and industry", {"customer", "industry"}),
    ("Total revenue by customer and country", {"customer", "country"}),
    ("Billed sales by month, country and currency", {"month", "country", "currency"}),
])
def test_coordinated_dimensions_are_all_required(question, dimensions):
    assert set(extract_analytical_operations(question)["group_by"]) == dimensions


def test_normalized_year_grouping_does_not_reject_requested_entities():
    question = "Show the lowest sales for year 2000 by country, customer, and product"
    sql = '''SELECT SUBSTRING(h.fkdat,1,4) AS year, c.land1 AS country,
                    h.kunag AS customer_id, p.matnr AS product_id, SUM(p.netwr) AS sales_value
             FROM VBRK h JOIN vbrp p ON h.mandt=p.mandt AND h.vbeln=p.vbeln
             LEFT JOIN KNA1 c ON h.mandt=c.mandt AND LPAD(h.kunag,10,'0')=LPAD(c.kunnr,10,'0')
             WHERE h.fkdat BETWEEN '20000101' AND '20001231'
             GROUP BY SUBSTRING(h.fkdat,1,4), c.land1,h.kunag,p.matnr
             ORDER BY sales_value ASC LIMIT 5'''
    normalized = parse_one(sql, read="postgres").sql(dialect="postgres")
    assert "FROM 1 FOR 4" in normalized
    assert sql_satisfies_analytical_intent(normalized, question)


def test_unspecified_ranking_bound_is_not_an_exact_count():
    sql = 'SELECT p.matnr AS product_id, SUM(p.netwr-p.wavwr) AS gross_profit FROM vbrp p GROUP BY p.matnr ORDER BY gross_profit DESC LIMIT 3'
    assert sql_satisfies_analytical_intent(sql, "Show products with the highest profits")
    assert not sql_satisfies_analytical_intent(sql, "Show top 10 products by profits")


def test_qualified_currency_rank_keeps_explicit_top_n_per_currency():
    sql = '''WITH totals AS (SELECT p.matnr AS product_id,p.waerk AS currency,SUM(p.netwr) AS billed_sales
                             FROM vbrp p GROUP BY p.matnr,p.waerk),
                    ranked AS (SELECT t.*,ROW_NUMBER() OVER(PARTITION BY t.currency ORDER BY t.billed_sales DESC) AS ranking
                               FROM totals t)
             SELECT r.product_id,r.currency,r.billed_sales,r.ranking FROM ranked r WHERE r.ranking<=10 ORDER BY r.currency,r.ranking LIMIT 201'''
    assert has_ranking_bound(sql, 10, partition_dimension="currency")
    rows = [{"product_id": str(n), "currency": curr, "billed_sales": Decimal(100-n), "ranking": n}
            for curr in ("USD", "EUR") for n in range(1, 11)]
    assert not result_matches_analytical_intent(rows, "Top 10 products by billed sales, with currency shown separately", sql=sql)


def test_extra_entity_grain_is_still_rejected():
    sql = 'SELECT c.land1 AS country,p.matnr AS product_id,SUM(p.netwr) AS sales FROM vbrp p JOIN KNA1 c ON p.kunnr=c.kunnr GROUP BY c.land1,p.matnr ORDER BY sales DESC LIMIT 10'
    assert not sql_satisfies_analytical_intent(sql, "Top 10 countries by sales")


def test_top_n_currency_counts_are_separate_for_each_sap_client():
    sql = '''WITH totals AS (SELECT p.mandt AS sap_client,p.matnr AS product_id,p.waerk AS currency,SUM(p.netwr) AS billed_sales
                            FROM vbrp p GROUP BY p.mandt,p.matnr,p.waerk),
             ranked AS (SELECT t.*,ROW_NUMBER() OVER(PARTITION BY t.sap_client,t.currency ORDER BY t.billed_sales DESC) AS ranking FROM totals t)
             SELECT r.sap_client,r.product_id,r.currency,r.billed_sales,r.ranking FROM ranked r WHERE r.ranking<=10 ORDER BY r.sap_client,r.currency,r.ranking LIMIT 201'''
    rows = [{"sap_client": client,"product_id": str(n),"currency": "EUR","billed_sales": Decimal(100-n),"ranking": n}
            for client in ("800", "811") for n in range(1,11)]
    assert not result_matches_analytical_intent(rows,"Top 10 products by billed sales, with currency shown separately",sql=sql)


def test_year_over_year_does_not_invent_monthly_grain():
    ops = extract_analytical_operations("Year over year billed sales for 2000 vs 2001")
    assert "month" not in ops["group_by"]
    assert ops["period_compare"]["base_period"]["year"] == "2000"


def test_calendar_year_accepts_normalized_predicate_and_rejects_title_only():
    assert sql_has_calendar_year("SELECT SUM(netwr) FROM VBRK WHERE CAST(SUBSTRING(fkdat FROM 1 FOR 4) AS INT)=2000", "2000")
    assert not sql_has_calendar_year("SELECT 'sales 2000' AS title,SUM(netwr) FROM VBRK", "2000")
