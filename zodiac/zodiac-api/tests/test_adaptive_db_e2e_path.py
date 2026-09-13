"""End-to-end adaptive path simulation without live DB.

Exercises: route → semantics → plan → SQL builders → presentation → safety.
Does not invent row values; charts bind only to provided rows.
"""
from __future__ import annotations

from app.services.adaptive_analyst.diagnostics import build_analytical_diagnostics
from app.services.adaptive_analyst.investigation import plan_investigation_steps
from app.services.adaptive_analyst.presentation import plan_presentation
from app.services.adaptive_nl_sql_hardening import (
    is_capability_or_help_question,
    is_general_knowledge_question,
    question_requires_database,
)
from app.services.adaptive_structured_sql import (
    build_dimension_ranking_sql,
    build_period_compare_sql,
    build_period_sales_sql,
    build_total_measure_sql,
)
from app.services.ai_query_memory_service import validate_sql_for_safe_execution
from app.services.analytical_operations import extract_analytical_operations
from app.services.plan_satisfaction import sql_satisfies_analytical_intent
from app.services.semantic_requirements import required_semantics


def _sql_for(q: str):
    return (
        build_period_compare_sql(q, [])
        or build_dimension_ranking_sql(q, [])
        or build_period_sales_sql(q, [])
        or build_total_measure_sql(q, [])
    )


def test_e2e_general_stays_off_db():
    assert is_capability_or_help_question("What can I ask?")
    assert not question_requires_database("What can I ask?")
    assert is_general_knowledge_question("What is SAP?")
    assert not question_requires_database("What is SAP?")


def test_e2e_basic_and_unseen_revenue_sql():
    for q in (
        "What was revenue in 2025?",
        "How much money did we generate during 2025?",
    ):
        assert question_requires_database(q)
        ops = extract_analytical_operations(q)
        assert ops.get("measure_concept") in {"revenue", "sales"}
        sql = _sql_for(q)
        assert sql
        ok, _ = validate_sql_for_safe_execution(sql)
        assert ok
        assert sql_satisfies_analytical_intent(sql, q)


def test_e2e_ranking_sql_and_chart_from_rows():
    q = "Which five customers brought in the most revenue?"
    sql = _sql_for(q)
    assert sql and "LIMIT 5" in sql.upper()
    rows = [
        {"customer_name": "A", "total_sales": 50},
        {"customer_name": "B", "total_sales": 40},
        {"customer_name": "C", "total_sales": 30},
        {"customer_name": "D", "total_sales": 20},
        {"customer_name": "E", "total_sales": 10},
    ]
    charts = [{"chart_type": "bar", "data": rows, "x_key": "customer_name", "y_keys": ["total_sales"]}]
    plan = plan_presentation(q + " as a chart.", rows, charts=charts)
    assert plan["data_from_rows_only"] is True
    assert plan["charts"][0]["data"] == rows


def test_e2e_comparison_and_trend():
    q_cmp = "How much did revenue change between 2024 and 2025?"
    sql_cmp = build_period_compare_sql(q_cmp, [])
    assert sql_cmp
    assert "2024" in sql_cmp and "2025" in sql_cmp
    q_tr = "Show me the monthly revenue trend for 2025."
    sql_tr = build_period_sales_sql(q_tr, [])
    assert sql_tr and "month" in sql_tr.lower()
    assert "2025" in sql_tr


def test_e2e_investigation_plan_and_unseen_contribution_sql():
    q_why = "Why did revenue fall?"
    req = required_semantics(q_why)
    assert req.get("period_compare")
    steps = plan_investigation_steps(q_why, req)
    assert steps[0]["kind"] == "confirm_direction"
    assert any(s["kind"] == "drivers" for s in steps)

    q = (
        "Which three customers accounted for the largest share of the revenue "
        "decline between 2024 and 2025?"
    )
    sql = build_period_compare_sql(q, [])
    assert sql
    assert "contribution_pct" in sql.lower() or "change" in sql.lower()
    assert sql_satisfies_analytical_intent(sql, q)
    ok, _ = validate_sql_for_safe_execution(sql)
    assert ok


def test_e2e_diagnostics_contract():
    q = "Which five customers brought in the most revenue?"
    sql = _sql_for(q) or ""
    diag = build_analytical_diagnostics(
        question=q,
        route="database",
        semantic=required_semantics(q),
        sql=sql,
        row_count=5,
        presentation={"type": "chart", "chart_type": "bar"},
        answer_status="SUCCESS",
        failure_class="SUCCESS",
    )
    assert diag["semantic_plan"]["ranking"]
    assert diag["sql"]["generated"] is True
    assert diag["final_status"] == "SUCCESS"
