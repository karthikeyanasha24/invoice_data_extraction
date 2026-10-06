"""Clarification answers complete requests; they do not require executed rows."""
from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst import orchestrator, understanding
from app.services.adaptive_analyst.pending_analysis import pending_analysis_context


def test_final_result_validation_reuses_the_pipeline_question_not_its_paraphrase():
    original = "Show the top 10 customers by billed sales, grouped by currency."
    rewritten = "For each currency, rank customers by invoice revenue."

    assert orchestrator._result_validation_question(
        {"_original_user_question": original}, original, rewritten
    ) == original
    assert orchestrator._result_validation_question({}, original, rewritten) == original


def test_self_contained_database_question_replaces_stale_pending_clarification(monkeypatch):
    question = (
        "Show the bottom 10 negative billed invoices in calendar year 2000. "
        "Include billing document number, customer, invoice posting date, billed amount, and currency. "
        "For those invoices, compare linked sales order totals in 2000 versus 2001 "
        "and show absolute and percent change. Show the SQL."
    )
    pending_plan = {"pending_analysis": {"question": "Compare billed sales in 2018 and 2019."}}

    adapted = orchestrator.adapt_user_turn(
        question,
        prior_question="Compare billed sales in 2018 and 2019.",
        prior_plan=pending_plan,
        prior_status="CLARIFICATION",
    )

    assert adapted.action == "query"
    assert adapted.question == question
    # Verify the observable SQL scope rather than requiring a particular
    # pre-model adapter decision for this fully specified restatement.
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="new_request", context_source="none",
    ))
    pipeline = MagicMock(return_value={"error": "sql_validation_failed", "detail": ["test boundary"]})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    orchestrator.run_adaptive_orchestrator(
        question, MagicMock(), MagicMock(), prior_plan=pending_plan,
        prior_question="Compare billed sales in 2018 and 2019.", prior_status="CLARIFICATION",
    )
    assert pipeline.call_args.args[0] == question
    assert pipeline.call_args.kwargs["prior_sql"] == ""
    assert pipeline.call_args.args[3].tables == []


@pytest.mark.parametrize("reply", ["USD", "By supplier for those periods", "Yes, use those defaults", "Compare invoices first", "Show both changes"])
def test_short_clarification_reply_keeps_pending_context(reply):
    pending_plan = {"pending_analysis": {"question": "Compare billed sales in 2018 and 2019."}}

    adapted = orchestrator.adapt_user_turn(
        reply,
        prior_question="Compare billed sales in 2018 and 2019.",
        prior_plan=pending_plan,
        prior_status="CLARIFICATION",
    )

    assert adapted.action == "query"
    assert adapted.drop_prior is False
    assert adapted.is_fragment is True


@pytest.mark.parametrize("original,reply,resolved", [
    (
        "Show lowest negative sales in 2000 and compare with 2001.",
        "Use first invoices to compare and then compare with sales orders relevant to those linked invoices",
        "List the ten most negative billed invoices in 2000, compare their customers' billed amounts with 2001, and include the sales orders linked to those invoices.",
    ),
    (
        "Compare purchasing costs in 2012 and 2013.",
        "By supplier, show both changes for those periods.",
        "Compare purchasing costs by supplier in 2012 versus 2013 with absolute and percentage changes.",
    ),
    (
        "Rank stock balances for 2022.", "Use warehouse totals, twenty rows.",
        "Rank the twenty warehouses with the highest stock balance in 2022.",
    ),
    (
        "Compare billed sales in 2018 and 2019.", "Yes, use those defaults.",
        "Compare total billed sales in 2018 and 2019, separately by currency, with absolute and percentage changes.",
    ),
])
def test_pending_answer_reaches_sql_with_whole_model_resolved_goal(monkeypatch, original, reply, resolved):
    model = MagicMock(return_value=understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, resolved_question=resolved,
        turn_relation="clarification_answer", context_source="pending_request",
        understanding_model_called=True,
    ))
    monkeypatch.setattr(understanding, "understand_turn", model)
    pipeline = MagicMock(return_value={"error": "sql_validation_failed", "detail": ["test boundary"]})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    plan = {"last_mode": "clarification", "pending_analysis": {
        "question": original, "clarification_question": "Which grouping should I use?",
    }}
    result = orchestrator.run_adaptive_orchestrator(
        reply, MagicMock(), MagicMock(), prior_question=original,
        prior_plan=plan, prior_status="CLARIFICATION", prior_rows=[], prior_sql="",
    )
    # The SQL boundary is deliberately stubbed: verify routing and intent,
    # without pretending that a mocked query is a verified database answer.
    assert pipeline.call_count == 1
    assert pipeline.call_args.args[0] == resolved
    assert pipeline.call_args.kwargs["prior_sql"] == ""
    assert result["route"] == "database"
    assert model.call_args.kwargs["prior_plan"]["pending_analysis"]["question"] == original


def test_partial_answers_preserve_accumulated_request_for_next_clarification(monkeypatch):
    complete_so_far = "Compare purchasing costs by supplier in 2012 versus 2013."
    model = understanding.TurnUnderstanding(
        intent="clarification", requires_database=True, clarification_needed=True,
        clarification_question="Should I use order date or receipt date?",
        resolved_question=complete_so_far,
        turn_relation="clarification_answer", context_source="pending_request",
    )
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: model)
    result = orchestrator.run_adaptive_orchestrator(
        "By supplier", MagicMock(), MagicMock(), prior_status="CLARIFICATION",
        prior_question="Compare purchasing costs in 2012 and 2013.",
    )
    assert result["answer_status"] == "CLARIFICATION"
    assert result["query_plan"]["pending_analysis"]["question"] == complete_so_far
    assert pending_analysis_context(result["query_plan"], "By supplier", "CLARIFICATION")["question"] == complete_so_far


def test_result_selection_is_not_authorized_by_an_unexecuted_pending_request(monkeypatch):
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="followup",
        context_source="prior_result", resolved_question="Show orders for the highest-ranked supplier.",
    ))
    pipeline = MagicMock(side_effect=AssertionError("no result-backed supplier exists"))
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    result = orchestrator.run_adaptive_orchestrator(
        "For the supplier in that result, show its orders.", MagicMock(), MagicMock(),
        prior_status="CLARIFICATION", prior_question="Compare costs by supplier.",
        prior_plan={"pending_analysis": {"question": "Compare costs by supplier."}},
    )
    assert result["answer_status"] == "CLARIFICATION"
    assert result["query_plan"]["requires_result_anchor"]
    assert pending_analysis_context(result["query_plan"], "For the supplier in that result", "CLARIFICATION") is None
    pipeline.assert_not_called()


def test_new_request_does_not_inherit_pending_goal_or_unrelated_retained_rows(monkeypatch):
    question = "Show inventory balances by warehouse."
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="new_request", context_source="none",
    ))
    pipeline = MagicMock(return_value={"error": "sql_validation_failed", "detail": ["test boundary"]})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    plan = {"pending_analysis": {"question": "Compare billed sales in 2012 and 2013."},
            "investigation_state": {"metric": "billed_sales", "dimensions": ["customer"], "tables": ["VBRK"], "time_period": "2012 and 2013"},
            "retained_analytical_context": {"previousSQL": 'SELECT * FROM "VBRK"',
                "previousAnswerStatus": "SUCCESS", "previousPlan": {}, "data": [{"vbeln": "123"}]}}
    orchestrator.run_adaptive_orchestrator(
        question, MagicMock(), MagicMock(), prior_plan=plan, prior_status="CLARIFICATION",
    )
    assert pipeline.call_args.args[0] == question
    assert pipeline.call_args.kwargs["prior_sql"] == ""
    assert pipeline.call_args.args[3].tables == []
    assert pipeline.call_args.args[3].metric == ""
    assert pipeline.call_args.args[3].dimensions == []


def test_compound_new_request_after_pending_clarification_keeps_both_asks(monkeypatch):
    from app.services import sales_order_analysis

    question = "Show the top customers by billed sales. How many sales orders are there?"
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="new_request", context_source="none",
        requested_parts=["Show the top customers by billed sales.", "How many sales orders are there?"],
        understanding_model_called=True,
    ))
    count_fast_path = MagicMock(side_effect=AssertionError("must not discard the billed-sales ranking"))
    monkeypatch.setattr(sales_order_analysis, "try_sales_order_analysis", count_fast_path)
    pipeline = MagicMock(return_value={"error": "sql_validation_failed", "detail": ["test boundary"]})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    pending = {"pending_analysis": {"question": "How do the comparisons change for a defined reporting period?"}}

    orchestrator.run_adaptive_orchestrator(
        question, MagicMock(), MagicMock(),
        prior_question="How do the comparisons change for a defined reporting period?",
        prior_plan=pending, prior_status="CLARIFICATION",
    )

    assert pipeline.call_args.args[0] == question
    assert pipeline.call_args.kwargs["prior_sql"] == ""
    assert pipeline.call_args.args[3].tables == []
    count_fast_path.assert_not_called()


def test_single_part_sales_order_count_keeps_its_governed_fast_path(monkeypatch):
    from app.services import sales_order_analysis, plan_satisfaction

    question = "How many sales orders are there?"
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, requested_parts=[question],
        understanding_model_called=True,
    ))
    result = {
        "answer_status": "SUCCESS", "summary": "There are 12 sales orders.",
        "sql": 'SELECT COUNT(DISTINCT vbeln) FROM "VBAK"', "data": [{"count": 12}],
        "rowCount": 1, "query_plan": {},
    }
    fast_path = MagicMock(return_value=result)
    monkeypatch.setattr(sales_order_analysis, "try_sales_order_analysis", fast_path)
    monkeypatch.setattr(plan_satisfaction, "sql_satisfies_analytical_intent", lambda *a, **k: True)
    pipeline = MagicMock(side_effect=AssertionError("single atomic count should retain its governed path"))
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)

    out = orchestrator.run_adaptive_orchestrator(question, MagicMock(), MagicMock())

    assert out["pipeline"] == "governed_sales_order_count"
    fast_path.assert_called_once()
    pipeline.assert_not_called()


def test_model_understanding_exposes_requested_parts_without_losing_full_goal(monkeypatch):
    seen = {}

    def model(system, user):
        seen["system"] = system
        seen["user"] = user
        return {
            "intent": "analytics",
            "goal": "Rank customers by billed sales and count sales orders.",
            "requires_database": True,
            "requested_parts": [
                "Show the top customers by billed sales.",
                "How many sales orders are there?",
            ],
            "resolved_question": "Show the top customers by billed sales and count the sales orders.",
        }, "test"

    monkeypatch.setattr(understanding, "analyze_json", model)
    result = understanding.understand_turn(
        "Show the top customers by billed sales. How many sales orders are there?",
        capability_context={},
    )

    assert len(result.requested_parts) == 2
    assert "separate items for distinct outputs" in seen["system"]
    assert "Show the top customers by billed sales" in result.resolved_question


def test_api_preserves_pending_plan_even_when_classifier_calls_it_fresh(monkeypatch):
    from fastapi import BackgroundTasks
    from app.api.adaptive_query import _post_query_adaptive_body
    from app.services import adaptive_analyst

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(adaptive_analyst, "orchestrator_enabled", lambda: True)
    runner = MagicMock(return_value={"answer_status": "CLARIFICATION", "mode": "clarification", "sql": "", "data": [], "summary": "Captured"})
    monkeypatch.setattr(adaptive_analyst, "run_adaptive_orchestrator", runner)
    original = "Compare negative sales in 2000 and 2001."
    _post_query_adaptive_body(
        q="Billing document numbers first based on customer", original_question="Billing document numbers first based on customer",
        tableHint=None, overrideSql=None, threadId=None, investigationId=None,
        db=MagicMock(), current_user=None, background_tasks=BackgroundTasks(),
        contextData={"previousQuestion": original, "previousSQL": "", "data": [],
                     "previousAnswerStatus": "CLARIFICATION", "previousPlan": {"last_mode": "clarification"}},
    )
    assert runner.call_args.kwargs["prior_plan"]["pending_analysis"]["question"] == original
    assert runner.call_args.kwargs["prior_status"] == "CLARIFICATION"


def test_understanding_prompt_labels_pending_as_intent_without_claiming_rows(monkeypatch):
    seen = {}
    def model(system, user):
        seen.update(system=system, user=user)
        return {"intent": "analytics", "turn_relation": "clarification_answer", "context_source": "pending_request"}, "test"
    monkeypatch.setattr(understanding, "analyze_json", model)
    result = understanding.understand_turn(
        "By warehouse", prior_question="Compare stock in 2012 and 2013.",
        prior_status="CLARIFICATION", capability_context={},
    )
    assert "Pending analytical request (unexecuted intent" in seen["user"]
    assert "Compare stock in 2012 and 2013." in seen["user"]
    assert "Previous verified result sample" not in seen["user"]
    assert result.turn_relation == "clarification_answer" and result.context_source == "pending_request"


def test_pending_request_reports_model_outage_instead_of_lexical_fallback(monkeypatch):
    monkeypatch.setattr(understanding, "analyze_json", MagicMock(side_effect=TimeoutError()))
    with pytest.raises(RuntimeError, match="pending analytical request"):
        understanding.understand_turn(
            "By supplier for those periods", prior_question="Compare purchasing costs in 2012 and 2013.",
            prior_status="CLARIFICATION", capability_context={},
        )
    pending = {"question": "Compare purchasing costs in 2012 and 2013."}
    result = orchestrator.run_adaptive_orchestrator(
        "By supplier for those periods", MagicMock(), MagicMock(),
        prior_plan={"pending_analysis": pending}, prior_status="CLARIFICATION",
    )
    assert result["failure_class"] == "UNDERSTANDING_MODEL_FAILED"
    assert result["query_plan"]["pending_analysis"] == pending


def test_followup_can_reuse_requested_periods_without_claiming_result_entities(monkeypatch):
    resolved = "Compare total purchasing costs by supplier in 2012 and 2013."
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="followup",
        context_source="prior_request", resolved_question=resolved,
    ))
    pipeline = MagicMock(return_value={"error": "sql_validation_failed"})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    orchestrator.run_adaptive_orchestrator(
        "Use supplier totals for those periods instead.", MagicMock(), MagicMock(),
        prior_question="Compare purchasing costs in 2012 and 2013.", prior_status="CANNOT_ANSWER",
    )
    assert pipeline.call_args.args[0] == resolved


def test_explaining_a_failed_request_does_not_require_a_database_rewrite(monkeypatch):
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="conversation", requires_database=False, turn_relation="followup",
        context_source="prior_request", resolved_question=None,
    ))
    monkeypatch.setattr(understanding, "generate_grounded_response", lambda *a, **k: (
        "The comparison stopped before a verified result was available.", "test"))
    pipeline = MagicMock(side_effect=AssertionError("explanations must not execute SQL"))
    execute = MagicMock(side_effect=AssertionError("explanations must not execute SQL"))
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    result = orchestrator.run_adaptive_orchestrator(
        "What does that error mean?", MagicMock(), execute,
        prior_question="Compare two monetary measures.", prior_status="CANNOT_ANSWER",
    )
    assert result["mode"] == "general_chat"
    assert "verified result" in result["answer"]
    pipeline.assert_not_called()
    execute.assert_not_called()


def test_new_analytical_request_preserves_user_scope_without_invented_rewrite(monkeypatch):
    resolved = "Compare independently aggregated order and invoice net values per order, within the same currency."
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="new_request",
        context_source="none", resolved_question=resolved,
    ))
    pipeline = MagicMock(return_value={"error": "sql_validation_failed"})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    orchestrator.run_adaptive_orchestrator("Compare orders and linked billing values.", MagicMock(), MagicMock())
    assert pipeline.call_args.args[0] == "Compare orders and linked billing values."


def test_analytics_needing_metadata_still_runs_the_analytical_pipeline(monkeypatch):
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, requires_metadata=True,
        turn_relation="new_request", context_source="none",
    ))
    pipeline = MagicMock(return_value={"error": "sql_validation_failed"})
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    result = orchestrator.run_adaptive_orchestrator("Compare the two linked document values.", MagicMock(), MagicMock())
    pipeline.assert_called_once()
    assert result["route"] == "database"


@pytest.mark.parametrize("rewrite", [None, 'SELECT * FROM "VBRK"'])
def test_unresolved_or_sql_shaped_pending_rewrite_cannot_execute_fragment(monkeypatch, rewrite):
    monkeypatch.setattr(understanding, "understand_turn", lambda *a, **k: understanding.TurnUnderstanding(
        intent="analytics", requires_database=True, turn_relation="clarification_answer",
        context_source="pending_request", resolved_question=rewrite,
    ))
    pipeline = MagicMock(side_effect=AssertionError("an unresolved reply must not become SQL"))
    monkeypatch.setattr(orchestrator, "_run_four_stage_or_legacy_sql", pipeline)
    pending = {"question": "Compare billed sales in 2018 and 2019."}
    result = orchestrator.run_adaptive_orchestrator(
        "Yes, use those defaults", MagicMock(), MagicMock(),
        prior_status="CLARIFICATION", prior_plan={"pending_analysis": pending},
    )
    assert result["failure_class"] == "UNDERSTANDING_MODEL_FAILED"
    assert result["query_plan"]["pending_analysis"] == pending
    pipeline.assert_not_called()
