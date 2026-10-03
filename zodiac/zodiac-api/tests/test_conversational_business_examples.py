"""General examples must not acquire a database route from sales vocabulary."""
from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst import orchestrator, understanding


@pytest.mark.parametrize("question", [
    "Give an example of that using gross sales of 1000, returns of 100 and discounts of 50.",
    "Calculate that with hypothetical revenue of 2400 and returns of 60.",
    "Show how that sales calculation works when the amounts are supplied by me.",
])
@pytest.mark.parametrize("has_retained_result", [False, True])
def test_model_selected_example_stays_general_with_or_without_data_history(
    monkeypatch, question, has_retained_result,
):
    monkeypatch.setattr(understanding, "understand_turn", lambda *_args, **_kwargs: understanding.TurnUnderstanding(
        intent="conversation", requires_database=False, requires_conversation_context=True,
        goal="Illustrate the prior explanation using user-supplied numbers",
        understanding_model_called=True,
    ))
    respond = MagicMock(return_value=("For the supplied example, net sales are 850.", "test"))
    monkeypatch.setattr(understanding, "generate_grounded_response", respond)
    sql_pipeline = MagicMock(side_effect=AssertionError("an example must not generate SQL"))
    execute = MagicMock(side_effect=AssertionError("an example must not query the database"))
    reuse = MagicMock(side_effect=AssertionError("an example must not select prior result rows"))
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", sql_pipeline)
    monkeypatch.setattr("app.services.result_first_followup.try_answer_from_prior_rows", reuse)
    plan = {"last_mode": "general_chat", "investigation_state": {
        "mode": "general_chat", "last_summary": "Net sales subtract returns and discounts from gross sales.",
        "recent_turns": [{"role": "assistant", "mode": "general_chat", "content": "Net sales subtract returns and discounts."}],
    }}
    rows = [{"country": "US", "currency": "USD", "billed_sales": 5000}] if has_retained_result else []
    prior_sql = 'SELECT country, currency, SUM(netwr) AS billed_sales FROM "VBRK" GROUP BY country, currency' if has_retained_result else ""

    result = orchestrator.run_adaptive_orchestrator(
        question, MagicMock(), execute, use_sap=False,
        prior_question="Explain net sales versus gross sales.", prior_plan=plan,
        prior_status="SUCCESS", prior_rows=rows, prior_sql=prior_sql,
    )

    assert result["mode"] == "general_chat"
    assert result["route"] == "general"
    assert result["answer_status"] == "SUCCESS"
    assert result["answer"] == respond.return_value[0]
    assert result["sql"] == "" and result["data"] == []
    assert not result.get("noDataGap")
    assert result["meta"]["selected_capability"] == "conversation"
    sql_pipeline.assert_not_called()
    execute.assert_not_called()
    reuse.assert_not_called()


def test_data_followup_after_general_chat_keeps_retained_verified_sql(monkeypatch):
    question = "For that country, show monthly billed sales in the same year and currency."
    sql = 'SELECT country, currency, SUM(netwr) AS billed_sales FROM "VBRK" WHERE fkdat LIKE \'2017%\' GROUP BY country, currency'
    monkeypatch.setattr(understanding, "understand_turn", lambda *_args, **_kwargs: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, requires_conversation_context=True,
        resolved_question="Show billed sales by month for country code 'US' in calendar year 2017 in currency USD.",
        understanding_model_called=True,
    ))
    monkeypatch.setattr("app.services.result_first_followup.try_answer_from_prior_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.services.adaptive_analyst.governed.try_governed_database", lambda *_args, **_kwargs: None)
    sql_pipeline = MagicMock(return_value={"error": "sql_validation_failed", "detail": ["test boundary"]})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", sql_pipeline)
    plan = {
        "last_mode": "general_chat",
        "recent_turns": [{"role": "assistant", "mode": "general_chat", "content": "Net sales subtract returns."}],
        "retained_analytical_context": {
            "previousQuestion": "Show the top countries by billed sales in 2017 in USD.",
            "previousSQL": sql, "previousAnswerStatus": "SUCCESS",
            "previousPlan": {"last_mode": "database_analysis"},
            "data": [{"country": "US", "currency": "USD", "billed_sales": 5000}],
        },
    }

    result = orchestrator.run_adaptive_orchestrator(
        question, MagicMock(), MagicMock(), use_sap=False,
        prior_question="Explain net sales.", prior_plan=plan, prior_status="SUCCESS",
    )

    assert result["route"] == "database"
    assert sql_pipeline.call_count == 1
    assert sql_pipeline.call_args.kwargs["prior_sql"] == sql
    assert sql_pipeline.call_args.args[3].recent_turns[0]["content"] == "Net sales subtract returns."


def test_data_followup_with_missing_selection_still_clarifies_after_understanding(monkeypatch):
    model = MagicMock(return_value=understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, requires_conversation_context=True,
        understanding_model_called=True,
    ))
    monkeypatch.setattr(understanding, "understand_turn", model)
    execute = MagicMock(side_effect=AssertionError("a missing selection must not query the database"))
    result = orchestrator.run_adaptive_orchestrator(
        "For that country, show monthly billed sales in the same year.",
        MagicMock(), execute, prior_question="Show top countries.",
        prior_status="CANNOT_ANSWER", use_sap=False,
    )
    assert result["answer_status"] == "CLARIFICATION"
    assert result["sql"] == ""
    assert result["meta"]["understanding_model_called"]
    model.assert_called_once()
    execute.assert_not_called()


def test_general_reply_uses_current_outer_history_over_saved_analysis_snapshot(monkeypatch):
    monkeypatch.setattr(understanding, "understand_turn", lambda *_args, **_kwargs: understanding.TurnUnderstanding(
        intent="conversation", requires_database=False, understanding_model_called=True,
    ))
    respond = MagicMock(return_value=("An explanation in the requested style.", "test"))
    monkeypatch.setattr(understanding, "generate_grounded_response", respond)
    newest = [{"role": "user", "content": "Use short answers with simple examples."}]
    plan = {
        "last_mode": "general_chat", "recent_turns": newest,
        "investigation_state": {"mode": "general_chat", "recent_turns": [
            {"role": "assistant", "content": "An older answer."},
        ]},
    }
    result = orchestrator.run_adaptive_orchestrator(
        "Give another explanation.", MagicMock(), MagicMock(), use_sap=False,
        prior_question="Explain sales.", prior_plan=plan, prior_status="SUCCESS",
    )
    assert result["mode"] == "general_chat"
    assert respond.call_args.kwargs["evidence"]["recent_turns"][:1] == newest
