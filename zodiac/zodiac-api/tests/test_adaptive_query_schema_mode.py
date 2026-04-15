from app.api.adaptive_query import (
    _build_schema_structure_payload,
    _build_schema_structure_answer,
    _extract_known_columns_from_question,
    _looks_like_schema_structure_question,
)


def test_schema_structure_detector_matches_column_table_question() -> None:
    assert _looks_like_schema_structure_question("which tables contain netwr and fkdat columns")


def test_schema_structure_detector_ignores_regular_metric_question() -> None:
    assert not _looks_like_schema_structure_question("show top 10 customers by billing amount")


def test_extract_known_columns_from_question_finds_sap_columns() -> None:
    cols = _extract_known_columns_from_question("please compare netwr and fkdat by vbeln")
    low = {c.lower() for c in cols}
    assert "netwr" in low or "fkdat" in low or "vbeln" in low


def test_build_schema_structure_answer_includes_shared_columns_for_named_tables() -> None:
    ans = _build_schema_structure_answer("what common columns are shared between VBRK and VBRP")
    low = ans.lower()
    assert "schema lookup" in low
    assert "shared columns between" in low
    assert "vbrk" in low and "vbrp" in low


def test_schema_structure_payload_includes_intent_confidence_and_suggestions() -> None:
    payload = _build_schema_structure_payload("which tables contain netwr")
    assert payload.get("type") == "analysis"
    assert payload.get("schemaIntentType") in {
        "column_lookup",
        "schema_lookup",
        "table_profile",
        "join_candidates",
        "datatype_lookup",
        "coverage_gap",
    }
    assert isinstance(payload.get("confidence"), float)
    assert "answer" in payload and isinstance(payload.get("answer"), str)
    assert "suggestions" in payload and isinstance(payload.get("suggestions"), list)
    assert isinstance(payload.get("matches"), dict)
    assert "tables" in payload.get("matches", {})
    assert "columns" in payload.get("matches", {})


def test_schema_structure_payload_recovers_near_miss_table_token() -> None:
    payload = _build_schema_structure_payload("show columns in vbrick")
    low = str(payload.get("answer") or "").lower()
    assert "vbrk" in low


def test_schema_structure_payload_recovers_near_miss_column_token() -> None:
    payload = _build_schema_structure_payload("which table has netwar")
    low = str(payload.get("answer") or "").lower()
    assert "netwr" in low


def test_schema_structure_payload_sets_datatype_intent() -> None:
    payload = _build_schema_structure_payload("what is the data type of netwr")
    assert payload.get("schemaIntentType") == "datatype_lookup"


def test_schema_structure_payload_sets_coverage_gap_and_clarification() -> None:
    payload = _build_schema_structure_payload("explain this business domain deeply")
    assert payload.get("schemaIntentType") == "coverage_gap"
    assert payload.get("clarifyingQuestion")

