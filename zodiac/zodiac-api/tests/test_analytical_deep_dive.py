"""Unit tests for multi-dimensional deep analysis planner (no live DB required)."""
from __future__ import annotations

from app.services.analytical_deep_dive import (
    build_analytical_plan,
    compile_queries,
    is_deep_analysis_candidate,
    try_deep_multidim_analysis,
)
from app.services.business_semantic_layer import METRICS, resolve_metric


def test_metric_registry_distinguishes_profit_from_revenue():
    rev = resolve_metric("revenue")
    profit = resolve_metric("highest profit")
    net = resolve_metric("net profit")
    assert rev is not None and rev.name == "revenue"
    assert profit is not None and profit.name == "gross_profit"
    assert net is not None and net.status == "unavailable"
    assert "profit" in profit.substitutes_forbidden or "net profit" in profit.substitutes_forbidden


def test_cogs_uses_wavwr_not_invented_formula():
    cogs = METRICS["cogs"]
    assert cogs.status == "supported"
    assert "wavwr" in cogs.formula_sql.lower()
    assert "ACDOCA" in cogs.caveats or "acdoca" in cogs.caveats.lower()


def test_plan_highest_profit_products():
    plan = build_analytical_plan("Show me products with highest profits")
    assert plan.intent == "product_profitability"
    assert "gross_profit" in plan.metrics
    assert "cogs" in plan.metrics
    assert plan.ranking and plan.ranking["direction"] == "desc"
    queries, gaps = compile_queries(plan)
    assert queries
    assert "wavwr" in queries[0]["sql"].lower()
    assert "netwr" in queries[0]["sql"].lower()


def test_plan_lowest_margins():
    plan = build_analytical_plan("Show me products with lowest margins")
    assert plan.intent == "lowest_margin_products"
    assert plan.ranking["metric"] == "gross_margin_pct"
    assert plan.ranking["direction"] == "asc"


def test_plan_cogs():
    plan = build_analytical_plan("Show me cost of goods sold")
    assert plan.intent == "cogs_by_product"
    queries, _ = compile_queries(plan)
    assert queries and "cogs" in queries[0]["sql"].lower()


def test_plan_components_multi_query():
    plan = build_analytical_plan(
        "Show me product with highest profits and show me the breakdown of components"
    )
    assert plan.intent in {"profit_components", "product_profitability"}
    # Force components intent
    plan2 = build_analytical_plan("Break down the cost components")
    # without prior may be components or unsupported — with prior deep context:
    prior = {"deep_analysis": True, "selected_products": ["MAT1"], "metrics": ["gross_profit"]}
    plan3 = build_analytical_plan("Break down the components", prior)
    assert plan3.intent == "profit_components"
    queries, _ = compile_queries(plan3)
    assert len(queries) >= 2


def test_followup_customers_preserves_products():
    prior = {
        "deep_analysis": True,
        "selected_products": ["000111", "000222"],
        "metrics": ["gross_profit", "cogs"],
        "base_question": "top profitable products",
    }
    plan = build_analytical_plan("Show their customers", prior)
    assert plan.intent == "customers_of_selection"
    assert plan.selected_products == ["000111", "000222"]
    queries, _ = compile_queries(plan)
    assert "000111" in queries[0]["sql"]
    assert "kna1" in queries[0]["sql"].lower()


def test_industry_and_country_followups():
    prior = {"deep_analysis": True, "selected_products": ["P1"]}
    ind = build_analytical_plan("Break that down by industry", prior)
    assert ind.intent == "industry_breakdown"
    ctry = build_analytical_plan("Show the regional breakdown", prior)
    assert ctry.intent == "country_breakdown"
    q1, _ = compile_queries(ind)
    q2, _ = compile_queries(ctry)
    assert "brsch" in q1[0]["sql"].lower() or "t016t" in q1[0]["sql"].lower()
    assert "land1" in q2[0]["sql"].lower()


def test_process_sell_and_buy():
    plan = build_analytical_plan("Show the buying process and selling process")
    assert plan.intent == "process_sell_and_buy"
    queries, _ = compile_queries(plan)
    ids = {q["id"] for q in queries}
    assert "process_sell_stages" in ids
    assert "process_buy_stages" in ids


def test_net_profit_data_gap_no_sql():
    def boom(*_a, **_k):
        raise AssertionError("should not execute SQL for net profit")

    payload = try_deep_multidim_analysis(
        "Show me true net profit by product",
        db=None,
        execute_sql=boom,
    )
    assert payload is not None
    assert payload["answer_status"] == "CANNOT_ANSWER"
    assert not payload.get("sql")
    assert "operating" in (payload.get("summary") or "").lower() or "net profit" in (
        payload.get("summary") or ""
    ).lower()


def test_basic_sales_not_forced_into_deep_engine():
    assert not is_deep_analysis_candidate("Show me highest sales for the year 2004 with customer and industry")
    plan = build_analytical_plan("Only the Trading industry")
    # Without prior deep context, industry-only follow-up should not claim profitability path
    assert plan.intent == "unsupported_deep"


def test_mock_execute_profitability_payload_shape():
    rows = [
        {
            "product": "A1",
            "product_name": "Widget",
            "currency": "EUR",
            "revenue": 1000,
            "cogs": 400,
            "gross_profit": 600,
            "gross_margin_pct": 60.0,
            "quantity": 10,
        }
    ]

    def fake_exec(_db, sql, _q=""):
        return rows

    payload = try_deep_multidim_analysis(
        "Show products with highest profit",
        db=None,
        execute_sql=fake_exec,
    )
    assert payload is not None
    assert payload["answer_status"] == "SUCCESS"
    assert payload["pipeline"] == "deep_multidim"
    assert payload["query_plan"]["analytical_context"]["deep_analysis"] is True
    assert payload["suggested_followups"]
    assert "Widget" in (payload["summary"] or "")
    assert payload["data"][0]["gross_profit"] == 600
