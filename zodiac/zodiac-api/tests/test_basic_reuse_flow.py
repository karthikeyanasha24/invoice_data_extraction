"""Checked reuse runs live SQL; only a miss goes to the existing Agentic route."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.services import basic_rag as rag
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope, set_trusted_scope, reset_trusted_scope
from app.services.basic_sql_answer import run_basic_sql_answer
from app.services.investigation_budget import end_investigation, paid_models_blocked


def test_reuse_button_to_suggestions_to_fresh_rows_after_cold_start(tmp_path, monkeypatch):
    from app.api import adaptive_query as api
    path = "sqlite:///" + str(tmp_path / "reuse.db")
    engine = create_engine(path)
    scope = TrustedAiExecutionScope(user_id=7, sap_access="full")
    question = "total billed sales in 2001"
    sql = "SELECT waerk AS currency, SUM(netwr) AS total_sales FROM VBRK WHERE fkdat LIKE '2001%' GROUP BY waerk"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE VBRK (waerk TEXT, netwr INTEGER, fkdat TEXT)"))
        connection.execute(text("INSERT INTO VBRK VALUES ('USD', 10, '20010101'), ('EUR', 8, '20010101'), ('USD', 999, '20020101')"))
    payload = {"sql": sql, "query_plan": {"effective_question": question}, "agent_primary_result_id": "one",
               "agent_results": [{"id": "one", "kind": "analysis", "source": "business", "sql": sql}]}
    rag.capture_training_reference(payload, engine, scope)
    # Merely answering offers a button, not an automatically approved example.
    assert not rag.load_verified_queries(engine, scope, "business")
    db = MagicMock()
    db.get_bind.return_value = engine
    monkeypatch.setattr(api, "USE_SAP_DB_FOR_AI", True)
    monkeypatch.setattr("app.core.workspace.context.list_assigned_customer_ids", lambda *_: [])
    owner = SimpleNamespace(id=7, is_customer_user=False, is_admin=True)
    other = SimpleNamespace(id=8, is_customer_user=False, is_admin=True)
    body = {"result_id": payload["meta"]["basic_training_reference"]["id"], "question": question}
    assert api.teach_basic_endpoint(body=body, db=db, current_user=owner)["saved"]
    suggestions = api.basic_questions_endpoint(db=db, current_user=owner)
    assert suggestions["questions"] == [question]
    assert "billed sales by year" in suggestions["predefined_questions"]
    assert len(suggestions["database_questions"]) >= 50
    assert "top 5 customers by billed sales in 2000" in suggestions["database_questions"]
    assert api.basic_questions_endpoint(db=db, current_user=other)["questions"] == []
    with pytest.raises(HTTPException) as denied:
        api.teach_basic_endpoint(body=body, db=db, current_user=other)
    assert denied.value.status_code == 403
    engine.dispose()
    engine = create_engine(path)
    examples = rag.load_verified_queries(engine, scope, "business")
    calls = []
    def execute(query):
        assert paid_models_blocked()
        calls.append(query)
        with engine.connect() as connection:
            return {"ok": True, "sql": query, "rows": [dict(row) for row in connection.execute(text(query)).mappings()]}
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent", lambda *_a, **_k: pytest.fail("Reuse must not call a model"))
    first = run_basic_sql_answer(question, execute=execute, prior_examples=examples)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO VBRK VALUES ('USD', 5, '20010601')"))
    second = run_basic_sql_answer(question, execute=execute, prior_examples=examples)
    assert first["data"] == [{"currency": "EUR", "total_sales": 8}, {"currency": "USD", "total_sales": 10}]
    assert second["data"] == [{"currency": "EUR", "total_sales": 8}, {"currency": "USD", "total_sales": 15}]
    assert "15" in second["answer"] and "USD" in second["answer"]
    assert calls == [sql, sql] and second["llm_calls"] == 0
    assert not paid_models_blocked()
    engine.dispose()


@pytest.mark.parametrize("failure", [False, True])
def test_basic_miss_or_failed_sql_uses_normal_agent_with_honest_usage(monkeypatch, failure):
    from app.api import adaptive_query as api
    monkeypatch.setenv("BASIC_ALLOW_PAID_FALLBACK", "true")
    # This test covers the explicitly enabled paid fallback. A developer's
    # local Ollama configuration must not change which route the unit exercises.
    monkeypatch.setattr("app.services.basic_hosted_provider.basic_llm_enabled", lambda: False)
    question = "explain seasonal demand and component shortages"
    sql = "SELECT 1 AS obsolete_column"
    monkeypatch.setattr("app.services.basic_rag.load_verified_queries", lambda *_: [{"question": question, "sql": sql}] if failure else [])
    monkeypatch.setattr("app.services.basic_rag.save_verified_query", lambda *_: pytest.fail("Unreviewed results must not be saved"))
    calls = []
    class Executor:
        def __init__(self, *_a, **_k): self.plans = {}
        def call(self, *_a, **_k):
            assert paid_models_blocked()
            return {"ok": False, "error": "schema changed"}
        def close(self): calls.append("closed")
    monkeypatch.setattr("app.services.analyst_agent.AnalystTools", Executor)
    context = {"previousQuestion": "product costs in 2001"}
    def agent(asked, *_a, **kwargs):
        assert not paid_models_blocked()
        assert asked == question and kwargs["context"] == context
        assert calls == ["closed"]
        calls.append("agent")
        return {"pipeline": "analyst_agent", "mode": "general_chat", "answer_status": "SUCCESS",
                "answer": "A fresh investigation", "llm_calls": 2,
                "meta": {"usage": {"total_tokens": 57}}}
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent", agent)
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=7, sap_access="full"))
    try:
        result = api._post_query_adaptive_body(q=question, original_question=question, tableHint=None,
            contextData=context, overrideSql=None, threadId=None, investigationId=None, db=MagicMock(),
            current_user=SimpleNamespace(id=7), analysis_mode="basic")
        assert calls == ["closed", "agent"]
        assert result["meta"]["basic_fallback"] == ("saved_query_failed" if failure else "no_safe_match")
        assert result["meta"]["credits_used"] is True
        assert result["meta"]["analysis_method"] == "agent"
        assert result["meta"]["usage"]["total_tokens"] == 57
    finally:
        reset_trusted_scope(token)
        end_investigation()


def test_agentic_selection_bypasses_basic_entirely(monkeypatch):
    from app.api import adaptive_query as api
    monkeypatch.setattr("app.services.basic_sql_answer.run_basic_sql_answer", lambda *_a, **_k: pytest.fail("Agentic must not route through Basic"))
    monkeypatch.setattr("app.services.basic_rag.load_verified_queries", lambda *_: pytest.fail("Agentic does not consult Basic memory"))
    calls = []
    def agent(question, *_a, **_k):
        calls.append(question)
        return {"pipeline": "analyst_agent", "mode": "general_chat", "answer_status": "SUCCESS", "answer": "Existing agent", "llm_calls": 1}
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent", agent)
    try:
        result = api._post_query_adaptive_body(q="investigate demand", original_question="investigate demand", tableHint=None,
            contextData=None, overrideSql=None, threadId=None, investigationId=None, db=MagicMock(),
            current_user=SimpleNamespace(id=7), agent_mode=True, analysis_mode="agent")
        assert calls == ["investigate demand"] and result["llm_calls"] == 1
        assert not result.get("meta", {}).get("basic_fallback")
    finally:
        end_investigation()


def test_multistep_reuse_rejects_yesterdays_winner_and_conditional_branch():
    payload = {"query_plan": {"effective_question": "top product and component costs in 2001"},
               "agent_results": [
                   {"kind": "analysis", "source": "business", "sql": "SELECT product FROM products ORDER BY profit DESC LIMIT 1"},
                   {"kind": "analysis", "source": "business", "sql": "SELECT cost FROM components WHERE product = 'OLD_WINNER'"},
               ]}
    assert rag.investigation_steps(payload) == []
    payload["agent_results"][1]["sql"] = "SELECT cost FROM components"
    assert len(rag.investigation_steps(payload)) == 2
    payload["query_plan"]["conditional_request"] = {"when_empty": "another period"}
    assert rag.investigation_steps(payload) == []


def test_teaching_cannot_relabel_one_metric_as_another():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=7, sap_access="full")
    payload = {"sql": "SELECT 10 AS sales", "query_plan": {"effective_question": "total sales in 2001"}}
    rag.capture_training_reference(payload, engine, scope)
    with pytest.raises(ValueError):
        rag.teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], "average profit in 2001")


@pytest.mark.parametrize("question", ["Billing documents in 2001", "Annual sales", "Can you show sales in 2001?"])
def test_reuse_button_accepts_unchanged_question_wording(question):
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=7, sap_access="full")
    payload = {"sql": "SELECT 10 AS sales", "query_plan": {"effective_question": question}}
    rag.capture_training_reference(payload, engine, scope)
    assert rag.teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], question)["saved"]


def test_multi_source_same_sql_keeps_primary_source_and_replays_all_steps():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=7, sap_access="full")
    question = "compare inventory across data sources"
    sql = "SELECT COUNT(*) AS inventory_count FROM inventory"
    payload = {"sql": sql, "query_plan": {"effective_question": question}, "agent_primary_result_id": "app",
               "agent_results": [
                   {"id": "app", "kind": "analysis", "source": "application", "sql": sql},
                   {"id": "sap", "kind": "analysis", "source": "business", "sql": sql},
               ]}
    rag.capture_training_reference(payload, engine, scope)
    rag.teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], question)
    examples = rag.load_basic_examples(engine, scope, True)
    assert len(examples) == 1 and examples[0]["source"] == "application"
    sources = []
    def execute(query, step):
        sources.append(step["source"])
        return {"ok": True, "sql": query, "rows": [{"inventory_count": len(sources)}]}
    result = run_basic_sql_answer(question, execute=execute, prior_examples=examples)
    assert sources == ["application", "business"]
    assert result["data"] == [{"inventory_count": 1}]
    assert result["agent_primary_result_id"] == "result_1"


def test_short_historical_question_can_reuse_its_checked_query():
    sql = "SELECT SUM(cost) AS cogs FROM components"
    assert rag.recall_sql("Show COGS.", [{"question": "Show COGS.", "sql": sql}]) == sql
    assert rag.recall_sql("Show margins.", [{"question": "Show COGS.", "sql": sql}]) == ""


def test_all_saved_suggestions_remain_reusable_beyond_recent_limit():
    from app.services.analyst_drilldown import scope_digest
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=7, sap_access="full")
    rag.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(rag.memory.insert(), [
            {"id": str(index), "user_id": 7, "scope_digest": scope_digest(scope), "source": "business",
             "question": f"sales for customer {index}", "sql": f"SELECT {index} AS sales", "use_count": 1, "updated_at": index}
            for index in range(205)
        ])
    examples = rag.load_basic_examples(engine, scope, True)
    assert len(examples) == 205
    assert rag.recall_sql("sales for customer 0", examples) == "SELECT 0 AS sales"


@pytest.mark.parametrize("status", ["SUCCESS", "CANNOT_ANSWER"])
def test_basic_uses_configured_free_model_on_miss_without_paid_retry(monkeypatch, status):
    from app.api import adaptive_query as api
    from app.services.basic_local_provider import local_agent_active
    monkeypatch.setattr("app.services.basic_hosted_provider.basic_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.basic_hosted_provider.basic_provider", lambda: "groq")
    monkeypatch.setattr("app.services.basic_rag.load_verified_queries", lambda *_: [])
    class Executor:
        def __init__(self, *_a, **_k): self.plans = {}
        def close(self): pass
        def call(self, *_a, **_k): pytest.fail("Unknown question should require investigation")
    monkeypatch.setattr("app.services.analyst_agent.AnalystTools", Executor)
    calls = []
    def agent(question, *_a, **_k):
        assert local_agent_active() and paid_models_blocked()
        calls.append(question)
        return {"pipeline": "analyst_agent", "mode": "general_chat", "answer_status": status,
                "answer": "Free model investigation", "llm_calls": 1}
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent", agent)
    question = "explain seasonal demand and component shortages"
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=7, sap_access="full"))
    try:
        result = api._post_query_adaptive_body(q=question, original_question=question, tableHint=None,
            contextData=None, overrideSql=None, threadId=None, investigationId=None, db=MagicMock(),
            current_user=SimpleNamespace(id=7), analysis_mode="basic")
        assert calls == [question]
        assert result["meta"]["provider"] == "groq" and result["meta"]["credits_used"] is False
        assert not result["meta"].get("basic_fallback")
        assert not paid_models_blocked() and not local_agent_active()
    finally:
        reset_trusted_scope(token)
        end_investigation()


def test_basic_can_disable_paid_agentic_fallback_without_changing_agentic_mode(monkeypatch):
    from app.api import adaptive_query as api

    monkeypatch.setenv("BASIC_ALLOW_PAID_FALLBACK", "false")
    monkeypatch.setattr("app.services.basic_hosted_provider.basic_llm_enabled", lambda: False)
    monkeypatch.setattr("app.services.basic_rag.load_verified_queries", lambda *_: [])
    class Executor:
        def __init__(self, *_a, **_k): self.plans = {}
        def close(self): pass
    monkeypatch.setattr("app.services.analyst_agent.AnalystTools", Executor)
    monkeypatch.setattr("app.services.analyst_agent.run_analyst_agent",
                        lambda *_a, **_k: pytest.fail("Basic must not invoke paid Agentic"))
    question = "explain seasonal demand and component shortages"
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=7, sap_access="full"))
    try:
        result = api._post_query_adaptive_body(q=question, original_question=question,
            tableHint=None, contextData=None, overrideSql=None, threadId=None,
            investigationId=None, db=MagicMock(), current_user=SimpleNamespace(id=7),
            analysis_mode="basic")
        assert result["llm_calls"] == 0
        assert result["meta"]["needs_agent"] is True
        assert result["meta"]["credits_used"] is False
    finally:
        reset_trusted_scope(token)
        end_investigation()
