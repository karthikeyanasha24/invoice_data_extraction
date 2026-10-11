"""Response generation must receive actual user preferences independently of SQL anchors."""
from __future__ import annotations

import json

from app.services.adaptive_analyst import understanding
from app.services.adaptive_analyst.chat_memory import (
    relevant_conversation,
    remember_response,
    user_conversation_preferences,
)


def test_preference_is_retained_when_the_next_topic_has_no_matching_words():
    preference = "For this chat, remember that I prefer answers in one short sentence when I ask a general question."
    turns = [
        {"role": "user", "content": preference},
        {"role": "assistant", "content": "Understood."},
    ]
    for index in range(8):
        turns.extend([
            {"role": "user", "content": f"Show billing document {index}."},
            {"role": "assistant", "content": f"Document {index} is returned."},
        ])

    relevant = relevant_conversation("What is a database index?", turns)

    assert any(turn["role"] == "user" and turn["content"] == preference for turn in relevant)
    assert user_conversation_preferences(relevant) == [preference]


def test_long_retrieved_answers_cannot_displace_the_latest_followup():
    turns = []
    for index in range(8):
        turns.extend([
            {"role": "user", "content": f"Show billing sales for country {index}."},
            {"role": "assistant", "content": f"Country {index}: " + "Verified row. " * 460},
        ])
    turns.extend([
        {"role": "user", "content": "Only for calendar year 2000."},
        {"role": "assistant", "content": "I used calendar year 2000 and kept currencies separate.", "mode": "analysis"},
    ])
    result = relevant_conversation("Compare that with 2001", turns, recent_limit=20, max_chars=12000)
    assert result[-2:] == turns[-2:]
    assert sum(len(turn["content"]) for turn in result) <= 12000
    assert any("Message excerpt" in turn["content"] for turn in result)


def test_a_long_message_is_marked_as_an_excerpt_even_before_total_budget_runs_out():
    result = relevant_conversation("Explain those results", [
        {"role": "assistant", "content": "Verified data " * 600},
    ], max_chars=22000)
    assert len(result[0]["content"]) <= 6000
    assert result[0]["content"].endswith("[Message excerpt; remaining content omitted.]")


def test_preferences_survive_large_results_and_later_corrections_stay_ordered():
    first = "For this chat, please use short answers."
    correction = "Forget my brevity preference and use detailed replies from now on."
    turns = [{"role": "user", "content": first}]
    for index in range(10):
        turns.extend([
            {"role": "user", "content": f"Show customer {index}."},
            {"role": "assistant", "content": "Verified data " * 500},
        ])
    turns.extend([{"role": "user", "content": correction}, {"role": "assistant", "content": "Understood."}])
    result = relevant_conversation("Explain an index", turns, recent_limit=12, max_chars=12000)
    assert user_conversation_preferences(result) == [first, correction]
    assert result[-2:] == turns[-2:]
    assert sum(len(turn["content"]) for turn in result) <= 12000


def test_general_model_receives_user_preference_and_recent_chat_despite_an_sql_anchor(monkeypatch):
    preference = "For our conversation, explain general concepts in Spanish and avoid bullet lists."
    history = [
        {"role": "user", "content": preference},
        {"role": "assistant", "content": "Entendido.", "mode": "general_chat"},
    ]
    source_sql = 'SELECT country, sales FROM verified_billing'
    memory = remember_response(
        {"retained_analytical_context": {"previousSQL": source_sql}},
        history,
        "What is a database index?",
        "Un índice ayuda a localizar filas.",
        "general_chat",
    )
    seen = {}
    generated = "Esta respuesta sigue la preferencia. Mantiene todo el texto generado."

    def response(system, user):
        seen["system"] = system
        seen["payload"] = json.loads(user.split("\n", 1)[1])
        return generated, "mock"

    monkeypatch.setattr(understanding, "complete_text", response)
    reply, provider = understanding.generate_grounded_response(
        "What is a database index?",
        understanding.TurnUnderstanding(intent="knowledge"),
        prior_question="Show countries by sales for 2021.",
        evidence={"recent_turns": memory["recent_turns"]},
    )

    assert seen["payload"]["conversation_context"]["user_preferences"] == [preference]
    assert "Later user changes" in seen["system"]
    assert "specific instruction in the current message" in seen["system"]
    assert reply == generated and provider == "mock"
    assert memory["retained_analytical_context"]["previousSQL"] == source_sql


def test_preference_corrections_stay_in_order_and_recall_questions_are_not_new_rules():
    first = "I prefer very brief responses."
    correction = "Forget my brevity preference and use detailed replies from now on."
    turns = [
        {"role": "user", "content": first},
        {"role": "assistant", "content": "I prefer to answer in bullets."},
        {"role": "user", "content": correction},
        {"role": "user", "content": "What answer-length preference did I ask you to remember for this chat?"},
    ]

    assert user_conversation_preferences(turns) == [first, correction]


def test_understanding_uses_latest_outer_history_instead_of_stale_sql_state(monkeypatch):
    preference = "For this chat, keep conceptual answers conversational."
    latest = [{"role": "user", "content": preference}]
    stale = [{"role": "user", "content": "Show invoices for 2020."}]
    context = understanding._context_block(
        current_question="What response preference did I request?",
        prior_plan={"recent_turns": latest, "investigation_state": {"recent_turns": stale}},
    )

    assert preference in context
    assert "User-authored conversation preferences" in context
    assert "Show invoices for 2020." not in context
