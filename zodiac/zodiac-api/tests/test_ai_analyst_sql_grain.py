"""Behavioral regressions for live analyses that returned the wrong grain."""
from __future__ import annotations

import pytest

from app.services.adaptive_query_repair import repair_grouping_error_sql
from app.services.adaptive_structured_sql import (
    PlanField,
    PlanFilter,
    StructuredQueryPlan,
    _apply_semantic_defaults,
    build_dimension_ranking_sql,
    build_billing_document_ranking_sql,
    build_dimension_period_sales_sql,
    build_linked_sales_orders_sql,
    render_sql_from_plan,
    year_filter_expression,
    _apply_anti_join_nulls,
    _year_from_semantic,
    _normalize_plan_expressions,
    validate_query_plan,
)
from app.services.adaptive_structured_sql import detect_ranking_measure
from app.services.business_semantic_layer import resolve_metric
from app.services.analytical_operations import extract_analytical_operations, merge_semantic_requirements
from app.services.plan_satisfaction import result_matches_analytical_intent, sql_satisfies_analytical_intent
from app.services.semantic_requirements import enrich_semantic_with_requirements, required_semantics
from app.services.result_first_followup import try_answer_from_prior_rows


@pytest.mark.parametrize("question", [
    "Show the products with the highest profits.",
    "Which products are most profitable?",
    "List products by gross profit.",
])
def test_profit_ranking_phrasings_resolve_to_governed_gross_profit(question):
    metric = resolve_metric(question)
    assert metric is not None and metric.name == "gross_profit"
    assert detect_ranking_measure(question) == "gross_profit"


def test_true_net_profit_request_does_not_fall_back_to_gross_profit():
    metric = resolve_metric("Rank products by net profit")
    assert metric is not None and metric.name == "net_profit"
    assert metric.status == "unavailable"
    assert detect_ranking_measure("Rank products by net profit") == "net_profit"
    assert build_dimension_ranking_sql(
        "Rank products by net profit", ["vbrp", "VBRK", "MAKT"]
    ) is None


@pytest.mark.parametrize("question,metric,formula_piece", [
    ("Show products with highest profits", "gross_profit", '"wavwr"'),
    ("Rank products by highest gross margin", "gross_margin_pct", '"wavwr"'),
    ("Rank products by cost of goods", "cogs", '"wavwr"'),
    ("Rank products by revenue", "revenue", '"netwr"'),
])
def test_product_rankings_compile_catalog_metric_and_currency(question, metric, formula_piece):
    sql = build_dimension_ranking_sql(question, ["vbrp", "VBRK", "MAKT"])
    assert sql is not None
    assert f'AS "{metric if metric != "revenue" else "total_sales"}"' in sql
    assert formula_piece in sql
    assert '"currency"' in sql
    assert 'PARTITION BY grouped."currency"' in sql


def test_combined_year_totals_compile_to_year_grain_despite_model_noise():
    question = "Show total billed sales and billing-document count by calendar year."
    semantic = merge_semantic_requirements(question, {"measure": {"concept": "count", "aggregation": "COUNT"}})
    year = year_filter_expression("VBRK", "fkdat")
    plan = StructuredQueryPlan(
        question=question,
        tables=["VBRK"],
        semantic_requirements=semantic,
        select=[
            PlanField(type="column", table="VBRK", column="fkdat"),
            PlanField(type="column", table="VBRK", column="netwr"),
            PlanField(type="expression", expression=year, alias="calendar_year"),
            PlanField(type="expression", expression='SUM(CAST("VBRK"."netwr" AS NUMERIC))', alias="billed_sales_total"),
            PlanField(type="expression", expression='COUNT(DISTINCT "VBRK"."vbeln")', alias="billing_document_count"),
        ],
        group_by=[
            PlanField(type="column", table="VBRK", column="fkdat"),
            PlanField(type="column", table="VBRK", column="netwr"),
        ],
    )
    _apply_semantic_defaults(plan, semantic)
    sql = render_sql_from_plan(plan)
    assert 'GROUP BY "VBRK"."fkdat"' not in sql
    assert 'GROUP BY "VBRK"."netwr"' not in sql
    assert not any(field.type == "column" for field in plan.group_by)
    assert sql_satisfies_analytical_intent(sql, question, semantic)
    assert not result_matches_analytical_intent(
        [{"calendar_year": "2000", "billed_sales_total": 120, "billing_document_count": 2}],
        question, semantic, sql,
    )


@pytest.mark.parametrize("grouping", ['"VBRK"."fkdat"', '"VBRK"."fkdat", "VBRK"."netwr"'])
def test_year_alias_does_not_validate_raw_date_or_amount_groups(grouping):
    question = "Show total billed sales and billing-document count by calendar year."
    sql = (
        'SELECT EXTRACT(YEAR FROM "VBRK"."fkdat") AS calendar_year, '
        'SUM("VBRK"."netwr") AS total_sales, COUNT(DISTINCT "VBRK"."vbeln") AS document_count '
        f'FROM "VBRK" GROUP BY {grouping}'
    )
    assert not sql_satisfies_analytical_intent(sql, question)
    warnings = result_matches_analytical_intent(
        [{"calendar_year": "2000", "total_sales": 120, "document_count": 2}], question, sql=sql,
    )
    assert "executed SQL does not satisfy the analytical plan" in warnings


def test_alias_and_ordinal_groups_preserve_valid_year_aggregates():
    question = "Show billed sales by calendar year."
    for group in ("calendar_year", "1", "DATE_PART('year', k.fkdat)"):
        sql = (
            "SELECT DATE_PART('year', k.fkdat) AS calendar_year, SUM(k.netwr) AS total_sales "
            f'FROM "VBRK" k GROUP BY {group}'
        )
        assert sql_satisfies_analytical_intent(sql, question)


def test_month_grain_does_not_accept_extra_daily_grouping():
    question = "Show billed sales by month."
    good = (
        "SELECT DATE_TRUNC('month', k.fkdat) AS month, SUM(k.netwr) AS total_sales "
        'FROM "VBRK" k GROUP BY 1'
    )
    assert sql_satisfies_analytical_intent(good, question)
    assert not sql_satisfies_analytical_intent(good.replace("GROUP BY 1", "GROUP BY 1, k.fkdat"), question)


@pytest.mark.parametrize("question", [
    "For the higher-sales country, show monthly billed sales in the same year and currency.",
    "For the highest-sales country and currency, show monthly billed sales in that same year.",
])
def test_superlative_prior_entity_does_not_rank_monthly_followup(question):
    ops = extract_analytical_operations(question)
    assert ops["group_by"] == ["month"]
    assert ops["ranking"] is None
    sql = (
        'SELECT SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 6) AS "month", '
        'SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "total_billed_sales", '
        'k."waerk" AS "currency" FROM "VBRK" k '
        'JOIN "KNA1" c ON LPAD(TRIM(CAST(k."kunag" AS TEXT)), 10, \'0\') = '
        'LPAD(TRIM(CAST(c."kunnr" AS TEXT)), 10, \'0\') '
        'WHERE TRIM(CAST(c."land1" AS TEXT)) = \'US\' '
        'AND SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 4) IN (\'2017\') '
        'AND TRIM(CAST(k."waerk" AS TEXT)) = \'USD\' '
        'GROUP BY SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 6), k."waerk" '
        'ORDER BY "month" ASC'
    )
    assert sql_satisfies_analytical_intent(sql, question)


def test_top_five_requires_requested_limit_even_if_query_is_valid():
    question = "Show the top five countries by billed sales."
    sql = (
        'SELECT k.land1 AS country, SUM(k.netwr) AS total_sales FROM "VBRK" k '
        "GROUP BY k.land1 ORDER BY total_sales DESC LIMIT 10"
    )
    assert not sql_satisfies_analytical_intent(sql, question)
    assert sql_satisfies_analytical_intent(sql.replace("LIMIT 10", "LIMIT 5"), question)
    rows = [{"country": f"C{i}", "total_sales": i} for i in range(6)]
    assert "ranking limit was not applied" in result_matches_analytical_intent(rows, question, sql=sql)


def test_country_ranking_rejects_customer_level_subtotals():
    question = "Show the top five countries by billed sales."
    sql = (
        'SELECT k.land1 AS country, SUM(k.netwr) AS total_sales FROM "VBRK" k '
        "GROUP BY k.land1, k.kunag ORDER BY total_sales DESC LIMIT 5"
    )
    assert not sql_satisfies_analytical_intent(sql, question)


def test_verified_latest_period_bounds_survive_semantic_merges_and_compilation():
    question = "Show the top five countries by billed sales in the latest complete year available in the data."
    verified = {
        "time_filter": {
            "relative": "latest_full_year", "resolved_from_data": True,
            "date_table": "VBRK", "date_column": "fkdat", "years": ["2001"],
            "start": "2001-01-01", "end": "2002-01-01",
            "start_yyyymmdd": "20010101", "end_yyyymmdd": "20020101",
        },
    }
    req = required_semantics(question, verified)
    assert req["date_filter"]["start"] == "2001-01-01"
    assert req["date_filter"]["end"] == "2002-01-01"
    sql = build_dimension_ranking_sql(question, ["VBRK", "KNA1"], verified)
    assert sql and "2001" in sql and "LIMIT 5" in sql
    assert 'AS "country"' in sql
    assert sql_satisfies_analytical_intent(sql, question, verified)
    assert not sql_satisfies_analytical_intent(sql.replace("'2001'", "'2000'"), question, verified)
    enriched = enrich_semantic_with_requirements(question, verified)
    assert enriched["time_filter"]["resolved_from_data"] is True
    assert enriched["time_filter"]["date_column"] == "fkdat"
    assert "value" not in enriched["time_filter"]


def test_unverified_latest_period_bounds_are_discarded():
    question = "Show billed sales in the latest complete year."
    req = required_semantics(question, {"time_filter": {
        "relative": "latest_full_year", "start": "2099-01-01", "end": "2100-01-01", "years": ["2099"],
    }})
    assert req["date_filter"]["start"] is None
    assert req["date_filter"]["years"] == []


def test_latest_complete_period_accepts_generic_number_of_years():
    question = "For that country, show billed sales by year for the last five complete years available."
    ops = extract_analytical_operations(question)
    assert ops["relative_period_count"] == 5
    assert required_semantics(question)["date_filter"]["count"] == 5


def test_document_ranking_keeps_output_grain_despite_customer_filter():
    question = "Show the top ten billing documents behind the leading customer's total."
    ops = extract_analytical_operations(question)
    assert ops["group_by"] == ["document"]
    assert ops["ranking"]["limit"] == 10
    rows = [{"customer_id": "A", "total_sales": 20}]
    assert "requested dimension document missing from result columns" in result_matches_analytical_intent(rows, question)


def test_highest_value_billing_documents_select_document_grain():
    question = (
        "List the 10 highest-value billing documents issued in calendar year 2017, "
        "including document ID, invoice date, billed amount, and currency."
    )
    ops = extract_analytical_operations(question)
    req = required_semantics(question)

    assert "document" in ops["group_by"]
    assert "document" in req["group_by"]
    assert req["measure"]["aggregation"] == ""


def test_referential_highest_invoice_followup_requests_a_customer_time_series():
    question = (
        "For the highest-value invoice, show its customer name and that customer's "
        "monthly billed sales in 2017."
    )
    ops = extract_analytical_operations(question)
    req = required_semantics(question)

    assert set(ops["group_by"]) == {"month", "customer"}
    assert "document" not in req["group_by"]

    result = try_answer_from_prior_rows(
        question,
        [{"billing_document": "0090040381", "customer_id": "0000300286", "customer_name": "Dynamic Industries", "billed_amount": 800000}],
    )
    assert result and result["needs_plan_expansion"]
    assert "by month and customer" in result["expanded_question"]
    assert "customer ID '0000300286'" in result["expanded_question"]


def test_same_customer_period_followup_reuses_explicit_id_from_recent_conversation():
    question = "For that same customer, show billed sales by month for 2017 in USD."
    prior = {
        "recent_turns": [
            {"role": "user", "content": "For customer ID 0000300286, show monthly billed sales in USD in calendar year 2017."},
            {"role": "assistant", "content": "The query completed and returned 1 row."},
        ],
    }
    result = try_answer_from_prior_rows(
        question,
        [{"month": "201701", "total_billed_sales": 1223400, "currency": "USD"}],
        prior_plan=prior,
    )

    assert result and result["needs_plan_expansion"]
    assert "customer ID '0000300286'" in result["expanded_question"]
    assert "by month" in result["expanded_question"]
    assert "2017" in result["expanded_question"] and "USD" in result["expanded_question"]


def test_same_customer_period_followup_asks_instead_of_broadening_without_anchor():
    result = try_answer_from_prior_rows(
        "For that same customer, show billed sales by month for 2017.",
        [{"month": "201701", "total_billed_sales": 1223400, "currency": "USD"}],
    )

    assert result and result["answer_status"] == "CLARIFICATION"
    assert "customer ID or name" in result["answer"]


def test_negative_billing_document_ranking_uses_invoice_rows_not_customer_aggregation(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "KNA1": {"kunnr", "name1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper() if table.lower() == "vbrk" else table)

    question = "Show the ten most negative billed documents, with document number, customer, date, and amount."
    sql = build_billing_document_ranking_sql(question, ["VBRK", "KNA1"])
    assert sql
    assert 'AS "billing_document"' in sql
    assert 'AS "customer_name"' in sql
    assert 'AS "billing_date"' in sql
    assert 'AS "billed_amount"' in sql
    assert "< 0" in sql
    assert 'ORDER BY "billed_amount" ASC' in sql
    assert "LIMIT 10" in sql
    assert "GROUP BY" not in sql and "SUM(" not in sql
    assert sql_satisfies_analytical_intent(sql, question)
    assert not result_matches_analytical_intent(
        [{"billing_document": "1", "customer_id": "C1", "billing_date": "20000101", "billed_amount": -2}],
        question,
        sql=sql,
    )


def test_same_billing_documents_cannot_be_compared_across_calendar_years():
    from app.services.analytical_operations import extract_analytical_operations
    from app.services.semantic_requirements import required_semantics

    question = (
        "Show the lowest negative billed invoice amounts in calendar year 2000 and compare them "
        "with the same invoices in calendar year 2001. List billing document numbers by customer "
        "and include both absolute and percent change."
    )
    ops = extract_analytical_operations(question)
    required = required_semantics(question)

    assert ops["group_by"] == ["document"]
    assert ops["clarification"]["type"] == "document_period_comparison"
    assert "one billing date" in ops["clarification"]["message"]
    assert required["clarification"]["type"] == "document_period_comparison"
    assert "2000" in required["clarification"]["message"]
    assert "2001" in required["clarification"]["message"]


def test_leading_customer_document_drilldown_reuses_verified_id_period_and_currency():
    question = "Show the top ten billing documents behind the leading customer's total."
    plan = {
        "verified_db_context": {
            "semantic_requirements": {
                "time_filter": {"resolved_from_data": True, "years": ["2018"]},
            },
        },
    }
    result = try_answer_from_prior_rows(
        question,
        [
            {"customer_id": "0000300286", "customer_name": "Customer A", "currency": "USD", "total_sales": 125},
            {"customer_id": "0000300200", "customer_name": "Customer B", "currency": "USD", "total_sales": 80},
        ],
        prior_plan=plan,
    )
    assert result and result["needs_plan_expansion"]
    expanded = result["expanded_question"]
    assert "customer ID '0000300286'" in expanded
    assert "calendar year 2018" in expanded
    assert "currency USD" in expanded


def test_country_year_followup_expands_to_verified_country_and_uses_period_template(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "KNA1": {"kunnr", "land1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Show billed sales by year for country code 'US' for the last five complete years available in the data in currency USD."
    semantic = {
        "time_filter": {
            "relative": "latest_full_year", "resolved_from_data": True,
            "years": ["2013", "2014", "2015", "2016", "2017"], "count": 5,
            "date_table": "VBRK", "date_column": "fkdat",
        },
    }
    sql = build_dimension_period_sales_sql(question, ["VBRK", "KNA1"], semantic)
    assert sql
    assert '"year"' in sql and "GROUP BY" in sql
    assert "c.\"land1\"" in sql and "= 'US'" in sql
    assert "'2013'" in sql and "'2017'" in sql
    assert "'USD'" in sql
    assert sql_satisfies_analytical_intent(sql, question, semantic)


def test_country_month_followup_uses_year_qualified_month_bucket_and_passes_precision_validation(monkeypatch):
    import app.services.adaptive_structured_sql as structured
    from app.services.sap_sql_precision_validator import validate_sql_precision

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "KNA1": {"kunnr", "land1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Show billed sales by month for country code 'US' in calendar year 2017 in currency USD."
    semantic = {
        "time_filter": {
            "resolved_from_data": True,
            "years": ["2017"],
            "date_table": "VBRK",
            "date_column": "fkdat",
        },
    }

    sql = build_dimension_period_sales_sql(question, ["VBRK", "KNA1"], semantic)

    assert sql
    assert 'SUBSTRING(TRIM(CAST(k."fkdat" AS TEXT)), 1, 6) AS "month"' in sql
    assert "GROUP BY SUBSTRING(TRIM(CAST(k.\"fkdat\" AS TEXT)), 1, 6), k.\"waerk\"" in sql
    assert "'2017'" in sql and "'US'" in sql and "'USD'" in sql
    assert sql_satisfies_analytical_intent(sql, question, semantic)
    validation = validate_sql_precision(
        sql,
        {"VBRK": sorted(physical_columns["VBRK"]), "KNA1": sorted(physical_columns["KNA1"])},
        question=question,
    )
    assert validation.is_valid, validation.errors


def test_country_month_grouping_uses_customer_country_without_a_single_country_filter(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "KNA1": {"kunnr", "land1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Show billed sales by customer country and month for calendar year 2017 in USD."

    ops = extract_analytical_operations(question)
    assert ops["group_by"] == ["month", "country"]
    sql = build_dimension_period_sales_sql(question, ["VBRK", "KNA1"])

    assert sql
    assert 'AS "country"' in sql
    assert 'AS "month"' in sql
    assert "GROUP BY TRIM(CAST(c.\"land1\" AS TEXT))" in sql
    assert "'2017'" in sql and "'USD'" in sql
    assert sql_satisfies_analytical_intent(sql, question)


def test_multiple_explicit_years_by_year_are_a_series_not_a_two_period_pivot(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {"VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"}}
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Compare billed sales by calendar year for 2015, 2016, and 2017 in USD."
    ops = extract_analytical_operations(question)

    assert ops["group_by"] == ["year"]
    assert ops["period_compare"] is None
    sql = build_dimension_period_sales_sql(question, [])

    assert sql
    assert 'AS "year"' in sql
    assert "fkdat" in sql.lower() and "erdat" not in sql.lower()
    assert all(f"'{year}'" in sql for year in ("2015", "2016", "2017"))
    assert sql_satisfies_analytical_intent(sql, question)


def test_billed_sales_by_currency_uses_billing_header_year_and_currency_grain(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {"VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"}}
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Show billed sales totals by currency for calendar year 2017."

    sql = build_dimension_period_sales_sql(question, ["VBRK"])

    assert sql
    assert '"VBRK"' in sql and '"waerk" AS "currency"' in sql
    assert '"fkdat"' in sql and '"erdat"' not in sql
    assert "'2017'" in sql and "GROUP BY k.\"waerk\"" in sql
    assert "'FOR'" not in sql
    assert sql_satisfies_analytical_intent(sql, question)


def test_country_sales_ranking_uses_invoice_header_amount_for_monthly_consistency(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "vbrp": {"vbeln", "posnr", "matnr", "netwr", "fkimg"},
        "KNA1": {"kunnr", "land1", "name1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in {t.upper() for t in physical_columns})
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in next(
            (cols for name, cols in physical_columns.items() if name.upper() == table.upper()), set()
        ),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: "vbrp" if table.lower() == "vbrp" else table.upper())

    sql = build_dimension_ranking_sql(
        "Show the top five countries by billed sales in calendar year 2017.",
        ["VBRK", "vbrp", "KNA1"],
    )

    assert sql
    assert 'FROM "VBRK" k' in sql
    assert 'SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), \'\') AS NUMERIC))' in sql
    assert 'FROM "vbrp" p' not in sql
    assert "'2017'" in sql
    assert "LIMIT 5" in sql


def test_product_sales_ranking_keeps_billing_item_grain(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "vbrp": {"vbeln", "posnr", "matnr", "netwr", "fkimg"},
        "MAKT": {"matnr", "maktx", "spras"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in {t.upper() for t in physical_columns})
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in next(
            (cols for name, cols in physical_columns.items() if name.upper() == table.upper()), set()
        ),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: "vbrp" if table.lower() == "vbrp" else table.upper())

    sql = build_dimension_ranking_sql("Show the top five products by billed sales.", ["VBRK", "vbrp"])

    assert sql
    assert 'FROM "vbrp" p' in sql
    assert "SUM(CAST(NULLIF" in sql and 'p."netwr"' in sql


def test_quarterly_billed_sales_use_quarter_buckets_from_billing_date(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "KNA1": {"kunnr", "land1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Show billed sales by quarter for customer ID '0000300286' in calendar year 2017 in currency USD."

    sql = build_dimension_period_sales_sql(question, ["VBRK", "KNA1"])

    assert sql and 'AS "quarter"' in sql
    assert "fkdat" in sql.lower() and "-Q" in sql
    assert "'2017'" in sql and "'USD'" in sql
    assert "GROUP BY" in sql
    assert sql_satisfies_analytical_intent(sql, question)


def test_month_number_bucket_is_valid_only_inside_a_single_fkdat_year():
    from app.services.sap_sql_precision_validator import validate_sql_precision

    schema = {
        "VBRK": ["fkdat", "kunag", "netwr", "vbeln", "waerk"],
        "KNA1": ["kunnr", "land1"],
    }
    month_number = 'CAST(SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)) FROM 5 FOR 2) AS INTEGER)'
    fixed_year = 'SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) = \'2017\''
    single_year_sql = (
        f'SELECT {month_number} AS "month", SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS "sales" '
        'FROM "VBRK" WHERE ' + fixed_year + f' GROUP BY {month_number}'
    )
    multi_year_sql = single_year_sql.replace(
        fixed_year,
        'SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) IN (\'2016\', \'2017\')',
    )

    one_year = validate_sql_precision(
        single_year_sql, schema, question="Show monthly billed sales for calendar year 2017."
    )
    multiple_years = validate_sql_precision(
        multi_year_sql, schema, question="Show monthly billed sales for calendar years 2016 and 2017."
    )

    assert one_year.is_valid, one_year.errors
    assert not multiple_years.is_valid
    assert any("month bucket derived from FKDAT" in error for error in multiple_years.errors)


def test_linked_order_template_uses_document_flow_and_only_prior_document_ids(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {"VBFA": {"vbeln", "vbelv"}, "VBAK": {"vbeln"}, "VBRK": {"vbeln"}}
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "List sales orders linked through document flow to billing document IDs: '0000000001', '0000000002'."
    sql = build_linked_sales_orders_sql(question, list(physical_columns))
    assert sql
    assert '"VBFA" f' in sql and '"VBAK" o' in sql and '"VBRK" b' in sql
    assert 'f."vbelv"' in sql
    assert "0000000001" in sql and "0000000002" in sql
    assert "SELECT DISTINCT" in sql
    assert sql_satisfies_analytical_intent(sql, question)


def test_followups_expand_demonstrative_country_and_same_documents_from_prior_rows():
    country = try_answer_from_prior_rows(
        "For that country, show billed sales by year for the last five complete years available.",
        [{"country": "US", "currency": "USD", "total_sales": 1227}],
    )
    assert country and country["needs_plan_expansion"]
    assert "country code 'US'" in country["expanded_question"]
    assert "currency USD" in country["expanded_question"]

    documents = try_answer_from_prior_rows(
        "For those same documents, include the linked sales orders if the data supports that link.",
        [{"billing_document": "0000000001"}, {"billing_document": "0000000002"}],
    )
    assert documents and documents["needs_plan_expansion"]
    assert "0000000001" in documents["expanded_question"]
    assert "0000000002" in documents["expanded_question"]


def test_grouping_repair_does_not_append_measure_to_group_by():
    sql = 'SELECT "VBRK"."netwr", COUNT(*) FROM "VBRK" GROUP BY "VBRK"."fkdat"'
    error = 'column "VBRK.netwr" must appear in the GROUP BY clause or be used in an aggregate function'
    assert repair_grouping_error_sql(sql, "Show total sales and document count by year", error) is None


def test_empty_model_negation_does_not_filter_out_joined_data():
    question = "Show total billed sales and billing-document count by calendar year."
    polluted = {"negation": {"required": None, "forbidden": None}}
    plan = StructuredQueryPlan(question=question, semantic_requirements=polluted, negation=polluted["negation"])
    sql = 'SELECT SUM(p.netwr) FROM "VBRK" LEFT JOIN "vbrp" ON "VBRK"."vbeln"="vbrp"."vbeln" GROUP BY 1'
    assert _apply_anti_join_nulls(sql, plan) == sql
    assert "negation" not in enrich_semantic_with_requirements(question, polluted)


def test_relative_period_name_is_never_used_as_a_year_literal():
    question = "Show billed sales last year."
    sem = enrich_semantic_with_requirements(question, {"time_filter": {"relative": "last_year", "value": "last_year"}})
    assert "value" not in sem["time_filter"]
    assert _year_from_semantic({"time_filter": {"value": "last_year"}}) is None


def test_verified_year_transformation_alias_is_expanded_before_filter_validation():
    year = year_filter_expression("VBRK", "fkdat")
    plan = StructuredQueryPlan(
        tables=["VBRK"],
        select=[PlanField(type="expression", expression=year, alias="billing_year")],
        filters=[PlanFilter(type="expression", expression="billing_year = 2001")],
    )
    _normalize_plan_expressions(plan)
    assert year in plan.filters[0].expression
    assert validate_query_plan(plan) == []


@pytest.mark.parametrize("expression", ['fake_year = 2001', 'VBRK.fake_year = 2001'])
def test_plan_rejects_invented_expression_fields(expression):
    plan = StructuredQueryPlan(tables=["VBRK"], filters=[PlanFilter(type="expression", expression=expression)])
    assert any("fake_year" in error for error in validate_query_plan(plan))


def test_year_grouping_requires_year_projection_before_query_executes():
    semantic = merge_semantic_requirements("Show total billed sales by calendar year.")
    plan = StructuredQueryPlan(
        tables=["VBRK"], semantic_requirements=semantic,
        select=[PlanField(type="expression", expression='SUM("VBRK"."netwr")', alias="sales")],
        group_by=[PlanField(type="expression", expression=year_filter_expression("VBRK", "fkdat"))],
    )
    assert "year grouping missing from result projection" in validate_query_plan(plan)
