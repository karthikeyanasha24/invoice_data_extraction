"""Scripted Ollama replies exercise the shared agent and all no-paid boundaries."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import basic_local_provider as local
from app.services import analyst_agent as agent
from app.services.basic_sql_answer import run_basic_sql_answer
from app.services.investigation_budget import block_paid_models, restore_paid_models, paid_models_blocked, end_investigation


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("BASIC_LOCAL_MODEL", "qwen3:4b")
    monkeypatch.delenv("BASIC_EMBED_MODEL", raising=False)
    monkeypatch.setattr("openai.OpenAI", lambda *_a, **_k: pytest.fail("Basic contacted OpenAI"))
    yield
    end_investigation()


def response(message):
    return {"done": True, "done_reason": "stop", "message": message, "prompt_eval_count": 12, "eval_count": 8}


def test_casual_reply_uses_ollama_without_tools_or_thinking(monkeypatch):
    seen = {}
    monkeypatch.setattr(local, "ollama_post", lambda endpoint, body, timeout: (
        seen.update(endpoint=endpoint, body=body, timeout=timeout)
        or response({"content": "Hi! What would you like to know about billing?"})
    ))

    result = local.casual_local_reply("hai")

    assert result["answer"] == "Hi! What would you like to know about billing?"
    assert result["model"] == "ollama/qwen3:4b"
    assert result["total_tokens"] == 20
    assert seen["endpoint"] == "/api/chat" and seen["timeout"] == 20
    assert seen["body"]["think"] is False
    assert "tools" not in seen["body"]
    assert seen["body"]["options"]["num_ctx"] == 512


def test_transport_serializes_tool_results_and_excludes_paid_research(monkeypatch):
    seen = []
    monkeypatch.setattr(local, "ollama_post", lambda endpoint, body, timeout: seen.append(body) or response({
        "tool_calls": [{"function": {"name": "calculate", "arguments": {"expression": "2+3"}}}]}))
    inp = [{"role": "user", "content": "Hello"},
           {"type": "function_call", "call_id": "c", "name": "calculate", "arguments": '{"expression":"1+1"}'},
           {"type": "function_call_output", "call_id": "c", "output": "2"}]
    result = local.create_local_response(instructions="test", input=inp, tools=agent._TOOLS, output_schema=agent._FINAL_SCHEMA)
    assert result.output[0]["name"] == "calculate"
    assert seen[0]["messages"][-1] == {"role": "tool", "tool_name": "calculate", "content": "2"}
    assert "research_public_context" not in [t["function"]["name"] for t in seen[0]["tools"]]


@pytest.mark.parametrize("message", [
    {"content": "I think revenue is 400"},
    {"content": '{"kind":"analysis"}'},
    {"tool_calls": [{"function": {"name": "research_public_context", "arguments": {}}}]},
])
def test_malformed_or_unauthorized_model_output_is_rejected(monkeypatch, message):
    monkeypatch.setattr(local, "ollama_post", lambda *_: response(message))
    with pytest.raises(ValueError):
        local.create_local_response(instructions="test", input=[], tools=agent._TOOLS, output_schema=agent._FINAL_SCHEMA)


@pytest.mark.parametrize("model", ["qwen3:cloud", "vendor/model", ""])
def test_only_installed_local_models_are_allowed(monkeypatch, model):
    monkeypatch.setenv("BASIC_LOCAL_MODEL", model)
    with pytest.raises(ValueError):
        local.local_model()


@pytest.mark.parametrize("url", ["https://ollama.com", "https://api.ollama.com", "http://user:pass@localhost:11434", "http://localhost:11434?x=1"])
def test_hosted_or_credential_urls_are_rejected(monkeypatch, url):
    monkeypatch.setenv("BASIC_OLLAMA_URL", url)
    with pytest.raises(ValueError):
        local.ollama_post("/api/chat", {}, 1)


def test_remote_ollama_requires_https_and_bearer_key(monkeypatch):
    monkeypatch.setenv("BASIC_OLLAMA_URL", "https://model.example.org")
    monkeypatch.delenv("BASIC_OLLAMA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="authenticated HTTPS|HTTPS endpoint"):
        local.ollama_endpoint_config()
    monkeypatch.setenv("BASIC_OLLAMA_API_KEY", "test-secret")
    assert local.ollama_endpoint_config() == (
        "https://model.example.org", {"Authorization": "Bearer test-secret"})
    monkeypatch.setenv("BASIC_OLLAMA_URL", "http://model.example.org")
    with pytest.raises(ValueError, match="HTTPS endpoint"):
        local.ollama_endpoint_config()


def test_unknown_question_runs_real_tool_loop_with_local_model_and_live_rows(monkeypatch):
    schema = {"VBRK": [{"col": "waerk", "type": "text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema, "live_database_metadata"))
    monkeypatch.setattr("app.services.four_stage_db_pipeline.pipeline3_sql_generation", lambda *a, **k: "")
    messages = iter([
        response({"tool_calls": [{"function": {"name": "describe_tables", "arguments": {
            "source": "application", "tables": ["VBRK"], "column_filter": None}}}]}),
        response({"tool_calls": [{"function": {"name": "run_readonly_sql", "arguments": {
            "source": "application", "sql": 'SELECT DISTINCT waerk AS currency FROM "VBRK"',
            "purpose": "Find recorded currencies"}}}]}),
        response({"content": json.dumps({"kind": "analysis", "answer": "Recorded currency is USD.",
            "summary": "Recorded currency is USD.", "result_ids": ["result_2"], "followups": []})}),
    ])
    requests = []
    def respond(endpoint, body, timeout):
        assert paid_models_blocked() and local.local_agent_active()
        requests.append(body)
        return next(messages)
    monkeypatch.setattr(local, "ollama_post", respond)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "VBRK" (waerk TEXT)'))
        connection.execute(text('INSERT INTO "VBRK" VALUES (\'USD\')'))
    with Session(engine) as db:
        def execute(session, sql, *_):
            return [dict(row) for row in db.execute(text(sql)).mappings().all()]
        result = run_basic_sql_answer("Which currencies are recorded?", execute=MagicMock(),
            local_agent=lambda examples: agent.run_analyst_agent("Which currencies are recorded?", db, execute,
                schema_loader=lambda: schema, context={"basic_rag_examples": examples}))
    assert result["answer_status"] == "SUCCESS", json.dumps(result, default=str)
    assert result["data"] == [{"currency": "USD"}]
    assert result["meta"]["provider"] == "ollama" and result["meta"]["credits_used"] is False
    assert result["meta"]["usage"]["total_tokens"] > 0
    assert result["meta"]["usage"]["estimated_cost_usd"] == "0"
    assert paid_models_blocked() is False and local.local_agent_active() is False


def test_provider_error_never_falls_back_to_paid_and_context_is_restored(monkeypatch):
    monkeypatch.setattr("app.services.four_stage_db_pipeline.pipeline3_sql_generation", lambda *a, **k: "")
    def fail(_):
        assert paid_models_blocked() and local.local_agent_active()
        raise ConnectionError("Ollama unavailable")
    with pytest.raises(ConnectionError):
        run_basic_sql_answer("new custom investigation", execute=MagicMock(), local_agent=fail)
    assert paid_models_blocked() is False and local.local_agent_active() is False


def test_paid_guard_still_blocks_openai_outside_local_context():
    from app.services.analyst_agent_provider import create_agent_response
    token = block_paid_models()
    try:
        with pytest.raises(RuntimeError, match="paid model"):
            create_agent_response(instructions="test", input=[], tools=[], output_schema={})
    finally:
        restore_paid_models(token)
