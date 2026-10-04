from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from app.services.adaptive_analyst.chat_memory import compact_sql_lineage, relevant_conversation
from app.services.adaptive_analyst.database_metadata import (
    SEARCH_COLUMNS,
    answer_database_metadata,
    classify_metadata_operation,
    is_database_metadata_question,
)
from app.services.adaptive_analyst.understanding import (
    _context_block,
    _schema_semantics_evidence,
    is_prior_turn_discourse,
    is_referential_database_action,
)
from app.services.analytical_operations import extract_analytical_operations
from app.services.adaptive_structured_sql import (
    PlanField,
    StructuredQueryPlan,
    _apply_period_compare_fields,
    build_dimension_ranking_sql,
    build_linked_order_period_comparison_sql,
)
from app.services.four_stage_db_pipeline import (
    VerifiedDbContext,
    _resolved_latest_period_note,
    _apply_followup_to_context,
    _contains_unresolved_sql_value,
    _resolve_latest_data_years,
)
from app.services.result_first_followup import (
    is_result_scoped_followup,
    resolve_pending_currency_clarification,
    try_answer_from_prior_rows,
)
from app.services.semantic_requirements import required_semantics
from app.services.plan_satisfaction import sql_satisfies_analytical_intent, result_matches_analytical_intent
from app.data_catalog.physical import load_physical_schema


def test_specific_sap_field_metadata_returns_matching_columns_only():
    question = "For VBRK, list the exact column names for billing date and billing document number."
    plan = classify_metadata_operation(question, schema=load_physical_schema())
    assert plan is not None
    assert plan.operation == SEARCH_COLUMNS
    assert plan.search_terms == ["billing date", "billing document number"]

    answer = answer_database_metadata(question, load_physical_schema())
    assert answer is not None
    assert {row["column"].lower() for row in answer["data"]} == {"fkdat", "vbeln"}


def test_explicit_table_list_and_schema_followup_use_catalog_metadata():
    from app.services.adaptive_analyst.understanding import is_referential_database_action

    question = "How many database tables are connected, and list the first five table names?"
    schema = load_physical_schema()
    plan = classify_metadata_operation(question, schema=schema)
    assert plan is not None
    assert plan.operation == "LIST_TABLES"
    assert plan.list_limit == 5
    assert plan.include_total_count is True
    answer = answer_database_metadata(question, schema)
    assert answer is not None
    assert answer["answer_status"] == "SUCCESS"
    assert len(answer["data"]) == 5
    assert "first five" in answer["summary"].lower() or "requested table names" in answer["summary"].lower()

    followup = "From that schema, list just the first five sales-domain table names."
    assert not is_referential_database_action(followup, has_prior=True)
    domain_plan = classify_metadata_operation(followup, schema=schema)
    assert domain_plan is not None
    assert domain_plan.operation == "LIST_TABLES"
    assert domain_plan.domain_filter == "sales"
    assert domain_plan.list_limit == 5


def test_table_search_uses_catalog_grain_and_domain_descriptions():
    answer = answer_database_metadata(
        "Which tables contain billing or invoice header data?", load_physical_schema()
    )
    assert answer is not None
    assert answer["data"][0]["table"] == "VBRK"
    assert len(answer["data"]) <= 5


def test_count_by_calendar_year_discards_llm_grain_and_measure_noise():
    req = required_semantics(
        "Break that count down by calendar year using the billing date.",
        {
            "dimensions": ["customer", "billing_date"],
            "group_by": ["customer", "billing_date"],
            "measure": {"concept": "revenue", "aggregation": "SUM"},
            "ranking": {"direction": "DESC", "limit": 10},
        },
    )
    assert req["dimensions"] == ["year"]
    assert req["group_by"] == ["year"]
    assert req["measure"] == {"concept": "count", "aggregation": "COUNT"}
    assert req.get("ranking") is None


def test_ungrouped_period_comparison_preserves_both_requested_changes():
    req = required_semantics(
        "Compare 2001 with 2000 using both absolute and percent change.",
        {
            "dimensions": ["customer", "billing_date"],
            "group_by": ["customer"],
            "ranking": {"direction": "DESC", "limit": 10},
            "measure": {"concept": "revenue", "aggregation": "SUM"},
        },
    )
    assert req["dimensions"] == []
    assert req["group_by"] == []
    assert req.get("ranking") is None
    assert req["period_compare"]["calculation"] == "both"


def test_explicit_top_five_wins_over_llm_top_ten():
    req = required_semantics(
        "Show the five countries with the highest billed sales.",
        {"dimensions": ["customer"], "ranking": {"direction": "DESC", "limit": 10}},
    )
    assert req["ranking"]["limit"] == 5
    assert req["dimensions"] == ["country"]
    sql = build_dimension_ranking_sql(
        "Show the five countries with the highest billed sales.",
        ["VBRK", "VBRP", "KNA1"],
        req["semantic"],
    )
    assert sql is not None
    assert 'PARTITION BY grouped."currency"' in sql
    assert '"rank_within_currency" <= 5' in sql


def test_top_five_country_currency_ranking_is_not_currency_filtered():
    question = (
        "Show me the top five countries by billed sales in calendar year 2017, "
        "with billing currency shown as a field. Do not assume or filter to a "
        "currency unless needed to keep amounts comparable."
    )
    sql = build_dimension_ranking_sql(question, ["VBRK", "KNA1"])
    assert sql
    assert 'AS "country"' in sql
    assert 'AS "currency"' in sql
    assert 'GROUP BY TRIM(c."land1"), k."waerk"' in sql
    assert "= '2017'" in sql
    assert 'PARTITION BY grouped."currency"' in sql
    assert '"rank_within_currency" <= 5' in sql
    assert not re.search(r'\."(?:waerk|waers|rtcur)"\s*=\s*\'[A-Z]{3}\'', sql, re.I)
    assert sql_satisfies_analytical_intent(sql, question)


def test_currency_partitioned_top_n_result_allows_up_to_n_per_currency():
    question = (
        "Show the top five countries by billed sales in calendar year 2017, "
        "with billing currency shown as a field. Do not filter to one currency."
    )
    sql = build_dimension_ranking_sql(question, ["VBRK", "KNA1"])
    assert sql
    rows = [
        {"country": country, "currency": currency, "total_sales": value}
        for currency, entries in {
            "USD": [("US", 100), ("CA", 90), ("MX", 80), ("BR", 70)],
            "EUR": [("DE", 120), ("FR", 110), ("IT", 100)],
        }.items()
        for country, value in entries
    ]
    assert result_matches_analytical_intent(rows, question, sql=sql) == []

    rows.extend(
        {"country": f"US{i}", "currency": "USD", "total_sales": 1}
        for i in range(5)
    )
    assert "currency-partitioned top-n exceeded limit 5" in result_matches_analytical_intent(
        rows, question, sql=sql
    )


def test_output_field_word_does_not_route_business_ranking_to_schema_metadata():
    question = (
        "Show the top five countries by billed sales in calendar year 2017, "
        "with billing currency shown as a field. Do not filter to one currency. "
        "Show the SQL."
    )
    assert not is_database_metadata_question(question)
    assert is_database_metadata_question("Which field stores the billing document number?")


def test_country_ranking_template_wins_in_sql_pipeline_with_noisy_llm_plan(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "fkdat", "kunag", "netwr", "waerk"},
        "KNA1": {"kunnr", "land1", "name1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())

    question = (
        "Show the top five countries by billed sales in calendar year 2017, "
        "with billing currency shown as a field; do not filter to one currency."
    )
    noisy_plan = {
        "dimensions": ["customer"],
        "group_by": ["customer"],
        "measure": {"concept": "revenue", "aggregation": "SUM"},
        "ranking": {"direction": "DESC", "limit": 10},
    }
    ctx = VerifiedDbContext(
        question=question,
        tables=list(physical_columns),
        semantic_requirements=required_semantics(question, noisy_plan),
    )
    from app.services.four_stage_db_pipeline import pipeline3_sql_generation

    sql = pipeline3_sql_generation(question, ctx)
    assert sql
    assert ctx.pipeline_log["PIPELINE_3_SQL_GENERATION"]["source"] == "dimension_ranking_template"
    assert 'AS "country"' in sql and 'AS "currency"' in sql
    assert 'AS "total_sales"' in sql
    assert 'PARTITION BY grouped."currency"' in sql
    assert "= '2017'" in sql
    assert not re.search(r'\."(?:waerk|waers|rtcur)"\s*=\s*\'[A-Z]{3}\'', sql, re.I)


def test_linked_order_comparison_keeps_invoice_rows_and_uses_verified_posting_date(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    physical_columns = {
        "VBRK": {"vbeln", "netwr", "waerk", "kunag", "belnr", "gjahr", "bukrs"},
        "VBFA": {"vbeln", "vbelv"},
        "VBAK": {"vbeln", "netwr", "waerk", "erdat"},
        "BKPF": {"belnr", "gjahr", "bukrs", "budat"},
        "KNA1": {"kunnr", "name1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in physical_columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in physical_columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())

    question = (
        "Show the ten most negative billed invoices in 2000, compare 2000 with 2001, "
        "use invoice posting date, list billing document numbers first based on customer, "
        "and compare the linked sales orders for those invoices in 2000 vs 2001."
    )
    noisy_plan = {
        "dimensions": ["customer"],
        "group_by": ["customer"],
        "measure": {"concept": "revenue", "aggregation": "SUM"},
        "ranking": {"direction": "ASC", "limit": 10},
    }
    assert required_semantics(question, noisy_plan)["group_by"] == ["document"]
    sql = build_linked_order_period_comparison_sql(
        question, list(physical_columns), noisy_plan
    )
    assert sql
    assert 'JOIN "BKPF" fi' in sql
    assert 'fi."belnr" = k."belnr"' in sql
    assert 'TRIM(CAST(fi."budat" AS TEXT)) >= \'20000101\'' in sql
    assert 'TRIM(CAST(fi."budat" AS TEXT)) < \'20010101\'' in sql
    assert "< 0" in sql
    assert 'AS "billing_document"' in sql
    assert 'AS "order_amount_2000"' in sql
    assert 'AS "order_amount_2001"' in sql
    assert 'AS "currency_mismatch_order_count"' in sql
    assert 'AS "absolute_change"' in sql
    assert 'AS "percent_change"' in sql
    assert 'UPPER(TRIM(CAST(l."linked_order_currency" AS TEXT))) = UPPER(i."currency")' in sql
    assert "GROUP BY l.\"billing_document\"" in sql
    assert "LIMIT 10" in sql
    assert sql_satisfies_analytical_intent(sql, question)
    rows = [{
        "billing_document": "1", "customer_id": "2", "customer_name": "Example",
        "invoice_date": "20000101", "invoice_amount": -10, "currency": "USD",
        "order_amount_2000": 20, "order_amount_2001": 25,
        "absolute_change": 5, "percent_change": 25,
    }]
    assert result_matches_analytical_intent(rows, question, sql=sql) == []


def test_latest_year_questions_get_dynamic_relative_semantics():
    question = "How many sales orders were created in the latest full calendar year?"
    req = required_semantics(question)
    assert req["measure"] == {"concept": "sales_order", "aggregation": "COUNT"}
    assert req["date_filter"]["type"] == "latest_data_years"
    assert req["date_filter"]["count"] == 1

    question = "For that country, show billed sales by year for the latest two full years in the data."
    req = required_semantics(question)
    assert req["group_by"] == ["year"]
    assert req["date_filter"]["period"] == "latest_two_full_years"
    assert req["date_filter"]["count"] == 2


def test_resolved_latest_period_summary_identifies_data_source():
    ctx = VerifiedDbContext(
        question="Show sales for the latest complete calendar year.",
        semantic_requirements={"time_filter": {
            "relative": "latest_full_year",
            "years": ["2017"],
            "resolved_from_data": True,
            "date_table": "VBRK",
            "date_column": "FKDAT",
            "coverage_basis": "calendar period within observed date range",
        }},
    )
    note = _resolved_latest_period_note(ctx)
    assert "2017 was selected dynamically" in note
    assert "VBRK.FKDAT" in note
    assert "completeness check" in note


def test_explicit_latest_complete_year_overrides_conflicting_llm_period():
    question = "Show billed sales for the latest complete year available in the data."
    req = required_semantics(
        question,
        {"time_filter": {"relative": "this_month"}},
    )
    assert req["date_filter"]["type"] == "latest_data_years"
    assert req["date_filter"]["period"] == "latest_full_year"


def test_latest_data_year_resolution_uses_schema_meaning_and_verified_years():
    question = "Show billed sales by year for the latest two full years."
    ctx = VerifiedDbContext(
        question=question,
        tables=["VBRK"],
        columns=["VBRK.ERDAT", "VBRK.FKDAT"],
        semantic_requirements={"time_filter": {"relative": "latest_two_full_years"}},
    )
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        ("2001", "20011231", "19991231"), ("2000", "20011231", "19991231")
    ]

    assert _resolve_latest_data_years(question, ctx, db) is True
    executed_sql = str(db.execute.call_args.args[0])
    assert '"VBRK"."FKDAT"' in executed_sql
    assert ctx.semantic_requirements["time_filter"]["years"] == ["2000", "2001"]
    assert ctx.semantic_requirements["time_filter"]["start_yyyymmdd"] == "20000101"
    assert ctx.semantic_requirements["time_filter"]["end_yyyymmdd"] == "20020101"


def test_both_period_change_sql_fields_are_generated():
    period = {
        "base_period": {"year": "2000"},
        "comparison_period": {"year": "2001"},
        "calculation": "both",
    }
    plan = StructuredQueryPlan(
        tables=["VBRK", "VBRP"],
        select=[
            PlanField(type="column", table="VBRK", column="vbeln", alias="billing_document"),
            PlanField(type="column", table="VBRP", column="netwr", alias="sales", purpose="measure"),
        ],
        semantic_requirements={"measure": {"concept": "revenue"}},
        period_compare=period,
    )
    with (
        patch("app.services.adaptive_structured_sql._find_date_column", return_value=("VBRK", "fkdat")),
        patch("app.services.adaptive_structured_sql._find_measure_column", return_value=("VBRP", "netwr")),
    ):
        _apply_period_compare_fields(plan, plan.semantic_requirements)
    aliases = {field.alias for field in plan.select}
    assert {"period_a", "period_b", "change", "pct_change"} <= aliases


def test_result_followup_can_rank_a_country_from_prior_rows():
    rows = [
        {"country": "US", "total_billed_sales": "7,000"},
        {"country": "DE", "total_billed_sales": "5,000"},
    ]
    result = try_answer_from_prior_rows("Which country was highest in that result?", rows)
    assert result is not None
    assert result["answer_status"] == "SUCCESS"
    assert result["data"][0]["country"] == "US"


def test_result_followup_calculates_difference_between_prior_rows():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": "1,227,978"},
        {"country": "DE", "currency": "USD", "total billed sales": "10,000"},
    ]
    question = "Which country had higher billed sales in that result, and what was the difference?"
    prior_sql = 'SELECT "country", SUM("netwr") AS "total billed sales" FROM "VBRK" GROUP BY 1'
    result = try_answer_from_prior_rows(question, rows, prior_sql=prior_sql)
    assert is_result_scoped_followup(question, has_prior_rows=True)
    assert is_referential_database_action(question, has_prior=True)
    assert result is not None
    assert result["answer_status"] == "SUCCESS"
    assert result["sql"] == ""
    assert result["source_sql"] == prior_sql
    assert "US had higher" in result["summary"]
    assert "1,217,978 USD" in result["summary"]


def test_result_followup_does_not_subtract_different_currencies():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": "1,200"},
        {"country": "DE", "currency": "EUR", "total billed sales": "1,000"},
    ]
    result = try_answer_from_prior_rows(
        "What was the difference between those results?", rows
    )
    assert result is not None
    assert result["answer_status"] == "CLARIFICATION"
    assert "different currencies" in result["summary"]


def test_higher_country_followup_asks_for_currency_when_prior_ranking_mixes_currencies():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": 1200},
        {"country": "DE", "currency": "EUR", "total billed sales": 1000},
    ]
    result = try_answer_from_prior_rows(
        "For the higher-sales country, show monthly billed sales in the same year and currency.",
        rows,
        prior_plan={
            "verified_db_context": {
                "semantic_requirements": {
                    "time_filter": {"resolved_from_data": True, "years": ["2017"]}
                }
            }
        },
    )
    assert result
    assert result["answer_status"] == "CLARIFICATION"
    assert result["sql"] == ""
    assert result["meta"]["followup"] == "currency_ambiguity"
    assert "Which currency" in result["answer"]


def test_currency_clarification_resumes_followup_from_verified_ranking():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": 1227978, "rank within currency": 1},
        {"country": "DE", "currency": "USD", "total billed sales": 10000, "rank within currency": 2},
        {"country": "EG", "currency": "EUR", "total billed sales": 22081, "rank within currency": 1},
        {"country": "DE", "currency": "EUR", "total billed sales": 3890, "rank within currency": 2},
    ]
    prior_plan = {
        "last_user_question": "Show the top countries by billed sales for calendar year 2017, by currency.",
        "verified_db_context": {
            "semantic_requirements": {
                "time_filter": {"resolved_from_data": True, "years": ["2017"]}
            }
        },
    }
    clarification = try_answer_from_prior_rows(
        "For the higher-sales country, show monthly billed sales in the same year and currency.",
        rows,
        prior_plan=prior_plan,
    )
    assert clarification and clarification["answer_status"] == "CLARIFICATION"
    assert clarification["query_plan"]["pending_clarification"]["kind"] == "currency_ambiguity"

    # The clarification turn retains the successful source analysis separately;
    # API context restoration merges its pending marker back into that plan.
    retained_plan = {
        **prior_plan,
        "pending_clarification": clarification["query_plan"]["pending_clarification"],
    }
    resumed = resolve_pending_currency_clarification("USD", rows, retained_plan)
    assert resumed == (
        "For country code 'US', show monthly billed sales in calendar year 2017 in currency USD."
    )


def test_currency_clarification_does_not_guess_on_invalid_currency_or_tied_leader():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": 100, "rank within currency": 1},
        {"country": "DE", "currency": "USD", "total billed sales": 100, "rank within currency": 1},
        {"country": "FR", "currency": "EUR", "total billed sales": 90, "rank within currency": 1},
    ]
    pending = {
        "pending_clarification": {
            "kind": "currency_ambiguity",
            "question": "For the higher-sales country, show monthly billed sales in the same year and currency.",
            "currency_column": "currency",
        },
        "last_user_question": "Show top countries by sales for calendar year 2017.",
        "verified_db_context": {
            "semantic_requirements": {
                "time_filter": {"resolved_from_data": True, "years": ["2017"]}
            }
        },
    }
    assert resolve_pending_currency_clarification("JPY", rows, pending) is None
    assert resolve_pending_currency_clarification("USD", rows, pending) is None


def test_currency_clarification_requires_a_verified_year():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": 100, "rank within currency": 1},
        {"country": "DE", "currency": "EUR", "total billed sales": 90, "rank within currency": 1},
    ]
    pending = {
        "pending_clarification": {
            "kind": "currency_ambiguity",
            "question": "For the higher-sales country, show monthly billed sales in the same year and currency.",
            "currency_column": "currency",
        },
        "last_user_question": "Show top countries by billed sales for the latest complete year.",
    }
    assert resolve_pending_currency_clarification("USD", rows, pending) is None


def test_failed_followup_can_restore_client_retained_successful_analysis():
    from app.api.adaptive_query import _usable_retained_analytical_context

    retained = {
        "previousQuestion": "Show billed sales by country for calendar year 2017 in USD.",
        "previousSQL": 'SELECT "country", SUM("netwr") FROM "VBRK" GROUP BY 1',
        "previousPlan": {
            "verified_db_context": {
                "tables": ["VBRK", "KNA1"],
                "semantic_requirements": {
                    "time_filter": {"resolved_from_data": True, "years": ["2017"]},
                },
            },
        },
        "previousAnswerStatus": "SUCCESS",
        "data": [{"country": "US", "total_billed_sales": 1227978, "currency": "USD"}],
    }

    # The current assistant response can be an error while the nested retained
    # anchor still points to a successful, verified analysis.
    context = _usable_retained_analytical_context({"retained_analytical_context": retained})
    assert context == retained
    assert _usable_retained_analytical_context({
        "retained_analytical_context": {**retained, "previousAnswerStatus": "CANNOT_ANSWER"}
    }) is None


def test_deeper_ranked_country_followup_reuses_verified_period_and_currency():
    rows = [
        {"country": "US", "currency": "USD", "total billed sales": "1,227,978"},
        {"country": "DE", "currency": "USD", "total billed sales": "10,000"},
    ]
    prior_plan = {
        "last_user_question": "Show billed sales for the latest complete calendar year available.",
        "verified_db_context": {
            "semantic_requirements": {
                "time_filter": {
                    "resolved_from_data": True,
                    "years": ["2017"],
                    "type": "latest_data_years",
                }
            }
        },
    }
    result = try_answer_from_prior_rows(
        "For the higher-sales country, show monthly billed sales in the same year and currency.",
        rows,
        prior_plan=prior_plan,
    )
    assert result and result["needs_plan_expansion"]
    assert result["expanded_question"] == (
        "Show billed sales by month for country code 'US' in calendar year 2017 in currency USD."
    )


def test_expanded_country_period_query_reuses_verified_schema_for_sql_generation():
    question = (
        "Show billed sales by month for country code 'US' "
        "in calendar year 2017 in currency USD."
    )
    prior = {
        "verified_db_context": {
            "tables": ["VBRK", "KNA1"],
            "columns": ["VBRK.FKDAT", "VBRK.NETWR", "VBRK.WAERK", "KNA1.LAND1"],
            "joins": [],
            "relationships": [],
        }
    }

    assert _apply_followup_to_context(question, prior) is None
    context = _apply_followup_to_context(
        question, {**prior, "result_first_requery": True}
    )
    assert context is not None
    assert set(context.tables) == {"VBRK", "KNA1"}
    assert context.pipeline_log["followup_requery"] is True


def test_followup_routing_distinguishes_recall_from_database_augmentation():
    recall = "Earlier you counted billing documents; what was the count and which table and column did SQL count?"
    augment = "Add the customer and billing date for those documents."
    assert is_prior_turn_discourse(recall, has_prior=True)
    assert not is_referential_database_action(recall, has_prior=True)
    assert is_referential_database_action(augment, has_prior=True)

    implicit_lineage_recall = "What was the count, and which table and column did SQL count?"
    assert is_prior_turn_discourse(implicit_lineage_recall, has_prior=True)
    assert not is_referential_database_action(implicit_lineage_recall, has_prior=True)

    prior = {"investigation_state": {"last_sql": 'SELECT COUNT(DISTINCT v."vbeln") FROM "VBAK" v'}}
    context = _context_block(
        prior_question="How many sales orders are in the database?",
        prior_summary="65,720 sales documents in VBAK.",
        prior_plan=prior,
        current_question=implicit_lineage_recall,
    )
    assert "VBAK" in context and "vbeln" in context


def test_database_augmentation_reuses_prior_verified_tables_and_flags_requery():
    prior = {
        "verified_db_context": {
            "tables": ["VBRK", "VBRP"],
            "columns": ["VBRK.VBELN", "VBRP.NETWR"],
            "joins": [],
            "relationships": [],
        }
    }
    ctx = _apply_followup_to_context(
        "Add the customer and billing date for those documents.", prior
    )
    assert ctx is not None
    assert ctx.pipeline_log["followup_requery"] is True
    assert set(ctx.tables) == {"VBRK", "VBRP"}


def test_sql_placeholder_values_are_rejected_before_execution():
    assert _contains_unresolved_sql_value(
        'SELECT * FROM "VBRK" WHERE "VBELN" = <document_id>'
    )
    assert _contains_unresolved_sql_value('SELECT * FROM "VBRK" WHERE "VBELN" = your_document_id')
    assert not _contains_unresolved_sql_value('SELECT * FROM "VBRK" WHERE "VBELN" = \'0000000001\'')


def test_retrieved_memory_keeps_old_query_and_sql_lineage_without_literals():
    turns = [
        {"role": "user", "content": "How many billing documents are in the database?"},
        {
            "role": "assistant",
            "content": "35,057 billing documents. Verified SQL structure: SELECT COUNT(VBRK.VBELN) FROM VBRK WHERE VBRK.FKDAT >= ?",
        },
    ]
    for index in range(10):
        turns.extend(
            [
                {"role": "user", "content": f"Tell me about unrelated topic {index}."},
                {"role": "assistant", "content": f"An unrelated explanation {index}."},
            ]
        )
    retrieved = relevant_conversation(
        "Earlier you counted billing documents; what was the count and which table and column did SQL count?",
        turns,
        recent_limit=6,
    )
    content = "\n".join(turn["content"] for turn in retrieved)
    assert "35,057" in content
    assert "VBRK.VBELN" in content
    assert "billing documents" in content

    compact = compact_sql_lineage(
        "SELECT COUNT(\"VBRK\".\"VBELN\") FROM \"VBRK\" "
        "WHERE \"VBRK\".\"FKDAT\" >= '20000101' LIMIT 10"
    )
    assert "VBELN" in compact and "FKDAT" in compact
    assert "20000101" not in compact and "LIMIT 10" not in compact


def test_period_recall_points_to_most_recent_user_time_request():
    recent_turns = [
        {"role": "user", "content": "For that country, show billed sales by year for the latest two full years in the data."},
        {"role": "assistant", "content": "I will compare the latest two full years."},
        {"role": "user", "content": "Which five materials had the highest billed sales in the latest full year?"},
        {"role": "assistant", "content": "Here are the materials."},
        {"role": "user", "content": "What is a billing document in SAP?"},
        {"role": "assistant", "content": "It represents a customer billing transaction."},
    ]
    context = _context_block(
        prior_plan={"investigation_state": {"recent_turns": recent_turns}},
        current_question="Which period did I ask about most recently?",
    )
    assert "most recent prior user request specifying a time period" in context.lower()
    assert "latest full year" in context


def test_response_schema_evidence_prefers_primary_sap_field_labels():
    recent = [
        {"role": "user", "content": "For VBRK list columns."},
        {"role": "assistant", "content": "VBRK.vbeln and VBRK.fkdat are key fields."},
    ]
    doc_fields = _schema_semantics_evidence("What is a billing document number in SAP?", recent)
    date_fields = _schema_semantics_evidence("Which of those columns is the billing date?", recent)
    assert doc_fields[0].startswith("VBRK.VBELN:")
    assert date_fields[0].startswith("VBRK.FKDAT:")
