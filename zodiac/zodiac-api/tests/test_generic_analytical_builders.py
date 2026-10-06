"""Unit tests for generic analytical SQL builders (no question-specific handlers)."""
from __future__ import annotations

from app.services.adaptive_structured_sql import (
    build_above_average_sql,
    build_dimension_ranking_sql,
    build_document_count_by_period_sql,
    build_dimension_period_sales_sql,
    build_negation_anti_join_sql,
    build_partitioned_topn_sql,
    build_period_compare_sql,
)
from app.services.analytical_operations import extract_analytical_operations
from app.services.plan_satisfaction import sql_satisfies_analytical_intent
from app.services.semantic_requirements import required_semantics


def test_vendor_purchase_ranking_is_generic():
    q = "List the top 8 vendors by purchase order value."
    sql = build_dimension_ranking_sql(q, [])
    assert sql and "lifnr" in sql.lower() and "LIMIT 8" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_document_count_by_year():
    q = "How many billing documents were created each year?"
    sql = build_document_count_by_period_sql(q, [])
    assert sql and "GROUP BY" in sql.upper() and "COUNT" in sql.upper()
    assert "SUBSTRING" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_top_plural_entity_infers_result_grain_without_model():
    req = required_semantics(
        "Show the top five countries by billed sales in the latest complete year available.",
        {},
    )
    assert req["dimensions"] == ["country"]
    assert req["group_by"] == ["country"]
    assert req["ranking"]["limit"] == 5
    assert req["date_filter"]["type"] == "latest_data_years"


def test_monthly_country_sales_uses_values_supplied_by_user():
    question = (
        "Show billed sales by month for country code 'US' in calendar year 2017 "
        "in currency USD."
    )
    sql = build_dimension_period_sales_sql(question, [])
    assert sql
    assert "'US'" in sql
    assert "'2017'" in sql
    assert "'USD'" in sql
    assert '"VBRK"' in sql


def test_schema_backed_pipeline_generates_supported_sql_during_model_outage(monkeypatch):
    from app.services import adaptive_structured_sql, four_stage_db_pipeline

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(four_stage_db_pipeline, "analyze_json", unavailable)
    monkeypatch.setattr(four_stage_db_pipeline, "complete_text", unavailable)
    monkeypatch.setattr(adaptive_structured_sql, "analyze_json", unavailable)
    question = (
        "Show billed sales by month for country code 'US' in calendar year 2017 "
        "in currency USD."
    )
    context = four_stage_db_pipeline.VerifiedDbContext(question=question)
    four_stage_db_pipeline.pipeline1_table_selection(question, context)
    four_stage_db_pipeline.pipeline2_column_selection(question, context)
    four_stage_db_pipeline.pipeline25_query_plan(question, context, db=None)
    sql = four_stage_db_pipeline.pipeline3_sql_generation(question, context)
    assert sql
    assert "'US'" in sql and "'2017'" in sql and "'USD'" in sql


def test_result_analysis_returns_verified_row_count_when_model_is_unavailable(monkeypatch):
    from app.services import four_stage_db_pipeline

    monkeypatch.setattr(
        four_stage_db_pipeline,
        "analyze_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    context = four_stage_db_pipeline.VerifiedDbContext(question="Show billed sales")
    result = four_stage_db_pipeline.pipeline4_result_analysis(
        "Show billed sales",
        'SELECT "VBRK"."netwr" FROM "VBRK"',
        [{"netwr": "not exposed in fallback prose"}],
        context,
    )
    assert result["summary"] == "The query completed and returned 1 row(s). See the result table for the verified values."
    assert result["findings"] == []


def test_above_average_builder():
    q = "Which customers had billed sales above the average customer sales?"
    sql = build_above_average_sql(q, [])
    assert sql and "AVG" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_plant_partition_detection():
    q = "Which materials had the highest billed quantity in each plant?"
    ops = extract_analytical_operations(q)
    assert "plant" in (ops.get("partition_by") or [])
    sql = build_partitioned_topn_sql(q, [])
    assert sql and "PARTITION BY" in sql.upper() and "plant" in sql.lower()
    assert sql_satisfies_analytical_intent(sql, q)


def test_period_decline_has_having():
    q = "Which country had the largest decline in sales between 2004 and 2005?"
    sql = build_period_compare_sql(q, [])
    assert sql and "HAVING" in sql.upper() and "2004" in sql and "2005" in sql
    assert sql_satisfies_analytical_intent(sql, q)


def test_period_comparison_monthly_compares_same_months_and_keeps_currency(monkeypatch):
    from app.services import adaptive_structured_sql as structured

    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() == "VBRK")
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: table.upper() == "VBRK" and column.lower() in {"vbeln", "netwr", "fkdat", "waerk", "mandt"},
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: "VBRK")
    question = "Compare monthly billed sales for 2013 with 2014, keeping each currency separate."
    semantic = {
        "period_compare": {
            "base_period": {"year": "2013"},
            "comparison_period": {"year": "2014"},
        },
        "group_by": ["month"],
    }
    sql = build_period_compare_sql(question, ["VBRK"], semantic)
    assert sql
    assert '"billing_document_rows" AS' in sql
    assert 'src."vbeln"' in sql
    assert 'AS "month"' in sql and 'AS "currency"' in sql
    assert "GROUP BY SUBSTRING" in sql
    assert "2013" in sql and "2014" in sql
    assert 'AS "period_a"' in sql and 'AS "period_b"' in sql and 'AS "change"' in sql
    assert sql_satisfies_analytical_intent(sql, question)


def test_material_ranking_carries_resolved_relative_year_bounds(monkeypatch):
    from app.services import adaptive_structured_sql as structured

    columns = {
        "VBRK": {"vbeln", "netwr", "fkdat", "waerk", "mandt"},
        "VBRP": {"mandt", "vbeln", "posnr", "netwr", "aubel", "aupos", "matnr", "fkimg", "vrkme"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in columns)
    monkeypatch.setattr(structured, "has_column", lambda table, column: column.lower() in columns.get(table.upper(), set()))
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    question = "Which 10 materials had the highest billed sales last year? Show the year and currency."
    semantic = {
        "time_filter": {"relative": "last_year", "start_yyyymmdd": "20250101", "end_yyyymmdd": "20260101"}
    }
    sql = build_dimension_ranking_sql(question, ["VBRK", "VBRP"], semantic)
    assert sql
    assert '"fkdat" AS TEXT)) >= \'20250101\'' in sql
    assert '"fkdat" AS TEXT)) < \'20260101\'' in sql
    assert 'AS "billing_year"' in sql
    assert 'CAST(p."netwr" AS TEXT)' in sql


def test_period_comparison_includes_requested_base_period_documents_and_percent_change(monkeypatch):
    from app.services import adaptive_structured_sql as structured

    tables = {"VBRK", "KNA1"}
    columns = {
        "VBRK": {"vbeln", "netwr", "fkdat", "kunag"},
        "KNA1": {"kunnr", "name1"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in tables)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())

    question = (
        "For the top 32 customers from 2017, compare billed sales between calendar years 2000 and 2001."
    )
    semantic = {
        "period_compare": {
            "type": "period_change",
            "base_period": {"year": "2000"},
            # Simulate the previous turn's year leaking into the LLM plan.
            "comparison_period": {"year": "2017"},
            "calculation": "both",
        },
        "ranking": {"direction": "DESC", "limit": 32},
        "include_fields": [{"field": "invoice_number", "year": "2000"}],
        "_original_user_question": (
            "For those same customers, compare billed sales in 2000 and 2001 "
            "and show the 2000 billing document numbers, absolute change, and percentage change."
        ),
        "prior_result_rows": [
            {"customer_id": "CUST-1", "customer_name": "Customer One"},
            {"customer_id": "CUST-2", "customer_name": "Customer Two"},
        ],
    }

    sql = structured.build_period_compare_sql(question, ["VBRK", "KNA1"], semantic)

    assert sql
    assert 'AS "invoice_numbers_2000"' in sql
    assert "STRING_AGG(DISTINCT CASE WHEN" in sql
    assert "= '2000'" in sql
    assert 'AS "percent_change"' in sql
    assert 'AS "change"' in sql
    assert "IN ('2000', '2001')" in sql
    assert "2017" not in sql
    assert "LIMIT 2" in sql
    assert "LPAD('CUST-1', 10, '0')" in sql
    assert "LPAD('CUST-2', 10, '0')" in sql
    assert "CUST-3" not in sql
    assert "WITH selected_customers(customer_id)" in sql
    assert "LEFT JOIN period_totals" in sql
    assert 'COALESCE(pt."period_a", 0)' in sql
    from app.services.ai_native_pipeline import _schema_violations
    assert not any("unknown table selected_customers" in issue.lower() for issue in _schema_violations(sql))
    from app.services.sap_sql_precision_validator import validate_sql_precision
    precision = validate_sql_precision(
        sql,
        {
            "VBRK": ["fkdat", "kunag", "netwr", "vbeln"],
            "KNA1": ["kunnr", "name1"],
        },
        question=semantic["_original_user_question"],
    )
    assert precision.is_valid, precision.errors


def test_same_customer_period_followup_uses_comparison_template_before_inherited_ranking(monkeypatch):
    from app.services import adaptive_structured_sql, four_stage_db_pipeline
    from app.services.four_stage_db_pipeline import VerifiedDbContext

    question = "For those same customers, compare billed sales in 2000 and 2001."
    checked_questions = []
    ctx = VerifiedDbContext(
        question="For the top 32 customers from 2017, compare billed sales in 2000 and 2001.",
        tables=["VBRK", "KNA1"],
        semantic_requirements={
            "_original_user_question": question,
            "prior_result_rows": [{"customer_id": "CUST-1"}],
            "period_compare": {"base_period": {"year": "2000"}, "comparison_period": {"year": "2017"}},
            "ranking": {"direction": "DESC", "limit": 32},
        },
    )
    monkeypatch.setattr(
        adaptive_structured_sql,
        "build_period_compare_sql",
        lambda *_args, **_kwargs: 'SELECT 1 AS "period_a", 2 AS "period_b", 1 AS "change"',
    )
    monkeypatch.setattr(
        adaptive_structured_sql,
        "build_dimension_ranking_sql",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("inherited ranking ran first")),
    )
    monkeypatch.setattr(
        "app.services.plan_satisfaction.sql_satisfies_analytical_intent",
        lambda _sql, checked_question, *_args, **_kwargs: (
            checked_questions.append(checked_question) or True
        ),
    )

    sql = four_stage_db_pipeline.pipeline3_sql_generation(ctx.question, ctx)

    assert sql and 'AS "period_a"' in sql
    assert ctx.pipeline_log["PIPELINE_3_SQL_GENERATION"]["source"] == "period_compare_template"
    assert checked_questions == [question]


def test_declined_past_tense_is_decrease_condition():
    from app.services.semantic_requirements import required_semantics
    from app.services.analytical_operations import extract_analytical_operations

    q = "Which country declined the most in billed sales between 2004 and 2005?"
    ops = extract_analytical_operations(q)
    assert (ops.get("period_compare") or {}).get("condition") == "decreased"
    req = required_semantics(q)
    assert (req.get("period_compare") or {}).get("condition") == "decreased"
    sql = build_period_compare_sql(q, [])
    assert sql and "< 0" in sql and "HAVING" in sql.upper()


def test_supplier_invoice_amount_uses_vendor_invoice_measure():
    from app.services.adaptive_structured_sql import detect_ranking_measure

    q = "Show the top 10 suppliers by invoice amount."
    assert detect_ranking_measure(q) == "vendor_invoice_value"
    sql = build_dimension_ranking_sql(q, [])
    assert sql and "RBKP" in sql.upper() and "invoice_amount" in sql.lower()
    assert "EKPO" not in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)

def test_negation_anti_join():
    q = "Which suppliers have purchase orders but no invoices?"
    sql = build_negation_anti_join_sql(q, [])
    assert sql and "NOT EXISTS" in sql.upper()
    assert "RBKP" in sql.upper() or "VBRK" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_plural_industry_ranking_limit_not_top1():
    from app.services.semantic_requirements import required_semantics
    from app.services.plan_satisfaction import result_matches_analytical_intent

    q = "Which industries generated the most billed sales?"
    req = required_semantics(q)
    assert int((req.get("ranking") or {}).get("limit") or 0) >= 10
    sql = (
        'SELECT industry, total_sales FROM t ORDER BY total_sales DESC LIMIT 10'
    )
    warnings = result_matches_analytical_intent(
        [{"industry": f"I{i}", "total_sales": 100 - i} for i in range(10)],
        q,
        semantic=req,
        sql=sql,
    )
    assert not any("ranking limit" in w for w in warnings)


def test_vendor_po_ranking_ignores_polluted_negation():
    from app.services.semantic_requirements import required_semantics

    q = "Which vendor has the highest purchase order value?"
    # Simulate LLM pollution: required PO without absence language.
    sem = {
        "dimensions": ["vendor"],
        "group_by": ["vendor"],
        "measure": {"concept": "purchase_order", "aggregation": "SUM"},
        "ranking": {"direction": "DESC", "limit": 1},
        "negation": {"required": "purchase_order", "forbidden": None},
    }
    req = required_semantics(q, sem)
    assert not req.get("negation")
    sql = build_dimension_ranking_sql(q, [])
    assert sql and sql_satisfies_analytical_intent(sql, q, sem)


def test_explicit_ranking_grain_overrides_unrequested_model_dimensions(monkeypatch):
    from app.services import four_stage_db_pipeline

    question = "Show the top 32 customers by billed sales in calendar year 2017 in USD."
    monkeypatch.setattr(
        four_stage_db_pipeline,
        "analyze_json",
        lambda *_args, **_kwargs: (
            {
                "dimensions": ["customer", "country"],
                "group_by": ["customer", "country"],
                "measure": {"concept": "revenue", "aggregation": "SUM"},
                "ranking": {"direction": "DESC", "limit": 32},
            },
            "test",
        ),
    )

    semantic = four_stage_db_pipeline.extract_semantic_requirements(question)

    assert semantic["dimensions"] == ["customer"]
    assert semantic["group_by"] == ["customer"]
    assert semantic["ranking"]["limit"] == 32
    assert semantic["time_filter"]["value"] == "2017"
    # Currency filtering remains a separate constraint; it is not an output grain.
    assert "country" not in semantic["dimensions"]


def test_cte_schema_violations_allow_local_relations():
    from app.services.ai_native_pipeline import _schema_violations

    sql = build_above_average_sql(
        "Which customers have sales above the average?",
        [],
    )
    assert sql and sql.upper().startswith("WITH")
    viol = _schema_violations(sql)
    assert not any("unknown table cust" in v.lower() for v in viol), viol
    assert not any("unknown table avg_v" in v.lower() for v in viol), viol


def test_multi_entity_having_uses_transactional_country():
    from app.services.adaptive_structured_sql import build_multi_entity_having_sql
    from app.services.analytical_operations import extract_analytical_operations

    q = "Which customers bought products in more than one country?"
    ops = extract_analytical_operations(q)
    assert ops.get("having_distinct")
    assert ops["having_distinct"]["grain"] == "transaction"
    sql = build_multi_entity_having_sql(q, [])
    assert sql and "HAVING" in sql.upper() and "COUNT(DISTINCT" in sql.upper()
    assert 'k."land1"' in sql.lower() or 'k."LAND1"' in sql
    # Must not count master-only KNA1.land1 for transactional attribution.
    assert "c.\"land1\"" not in sql.lower().replace(" ", "")
    assert sql_satisfies_analytical_intent(sql, q)


def test_qualitative_threshold_clarification_generic():
    from app.services.threshold_semantics import detect_threshold_clarification
    from app.services.analytical_operations import extract_analytical_operations

    q = "Which materials generated high quantity but relatively low billed value?"
    clar = detect_threshold_clarification(q)
    assert clar and clar["type"] == "threshold_definition"
    ops = extract_analytical_operations(q)
    assert (ops.get("clarification") or {}).get("type") == "threshold_definition"

    # Ranking must not ask for thresholds.
    assert detect_threshold_clarification("Which customers generated the highest billed sales?") is None
    # Explicit average is executable.
    assert detect_threshold_clarification(
        "Which customers had billed sales above the average customer sales?"
    ) is None


def test_cancel_sets_cancelled_answer_status():
    from app.services.investigation_budget import (
        begin_investigation,
        cancel_investigation,
        end_investigation,
        timeout_response,
    )

    b = begin_investigation("test cancel", limit_s=30, request_id="cancel-unit-test-1")
    assert cancel_investigation(b.request_id) is True
    payload = timeout_response("sql_generation", question="test cancel")
    assert payload["answer_status"] == "CANCELLED"
    assert payload["status"] == "cancelled"
    end_investigation("cancelled")
    # Case E: cancel after completion must not flip status.
    b2 = begin_investigation("done", limit_s=30, request_id="cancel-unit-test-2")
    end_investigation("completed")
    assert cancel_investigation(b2.request_id) is False
