"""Tests for four-stage schema intelligence pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.four_stage_db_pipeline import (
    VerifiedDbContext,
    _apply_followup_to_context,
    _deterministic_sql_if_known,
    _question_needs_operational_tables,
)
from app.services.schema_intelligence_registry import get_schema_registry


def test_schema_registry_loads_once():
    reg = get_schema_registry()
    reg.ensure_loaded()
    assert len(reg.all_table_names(include_operational=True)) > 50
    assert reg.table_exists("vbrp") or reg.table_exists("VBRP")


def test_sat_question_includes_operational_tables():
    assert _question_needs_operational_tables("Show SAT processing log steps that failed")


def test_sat_concept_maps_to_sat_processing_logs():
    reg = get_schema_registry()
    scored = reg.score_tables_for_question(
        "Show SAT processing log steps that failed and their error messages",
        include_operational=True,
    )
    tables = [t for t, _, _ in scored]
    assert any("sat_processing" in t.lower() for t in tables)


def test_customer_ranking_deterministic_sql():
    ctx = VerifiedDbContext(question="Show top 10 customers by billing revenue", tables=["vbrp", "VBRK", "KNA1"])
    sql = _deterministic_sql_if_known(ctx.question, ctx)
    assert sql
    assert "vbrp" in sql.lower()
    assert "LIMIT 10" in sql


def test_material_quantity_deterministic_sql():
    ctx = VerifiedDbContext(question="Show top 20 materials by billed quantity", tables=["vbrp", "MAKT"])
    sql = _deterministic_sql_if_known(ctx.question, ctx)
    assert sql
    assert "fkimg" in sql.lower()
    assert "LIMIT 20" in sql


def test_followup_reuses_verified_context():
    prior = {
        "verified_db_context": {
            "question": "Show top 10 customers by billing revenue",
            "tables": ["vbrp", "VBRK", "KNA1"],
            "columns": ["vbrp.netwr", "KNA1.name1"],
            "relationships": [],
        }
    }
    ctx = _apply_followup_to_context("Show only the top 3", prior)
    assert ctx is not None
    assert ctx.tables == ["vbrp", "VBRK", "KNA1"]
    assert ctx.pipeline_log.get("followup_reuse") is True


@patch("app.services.four_stage_db_pipeline.pipeline1_table_selection")
@patch("app.services.four_stage_db_pipeline.pipeline2_column_selection")
@patch("app.services.four_stage_db_pipeline.pipeline3_sql_generation")
@patch("app.services.four_stage_db_pipeline.pipeline4_result_analysis")
@patch("app.services.four_stage_db_pipeline._validate_sql_against_context", return_value=[])
def test_run_four_stage_data_limitation(mock_val, mock_p4, mock_p3, mock_p2, mock_p1):
    from app.services.four_stage_db_pipeline import run_four_stage_database_query

    def p1_side(q, ctx):
        ctx.pipeline_log["data_limitation"] = "No SAT tables"
        ctx.tables = []

    mock_p1.side_effect = p1_side
    mock_p3.return_value = ""
    out = run_four_stage_database_query(
        "Show SAT processing log steps that failed",
        MagicMock(),
        lambda *_a, **_k: [],
        prior_plan=None,
    )
    assert out.get("error") == "data_limitation"
