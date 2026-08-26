"""R4-1: month / quarter trends — planner, SQL grain, follow-ups, date safety."""
from __future__ import annotations

from app.services.analytical_deep_dive import (
    build_analytical_plan,
    compile_queries,
    is_deep_analysis_candidate,
)
from app.services.analytical_followup_resolver import resolve_analytical_followup
from app.services.business_intelligence_inventory import compose_intent
from app.services.fkdat_time import (
    fkdat_valid_predicate,
    year_month_sql,
    year_quarter_sql,
    year_sql,
)
from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout


PRIOR = {
    "deep_analysis": True,
    "intent": "product_profitability",
    "selected_products": ["MAT-A", "MAT-B"],
    "selected_customers": ["C-1"],
    "selected_regions": ["US"],
    "metrics": ["revenue", "cogs", "gross_profit", "gross_margin_pct"],
    "dimensions": ["product", "currency"],
    "base_question": "highest profit products",
}

MONTHLY_PRIOR = {
    **PRIOR,
    "intent": "monthly_trend",
    "dimensions": ["month", "currency"],
    "comparisons": ["mom"],
}


def _assert_billing_grain(sql: str) -> None:
    s = sql.lower()
    assert "vbrp" in s and "vbrk" in s
    assert not sql_has_unsafe_monetary_fanout(sql)
    for banned in ("ekpo", "vbfa", "konv", "bseg", "mbew", "mard"):
        assert banned not in s, f"unexpected join {banned}"


def test_fkdat_helpers_are_substring_based():
    assert "SUBSTRING" in year_sql("vk").upper()
    assert "CAST" in year_month_sql("vk").upper() or "SUBSTRING" in year_month_sql("vk").upper()
    assert "-Q" in year_quarter_sql("vk")
    assert "IS NOT NULL" in fkdat_valid_predicate("vk")
    # Never CAST FKDAT AS DATE for extraction
    assert "AS DATE" not in year_month_sql("vk").upper()
    assert "AS DATE" not in year_quarter_sql("vk").upper()


def test_compose_intent_month_quarter():
    assert compose_intent(["month"]) == "monthly_trend"
    assert compose_intent(["quarter"]) == "quarterly_trend"


def test_deep_candidate_for_time_grain():
    assert is_deep_analysis_candidate("Show monthly sales.")
    assert is_deep_analysis_candidate("Show quarterly revenue.")
    assert is_deep_analysis_candidate("Compare this month with last month.")


def test_monthly_revenue_plan_and_sql():
    plan = build_analytical_plan("Show monthly sales.")
    assert plan.intent == "monthly_trend"
    assert "month" in plan.dimensions
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    _assert_billing_grain(sql)
    assert "year_month" in sql.lower()
    assert "AS DATE" not in sql.upper()
    assert "SUBSTRING" in sql.upper()
    assert "netwr" in sql.lower()
    assert "ORDER BY year_month" in sql or "order by year_month" in sql.lower()


def test_quarterly_revenue_plan_and_sql():
    plan = build_analytical_plan("Show quarterly sales.")
    assert plan.intent == "quarterly_trend"
    assert "quarter" in plan.dimensions
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    _assert_billing_grain(sql)
    assert "year_quarter" in sql.lower()
    assert "-Q" in sql
    assert "AS DATE" not in sql.upper()


def test_monthly_cogs_gp_margin_qty_invoice_asp_in_sql():
    plan = build_analytical_plan("Show monthly revenue.")
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"].lower()
    for col in (
        "revenue",
        "cogs",
        "gross_profit",
        "gross_margin_pct",
        "quantity",
        "invoice_count",
        "avg_selling_price",
        "wavwr",
        "fkimg",
    ):
        assert col in sql


def test_quarterly_cogs_gp_margin():
    plan = build_analytical_plan("Show quarterly COGS.")
    assert plan.intent == "quarterly_trend"
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"].lower()
    assert "cogs" in sql and "wavwr" in sql


def test_month_comparison_and_quarter_comparison():
    plan_m = build_analytical_plan("Compare this month with last month.")
    assert plan_m.intent == "monthly_trend"
    assert "mom" in (plan_m.comparisons or [])
    plan_q = build_analytical_plan("Compare this quarter with last quarter.")
    assert plan_q.intent == "quarterly_trend"
    assert "qoq" in (plan_q.comparisons or [])


def test_yoy_monthly_and_quarterly_compare():
    plan = build_analytical_plan("Compare monthly sales for 2004 and 2005.")
    assert plan.intent == "monthly_trend"
    assert 2004 in plan.years and 2005 in plan.years
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    assert "'2004'" in sql and "'2005'" in sql
    plan_q = build_analytical_plan("Compare quarterly performance for 2004 and 2005.")
    assert plan_q.intent == "quarterly_trend"
    assert 2004 in plan_q.years


def test_which_month_highest_orders_by_metric():
    plan = build_analytical_plan("Which month had the highest revenue?")
    assert plan.intent == "monthly_trend"
    queries, _ = compile_queries(plan)
    assert "ORDER BY revenue" in queries[0]["sql"] or "order by revenue" in queries[0]["sql"].lower()


def test_which_quarter_highest_gp():
    plan = build_analytical_plan("Which quarter had the highest gross profit?")
    assert plan.intent == "quarterly_trend"
    queries, _ = compile_queries(plan)
    assert "gross_profit" in queries[0]["sql"].lower()


def test_product_filtered_monthly_trend():
    plan = build_analytical_plan("Show the monthly trend for these products.", PRIOR)
    assert plan.intent == "monthly_trend"
    assert plan.selected_products == ["MAT-A", "MAT-B"]
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    assert "MAT-A" in sql and "MAT-B" in sql


def test_customer_filtered_monthly_trend():
    plan = build_analytical_plan(
        "Show quarterly performance for these customers.",
        {**PRIOR, "intent": "customers_of_selection"},
    )
    assert plan.intent == "quarterly_trend"
    assert plan.selected_customers == ["C-1"]
    queries, _ = compile_queries(plan)
    assert "C-1" in queries[0]["sql"]


def test_region_filtered_quarterly_trend():
    plan = build_analytical_plan(
        "Show quarterly revenue.",
        {**PRIOR, "intent": "country_breakdown", "selected_regions": ["DE", "US"]},
    )
    assert plan.intent == "quarterly_trend"
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    assert "DE" in sql and "US" in sql


def test_empty_period_years_in_filter():
    plan = build_analytical_plan("Show monthly revenue for 2099.")
    assert plan.intent == "monthly_trend"
    assert 2099 in plan.years
    queries, _ = compile_queries(plan)
    assert "'2099'" in queries[0]["sql"]
    assert fkdat_valid_predicate("vk").split()[0]  # helper present
    assert "SUBSTRING" in queries[0]["sql"].upper()


def test_malformed_date_guard_in_sql():
    plan = build_analytical_plan("Show monthly margins.")
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    # Valid FKDAT predicate rejects empty / short / non-numeric fragments
    assert "IS NOT NULL" in sql.upper()
    assert "~" in sql or "SUBSTRING" in sql.upper()


def test_followup_context_monthly_chain():
    res = resolve_analytical_followup("Show COGS.", MONTHLY_PRIOR)
    assert res.resolved
    assert res.intent == "monthly_trend"
    assert res.metrics == ["cogs"] or "cogs" in (res.metrics or [])

    res2 = resolve_analytical_followup("Show margins.", MONTHLY_PRIOR)
    assert res2.intent == "monthly_trend"

    res3 = resolve_analytical_followup("Show quarterly.", MONTHLY_PRIOR)
    assert res3.intent == "quarterly_trend"

    res4 = resolve_analytical_followup("Compare with last year.", MONTHLY_PRIOR)
    assert res4.intent == "monthly_trend"
    assert "yoy" in (res4.comparisons or [])

    res5 = resolve_analytical_followup("Which month was best?", MONTHLY_PRIOR)
    assert res5.intent == "monthly_trend"

    res6 = resolve_analytical_followup("Why?", {**MONTHLY_PRIOR, "intent": "quarterly_trend"})
    assert res6.intent == "quarterly_trend"


def test_data_gap_recovery_after_monthly():
    res = resolve_analytical_followup("Show logistics cost.", MONTHLY_PRIOR)
    assert res.intent == "logistics_cost_gap"
    # Next supported follow-up still resolves against preserved prior
    res2 = resolve_analytical_followup("Show COGS.", MONTHLY_PRIOR)
    assert res2.intent == "monthly_trend"


def test_basic_ga_regression_highest_profit_unchanged():
    plan = build_analytical_plan("Show me the products with the highest profits.")
    assert plan.intent == "product_profitability"
    plan2 = build_analytical_plan("Compare 2004 and 2005.", PRIOR)
    assert plan2.intent == "period_compare_selection"


def test_nl_variations_resolve_semantically():
    variants = [
        ("monthly sales", "monthly_trend"),
        ("sales each month", "monthly_trend"),
        ("revenue by month", "monthly_trend"),
        ("quarterly revenue", "quarterly_trend"),
        ("sales per quarter", "quarterly_trend"),
        ("monthly margins", "monthly_trend"),
        ("which quarter performed best", "quarterly_trend"),
        ("Show monthly profit.", "monthly_trend"),
        ("Show quarterly profit.", "quarterly_trend"),
        ("Show monthly margins.", "monthly_trend"),
        ("Show quarterly margins.", "quarterly_trend"),
    ]
    for q, intent in variants:
        plan = build_analytical_plan(q)
        assert plan.intent == intent, f"{q!r} → {plan.intent}"
