"""Expanded unseen-formulation matrix for adaptive DB intelligence.

Same underlying capability under different wording — no phrase handlers.
"""
from __future__ import annotations

import re

from app.services.adaptive_analyst.investigation import (
    available_driver_grains,
    evidence_based_summary,
    plan_investigation_steps,
)
from app.services.adaptive_analyst.presentation import plan_presentation
from app.services.adaptive_structured_sql import build_period_compare_sql, extract_ranking_limit
from app.services.analytical_operations import extract_analytical_operations
from app.services.ai_query_memory_service import validate_sql_for_safe_execution
from app.services.plan_satisfaction import sql_satisfies_analytical_intent
from app.services.result_first_followup import try_answer_from_prior_rows
from app.services.semantic_requirements import required_semantics
from app.services.sql_validator import validate_sql


def _measures_align(a, b):
    return {a, b} <= {"revenue", "sales", "billing"} or a == b


def test_sales_2025_paraphrase_matrix():
    variants = [
        "What were our sales in 2025?",
        "How much did we sell in 2025?",
        "Show me 2025 sales.",
        "Give me the total sales for 2025.",
        "How much money did we generate during 2025?",
    ]
    for q in variants:
        ops = extract_analytical_operations(q)
        assert ops.get("measure_concept") in {"revenue", "sales", "billing", "quantity"} or ops.get(
            "aggregation"
        ), q
        assert "2025" in (ops.get("years") or []), q


def test_ranking_paraphrase_matrix_limit_five():
    variants = [
        "Top 5 customers by revenue.",
        "Which five customers generated the most revenue?",
        "Who were our five biggest customers by sales?",
        "Give me the five biggest customers by sales.",
    ]
    for q in variants:
        ops = extract_analytical_operations(q)
        assert ops.get("ranking"), q
        assert int(ops["ranking"]["limit"]) == 5, q
        assert extract_ranking_limit(q) == 5, q


def test_comparison_paraphrase_matrix():
    variants = [
        "Compare 2024 and 2025 revenue.",
        "Did revenue increase in 2025?",
        "How much did revenue change year over year?",
        "Was 2025 better than 2024 in terms of revenue?",
        "How much did revenue change between 2024 and 2025?",
    ]
    for q in variants:
        ops = extract_analytical_operations(q)
        req = required_semantics(q)
        assert ops.get("compare") or ops.get("growth") or req.get("period_compare") or ops.get(
            "period_compare"
        ), q


def test_trend_paraphrase_matrix():
    variants = [
        "Show monthly revenue in 2025.",
        "How did revenue move month by month?",
        "What was the revenue trend during 2025?",
        "Show me the monthly revenue trend for 2025.",
    ]
    for q in variants:
        ops = extract_analytical_operations(q)
        assert ops.get("trend") or ops.get("time_grain") == "month" or "month" in (
            ops.get("group_by") or []
        ), q


def test_investigation_paraphrase_matrix():
    variants = [
        "Why did revenue fall?",
        "What drove the revenue decline?",
        "Which customers contributed most to the decrease?",
        "What changed that caused the drop?",
        "Why did revenue decrease in 2025?",
    ]
    for q in variants:
        ops = extract_analytical_operations(q)
        req = required_semantics(q)
        assert ops.get("contribution") or ops.get("period_compare") or req.get("period_compare"), q
        steps = plan_investigation_steps(q, req)
        assert any(s.get("kind") == "confirm_direction" for s in steps), q
        assert any(s.get("kind") == "drivers" for s in steps), q


def test_unseen_share_of_decline_three_customers():
    q = (
        "Which three customers accounted for the largest share of the revenue "
        "decline between 2024 and 2025?"
    )
    ops = extract_analytical_operations(q)
    req = required_semantics(q)
    assert ops.get("contribution") or ops.get("share")
    assert req.get("period_compare")
    assert int((ops.get("ranking") or {}).get("limit") or 0) == 3
    assert "customer" in (ops.get("group_by") or req.get("group_by") or [])
    sql = build_period_compare_sql(q, [])
    # Schema may be absent in unit env; semantics + intent gate still apply when SQL builds.
    if sql:
        assert "LIMIT 3" in sql.upper() or "LIMIT 5" in sql.upper() or "contribution" in sql.lower()
        assert sql_satisfies_analytical_intent(sql, q)
        assert "contribution_pct" in sql.lower() or "change" in sql.lower()


def test_multi_grain_investigation_plan_from_schema():
    q = "Why did revenue fall?"
    grains = available_driver_grains(q, required_semantics(q))
    assert grains
    assert "customer" in grains or "material" in grains or "country" in grains
    steps = plan_investigation_steps(q, required_semantics(q))
    driver_grains = [s["group_by"][0] for s in steps if s.get("kind") == "drivers"]
    assert len(driver_grains) >= 1
    assert len(driver_grains) <= 3


def test_evidence_language_is_contribution_not_causality():
    text = evidence_based_summary(
        confirm={"period_a": 100.0, "period_b": 80.0, "change": -20.0},
        driver_rows=[{"customer_name": "Acme", "change": -12.0, "contribution_pct": 60.0}],
        grain="customer",
    )
    assert "accounted for" in text.lower() or "contributor" in text.lower()
    assert "disliked" not in text.lower()
    assert "caused because" not in text.lower()


def test_presentation_both_chart_and_table():
    rows = [{"customer_name": "A", "total_sales": 9}, {"customer_name": "B", "total_sales": 7}]
    charts = [{"chart_type": "bar", "data": rows, "x_key": "customer_name", "y_keys": ["total_sales"]}]
    plan = plan_presentation(
        "Show the top customers by revenue — give me both the chart and the table.",
        rows,
        charts=charts,
    )
    assert plan["prefer_both"] or plan["type"] == "chart_table"
    assert plan["data_from_rows_only"] is True
    assert any(str(c.get("chart_type")) == "table" for c in plan.get("charts") or [])
    for c in plan.get("charts") or []:
        if c.get("data"):
            assert c["data"] == rows or c["data"] == rows[:100]


def test_followup_growth_then_needs_sql_when_levels_only():
    prior = [
        {"customer_name": "Acme", "total_sales": 100},
        {"customer_name": "Beta", "total_sales": 90},
    ]
    out = try_answer_from_prior_rows(
        "Which one grew the fastest?",
        prior,
        prior_plan={"last_user_question": "Show the top 5 customers by revenue."},
    )
    assert out and out.get("needs_plan_expansion")
    assert out.get("expanded_question")
    assert "Acme" in out["expanded_question"]


def test_destructive_sql_blocked_read_only():
    for bad in (
        "DELETE FROM \"VBRK\"",
        "DROP TABLE \"KNA1\"",
        "INSERT INTO \"VBRK\" VALUES (1)",
        "UPDATE \"VBRK\" SET netwr = 0",
        "TRUNCATE \"VBRK\"",
    ):
        ok, reason = validate_sql_for_safe_execution(bad)
        assert ok is False, bad
        assert reason


def test_select_only_schema_validator():
    ok, err = validate_sql("DELETE FROM VBRK", {"VBRK": ["netwr"]})
    assert ok is False
    assert err and "SELECT" in err.upper()


def test_model_cannot_inject_foreign_tenant_filter_as_authority():
    """Trusted scope rewrites user-scoped predicates; writes stay blocked.

    SAP extract isolation is connection/DSN binding (process config), not LLM.
    App tables with user_id are constrained by TrustedAiExecutionScope.
    """
    from app.services.adaptive_trusted_scope import (
        TrustedAiExecutionScope,
        enforce_trusted_user_scope,
    )

    forged = (
        "SELECT id, user_id FROM sat_documents WHERE user_id = 999999 ORDER BY id DESC LIMIT 5"
    )
    out, params = enforce_trusted_user_scope(forged, TrustedAiExecutionScope(user_id=42))
    assert params["_trusted_user_id"] == 42
    assert "999999" not in out
    assert "user_id = :_trusted_user_id" in out

    multi = 'SELECT 1 FROM "VBRK"; DROP TABLE "KNA1"'
    ok2, reason = validate_sql_for_safe_execution(multi)
    assert ok2 is False
    assert reason


def test_router_still_keeps_general_outside_db():
    from app.services.adaptive_nl_sql_hardening import (
        is_capability_or_help_question,
        is_general_knowledge_question,
        question_requires_database,
    )

    assert is_capability_or_help_question("What can I ask?")
    assert not question_requires_database("What can I ask?")
    assert is_general_knowledge_question("What is SAP?")
    assert not question_requires_database("What is SAP?")
