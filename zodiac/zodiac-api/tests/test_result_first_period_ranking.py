"""Regression coverage for ranking returned periods without changing the requested metric."""
from __future__ import annotations

import pytest

from app.services.result_first_followup import (
    expand_growth_followup_question,
    is_result_scoped_followup,
    try_answer_from_prior_rows,
)


@pytest.mark.parametrize("direction, expected_month, expected_amount", [
    ("highest", "201706", "72,150.75 USD"),
    ("lowest", "201701", "-15 USD"),
])
def test_rank_returned_months_uses_actual_sales_and_preserves_the_source(direction, expected_month, expected_amount):
    rows = [
        {"month": "201705", "total_billed_sales": "20,000", "currency": "USD"},
        {"month": "201701", "total_billed_sales": "-15", "currency": "USD"},
        {"month": "201706", "total_billed_sales": "72,150.75", "currency": "USD"},
    ]
    question = f"Which of those months had the {direction} billed sales, and what was the amount?"
    sql = 'SELECT monthly_bucket AS month, SUM(amount) AS total_billed_sales FROM verified_billing GROUP BY monthly_bucket'

    result = try_answer_from_prior_rows(question, rows, prior_sql=sql)

    assert is_result_scoped_followup(question, has_prior_rows=True)
    assert result and result["answer_status"] == "SUCCESS"
    assert result["data"][0]["month"] == expected_month
    assert expected_amount in result["answer"]
    assert result["source_sql"] == sql
    assert result["sql_generation_method"] == "result_first_rank"
    assert not result.get("needs_plan_expansion")
    assert not expand_growth_followup_question(question, rows, prior_question="Billed sales for 2017")


def test_growth_expansion_cannot_treat_month_labels_as_customer_ids():
    rows = [{"month": "202103", "revenue": 50}, {"month": "202104", "revenue": 80}]

    assert expand_growth_followup_question("Which one grew the fastest?", rows) is None
    result = try_answer_from_prior_rows("Which one grew the fastest?", rows)
    assert result and result["needs_plan_expansion"]
    assert result.get("expanded_question") is None


def test_growth_expansion_is_scoped_to_real_customer_identifiers():
    rows = [{"month": "202103", "customer_id": "0000042", "revenue": 50}]

    result = expand_growth_followup_question(
        "Which of those customers grew the fastest?", rows, prior_question="Customers by sales in 2021"
    )

    assert result and "customers (0000042)" in result
    assert "202103" not in result


def test_returned_month_ranking_keeps_ties_and_rejects_mixed_currency_comparison():
    rows = [
        {"month": "202203", "billed_sales": 100, "currency": "EUR"},
        {"month": "202204", "billed_sales": 100, "currency": "EUR"},
    ]
    question = "Which of these months had the highest billed sales?"
    tied = try_answer_from_prior_rows(question, rows)
    assert tied and tied["rowCount"] == 2
    assert "202203" in tied["answer"] and "202204" in tied["answer"]

    mixed = try_answer_from_prior_rows(question, [rows[0], {**rows[1], "currency": "USD"}])
    assert mixed and mixed["answer_status"] == "CLARIFICATION"
    assert mixed["data"] == []


def test_ranks_months_when_reference_precedes_the_question_clause():
    rows = [
        {"month": "201701", "total_billed_sales": 1224719, "currency": "USD"},
        {"month": "201705", "total_billed_sales": 500, "currency": "USD"},
        {"month": "201706", "total_billed_sales": 560, "currency": "USD"},
        {"month": "201708", "total_billed_sales": 1000, "currency": "USD"},
        {"month": "201709", "total_billed_sales": 799, "currency": "USD"},
        {"month": "201711", "total_billed_sales": 400, "currency": "USD"},
    ]
    question = "Among those monthly results, which month has the largest total billed sales?"

    result = try_answer_from_prior_rows(question, rows, prior_sql="SELECT verified_monthly_sales")

    assert is_result_scoped_followup(question, has_prior_rows=True)
    assert result and result["answer_status"] == "SUCCESS"
    assert result["data"] == [rows[0]]
    assert "201701" in result["answer"] and "1,224,719 USD" in result["answer"]


def test_implicit_month_rank_uses_prior_rows_and_does_not_drop_context():
    from app.services.adaptive_analyst.orchestrator import adapt_user_turn

    rows = [
        {"month": "201701", "total_billed_sales": 1224719, "currency": "USD"},
        {"month": "201705", "total_billed_sales": 500, "currency": "USD"},
        {"month": "201706", "total_billed_sales": 560, "currency": "USD"},
        {"month": "201708", "total_billed_sales": 1000, "currency": "USD"},
        {"month": "201709", "total_billed_sales": 799, "currency": "USD"},
        {"month": "201711", "total_billed_sales": 400, "currency": "USD"},
    ]
    question = "Which month had the highest billed sales?"
    source_sql = 'SELECT month, SUM(amount) AS total_billed_sales FROM billing GROUP BY month'

    adapted = adapt_user_turn(
        question,
        prior_question="Show billed sales by month for country code US in calendar year 2017 in currency USD.",
        prior_plan={"last_user_question": "Show billed sales by month"},
        prior_status="SUCCESS",
    )
    result = try_answer_from_prior_rows(question, rows, prior_sql=source_sql)

    assert adapted.is_fragment and not adapted.drop_prior
    assert is_result_scoped_followup(question, has_prior_rows=True)
    assert result and result["answer_status"] == "SUCCESS"
    assert result["data"] == [rows[0]]
    assert "201701" in result["answer"] and "1,224,719 USD" in result["answer"]
    assert result["source_sql"] == source_sql
    assert result["sql_generation_method"] == "result_first_rank"


def test_incomplete_month_sample_does_not_claim_the_highest_result():
    result = try_answer_from_prior_rows(
        "Which of those months had the highest billed sales?",
        [{"month": "202304", "billed_sales": 100}],
        prior_plan={"result_artifact": {"row_count": 12, "truncated": True}},
    )

    assert result and result["needs_plan_expansion"]
    assert result["missing_concept"] == "complete_prior_result"
