"""Semantic DATABASE_METADATA capability tests — no phrase-handler regressions."""
from __future__ import annotations

import pytest

from app.services.adaptive_analyst.database_metadata import (
    COUNT_COLUMNS,
    COUNT_TABLES,
    DESCRIBE_TABLE,
    LIST_COLUMNS,
    LIST_TABLES,
    SEARCH_TABLES,
    answer_database_metadata,
    classify_metadata_operation,
    execute_metadata_plan,
    is_database_metadata_question,
)
from app.services.adaptive_nl_sql_hardening import (
    is_capability_or_help_question,
    is_general_knowledge_question,
    question_requires_database,
)
from app.services.ai_followup_routing import (
    TurnIntent,
    classify_turn,
    should_route_to_general_chat,
)
from app.services.adaptive_analyst.orchestrator import _force_general_chat, adapt_user_turn


SAMPLE_SCHEMA = {
    "VBRK": [
        {"col": "vbeln", "type": "text"},
        {"col": "netwr", "type": "numeric"},
        {"col": "fkdat", "type": "text"},
        {"col": "kunag", "type": "text"},
    ],
    "VBRP": [
        {"col": "vbeln", "type": "text"},
        {"col": "matnr", "type": "text"},
        {"col": "netwr", "type": "numeric"},
    ],
    "KNA1": [
        {"col": "kunnr", "type": "text"},
        {"col": "name1", "type": "text"},
        {"col": "land1", "type": "text"},
    ],
    "MAKT": [
        {"col": "matnr", "type": "text"},
        {"col": "maktx", "type": "text"},
    ],
}


COUNT_TABLE_FORMS = [
    "How many tables are there?",
    "How many tables exist?",
    "Can you count the tables?",
    "What's the table count?",
    "How many tables do you have access to?",
    "Tell me the number of tables.",
    "Can you tell me how many tables exist in the database?",
]

LIST_TABLE_FORMS = [
    "List the tables.",
    "Show all available tables.",
    "What tables are in the database?",
    "What tables are available?",
    "List all tables.",
    "Which tables exist?",
]


@pytest.mark.parametrize("q", COUNT_TABLE_FORMS)
def test_count_tables_semantic_equivalence(q: str) -> None:
    assert is_database_metadata_question(q)
    plan = classify_metadata_operation(q, SAMPLE_SCHEMA)
    assert plan is not None
    assert plan.operation == COUNT_TABLES
    result = execute_metadata_plan(plan, SAMPLE_SCHEMA)
    assert result.value == 4
    assert "4 tables" in result.summary.lower()
    payload = answer_database_metadata(q, SAMPLE_SCHEMA)
    assert payload is not None
    assert payload["answer_status"] == "SUCCESS"
    assert payload["mode"] == "database_metadata"
    assert payload["meta"]["operation"] == COUNT_TABLES
    assert payload["data"][0]["table_count"] == 4
    assert not payload.get("sql")


@pytest.mark.parametrize("q", LIST_TABLE_FORMS)
def test_list_tables_semantic_equivalence(q: str) -> None:
    assert is_database_metadata_question(q)
    plan = classify_metadata_operation(q, SAMPLE_SCHEMA)
    assert plan is not None
    assert plan.operation == LIST_TABLES
    result = execute_metadata_plan(plan, SAMPLE_SCHEMA)
    assert set(result.value) == set(SAMPLE_SCHEMA.keys())
    payload = answer_database_metadata(q, SAMPLE_SCHEMA)
    assert payload["rowCount"] == 4
    assert payload["meta"]["operation"] == LIST_TABLES


def test_count_columns_operation() -> None:
    q = "How many columns are there?"
    plan = classify_metadata_operation(q, SAMPLE_SCHEMA)
    assert plan is not None
    assert plan.operation == COUNT_COLUMNS
    result = execute_metadata_plan(plan, SAMPLE_SCHEMA)
    assert result.value == 12


def test_describe_and_list_columns_for_named_table() -> None:
    for q, op in (
        ("What columns does VBRK have?", LIST_COLUMNS),
        ("Describe the VBRK table.", DESCRIBE_TABLE),
        ("List the columns in VBRK.", LIST_COLUMNS),
    ):
        assert is_database_metadata_question(q), q
        plan = classify_metadata_operation(q, SAMPLE_SCHEMA)
        assert plan is not None, q
        assert plan.operation == op, (q, plan.operation)
        assert plan.table_name == "VBRK"
        result = execute_metadata_plan(plan, SAMPLE_SCHEMA)
        assert result.evidence.get("column_count") == 4


def test_search_tables_customer_topic() -> None:
    q = "Which tables contain customer information?"
    plan = classify_metadata_operation(q, SAMPLE_SCHEMA)
    assert plan is not None
    assert plan.operation == SEARCH_TABLES
    result = execute_metadata_plan(plan, SAMPLE_SCHEMA)
    tables = {r["table"] for r in result.rows}
    assert "KNA1" in tables


def test_metadata_not_business_analytics() -> None:
    business = [
        "Show top 10 customers by revenue.",
        "What was our revenue in 2004?",
        "How many sales orders are there?",
    ]
    for q in business:
        assert not is_database_metadata_question(q), q
        assert classify_metadata_operation(q, SAMPLE_SCHEMA) is None


def test_general_chat_regressions() -> None:
    for q in ("Hi", "What can I ask?", "What is SAP?"):
        assert not is_database_metadata_question(q), q
        assert (
            _force_general_chat(q)
            or is_capability_or_help_question(q)
            or is_general_knowledge_question(q)
            or q.lower() == "hi"
        )
        turn = classify_turn(q)
        assert turn.reason != "database_metadata"
        assert should_route_to_general_chat(q, turn)


def test_clarification_growth_unaffected() -> None:
    q = "Show me the growth."
    assert not is_database_metadata_question(q)
    turn = classify_turn(q)
    assert turn.intent == TurnIntent.CLARIFICATION_REQUIRED


def test_business_still_requires_database() -> None:
    q = "Show top 10 customers by revenue."
    assert not is_database_metadata_question(q)
    assert question_requires_database(q)
    assert adapt_user_turn(q).action != "chat"


def test_metadata_routing_not_general_chat() -> None:
    q = "How many tables are there?"
    turn = classify_turn(q)
    assert turn.reason == "database_metadata"
    assert not should_route_to_general_chat(q, turn)
    assert not question_requires_database(q)


def test_no_fabricated_count_when_schema_empty() -> None:
    plan = classify_metadata_operation("How many tables are there?", {})
    assert plan is not None
    result = execute_metadata_plan(plan, {})
    assert result.value == 0
    assert "0 tables" in result.summary.lower()
