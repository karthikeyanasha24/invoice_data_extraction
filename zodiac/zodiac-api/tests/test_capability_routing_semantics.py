"""Semantic capability routing — not phrase handlers."""
from __future__ import annotations

import pytest

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


CAPABILITY_VARIANTS = [
    "What can I ask?",
    "What can you answer?",
    "What questions can I ask you?",
    "What kinds of questions can you answer?",
    "What can you help me with?",
    "What are you able to answer?",
    "What can you do?",
    "Can you answer questions about my data?",
    "Can you answer anything?",
    "you can answer anything?",
    "Can you answer my questions?",
    "What kind of analysis can you do?",
    "What information can you provide?",
    "What can this AI Analyst do?",
    "What are your capabilities?",
    "What kind of questions can you handle?",
    "Are you able to answer questions about my data?",
    "What does this AI Analyst do?",
]


@pytest.mark.parametrize("q", CAPABILITY_VARIANTS)
def test_capability_variants_are_general_chat(q: str) -> None:
    assert is_capability_or_help_question(q), q
    assert not question_requires_database(q), q
    turn = classify_turn(q)
    assert turn.intent == TurnIntent.NON_BUSINESS, (q, turn.intent, turn.reason)
    assert turn.reason == "capability_meta", (q, turn.reason)
    assert should_route_to_general_chat(q, turn), q
    assert _force_general_chat(q), q
    assert adapt_user_turn(q).action == "chat", q
    payload = clarification_payload(q, "capability_meta")
    assert payload["answer_status"] == "SUCCESS"
    assert payload["mode"] == "general_chat"
    assert not payload.get("sql")
    # Must not emit the business-metric clarification copy.
    summary = (payload.get("summary") or "").lower()
    assert "didn't catch a business metric" not in summary, q


def test_you_can_answer_anything_exact_live_failure() -> None:
    q = "you can answer anything?"
    turn = classify_turn(q)
    assert turn.reason == "capability_meta"
    assert should_route_to_general_chat(q, turn)
    assert not should_route_to_general_chat(
        "Show me the growth.",
        classify_turn("Show me the growth."),
    )


def test_underspecified_analytics_remain_clarification() -> None:
    for q in ("Show me the growth.", "How much?"):
        assert not is_capability_or_help_question(q), q
        turn = classify_turn(q)
        assert turn.intent == TurnIntent.CLARIFICATION_REQUIRED, (q, turn)
        assert turn.reason in {"no_business_signal", "ambiguous"}, (q, turn.reason)
        assert not should_route_to_general_chat(q, turn), q


def test_metadata_not_capability() -> None:
    from app.services.adaptive_analyst.database_metadata import is_database_metadata_question

    q = "How many tables are there?"
    assert is_database_metadata_question(q)
    assert not is_capability_or_help_question(q)
    turn = classify_turn(q)
    assert turn.reason == "database_metadata"
    assert not should_route_to_general_chat(q, turn)


def test_business_analytics_not_capability() -> None:
    q = "Show top 5 customers by billing revenue."
    assert not is_capability_or_help_question(q)
    assert question_requires_database(q)
    turn = classify_turn(q)
    assert turn.intent == TurnIntent.NEW_ANALYTICAL_QUERY
    assert not should_route_to_general_chat(q, turn)


def test_orchestrator_force_general_overrides_query_action(monkeypatch) -> None:
    """force_general_chat must win over adapt_user_turn action=query."""
    q = "you can answer anything?"
    # Without force, older path treated this as query before capability expansion;
    # with expansion adapt_user_turn is already chat — force still must be honored.
    out = run_adaptive_orchestrator(
        q,
        object(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
        force_general_chat=True,
    )
    assert out["mode"] == "general_chat"
    assert out["answer_status"] == "SUCCESS"
    assert not out.get("sql")
    assert "didn't catch a business metric" not in (out.get("summary") or "").lower()


def test_adaptive_body_general_and_clarification_no_unbound_local(monkeypatch) -> None:
    """Regression: nested import must not UnboundLocalError on GENERAL_CHAT / clarification.

    Production HTTP 500 on hai / capability / 'Show me the growth.' was caused by a
    local ``from ... import clarification_payload, question_requires_database`` inside
    ``_post_query_adaptive_body`` that shadowed the module-level names for the whole
    function before that import ran.
    """
    from unittest.mock import MagicMock

    import app.api.adaptive_query as aq

    class _User:
        id = 1
        is_admin = True

    monkeypatch.setenv("OPEN_AI_KEY", "sk-test")
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setattr(aq, "USE_SAP_DB_FOR_AI", False, raising=False)
    monkeypatch.setattr(aq, "_load_schema", lambda: {})
    monkeypatch.setattr(aq, "_looks_like_schema_structure_question", lambda _q: False)
    monkeypatch.setattr(
        "app.services.operational_query_resolver.resolve_operational_query",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.adaptive_analyst.orchestrator_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.ai_native_pipeline.ai_native_enabled",
        lambda: False,
    )

    cases = [
        ("hai", {"SUCCESS", "CLARIFICATION"}),
        ("What can I ask?", {"SUCCESS"}),
        ("What can you answer?", {"SUCCESS"}),
        ("Can you answer anything?", {"SUCCESS"}),
        ("you can answer anything?", {"SUCCESS"}),
        ("What are your capabilities?", {"SUCCESS"}),
        ("What are you able to answer?", {"SUCCESS"}),
        ("What is SAP?", {"SUCCESS", "CLARIFICATION"}),
        ("Show me the growth.", {"CLARIFICATION"}),
        ("How much?", {"CLARIFICATION"}),
    ]
    for q, allowed in cases:
        out = aq._post_query_adaptive_body(
            q=q,
            original_question=q,
            tableHint=None,
            contextData=None,
            overrideSql=None,
            threadId=None,
            investigationId="reg-unbound",
            db=MagicMock(),
            current_user=_User(),
        )
        status = str(out.get("answer_status") or "").upper()
        assert status in allowed, (q, status, out.get("summary"))
        assert status != "ERROR", q
