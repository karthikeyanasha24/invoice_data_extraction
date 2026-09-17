"""LLM-first understanding — unseen language, no phrase handlers."""
from __future__ import annotations

from typing import Any, Dict, Tuple
from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst import understanding as und
from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator
from app.services.adaptive_analyst.understanding import (
    TurnUnderstanding,
    capability_facts,
    is_sufficiently_specified_ranking,
    technical_understanding_failure,
)


def _json_for(question: str, prior_summary: str = "") -> Dict[str, Any]:
    q = (question or "").lower()
    prior = (prior_summary or "").lower()
    if "predefined" in q or "dynamic" in q or "prepared answers" in q or "haven't seen" in q or "previous answer affect" in q:
        return {
            "intent": "conversation",
            "goal": "Ask whether answers are predefined or dynamic",
            "requires_database": False,
            "requires_metadata": False,
            "requires_conversation_context": True,
            "entities": [],
            "metric": None,
            "dimension": None,
            "time_scope": None,
            "operation": None,
            "clarification_needed": False,
            "clarification_question": None,
        }
    if ("simpler" in q or ("explain" in q and prior)) and "sap" not in q:
        return {
            "intent": "conversation",
            "goal": "Simplify or continue prior explanation",
            "requires_database": False,
            "requires_metadata": False,
            "requires_conversation_context": True,
            "entities": [],
            "metric": None,
            "dimension": None,
            "time_scope": None,
            "operation": None,
            "clarification_needed": False,
            "clarification_question": None,
        }
    if "what can you answer" in q or "capabilities" in q or "what can you do" in q:
        return {
            "intent": "capability",
            "goal": "Describe assistant capabilities",
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
        }
    if "sap" in q:
        return {
            "intent": "knowledge",
            "goal": "Explain SAP",
            "requires_database": False,
            "requires_metadata": False,
            "requires_conversation_context": False,
            "entities": ["SAP"],
            "metric": None,
            "dimension": None,
            "time_scope": None,
            "operation": None,
            "clarification_needed": False,
            "clarification_question": None,
        }
    if "table" in q or "schema" in q or "catalog" in q:
        return {
            "intent": "metadata",
            "goal": "Schema introspection",
            "requires_database": False,
            "requires_metadata": True,
            "requires_conversation_context": False,
            "entities": [],
            "metric": None,
            "dimension": None,
            "time_scope": None,
            "operation": "count_tables",
            "clarification_needed": False,
            "clarification_question": None,
        }
    if "growth" in q and "customer" not in q and "sales" not in q:
        return {
            "intent": "clarification",
            "goal": "Underspecified analytics",
            "requires_database": True,
            "requires_metadata": False,
            "requires_conversation_context": False,
            "entities": [],
            "metric": None,
            "dimension": None,
            "time_scope": None,
            "operation": None,
            "clarification_needed": True,
            "clarification_question": "Which metric and time period should I use for growth?",
        }
    if "sales" in q or "customer" in q or "bought" in q or "compare" in q or "decline" in q:
        return {
            "intent": "analytics",
            "goal": "Business analytics request",
            "requires_database": True,
            "requires_metadata": False,
            "requires_conversation_context": False,
            "entities": ["customer"],
            "metric": "sales",
            "dimension": "customer",
            "time_scope": "2004" if "2004" in q else None,
            "operation": None,
            "clarification_needed": False,
            "clarification_question": None,
        }
    return {
        "intent": "conversation",
        "goal": q[:80],
        "requires_database": False,
        "requires_metadata": False,
        "requires_conversation_context": bool(prior_summary),
        "entities": [],
        "metric": None,
        "dimension": None,
        "time_scope": None,
        "operation": None,
        "clarification_needed": False,
        "clarification_question": None,
    }


@pytest.fixture
def mock_llm(monkeypatch):
    calls = {"understand": 0, "respond": 0, "last_understand_user": "", "last_respond_user": ""}

    def fake_json(system: str, user: str) -> Tuple[Dict[str, Any], str]:
        calls["understand"] += 1
        calls["last_understand_user"] = user
        prior = ""
        if "Previous assistant answer:" in user:
            prior = user.split("Previous assistant answer:", 1)[1].split("\n", 1)[0]
        cur = user.rsplit("Current user message:\n", 1)[-1].strip()
        return _json_for(cur, prior), "mock"

    def fake_text(system: str, user: str, **_k) -> Tuple[str, str]:
        calls["respond"] += 1
        calls["last_respond_user"] = user
        if "capability_facts" in user and "available_capabilities" in user:
            return (
                "I can help with conversation, schema metadata, and governed SAP analytics "
                "such as rankings and comparisons over migrated business tables.",
                "mock",
            )
        if "predefined" in user.lower() or "dynamic" in user.lower() or "prepared" in user.lower():
            return (
                "No — I interpret each message with conversation context and then choose "
                "a governed capability. Capability facts are structured metadata, not a fixed script.",
                "mock",
            )
        if "sap" in user.lower():
            return ("SAP is enterprise software companies use to run core business processes.", "mock")
        return ("Understood. How can I help next?", "mock")

    monkeypatch.setattr(und, "analyze_json", fake_json)
    monkeypatch.setattr(und, "complete_text", fake_text)
    return calls


def test_greeting_uses_llm_not_canned(mock_llm, monkeypatch):
    from app.services.adaptive_analyst import llm_provider as lp

    monkeypatch.setattr(lp, "complete_text", und.complete_text)
    out = run_adaptive_orchestrator(
        "hai how are you",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
    )
    assert mock_llm["respond"] >= 1
    assert out["mode"] == "general_chat"
    assert out.get("sql_generation_method") == "llm_greeting_fast"
    assert out["meta"].get("fast_path") == "greeting_single_llm"
    assert "Hi there! How can I help you today?" != (out.get("summary") or "")


def test_capability_facts_are_structured_not_paragraph():
    facts = capability_facts()
    assert "available_capabilities" in facts
    assert facts["available_capabilities"]["business_analytics"] is True
    assert "connected_schema_table_count" in facts
    assert "I can answer governed questions across" not in str(facts)


def test_what_can_you_answer_calls_understanding_and_response(mock_llm):
    out = run_adaptive_orchestrator(
        "What can you answer?",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
    )
    assert mock_llm["understand"] >= 1
    assert mock_llm["respond"] >= 1
    assert out["mode"] == "general_chat"
    assert out["answer_status"] == "SUCCESS"
    assert out["meta"]["understanding_model_called"] is True
    assert out["meta"]["response_model_called"] is True
    assert out["meta"]["selected_capability"] == "capability"
    assert "I can answer governed questions across" not in (out.get("summary") or "")
    assert "analytics" in (out.get("summary") or "").lower() or "help" in (out.get("summary") or "").lower()


def test_is_everything_predefined_uses_prior_context(mock_llm):
    prior_plan = {
        "last_mode": "general_chat",
        "investigation_state": {
            "mode": "general_chat",
            "last_summary": "I can help with governed SAP analytics and metadata.",
            "last_user_question": "What can you answer?",
        },
    }
    out = run_adaptive_orchestrator(
        "Is everything predefined?",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
        prior_question="What can you answer?",
        prior_plan=prior_plan,
        prior_status="SUCCESS",
    )
    assert mock_llm["understand"] >= 1
    assert "Previous assistant answer:" in mock_llm["last_understand_user"]
    assert "What can you answer?" in mock_llm["last_understand_user"] or "governed SAP" in mock_llm["last_understand_user"]
    assert out["mode"] == "general_chat"
    assert out["meta"]["selected_capability"] == "conversation"
    assert "didn't catch a business metric" not in (out.get("summary") or "").lower()
    assert "predefined" in (out.get("summary") or "").lower() or "dynamic" in (out.get("summary") or "").lower() or "interpret" in (out.get("summary") or "").lower()


@pytest.mark.parametrize(
    "q",
    [
        "Is this thing actually dynamic?",
        "So this isn't just a list of prepared answers?",
        "Are you deciding what to do based on what I ask?",
        "Can I ask something you haven't seen before?",
        "Does the previous answer affect what I ask next?",
    ],
)
def test_unseen_conversation_variants(mock_llm, q):
    prior_plan = {
        "last_mode": "general_chat",
        "investigation_state": {
            "mode": "general_chat",
            "last_summary": "I support conversation, metadata, and analytics.",
            "last_user_question": "What can you answer?",
        },
    }
    out = run_adaptive_orchestrator(
        q,
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
        prior_question="What can you answer?",
        prior_plan=prior_plan,
        prior_status="SUCCESS",
    )
    assert out["meta"]["understanding_model_called"] is True
    assert out["mode"] == "general_chat"
    assert "didn't catch a business metric" not in (out.get("summary") or "").lower()


@pytest.mark.parametrize(
    "q",
    [
        "I'm unfamiliar with SAP. Give me a simple explanation.",
        "Why do companies use SAP?",
        "Can you explain SAP in plain English?",
    ],
)
def test_unseen_knowledge_variants(mock_llm, q):
    out = run_adaptive_orchestrator(
        q,
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
    )
    assert out["meta"]["understanding_model_called"] is True
    assert out["meta"]["selected_capability"] == "knowledge"
    assert out["mode"] == "general_chat"
    assert "sap" in (out.get("summary") or "").lower()


def test_show_me_the_growth_is_analytics_clarification_not_early_gate(mock_llm):
    out = run_adaptive_orchestrator(
        "Show me the growth.",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
    )
    assert out["answer_status"] == "CLARIFICATION"
    assert out["meta"]["understanding_model_called"] is True
    assert out["meta"]["selected_capability"] == "clarification"
    assert "metric" in (out.get("summary") or "").lower() or "period" in (out.get("summary") or "").lower()


def test_understanding_failure_is_not_metric_clarification():
    err = RuntimeError("boom")
    payload = technical_understanding_failure("Is everything predefined?", err)
    assert payload["answer_status"] == "CANNOT_ANSWER"
    assert payload["failure_class"] == "UNDERSTANDING_MODEL_FAILED"
    assert "business metric" not in (payload.get("summary") or "").lower()


def test_ranking_specifier_is_exported_for_orchestrator():
    """Live ImportError: orchestrator imported a name that was never on GitHub."""
    assert callable(is_sufficiently_specified_ranking)
    assert is_sufficiently_specified_ranking("top 5 customers by billed sales")
    assert not is_sufficiently_specified_ranking("hai")


def test_metadata_path_uses_understanding_then_tool(mock_llm, monkeypatch):
    def fake_meta(question, schema=None):
        return {
            "answer_status": "SUCCESS",
            "mode": "database_metadata",
            "route": "database_metadata",
            "sql": "",
            "data": [{"table_count": 121}],
            "rowCount": 1,
            "summary": "There are 121 tables available in the connected database.",
            "answer": "There are 121 tables available in the connected database.",
            "meta": {"operation": "COUNT_TABLES", "failure_class": "SUCCESS"},
        }

    monkeypatch.setattr(
        "app.services.adaptive_analyst.database_metadata.answer_database_metadata",
        fake_meta,
    )
    out = run_adaptive_orchestrator(
        "What's the size of the schema in terms of tables?",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
        schema_for_metadata={"VBAK": [{"col": "VBELN", "type": "text"}]},
    )
    assert mock_llm["understand"] >= 1
    assert out["mode"] == "database_metadata"
    assert out["meta"]["understanding_model_called"] is True
    assert "121" in (out.get("summary") or "")


def test_followup_chain_sap_then_simpler(mock_llm):
    t1 = run_adaptive_orchestrator(
        "What is SAP?",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
    )
    assert t1["meta"]["selected_capability"] == "knowledge"
    plan = t1.get("query_plan")
    t2 = run_adaptive_orchestrator(
        "Can you make that simpler?",
        MagicMock(),
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sql")),
        use_sap=False,
        prior_question="What is SAP?",
        prior_plan=plan,
        prior_status="SUCCESS",
    )
    assert t2["meta"]["selected_capability"] == "conversation"
    assert t2["meta"]["understanding_model_called"] is True
    assert "Previous" in mock_llm["last_understand_user"]
