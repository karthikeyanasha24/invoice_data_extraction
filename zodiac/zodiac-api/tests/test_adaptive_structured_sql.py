"""Tests for structured query plan and SQL expression repair."""
from __future__ import annotations

from app.services.adaptive_structured_sql import (
    PlanField,
    PlanFilter,
    StructuredQueryPlan,
    classify_sql_execution_error,
    detect_expression_as_column_errors,
    repair_quoted_expressions_as_columns,
    render_sql_from_plan,
    validate_query_plan,
    year_filter_expression,
)


def test_repair_substring_quoted_as_column():
    bad = (
        'SELECT "VBRK"."vbeln", CAST("VBRK"."SUBSTRING(TRIM(fkdat),1,4)" AS integer) AS "year", '
        'CAST("VBRK"."netwr" AS numeric) AS "netwr" FROM "VBRK"'
    )
    fixed = repair_quoted_expressions_as_columns(bad)
    assert '"SUBSTRING' not in fixed or "SUBSTRING(TRIM" in fixed
    assert '"VBRK"."SUBSTRING' not in fixed
    assert detect_expression_as_column_errors(fixed) == []


def test_classify_expression_as_column_error():
    err = 'column VBRK.SUBSTRING(TRIM(fkdat),1,4) does not exist'
    assert classify_sql_execution_error(err) == "expression_as_column"


def test_repair_extract_on_text_fkdat():
    from app.services.adaptive_structured_sql import repair_extract_on_text_dates

    bad = 'SELECT EXTRACT(YEAR FROM "VBRK".fkdat) AS year FROM "VBRK"'
    fixed = repair_extract_on_text_dates(bad)
    assert "EXTRACT" not in fixed.upper()
    assert "SUBSTRING" in fixed.upper()
    assert '"VBRK"."fkdat"' in fixed


def test_build_master_list_customer_names():
    from app.services.adaptive_structured_sql import build_master_list_sql

    sql = build_master_list_sql("Show customer names only", ["KNA1"])
    assert sql
    assert "KNA1" in sql
    assert "name1" in sql
    assert "ILIKE" not in sql.upper()


def test_repair_absurd_literal_filter():
    from app.services.adaptive_structured_sql import repair_absurd_question_literal_filters

    bad = (
        'SELECT "KNA1"."name1" FROM "KNA1" '
        "WHERE name1 ILIKE '%names only%' LIMIT 50"
    )
    fixed = repair_absurd_question_literal_filters(bad, "Show customer names only")
    assert "names only" not in fixed.lower()


def test_build_multidim_ranking_country_customer_industry():
    from app.services.adaptive_structured_sql import build_multidim_ranking_sql

    sql = build_multidim_ranking_sql(
        "Which country, customer, and industry has the highest sales?",
        ["VBRK", "KNA1", "T016T"],
        {},
    )
    assert sql
    assert "VBRK" in sql
    assert "KNA1" in sql
    assert "T016T" in sql
    assert "vbrp" not in sql.lower()
    assert "GROUP BY" in sql.upper()
    assert "LIMIT 1" in sql


def test_build_filter_list_negative_sales_2000():
    from app.services.adaptive_structured_sql import build_filter_list_sql

    sql = build_filter_list_sql(
        "show me negatives sales for the year 2000",
        ["vbrp", "MAKT", "KNA1"],
        {},
    )
    assert sql
    assert "SUM(" not in sql.upper()
    assert "GROUP BY" not in sql.upper()
    assert "2000" in sql
    assert "< 0" in sql or "<0" in sql.replace(" ", "")
    assert "SUBSTRING" in sql.upper()
    assert "EXTRACT" not in sql.upper()


def test_detect_filter_list_from_question_text():
    from app.services.adaptive_structured_sql import detect_filter_list_intent

    assert detect_filter_list_intent("show me negative sales for the year 2000", {})
    assert detect_filter_list_intent("show me negatives sales for the year 2000", {})
    assert not detect_filter_list_intent("top 5 customers by billed sales", {})


def test_filter_list_question_does_not_aggregate():
    from app.services.adaptive_structured_sql import (
        PlanField,
        PlanFilter,
        StructuredQueryPlan,
        render_sql_from_plan,
        _needs_aggregation,
    )

    plan = StructuredQueryPlan(
        question="show negative sales 2000",
        tables=["VBRK"],
        select=[
            PlanField(type="column", table="VBRK", column="vbeln"),
            PlanField(type="column", table="VBRK", column="netwr"),
            PlanField(type="column", table="VBRK", column="fkdat"),
        ],
        filters=[
            PlanFilter(type="column", table="VBRK", column="netwr", operator="<", value=0),
            PlanFilter(
                type="expression",
                expression="SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4) = '2000'",
            ),
        ],
        semantic_requirements={
            "condition": {"measure_operator": "<", "measure_value": 0},
            "time_filter": {"value": "2000"},
            "measure": {"concept": "sales", "aggregation": "none"},
        },
        limit=100,
    )
    assert _needs_aggregation(plan) is False
    sql = render_sql_from_plan(plan)
    assert "SUM(" not in sql.upper()
    assert "2000" in sql
    assert "< 0" in sql or "<0" in sql.replace(" ", "")


def test_render_plan_negative_sales_2000():
    plan = StructuredQueryPlan(
        question="Show negative sales for 2000",
        tables=["VBRK"],
        select=[
            PlanField(type="column", table="VBRK", column="vbeln"),
            PlanField(type="column", table="VBRK", column="fkdat"),
            PlanField(type="column", table="VBRK", column="netwr"),
            PlanField(
                type="expression",
                expression='SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4)',
                alias="year",
            ),
        ],
        filters=[
            PlanFilter(type="column", table="VBRK", column="netwr", operator="<", value=0),
            PlanFilter(
                type="expression",
                expression="SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4) = '2000'",
            ),
        ],
    )
    assert validate_query_plan(plan) == []
    sql = render_sql_from_plan(plan)
    assert "netwr" in sql.lower()
    assert "< 0" in sql or "<0" in sql.replace(" ", "")
    assert "2000" in sql
    assert '"VBRK"."SUBSTRING' not in sql


def test_detect_bad_quoted_expression():
    bad = 'SELECT "VBRK"."SUBSTRING(TRIM(fkdat),1,4)" FROM "VBRK"'
    errors = detect_expression_as_column_errors(bad)
    assert len(errors) >= 1
