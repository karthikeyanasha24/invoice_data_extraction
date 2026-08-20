"""Turn-intent routing: context is an input, never proof of continuation."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.ai_followup_routing import (
    TurnIntent,
    classify_turn,
    looks_like_followup_utterance,
    looks_like_standalone_analytical,
)
from app.services.ai_query_plan import apply_followup_delta, extract_query_plan
from app.services.adaptive_nl_sql_hardening import is_supported_business_question


GOLDEN_TURNS = (
    "Show me highest sales for the year 2004 with customer and industry",
    "Only the Trading industry",
    "Now show the top 5",
    "Compare with 2003",
    "Remove the Trading filter",
    "Show invoice count instead",
    "Meaning of life",
    "Show sales for 2005",
    "Top 3",
)

GOLDEN_INTENTS = (
    TurnIntent.NEW_ANALYTICAL_QUERY,
    TurnIntent.FOLLOWUP_DELTA,
    TurnIntent.FOLLOWUP_DELTA,
    TurnIntent.FOLLOWUP_DELTA,
    TurnIntent.FOLLOWUP_DELTA,
    TurnIntent.FOLLOWUP_DELTA,
    TurnIntent.NON_BUSINESS,
    TurnIntent.NEW_ANALYTICAL_QUERY,
    TurnIntent.FOLLOWUP_DELTA,
)

_PRIOR_SQL = 'SELECT 1 AS total_sales FROM "VBRK" WHERE 1=1'
_INVOICE_COUNT_SQL = (
    'SELECT COUNT(DISTINCT TRIM(v."vbeln")) AS invoice_count '
    'FROM "VBRK" v WHERE SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)),1,4) IN (\'2003\',\'2004\')'
)
_INVOICE_COUNT_ROWS = [
    {
        "year": "2004",
        "customer_name": "CBD Computer Based Design",
        "industry": "High Technology & Electronics",
        "currency": "EUR",
        "invoice_count": 53,
    }
]
_INVOICE_COUNT_CONTEXT = {
    "previousQuestion": "Show invoice count instead",
    "previousSQL": _INVOICE_COUNT_SQL,
    "previousAnswerStatus": "SUCCESS",
    "previousPlan": {
        "metric": "count",
        "dimensions": ["customer", "industry"],
        "filters": {"years": ["2003", "2004"]},
        "operation": "count",
        "delta_ops": ["change_metric:count"],
    },
    "data": _INVOICE_COUNT_ROWS,
}


def _classify(question: str, prev_q: str = "", prev_sql: str = "", prev_plan=None, status="SUCCESS"):
    return classify_turn(
        question,
        previous_question=prev_q,
        previous_sql=prev_sql,
        previous_plan=prev_plan,
        previous_status=status,
    )


def test_routing_matrix_expected_intents():
    plan_2004 = extract_query_plan(GOLDEN_TURNS[0]).to_dict()
    cases = [
        ("Show me highest sales for the year 2004 with customer and industry", "", "", None, TurnIntent.NEW_ANALYTICAL_QUERY),
        ("Only the Trading industry", GOLDEN_TURNS[0], _PRIOR_SQL, plan_2004, TurnIntent.FOLLOWUP_DELTA),
        ("Now show the top 5", GOLDEN_TURNS[0], _PRIOR_SQL, plan_2004, TurnIntent.FOLLOWUP_DELTA),
        ("Compare with 2003", GOLDEN_TURNS[0], _PRIOR_SQL, plan_2004, TurnIntent.FOLLOWUP_DELTA),
        ("Remove the Trading filter", GOLDEN_TURNS[0], _PRIOR_SQL, plan_2004, TurnIntent.FOLLOWUP_DELTA),
        ("Show invoice count instead", GOLDEN_TURNS[0], _PRIOR_SQL, plan_2004, TurnIntent.FOLLOWUP_DELTA),
        ("Meaning of life", GOLDEN_TURNS[5], _INVOICE_COUNT_SQL, _INVOICE_COUNT_CONTEXT["previousPlan"], TurnIntent.NON_BUSINESS),
        ("Tell me a joke", GOLDEN_TURNS[5], _INVOICE_COUNT_SQL, _INVOICE_COUNT_CONTEXT["previousPlan"], TurnIntent.NON_BUSINESS),
        ("What's your favorite color?", GOLDEN_TURNS[5], _INVOICE_COUNT_SQL, _INVOICE_COUNT_CONTEXT["previousPlan"], TurnIntent.NON_BUSINESS),
        ("Show sales for 2005", GOLDEN_TURNS[5], _INVOICE_COUNT_SQL, _INVOICE_COUNT_CONTEXT["previousPlan"], TurnIntent.NEW_ANALYTICAL_QUERY),
        ("What about Europe?", GOLDEN_TURNS[0], _PRIOR_SQL, plan_2004, TurnIntent.CLARIFICATION_REQUIRED),
        ("sales for customer XYZNOEXIST999", "", "", None, TurnIntent.NEW_ANALYTICAL_QUERY),
    ]
    for question, prev_q, prev_sql, prev_plan, expected in cases:
        got = _classify(question, prev_q, prev_sql, prev_plan)
        assert got.intent == expected, f"{question!r} → {got.intent} ({got.reason}), expected {expected}"


def test_golden_nine_turn_intent_sequence_and_state():
    prev_q = ""
    prev_sql = ""
    prev_plan = None
    prev_status = "SUCCESS"
    analytical_plan = None
    analytical_sql = ""
    analytical_q = ""

    for i, (question, expected) in enumerate(zip(GOLDEN_TURNS, GOLDEN_INTENTS), start=1):
        got = _classify(question, prev_q, prev_sql, prev_plan, prev_status)
        assert got.intent == expected, (
            f"turn {i} {question!r} → {got.intent} ({got.reason}), expected {expected}"
        )
        if expected == TurnIntent.NON_BUSINESS:
            assert analytical_plan is not None
            # Nonsense must not replace active analytical state.
            prev_q, prev_sql, prev_plan, prev_status = (
                analytical_q,
                analytical_sql,
                analytical_plan,
                "SUCCESS",
            )
            continue
        if expected == TurnIntent.NEW_ANALYTICAL_QUERY:
            plan = extract_query_plan(question)
            prev_plan = plan.to_dict()
            prev_sql = 'SELECT 1 FROM "VBRK"'
            prev_q = question
            prev_status = "SUCCESS"
            analytical_plan, analytical_sql, analytical_q = prev_plan, prev_sql, prev_q
            if i == 8:
                years = plan.filters.get("years") or []
                assert "2005" in [str(y) for y in years]
                assert plan.metric != "count"
            continue
        # FOLLOWUP_DELTA
        assert got.plan is not None
        ops = " ".join(got.plan.delta_ops)
        if i == 2:
            assert "add_filter" in ops
        if i == 3:
            assert "change_ranking" in ops
        if i == 4:
            assert "change_time" in ops or "compare" in ops
        if i == 5:
            assert "remove_filter" in ops
        if i == 6:
            assert "change_metric" in ops
        if i == 9:
            assert "change_ranking" in ops
            years = got.plan.filters.get("years") or []
            assert "2005" in [str(y) for y in years]
            assert "2004" not in [str(y) for y in years]
        from app.services.ai_query_plan import QueryPlan
        merged = apply_followup_delta(QueryPlan.from_dict(prev_plan), question)
        prev_plan = merged.to_dict()
        prev_q = question
        prev_sql = 'SELECT 1 FROM "VBRK"'
        prev_status = "SUCCESS"
        analytical_plan, analytical_sql, analytical_q = prev_plan, prev_sql, prev_q


def test_short_followups_remain_valid_with_context():
    plan = extract_query_plan(GOLDEN_TURNS[0]).to_dict()
    for q in (
        "Trading",
        "Top 5",
        "2003",
        "Remove Trading",
        "Invoice count",
        "Count",
        "Sales",
        "Highest industry",
        "Lowest sales",
    ):
        ok, reason = is_supported_business_question(q, has_active_analysis=True)
        assert ok, f"{q} gated as {reason}"
        got = _classify(q, GOLDEN_TURNS[0], _PRIOR_SQL, plan)
        assert got.intent == TurnIntent.FOLLOWUP_DELTA, f"{q} → {got.intent} ({got.reason})"


def test_topic_switch_phrases_are_non_business_even_with_context():
    plan = _INVOICE_COUNT_CONTEXT["previousPlan"]
    for q in (
        "Meaning of life",
        "Tell me a joke",
        "What's your favorite color?",
        "What's the weather today?",
        "Explain SAP",
        "Who is the CEO of Microsoft?",
    ):
        got = _classify(q, GOLDEN_TURNS[5], _INVOICE_COUNT_SQL, plan)
        assert got.intent in {
            TurnIntent.NON_BUSINESS,
            TurnIntent.CLARIFICATION_REQUIRED,
        }, f"{q} → {got.intent}"
        assert got.intent != TurnIntent.FOLLOWUP_DELTA


def test_standalone_2005_is_not_a_year_delta_on_invoice_count():
    got = _classify(
        "Show sales for 2005",
        GOLDEN_TURNS[5],
        _INVOICE_COUNT_SQL,
        _INVOICE_COUNT_CONTEXT["previousPlan"],
    )
    assert got.intent == TurnIntent.NEW_ANALYTICAL_QUERY
    assert looks_like_standalone_analytical("Show sales for 2005")
    assert not looks_like_followup_utterance("Show sales for 2005")


def test_new_invoice_count_for_2005_does_not_keep_trading_filter():
    trading_plan = extract_query_plan(GOLDEN_TURNS[0])
    trading_plan = apply_followup_delta(trading_plan, "Only the Trading industry")
    got = _classify(
        "Show invoice count for 2005",
        "Only the Trading industry",
        _PRIOR_SQL,
        trading_plan.to_dict(),
    )
    assert got.intent == TurnIntent.NEW_ANALYTICAL_QUERY
    fresh = extract_query_plan("Show invoice count for 2005")
    assert "2005" in [str(y) for y in (fresh.filters.get("years") or [])]
    assert not (fresh.filters.get("industry") or "")


async def _adaptive_direct(question: str, context=None):
    from app.api.adaptive_query import post_query_adaptive

    with patch(
        "app.api.adaptive_query._followup_analysis",
        side_effect=AssertionError("previous-result narration must not run"),
    ):
        return await post_query_adaptive(
            question=question,
            tableHint=None,
            contextData=context,
            overrideSql=None,
            threadId=None,
            db=MagicMock(),
            current_user=None,
        )


def test_api_nonsense_after_chain_is_clarification_without_sql():
    import asyncio

    payload = asyncio.run(_adaptive_direct("Meaning of life", _INVOICE_COUNT_CONTEXT))
    assert payload.get("answer_status") == "CLARIFICATION"
    assert not (payload.get("sql") or "").strip()
    assert (payload.get("data") or []) == []
    blob = json.dumps(payload).lower()
    assert "cbd" not in blob
    assert "invoice_count" not in blob
    assert payload.get("meta", {}).get("turn_intent") == TurnIntent.NON_BUSINESS


def test_api_new_analytical_does_not_patch_prior_invoice_count_sql():
    import asyncio

    stub = {
        "sql_path_reason": "intent_sql_fast",
        "sql": 'SELECT 2005 AS year, SUM(1) AS total_sales FROM "VBRK"',
        "rows_preview": [{"year": "2005", "total_sales": 1}],
        "reply": "Sales for 2005",
        "sql_generation_method": "intent_sql_fast",
        "llm_calls": 0,
        "charts": [],
    }
    with patch(
        "app.api.adaptive_query.apply_plan_sql_deltas",
        side_effect=AssertionError("must not apply delta to prior invoice-count SQL"),
    ):
        with patch(
            "app.services.dashboard_query_router.run_dashboard_query",
            return_value=stub,
        ):
            payload = asyncio.run(_adaptive_direct("Show sales for 2005", _INVOICE_COUNT_CONTEXT))
    assert payload.get("answer_status") != "CLARIFICATION"
    assert "2005" in (payload.get("sql") or "")
    assert payload.get("follow_up_mode") != "narrative"
    assert payload.get("meta", {}).get("turn_intent") == TurnIntent.NEW_ANALYTICAL_QUERY
    blob = json.dumps(payload).lower()
    assert "cbd computer" not in blob
    assert "from your result set" not in blob


def test_context_data_alone_does_not_force_followup():
    got = _classify(
        "Show sales for 2005",
        "Show invoice count instead",
        _INVOICE_COUNT_SQL,
        _INVOICE_COUNT_CONTEXT["previousPlan"],
    )
    assert got.intent != TurnIntent.FOLLOWUP_DELTA
    empty = _classify("Show sales for 2005")
    assert empty.intent == TurnIntent.NEW_ANALYTICAL_QUERY
