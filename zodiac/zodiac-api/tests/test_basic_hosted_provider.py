import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import basic_hosted_provider as hosted
from app.services import analyst_agent as agent
from app.services.basic_local_provider import use_local_agent, restore_local_agent
from app.services.basic_sql_answer import run_basic_sql_answer
from app.services.investigation_budget import block_paid_models, restore_paid_models, paid_models_blocked, end_investigation


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("BASIC_LLM_PROVIDER", "groq")
    monkeypatch.setenv("BASIC_GROQ_FREE_PLAN", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("app.services.basic_local_provider.ollama_post", lambda *_: pytest.fail("Vercel must not call localhost"))
    monkeypatch.setattr("openai.OpenAI", lambda *_a, **_k: pytest.fail("Basic must not use OpenAI credits"))
    yield
    end_investigation()


def reply(message, reason="stop"):
    return {"choices": [{"message": message, "finish_reason": reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_free_plan_requires_explicit_configuration(monkeypatch):
    monkeypatch.delenv("BASIC_GROQ_FREE_PLAN")
    assert not hosted.basic_llm_enabled()
    monkeypatch.setenv("BASIC_GROQ_FREE_PLAN", "true")
    monkeypatch.delenv("GROQ_API_KEY")
    assert not hosted.basic_llm_enabled()


def test_vercel_never_enables_a_local_daemon(monkeypatch):
    monkeypatch.setenv("BASIC_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("BASIC_LOCAL_MODEL", "qwen3:4b")
    assert not hosted.basic_llm_enabled()


def test_serializes_tool_ids_correctly_and_stays_within_bounded_prompt(monkeypatch):
    seen = []
    monkeypatch.setattr(hosted, "groq_post", lambda body, timeout: seen.append(body) or reply({"tool_calls": [
        {"id": "c2", "function": {"name": "calculate", "arguments": '{"expression":"2+2"}'}}]}, "tool_calls"))
    result = hosted.create_hosted_response(instructions="ignored paid-provider prose", input=[
        {"type": "function_call", "call_id": "c1", "name": "calculate", "arguments": '{"expression":"1+1"}'},
        {"type": "function_call_output", "call_id": "c1", "output": "2"}], tools=agent._TOOLS, output_schema=agent._FINAL_SCHEMA)
    assert result.output[0]["call_id"] == "c2"
    assert seen[0]["messages"][-1]["tool_call_id"] == "c1"
    assert seen[0]["model"] == "openai/gpt-oss-20b"
    assert seen[0]["max_completion_tokens"] == 1024
    assert "research_public_context" not in [t["function"]["name"] for t in seen[0]["tools"]]


def test_oversized_prompt_stops_before_sending_private_data(monkeypatch):
    monkeypatch.setattr(hosted, "groq_post", lambda *_: pytest.fail("Oversized prompt must stop"))
    with pytest.raises(ValueError, match="context limit"):
        hosted.create_hosted_response(instructions="", input=[{"role": "user", "content": "x"*25000}],
                                      tools=agent._TOOLS, output_schema=agent._FINAL_SCHEMA)


def test_hosted_loop_executes_real_sql_with_no_paid_fallback(monkeypatch):
    schema = {"VBRK": [{"col": "waerk", "type": "text"}]}
    monkeypatch.setattr("app.services.adaptive_analyst.live_schema.load_live_schema", lambda *_: (schema, "live_database_metadata"))
    monkeypatch.setattr("app.services.four_stage_db_pipeline.pipeline3_sql_generation", lambda *a, **k: "")
    sequence = iter([
        reply({"tool_calls": [{"id": "inspect", "function": {"name": "describe_tables", "arguments": json.dumps({
            "source": "application", "tables": ["VBRK"], "column_filter": None})}}]}, "tool_calls"),
        reply({"tool_calls": [{"id": "query", "function": {"name": "run_readonly_sql", "arguments": json.dumps({
            "source": "application", "sql": 'SELECT DISTINCT waerk AS currency FROM "VBRK"', "purpose": "List currencies"})}}]}, "tool_calls"),
    ])
    def respond(body, timeout):
        assert paid_models_blocked()
        return next(sequence)
    monkeypatch.setattr(hosted, "groq_post", respond)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "VBRK"(waerk TEXT)'))
        conn.execute(text('INSERT INTO "VBRK" VALUES (\'USD\')'))
    with Session(engine) as db:
        result = run_basic_sql_answer("Which currencies are recorded?", execute=MagicMock(),
            local_agent=lambda examples: agent.run_analyst_agent("Which currencies are recorded?", db,
                lambda session, sql, *_: [dict(r) for r in session.execute(text(sql)).mappings().all()], schema_loader=lambda: schema))
    assert result["answer_status"] == "SUCCESS", result
    assert result["data"] == [{"currency": "USD"}]
    assert result["meta"]["provider"] == "groq" and result["meta"]["free_quota_used"]
    assert result["meta"]["usage"]["total_tokens"] == 30
    assert not paid_models_blocked()


def test_quota_exhaustion_does_not_retry_or_fallback(monkeypatch):
    import httpx
    response = MagicMock(status_code=429)
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    with pytest.raises(RuntimeError, match="free model quota"):
        hosted.groq_post({}, 2)
    client.post.assert_called_once()
    assert client.post.call_args.args[0] == "https://api.groq.com/openai/v1/chat/completions"
