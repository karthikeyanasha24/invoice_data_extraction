import pytest
from sqlalchemy import create_engine

from app.services.basic_rag import capture_training_reference, teach_verified_question, load_verified_queries, recall_sql
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope


def result():
    return {"sql": 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" WHERE fkdat LIKE \'2001%\' GROUP BY waerk',
        "query_plan": {"effective_question": "total billed sales in 2001"},
        "agent_results": [{"kind": "analysis", "source": "business"}]}


def test_person_can_teach_a_checked_answer_and_recall_after_a_cold_start(tmp_path):
    path = tmp_path / "memory.db"
    engine = create_engine("sqlite:///" + str(path))
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    payload = result()
    capture_training_reference(payload, engine, scope)
    taught = teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], "Please show turnover during 2001")
    assert taught["saved"] and taught["model_calls"] == 0
    engine.dispose()
    cold_engine = create_engine("sqlite:///" + str(path))
    assert recall_sql("Please show turnover during 2001", load_verified_queries(cold_engine, scope, "business")) == payload["sql"]
    cold_engine.dispose()


def test_teaching_is_permission_bound_and_rejects_changed_year():
    engine = create_engine("sqlite://")
    owner = TrustedAiExecutionScope(user_id=1, sap_access="full")
    payload = result()
    capture_training_reference(payload, engine, owner)
    identifier = payload["meta"]["basic_training_reference"]["id"]
    with pytest.raises(ValueError, match="same year"):
        teach_verified_question(engine, owner, identifier, "total sales in 2002")
    with pytest.raises(PermissionError):
        teach_verified_question(engine, TrustedAiExecutionScope(user_id=2, sap_access="full"), identifier, "total sales in 2001")
    assert not load_verified_queries(engine, owner, "business")


def test_compound_investigation_is_taught_and_replayed_without_a_model():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    first = 'SELECT waerk AS currency, SUM(netwr) AS profit FROM "VBRK" WHERE fkdat LIKE \'2001%\' GROUP BY waerk'
    second = 'SELECT wavwr AS cost FROM "VBRP" WHERE fkdat LIKE \'2001%\''
    payload = result()
    payload["query_plan"]["effective_question"] = "show product profits and the component breakdown in 2001"
    payload["sql"] = second
    payload["agent_primary_result_id"] = "result_2"
    payload["agent_results"] = [
        {"id": "result_1", "kind": "analysis", "source": "business", "sql": first, "purpose": "profit"},
        {"id": "result_2", "kind": "analysis", "source": "business", "sql": second, "purpose": "components",
         "analysis_plan": {"strategy": "components", "tables": ["VBRP"]}},
    ]
    capture_training_reference(payload, engine, scope)
    assert payload["meta"]["basic_training_reference"]["queries"] == 2
    taught_question = "please show product profits and component breakdown during 2001"
    taught = teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], taught_question)
    assert taught["queries"] == 2 and taught["model_calls"] == 0
    saved = load_verified_queries(engine, scope, "business")[0]
    assert [step["sql"] for step in saved["steps"]] == [first, second]
    assert saved["analysis_plan"]["strategy"] == "components"
    assert recall_sql("profits and component breakdown in 2002", [saved]) == ""

    from app.services.basic_sql_answer import run_basic_sql_answer
    calls = []
    def execute(sql, step=None):
        calls.append((sql, step["purpose"], step["checked_investigation"]))
        column = "profit" if "profit" in step["purpose"] else "cost"
        return {"ok": True, "sql": sql, "rows": [{column: 5}], "source": "business"}
    replay = run_basic_sql_answer(taught_question, execute=execute, prior_examples=[saved])
    assert replay["llm_calls"] == 0 and replay["answer_status"] == "SUCCESS"
    assert "2 checked queries" in replay["answer"]
    assert [item["purpose"] for item in replay["agent_results"]] == ["profit", "components"]
    assert len(calls) == 2 and all(item[2] for item in calls)


def test_incomplete_compound_is_not_taught_as_a_partial_answer():
    engine = create_engine("sqlite://")
    payload = result()
    payload["agent_results"].append({"kind": "analysis", "source": "business"})
    capture_training_reference(payload, engine, TrustedAiExecutionScope(user_id=1, sap_access="full"))
    assert "meta" not in payload


def test_teaching_retains_verified_cross_source_plan():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    payload = result()
    payload["agent_results"][0]["analysis_plan"] = {"strategy": "identified_values", "tables": ["VBRK", "VBAK"], "fields": []}
    capture_training_reference(payload, engine, scope)
    teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], "total revenue in 2001")
    assert load_verified_queries(engine, scope, "business")[0]["analysis_plan"] == payload["agent_results"][0]["analysis_plan"]


def test_teaching_rejects_changed_named_filter():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    payload = result()
    payload["query_plan"]["effective_question"] = "billed sales for Germany in 2001"
    capture_training_reference(payload, engine, scope)
    with pytest.raises(ValueError, match="named filters"):
        teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], "sales for France in 2001")


def test_teaching_rejects_a_total_that_mixes_billing_currencies():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=1, sap_access="full")
    payload = result()
    payload["sql"] = 'SELECT SUM(netwr) AS total_sales FROM "VBRK" WHERE fkdat LIKE \'2001%\''
    capture_training_reference(payload, engine, scope)
    with pytest.raises(ValueError, match="mixes currencies"):
        teach_verified_question(engine, scope, payload["meta"]["basic_training_reference"]["id"], "total billed sales in 2001")


def test_basic_api_restores_cached_analysis_plan_without_model_calls(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.api import adaptive_query as api
    from app.services.investigation_budget import end_investigation
    from app.services.adaptive_trusted_scope import set_trusted_scope, reset_trusted_scope
    question = "compare billed sales and order values in 2001"
    sql = 'SELECT 1 AS billing_value, 2 AS order_value'
    plan = {"strategy": "independent_aggregates", "tables": ["VBRK", "VBAK"]}
    monkeypatch.setattr("app.services.basic_rag.load_verified_queries", lambda *_: [{"question": question, "sql": sql, "analysis_plan": plan}])
    monkeypatch.setattr("app.services.basic_rag.save_verified_query", lambda *_: True)
    monkeypatch.setattr("app.services.basic_rag.capture_training_reference", lambda *_: None)
    monkeypatch.setattr("app.services.analyst_drilldown.capture_result", lambda *_: None)
    calls = []
    class Executor:
        def __init__(self, *_a, **_k): self.plans = {}
        def call(self, name, arguments):
            assert self.plans[arguments["source"]] == plan
            calls.append(arguments)
            return {"ok": True, "sql": sql, "rows": [{"billing_value": 1, "order_value": 2}], "analysis_plan": plan}
        def close(self): pass
    monkeypatch.setattr("app.services.analyst_agent.AnalystTools", Executor)
    monkeypatch.setattr("app.services.analyst_agent._analysis_issues", lambda *_: [])
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=1, sap_access="full"))
    try:
        response = api._post_query_adaptive_body(q=question, original_question=question, tableHint=None,
            contextData=None, overrideSql=None, threadId=None, investigationId=None, db=MagicMock(),
            current_user=SimpleNamespace(id=1), analysis_mode="basic")
        assert response["answer_status"] == "SUCCESS" and response["llm_calls"] == 0
        assert response["agent_results"][0]["analysis_plan"] == plan
        assert len(calls) == 1
    finally:
        reset_trusted_scope(token)
        end_investigation()
