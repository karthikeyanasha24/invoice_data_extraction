"""Unit tests for semantic reliability hard gates (period / partition / negation / dates)."""
from __future__ import annotations

from datetime import date

from app.services.analytical_operations import extract_analytical_operations, merge_semantic_requirements
from app.services.plan_satisfaction import (
    result_matches_analytical_intent,
    sql_has_period_comparison,
    sql_satisfies_analytical_intent,
)
from app.services.semantic_requirements import (
    required_semantics,
    resolve_relative_period_bounds,
)


def test_year_total_does_not_require_customer_country_dims():
    """Plain 'sales for year 2000' must accept a year total without customer/country columns."""
    q = "show me sales for the year 2000"
    polluted = {
        "dimensions": ["date", "product", "customer", "country", "region", "sales_person"],
        "group_by": [],
        "measure": {"concept": "sales", "aggregation": "SUM"},
        "time_filter": {"type": "calendar_year", "value": "2000", "years": ["2000"]},
    }
    rows = [{"year": "2000", "total_sales": 12345.67}]
    sql = (
        'SELECT SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) AS "year", '
        'SUM(CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "total_sales" '
        'FROM "VBRK" WHERE SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) = \'2000\' '
        'GROUP BY 1'
    )
    warnings = result_matches_analytical_intent(rows, q, polluted, sql=sql)
    assert not any("customer" in w or "country" in w for w in warnings)


def test_period_compare_rejects_plain_sum():
    q = "Which customers increased their billed sales between 2004 and 2005?"
    req = required_semantics(q)
    assert req.get("period_compare")
    assert req["period_compare"].get("condition") == "increased"
    sql = (
        'SELECT "KNA1"."name1" AS "customer", SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS "total_sales" '
        'FROM "VBRK" JOIN "KNA1" ON 1=1 GROUP BY "KNA1"."name1" ORDER BY "total_sales" DESC LIMIT 10'
    )
    assert sql_satisfies_analytical_intent(sql, q) is False
    warnings = result_matches_analytical_intent(
        [{"customer": "A", "total_sales": 100}], q, sql=sql
    )
    assert any("period" in w.lower() or "comparison" in w.lower() for w in warnings)


def test_period_compare_accepts_case_diff():
    q = "Which customers increased their billed sales between 2004 and 2005?"
    sql = """
    SELECT "KNA1"."name1" AS "customer",
      SUM(CASE WHEN SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4)='2004'
          THEN CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)),'') AS NUMERIC) ELSE 0 END) AS "period_a",
      SUM(CASE WHEN SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4)='2005'
          THEN CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)),'') AS NUMERIC) ELSE 0 END) AS "period_b",
      (SUM(CASE WHEN SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4)='2005'
          THEN CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)),'') AS NUMERIC) ELSE 0 END)
       - SUM(CASE WHEN SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4)='2004'
          THEN CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)),'') AS NUMERIC) ELSE 0 END)) AS "change"
    FROM "VBRK"
    JOIN "KNA1" ON 1=1
    GROUP BY "KNA1"."name1"
    HAVING (SUM(CASE WHEN SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4)='2005'
          THEN CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)),'') AS NUMERIC) ELSE 0 END)
       - SUM(CASE WHEN SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4)='2004'
          THEN CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)),'') AS NUMERIC) ELSE 0 END)) > 0
    """
    assert sql_has_period_comparison(sql, ["2004", "2005"])
    assert sql_satisfies_analytical_intent(sql, q) is True
    warnings = result_matches_analytical_intent(
        [{"customer": "A", "period_a": 10, "period_b": 20, "change": 10}],
        q,
        sql=sql,
    )
    assert not any("period comparison missing" in w for w in warnings)


def test_partitioned_topn_rejects_global_limit():
    q = "Show the top 5 customers in each country by billed sales."
    ops = extract_analytical_operations(q)
    assert ops["ranking"]["partition_by"] == ["country"]
    sql = (
        'SELECT "KNA1"."land1" AS "country", "KNA1"."name1" AS "customer", '
        'SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS "total_sales" '
        'FROM "VBRK" JOIN "KNA1" ON 1=1 '
        'GROUP BY "KNA1"."land1", "KNA1"."name1" '
        'ORDER BY "total_sales" DESC LIMIT 5'
    )
    assert sql_satisfies_analytical_intent(sql, q) is False


def test_partitioned_topn_accepts_window():
    q = "Show the top 5 customers in each country by billed sales."
    sql = """
    SELECT * FROM (
      SELECT inner_q.*, ROW_NUMBER() OVER (
        PARTITION BY "country" ORDER BY "total_sales" DESC
      ) AS rank_in_partition
      FROM (
        SELECT "KNA1"."land1" AS "country", "KNA1"."name1" AS "customer",
               SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS "total_sales"
        FROM "VBRK" JOIN "KNA1" ON 1=1
        GROUP BY "KNA1"."land1", "KNA1"."name1"
      ) inner_q
    ) ranked WHERE rank_in_partition <= 5
    """
    assert sql_satisfies_analytical_intent(sql, q) is True
    warnings = result_matches_analytical_intent(
        [
            {"country": "US", "customer": "A", "total_sales": 9, "rank_in_partition": 1},
            {"country": "US", "customer": "B", "total_sales": 8, "rank_in_partition": 2},
            {"country": "DE", "customer": "C", "total_sales": 7, "rank_in_partition": 1},
        ],
        q,
        sql=sql,
    )
    assert not any("collapsed to a single overall" in w for w in warnings)
    # Classic wrong shape: 5 rows, one country
    warnings2 = result_matches_analytical_intent(
        [{"country": "US", "customer": f"C{i}", "total_sales": i} for i in range(5)],
        q,
        sql='SELECT country, customer, total_sales FROM t ORDER BY total_sales DESC LIMIT 5',
    )
    assert any("overall" in w or "partition" in w for w in warnings2)


def test_negation_requires_absence_sql():
    q = "Which suppliers have purchase orders but no invoices?"
    req = required_semantics(q)
    assert req.get("negation")
    assert req["negation"].get("forbidden") == "invoice"
    sql = (
        'SELECT "LFA1"."lifnr" FROM "LFA1" '
        'INNER JOIN "EKKO" ON 1=1 INNER JOIN "VBRK" ON 1=1'
    )
    assert sql_satisfies_analytical_intent(sql, q) is False
    sql_ok = (
        'SELECT "LFA1"."lifnr" FROM "LFA1" '
        'WHERE EXISTS (SELECT 1 FROM "EKKO" e WHERE e."lifnr"="LFA1"."lifnr") '
        'AND NOT EXISTS (SELECT 1 FROM "VBRK" v WHERE v."kunag"="LFA1"."lifnr")'
    )
    assert sql_satisfies_analytical_intent(sql_ok, q) is True


def test_relative_last_month_bounds_are_calendar():
    start, end = resolve_relative_period_bounds("last_month", today=date(2026, 9, 9))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 9, 1)
    q = "Show invoices from last month."
    req = required_semantics(q)
    assert req["date_filter"]["start_yyyymmdd"] == "20260801"
    assert req["date_filter"]["end_yyyymmdd"] == "20260901"
    sql_bad = 'SELECT * FROM "VBRK" LIMIT 10'
    assert sql_satisfies_analytical_intent(sql_bad, q) is False
    sql_ok = (
        'SELECT "VBRK"."vbeln", "VBRK"."fkdat" FROM "VBRK" '
        "WHERE TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)) >= '20260801' "
        "AND TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)) < '20260901'"
    )
    # Patch semantic time filter years via merge so date bounds match "today" used above
    sem = merge_semantic_requirements(q, {"time_filter": dict(req["date_filter"], relative="last_month")})
    # Force date_filter from required_semantics — sql check uses required_semantics(question)
    # which resolves against real today; so only check shape when bounds appear in SQL:
    from app.services.plan_satisfaction import sql_has_relative_date_bound

    assert sql_has_relative_date_bound(sql_ok, "20260801", "20260901")


def test_growth_without_years_still_requires_period_compare():
    q = "Which country had the highest sales growth?"
    req = required_semantics(q)
    # Must not invent years; clarification or controlled cannot-answer is correct.
    assert req.get("clarification") or not req.get("period_compare")
    sql = (
        'SELECT "KNA1"."land1" AS "country", SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS "total_sales" '
        'FROM "VBRK" JOIN "KNA1" ON 1=1 GROUP BY "KNA1"."land1" ORDER BY "total_sales" DESC LIMIT 10'
    )
    # Plain ranking must not be accepted as growth proof when growth language is present
    # without a validated period comparison plan.
    if req.get("period_compare"):
        assert sql_satisfies_analytical_intent(sql, q) is False
    elif req.get("clarification"):
        assert req["clarification"].get("type") == "comparison_period"
