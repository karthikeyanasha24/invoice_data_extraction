"""Offline execution regressions for comparison rewrites and SQL scope checks."""
import sqlite3

import pytest
from sqlglot import exp, parse_one, transpile

from app.services.adaptive_structured_sql import (
    PlanField, PlanFilter, StructuredQueryPlan, _apply_period_compare_fields,
    _normalize_plan_expressions, _needs_aggregation, render_sql_from_plan,
    validate_query_plan, year_filter_expression,
)
from app.services.sql_structure import (
    has_date_year_predicate, has_group_aggregate, qualify_expression, sql_structure_errors, widen_year_predicate,
)


@pytest.mark.parametrize("base,comparison", [("2000", "2001"), ("2012", "2015"), ("2022", "2023")])
def test_comparison_rewrite_executes_both_periods_and_preserves_customer_filter(base, comparison):
    year = year_filter_expression("VBRK", "fkdat")
    semantic = {
        "dimensions": ["customer"], "group_by": ["customer"],
        "measure": {"concept": "sales", "aggregation": "none"},
        "period_compare": {"base_period": {"year": base}, "comparison_period": {"year": comparison}},
    }
    plan = StructuredQueryPlan(
        question=f"Show negative sales by customer in {base} and compare with {comparison}",
        tables=["VBRK"], semantic_requirements=semantic,
        select=[PlanField(type="column", table="VBRK", column="kunag", purpose="dimension")],
        filters=[
            PlanFilter(type="expression", expression=f"{year} = '{base}' AND VBRK.kunag = 'A'"),
            PlanFilter(type="expression", expression=f"{year} = '{base}'"),
            PlanFilter(type="column", table="VBRK", column="netwr", operator="<", value=0),
        ],
    )
    _normalize_plan_expressions(plan)
    _apply_period_compare_fields(plan, semantic)
    assert _needs_aggregation(plan)
    sql = render_sql_from_plan(plan)
    assert not sql_structure_errors(sql)
    assert 'GROUP BY "VBRK"."kunag"' in sql
    db = sqlite3.connect(":memory:")
    db.execute('CREATE TABLE "VBRK" (kunag TEXT, fkdat TEXT, netwr TEXT)')
    db.executemany('INSERT INTO "VBRK" VALUES (?, ?, ?)', [
        ("A", base + "0101", "-100"), ("A", base + "0601", "-20"),
        ("A", comparison + "0101", "-35"), ("A", comparison + "1201", "-5"),
        ("B", base + "0101", "-900"), ("A", "19990101", "-999"),
        ("A", comparison + "0102", "150"),
    ])
    try:
        rows = db.execute(transpile(sql, read="postgres", write="sqlite")[0]).fetchall()
        assert rows == [("A", -120, -40, 80)]
    finally:
        db.close()


def test_comparison_year_rewrite_does_not_change_another_date_or_customer_literal():
    year = year_filter_expression("VBRK", "fkdat")
    other = year_filter_expression("VBRK", "erdat")
    predicate = f"({year} = '2010' AND {other} = '2009') AND VBRK.kunag = '2010'"
    rewritten = widen_year_predicate(predicate, year, ["2010", "2011"])
    assert "= '2009'" in rewritten
    assert "kunag = '2010'" in rewritten
    assert "IN ('2010', '2011')" in rewritten


def test_numeric_year_wrapper_is_widened_but_month_bucket_is_preserved():
    year = year_filter_expression("VBRK", "fkdat")
    wrapped = f"CAST(NULLIF({year}, '') AS INTEGER)"
    predicate = f"{wrapped} = 2010 AND SUBSTRING(VBRK.fkdat, 5, 2) = '03'"
    result = widen_year_predicate(predicate, year, ["2010", "2011"])
    assert "IN ('2010', '2011')" in result
    assert "= '03'" in result
    sql = f'SELECT SUM(CASE WHEN {year}=\'2010\' THEN 1 END), SUM(CASE WHEN {year}=\'2011\' THEN 1 END) FROM "VBRK" WHERE {predicate}'
    assert any("excludes a period" in e for e in sql_structure_errors(sql))


@pytest.mark.parametrize("predicate", ["= '2000'", "IN ('2000')"])
def test_contradictory_comparison_filters_rejected(predicate):
    year = year_filter_expression("VBRK", "fkdat")
    sql = f'''SELECT "VBRK"."kunag",
        SUM(CASE WHEN {year} = '2000' THEN 1 ELSE 0 END),
        SUM(CASE WHEN {year} = '2001' THEN 1 ELSE 0 END)
        FROM "VBRK" WHERE {year} {predicate}
        AND {year} IN ('2000', '2001') GROUP BY "VBRK"."kunag"'''
    assert any("excludes a period" in e for e in sql_structure_errors(sql))


@pytest.mark.parametrize("projection,group", [
    ("k.kunag, SUM(k.netwr)", ""),
    ("k.kunag, k.fkdat, SUM(k.netwr)", "GROUP BY k.kunag"),
    ("k.netwr - SUM(k.netwr)", ""),
])
def test_mixed_scalar_aggregate_projection_rejected(projection, group):
    assert any("Ungrouped column" in e for e in sql_structure_errors(f'SELECT {projection} FROM "VBRK" k {group}'))


@pytest.mark.parametrize("sql", [
    'SELECT k.kunag, SUM(k.netwr) FROM "VBRK" k GROUP BY k.kunag',
    'SELECT SUBSTRING(k.fkdat, 1, 4) AS year, SUM(k.netwr) FROM "VBRK" k GROUP BY year',
    'SELECT SUBSTRING(k.fkdat, 1, 4), SUM(k.netwr) FROM "VBRK" k GROUP BY 1',
    'SELECT SUM(k.netwr) FROM "VBRK" k',
    'SELECT k.kunag, SUM(k.netwr) OVER (PARTITION BY k.kunag) FROM "VBRK" k',
    'SELECT c.kunag, (SELECT SUM(k.netwr) FROM "VBRK" k WHERE k.kunag=c.kunag) FROM "KNA1" c',
    'WITH cohort AS (SELECT k.kunag FROM "VBRK" k WHERE k.fkdat=\'20000101\') SELECT * FROM cohort',
])
def test_scope_checker_accepts_valid_groups_windows_and_nested_queries(sql):
    assert not sql_structure_errors(sql)


def test_aggregate_detection_is_local_to_expression_scope():
    assert has_group_aggregate('SUM("VBRK"."netwr")')
    assert not has_group_aggregate('SUM("VBRK"."netwr") OVER ()')
    assert not has_group_aggregate('(SELECT SUM("VBRK"."netwr") FROM "VBRK")')
    assert has_group_aggregate('SUM(SUM("VBRK"."netwr")) OVER ()')


def test_window_aggregate_still_requires_grouped_inputs_in_an_aggregate_query():
    bad = 'SELECT k.kunag, SUM(k.netwr) OVER (), COUNT(*) FROM "VBRK" k GROUP BY k.kunag'
    assert any("k.netwr" in e for e in sql_structure_errors(bad))
    good = 'SELECT k.kunag, SUM(SUM(k.netwr)) OVER (), COUNT(*) FROM "VBRK" k GROUP BY k.kunag'
    assert not sql_structure_errors(good)


@pytest.mark.parametrize('sql,expected', [
    ('WITH ranked AS (SELECT id, ROW_NUMBER() OVER (PARTITION BY currency ORDER BY amount) AS ordinal FROM facts) SELECT * FROM ranked WHERE ordinal <= 7', True),
    ('SELECT * FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY amount) AS ordinal FROM facts) r WHERE r.ordinal < 8', True),
    ('WITH ranked AS (SELECT id, ROW_NUMBER() OVER (ORDER BY amount) AS ordinal FROM facts) SELECT * FROM facts WHERE amount <= 7', False),
    ('WITH ranked AS (SELECT id, ROW_NUMBER() OVER (ORDER BY amount) AS ordinal FROM facts), unused AS (SELECT * FROM ranked WHERE ordinal <= 7) SELECT * FROM facts', False),
    ('WITH ranked AS (SELECT id, ROW_NUMBER() OVER (ORDER BY amount) AS ordinal FROM facts) SELECT * FROM ranked WHERE ordinal <= 7 OR id=1', False),
    ('WITH ranked AS (SELECT id, ROW_NUMBER() OVER () AS ordinal FROM facts) SELECT * FROM ranked WHERE ordinal <= 7', False),
    ('WITH ranked AS (SELECT id, ROW_NUMBER() OVER (ORDER BY amount) AS ordinal FROM facts) SELECT * FROM ranked WHERE ordinal <= 9', False),
])
def test_top_n_validation_tracks_ordered_rank_filters_in_used_query_scopes(sql, expected):
    from app.services.sql_structure import has_ranking_bound
    assert has_ranking_bound(sql, 7) is expected


@pytest.mark.parametrize("predicate", ["= '2017'", "IN ('2017', '2018')", "BETWEEN '2017' AND '2018'"])
def test_year_predicate_recognition_uses_where_scope(predicate):
    year = year_filter_expression("VBRK", "fkdat")
    assert has_date_year_predicate(f'SELECT 1 FROM "VBRK" WHERE {year} {predicate}', "fkdat", "2017")
    assert not has_date_year_predicate(f'SELECT {year}, \'2017\' FROM "VBRK"', "fkdat", "2017")
    assert not has_date_year_predicate(f'SELECT 1 FROM "VBRK" WHERE {year} = \'2018\' AND kunag=\'2017\'', "fkdat", "2017")


def test_comparison_drops_arbitrarily_named_year_group_and_preserves_base_ranking():
    year = year_filter_expression("VBRK", "fkdat")
    semantic = {
        "measure": {"concept": "sales"},
        "ranking": {"direction": "ASC", "limit": 10, "metric": "sales"},
        "period_compare": {"base_period": {"year": "2000"}, "comparison_period": {"year": "2001"}},
    }
    plan = StructuredQueryPlan(
        tables=["VBRK"], semantic_requirements=semantic,
        select=[PlanField(type="expression", expression=year, alias="billing_year")],
        group_by=[PlanField(type="expression", expression=year)],
    )
    _apply_period_compare_fields(plan, semantic)
    assert not any(field.alias == "billing_year" for field in plan.select)
    assert not plan.group_by
    assert plan.order_by == [{"field": "period_a", "direction": "ASC"}]


def test_verified_identifier_quoting_preserves_literals_and_aliases():
    assert qualify_expression("VBRK.fkdat || 'VBRK.fkdat'", ["VBRK"]) == '"VBRK"."fkdat" || \'VBRK.fkdat\''
    assert qualify_expression("k.fkdat", ["VBRK"]) == "k.fkdat"


def test_structured_plan_rejects_undeclared_subquery_scopes():
    plan = StructuredQueryPlan(
        question="Compare sales", tables=["VBRK"],
        select=[PlanField(type="expression", expression='(SELECT p.netwr FROM "VBRK" p)', alias="amount")],
    )
    assert any("nested query scopes" in e for e in validate_query_plan(plan))


@pytest.mark.parametrize("base,comparison", [("2000", "2001"), ("2012", "2015")])
@pytest.mark.parametrize("both_invoice_periods", [False, True])
@pytest.mark.parametrize("item_reference_route", [False, True])
def test_negative_invoice_cohort_and_linked_order_periods_execute_without_duplicate_sums(monkeypatch, base, comparison, both_invoice_periods, item_reference_route):
    import app.services.adaptive_structured_sql as structured

    columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "VBFA": {"vbeln", "vbelv"},
        "VBAK": {"vbeln", "erdat", "netwr", "waerk"},
    }
    if item_reference_route:
        columns['VBRP'] = {'vbeln', 'aubel'}
    monkeypatch.setattr(structured, "has_table", lambda t: t.upper() in columns)
    monkeypatch.setattr(structured, "has_column", lambda t, c: c in columns.get(t.upper(), set()))
    monkeypatch.setattr(structured, "resolve_table_name", lambda t: t.upper())
    invoice_question = (
        f"Independently select bottom 2 negative invoices for calendar years {base} and {comparison} by customer; "
        if both_invoice_periods else f"Show bottom 2 negative invoice billing documents in {base} by customer; "
    )
    semantic = {
        "measure": {"concept": "sales"},
        "ranking": {"direction": "ASC", "limit": 2},
        "period_compare": {"base_period": {"year": base}, "comparison_period": {"year": comparison}},
        "invoice_cohort_scope": "each_period" if both_invoice_periods else "base_period",
    }
    question = invoice_question + f"compare their linked sales orders in {base} versus {comparison} with both changes."
    sql = structured.build_linked_order_period_comparison_sql(question, list(columns))
    assert sql and not sql_structure_errors(sql)

    # Exercise the production acceptance path too: an unrelated grouped CTE
    # must not invalidate the invoice ranking window or select a fallback query.
    from app.services import four_stage_db_pipeline as pipeline
    ctx = pipeline.VerifiedDbContext(question, tables=list(columns), semantic_requirements=semantic)
    accepted = pipeline.pipeline3_sql_generation(question, ctx, templates_only=True)
    assert accepted
    assert ctx.pipeline_log['PIPELINE_3_SQL_GENERATION']['source'] == 'linked_order_period_comparison_template'

    # SQLite dialect adapters emulate PostgreSQL decimal division and ordered
    # STRING_AGG; the cohort, joins, DISTINCT and conditional sums are unchanged.
    tree = parse_one(sql, read="postgres")
    def sqlite_adapter(node):
        if isinstance(node, exp.Cast) and node.args["to"].is_type(exp.DataType.Type.DECIMAL):
            node.set("to", exp.DataType.build("REAL"))
        if isinstance(node, exp.GroupConcat):
            value = node.this
            if isinstance(value, exp.Order):
                value = value.this
            return exp.Anonymous(this="text_list", expressions=[value.copy()])
        return node
    sqlite_sql = tree.transform(sqlite_adapter).sql(dialect="sqlite")

    class TextList:
        def __init__(self):
            self.values = set()
        def step(self, value):
            if value is not None:
                self.values.add(str(value))
        def finalize(self):
            return ", ".join(sorted(self.values))

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.create_aggregate("text_list", 1, TextList)
    for table, names in columns.items():
        db.execute(f'CREATE TABLE "{table}" ({", ".join(sorted(names))})')
    db.executemany('INSERT INTO VBRK (vbeln,fkdat,kunag,netwr,waerk) VALUES (?,?,?,?,?)', [
        ("I1", base + "0201", "A", "-200", "USD"),
        ("I2", base + "0301", "B", "-10", "USD"),
        ("I3", comparison + "0201", "A", "-999", "USD"),
        ("I4", base + "0201", "A", "100", "USD"),
        ("I5", comparison + "0201", "B", "-5", "USD"),
    ])
    db.executemany('INSERT INTO VBAK (vbeln,erdat,netwr,waerk) VALUES (?,?,?,?)', [
        ("O1", base + "0101", "100", "USD"), ("O2", comparison + "0101", "150", "USD"),
        ("O3", comparison + "0101", "900", "EUR"), ("O4", base + "0101", "50", "USD"),
        ("O5", base + "0101", "9999", "USD"),
        ("O6", str(int(base) - 2) + "0101", "30", "USD"),
    ])
    db.executemany('INSERT INTO VBFA (vbeln,vbelv) VALUES (?,?)', [
        ("I1", "O1"), ("I1", "O1"), ("I1", "O2"), ("I1", "O3"),
        ("I2", "O4"), ("I3", "O5"), ("I4", "O5"),
    ])
    if item_reference_route:
        db.executemany('INSERT INTO VBRP (vbeln,aubel) VALUES (?,?)', [('I1','O1'), ('I1','O1'), ('I1','O2'), ('I5','O6')])
    else:
        db.execute('INSERT INTO VBFA (vbeln,vbelv) VALUES (?,?)', ('I5','O6'))
    try:
        rows = [dict(row) for row in db.execute(sqlite_sql)]
    finally:
        db.close()
    assert [row["billing_document"] for row in rows] == (["I1", "I2", "I3", "I5"] if both_invoice_periods else ["I1", "I2"])
    first, second = rows[:2]
    assert first[f"order_amount_{base}"] == 100
    assert first[f"order_amount_{comparison}"] == 150
    assert first[f"linked_order_count_{base}"] == 1
    assert first["absolute_change"] == 50
    assert first["percent_change"] == 50
    assert first["currency_mismatch_order_count"] == 1
    assert first["linked_sales_orders"] == "O1, O2, O3"
    assert second[f"order_amount_{comparison}"] is None
    assert second["absolute_change"] is None
    if both_invoice_periods:
        assert [(r['invoice_year'], r['invoice_rank']) for r in rows] == [(base, 1), (base, 2), (comparison, 1), (comparison, 2)]
        outside = rows[-1]
        assert outside['linked_sales_orders'] == 'O6'
        assert outside['linked_order_count_all_periods'] == 1
        assert outside['linked_order_count_outside_comparison'] == 1
        assert outside[f'order_amount_{base}'] is None
        assert outside[f'order_amount_{comparison}'] is None
