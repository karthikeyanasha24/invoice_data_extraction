"""Scripted model decisions exercise the real loop and database boundaries."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text

from app.services import analyst_agent as agent
from app.services.analyst_agent_sql import validate_agent_sql, enforce_agent_user_scope, queryable_schema
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope, set_trusted_scope, reset_trusted_scope
from app.services.investigation_budget import begin_investigation, end_investigation, cancel_investigation

SCHEMA = {
    "VBRK": [{"col": "vbeln", "type": "text"}, {"col": "netwr", "type": "text"}, {"col": "waerk", "type": "text"}],
    "KNA1": [{"col": "kunnr", "type": "text"}, {"col": "name1", "type": "text"}],
    "sat_documents": [{"col": "id", "type": "integer"}, {"col": "user_id", "type": "integer"}, {"col": "status", "type": "text"}],
    "users": [{"col": "id", "type": "integer"}, {"col": "password_hash", "type": "text"}],
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx.Client, "send", lambda *_a, **_k: pytest.fail("Tests must not contact external models"))
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (SCHEMA, "live_database_metadata"))
    yield
    end_investigation()


def tool(name, arguments, call_id="call_1"):
    if name == "describe_tables":
        arguments = {"column_filter": None, **arguments}
    return SimpleNamespace(output=[{"type": "reasoning", "id": "reasoning_1", "encrypted_content": "opaque-reasoning", "summary": []},
                                   {"type": "function_call", "call_id": call_id, "name": name, "arguments": json.dumps(arguments)}], output_text="")


def final(answer, kind="conversation", result_ids=None):
    body = {"kind": kind, "answer": answer, "summary": answer, "result_ids": result_ids or [], "followups": []}
    return SimpleNamespace(output=[{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(body)}]}], output_text=json.dumps(body))


def scripted(monkeypatch, responses):
    inputs = []
    iterator = iter(responses)
    def respond(**kwargs):
        inputs.append(json.loads(json.dumps(kwargs["input"])))
        return next(iterator)
    monkeypatch.setattr(agent, "create_agent_response", respond)
    return inputs


def run(question="Hello", execute=None, **kwargs):
    return agent.run_analyst_agent(question, MagicMock(), execute or MagicMock(), schema_loader=lambda: SCHEMA, **kwargs)


def test_general_conversation_needs_no_database_tools(monkeypatch):
    scripted(monkeypatch, [final("Hello!"), final("An invoice is a request for payment.")])
    execute = MagicMock(side_effect=AssertionError("No SQL needed"))
    assert run("Hai", execute)["answer"] == "Hello!"
    result = run("What is an invoice?", execute)
    assert result["mode"] == "general_chat" and result["query_plan"]["agent_trace"] == []
    execute.assert_not_called()


def test_table_count_uses_tool_and_preserves_reasoning_items(monkeypatch):
    inputs = scripted(monkeypatch, [tool("list_tables", {"source": "business", "name_filter": None, "include_names": False, "limit": None}),
                                    final("There are 4 tables.", "metadata", ["result_1"])])
    result = run("How many tables are there?")
    assert result["answer_status"] == "SUCCESS"
    assert result["data"] == [{"table_count": 4}]
    assert inputs[1][-1]["type"] == "function_call_output"
    assert any(item.get("type") == "reasoning" for item in inputs[1])
    assert result["meta"]["tool_calls"] == 1


def test_schema_snapshot_is_disclosed_in_final_answer(monkeypatch):
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (SCHEMA, "schema_snapshot"))
    scripted(monkeypatch, [tool("list_tables", {"source": "business", "name_filter": None, "include_names": False, "limit": None}),
                           final("There are 4 tables in the snapshot.", "metadata", ["result_1"])])
    result = run("How many tables are there?")
    assert result["answer_status"] == "SUCCESS"
    assert "live catalog could not be verified" in result["answer"]


def test_followup_reaches_model_with_prior_context_and_preferences(monkeypatch):
    inputs = scripted(monkeypatch, [tool("list_tables", {"source": "business", "name_filter": None, "include_names": True, "limit": None}),
                                    final("Here are those tables.", "metadata", ["result_1"])])
    context = {"previousQuestion": "How many tables are there?", "previousAnswerStatus": "SUCCESS", "data": [{"table_count": 4}],
               "previousPlan": {"recent_turns": [{"role": "user", "content": "Please answer in Spanish from now on"},
                                                {"role": "assistant", "content": "Hay cuatro tablas.", "mode": "database_metadata"}]}}
    result = run("list those", context=context)
    assert "How many tables" in str(inputs[0]) and "Spanish" in str(inputs[0])
    assert result["rowCount"] == 4


def test_sql_error_returns_feedback_then_agent_revises_query(monkeypatch):
    inputs = scripted(monkeypatch, [
        tool("describe_tables", {"source": "business", "tables": ["VBRK"]}),
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT nonexistent FROM "VBRK"', "purpose": "Inspect billing documents"}, "bad"),
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT vbeln FROM "VBRK"', "purpose": "Inspect billing documents"}, "good"),
        final("Found two billing documents.", "analysis", ["result_2"]),
    ])
    execute = MagicMock(return_value=[{"vbeln": "A"}, {"vbeln": "B"}])
    result = run("Show billing documents", execute)
    assert result["answer_status"] == "SUCCESS"
    execute.assert_called_once()
    assert '"vbeln"' in result["sql"]
    error = json.loads(inputs[2][-1]["output"])
    assert error["ok"] is False and "nonexistent" in error["error"]
    assert [step["status"] for step in result["query_plan"]["agent_trace"]] == ["completed", "error", "completed"]


def test_reason_request_continues_after_header_query_and_does_not_invent_a_cause(monkeypatch):
    inputs = scripted(monkeypatch, [
        tool('run_readonly_sql', {'source': 'business', 'sql': 'SELECT vbeln, netwr FROM "VBRK"',
                                  'purpose': 'Inspect the invoice amount'}),
        final('A special discount caused the difference.', 'analysis', ['result_1']),
    ])
    result = run('Why does this invoice have this amount?', MagicMock(return_value=[{'vbeln': 'B1', 'netwr': '12.50'}]))
    assert len(inputs) == 2
    assert 'reason' in inputs[1][-1]['content']
    assert result['answer_status'] == 'SUCCESS'
    assert 'special discount' not in result['answer']
    assert 'does not establish its cause' in result['answer']
    assert result['data'] == [{'vbeln': 'B1', 'netwr': '12.50'}]


def test_database_execution_error_can_be_repaired_in_same_turn(monkeypatch):
    inputs = scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT CAST(netwr AS NUMERIC) AS amount FROM "VBRK"', "purpose": "Inspect billed amounts"}),
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT netwr FROM "VBRK"', "purpose": "Inspect billed amounts"}, "repair"),
        final("The document value is 12.5.", "analysis", ["result_1"]),
    ])
    execute = MagicMock(side_effect=[RuntimeError("Invalid numeric text"), [{"netwr": "12.5"}]])
    result = run("Show billing document values", execute)
    assert result["answer_status"] == "SUCCESS" and execute.call_count == 2
    assert "Invalid numeric" in inputs[1][-1]["output"]


def test_compound_request_preserves_two_successful_result_sets(monkeypatch):
    scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT COUNT(*) AS documents FROM "VBRK"', "purpose": "Count billing documents"}),
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT COUNT(*) AS customers FROM "KNA1"', "purpose": "Count customer records"}, "customers"),
        final("There are 12 documents and 5 customers.", "analysis", ["result_1", "result_2"]),
    ])
    result = run("Count billing documents and customer records", MagicMock(side_effect=[[{"documents": 12}], [{"customers": 5}]]))
    assert result["answer_status"] == "SUCCESS" and len(result["agent_results"]) == 2
    assert result["agent_primary_result_id"] == "result_2"


def test_final_answer_cannot_reference_nonexistent_results(monkeypatch):
    scripted(monkeypatch, [final("Revenue is 999.", "analysis", ["made_up"])] * 3)
    result = run("Show revenue")
    assert result["answer_status"] == "CANNOT_ANSWER" and not result["data"]
    assert result["failure_class"] == "AGENT_VALIDATION_FAILED"


def test_general_answer_cannot_replace_required_database_evidence(monkeypatch):
    scripted(monkeypatch, [final("Your total sales are 999.")] * 3)
    result = run("What were our total sales in 2000?")
    assert result["answer_status"] == "CANNOT_ANSWER"


def test_unknown_tools_and_extra_identity_arguments_are_rejected():
    tools = agent.AnalystTools(MagicMock(), MagicMock(), lambda: SCHEMA)
    assert tools.call("shell", {"command": "anything"})["ok"] is False
    assert tools.call("run_readonly_sql", {"source": "business", "sql": "SELECT 1", "purpose": "test", "user_id": 2})["ok"] is False


def test_tool_and_decision_limits_stop_an_infinite_loop(monkeypatch):
    scripted(monkeypatch, [tool("calculate", {"expression": "2 + 2"})] * 14)
    result = run("Compute 2 + 2")
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert result["meta"]["error_type"] == "ValueError"
    assert len(result["query_plan"]["agent_trace"]) == 14
    assert result["query_plan"]["agent_trace"][-1]["status"] == "cached"


def test_cancellation_prevents_any_model_or_tool_call(monkeypatch):
    model = MagicMock(side_effect=AssertionError("Cancelled"))
    monkeypatch.setattr(agent, "create_agent_response", model)
    budget = begin_investigation("test", request_id="agent-cancel-test")
    cancel_investigation(budget.request_id)
    result = run()
    assert result["answer_status"] == "CANCELLED"
    model.assert_not_called()


def test_provider_quota_does_not_become_canned_chat_success(monkeypatch):
    error = RuntimeError("provider credits exhausted")
    error.code, error.status_code = "credit_balance_exhausted", 429
    monkeypatch.setattr(agent, "create_agent_response", MagicMock(side_effect=error))
    result = run("hai again")
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert result["meta"]["service_issue"] == "quota_exhausted"
    assert agent.create_agent_response.call_count == 1
    assert not result["sql"] and "Hello" not in result["answer"]
    assert run("2 plus 2")["answer"].endswith("= 4")
    assert run("How many tables are there?")["data"] == [{"table_count": 4}]


@pytest.mark.parametrize('error', [
    agent.AnalystResourceLimit('Model-call budget reached'),
    agent.AnalystResourceLimit('Token budget reached'),
    agent.AnalystResponseIncomplete('The model reached its response limit'),
])
def test_analysis_limits_after_tools_are_not_provider_outages(monkeypatch, error):
    responses = iter([tool('describe_tables', {'source': 'business', 'tables': ['VBRK']})])
    def respond(**_):
        try:
            return next(responses)
        except StopIteration:
            raise error
    monkeypatch.setattr(agent, 'create_agent_response', respond)
    execute = MagicMock()
    result = run('Compare invoice 0090010427 with its order', execute)
    assert result['failure_class'] == 'ANALYSIS_LIMIT_REACHED'
    assert result['meta']['failure_class'] == 'ANALYSIS_LIMIT_REACHED'
    assert 'service_issue' not in result['meta']
    assert result['query_plan']['agent_trace'][0]['status'] == 'completed'
    assert not result['data']
    assert 'unavailable' not in result['answer']
    execute.assert_not_called()


def test_analysis_limit_answers_from_executed_sql(monkeypatch):
    schema = {"VBRK": SCHEMA["VBRK"] + [{"col": "fkdat", "type": "text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema, "live_database_metadata"))
    responses = iter([
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT vbeln FROM "VBRK"', "purpose": "Inspect billing documents"}),
    ])
    def respond(**_):
        try:
            return next(responses)
        except StopIteration:
            raise agent.AnalystResourceLimit("Model-call budget reached")
    monkeypatch.setattr(agent, "create_agent_response", respond)
    result = run("Show billing documents in 2000", MagicMock(return_value=[{"vbeln": "0090010427"}]))
    assert result["answer_status"] == "SUCCESS"
    assert result["data"] == [{"vbeln": "0090010427"}]
    assert result["meta"].get("analysis_limit_recovered") is True
    assert result.get("failure_class") != "ANALYSIS_LIMIT_REACHED"
    assert "unavailable" not in result["answer"]


def test_incomplete_response_does_not_mark_provider_unavailable(monkeypatch):
    from app.services import analyst_agent_provider as provider
    import openai
    monkeypatch.setattr('app.services.basic_local_provider.local_agent_active', lambda: False)
    monkeypatch.setattr(provider, '_openai_key', lambda: 'test-key')
    monkeypatch.setattr(provider, '_provider_available', lambda _: True)
    failed = MagicMock()
    monkeypatch.setattr(provider, '_provider_failed', failed)
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(status='incomplete', usage=None)
    monkeypatch.setattr(openai, 'OpenAI', lambda **_: client)
    with pytest.raises(provider.AnalystResponseIncomplete):
        provider.create_agent_response(instructions='Test', input=[], tools=[], output_schema={})
    failed.assert_not_called()


def test_tool_output_compaction_always_remains_valid_json():
    result = {"ok": True, "id": "r", "rows": [{"large": "x" * 5000} for _ in range(200)]}
    compact = json.loads(agent._model_evidence(result))
    assert compact["ok"] is True and compact["model_sample_truncated"] is True
    assert len(compact["rows"]) < 200


def test_catalog_fallback_timeout_returns_structured_failure(monkeypatch):
    from app.services.investigation_budget import InvestigationTimeout
    monkeypatch.setattr(agent, "create_agent_response", MagicMock(side_effect=RuntimeError("provider unavailable")))
    monkeypatch.setattr(agent.AnalystTools, "schema", MagicMock(side_effect=InvestigationTimeout("RETRIEVING_SCHEMA", 120)))
    result = run("How many tables are there?")
    assert result["answer_status"] == "TIMEOUT"
    assert result["pipeline"] == "analyst_agent"
    assert not result["data"] and result["query_plan"]["agent_trace"] == []


@pytest.mark.parametrize("sql", [
    'DELETE FROM "VBRK"', 'SELECT * FROM "VBRK"; DROP TABLE "VBRK"',
    'WITH x AS (DELETE FROM "VBRK" RETURNING *) SELECT * FROM x',
    'SELECT * INTO stolen FROM "VBRK"', 'SELECT * FROM "VBRK" FOR UPDATE',
    "SELECT pg_read_file('/etc/passwd') FROM VBRK", "SELECT set_config('x','y',false) FROM VBRK",
    "SELECT my_side_effect() FROM VBRK", 'SELECT * FROM information_schema.tables',
    'SELECT password_hash FROM users', 'SELECT nonexistent FROM VBRK',
    'SELECT * FROM another_database.public.VBRK',
])
def test_unsafe_or_unavailable_sql_is_blocked_before_execution(sql):
    with pytest.raises(Exception):
        validate_agent_sql(sql, SCHEMA)


def test_valid_cte_and_star_are_checked_against_safe_columns():
    schema = {"VBRK": SCHEMA["VBRK"] + [{"col": "api_key", "type": "text"}]}
    sql, tables = validate_agent_sql('WITH x AS (SELECT * FROM VBRK) SELECT * FROM x', schema)
    assert tables == ["VBRK"] and "api_key" not in sql
    assert "LIMIT 201" in sql
    assert "users" not in queryable_schema(SCHEMA)


@pytest.mark.parametrize("sql", [
    'SELECT id FROM sat_documents WHERE user_id = 2 OR status = \'ok\'',
    'SELECT id FROM sat_documents UNION ALL SELECT id FROM sat_documents WHERE user_id = 2',
    'WITH x AS (SELECT * FROM sat_documents) SELECT id FROM x',
    'SELECT a.id FROM sat_documents a JOIN sat_documents b ON a.id = b.id',
])
def test_ownership_filter_survives_or_union_cte_and_join(sql):
    safe, _ = validate_agent_sql(sql, SCHEMA)
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=1))
    try:
        scoped, params = enforce_agent_user_scope(safe, SCHEMA)
    finally:
        reset_trusted_scope(token)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sat_documents (id INTEGER, user_id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO sat_documents VALUES (11,1,'ok'),(22,2,'ok')"))
        rows = connection.execute(text(scoped), params).fetchall()
    assert rows and all(row[0] == 11 for row in rows)


def test_application_sql_requires_authenticated_scope():
    sql, _ = validate_agent_sql("SELECT id FROM sat_documents", SCHEMA)
    with pytest.raises(PermissionError):
        enforce_agent_user_scope(sql, SCHEMA)


def test_actual_executor_sets_readonly_and_fetches_bounded_rows(monkeypatch):
    monkeypatch.setattr('app.services.analyst_agent_sql.get_trusted_scope',lambda:TrustedAiExecutionScope(user_id=1,sap_access='full'))
    from app.api import adaptive_query as api
    monkeypatch.setattr(api, "apply_statement_timeout", lambda *_a, **_k: None)
    budget = begin_investigation("Show billing documents")
    budget.diagnostics.update(agent_read_only=True, agent_schema=SCHEMA, agent_max_rows=201)
    db = MagicMock()
    result = MagicMock()
    result.keys.return_value = ["vbeln"]
    result.fetchmany.return_value = [("A",)]
    db.execute.return_value = result
    assert api._execute_sql(db, 'SELECT vbeln FROM "VBRK"', "Show billing documents") == [{"vbeln": "A"}]
    assert str(db.execute.call_args_list[0].args[0]) == "SET TRANSACTION READ ONLY"
    result.fetchmany.assert_called_once_with(201)
    result.fetchall.assert_not_called()


def test_public_endpoint_runs_agent_by_default(monkeypatch):
    from app.api import adaptive_query as api
    runner = MagicMock(return_value={"answer_status": "SUCCESS", "mode": "general_chat", "answer": "Hello.", "summary": "Hello.", "data": [], "rowCount": 0, "pipeline": "analyst_agent"})
    monkeypatch.delenv("AI_ANALYST_AGENT_ENABLED", raising=False)
    monkeypatch.setattr(agent, "run_analyst_agent", runner)
    result = api.post_query_adaptive(question="What is an invoice?", db=MagicMock(), current_user=None,
                                    tableHint=None, contextData=None, overrideSql=None, threadId=None,
                                    investigationId=None, conversationHistory=None, newQuestion=False)
    assert result["pipeline"] == "analyst_agent"
    runner.assert_called_once()


def test_responses_transport_uses_tools_stateless_reasoning_and_bounded_retries(monkeypatch):
    from app.services import analyst_agent_provider as provider
    import openai
    response = SimpleNamespace(status="completed", output=[], output_text="{}")
    client = MagicMock()
    client.responses.create.return_value = response
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(openai, "OpenAI", factory)
    monkeypatch.setattr(provider, "_openai_key", lambda: "synthetic-test-key")
    monkeypatch.setattr(provider, "_provider_available", lambda _: True)
    monkeypatch.setenv("AI_ANALYST_AGENT_MODEL", "gpt-6-astra")
    result = provider.create_agent_response(instructions="test", input=[], tools=agent._TOOLS, output_schema=agent._FINAL_SCHEMA)
    assert result is response
    args = client.responses.create.call_args.kwargs
    assert args["store"] is False and args["parallel_tool_calls"] is False
    assert args["model"] == "gpt-6-astra" and args["include"] == ["reasoning.encrypted_content"]
    assert args["text"]["format"]["strict"] is True
    assert factory.call_args.kwargs["max_retries"] == 0


def test_incomplete_model_response_is_not_accepted(monkeypatch):
    from app.services import analyst_agent_provider as provider
    import openai
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(status="incomplete", output_text="partial")
    monkeypatch.setattr(openai, "OpenAI", lambda **_: client)
    monkeypatch.setattr(provider, "_openai_key", lambda: "synthetic-test-key")
    monkeypatch.setattr(provider, "_provider_available", lambda _: True)
    monkeypatch.setattr(provider, "_provider_failed", MagicMock())
    with pytest.raises(provider.AnalystResponseIncomplete, match="[Pp]artial answers"):
        provider.create_agent_response(instructions="test", input=[], tools=[], output_schema=agent._FINAL_SCHEMA)


def test_transient_timeout_retries_then_answers(monkeypatch):
    from app.services import analyst_agent_provider as provider
    import openai
    response = SimpleNamespace(status="completed", output=[], output_text="{}")
    client = MagicMock()
    client.responses.create.side_effect = [TimeoutError("timed out"), response]
    monkeypatch.setattr(openai, "OpenAI", lambda **_: client)
    monkeypatch.setattr("app.services.basic_local_provider.local_agent_active", lambda: False)
    monkeypatch.setattr(provider, "_openai_key", lambda: "synthetic-test-key")
    monkeypatch.setattr(provider, "_provider_available", lambda _: True)
    recovered = MagicMock()
    failed = MagicMock()
    monkeypatch.setattr(provider, "_provider_recovered", recovered)
    monkeypatch.setattr(provider, "_provider_failed", failed)
    monkeypatch.setattr(provider.time, "sleep", lambda *_a, **_k: None)
    result = provider.create_agent_response(instructions="test", input=[], tools=[], output_schema=agent._FINAL_SCHEMA)
    assert result is response
    assert client.responses.create.call_count == 2
    recovered.assert_called_once_with("openai")
    failed.assert_not_called()


def test_final_validation_feedback_triggers_a_new_tool_query(monkeypatch):
    schema = {"VBRK": SCHEMA["VBRK"] + [{"col": "fkdat", "type": "text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema, "live_database_metadata"))
    inputs = scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT vbeln FROM VBRK', "purpose": "Inspect billing documents"}),
        final("These are the 2000 billing documents.", "analysis", ["result_1"]),
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT vbeln FROM VBRK WHERE fkdat LIKE '2000%'", "purpose": "Inspect billing documents in 2000"}, "correct_period"),
        final("These are the 2000 billing documents.", "analysis", ["result_2"]),
    ])
    result = run("Show billing documents in 2000", MagicMock(return_value=[{"vbeln": "A"}]))
    assert result["answer_status"] == "SUCCESS"
    assert "2000%" in result["sql"]
    assert "Application validation feedback" in str(inputs[1])


def test_general_chat_does_not_hide_retained_database_context(monkeypatch):
    inputs = scripted(monkeypatch, [final("I can continue that analysis.")])
    run("Can you explain that?", context={"previousQuestion": "Hi", "previousPlan": {
        "retained_analytical_context": {"previousQuestion": "Top customers", "previousSQL": 'SELECT kunnr FROM "KNA1"',
                                        "previousAnswerStatus": "SUCCESS", "data": [{"kunnr": "C1"}]}}})
    assert 'SELECT kunnr' in str(inputs[0]) and 'C1' in str(inputs[0])


def test_tool_purpose_is_not_parsed_as_a_second_user_request(monkeypatch):
    schema = {"VBRK": SCHEMA["VBRK"] + [{"col":"mandt","type":"text"}, {"col":"kunag","type":"text"}],
              "KNA1": SCHEMA["KNA1"] + [{"col":"mandt","type":"text"}, {"col":"land1","type":"text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema,"live_database_metadata"))
    sql = '''SELECT h.waerk AS currency,c.land1 AS country,SUM(CAST(h.netwr AS NUMERIC)) AS billed_sales
             FROM VBRK h LEFT JOIN KNA1 c ON h.mandt=c.mandt AND LPAD(h.kunag,10,'0')=LPAD(c.kunnr,10,'0')
             GROUP BY h.waerk,c.land1 ORDER BY billed_sales DESC LIMIT 10'''
    scripted(monkeypatch,[tool("run_readonly_sql",{"source":"business","sql":sql,"purpose":"Rank top 10 sold-to customer countries; do not group by customer"}),
                          final("Here are the highest billed sales by country.","analysis",["result_1"])])
    execute = MagicMock(return_value=[{"currency":"USD","country":"US","billed_sales":12.5}])
    result = run("Show the highest sales by country",execute)
    assert result["answer_status"] == "SUCCESS"
    assert execute.call_args.args[2] == ""


def test_decision_limit_uses_last_verified_query(monkeypatch):
    scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT vbeln FROM "VBRK"', "purpose": "List billing documents"}, f"c{i}")
        for i in range(14)
    ])
    result = run("Show billing documents", MagicMock(return_value=[{"vbeln": "A"}]))
    assert result["answer_status"] == "SUCCESS"
    assert result["meta"].get("evidence_fallback") is True
    assert result["data"] == [{"vbeln": "A"}]


def test_verified_sql_returns_without_another_model_turn(monkeypatch):
    inputs = scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": 'SELECT vbeln FROM "VBRK"', "purpose": "List billing documents"}),
        final("Document A is in the connected billing data.", "analysis", ["result_1"]),
    ])
    result = run("Show billing documents", MagicMock(return_value=[{"vbeln": "A"}]))
    assert result["answer_status"] == "SUCCESS"
    assert result["meta"].get("evidence_fallback") is True
    assert len(inputs) == 1
    assert result["data"] == [{"vbeln": "A"}]
    assert result["meta"]["agent_turns"] == 1


def test_short_followup_keeps_prior_customer_and_replaces_year():
    prior = "Did the insurance company in 2004 have any sales?"
    assert "show those billing documents" in agent._scope_question("show those billing documents", prior)
    changed = agent._scope_question("what about 2000", prior)
    assert "2000" in changed and "2004" not in changed
    assert "insurance company" in changed.lower()


@pytest.mark.parametrize("followup", ["Break down by country", "Only negative amounts", "Also include industry"])
def test_followup_keeps_the_actual_modifier(followup):
    prior = "Top 10 customers by billed sales"
    scope = agent._scope_question(followup, prior)
    assert prior in scope and followup in scope


def test_short_new_topic_does_not_inherit_customer_or_period():
    assert agent._scope_question("What can you do?", "Insurance Company sales in 2004") == "What can you do?"
    scope = agent._scope_question("Compare 2000 with 2001 for those customers", "Top customers in 2004")
    assert "2000" in scope and "2001" in scope


def test_shape_validation_error_returns_feedback_instead_of_crashing(monkeypatch):
    monkeypatch.setattr("app.services.plan_satisfaction.result_matches_analytical_intent",
                        lambda rows, *_a, **_k: [] if rows and "amount" in rows[0] else ["sales measure missing from result columns"])
    inputs = scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT vbeln FROM VBRK", "purpose": "Inspect documents"}),
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT netwr AS amount FROM VBRK", "purpose": "Read amounts"}, "repair"),
    ])
    execute = MagicMock(side_effect=[[{"vbeln": "A"}], [{"amount": 42}]])
    result = run("Show billing amounts", execute)
    assert result["answer_status"] == "SUCCESS"
    assert result["data"] == [{"amount": 42}]
    assert result["meta"]["validation_rejects"] == 1
    assert "sales measure missing" in str(inputs[1])


def test_small_aggregate_answer_displays_zero_count_and_null_amount():
    answer = agent._answer_from_analysis("Any sales?", {"rows": [{"billing_documents": 0, "billed_sales": None}]})
    assert "billing documents" in answer and "| 0 | Not available |" in answer
    assert "No matching records" not in answer


def test_empty_result_summary_preserves_the_verified_empty_answer(monkeypatch):
    scripted(monkeypatch, [tool("run_readonly_sql", {"source": "business", "sql": "SELECT vbeln FROM VBRK", "purpose": "Read billing documents"})])
    result = run("Show billing documents", MagicMock(return_value=[]))
    assert result["answer_status"] == "SUCCESS_EMPTY"
    assert result["summary"] == result["answer"]
    assert "No matching records" in result["summary"]


def test_profit_fallback_names_the_cost_basis_without_an_extra_model_turn():
    answer = agent._answer_from_analysis("Highest profits", {"rows": [{"gross_profit": 30}], "sql": "SELECT netwr-wavwr FROM vbrp"})
    assert "vbrp.wavwr" in answer and "gross-profit proxy" in answer


def test_multiple_selected_queries_do_not_bypass_primary_validation():
    tools = agent.AnalystTools(MagicMock(), MagicMock(), lambda: SCHEMA)
    tools.save([{"vbeln": "A"}], kind="analysis", source="business", sql='SELECT vbeln FROM "VBRK"')
    tools.save([{"vbeln": "B"}], kind="analysis", source="business", sql='SELECT vbeln FROM "VBRK"')
    with pytest.raises(ValueError, match="does not satisfy"):
        agent._final_result("Show billing documents in 2000", {
            "kind": "analysis", "answer": "Here are the documents.", "summary": "Documents",
            "result_ids": ["result_1", "result_2"], "followups": [],
        }, tools, agent.InvestigationState(), 1)


def test_conditional_empty_period_does_not_finish_before_available_years(monkeypatch):
    schema = {"VBRK": SCHEMA["VBRK"] + [{"col": "fkdat", "type": "text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema, "live_database_metadata"))
    inputs = scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT vbeln FROM VBRK WHERE fkdat LIKE '2005%'", "purpose": "Check the requested year"}),
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT SUBSTRING(fkdat,1,4) AS sales_year, COUNT(DISTINCT vbeln) AS billing_documents FROM VBRK GROUP BY SUBSTRING(fkdat,1,4)", "purpose": "Find available years"}, "years"),
        final("There are no matching documents in 2005. The available year is 2000 with 1 document.", "analysis", ["result_1", "result_2"]),
    ])
    result = run("What about 2005, if it is empty which years have billing documents?",
                 MagicMock(side_effect=[[], [{"sales_year": "2000", "billing_documents": 1}]]),
                 context={"previousQuestion": "Show billing documents in 2004"})
    assert result["answer_status"] == "SUCCESS"
    assert len(inputs) == 3 and len(result["agent_results"]) == 2
    assert "second part" in str(inputs[1])
    assert result["query_plan"]["conditional_request"]["when_empty"]


def test_conditional_final_cannot_claim_completion_with_only_empty_first_step():
    tools = agent.AnalystTools(MagicMock(), MagicMock(), lambda: SCHEMA)
    tools.save([], kind="analysis", source="business", sql="SELECT vbeln FROM VBRK WHERE fkdat LIKE '2005%'")
    with pytest.raises(ValueError, match="second part"):
        agent._final_result("What about 2005 if it is empty which years have billing documents?", {
            "kind": "analysis", "answer": "No matching records.", "summary": "No matches",
            "result_ids": ["result_1"], "followups": [],
        }, tools, agent.InvestigationState(), 1, prior_question="Show billing documents in 2004")


def test_only_year_confirmation_cannot_be_proved_by_querying_only_that_year():
    evidence = {"rows": [{"sales_year": "2000", "billed_sales": 299}],
                "sql": "SELECT SUBSTRING(fkdat,1,4) AS sales_year,SUM(CAST(netwr AS NUMERIC)) AS billed_sales FROM VBRK WHERE fkdat LIKE '2000%' GROUP BY SUBSTRING(fkdat,1,4)"}
    assert any("all years" in issue for issue in agent._analysis_issues("Is 2000 the only year with sales?", evidence))
    assert not agent._available_period_request("Only for year 2000")
    assert not agent._has_period_restriction("SELECT SUBSTRING(fkdat,1,4) FROM VBRK WHERE fkdat ~ '^[0-9]{8}$'")


def test_standalone_count_rejects_silently_inherited_customer_filter():
    evidence = {"rows": [{"billing_documents": 1}], "sql": "SELECT COUNT(DISTINCT vbeln) AS billing_documents FROM VBRK WHERE kunag='0000003034'"}
    assert any("inherit" in issue for issue in agent._analysis_issues("How many billing documents are there?", evidence))
    assert any("inherit" in issue for issue in agent._analysis_issues("No, overall I am asking", evidence))
    assert not agent._analysis_issues("How many billing documents for customer 0000003034?", evidence)
    evidence["sql"] = "SELECT COUNT(DISTINCT vbeln) AS billing_documents FROM VBRK WHERE mandt='800'"
    assert any("SAP client" in issue for issue in agent._analysis_issues("How many billing documents are there?", evidence))
    assert not agent._analysis_issues("How many billing documents in client 800?", evidence)


def test_effective_request_survives_chained_followups(monkeypatch):
    inputs = scripted(monkeypatch, [final("I can continue that analysis.")])
    run("Only for year 2000", context={"previousQuestion": "Break down by country",
        "previousPlan": {"effective_question": "Top 10 customers by billed sales. Break down by country"}})
    assert "Top 10 customers" in str(inputs[0]) and "2000" in str(inputs[0])


def test_public_endpoint_keeps_conditional_evidence_through_its_final_gate(monkeypatch):
    from app.api import adaptive_query as api
    schema = {"VBRK": SCHEMA["VBRK"] + [{"col": "fkdat", "type": "text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema, "live_database_metadata"))
    monkeypatch.setattr(api, "_execute_sql", MagicMock(side_effect=[[], [{"sales_year": "2000", "billing_documents": 1}]]))
    scripted(monkeypatch, [
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT vbeln FROM VBRK WHERE fkdat LIKE '2005%'", "purpose": "Check the requested year"}),
        tool("run_readonly_sql", {"source": "business", "sql": "SELECT SUBSTRING(fkdat,1,4) AS sales_year, COUNT(DISTINCT vbeln) AS billing_documents FROM VBRK GROUP BY SUBSTRING(fkdat,1,4)", "purpose": "Find all available years"}, "years"),
        final("No matching documents in 2005. The available year is 2000 with 1 document.", "analysis", ["result_1", "result_2"]),
    ])
    result = api.post_query_adaptive(
        question="What about 2005 if it is empty which years have billing documents?", db=MagicMock(), current_user=None,
        tableHint=None, contextData={"previousQuestion": "Show billing documents in 2004"}, overrideSql=None,
        threadId=None, investigationId=None, conversationHistory=None, newQuestion=False,
    )
    assert result["answer_status"] == "SUCCESS"
    assert len(result["query_plan"]["agent_results"]) == 2


def test_complete_ranking_does_not_inherit_prior_year(monkeypatch):
    inputs = scripted(monkeypatch, [final("I need a database query.")] * 3)
    run(
        "Show me the lowest sales for the year 2000 by country, customer, and product.",
        context={"previousQuestion": "Did the insurance company in 2004 have any sales?"},
    )
    assert "complete new analytical request" in str(inputs[0])
    assert "do not inherit" in str(inputs[0])


def test_numeric_evidence_blocks_invented_totals_and_accepts_rounding_and_calculations():
    results = [{"kind": "analysis", "rows": [{"sales": 12.346}], "row_count": 1}]
    assert agent._unsupported_numbers("Sales are 999.", results, "Show sales") == ["999"]
    assert agent._unsupported_numbers("Sales are 12.35.", results, "Show sales") == []
    assert agent._unsupported_numbers("Growth is -25%.", results, "Show growth") == ["-25"]
    results.append({"kind": "calculation", "value": "-25", "rows": []})
    assert agent._unsupported_numbers("Growth is -25%.", results, "Show growth") == []
