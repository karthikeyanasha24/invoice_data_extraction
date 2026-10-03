from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.adaptive_analyst.chat_memory import compact_sql_lineage, relevant_conversation
from app.services.adaptive_analyst.database_metadata import (
    SEARCH_COLUMNS,
    answer_database_metadata,
    classify_metadata_operation,
)
from app.services.adaptive_analyst.understanding import (
    _context_block,
    _schema_semantics_evidence,
    is_prior_turn_discourse,
    is_referential_database_action,
)
from app.services.analytical_operations import extract_analytical_operations
from app.services.adaptive_structured_sql import (
    PlanField,
    StructuredQueryPlan,
    _apply_period_compare_fields,
    build_dimension_ranking_sql,
)
from app.services.four_stage_db_pipeline import (
    VerifiedDbContext,
    _apply_followup_to_context,
    _contains_unresolved_sql_value,
    _resolve_latest_data_years,
)
from app.services.result_first_followup import try_answer_from_prior_rows
from app.services.semantic_requirements import required_semantics
from app.data_catalog.physical import load_physical_schema


def test_specific_sap_field_metadata_returns_matching_columns_only():
    question = "For VBRK, list the exact column names for billing date and billing document number."
    plan = classify_metadata_operation(question, schema=load_physical_schema())
    assert plan is not None
    assert plan.operation == SEARCH_COLUMNS
    assert plan.search_terms == ["billing date", "billing document number"]

    answer = answer_database_metadata(question, load_physical_schema())
    assert answer is not None
    assert {row["column"].lower() for row in answer["data"]} == {"fkdat", "vbeln"}


def test_table_search_uses_catalog_grain_and_domain_descriptions():
    answer = answer_database_metadata(
        "Which tables contain billing or invoice header data?", load_physical_schema()
    )
    assert answer is not None
    assert answer["data"][0]["table"] == "VBRK"
    assert len(answer["data"]) <= 5


def test_count_by_calendar_year_discards_llm_grain_and_measure_noise():
    req = required_semantics(
        "Break that count down by calendar year using the billing date.",
        {
            "dimensions": ["customer", "billing_date"],
            "group_by": ["customer", "billing_date"],
            "measure": {"concept": "revenue", "aggregation": "SUM"},
            "ranking": {"direction": "DESC", "limit": 10},
        },
    )
    assert req["dimensions"] == ["year"]
    assert req["group_by"] == ["year"]
    assert req["measure"] == {"concept": "count", "aggregation": "COUNT"}
    assert req.get("ranking") is None


def test_ungrouped_period_comparison_preserves_both_requested_changes():
    req = required_semantics(
        "Compare 2001 with 2000 using both absolute and percent change.",
        {
            "dimensions": ["customer", "billing_date"],
            "group_by": ["customer"],
            "ranking": {"direction": "DESC", "limit": 10},
            "measure": {"concept": "revenue", "aggregation": "SUM"},
        },
    )
    assert req["dimensions"] == []
    assert req["group_by"] == []
    assert req.get("ranking") is None
    assert req["period_compare"]["calculation"] == "both"


def test_explicit_top_five_wins_over_llm_top_ten():
    req = required_semantics(
        "Show the five countries with the highest billed sales.",
        {"dimensions": ["customer"], "ranking": {"direction": "DESC", "limit": 10}},
    )
    assert req["ranking"]["limit"] == 5
    assert req["dimensions"] == ["country"]
    sql = build_dimension_ranking_sql(
        "Show the five countries with the highest billed sales.",
        ["VBRK", "VBRP", "KNA1"],
        req["semantic"],
    )
    assert sql is not None
    assert sql.rstrip().endswith("LIMIT 5")


def test_latest_year_questions_get_dynamic_relative_semantics():
    question = "How many sales orders were created in the latest full calendar year?"
    req = required_semantics(question)
    assert req["measure"] == {"concept": "sales_order", "aggregation": "COUNT"}
    assert req["date_filter"]["type"] == "latest_data_years"
    assert req["date_filter"]["count"] == 1

    question = "For that country, show billed sales by year for the latest two full years in the data."
    req = required_semantics(question)
    assert req["group_by"] == ["year"]
    assert req["date_filter"]["period"] == "latest_two_full_years"
    assert req["date_filter"]["count"] == 2


def test_latest_data_year_resolution_uses_schema_meaning_and_verified_years():
    question = "Show billed sales by year for the latest two full years."
    ctx = VerifiedDbContext(
        question=question,
        tables=["VBRK"],
        columns=["VBRK.ERDAT", "VBRK.FKDAT"],
        semantic_requirements={"time_filter": {"relative": "latest_two_full_years"}},
    )
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        ("2001", "20011231", "19991231"), ("2000", "20011231", "19991231")
    ]

    assert _resolve_latest_data_years(question, ctx, db) is True
    executed_sql = str(db.execute.call_args.args[0])
    assert '"VBRK"."FKDAT"' in executed_sql
    assert ctx.semantic_requirements["time_filter"]["years"] == ["2000", "2001"]
    assert ctx.semantic_requirements["time_filter"]["start_yyyymmdd"] == "20000101"
    assert ctx.semantic_requirements["time_filter"]["end_yyyymmdd"] == "20020101"


def test_both_period_change_sql_fields_are_generated():
    period = {
        "base_period": {"year": "2000"},
        "comparison_period": {"year": "2001"},
        "calculation": "both",
    }
    plan = StructuredQueryPlan(
        tables=["VBRK", "VBRP"],
        select=[
            PlanField(type="column", table="VBRK", column="vbeln", alias="billing_document"),
            PlanField(type="column", table="VBRP", column="netwr", alias="sales", purpose="measure"),
        ],
        semantic_requirements={"measure": {"concept": "revenue"}},
        period_compare=period,
    )
    with (
        patch("app.services.adaptive_structured_sql._find_date_column", return_value=("VBRK", "fkdat")),
        patch("app.services.adaptive_structured_sql._find_measure_column", return_value=("VBRP", "netwr")),
    ):
        _apply_period_compare_fields(plan, plan.semantic_requirements)
    aliases = {field.alias for field in plan.select}
    assert {"period_a", "period_b", "change", "pct_change"} <= aliases


def test_result_followup_can_rank_a_country_from_prior_rows():
    rows = [
        {"country": "US", "total_billed_sales": "7,000"},
        {"country": "DE", "total_billed_sales": "5,000"},
    ]
    result = try_answer_from_prior_rows("Which country was highest in that result?", rows)
    assert result is not None
    assert result["answer_status"] == "SUCCESS"
    assert result["data"][0]["country"] == "US"


def test_followup_routing_distinguishes_recall_from_database_augmentation():
    recall = "Earlier you counted billing documents; what was the count and which table and column did SQL count?"
    augment = "Add the customer and billing date for those documents."
    assert is_prior_turn_discourse(recall, has_prior=True)
    assert not is_referential_database_action(recall, has_prior=True)
    assert is_referential_database_action(augment, has_prior=True)


def test_database_augmentation_reuses_prior_verified_tables_and_flags_requery():
    prior = {
        "verified_db_context": {
            "tables": ["VBRK", "VBRP"],
            "columns": ["VBRK.VBELN", "VBRP.NETWR"],
            "joins": [],
            "relationships": [],
        }
    }
    ctx = _apply_followup_to_context(
        "Add the customer and billing date for those documents.", prior
    )
    assert ctx is not None
    assert ctx.pipeline_log["followup_requery"] is True
    assert set(ctx.tables) == {"VBRK", "VBRP"}


def test_sql_placeholder_values_are_rejected_before_execution():
    assert _contains_unresolved_sql_value(
        'SELECT * FROM "VBRK" WHERE "VBELN" = <document_id>'
    )
    assert _contains_unresolved_sql_value('SELECT * FROM "VBRK" WHERE "VBELN" = your_document_id')
    assert not _contains_unresolved_sql_value('SELECT * FROM "VBRK" WHERE "VBELN" = \'0000000001\'')


def test_retrieved_memory_keeps_old_query_and_sql_lineage_without_literals():
    turns = [
        {"role": "user", "content": "How many billing documents are in the database?"},
        {
            "role": "assistant",
            "content": "35,057 billing documents. Verified SQL structure: SELECT COUNT(VBRK.VBELN) FROM VBRK WHERE VBRK.FKDAT >= ?",
        },
    ]
    for index in range(10):
        turns.extend(
            [
                {"role": "user", "content": f"Tell me about unrelated topic {index}."},
                {"role": "assistant", "content": f"An unrelated explanation {index}."},
            ]
        )
    retrieved = relevant_conversation(
        "Earlier you counted billing documents; what was the count and which table and column did SQL count?",
        turns,
        recent_limit=6,
    )
    content = "\n".join(turn["content"] for turn in retrieved)
    assert "35,057" in content
    assert "VBRK.VBELN" in content
    assert "billing documents" in content

    compact = compact_sql_lineage(
        "SELECT COUNT(\"VBRK\".\"VBELN\") FROM \"VBRK\" "
        "WHERE \"VBRK\".\"FKDAT\" >= '20000101' LIMIT 10"
    )
    assert "VBELN" in compact and "FKDAT" in compact
    assert "20000101" not in compact and "LIMIT 10" not in compact


def test_period_recall_points_to_most_recent_user_time_request():
    recent_turns = [
        {"role": "user", "content": "For that country, show billed sales by year for the latest two full years in the data."},
        {"role": "assistant", "content": "I will compare the latest two full years."},
        {"role": "user", "content": "Which five materials had the highest billed sales in the latest full year?"},
        {"role": "assistant", "content": "Here are the materials."},
        {"role": "user", "content": "What is a billing document in SAP?"},
        {"role": "assistant", "content": "It represents a customer billing transaction."},
    ]
    context = _context_block(
        prior_plan={"investigation_state": {"recent_turns": recent_turns}},
        current_question="Which period did I ask about most recently?",
    )
    assert "most recent prior user request specifying a time period" in context.lower()
    assert "latest full year" in context


def test_response_schema_evidence_prefers_primary_sap_field_labels():
    recent = [
        {"role": "user", "content": "For VBRK list columns."},
        {"role": "assistant", "content": "VBRK.vbeln and VBRK.fkdat are key fields."},
    ]
    doc_fields = _schema_semantics_evidence("What is a billing document number in SAP?", recent)
    date_fields = _schema_semantics_evidence("Which of those columns is the billing date?", recent)
    assert doc_fields[0].startswith("VBRK.VBELN:")
    assert date_fields[0].startswith("VBRK.FKDAT:")
