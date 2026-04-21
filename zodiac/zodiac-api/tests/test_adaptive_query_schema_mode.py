from app.api.adaptive_query import (
    _build_schema_structure_payload,
    _build_schema_structure_answer,
    _extract_known_columns_from_question,
    _looks_like_schema_structure_question,
    _schema_reference_violations,
    _sql_guardrail_violations,
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


def test_sql_guardrail_flags_invoice_header_logic_when_vbrk_netwr_missing() -> None:
    question = "show zero and negative invoice values"
    sql = """
    SELECT p."vbeln", SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "vbrp" p
    GROUP BY p."vbeln"
    HAVING SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) > 0
    """
    violations = _sql_guardrail_violations(question, sql)
    joined = " | ".join(violations).lower()
    assert "vbrk.netwr" in joined
    assert "having > 0" in joined


def test_sql_guardrail_flags_irrelevant_industry_table() -> None:
    question = "show invoices by customer"
    sql = """
    SELECT k."vbeln", c."name1"
    FROM "VBRK" k
    LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr"
    LEFT JOIN "T016T" t ON c."brsch" = t."brsch"
    """
    violations = _sql_guardrail_violations(question, sql)
    assert any("t016t" in v.lower() for v in violations)


def test_schema_reference_violations_detect_unknown_table_and_column() -> None:
    sql = """
    SELECT "VBRK"."not_a_real_column"
    FROM "VBRK"
    JOIN "NOT_A_TABLE" x ON 1=1
    """
    violations = _schema_reference_violations(sql)
    joined = " | ".join(violations).lower()
    assert "unknown table reference" in joined
    assert "unknown column" in joined


def test_schema_reference_violations_accept_valid_vbrk_vbrp_query() -> None:
    sql = """
    SELECT k."vbeln", k."fkdat", k."netwr", p."matnr", p."netwr"
    FROM "VBRK" k
    JOIN "vbrp" p ON k."vbeln" = p."vbeln"
    """
    violations = _schema_reference_violations(sql)
    assert violations == []

