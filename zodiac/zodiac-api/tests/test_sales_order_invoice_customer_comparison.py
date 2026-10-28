from __future__ import annotations

import sqlite3

from app.services import adaptive_structured_sql as structured_sql
from app.services.four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
from app.services.agent_query_contract import RelationshipCatalog, identified_value_proof
from app.services.analyst_agent import _analysis_issues


_COLUMNS = {
    "VBAK": {"mandt", "vbeln", "kunnr", "audat", "netwr", "waerk"},
    "VBRK": {"mandt", "vbeln", "kunag", "fkdat", "netwr", "waerk", "fksto"},
    "KNA1": {"mandt", "kunnr", "land1", "name1"},
}


def _install_synthetic_schema(monkeypatch):
    monkeypatch.setattr(structured_sql, "has_table", lambda table: table.upper() in _COLUMNS)
    monkeypatch.setattr(
        structured_sql,
        "has_column",
        lambda table, column: column.lower() in _COLUMNS.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured_sql, "resolve_table_name", lambda table: table.upper())


def _seed_synthetic_database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.create_function("LPAD", 3, lambda value, width, fill: str(value or "").rjust(width, fill))
    db.executescript(
        """
        CREATE TABLE VBAK(mandt TEXT, vbeln TEXT, kunnr TEXT, audat TEXT, netwr TEXT, waerk TEXT);
        CREATE TABLE VBRK(mandt TEXT, vbeln TEXT, kunag TEXT, fkdat TEXT, netwr TEXT, waerk TEXT, fksto TEXT);
        CREATE TABLE KNA1(mandt TEXT, kunnr TEXT, land1 TEXT, name1 TEXT);
        INSERT INTO KNA1 VALUES('100', '0000000010', 'US', 'Synthetic Customer');
        INSERT INTO VBAK VALUES
          ('100', 'O97', '0000000010', '19970102', '9000', 'USD'),
          ('100', 'O00', '0000000010', '20000115', '1000', 'USD'),
          ('100', 'O04', '0000000010', '20041215', '400', 'USD'),
          ('100', 'O05', '0000000010', '20050115', '9999', 'USD');
        INSERT INTO VBRK VALUES
          ('100', 'I97', '0000000010', '19970121', '8000', 'USD', ''),
          ('100', 'I00', '0000000010', '20000120', '250', 'USD', ''),
          ('100', 'I04', '0000000010', '20041220', '150', 'USD', ''),
          ('100', 'I05', '0000000010', '20050120', '7000', 'USD', '');
        """
    )
    return db


def test_single_year_compares_customer_order_and_invoice_totals_without_stale_rows(monkeypatch):
    _install_synthetic_schema(monkeypatch)
    question = "Show major differences in sales order value and invoice by country and customer value for the 2000 year"

    sql = structured_sql.build_sales_order_invoice_customer_comparison_sql(
        question, ["VBAK", "VBRK", "KNA1"]
    )
    assert sql
    assert 'SUBSTRING(TRIM(CAST(o."audat" AS TEXT)), 1, 4) = \'2000\'' in sql
    assert 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4) = \'2000\'' in sql
    assert 'FROM "VBAK" o' in sql and 'FROM "VBRK" k' in sql, context.pipeline_log
    assert '"order_minus_invoice_net_value"' in sql
    assert 'c."mandt" = o."mandt" AND c."kunnr" = o."kunnr"' in sql
    assert 'c."mandt" = k."mandt" AND c."kunnr" = k."kunag"' in sql
    assert 'o."currency" AS "sales_order_currency"' in sql
    assert 'i."currency" AS "invoice_currency"' in sql
    assert '"country_code"' in sql and '"customer_name"' in sql

    rows = _seed_synthetic_database().execute(sql).fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["year"] == "2000"
    assert row["country_code"] == "US"
    assert row["customer_name"] == "Synthetic Customer"
    assert row["sales_order_count"] == 1
    assert row["invoice_count"] == 1
    assert row["sales_order_net_value"] == 1000
    assert row["invoice_net_value"] == 250
    assert row["order_minus_invoice_net_value"] == 750
    issues = _analysis_issues(question, {"sql": sql, "rows": [row], "coverage_issues": []})
    assert not issues, issues


def test_inclusive_year_range_is_filtered_on_order_and_invoice_dates(monkeypatch):
    _install_synthetic_schema(monkeypatch)
    question = "Compare sales order and invoice values by country and customer between 2000 and 2004"

    sql = structured_sql.build_sales_order_invoice_customer_comparison_sql(
        question, ["VBAK", "VBRK", "KNA1"]
    )
    assert sql
    assert 'SUBSTRING(TRIM(CAST(o."audat" AS TEXT)), 1, 4) BETWEEN \'2000\' AND \'2004\'' in sql
    assert 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4) BETWEEN \'2000\' AND \'2004\'' in sql

    rows = [dict(row) for row in _seed_synthetic_database().execute(sql).fetchall()]
    assert [row["year"] for row in rows] == ["2000", "2004"]
    assert [row["sales_order_net_value"] for row in rows] == [1000, 400]
    assert [row["invoice_net_value"] for row in rows] == [250, 150]
    issues = _analysis_issues(question, {"sql": sql, "rows": rows, "coverage_issues": []})
    assert not issues, issues


def test_basic_comparison_passes_independent_grain_and_currency_proofs(monkeypatch):
    _install_synthetic_schema(monkeypatch)
    question = "Show major differences in sales order value and invoice by country and customer value for the 2000 year"
    sql = structured_sql.build_sales_order_invoice_customer_comparison_sql(
        question, ["VBAK", "VBRK", "KNA1"]
    )
    catalog = RelationshipCatalog({
        table: [{"col": column, "type": "text"} for column in columns]
        for table, columns in _COLUMNS.items()
    })
    catalog.keys = {
        "VBAK": [{"mandt", "vbeln"}],
        "VBRK": [{"mandt", "vbeln"}],
        "KNA1": [{"mandt", "kunnr"}],
    }
    catalog.master_tables.add("KNA1")
    catalog.add_edge("VBAK", "KNA1", [("mandt", "mandt"), ("kunnr", "kunnr")], "test SAP customer key")
    catalog.add_edge("VBRK", "KNA1", [("mandt", "mandt"), ("kunag", "kunnr")], "test SAP customer key")

    ok, issues = identified_value_proof(
        sql,
        catalog,
        [("VBAK", "netwr"), ("VBRK", "netwr")],
        allow_currency_matched_difference=True,
    )
    assert ok, issues


def test_basic_sql_pipeline_selects_customer_order_invoice_comparison_template(monkeypatch):
    _install_synthetic_schema(monkeypatch)
    question = "Show major differences in sales order value and invoice by country and customer value for the 2000 year"
    context = VerifiedDbContext(question=question, tables=["VBAK", "VBRK", "KNA1"])

    sql = pipeline3_sql_generation(question, context, templates_only=True)

    assert 'FROM "VBAK" o' in sql and 'FROM "VBRK" k' in sql, context.pipeline_log
    assert context.pipeline_log["PIPELINE_3_SQL_GENERATION"]["source"] == (
        "sales_order_invoice_customer_comparison_template"
    )


def test_basic_sql_pipeline_prefers_customer_comparison_for_year_range(monkeypatch):
    _install_synthetic_schema(monkeypatch)
    question = "Compare sales order and invoice values by country and customer between 2000 and 2004"
    context = VerifiedDbContext(question=question, tables=["VBAK", "VBRK", "KNA1"])

    sql = pipeline3_sql_generation(question, context, templates_only=True)

    assert 'FROM "VBAK" o' in sql and 'FROM "VBRK" k' in sql, context.pipeline_log
    assert 'BETWEEN \'2000\' AND \'2004\'' in sql
    assert 'FROM "VBFA"' not in sql
    assert context.pipeline_log["PIPELINE_3_SQL_GENERATION"]["source"] == (
        "sales_order_invoice_customer_comparison_template"
    )
