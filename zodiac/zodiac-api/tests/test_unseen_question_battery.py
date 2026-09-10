"""Unseen-question battery: catalog/compilers must not be required.

These questions are intentionally not catalog IDs. Success here means
semantic operations + SQL/result gates generalize — not that a handler exists.
"""
from __future__ import annotations

from app.services.analytical_operations import extract_analytical_operations, merge_semantic_requirements
from app.services.plan_satisfaction import sql_satisfies_analytical_intent, result_matches_analytical_intent

UNSEEN = [
    "Which country generated the most billed quantity?",
    "Show invoice value by month.",
    "Show revenue by country and industry.",
    "Top 10 materials by quantity.",
    "Top 3 customers in each country by revenue.",
    "Which suppliers have purchase orders but no invoices?",
    "Which customers increased sales between 2004 and 2005?",
    "Which products had the largest decline?",
    "Show invoices from last month.",
    "Which clients generated the highest billed value?",
]


def test_unseen_questions_have_structured_operations():
    for q in UNSEEN:
        ops = extract_analytical_operations(q)
        merged = merge_semantic_requirements(q, {})
        assert isinstance(ops, dict)
        assert merged.get("measure") is not None or ops.get("negation") or ops.get("relative_period")


def test_unseen_grouping_rejects_grand_total():
    q = "Show invoice value by month."
    sql = 'SELECT SUM(CAST(NULLIF(TRIM(CAST("vbrp"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS total FROM "vbrp"'
    assert sql_satisfies_analytical_intent(sql, q) is False


def test_unseen_quantity_ranking_rejects_master_list():
    q = "Top 10 materials by quantity."
    sql = 'SELECT "MARA"."matnr" FROM "MARA" LIMIT 10'
    assert sql_satisfies_analytical_intent(sql, q) is False


def test_unseen_partition_requires_window():
    q = "Top 3 customers in each country by revenue."
    sql = (
        'SELECT TRIM("KNA1"."name1") AS customer, SUM(CAST(NULLIF(TRIM(CAST("vbrp"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS total '
        'FROM "vbrp" JOIN "VBRK" ON 1=1 JOIN "KNA1" ON 1=1 GROUP BY 1 ORDER BY total DESC LIMIT 3'
    )
    assert sql_satisfies_analytical_intent(sql, q) is False


def test_unseen_master_result_is_not_success():
    q = "Which clients generated the highest billed value?"
    rows = [{"kunnr": "1", "name1": "Acme"}]
    warnings = result_matches_analytical_intent(rows, q, sql='SELECT "kunnr", "name1" FROM "KNA1" LIMIT 10')
    assert warnings
