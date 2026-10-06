"""History preserves SQL disclosure separately from trusted result context."""
import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks

from app.services.adaptive_analyst.chat_memory import context_from_stored_turns
from app.services.adaptive_analyst.sql_evidence import (
    sql_evidence_from_payload, sql_evidence_from_stored_turn,
)


@pytest.mark.parametrize("sql_status,answer_status", [
    ("executed", "SUCCESS"),
    ("generated", "CANNOT_ANSWER"),
    ("validation_failed", "CANNOT_ANSWER"),
    ("execution_failed", "CANNOT_ANSWER"),
    ("result_validation_failed", "CANNOT_ANSWER"),
])
def test_sql_evidence_roundtrip_through_write_and_history_api(monkeypatch, sql_status, answer_status):
    from app import database
    from app.api import adaptive_query as api
    from app.services import chat_thread_store

    sql = 'SELECT SUM("netwr") FROM "VBRK"'
    evidence = sql_evidence_from_payload({
        "sql": sql, "attempted_sql": sql, "sql_status": sql_status,
        "failure_class": "RESULT_VALIDATION_FAILED" if sql_status == "result_validation_failed" else "",
    })
    db = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(chat_thread_store, "ensure_chat_tables", lambda *_args: None)
    monkeypatch.setattr(chat_thread_store, "next_turn_index", lambda *_args: 0)
    save = MagicMock(return_value=True)
    monkeypatch.setattr(chat_thread_store, "save_turn", save)
    api._persist_adaptive_turn_async({
        "user_id": 42, "thread_id": "ada_sql_history", "question": "Show billed sales.",
        "summary": "The analysis outcome.", "answer": "Detailed **explanation** with limitations.", "answer_status": answer_status,
        "sql": sql if answer_status == "SUCCESS" else "", "sql_evidence": evidence,
    })
    assistant = save.call_args_list[1].kwargs
    turn = {
        "role": "assistant", "content": assistant["content"],
        "sql_executed": assistant["sql_executed"], "key_metrics": assistant["key_metrics"],
    }
    monkeypatch.setattr(chat_thread_store, "thread_owner_user_id", lambda *_args: 42)
    monkeypatch.setattr(chat_thread_store, "load_thread", lambda *_args, **_kwargs: [turn])
    history = asyncio.run(api.get_adaptive_chat_history(
        thread_id="ada_sql_history", db=MagicMock(), current_user=type("User", (), {"id": 42})(),
    ))
    restored = history["messages"][0]["result"]
    assert {key: restored[key] for key in evidence} == evidence
    assert restored["answer_status"] == answer_status
    assert restored["summary"] == "The analysis outcome."
    assert restored["answer"] == "Detailed **explanation** with limitations."
    if answer_status != "SUCCESS":
        context = context_from_stored_turns([turn])
        assert context["previousSQL"] == "" and context["data"] == []
        assert context["previousAnswerStatus"] == answer_status


def test_failed_response_snapshot_retains_returned_sql_before_storage_clears_anchor(monkeypatch):
    from app.api import adaptive_query as api
    from app.services import adaptive_analyst, chat_thread_store

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(chat_thread_store, "thread_owner_user_id", lambda *_args: 42)
    monkeypatch.setattr(chat_thread_store, "load_thread", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("app.services.operational_query_resolver.resolve_operational_query", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adaptive_analyst, "orchestrator_enabled", lambda: True)
    sql = 'SELECT SUM("netwr") FROM "VBRK"'
    monkeypatch.setattr(adaptive_analyst, "run_adaptive_orchestrator", lambda *_args, **_kwargs: {
        "answer_status": "CANNOT_ANSWER", "mode": "error", "summary": "Query blocked.",
        "sql": sql, "attempted_sql": sql, "sql_status": "validation_failed",
        "failure_class": "SQL_VALIDATION_FAILED",
    })
    tasks = BackgroundTasks()
    result = api._post_query_adaptive_body(
        q="Show billed sales by month.", original_question="Show billed sales by month.",
        tableHint=None, contextData=None, overrideSql=None, threadId="ada_sql_history",
        investigationId=None, db=MagicMock(), current_user=type("User", (), {"id": 42})(),
        background_tasks=tasks,
    )
    snapshot = tasks.tasks[0].args[0]
    assert result["sql"] == sql
    assert snapshot["sql"] == ""
    assert snapshot["sql_evidence"] == {
        "sql": sql, "attempted_sql": sql, "sql_status": "validation_failed",
        "failure_class": "SQL_VALIDATION_FAILED",
    }


def test_reused_result_source_sql_survives_without_claiming_new_execution():
    source = 'SELECT "country", SUM("netwr") FROM "VBRK" GROUP BY "country"'
    evidence = sql_evidence_from_payload({"source_sql": source, "sql_status": "not_generated"})
    restored = sql_evidence_from_stored_turn({"key_metrics": {"sql_evidence": evidence}, "sql_executed": ""})
    assert restored == {"source_sql": source, "sql_status": "not_generated"}
    assert not restored.get("sql")


def test_legacy_query_preserves_text_without_inventing_execution_status():
    restored = sql_evidence_from_stored_turn({"sql_executed": "SELECT 1", "key_metrics": {"answer_status": "SUCCESS"}})
    assert restored == {"sql": "SELECT 1", "sql_status": "execution_unverified"}


def test_legacy_failure_with_erased_query_does_not_fabricate_sql():
    assert sql_evidence_from_stored_turn({"sql_executed": "", "key_metrics": {"answer_status": "CANNOT_ANSWER"}}) == {}
