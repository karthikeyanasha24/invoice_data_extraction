"""Catalog subject filters must follow metadata and the authorized schema."""
from __future__ import annotations

import pytest

from app.services.adaptive_analyst import database_metadata as metadata


@pytest.mark.parametrize("question", [
    "Which billing tables are available in the connected SAP database?",
    "What billing tables exist?",
    "List all billing tables.",
    "Show me the billing tables in the database.",
])
def test_table_subject_uses_verified_roles_and_authorized_tables(monkeypatch, question):
    schema = {
        "Z_BILL_HEADER": [{"col": "doc_id", "type": "text"}],
        "Z_BILL_LINE": [{"col": "doc_id", "type": "text"}],
        "Z_DELIVERY": [{"col": "doc_id", "type": "text"}],
        "Z_CUSTOMER": [{"col": "customer_id", "type": "text"}],
    }
    semantics = {
        "Z_BILL_HEADER": {"description": "Billing document header.", "domain": "invoice", "grain": "billing document"},
        "Z_BILL_LINE": {"description": "Billing document items.", "domain": "invoice", "grain": "billing item"},
        "Z_DELIVERY": {"description": "Outbound delivery header. Links to billing documents downstream.", "domain": "delivery", "grain": "delivery"},
        "Z_CUSTOMER": {"description": "Customer master.", "domain": "customer", "grain": "customer"},
        "UNAUTHORIZED": {"description": "Billing document header.", "domain": "invoice", "grain": "billing document"},
    }
    monkeypatch.setattr(metadata, "_table_semantics", lambda name: semantics[name])
    answer = metadata.answer_database_metadata(question, schema)

    assert {row["table"] for row in answer["data"]} == {"Z_BILL_HEADER", "Z_BILL_LINE"}
    assert answer["meta"]["evidence"]["match_count"] == 2
    assert answer["meta"]["evidence"]["table_count"] == 4
    assert all("billing" in row["role"].lower() for row in answer["data"])


def test_unknown_table_subject_does_not_fall_back_to_global_catalog():
    schema = {"CUSTOMERS": [{"col": "customer_id", "type": "text"}]}
    answer = metadata.answer_database_metadata("Which astrophysics tables are available?", schema)
    assert answer["data"] == []
    assert "No tables" in answer["summary"]
    assert "astrophysics" in answer["summary"]
    assert answer["meta"]["evidence"]["match_count"] == 0


def test_unknown_explicit_domain_does_not_discard_requested_filter():
    answer = metadata.answer_database_metadata(
        "List all astrophysics-domain tables.", {"CUSTOMERS": [{"col": "customer_id", "type": "text"}]},
    )
    assert answer["data"] == []
    assert answer["meta"]["evidence"]["domain"] == "astrophysics"


def test_topic_inventory_count_and_limit_use_filtered_catalog(monkeypatch):
    schema = {f"T_{i}": [{"col": "id", "type": "text"}] for i in range(5)}
    monkeypatch.setattr(metadata, "_table_semantics", lambda name: {
        "description": "Invoice header." if name != "T_4" else "Customer master.",
        "domain": "invoice" if name != "T_4" else "customer",
        "grain": "document",
    })
    answer = metadata.answer_database_metadata("How many invoice tables are there, and list the first two tables?", schema)
    assert [row["table"] for row in answer["data"]] == ["T_0", "T_1"]
    assert answer["meta"]["evidence"]["match_count"] == 4
    assert "4 connected tables matching invoice" in answer["summary"]
    assert not answer["meta"]["evidence"]["listed_all"]


def test_all_tables_request_preserves_complete_catalog():
    schema = {f"TABLE_{i:02}": [{"col": "id", "type": "text"}] for i in range(50)}
    answer = metadata.answer_database_metadata("List all available tables in the connected SAP database.", schema)
    assert len(answer["data"]) == 50
    assert answer["meta"]["evidence"]["listed_all"]


def test_physical_table_name_is_valid_topic_evidence_without_registry():
    schema = {"CUSTOM_BILLING": [{"col": "id", "type": "text"}], "CUSTOM_PEOPLE": [{"col": "id", "type": "text"}]}
    answer = metadata.answer_database_metadata("Which billing tables are available?", schema)
    assert [row["table"] for row in answer["data"]] == ["CUSTOM_BILLING"]


def test_live_sap_billing_inventory_excludes_other_catalog_domains():
    from app.data_catalog.physical import load_physical_schema

    answer = metadata.answer_database_metadata("Which billing tables are available in the connected SAP database?", load_physical_schema())
    assert {row["table"].upper() for row in answer["data"]} == {"VBRK", "VBRP"}


def test_named_table_semantic_fields_present_selects_requested_meanings():
    from app.data_catalog.physical import load_physical_schema

    answer = metadata.answer_database_metadata("Which date, amount and currency fields are present in VBRK?", load_physical_schema())
    assert answer["meta"]["operation"] == metadata.SEARCH_COLUMNS
    assert {(row["table"].upper(), row["column"].lower()) for row in answer["data"]} == {
        ("VBRK", "fkdat"), ("VBRK", "netwr"), ("VBRK", "waerk"),
    }


def test_list_all_columns_preserves_named_table_inventory():
    schema = {"CUSTOM_DOC": [{"col": "id", "type": "text"}, {"col": "posted", "type": "date"}]}
    answer = metadata.answer_database_metadata("List all columns in CUSTOM_DOC.", schema)
    assert answer["meta"]["operation"] == metadata.LIST_COLUMNS
    assert {row["column"] for row in answer["data"]} == {"id", "posted"}


def test_qualified_field_type_and_meaning_is_exact_metadata_lookup():
    from app.data_catalog.physical import load_physical_schema

    answer = metadata.answer_database_metadata("What is the data type and business meaning of VBRK.FKDAT?", load_physical_schema())
    assert answer["meta"]["operation"] == metadata.SEARCH_COLUMNS
    assert len(answer["data"]) == 1
    row = answer["data"][0]
    assert (row["table"].upper(), row["column"].lower()) == ("VBRK", "fkdat")
    assert row["type"]
    assert "billing" in row["meaning"].lower() and "date" in row["meaning"].lower()
    assert f"type: {row['type']}" in answer["summary"]
    assert row["meaning"] in answer["summary"]


def test_qualified_field_lookup_returns_catalog_type_without_sap_names():
    schema = {"DOCUMENT_EVENTS": [{"col": "event_time", "type": "timestamp"}]}
    answer = metadata.answer_database_metadata("Describe the data type of DOCUMENT_EVENTS.EVENT_TIME.", schema)
    assert [(row["table"], row["column"], row["type"]) for row in answer["data"]] == [("DOCUMENT_EVENTS", "event_time", "timestamp")]


def test_unknown_qualified_field_returns_no_verified_match():
    schema = {"DOCUMENT_EVENTS": [{"col": "event_time", "type": "timestamp"}]}
    answer = metadata.answer_database_metadata("What is the meaning of DOCUMENT_EVENTS.NONEXISTENT?", schema)
    assert answer["data"] == []
    assert "No verified columns matched" in answer["summary"]
