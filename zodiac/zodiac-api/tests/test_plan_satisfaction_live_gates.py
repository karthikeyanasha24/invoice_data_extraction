"""Quick regression for live certification gate fixes."""
from app.services.plan_satisfaction import (
    sql_has_month_bucket,
    sql_satisfies_analytical_intent,
)


def test_month_bucket_detects_nested_cast():
    assert sql_has_month_bucket(
        'SUBSTRING(TRIM(CAST("VBAK"."erdat" AS TEXT)), 1, 6)'
    )


def test_count_by_month_accepts_grouped_count():
    sql = (
        'SELECT SUBSTRING(TRIM(CAST("VBAK"."erdat" AS TEXT)), 1, 6) AS "month", '
        'COUNT(*) AS "count" FROM "VBAK" '
        'GROUP BY SUBSTRING(TRIM(CAST("VBAK"."erdat" AS TEXT)), 1, 6)'
    )
    assert sql_satisfies_analytical_intent(sql, "Show sales order count by month") is True


def test_count_by_month_rejects_sum_sales_template():
    sql = (
        'SELECT SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 6) AS "month", '
        "SUM(CAST(NULLIF(TRIM(CAST(\"VBRK\".\"netwr\" AS TEXT)), '') AS NUMERIC)) AS \"total_sales\" "
        'FROM "VBRK" '
        'GROUP BY SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 6)'
    )
    assert sql_satisfies_analytical_intent(sql, "Show sales order count by month") is False
