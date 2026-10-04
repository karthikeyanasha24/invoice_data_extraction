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
    SEARCH_COLUMNS,
    LIST_DATA_SOURCES,
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


def test_contextual_schema_followups_are_not_global_catalog_requests() -> None:
    followups = [
        "Which SAP table did you just mention for sales order and billing headers?",
        "Which of those columns is the billing date?",
        "For the top country from those results, show billed sales by year.",
        (
            "Run the query now, including negative billing amounts and using only "
            "real columns from the connected schema."
        ),
    ]
    for q in followups:
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


@pytest.mark.parametrize("question", [
    "Show the top five countries by billed sales in the latest complete year available in the data",
    "Show total billed sales for the last two complete years.",
    "Give the full customer breakdown of sales in 2001.",
    "Show all billing documents for the selected customer.",
    "Show billed sales from all connected data sources.",
])
def test_period_and_output_completeness_do_not_become_catalog_lists(question):
    assert not is_database_metadata_question(question)
    assert classify_metadata_operation(question, SAMPLE_SCHEMA) is None


def test_natural_field_question_resolves_primary_billing_document_identifier():
    from app.data_catalog.physical import load_physical_schema

    schema = load_physical_schema()
    answer = answer_database_metadata("Which table and field store the billing document number?", schema)
    assert answer["meta"]["operation"] == SEARCH_COLUMNS
    assert [(row["table"].upper(), row["column"].lower()) for row in answer["data"]] == [("VBRK", "vbeln")]
    assert "header" in answer["data"][0]["table_role"].lower()


def test_scoped_date_and_amount_question_does_not_count_all_columns():
    from app.data_catalog.physical import load_physical_schema

    answer = answer_database_metadata("Which date and amount fields are available for billing documents?", load_physical_schema())
    assert answer["meta"]["operation"] == SEARCH_COLUMNS
    assert {(row["table"].upper(), row["column"].lower()) for row in answer["data"]} == {("VBRK", "fkdat"), ("VBRK", "netwr")}


def test_multi_topic_discovery_preserves_table_roles_and_covers_each_domain():
    from app.data_catalog.physical import load_physical_schema

    answer = answer_database_metadata("Which tables contain billing documents, sales orders, customers, and materials?", load_physical_schema())
    tables = {row["table"].upper() for row in answer["data"]}
    assert {"VBRK", "VBRP", "VBAK", "VBAP", "KNA1", "MARA"} <= tables
    assert len(tables) <= 12
    assert all(row["role"] for row in answer["data"])
    assert "LIKP" not in tables and "LIPS" not in tables


def test_source_inventory_derives_domains_and_counts_from_authorized_schema():
    answer = answer_database_metadata("Which data sources are connected for this chat?", SAMPLE_SCHEMA)
    assert answer["meta"]["operation"] == LIST_DATA_SOURCES
    assert sum(row["table_count"] for row in answer["data"]) == len(SAMPLE_SCHEMA)
    assert all(table in " ".join(row["tables"] for row in answer["data"]) for table in SAMPLE_SCHEMA)


def test_exact_physical_field_discovery_returns_all_authorized_occurrences():
    answer = answer_database_metadata("Which tables have a column VBELN?", SAMPLE_SCHEMA)
    assert answer["meta"]["operation"] == SEARCH_COLUMNS
    assert {row["table"] for row in answer["data"]} == {"VBRK", "VBRP"}


def test_schema_evidence_disambiguates_delivery_and_billing_identifiers():
    from app.services.adaptive_analyst.understanding import _schema_semantics_evidence

    facts = _schema_semantics_evidence("Explain LIKP and LIPS delivery document number fields", [])
    assert any(fact.startswith("LIKP.VBELN:") and "delivery document number" in fact for fact in facts)
    assert any(fact.startswith("LIPS.VBELN:") and "delivery document number" in fact for fact in facts)
    assert not any(fact.startswith(("LIKP.VBELN:", "LIPS.VBELN:")) and "billing document" in fact for fact in facts)


@pytest.mark.parametrize("question", [
    "Show the billing documents behind the leading customer's total.",
    "For the highest-ranked material, show its sales by month in that year.",
    "Compare its sales with the previous complete year.",
    "For that country, show billed sales by year.",
])
def test_selected_result_references_are_database_followups(question):
    from app.services.adaptive_analyst.understanding import is_referential_database_action

    assert is_referential_database_action(question, has_prior=True)
    assert not is_referential_database_action(question, has_prior=False)


def test_new_top_customer_question_is_not_inferred_as_a_selected_reference():
    from app.services.adaptive_analyst.understanding import is_referential_database_action

    assert not is_referential_database_action("Show the top five customers by billed sales.", has_prior=True)


def test_local_possessive_in_invoice_question_is_not_mistaken_for_chat_followup():
    from app.services.adaptive_analyst.understanding import is_referential_database_action

    question = (
        "Show the 10 lowest billed invoices in 2000. For each invoice, "
        "compare its linked sales order amount in 2000 and 2001."
    )
    assert not is_referential_database_action(question, has_prior=True)

    # A possessive that refers to a selected result remains a follow-up.
    assert is_referential_database_action(
        "For the highest-ranked material, show its sales by month in that year.",
        has_prior=True,
    )


@pytest.mark.parametrize("question", [
    "Show this year's billed sales.",
    "Show sales in the previous year.",
    "Show sales in the previous two complete years.",
])
def test_calendar_relative_periods_are_not_entity_references(question):
    from app.services.adaptive_analyst.understanding import is_referential_database_action

    assert not is_referential_database_action(question, has_prior=True)
