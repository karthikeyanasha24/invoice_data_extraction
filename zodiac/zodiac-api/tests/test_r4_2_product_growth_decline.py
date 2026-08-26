"""R4-2: product growth / decline — planner, SQL grain, absolute vs %, follow-ups."""
from __future__ import annotations

from app.services.analytical_deep_dive import (
    build_analytical_plan,
    compile_queries,
    is_deep_analysis_candidate,
)
from app.services.analytical_followup_resolver import resolve_analytical_followup
from app.services.product_growth import (
    abs_change_sql,
    order_col_for,
    pct_change_sql,
    period_status_sql,
    resolve_change_mode,
    resolve_direction,
    resolve_growth_metric,
    resolve_period_grain,
    wants_product_change,
)
from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout


PRIOR = {
    "deep_analysis": True,
    "intent": "product_growth_decline",
    "selected_products": ["MAT-A", "MAT-B"],
    "selected_customers": ["C-1"],
    "selected_regions": ["US"],
    "metrics": ["revenue", "cogs", "gross_profit", "gross_margin_pct", "quantity", "avg_selling_price"],
    "dimensions": ["product", "year", "currency"],
    "comparisons": ["yoy", "product_change"],
    "growth_metric": "revenue",
    "growth_direction": "growth",
    "change_mode": "absolute",
    "filters": {"growth_metric": "revenue", "growth_direction": "growth", "change_mode": "absolute", "period_grain": "year"},
    "base_question": "Which products grew the most?",
}


def _assert_billing_grain(sql: str) -> None:
    s = sql.lower()
    assert "vbrp" in s and "vbrk" in s
    assert not sql_has_unsafe_monetary_fanout(sql)
    for banned in ("ekpo", "vbfa", "konv", "bseg", "mbew", "mard"):
        assert banned not in s, f"unexpected join {banned}"


def test_growth_helpers_null_safe():
    assert "CASE WHEN" in pct_change_sql("c", "p", "x")
    assert "= 0 THEN NULL" in pct_change_sql("c", "p", "x")
    assert "NEW_NO_PRIOR_BASE" in period_status_sql("c", "p")
    assert "FULL_DECLINE_NO_CURRENT" in period_status_sql("c", "p")
    assert "(c - p) AS x" in abs_change_sql("c", "p", "x").replace(" ", "") or "AS x" in abs_change_sql("c", "p", "x")


def test_absolute_vs_percentage_mode():
    assert resolve_change_mode("which products grew fastest?") == "pct"
    assert resolve_change_mode("which products had the biggest percentage increase?") == "pct"
    assert resolve_change_mode("which products added the most revenue?") == "absolute"
    assert resolve_change_mode("which products increased revenue the most?") == "absolute"
    assert resolve_change_mode("which products grew the most?") == "absolute"


def test_metric_and_direction_resolution():
    assert resolve_growth_metric("highest revenue growth") == "revenue"
    assert resolve_growth_metric("gross profit growth") == "gross_profit"
    assert resolve_growth_metric("biggest asp decline") == "avg_selling_price"
    assert resolve_growth_metric("margin improvement") == "gross_margin_pct"
    assert resolve_growth_metric("volume growth") == "quantity"
    assert resolve_direction("which products declined?") == "decline"
    assert resolve_direction("which products grew?") == "growth"
    assert resolve_direction("margins improved") == "growth"
    col, d = order_col_for("revenue", "absolute", "growth")
    assert col == "revenue_change_abs" and d == "DESC"
    col2, d2 = order_col_for("revenue", "pct", "decline")
    assert col2 == "revenue_change_pct" and d2 == "ASC"


def test_r3_margin_decline_not_hijacked():
    plan = build_analytical_plan("Which products had the biggest margin decline?")
    assert plan.intent == "margin_decline_drivers"
    assert wants_product_change("Which month had the biggest margin decline?") is False


def test_r4_1_month_margin_not_hijacked():
    plan = build_analytical_plan("Which month had the biggest margin decline?")
    assert plan.intent == "monthly_trend"


def test_basic_growth_and_decline_plans():
    assert is_deep_analysis_candidate("Which products grew the most?")
    g = build_analytical_plan("Which products grew the most?")
    assert g.intent == "product_growth_decline"
    assert g.filters.get("growth_direction") == "growth"
    assert g.filters.get("change_mode") == "absolute"
    d = build_analytical_plan("Which products declined the most?")
    assert d.intent == "product_growth_decline"
    assert d.filters.get("growth_direction") == "decline"


def test_metric_variants():
    cases = [
        ("Which products had the highest revenue growth?", "revenue"),
        ("Which products had the highest gross profit growth?", "gross_profit"),
        ("Which products had the biggest COGS growth?", "cogs"),
        ("Which products grew fastest by volume?", "quantity"),
        ("Which products had the biggest ASP increase?", "avg_selling_price"),
        ("Show products whose margins improved.", "gross_margin_pct"),
        ("Which products had the biggest margin decline?", "margin_decline_drivers"),  # R3
    ]
    for q, expected in cases:
        plan = build_analytical_plan(q)
        if expected == "margin_decline_drivers":
            assert plan.intent == "margin_decline_drivers"
        else:
            assert plan.intent == "product_growth_decline", q
            assert plan.filters.get("growth_metric") == expected, q


def test_fastest_uses_pct_ranking():
    plan = build_analytical_plan("Which products grew the fastest?")
    assert plan.intent == "product_growth_decline"
    assert plan.filters.get("change_mode") == "pct"
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    _assert_billing_grain(sql)
    assert "revenue_change_pct" in sql
    assert "ORDER BY revenue_change_pct DESC" in sql or "order by revenue_change_pct desc" in sql.lower()


def test_absolute_revenue_increase_sql():
    plan = build_analytical_plan("Which products increased their revenue the most?")
    assert plan.filters.get("change_mode") == "absolute"
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    _assert_billing_grain(sql)
    assert "revenue_change_abs" in sql
    assert "FULL OUTER JOIN" in sql.upper()
    assert "NEW_NO_PRIOR_BASE" in sql
    assert "AS DATE" not in sql.upper()


def test_yoy_2004_2005():
    plan = build_analytical_plan("Which products grew the most from 2004 to 2005?")
    assert plan.intent == "product_growth_decline"
    assert 2004 in plan.years and 2005 in plan.years
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    assert "'2004'" in sql and "'2005'" in sql
    assert "previous_year" in sql.lower()


def test_mom_and_qoq_product_growth():
    assert resolve_period_grain("which products grew month over month?") == "month"
    plan_m = build_analytical_plan("Which products grew month over month?")
    assert plan_m.intent == "product_growth_decline"
    assert plan_m.filters.get("period_grain") == "month"
    assert "mom" in (plan_m.comparisons or [])
    queries, _ = compile_queries(plan_m)
    sql_m = queries[0]["sql"]
    _assert_billing_grain(sql_m)
    assert "LAG(" in sql_m.upper()
    assert "previous_period" in sql_m.lower()

    plan_q = build_analytical_plan("Which products declined quarter over quarter?")
    assert plan_q.intent == "product_growth_decline"
    assert plan_q.filters.get("period_grain") == "quarter"
    queries_q, _ = compile_queries(plan_q)
    assert "LAG(" in queries_q[0]["sql"].upper()


def test_margin_improvement_and_decline():
    improv = build_analytical_plan("Which products improved their margins?")
    assert improv.intent == "product_growth_decline"
    assert improv.filters.get("growth_metric") == "gross_margin_pct"
    assert improv.filters.get("growth_direction") == "growth"
    dec = build_analytical_plan("Show products whose margins declined.")
    assert dec.intent == "product_growth_decline"
    assert dec.filters.get("growth_direction") == "decline"
    queries, _ = compile_queries(improv)
    assert "margin_change_pp" in queries[0]["sql"]


def test_followups_preserve_context():
    why = resolve_analytical_followup("Why?", PRIOR)
    assert why.resolved and why.intent == "product_growth_decline"
    cust = resolve_analytical_followup("Show their customers.", PRIOR)
    assert cust.resolved and cust.intent == "customers_of_selection"
    asp = resolve_analytical_followup("Show their ASP.", PRIOR)
    assert asp.resolved
    assert asp.intent == "product_growth_decline" or asp.metrics
    cogs = resolve_analytical_followup("Show their COGS.", PRIOR)
    assert cogs.resolved and cogs.intent == "product_growth_decline"
    regions = resolve_analytical_followup("Show their regions.", PRIOR)
    assert regions.resolved and regions.intent == "country_breakdown"


def test_decline_chain_why():
    prior = {**PRIOR, "growth_direction": "decline", "filters": {**PRIOR["filters"], "growth_direction": "decline"}}
    plan = build_analytical_plan("Why did those products decline?", prior)
    assert plan.intent == "product_growth_decline"


def test_data_gap_metric_detected_on_followup():
    from app.services.analytical_followup_resolver import resolve_analytical_followup

    gap = resolve_analytical_followup("Show their logistics cost.", PRIOR)
    assert gap.resolved
    assert gap.data_gap_metric == "logistics_cost"


def test_empty_period_years_on_plan():
    plan = build_analytical_plan("Which products grew from 2004 to 2099?")
    assert plan.intent == "product_growth_decline"
    assert 2099 in plan.years
    queries, _ = compile_queries(plan)
    assert "'2099'" in queries[0]["sql"]


def test_ga_basic_not_hijacked():
    # These must remain non-growth deep intents / basic candidates
    assert build_analytical_plan("Meaning of life").intent in {"generic", "unsupported_deep"}
    top = build_analytical_plan("Top 5")
    assert top.intent != "product_growth_decline"


def test_customer_driver_query_present():
    plan = build_analytical_plan("Which products declined the most?")
    queries, _ = compile_queries(plan)
    ids = [q["id"] for q in queries]
    assert "product_growth_decline" in ids
    assert "product_change_customer_drivers" in ids
    _assert_billing_grain(queries[0]["sql"])
    _assert_billing_grain(queries[1]["sql"])


def test_paraphrases_route_to_growth():
    for q in (
        "Show the biggest product growers.",
        "Which products fell the most?",
        "Show the biggest losers.",
        "Who grew fastest?",
        "Which products performed better?",
    ):
        assert wants_product_change(q.lower()) or "who grew" in q.lower()
        plan = build_analytical_plan(q)
        assert plan.intent == "product_growth_decline", q
