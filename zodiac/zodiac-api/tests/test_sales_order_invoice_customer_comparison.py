from __future__ import annotations

import sqlite3
import pytest

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


@pytest.mark.parametrize("wording", ["between 2000 and 2004", "2000 to 2004", "2000–2004"])
def test_inclusive_year_range_is_filtered_on_order_and_invoice_dates(monkeypatch, wording):
    _install_synthetic_schema(monkeypatch)
    question = "Compare sales order and invoice values by country and customer " + wording

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


def test_product_region_comparison_uses_shared_dimensions_and_independent_item_totals(monkeypatch):
    from app.services.basic_sql_answer import _predefined_template_step

    columns = {
        "VBAK": {"mandt", "vbeln", "kunnr", "audat", "netwr", "waerk"},
        "VBAP": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "VBRK": {"mandt", "vbeln", "kunag", "fkdat", "netwr", "waerk", "fksto"},
        "vbrp": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "KNA1": {"mandt", "kunnr", "land1", "regio", "name1"},
        "MARA": {"mandt", "matnr"},
    }
    by_upper = {table.upper(): table for table in columns}
    monkeypatch.setattr(structured_sql, "has_table", lambda table: table.upper() in by_upper)
    monkeypatch.setattr(
        structured_sql,
        "has_column",
        lambda table, column: column.lower() in columns.get(by_upper.get(table.upper(), ""), set()),
    )
    monkeypatch.setattr(structured_sql, "resolve_table_name", lambda table: by_upper.get(table.upper()))

    question = (
        "Compare sales order and invoice revenue, costs, and profits by product, country, "
        "customer, and region for each year from 1999 through 2004"
    )
    sql = structured_sql.build_sales_order_invoice_customer_comparison_sql(
        question, list(columns)
    )

    assert sql
    assert 'FROM "VBAK" h JOIN "VBAP" p' in sql
    assert 'FROM "VBRK" h JOIN "vbrp" p' in sql
    assert 'LEFT JOIN "MARA" m' in sql
    assert '"country_code"' in sql and '"region_code"' in sql
    assert '"customer_id"' in sql and '"product_id"' in sql
    assert 'BETWEEN \'1999\' AND \'2004\'' in sql
    assert 'CASE WHEN o."currency" = i."currency"' in sql
    assert '"order_minus_invoice_profit"' in sql
    from app.services.basic_sql_answer import _predefined_template_step
    assert _predefined_template_step(sql)["basic_predefined_template"] == "sales_order_invoice_customer_comparison"

    catalog = RelationshipCatalog({
        table: [{"col": column, "type": "text"} for column in table_columns]
        for table, table_columns in columns.items()
    })
    catalog.keys = {
        "VBAK": [{"mandt", "vbeln"}],
        "VBAP": [{"mandt", "vbeln", "posnr"}],
        "VBRK": [{"mandt", "vbeln"}],
        "vbrp": [{"mandt", "vbeln", "posnr"}],
        "KNA1": [{"mandt", "kunnr"}],
        "MARA": [{"mandt", "matnr"}],
    }
    catalog.master_tables.update({"KNA1", "MARA"})
    catalog.add_edge("VBAK", "VBAP", [("mandt", "mandt"), ("vbeln", "vbeln")], "sales order item")
    catalog.add_edge("VBRK", "vbrp", [("mandt", "mandt"), ("vbeln", "vbeln")], "invoice item")
    catalog.add_edge("VBAK", "KNA1", [("mandt", "mandt"), ("kunnr", "kunnr")], "customer")
    catalog.add_edge("VBRK", "KNA1", [("mandt", "mandt"), ("kunag", "kunnr")], "customer")
    catalog.add_edge("VBAP", "MARA", [("mandt", "mandt"), ("matnr", "matnr")], "material")
    catalog.add_edge("vbrp", "MARA", [("mandt", "mandt"), ("matnr", "matnr")], "material")
    ok, issues = identified_value_proof(
        sql,
        catalog,
        [("VBAP", "netwr"), ("vbrp", "netwr"), ("VBAP", "wavwr"), ("vbrp", "wavwr")],
        allow_currency_matched_difference=True,
    )
    assert ok, issues


def test_product_region_cost_profit_query_is_routed_as_a_server_template(monkeypatch):
    from app.services.basic_sql_answer import _predefined_template_step
    columns = {
        "VBAK": {"mandt", "vbeln", "kunnr", "audat", "netwr", "waerk"},
        "VBAP": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "VBRK": {"mandt", "vbeln", "kunag", "fkdat", "netwr", "waerk", "fksto"},
        "vbrp": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "KNA1": {"mandt", "kunnr", "land1", "regio", "name1"},
        "MARA": {"mandt", "matnr"},
    }
    by_upper = {table.upper(): table for table in columns}
    monkeypatch.setattr(structured_sql, "has_table", lambda table: table.upper() in by_upper)
    monkeypatch.setattr(
        structured_sql,
        "has_column",
        lambda table, column: column.lower() in columns.get(by_upper.get(table.upper(), ""), set()),
    )
    monkeypatch.setattr(structured_sql, "resolve_table_name", lambda table: by_upper.get(table.upper()))

    question = (
        "Compare sales order and invoice revenue, costs, and profits by product, country, "
        "customer, and region for each year from 1999 through 2004"
    )
    context = VerifiedDbContext(question=question, tables=list(columns))
    sql = pipeline3_sql_generation(question, context, templates_only=True)

    assert sql
    assert context.pipeline_log["PIPELINE_3_SQL_GENERATION"]["source"] == (
        "sales_order_invoice_customer_comparison_template"
    )
    assert all(name in sql for name in ("product_id", "country_code", "customer_id", "region_code"))
    assert '"order_minus_invoice_profit"' in sql
    assert 'BETWEEN \'1999\' AND \'2004\'' in sql
    assert _predefined_template_step(sql)["basic_predefined_template"] == (
        "sales_order_invoice_customer_comparison"
    )


def test_generated_product_cost_profit_comparison_preserves_currency_and_year_scope(monkeypatch):
    columns = {
        "VBAK": {"mandt", "vbeln", "kunnr", "audat", "netwr", "waerk"},
        "VBAP": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "VBRK": {"mandt", "vbeln", "kunag", "fkdat", "netwr", "waerk", "fksto"},
        "vbrp": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "KNA1": {"mandt", "kunnr", "land1", "regio", "name1"},
        "MARA": {"mandt", "matnr"},
    }
    by_upper = {table.upper(): table for table in columns}
    monkeypatch.setattr(structured_sql, "has_table", lambda table: table.upper() in by_upper)
    monkeypatch.setattr(
        structured_sql,
        "has_column",
        lambda table, column: column.lower() in columns.get(by_upper.get(table.upper(), ""), set()),
    )
    monkeypatch.setattr(structured_sql, "resolve_table_name", lambda table: by_upper.get(table.upper()))
    question = (
        "Compare sales order and invoice revenue, costs, and profits by product, country, "
        "customer, and region from 1999 through 2004"
    )
    sql = structured_sql.build_sales_order_invoice_customer_comparison_sql(question, list(columns))
    db = sqlite3.connect(":memory:")
    db.create_function("LPAD", 3, lambda value, width, fill: str(value or "").rjust(width, fill))
    for statement in (
        "CREATE TABLE VBAK(mandt TEXT,vbeln TEXT,kunnr TEXT,audat TEXT,netwr TEXT,waerk TEXT)",
        "CREATE TABLE VBAP(mandt TEXT,vbeln TEXT,posnr TEXT,matnr TEXT,netwr TEXT,wavwr TEXT)",
        "CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,kunag TEXT,fkdat TEXT,netwr TEXT,waerk TEXT,fksto TEXT)",
        "CREATE TABLE vbrp(mandt TEXT,vbeln TEXT,posnr TEXT,matnr TEXT,netwr TEXT,wavwr TEXT)",
        "CREATE TABLE KNA1(mandt TEXT,kunnr TEXT,land1 TEXT,regio TEXT,name1 TEXT)",
        "CREATE TABLE MARA(mandt TEXT,matnr TEXT)",
    ):
        db.execute(statement)
    db.execute("INSERT INTO KNA1 VALUES('100','0000000010','US','CA','Synthetic Customer')")
    db.execute("INSERT INTO MARA VALUES('100','P1')")
    db.execute("INSERT INTO VBAK VALUES('100','O1','0000000010','20000115','100','USD')")
    db.execute("INSERT INTO VBAP VALUES('100','O1','10','P1','100','60')")
    db.execute("INSERT INTO VBAK VALUES('100','O5','0000000010','20050115','999','USD')")
    db.execute("INSERT INTO VBAP VALUES('100','O5','10','P1','999','900')")
    db.execute("INSERT INTO VBRK VALUES('100','I1','0000000010','20000120','80','USD','')")
    db.execute("INSERT INTO vbrp VALUES('100','I1','10','P1','80','50')")
    db.execute("INSERT INTO VBRK VALUES('100','I2','0000000010','20000122','5','EUR','')")
    db.execute("INSERT INTO vbrp VALUES('100','I2','10','P1','5','3')")

    cursor = db.execute(sql)
    rows = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
    matched = next(row for row in rows if row["sales_order_currency"] == "USD" and row["invoice_currency"] == "USD")
    unmatched_currency = next(row for row in rows if row["invoice_currency"] == "EUR")
    assert len(rows) == 2
    assert {row["year"] for row in rows} == {"2000"}
    assert all(row["country_code"] == "US" and row["region_code"] == "CA" for row in rows)
    assert all(row["customer_id"] == "0000000010" and row["product_id"] == "P1" for row in rows)
    assert matched["sales_order_net_value"] == 100 and matched["invoice_net_value"] == 80
    assert matched["order_minus_invoice_net_value"] == 20
    assert matched["sales_order_cost"] == 60 and matched["invoice_cost"] == 50
    assert matched["order_minus_invoice_cost"] == 10
    assert matched["sales_order_profit"] == 40 and matched["invoice_profit"] == 30
    assert matched["order_minus_invoice_profit"] == 10
    assert unmatched_currency["sales_order_currency"] is None
    assert unmatched_currency["order_minus_invoice_net_value"] is None
    db.close()


def test_basic_routes_product_region_profit_template_without_model(monkeypatch):
    from app.services import schema_intelligence_registry
    from app.services.basic_sql_answer import run_basic_sql_answer

    columns = {
        "VBAK": {"mandt", "vbeln", "kunnr", "audat", "netwr", "waerk"},
        "VBAP": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "VBRK": {"mandt", "vbeln", "kunag", "fkdat", "netwr", "waerk", "fksto"},
        "vbrp": {"mandt", "vbeln", "posnr", "matnr", "netwr", "wavwr"},
        "KNA1": {"mandt", "kunnr", "land1", "regio", "name1"},
        "MARA": {"mandt", "matnr"},
    }
    by_upper = {table.upper(): table for table in columns}
    monkeypatch.setattr(structured_sql, "has_table", lambda table: table.upper() in by_upper)
    monkeypatch.setattr(
        structured_sql,
        "has_column",
        lambda table, column: column.lower() in columns.get(by_upper.get(table.upper(), ""), set()),
    )
    monkeypatch.setattr(structured_sql, "resolve_table_name", lambda table: by_upper.get(table.upper()))

    class Registry:
        def lightweight_table_catalog(self, include_operational=False):
            return [{"table": table} for table in columns]

    monkeypatch.setattr(schema_intelligence_registry, "get_schema_registry", lambda: Registry())
    question = (
        "Compare sales order and invoice revenue, costs, and profits by product, country, "
        "customer, and region for each year from 1999 through 2004"
    )
    executions = []

    def execute(*args, **kwargs):
        executions.append(args)
        pytest.fail("Basic must wait for approval before executing the predefined query")

    def local_agent(*args, **kwargs):
        pytest.fail("The supported comparison must not fall through to Ollama")

    result = run_basic_sql_answer(
        question, execute=execute, prior_examples=[], local_agent=local_agent,
    )

    assert result["answer_status"] == "CLARIFICATION"
    assert result["meta"]["basic_pattern_confirmation"]
    assert result["llm_calls"] == 0
    assert executions == []


def test_region_only_comparison_groups_by_country_to_keep_region_codes_distinct(monkeypatch):
    _install_synthetic_schema(monkeypatch)
    monkeypatch.setattr(
        structured_sql,
        "has_column",
        lambda table, column: column.lower() in {
            "mandt", "vbeln", "kunnr", "audat", "netwr", "waerk", "kunag", "fkdat", "fksto",
            "land1", "regio", "name1",
        },
    )
    question = "Compare sales order and invoice values by region in 2000"
    sql = structured_sql.build_sales_order_invoice_customer_comparison_sql(
        question, ["VBAK", "VBRK", "KNA1"]
    )
    assert sql
    assert 'COALESCE(o."country_code", i."country_code") AS "country_code"' in sql
    assert 'COALESCE(o."region_code", i."region_code") AS "region_code"' in sql
    assert 'o."customer_id" IS NOT DISTINCT FROM i."customer_id"' not in sql


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
