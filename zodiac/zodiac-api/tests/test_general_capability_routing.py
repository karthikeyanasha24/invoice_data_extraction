"""Generic capability routing: general vs database without question handlers."""
from __future__ import annotations

from app.services.adaptive_analyst.orchestrator import (
    _force_general_chat,
    adapt_user_turn,
    run_adaptive_orchestrator,
)
from app.services.adaptive_nl_sql_hardening import (
    clarification_payload,
    is_capability_or_help_question,
    is_general_knowledge_question,
    question_requires_database,
)
from app.services.ai_followup_routing import (
    TurnIntent,
    classify_turn,
    should_route_to_general_chat,
)


GENERAL_VARIANTS = [
    "Hi",
    "What can I ask?",
    "What questions can I ask?",
    "How do I use this?",
    "What are your capabilities?",
    "What do you support?",
    "Help me get started",
    "What is SAP?",
    "Explain revenue.",
    "What does billing mean?",
]

ANALYTICAL_MUST_NEED_DB = [
    "What was our revenue in 2025?",
    "Show me the top 5 customers by revenue.",
    "How has revenue changed over time?",
    "Show monthly sales.",
    "Compare 2024 and 2025 revenue.",
]


def test_capability_questions_are_not_database():
    for q in GENERAL_VARIANTS:
        assert is_capability_or_help_question(q) or is_general_knowledge_question(q) or q.lower() == "hi", q
        assert not question_requires_database(q), q
        assert _force_general_chat(q) or q.lower() == "hi" or is_capability_or_help_question(q) or is_general_knowledge_question(q), q
        adapted = adapt_user_turn(q)
        assert adapted.action == "chat", (q, adapted.action)
        turn = classify_turn(q)
        assert turn.intent == TurnIntent.NON_BUSINESS, (q, turn.intent, turn.reason)
        assert should_route_to_general_chat(q, turn), q


def test_what_can_i_ask_payload_is_general_success():
    payload = clarification_payload("what can I ask?", "capability_meta")
    assert payload["answer_status"] == "SUCCESS"
    assert payload["mode"] == "general_chat"
    assert not payload.get("sql")
    assert "sales" in (payload.get("summary") or "").lower() or "ask" in (payload.get("summary") or "").lower()


def test_analytical_questions_still_need_database():
    for q in ANALYTICAL_MUST_NEED_DB:
        assert question_requires_database(q), q
        assert not _force_general_chat(q), q
        adapted = adapt_user_turn(q)
        assert adapted.action in {"query", "clarify"}, (q, adapted.action)


def test_mixed_definition_plus_fact_needs_database():
    q = "What is revenue, and how much revenue did we make in 2025?"
    assert question_requires_database(q)
    assert not is_general_knowledge_question(q)


def test_investigation_why_still_needs_database():
    for q in (
        "Why did revenue fall?",
        "What caused the decline in sales?",
        "Which customers contributed most to the decrease?",
    ):
        assert not is_general_knowledge_question(q), q
        assert question_requires_database(q) or "contributed" in q.lower(), q
        assert adapt_user_turn(q).action != "chat", q


def test_orchestrator_what_can_i_ask_skips_sql(monkeypatch):
    """Capability turns must not enter SQL / four-stage."""
    import app.services.adaptive_analyst.understanding as und

    called = {"db": False}

    def fake_json(system: str, user: str):
        return {
            "intent": "capability",
            "goal": "capabilities",
            "requires_database": False,
            "requires_metadata": False,
            "requires_conversation_context": False,
            "entities": [],
            "metric": None,
            "dimension": None,
            "time_scope": None,
            "operation": None,
            "clarification_needed": False,
            "clarification_question": None,
        }, "mock"

    def fake_text(system: str, user: str, **_k):
        return ("I can help with governed SAP analytics and schema metadata.", "mock")

    monkeypatch.setattr(und, "analyze_json", fake_json)
    monkeypatch.setattr(und, "complete_text", fake_text)

    def _boom(*_a, **_k):
        called["db"] = True
        raise AssertionError("database path must not run for capability questions")

    monkeypatch.setattr(
        "app.services.adaptive_analyst.orchestrator.try_governed_database",
        _boom,
        raising=False,
    )
    import app.services.adaptive_analyst.governed as gov

    monkeypatch.setattr(gov, "try_governed_database", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no db")))

    class _DummyDb:
        pass

    out = run_adaptive_orchestrator(
        "what can I ask?",
        _DummyDb(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("execute_sql")),
        use_sap=False,
    )
    assert out["mode"] == "general_chat"
    assert out["answer_status"] == "SUCCESS"
    assert not out.get("sql")
    assert called["db"] is False
    assert out["meta"]["understanding_model_called"] is True
