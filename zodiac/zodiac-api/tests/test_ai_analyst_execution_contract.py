"""Regression coverage for conversation, SQL execution, and response boundaries."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst.orchestrator import adapt_user_turn
from app.services.ai_followup_routing import TurnIntent, classify_turn
from app.services.ai_query_plan import extract_query_plan
from app.services.investigation_budget import begin_investigation, end_investigation


@pytest.mark.parametrize("question, prior_question, prior_sql", [
    (
        "For that country, show billed sales by year for the last five complete years available.",
        "Show the top five countries by billed sales in the latest complete year.",
        'SELECT country, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY country ORDER BY total_sales DESC LIMIT 5',
    ),
    (
        "Show the top ten billing documents behind the leading customer's total.",
        "Show the top five customers by billed sales in the latest complete year.",
        'SELECT kunag AS customer, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY kunag ORDER BY total_sales DESC LIMIT 5',
    ),
    (
        "For the higher-sales country, show monthly billed sales in the same year and currency.",
        "Show the top five countries by billed sales in the latest complete year available.",
        'SELECT country, currency, SUM(netwr) AS billed_sales FROM "VBRK" GROUP BY country, currency ORDER BY billed_sales DESC LIMIT 5',
    ),
])
def test_drilldown_keeps_the_selected_result_context(question, prior_question, prior_sql):
    prior_plan = extract_query_plan(prior_question).to_dict()
    adapted = adapt_user_turn(
        question, prior_question=prior_question, prior_plan=prior_plan, prior_status="SUCCESS",
    )
    assert adapted.action == "query"
    assert adapted.question == question
    assert not adapted.drop_prior
    assert adapted.is_fragment
    turn = classify_turn(
        adapted.question, previous_question=prior_question, previous_sql=prior_sql,
        previous_plan=prior_plan, previous_status="SUCCESS",
    )
    assert turn.intent == TurnIntent.FOLLOWUP_DELTA


def test_followup_generation_receives_current_question_and_separate_prior_sql(monkeypatch):
    from app.services import four_stage_db_pipeline as pipeline

    question = "For that country, show billed sales by year for the last five complete years available."
    prior_sql = 'SELECT country, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY country ORDER BY total_sales DESC LIMIT 5'
    prior = {"verified_db_context": {
        "question": "Show the top five countries by billed sales.",
        "tables": ["VBRK", "KNA1"], "columns": ["VBRK.netwr", "KNA1.land1"],
    }}
    seen = []

    def select_tables(current, context):
        assert current == question
        context.tables = ["VBRK", "KNA1"]

    def select_columns(current, context):
        assert current == question
        context.columns = ["VBRK.netwr", "VBRK.fkdat", "KNA1.land1"]

    def prepare_plan(current, context, db):
        assert current == question
        context.query_plan = {"grain": "year"}

    def generate(current, context, *, validation_feedback=None):
        if validation_feedback is not None:
            assert validation_feedback["kind"] == "sql_validation_repair"
            assert validation_feedback["validation_errors"] == ["test validation boundary"]
        seen.append((current, context.prior_sql))
        return 'SELECT fkdat AS billing_date FROM "VBRK"'

    monkeypatch.setattr(pipeline, "extract_semantic_requirements", lambda _: {"dimensions": ["year"]})
    monkeypatch.setattr(pipeline, "pipeline1_table_selection", select_tables)
    monkeypatch.setattr(pipeline, "pipeline2_column_selection", select_columns)
    monkeypatch.setattr(pipeline, "pipeline25_query_plan", prepare_plan)
    monkeypatch.setattr(pipeline, "pipeline3_sql_generation", generate)
    monkeypatch.setattr(pipeline, "_apply_currency_if_needed", lambda _q, sql, *_args: sql)
    # Stop at validation: this test exercises the request/context handoff, not
    # database execution or the contents of a synthetic result.
    monkeypatch.setattr(pipeline, "_validate_sql_against_context", lambda *_args: ["test validation boundary"])
    execute = MagicMock(side_effect=AssertionError("validation must stop execution"))
    result = pipeline._run_four_stage_body(question, MagicMock(), execute, prior_plan=prior, prior_sql=prior_sql)
    assert result["error"] == "sql_validation_failed"
    assert seen and all(current == question and previous == prior_sql for current, previous in seen)
    execute.assert_not_called()


@pytest.mark.parametrize("succeeded", [True, False])
def test_execution_trace_records_the_actual_sanitized_sql(monkeypatch, succeeded):
    from app.api import adaptive_query as api

    monkeypatch.setattr(api, "apply_statement_timeout", lambda *_args, **_kwargs: None)
    db = MagicMock()
    if succeeded:
        db.execute.return_value.keys.return_value = ["document_count"]
        db.execute.return_value.fetchall.return_value = [(7,)]
    else:
        db.execute.side_effect = RuntimeError("database execution failed")
    input_sql = "SELECT COUNT(*) AS document_count FROM VBRK"
    budget = begin_investigation("How many billing documents are there?")
    try:
        if succeeded:
            assert api._execute_sql(db, input_sql, budget.question) == [{"document_count": 7}]
        else:
            with pytest.raises(RuntimeError, match="database execution failed"):
                api._execute_sql(db, input_sql, budget.question)
        executed_sql = str(db.execute.call_args.args[0])
        assert '"VBRK"' in executed_sql
        assert budget.diagnostics["sql_execution"] == {
            "input_sql": input_sql, "sql": executed_sql, "succeeded": succeeded,
        }
        assert budget.diagnostics["sql_status"] == ("executed" if succeeded else "execution_failed")
    finally:
        end_investigation()


def test_endpoint_keeps_attempted_sql_and_clears_failed_result_visuals(monkeypatch):
    from app.api import adaptive_query as api
    from app.services import adaptive_analyst

    monkeypatch.setenv("OPEN_AI_KEY", "test-key")
    monkeypatch.setattr(api, "apply_statement_timeout", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.services.operational_query_resolver.resolve_operational_query", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adaptive_analyst, "orchestrator_enabled", lambda: True)
    db = MagicMock()
    db.execute.side_effect = RuntimeError("database execution failed")
    input_sql = "SELECT COUNT(*) AS document_count FROM VBRK"

    def fail_analysis(question, session, execute, **_kwargs):
        with pytest.raises(RuntimeError, match="database execution failed"):
            execute(session, input_sql, question)
        return {
            "mode": "error", "answer_status": "CANNOT_ANSWER",
            "summary": "The query could not be completed.", "sql": "",
            "data": [{"document_count": 999}], "rowCount": 1,
            "charts": [{"type": "bar", "data": [{"value": 999}]}],
            "kpis": [{"label": "stale total", "value": 999}],
        }

    monkeypatch.setattr(adaptive_analyst, "run_adaptive_orchestrator", fail_analysis)
    try:
        payload = api.post_query_adaptive(
            question="How many billing documents are in the database?", tableHint=None,
            contextData=None, overrideSql=None, threadId=None, investigationId=None,
            conversationHistory=None, newQuestion=False, db=db, current_user=None,
        )
    finally:
        end_investigation()
    assert payload["answer_status"] == "CANNOT_ANSWER"
    assert payload["sql"] == str(db.execute.call_args.args[0])
    assert payload["attempted_sql"] == payload["sql"]
    assert payload["sql_status"] == "execution_failed"
    assert payload["data"] == [] and payload["rowCount"] == 0
    assert payload["charts"] == [] and payload["kpis"] == []


def test_endpoint_rejects_wrong_ranking_but_preserves_sql_for_inspection(monkeypatch):
    from app.api import adaptive_query as api
    from app.services import adaptive_analyst

    monkeypatch.setenv("OPEN_AI_KEY", "test-key")
    monkeypatch.setattr("app.services.operational_query_resolver.resolve_operational_query", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adaptive_analyst, "orchestrator_enabled", lambda: True)
    sql = 'SELECT country, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY country ORDER BY total_sales DESC LIMIT 10'
    rows = [{"country": f"country-{index}", "total_sales": 100 - index} for index in range(10)]
    monkeypatch.setattr(adaptive_analyst, "run_adaptive_orchestrator", lambda *_args, **_kwargs: {
        "mode": "analysis", "answer_status": "SUCCESS", "sql": sql,
        "data": rows, "rowCount": len(rows), "summary": "These are the highest countries.",
        "charts": [{"type": "bar", "data": rows}], "pipeline": "four_stage_schema_intelligence",
    })
    try:
        payload = api.post_query_adaptive(
            question="Show the top five countries by billed sales.", tableHint=None,
            contextData=None, overrideSql=None, threadId=None, investigationId=None,
            conversationHistory=None, newQuestion=False, db=MagicMock(), current_user=None,
        )
    finally:
        end_investigation()
    assert payload["answer_status"] == "CANNOT_ANSWER"
    assert payload["sql"] == sql
    assert payload["sql_status"] == "result_validation_failed"
    assert payload["charts"] == [] and payload["data"] == []


@pytest.mark.parametrize("model_rewrite", [
    'SELECT country, SUM(netwr) AS sales FROM "VBRK" GROUP BY country LIMIT 10',
    'WITH sales AS (SELECT * FROM "VBRK") SELECT * FROM sales',
    '```sql\nSELECT * FROM "VBRK"\n```',
])
def test_new_analytics_question_is_not_replaced_by_model_sql(monkeypatch, model_rewrite):
    from app.services.adaptive_analyst import orchestrator, understanding

    question = "Show the top five countries by billed sales in the latest complete year available in the data."
    monkeypatch.setattr(understanding, "understand_turn", lambda *_args, **_kwargs: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, resolved_question=model_rewrite,
        understanding_model_called=True,
    ))
    monkeypatch.setattr("app.services.adaptive_analyst.governed.try_governed_database", lambda *_args, **_kwargs: None)
    sql_pipeline = MagicMock(return_value={"error": "sql_validation_failed", "sql": "", "detail": ["test boundary"]})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", sql_pipeline)
    payload = orchestrator.run_adaptive_orchestrator(question, MagicMock(), MagicMock())
    assert payload["answer_status"] == "CANNOT_ANSWER"
    assert sql_pipeline.call_count == 1
    assert sql_pipeline.call_args.args[:2] == (question, question)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM items WHERE document_id = <document_id>",
    "SELECT * FROM items WHERE document_id = 'your_document_id'",
    "SELECT ... FROM items",
])
def test_unresolved_template_values_are_rejected(sql):
    from app.services.four_stage_db_pipeline import _contains_unresolved_sql_value

    assert _contains_unresolved_sql_value(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM events WHERE event_date < DATE '2002-01-01' AND event_date >= DATE '2001-01-01'",
    "SELECT * FROM items WHERE amount < 0 AND quantity > 0",
    "SELECT * FROM items WHERE amount <= 10 AND amount >= -10",
])
def test_real_comparison_operators_are_not_template_markers(sql):
    from app.services.four_stage_db_pipeline import _contains_unresolved_sql_value

    assert not _contains_unresolved_sql_value(sql)


def test_latest_complete_years_skip_a_partially_loaded_latest_year():
    from app.services.four_stage_db_pipeline import VerifiedDbContext, _resolve_latest_data_years

    question = "Show billed sales for the latest two complete years available in the data."
    context = VerifiedDbContext(
        question=question, tables=["VBRK"], columns=["VBRK.FKDAT"],
        semantic_requirements={"time_filter": {"relative": "latest_two_full_years", "count": 2}},
    )
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        ("2002", "20020630", "19991231"),
        ("2001", "20020630", "19991231"),
        ("2000", "20020630", "19991231"),
    ]
    assert _resolve_latest_data_years(question, context, db)
    period = context.semantic_requirements["time_filter"]
    assert period["years"] == ["2000", "2001"]
    assert period["end"] == "2002-01-01"
    assert period["observed_end"] == "2002-06-30"
    assert period["coverage_basis"] == "calendar period within observed date range"


def test_insufficient_bounded_years_clarify_instead_of_claiming_full_periods():
    from app.services.four_stage_db_pipeline import VerifiedDbContext, _resolve_latest_data_years

    question = "Show billed sales for the latest two complete years available in the data."
    context = VerifiedDbContext(
        question=question, tables=["VBRK"], columns=["VBRK.FKDAT"],
        semantic_requirements={"time_filter": {"relative": "latest_two_full_years", "count": 2}},
    )
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        ("2002", "20020630", "20010115"),
        ("2001", "20020630", "20010115"),
    ]
    assert not _resolve_latest_data_years(question, context, db)
    clarification = context.semantic_requirements["clarification"]
    assert clarification["type"] == "latest_data_period"
    assert "2 completed calendar year" in clarification["message"]
    assert not context.semantic_requirements["time_filter"].get("resolved_from_data")
