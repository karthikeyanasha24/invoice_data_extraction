"""Tests for deterministic analytical follow-up resolver + API gate."""
from __future__ import annotations

from app.services.adaptive_nl_sql_hardening import is_supported_business_question
from app.services.ai_followup_routing import TurnIntent, classify_turn
from app.services.analytical_deep_dive import build_analytical_plan, try_deep_multidim_analysis
from app.services.analytical_followup_resolver import (
    resolve_analytical_followup,
    KIND_METRIC_CHANGE,
    KIND_DIMENSION_EXPANSION,
    KIND_DATA_GAP_REQUEST,
    KIND_HISTORY_EXPANSION,
    KIND_CAUSE_ANALYSIS,
)

PRIOR = {
    "deep_analysis": True,
    "intent": "product_profitability",
    "selected_products": ["MAT-A", "MAT-B"],
    "metrics": ["revenue", "cogs", "gross_profit", "gross_margin_pct"],
    "dimensions": ["product", "currency"],
    "base_question": "top profitable products",
}

PRIOR_PLAN = {"analytical_context": PRIOR, "deep_analysis": True}


SHORT_FOLLOWUPS = [
    ("Show COGS.", "cogs_by_product", KIND_METRIC_CHANGE),
    ("Show cost.", "cogs_by_product", KIND_METRIC_CHANGE),
    ("Show the margins.", "margin_by_product", KIND_METRIC_CHANGE),
    ("Show profit.", "product_profitability", KIND_METRIC_CHANGE),
    ("Show the regions.", "country_breakdown", KIND_DIMENSION_EXPANSION),
    ("Show customers.", "customers_of_selection", KIND_DIMENSION_EXPANSION),
    ("Show industries.", "industry_breakdown", KIND_DIMENSION_EXPANSION),
    ("Show their customers.", "customers_of_selection", KIND_DIMENSION_EXPANSION),
    ("Break that down by industry.", "industry_breakdown", KIND_DIMENSION_EXPANSION),
    ("Compare 2004 and 2005.", "period_compare_selection", "COMPARISON"),
    ("How long have they been buying them?", "purchase_history", KIND_HISTORY_EXPANSION),
    ("Why did margins fall?", "margin_decline_drivers", KIND_CAUSE_ANALYSIS),
    ("Show the components.", "profit_components", "DETAIL_BREAKDOWN"),
    ("Show the selling process.", "process_sell", "PROCESS_EXPANSION"),
    ("Show logistics cost.", "logistics_cost_gap", KIND_DATA_GAP_REQUEST),
    ("Show net profit.", "net_profit_gap", KIND_DATA_GAP_REQUEST),
]


def test_short_followup_resolver_matrix():
    for q, expected_intent, expected_kind in SHORT_FOLLOWUPS:
        res = resolve_analytical_followup(q, PRIOR)
        assert res.resolved, f"{q!r} not resolved"
        assert res.intent == expected_intent, f"{q!r} → {res.intent} != {expected_intent}"


def test_build_plan_from_short_followups():
    for q, expected_intent, _ in SHORT_FOLLOWUPS:
        if expected_intent.endswith("_gap"):
            continue
        plan = build_analytical_plan(q, PRIOR)
        assert plan.intent == expected_intent, f"{q!r} → {plan.intent}"
        assert plan.selected_products == PRIOR["selected_products"]


def test_api_gate_allows_deep_followups():
    for q, _, _ in SHORT_FOLLOWUPS:
        allowed, reason = is_supported_business_question(q, previous_plan=PRIOR_PLAN)
        assert allowed, f"{q!r} blocked: {reason}"


def test_classify_turn_allows_deep_followups():
    for q, _, _ in SHORT_FOLLOWUPS:
        turn = classify_turn(
            q,
            previous_question="Show top profitable products",
            previous_sql='SELECT 1',
            previous_plan=PRIOR_PLAN,
            previous_status="SUCCESS",
        )
        assert turn.intent not in {
            TurnIntent.CLARIFICATION_REQUIRED,
            TurnIntent.NON_BUSINESS,
        }, f"{q!r} → {turn.intent} ({turn.reason})"


def test_cost_of_goods_without_sold():
    plan = build_analytical_plan("Show me cost of goods")
    assert plan.intent == "cogs_by_product"
    allowed, _ = is_supported_business_question("Show me cost of goods")
    assert allowed


def test_data_gap_preserves_context_for_next_followup():
    def boom(*_a, **_k):
        raise AssertionError("no SQL for logistics cost")

    gap = try_deep_multidim_analysis(
        "Show logistics cost.",
        db=None,
        execute_sql=boom,
        prior_plan=PRIOR_PLAN,
    )
    assert gap["answer_status"] == "CANNOT_ANSWER"
    ac = (gap.get("query_plan") or {}).get("analytical_context") or {}
    assert ac.get("selected_products") == PRIOR["selected_products"]

    rows = [{"product": "MAT-A", "cogs": 100, "revenue": 200, "currency": "EUR"}]

    def fake(_db, sql, _q=""):
        return rows

    after = try_deep_multidim_analysis(
        "Show COGS.",
        db=None,
        execute_sql=fake,
        prior_plan=gap.get("query_plan"),
    )
    assert after is not None
    assert after["answer_status"] == "SUCCESS"
    assert (after.get("query_plan") or {}).get("analytical_context", {}).get("intent") == "cogs_by_product"


def test_seventeen_turn_chain_planner_level():
    """Andy 17-turn chain at planner + mock execution level."""
    store = {"products": ["MAT-A", "MAT-B"]}

    def fake_exec(_db, sql, _q=""):
        sql_l = sql.lower()
        if "margin_change_pp" in sql_l or "yearly" in sql_l:
            return [{"product": "MAT-A", "margin_change_pp": -5.5, "currency": "EUR"}]
        if "first_purchase" in sql_l or "purchase_duration" in sql_l:
            return [{"customer": "C1", "product": "MAT-A", "purchase_duration_days": 365}]
        if "kunag" in sql_l and "brsch" in sql_l:
            return [{"customer": "C1", "industry": "Trading", "country": "DE", "product": "MAT-A", "revenue": 100}]
        if "brtxt" in sql_l or ("industry" in sql_l and "group by" in sql_l):
            return [{"industry": "Trading", "revenue": 500, "gross_profit": 300, "currency": "EUR"}]
        if "land1" in sql_l:
            return [{"country": "DE", "revenue": 500, "gross_profit": 300, "currency": "EUR"}]
        if "vbfa" in sql_l or "process" in sql_l:
            return [{"process_stage": "billing", "document_count": 3}]
        return [
            {
                "product": p,
                "product_name": f"Name-{p}",
                "currency": "EUR",
                "revenue": 1000,
                "cogs": 400,
                "gross_profit": 600,
                "gross_margin_pct": 60.0,
            }
            for p in store["products"]
        ]

    chain = [
        "Show me the products with the highest profits.",
        "Show their customers.",
        "Break that down by industry.",
        "Show the regions.",
        "Compare 2004 and 2005.",
        "Show COGS.",
        "Show the margins.",
        "Which products had the biggest margin decline?",
        "Why did those margins decline?",
        "Show me the cost components.",
        "How long have they been buying them?",
        "Show me the buying process.",
        "Show me the selling process.",
        "Show me the delivery process.",
        "Show me logistics cost.",
        "Show me net profit.",
        "Now show me COGS again.",
    ]
    ctx = None
    rows = None
    results = []
    for q in chain:
        payload = try_deep_multidim_analysis(
            q, db=None, execute_sql=fake_exec, prior_plan=ctx, prior_rows=rows
        )
        assert payload is not None, f"chain failed: {q}"
        status = payload.get("answer_status")
        assert status in {"SUCCESS", "CANNOT_ANSWER"}, f"{q} → {status}"
        results.append((q, status, (payload.get("query_plan") or {}).get("analytical_context", {}).get("intent")))
        ctx = payload.get("query_plan")
        if status == "SUCCESS":
            rows = payload.get("data") or rows

    assert results[14][1] == "CANNOT_ANSWER"  # logistics cost
    assert results[15][1] == "CANNOT_ANSWER"  # net profit
    assert results[16][1] == "SUCCESS"  # COGS after gaps
    assert results[16][2] == "cogs_by_product"
