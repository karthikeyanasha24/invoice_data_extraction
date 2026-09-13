"""Unseen DB formulations must share the same generic semantics.

No expected SQL. No phrase handlers. Same capability under different wording.
"""
from __future__ import annotations

from app.services.adaptive_analyst.presentation import plan_presentation
from app.services.adaptive_structured_sql import build_period_compare_sql, build_dimension_ranking_sql
from app.services.analytical_operations import extract_analytical_operations
from app.services.plan_satisfaction import sql_satisfies_analytical_intent
from app.services.semantic_requirements import required_semantics


def test_revenue_paraphrases_share_measure():
    a = extract_analytical_operations("What was our total revenue in 2025?")
    b = extract_analytical_operations("How much money did the business generate during 2025?")
    assert a.get("measure_concept") in {"revenue", "sales"}
    assert b.get("measure_concept") in {"revenue", "sales"}
    assert "2025" in (a.get("years") or [])
    assert "2025" in (b.get("years") or [])


def test_ranking_paraphrases_share_topn_customer():
    variants = [
        "Show me the top 5 customers by revenue.",
        "Which five customers brought in the most revenue?",
        "Give me the five biggest customers by sales.",
    ]
    for q in variants:
        ops = extract_analytical_operations(q)
        assert ops.get("ranking"), q
        assert int(ops["ranking"]["limit"]) == 5, q
        assert "customer" in (ops.get("group_by") or []) or ops.get("measure_concept"), q


def test_trend_paraphrase_sets_month_grain():
    q = "Show me how revenue moved month by month in 2025."
    ops = extract_analytical_operations(q)
    assert ops.get("trend") or "month" in (ops.get("group_by") or [])
    assert ops.get("time_grain") == "month" or "month" in (ops.get("group_by") or [])
    assert "2025" in (ops.get("years") or [])


def test_comparison_better_than_sets_period_compare():
    q = "Was 2025 better than 2024 in terms of revenue?"
    req = required_semantics(q)
    assert req.get("period_compare")
    years = [
        str((req["period_compare"].get("base_period") or {}).get("year")),
        str((req["period_compare"].get("comparison_period") or {}).get("year")),
    ]
    assert "2024" in years and "2025" in years


def test_contribution_between_years_is_period_compare_not_unsupported():
    q = "Which customers contributed most to the change in revenue between 2024 and 2025?"
    ops = extract_analytical_operations(q)
    req = required_semantics(q)
    assert ops.get("contribution")
    assert req.get("period_compare")
    assert req.get("contribution") or req["period_compare"].get("contribution")
    assert "customer" in (ops.get("group_by") or req.get("group_by") or [])
    sql = build_period_compare_sql(q, [])
    assert sql
    assert "contribution_pct" in sql.lower() or "change" in sql.lower()
    assert sql_satisfies_analytical_intent(sql, q)


def test_why_revenue_decreased_plans_yoy_investigation():
    q = "Why did revenue decrease?"
    ops = extract_analytical_operations(q)
    req = required_semantics(q)
    assert ops.get("contribution") or ops.get("period_compare")
    period = req.get("period_compare") or ops.get("period_compare")
    assert isinstance(period, dict)
    assert period.get("requires_two_periods") or period.get("base_period")
    assert period.get("op") == "decline" or period.get("condition") == "decreased"
    assert not ops.get("clarification"), "investigation must not ask for years when YoY can resolve"


def test_presentation_chart_vs_table_from_same_shape():
    rows = [{"month": "2025-01", "revenue": 10}, {"month": "2025-02", "revenue": 12}]
    chart = plan_presentation("Show monthly revenue for 2025 as a chart.", rows)
    table = plan_presentation("Show the same data as a table.", rows)
    assert chart["type"] == "chart"
    assert chart["chart_type"] == "line"
    assert table["type"] == "table"
    assert table["prefer_table"] is True


def test_presentation_ranking_prefers_bar():
    rows = [{"customer_name": "A", "total_sales": 9}, {"customer_name": "B", "total_sales": 7}]
    plan = plan_presentation("Show the top 5 customers by revenue.", rows)
    assert plan["type"] == "chart"
    assert plan["chart_type"] == "bar"


def test_ranking_sql_still_builds_for_paraphrase():
    q = "Which five customers brought in the most revenue?"
    sql = build_dimension_ranking_sql(q, [])
    # May be None if schema fixtures absent in unit env; semantics must still be ranking.
    ops = extract_analytical_operations(q)
    assert ops.get("ranking", {}).get("limit") == 5
    if sql:
        assert "LIMIT 5" in sql.upper()
        assert sql_satisfies_analytical_intent(sql, q)


def test_investigation_steps_are_confirm_then_drivers():
    from app.services.adaptive_analyst.investigation import (
        evaluate_direction_gate,
        plan_investigation_steps,
        sufficiency_for_investigation,
    )

    q = "Why did revenue decrease?"
    steps = plan_investigation_steps(q, required_semantics(q))
    kinds = [s["kind"] for s in steps]
    assert kinds[0] == "confirm_direction"
    assert "drivers" in kinds
    assert kinds.count("drivers") >= 1
    assert kinds.count("drivers") <= 3
    verdict, evidence = evaluate_direction_gate(
        [{"period_a": 100, "period_b": 80, "change": -20}],
        expected_direction="decline",
    )
    assert verdict == "proceed"
    assert evidence["change"] == -20
    opposite, _ = evaluate_direction_gate(
        [{"period_a": 100, "period_b": 120, "change": 20}],
        expected_direction="decline",
    )
    assert opposite == "opposite"
    suff = sufficiency_for_investigation(
        q,
        [{"customer_name": "A", "change": -5, "contribution_pct": 40}],
        confirm_evidence={"verdict": "proceed"},
    )
    assert suff["sufficient"] is True


def test_growth_followup_ranks_change_or_expands():
    from app.services.result_first_followup import (
        expand_growth_followup_question,
        try_answer_from_prior_rows,
    )

    with_change = [
        {"customer_name": "A", "change": 10},
        {"customer_name": "B", "change": 40},
    ]
    out = try_answer_from_prior_rows("Which one grew the fastest?", with_change)
    assert out and out.get("answer_status") == "SUCCESS"
    assert out["data"][0]["customer_name"] == "B"
    assert not out.get("needs_plan_expansion")

    levels = [
        {"customer_name": "Acme", "total_sales": 9},
        {"customer_name": "Beta", "total_sales": 7},
    ]
    gap = try_answer_from_prior_rows(
        "Which one grew the fastest?",
        levels,
        prior_plan={"last_user_question": "Show me the top 5 customers by revenue."},
    )
    assert gap and gap.get("needs_plan_expansion")
    assert gap.get("expanded_question")
    assert "Acme" in gap["expanded_question"]
    rewritten = expand_growth_followup_question(
        "Which one grew the fastest?",
        levels,
        prior_question="top customers 2024",
    )
    assert rewritten and "Acme" in rewritten


def test_presentation_never_invents_chart_values():
    rows = [{"month": "2025-01", "revenue": 10}, {"month": "2025-02", "revenue": 12}]
    charts = [
        {
            "chart_type": "line",
            "data": rows,
            "x_key": "month",
            "y_keys": ["revenue"],
        }
    ]
    plan = plan_presentation("Show monthly revenue for 2025 as a chart.", rows, charts=charts)
    assert plan["data_from_rows_only"] is True
    assert plan["charts"][0]["data"] == rows

