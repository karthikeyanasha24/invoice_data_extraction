"""Tests for generic query repair (GROUP BY, measure ranking, currency validation)."""
from __future__ import annotations

from app.services.adaptive_query_repair import (
    build_measure_ranking_sql,
    column_required_for_question,
    prune_plan_for_aggregation,
    repair_grouping_error_sql,
    validate_monetary_result,
)
from app.services.adaptive_structured_sql import PlanField, StructuredQueryPlan


def test_erdat_not_required_for_material_quantity_ranking():
    assert not column_required_for_question("vbrp", "erdat", "Top 20 materials by billed quantity")


def test_repair_grouping_error_removes_erdat():
    bad = (
        'SELECT "vbrp"."matnr", SUM(vbrp.fkimg) AS "billed_quantity", "vbrp"."erdat" '
        'FROM vbrp GROUP BY "vbrp"."matnr" ORDER BY 2 DESC LIMIT 20'
    )
    err = 'column "vbrp.erdat" must appear in the GROUP BY clause or be used in an aggregate function'
    fixed = repair_grouping_error_sql(bad, "Top 20 materials by billed quantity", err)
    assert fixed
    assert "erdat" not in fixed.lower()


def test_build_measure_ranking_materials():
    sql = build_measure_ranking_sql("Top 20 materials by billed quantity", ["vbrp", "MAKT"], {})
    assert sql
    assert "fkimg" in sql.lower() or "billed_quantity" in sql.lower()
    assert "erdat" not in sql.lower()
    assert "GROUP BY" in sql.upper()
    assert "LIMIT 20" in sql


def test_prune_plan_drops_erdat_from_select():
    plan = StructuredQueryPlan(
        question="Top 20 materials by billed quantity",
        tables=["vbrp", "MAKT"],
        select=[
            PlanField(type="column", table="vbrp", column="matnr"),
            PlanField(type="column", table="MAKT", column="maktx"),
            PlanField(type="column", table="vbrp", column="fkimg"),
            PlanField(type="column", table="vbrp", column="erdat"),
        ],
        semantic_requirements={"ranking": {"limit": 20}, "measure": {"concept": "quantity", "aggregation": "SUM"}},
    )
    prune_plan_for_aggregation(plan)
    cols = {pf.column.lower() for pf in plan.select if pf.type == "column"}
    assert "erdat" not in cols
    assert "fkimg" in cols


def test_validate_monetary_result_flags_multi_currency():
    rows = [
        {"total_sales": 100, "currency": "INR"},
        {"total_sales": 90, "currency": "EUR"},
    ]
    warnings = validate_monetary_result(rows, "Which customer has the highest sales?")
    assert warnings
    assert "MULTI_CURRENCY" in warnings[0]
