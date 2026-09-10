"""Regression: CAST must not be treated as a table name."""
from app.services.ai_native_pipeline import _schema_violations


def test_cast_in_expressions_not_unknown_table():
    sql = (
        'SELECT "VBRK"."vbeln", '
        'CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC) AS netwr '
        'FROM "VBRK" '
        'WHERE CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC) < 0 '
        'AND SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) = \'2000\' '
        "LIMIT 100"
    )
    viol = _schema_violations(sql)
    assert viol == [], viol


def test_cast_after_from_is_not_a_table():
    """Malformed LLM SQL must not produce false unknown-table CAST errors."""
    sql = 'SELECT CAST("VBRK"."netwr" AS NUMERIC) AS netwr FROM CAST(x AS int)'
    viol = _schema_violations(sql)
    assert not any("unknown table CAST" in v for v in viol)


def test_negative_sales_2000_rendered_plan_validates():
    from app.services.adaptive_structured_sql import (
        PlanField,
        PlanFilter,
        StructuredQueryPlan,
        render_sql_from_plan,
        validate_query_plan,
    )

    plan = StructuredQueryPlan(
        question="negative sales 2000",
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
        semantic_requirements={
            "condition": {"measure_operator": "<", "measure_value": 0},
            "time_filter": {"value": "2000"},
        },
        limit=100,
    )
    assert validate_query_plan(plan) == []
    sql = render_sql_from_plan(plan)
    assert '"VBRK"' in sql
    viol = _schema_violations(sql)
    assert not any("unknown table CAST" in v for v in viol), viol
