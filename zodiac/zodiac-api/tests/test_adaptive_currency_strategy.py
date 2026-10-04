"""Tests for adaptive currency strategy."""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from app.services.adaptive_currency_strategy import (
    apply_currency_strategy_to_sql,
    inject_currency_filter_sql,
    is_currency_validation_error,
    resolve_currency_strategy,
    requests_unfiltered_currency_scope,
    strip_currency_filter_predicates,
    sql_groups_currency_dimension,
    CurrencyStrategy,
)


def test_is_currency_validation_error():
    err = [
        "Ranking/breakdown over summed NETWR must handle currency: include VBRK.WAERK in GROUP BY"
    ]
    assert is_currency_validation_error(err)


def test_inject_currency_filter_with_table_alias():
    sql = (
        'SELECT TRIM(k."kunag") AS customer_id, SUM(CAST(p."netwr" AS NUMERIC)) AS total '
        'FROM "vbrp" p JOIN "VBRK" k ON p."vbeln" = k."vbeln" '
        'GROUP BY 1 ORDER BY total DESC LIMIT 5'
    )
    fixed = inject_currency_filter_sql(sql, "VBRK", "waerk", "USD")
    assert "k.\"waerk\"" in fixed or 'k."waerk"' in fixed
    assert '"VBRK"."waerk"' not in fixed


def test_repair_table_qualifier_mismatch():
    from app.services.adaptive_currency_strategy import repair_table_qualifier_mismatch

    sql = (
        'SELECT k."kunag" FROM "vbrp" p JOIN "VBRK" k ON p."vbeln" = k."vbeln" '
        'WHERE TRIM(CAST("VBRK"."waerk" AS TEXT)) = \'USD\''
    )
    fixed = repair_table_qualifier_mismatch(sql, "VBRK")
    assert 'k."waerk"' in fixed
    assert '"VBRK"."waerk"' not in fixed


def test_inject_does_not_create_second_where_after_bare_from():
    """FROM \"VBRK\"\\nWHERE ... must not become ... AND waerk=USD WHERE waerk=USD."""
    import re

    sql = (
        'SELECT SUM(CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "total_sales", '
        '"VBRK"."fkdat", SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) AS "year"\n'
        'FROM "VBRK"\n'
        'WHERE TRIM(CAST("VBRK"."fkdat" AS TEXT)) <> \'\' '
        "AND SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4) = '2000'\n"
        'GROUP BY "VBRK"."fkdat"'
    )
    fixed = inject_currency_filter_sql(sql, "VBRK", "waerk", "USD")
    assert len(re.findall(r"\bWHERE\b", fixed, flags=re.I)) == 1
    assert "waerk" in fixed.lower()
    assert "USD" in fixed


def test_inject_skips_when_quoted_waerk_already_filtered():
    sql = (
        'SELECT SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS total FROM "VBRK" '
        'WHERE SUBSTRING("VBRK"."fkdat", 1, 4) = \'2000\' AND "VBRK"."waerk" = \'USD\' '
        'GROUP BY "VBRK"."fkdat"'
    )
    fixed = inject_currency_filter_sql(sql, "VBRK", "waerk", "USD")
    assert fixed == sql
    assert len(__import__("re").findall(r"\bWHERE\b", fixed, flags=__import__("re").I)) == 1


def test_inject_currency_filter():
    sql = 'SELECT SUM(CAST("VBRK"."netwr" AS NUMERIC)) FROM "VBRK" GROUP BY "VBRK"."kunag" ORDER BY 1 DESC LIMIT 5'
    fixed = inject_currency_filter_sql(sql, "VBRK", "waerk", "EUR")
    assert "waerk" in fixed.lower()
    assert "EUR" in fixed


def test_apply_filter_strategy():
    strategy = CurrencyStrategy(
        mode="filter",
        currency_table="VBRK",
        currency_column="waerk",
        filter_currency="EUR",
    )
    sql = 'SELECT SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS total FROM "VBRK"'
    out = apply_currency_strategy_to_sql(sql, strategy)
    assert "EUR" in out
    assert "waerk" in out.lower()


def test_resolve_single_currency_strategy():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "EUR", "row_count": 1000},
    ]
    strategy = resolve_currency_strategy(
        db,
        tables=["VBRK", "KNA1"],
        question="top 5 customers by billed sales",
    )
    assert strategy is not None
    assert strategy.mode == "filter"
    assert strategy.filter_currency == "EUR"


def test_resolve_dominant_currency_strategy():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "EUR", "row_count": 900},
        {"currency": "USD", "row_count": 100},
    ]
    strategy = resolve_currency_strategy(
        db,
        tables=["VBRK"],
        question="top 5 customers by billed sales",
    )
    assert strategy is not None
    assert strategy.mode == "group_by"
    assert strategy.filter_currency is None


def test_resolve_multi_currency_group_by():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "EUR", "row_count": 400},
        {"currency": "USD", "row_count": 350},
        {"currency": "GBP", "row_count": 250},
    ]
    strategy = resolve_currency_strategy(
        db,
        tables=["VBRK"],
        question="top 5 customers by billed sales",
    )
    assert strategy is not None
    assert strategy.mode == "group_by"
    assert strategy.multi_currency is True


def test_explicit_currency_code_is_not_limited_to_a_curated_list():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "ZAR", "row_count": 10},
        {"currency": "USD", "row_count": 8},
    ]

    strategy = resolve_currency_strategy(
        db,
        tables=["VBRK"],
        question="Show billed sales in currency ZAR.",
    )

    assert strategy is not None
    assert strategy.mode == "filter"
    assert strategy.filter_currency == "ZAR"


def test_unrequested_currency_filter_is_removed_without_losing_year_scope():
    sql = (
        'SELECT k."land1" AS country, SUM(k."netwr") AS billed_sales '
        'FROM "VBRK" k WHERE TRIM(CAST(k."waerk" AS TEXT)) = \'USD\' '
        'AND SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4) = \'2017\' '
        'GROUP BY k."land1" ORDER BY billed_sales DESC LIMIT 5'
    )
    cleaned = strip_currency_filter_predicates(sql)
    assert "USD" not in cleaned
    assert "2017" in cleaned
    assert "GROUP BY k.\"land1\"" in cleaned


def test_unfiltered_currency_followup_keeps_year_and_groups_currency():
    question = (
        "For the original ranking, show top 5 country and currency pairs "
        "in the same year; do not apply a currency filter."
    )
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "USD", "row_count": 900},
        {"currency": "EUR", "row_count": 100},
    ]
    strategy = resolve_currency_strategy(db, tables=["VBRK"], question=question)
    assert requests_unfiltered_currency_scope(question)
    assert strategy is not None and strategy.mode == "group_by"
    sql = (
        'SELECT k."land1" AS country, SUM(k."netwr") AS billed_sales '
        'FROM "VBRK" k WHERE k."waerk" = \'USD\' '
        'AND SUBSTRING(k."fkdat", 1, 4) = \'2017\' '
        'GROUP BY k."land1" ORDER BY billed_sales DESC LIMIT 5'
    )
    cleaned = strip_currency_filter_predicates(sql)
    grouped = apply_currency_strategy_to_sql(cleaned, strategy)
    assert "USD" not in grouped
    assert "2017" in grouped
    assert 'k."waerk"' in grouped
    assert re.search(r"GROUP BY[^\n]*waerk", grouped, re.I)


def test_currency_dimension_detector_recognizes_grouped_currency_inside_cte():
    sql = (
        'WITH grouped AS (SELECT TRIM(c."land1") AS "country", '
        'k."waerk" AS "currency", SUM(k."netwr") AS "total_sales" '
        'FROM "VBRK" k JOIN "KNA1" c ON c."kunnr" = k."kunag" '
        'GROUP BY TRIM(c."land1"), k."waerk") '
        'SELECT grouped."country", grouped."currency", grouped."total_sales" FROM grouped'
    )
    assert sql_groups_currency_dimension(sql)


def test_pipeline_preserves_existing_currency_grouping_without_reinferring_table():
    from app.services.four_stage_db_pipeline import VerifiedDbContext, _apply_currency_if_needed

    question = (
        "Show the top five countries by billed sales in calendar year 2017, "
        "with billing currency shown as a field. Do not filter to one currency."
    )
    sql = (
        'WITH grouped AS (SELECT TRIM(c."land1") AS "country", '
        'k."waerk" AS "currency", SUM(k."netwr") AS "total_sales" '
        'FROM "VBRK" k JOIN "KNA1" c ON c."kunnr" = k."kunag" '
        'WHERE SUBSTRING(k."fkdat", 1, 4) = \'2017\' '
        'GROUP BY TRIM(c."land1"), k."waerk") '
        'SELECT grouped."country", grouped."currency", grouped."total_sales" FROM grouped'
    )
    ctx = VerifiedDbContext(
        question=question,
        tables=["KNA1", "VBAK", "VBRK"],
        semantic_requirements={"measure": {"concept": "sales", "aggregation": "SUM"}},
    )
    db = MagicMock()
    with patch(
        "app.services.adaptive_currency_strategy.resolve_currency_strategy",
        side_effect=AssertionError("already-grouped SQL must not be mutated"),
    ):
        fixed = _apply_currency_if_needed(question, sql, ctx, db)
    assert fixed == sql


def test_pipeline_prioritizes_tables_referenced_by_query_for_currency_strategy():
    from unittest.mock import patch

    from app.services.four_stage_db_pipeline import VerifiedDbContext, _apply_currency_if_needed

    question = "Show billed sales by country in currency EUR."
    sql = 'SELECT SUM(k."netwr") AS billed_sales FROM "VBRK" k GROUP BY k."kunag"'
    ctx = VerifiedDbContext(question=question, tables=["VBAK", "KNA1", "VBRK"])
    with patch(
        "app.services.adaptive_currency_strategy.resolve_currency_strategy", return_value=None
    ) as resolve:
        _apply_currency_if_needed(question, sql, ctx, MagicMock())
    assert resolve.call_args.kwargs["tables"][:1] == ["VBRK"]


def test_pipeline_replaces_generated_currency_filter_with_user_scope():
    from app.services.four_stage_db_pipeline import VerifiedDbContext, _apply_currency_if_needed

    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "USD", "row_count": 900},
        {"currency": "EUR", "row_count": 100},
    ]
    question = (
        "Show the top 5 country and currency pairs for calendar year 2017; "
        "do not apply a currency filter."
    )
    context = VerifiedDbContext(
        question=question,
        tables=["VBRK"],
        semantic_requirements={"measure": {"concept": "sales", "aggregation": "SUM"}},
    )
    sql = (
        'SELECT k."land1" AS country, SUM(k."netwr") AS billed_sales '
        'FROM "VBRK" k WHERE k."waerk" = \'USD\' '
        'AND SUBSTRING(k."fkdat", 1, 4) = \'2017\' '
        'GROUP BY k."land1" ORDER BY billed_sales DESC LIMIT 5'
    )
    fixed = _apply_currency_if_needed(question, sql, context, db)
    assert "USD" not in fixed
    assert "2017" in fixed
    assert 'k."waerk"' in fixed
    assert re.search(r"GROUP BY[^\n]*waerk", fixed, re.I)


def test_pipeline_corrects_generated_currency_to_explicit_user_currency():
    from app.services.four_stage_db_pipeline import VerifiedDbContext, _apply_currency_if_needed

    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"currency": "USD", "row_count": 900},
        {"currency": "EUR", "row_count": 100},
    ]
    question = "Show billed sales by country for calendar year 2017 in currency EUR."
    context = VerifiedDbContext(question=question, tables=["VBRK"])
    sql = (
        'SELECT k."land1" AS country, SUM(k."netwr") AS billed_sales '
        'FROM "VBRK" k WHERE k."waerk" = \'USD\' '
        'AND SUBSTRING(k."fkdat", 1, 4) = \'2017\' GROUP BY k."land1"'
    )
    fixed = _apply_currency_if_needed(question, sql, context, db)
    assert "EUR" in fixed
    assert "USD" not in fixed
    assert "2017" in fixed
