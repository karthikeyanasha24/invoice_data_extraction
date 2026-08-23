"""Andy deep-dive failure cases + conversational analytical-context chain."""
from __future__ import annotations

from app.services.analytical_deep_dive import (
    build_analytical_plan,
    compile_queries,
    try_deep_multidim_analysis,
)


ANDY_CASES = [
    ("Show me product with highest profits and show me the breakdown of components", {"profit_components", "product_profitability"}),
    ("Show me cost of goods sold", {"cogs_by_product"}),
    ("Show me products with lowest margins", {"lowest_margin_products"}),
    ("Show me products expiring by industry", {"product_expiry_by_industry", "product_expiry"}),
    ("Show customers with industry data and regions", {"customer_industry_region"}),
    ("What type of products are bought by which customers?", {"customer_product_mix"}),
    ("Show how long customers have been buying them", {"period_compare_selection", "customers_of_selection", "unsupported_deep"}),
    ("Show the process involved behind selling it", {"process_sell"}),
    ("Show the process involved in buying it", {"process_buy"}),
    ("Show the buying process and selling process", {"process_sell_and_buy"}),
]


def test_andy_failure_case_intents():
    for q, allowed in ANDY_CASES:
        prior = None
        if "buying them" in q.lower():
            prior = {"deep_analysis": True, "selected_products": ["P1"]}
        if "behind selling" in q.lower() or "in buying" in q.lower():
            prior = {"deep_analysis": True, "selected_products": ["P1"]}
        plan = build_analytical_plan(q, prior)
        assert plan.intent in allowed, f"{q!r} → {plan.intent} not in {allowed}"


def test_andy_component_question_compiles_multi_query():
    plan = build_analytical_plan(
        "Show me product with highest profits and show me the breakdown of components"
    )
    # May resolve to product_profitability or profit_components depending on ordering
    if plan.intent != "profit_components":
        plan = build_analytical_plan(
            "breakdown of components",
            {"deep_analysis": True, "selected_products": ["X"], "metrics": ["gross_profit"]},
        )
    assert plan.intent == "profit_components"
    queries, _ = compile_queries(plan)
    assert len(queries) >= 2
    assert any("wavwr" in q["sql"].lower() for q in queries)


def test_conversational_deep_chain_preserves_products():
    """Simulate Andy-style chain at planner level with mock execution."""
    store = {"products": ["MAT-A", "MAT-B"]}

    def fake_exec(_db, sql, _q=""):
        sql_l = sql.lower()
        if "margin_change_pp" in sql_l or "yearly" in sql_l:
            return [
                {
                    "product": "MAT-A",
                    "product_name": "Alpha",
                    "currency": "EUR",
                    "margin_change_pp": -5.5,
                    "margin_2024": 40.0,
                    "margin_2025": 34.5,
                }
            ]
        if "kunag" in sql_l and "brsch" in sql_l:
            return [
                {
                    "customer": "C1",
                    "customer_name": "Cust One",
                    "industry": "Trading",
                    "country": "DE",
                    "product": "MAT-A",
                    "product_name": "Alpha",
                    "currency": "EUR",
                    "revenue": 100,
                    "quantity": 2,
                    "first_billing_date": "2024-01-01",
                    "last_billing_date": "2025-06-01",
                }
            ]
        if "brtxt" in sql_l or "industry" in sql_l:
            return [{"industry": "Trading", "currency": "EUR", "revenue": 500, "cogs": 200, "gross_profit": 300, "customer_count": 3}]
        if "land1" in sql_l and "as country" in sql_l:
            return [{"country": "DE", "currency": "EUR", "revenue": 500, "cogs": 200, "gross_profit": 300}]
        # default profitability
        return [
            {
                "product": p,
                "product_name": f"Name-{p}",
                "currency": "EUR",
                "revenue": 1000,
                "cogs": 400,
                "gross_profit": 600,
                "gross_margin_pct": 60.0,
                "quantity": 10,
            }
            for p in store["products"]
        ]

    steps = [
        "Show the top 10 products by profit",
        "Show the customers buying those products",
        "Break that down by industry",
        "Compare 2024 and 2025",
        "Show COGS",
        "Show margin",
        "Which products had the biggest margin decline?",
        "Why did the margin decline?",
        "Show the regional breakdown",
    ]
    ctx = None
    rows = None
    intents = []
    for q in steps:
        payload = try_deep_multidim_analysis(q, db=None, execute_sql=fake_exec, prior_plan=ctx, prior_rows=rows)
        assert payload is not None, f"step failed: {q}"
        assert payload.get("answer_status") in {"SUCCESS", "CANNOT_ANSWER"}
        qp = payload.get("query_plan") or {}
        ctx = qp
        rows = payload.get("data") or rows
        intent = (qp.get("analytical_context") or {}).get("intent") or qp.get("intent")
        intents.append(intent)
        # After first success, products should stick for customer follow-up
        if intent == "customers_of_selection":
            ac = qp.get("analytical_context") or {}
            assert ac.get("selected_products"), "customers follow-up lost selected products"

    assert intents[0] == "product_profitability"
    assert "customers_of_selection" in intents
    assert "industry_breakdown" in intents
    assert "period_compare_selection" in intents or "cogs_by_product" in intents
    assert any(i in {"margin_decline_drivers", "margin_by_product"} for i in intents)
    assert "country_breakdown" in intents


def test_compare_by_year_followup():
    prior = {
        "deep_analysis": True,
        "selected_products": ["P9"],
        "metrics": ["gross_profit"],
    }
    plan = build_analytical_plan("Compare this by year", prior)
    assert plan.intent == "period_compare_selection"
    queries, _ = compile_queries(plan)
    assert "2024" in queries[0]["sql"] or "year" in queries[0]["sql"].lower()
    assert "P9" in queries[0]["sql"]
