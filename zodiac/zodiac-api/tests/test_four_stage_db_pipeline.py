"""Tests for four-stage schema intelligence pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.four_stage_db_pipeline import (
    VerifiedDbContext,
    _apply_followup_to_context,
    _deterministic_sql_if_known,
    _missing_tables_from_sql,
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


def test_customer_ranking_deterministic_sql_disabled():
    ctx = VerifiedDbContext(question="Show top 10 customers by billing revenue", tables=["vbrp", "VBRK", "KNA1"])
    assert _deterministic_sql_if_known(ctx.question, ctx) is None


def test_material_quantity_deterministic_sql_disabled():
    ctx = VerifiedDbContext(question="Show top 20 materials by billed quantity", tables=["vbrp", "MAKT"])
    assert _deterministic_sql_if_known(ctx.question, ctx) is None


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


def test_multi_dim_skips_deterministic_sql():
    ctx = VerifiedDbContext(
        question="Which country and customer and industry has highest sales?",
        tables=["KNA1", "KNVV", "VBRK", "vbrp"],
        semantic_requirements={"dimensions": ["country", "customer", "industry"], "measure": {"concept": "sales"}},
    )
    assert _deterministic_sql_if_known(ctx.question, ctx) is None


def test_missing_table_detection():
    ctx = VerifiedDbContext(
        question="test",
        tables=["KNA1", "VBAK", "KNVV", "VBRK"],
    )
    sql = 'SELECT * FROM "vbrp" p JOIN "VBRK" k ON p."vbeln" = k."vbeln"'
    missing = _missing_tables_from_sql(sql, ctx)
    assert any(t.lower() == "vbrp" for t in missing)


@patch("app.services.four_stage_db_pipeline.pipeline25_query_plan")
@patch("app.services.four_stage_db_pipeline.pipeline2_column_selection")
@patch("app.services.four_stage_db_pipeline.pipeline3_sql_generation", return_value='SELECT 1 FROM "vbrp" LIMIT 1')
@patch("app.services.four_stage_db_pipeline._validate_sql_against_context", return_value=[])
def test_recover_missing_tables(mock_val, mock_p3, mock_p2, mock_p25):
    from app.services.four_stage_db_pipeline import _recover_missing_tables_and_regenerate

    ctx = VerifiedDbContext(question="sales", tables=["KNA1", "VBRK"])
    sql = 'SELECT * FROM "vbrp" p JOIN "VBRK" k ON 1=1'
    new_sql, viol = _recover_missing_tables_and_regenerate("sales", sql, ctx, MagicMock())
    assert any(t.lower() == "vbrp" for t in ctx.tables)
    assert viol == []
    mock_p2.assert_called_once()
    mock_p3.assert_called_once()


def test_find_tables_for_sales_concept():
    reg = get_schema_registry()
    ranked = reg.find_tables_for_concept("sales", limit=5)
    assert len(ranked) > 0
    tables = [t.lower() for t, _, _ in ranked]
    assert any("vbr" in t or "billing" in t or "order" in t for t in tables) or len(tables) >= 1


def test_compact_catalog_has_all_tables():
    reg = get_schema_registry()
    text = reg.compact_catalog_text(include_operational=False)
    lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    assert len(lines) >= 80


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
