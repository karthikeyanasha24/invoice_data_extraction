"""Generic measure comparison + calendar-year filter semantics.

Capability-level: no expected SQL strings, no question-specific handlers.
"""
from __future__ import annotations

from app.services.adaptive_structured_sql import detect_filter_list_intent
from app.services.analytical_operations import extract_analytical_operations
from app.services.plan_satisfaction import (
    result_matches_analytical_intent,
    sql_satisfies_analytical_intent,
)
from app.services.semantic_requirements import required_semantics


NEGATIVE_2000_VARIANTS = [
    "show me the negative sales for the year 2000",
    "Show negative sales in 2000",
    "Which sales were negative during 2000?",
    "List invoices with negative sales in 2000",
    "Show negative billed amounts for 2000",
    "Find sales documents with amounts below zero in 2000",
]

COMPARISON_CASES = [
    ("sales below zero", "<", 0, "sales"),
    ("invoice amount below zero", "<", 0, None),
    ("quantity below zero", "<", 0, "quantity"),
    ("sales above zero", ">", 0, "sales"),
    ("sales equal to zero", "=", 0, "sales"),
    ("sales greater than 1000", ">", 1000, "sales"),
    ("sales below 5000", "<", 5000, "sales"),
]

DATE_PRED_CASES = [
    "negative sales in 2000",
    "positive invoices in 2020",
    "zero-value orders last year",
    "sales below 1000 last month",
    "quantity above 500 this quarter",
]


def _cmp(ops):
    return ops.get("comparison") or {}


def test_observed_question_has_sales_negative_and_year():
    q = "show me the negative sales for the year 2000"
    ops = extract_analytical_operations(q)
    req = required_semantics(q)
    assert ops.get("measure_concept") == "sales"
    assert _cmp(ops).get("operator") == "<"
    assert float(_cmp(ops).get("value") or 0) == 0
    assert ops.get("years") == ["2000"]
    df = req.get("date_filter") or {}
    assert df.get("type") == "calendar_year"
    assert str(df.get("value")) == "2000"
    assert req.get("comparison", {}).get("operator") == "<"
    assert str(req.get("measure", {}).get("aggregation") or "").lower() in {"", "none"}
    assert detect_filter_list_intent(q, {})


def test_unseen_negative_sales_2000_variants_share_semantics():
    for q in NEGATIVE_2000_VARIANTS:
        ops = extract_analytical_operations(q)
        req = required_semantics(q)
        assert _cmp(ops).get("operator") == "<", q
        assert _cmp(ops).get("value") == 0, q
        assert "2000" in (ops.get("years") or []), q
        assert str((req.get("date_filter") or {}).get("value")) == "2000", q
        assert detect_filter_list_intent(q, {}), q


def test_generic_comparison_operators():
    for q, op, val, concept in COMPARISON_CASES:
        ops = extract_analytical_operations(q)
        assert _cmp(ops).get("operator") == op, q
        assert float(_cmp(ops).get("value")) == float(val), q
        if concept:
            assert ops.get("measure_concept") == concept, q
        assert detect_filter_list_intent(q, {}), q


def test_date_and_predicate_combinations():
    for q in DATE_PRED_CASES:
        ops = extract_analytical_operations(q)
        req = required_semantics(q)
        assert _cmp(ops).get("operator"), q
        assert req.get("date_filter") or ops.get("relative_period") or ops.get("years"), q


def test_filter_list_sql_satisfies_plan_without_sum():
    q = "show me the negative sales for the year 2000"
    sql = (
        'SELECT "VBRK"."vbeln", CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC) AS "net_value" '
        'FROM "VBRK" WHERE CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC) < 0 '
        'AND SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) = \'2000\''
    )
    assert sql_satisfies_analytical_intent(sql, q) is True
    assert result_matches_analytical_intent([], q, sql=sql) == []


def test_count_by_year_sql_does_not_satisfy_negative_sales():
    q = "show me the negative sales for the year 2000"
    sql = (
        'SELECT SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) AS "year", COUNT(*) AS "cnt" '
        'FROM "VBRK" GROUP BY 1'
    )
    assert sql_satisfies_analytical_intent(sql, q) is False


def test_empty_satisfying_sql_is_not_result_validation_failure():
    q = "Show negative sales in 2099"
    sql = (
        'SELECT "VBRK"."vbeln" FROM "VBRK" '
        'WHERE CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC) < 0 '
        "AND SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4) = '2099'"
    )
    assert sql_satisfies_analytical_intent(sql, q)
    assert result_matches_analytical_intent([], q, sql=sql) == []


def test_ranking_questions_are_not_row_filters():
    assert not detect_filter_list_intent("top 5 customers by billed sales", {})
    ops = extract_analytical_operations("Which country generated the most billed sales?")
    assert ops.get("ranking")
    assert not ops.get("comparison")


def test_relative_period_plus_comparison_stays_on_plan():
    q = "sales below 1000 last month"
    req = required_semantics(q)
    assert req.get("comparison", {}).get("operator") == "<"
    assert float(req["comparison"]["value"]) == 1000
    df = req.get("date_filter") or {}
    assert df.get("type") == "relative_period"
    assert df.get("start_yyyymmdd")
    assert df.get("end_yyyymmdd")
    q = "Which customers increased their billed sales between 2004 and 2005?"
    req = required_semantics(q)
    assert req.get("period_compare")
    df = req.get("date_filter")
    assert not df or df.get("type") != "calendar_year"
