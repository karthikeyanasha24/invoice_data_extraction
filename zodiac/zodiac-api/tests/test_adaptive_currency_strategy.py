"""Tests for adaptive currency strategy."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.adaptive_currency_strategy import (
    apply_currency_strategy_to_sql,
    inject_currency_filter_sql,
    is_currency_validation_error,
    resolve_currency_strategy,
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
    assert strategy.mode == "filter"
    assert strategy.filter_currency == "EUR"


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
