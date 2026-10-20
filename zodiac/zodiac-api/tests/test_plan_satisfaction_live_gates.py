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


def test_cross_document_comparison_must_read_both_documents():
    from app.services.plan_satisfaction import missing_compared_documents
    question = "compare order net value with invoice net value for billing documents in 2000"
    billing_only = 'SELECT k.vbeln, k.netwr, k.waerk FROM "VBRK" k WHERE k.fkdat LIKE \'2000%\''
    assert missing_compared_documents(billing_only, question) == ["VBAK"]
    assert sql_satisfies_analytical_intent(billing_only, question) is False
    linked = billing_only.replace('FROM "VBRK" k', 'FROM "VBRK" k JOIN vbrp p ON p.vbeln = k.vbeln JOIN "VBAK" o ON o.vbeln = p.aubel')
    assert missing_compared_documents(linked, question) == []
    assert missing_compared_documents(billing_only, "billing documents in 2000 vs 2001 in descending order") == []
    assert missing_compared_documents(billing_only, "compare purchase order value with supplier invoices") == ["EKKO", "RBKP"]
