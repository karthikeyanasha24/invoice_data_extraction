"""Catalog follow-ups remain grounded even when every model is unavailable."""
from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst import understanding
from app.services.adaptive_analyst.database_metadata import (
    answer_database_metadata, resolve_metadata_followup, execute_metadata_plan,
)
from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator

SCHEMA = {f"TABLE_{n:03d}": [{"col": "ID", "type": "text"}] for n in range(129)}


@pytest.mark.parametrize("question", ["What does billing mean?", "What does average revenue mean?", "What do purchase orders mean?"])
def test_concept_definition_never_requests_fact_rows(question):
    from app.services.adaptive_nl_sql_hardening import is_general_knowledge_question, question_requires_database
    assert is_general_knowledge_question(question)
    assert not question_requires_database(question)


def unavailable(*_args, **_kwargs):
    error = RuntimeError("model credits exhausted")
    error.code = "credit_balance_exhausted"
    error.status_code = 429
    raise error


@pytest.mark.parametrize("question", ["list those", "show them", "please enumerate those tables", "list all", "show the first 5 of those"])
def test_count_followup_lists_catalog_with_model_down(monkeypatch, question):
    monkeypatch.setattr(understanding, "analyze_json", unavailable)
    prior = answer_database_metadata("How many tables are there?", SCHEMA)
    result = run_adaptive_orchestrator(
        question, MagicMock(), lambda *_: pytest.fail("schema listing must not execute SQL"),
        prior_question="How many tables are there?", prior_plan=prior["query_plan"],
        prior_status="SUCCESS", schema_for_metadata=SCHEMA,
    )
    assert result["answer_status"] == "SUCCESS"
    assert result["mode"] == "database_metadata"
    assert result["meta"]["operation"] == "LIST_TABLES"
    expected = 5 if "5" in question else 129
    assert result["rowCount"] == expected
    assert [r["table"] for r in result["data"]] == sorted(SCHEMA)[:expected]


def test_followup_retains_domain_scope_and_explicit_limit(monkeypatch):
    from app.services.adaptive_analyst import database_metadata as metadata
    monkeypatch.setattr(metadata, "_table_semantics", lambda table: {"domain": "sales" if table == "VBAK" else "purchase", "description": table, "grain": "document"})
    prior = answer_database_metadata("List all sales-domain tables", {"VBAK": [], "EKKO": []})
    plan = resolve_metadata_followup("show those", prior["query_plan"])
    assert plan.domain_filter == "sales"
    assert execute_metadata_plan(plan, {"VBAK": [], "EKKO": []}).value == ["VBAK"]


def test_column_followup_preserves_named_table():
    prior = answer_database_metadata("How many columns in TABLE_000?", SCHEMA)
    plan = resolve_metadata_followup("list those", prior["query_plan"])
    assert plan.table_name == "TABLE_000"
    result = execute_metadata_plan(plan, SCHEMA)
    assert result.rows[0]["column"] == "ID"


@pytest.mark.parametrize("question", ["list those", "show them", "list all"])
def test_missing_metadata_anchor_does_not_invent_global_catalog(question):
    assert resolve_metadata_followup(question) is None
    assert resolve_metadata_followup(question, {"last_mode": "database_analysis"}, "Show top customers") is None


def test_topic_change_closes_catalog_reference():
    prior = answer_database_metadata("How many tables are there?", SCHEMA)["query_plan"]
    prior["recent_turns"] = [
        {"role": "user", "content": "Explain sorting algorithms"},
        {"role": "assistant", "content": "Sorting rearranges items.", "mode": "general_chat"},
    ]
    assert resolve_metadata_followup("list those", prior) is None
    assert resolve_metadata_followup("why did you list those?", prior) is None


def test_api_count_then_list_has_no_model_dependency(monkeypatch):
    import app.api.adaptive_query as api
    from app.services.adaptive_analyst import live_schema, llm_provider
    from app.services.investigation_budget import end_investigation

    monkeypatch.setattr(live_schema, "load_live_schema", lambda *_: (SCHEMA, "live_database"))
    monkeypatch.setattr(api, "_load_schema", lambda: SCHEMA)
    monkeypatch.setattr(understanding, "analyze_json", lambda *_: pytest.fail("No model required"))
    monkeypatch.setattr(llm_provider, "complete_text", lambda *_: pytest.fail("No model required"))
    context = None
    for question in ["how many tables are there", "list those", "count those"]:
        try:
            result = api._post_query_adaptive_body(
                q=question, original_question=question, tableHint=None, contextData=context,
                overrideSql=None, threadId=None, investigationId="metadata-followup-test",
                db=MagicMock(), current_user=type("User", (), {"id": 0, "is_admin": False})(),
            )
            assert result["answer_status"] == "SUCCESS", result["summary"]
            assert result["mode"] == "database_metadata"
            if question == "list those":
                assert result["rowCount"] == 129
            else:
                assert result["data"][0]["table_count"] == 129
            context = {"previousQuestion": question, "previousPlan": result["query_plan"],
                       "previousAnswerStatus": "SUCCESS", "data": result["data"], "previousSQL": ""}
        finally:
            end_investigation()


def test_greeting_quota_failure_is_honest_and_keeps_catalog_context(monkeypatch):
    from app.services.adaptive_analyst import llm_provider
    monkeypatch.setattr(llm_provider, "complete_text", unavailable)
    prior = answer_database_metadata("How many tables are there?", SCHEMA)["query_plan"]
    result = run_adaptive_orchestrator("hai again", MagicMock(), lambda *_: pytest.fail("No SQL"), prior_plan=prior)
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert result["meta"]["service_issue"] == "quota_exhausted"
    assert "Hello!" not in result["answer"]
    assert resolve_metadata_followup("list those", result["query_plan"]).operation == "LIST_TABLES"


def test_generated_greeting_keeps_metadata_scope(monkeypatch):
    from app.services.adaptive_analyst import llm_provider
    monkeypatch.setattr(llm_provider, "complete_text", lambda *_: ("Welcome back.", "test"))
    prior = answer_database_metadata("How many tables are there?", SCHEMA)["query_plan"]
    result = run_adaptive_orchestrator("hai again", MagicMock(), lambda *_: pytest.fail("No SQL"), prior_plan=prior)
    assert result["answer"] == "Welcome back."
    assert result["meta"]["response_model_called"] is True
    assert resolve_metadata_followup("list those", result["query_plan"]).operation == "LIST_TABLES"
