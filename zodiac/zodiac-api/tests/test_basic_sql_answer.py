"""Basic mode and greetings must not call a paid model."""
import pytest
from app.services.adaptive_analyst.llm_provider import analyze_json
from app.services.adaptive_nl_sql_hardening import is_greeting_or_chitchat
from app.services.basic_sql_answer import continue_basic_question, recall_saved_sql, run_basic_sql_answer
from app.services.investigation_budget import block_paid_models, paid_models_blocked, restore_paid_models


def test_hai_is_a_greeting_and_not_a_database_question():
    assert is_greeting_or_chitchat("hai")
    assert is_greeting_or_chitchat("Hai")


def test_basic_pattern_does_not_call_a_model(monkeypatch):
    monkeypatch.setattr(
        "app.services.four_stage_db_pipeline.pipeline3_sql_generation",
        lambda question, ctx, templates_only=False: 'SELECT vbeln FROM "VBRK"',
    )
    monkeypatch.setattr(
        "app.services.schema_intelligence_registry.get_schema_registry",
        lambda: type("R", (), {"lightweight_table_catalog": lambda self, include_operational=False: [{"table": "VBRK"}]})(),
    )

    def execute(sql):
        assert paid_models_blocked()
        return {"ok": True, "sql": sql, "source": "business", "rows": [{"vbeln": "1"}]}

    result = run_basic_sql_answer("top customers", execute=execute)
    assert result["llm_calls"] == 0
    assert result["meta"]["credits_used"] is False
    assert paid_models_blocked() is False


def test_order_invoice_comparison_confirmation_names_both_values():
    from app.services.basic_sql_answer import _describe_predefined_pattern

    logic, warning = _describe_predefined_pattern(
        "Compare sales order and invoice values by country and customer in 2000",
        'WITH order_totals AS (SELECT "sales_order_net_value" FROM "VBAK"), '
        'invoice_totals AS (SELECT "invoice_net_value" FROM "VBRK") '
        'SELECT order_totals."sales_order_net_value", invoice_totals."invoice_net_value", '
        'order_totals."sales_order_net_value" - invoice_totals."invoice_net_value" '
        'AS "order_minus_invoice_net_value" GROUP BY "year", "customer_id", "country_code"',
    )

    assert "sales order value, invoice value, and their difference" in logic
    assert "customer" in logic and "country" in logic
    assert warning == ""


def test_order_invoice_comparison_template_is_marked_for_independent_grain_proof():
    from app.services.basic_sql_answer import _predefined_template_step

    sql = (
        'WITH "customer_dim" AS (SELECT "kunnr" FROM "KNA1"), '
        '"order_rows" AS (SELECT "netwr" FROM "VBAK"), '
        '"invoice_rows" AS (SELECT "netwr" FROM "VBRK"), '
        '"order_totals" AS (SELECT SUM("netwr") AS "sales_order_net_value" FROM "order_rows"), '
        '"invoice_totals" AS (SELECT SUM("netwr") AS "invoice_net_value" FROM "invoice_rows") '
        'SELECT "sales_order_net_value", "invoice_net_value", '
        '"order_minus_invoice_net_value" FROM "order_totals"'
    )
    assert _predefined_template_step(sql)["basic_predefined_template"] == "sales_order_invoice_customer_comparison"
    assert _predefined_template_step('SELECT "vbeln" FROM "VBAK" LIMIT 10') is None


def test_basic_runs_approved_order_invoice_template_with_its_proof_marker(monkeypatch):
    from app.services.basic_sql_answer import run_basic_sql_answer

    sql = (
        'WITH "customer_dim" AS (SELECT "kunnr" FROM "KNA1"), '
        '"order_rows" AS (SELECT "netwr" FROM "VBAK"), '
        '"invoice_rows" AS (SELECT "netwr" FROM "VBRK"), '
        '"order_totals" AS (SELECT SUM("netwr") AS "sales_order_net_value" FROM "order_rows"), '
        '"invoice_totals" AS (SELECT SUM("netwr") AS "invoice_net_value" FROM "invoice_rows") '
        'SELECT "sales_order_net_value", "invoice_net_value", '
        '"order_minus_invoice_net_value" FROM "order_totals"'
    )
    monkeypatch.setattr(
        "app.services.four_stage_db_pipeline.pipeline3_sql_generation",
        lambda question, ctx, templates_only=False: sql,
    )
    monkeypatch.setattr(
        "app.services.schema_intelligence_registry.get_schema_registry",
        lambda: type("R", (), {"lightweight_table_catalog": lambda self, include_operational=False: [
            {"table": "VBAK"}, {"table": "VBRK"}, {"table": "KNA1"}
        ]})(),
    )
    seen = {}

    def execute(query, step=None):
        seen["query"] = query
        seen["step"] = step
        return {"ok": True, "sql": query, "source": "business", "rows": []}

    result = run_basic_sql_answer(
        "Compare sales order and invoice value by country and customer in 2000",
        execute=execute,
        approve_predefined=True,
        prior_examples=[],
    )

    assert seen["query"] == sql
    assert seen["step"]["basic_predefined_template"] == "sales_order_invoice_customer_comparison"
    assert result["answer_status"] == "SUCCESS_EMPTY"


def test_basic_document_count_states_the_count_not_the_result_row_count(monkeypatch):
    monkeypatch.setattr(
        "app.services.four_stage_db_pipeline.pipeline3_sql_generation",
        lambda question, ctx, templates_only=False: 'SELECT COUNT(*) AS "billing_document_count" FROM "VBRK"',
    )
    result = run_basic_sql_answer(
        "How many billing documents are missing a currency code in 2001?",
        execute=lambda sql: {"ok": True, "sql": sql, "rows": [{"billing_document_count": 0}]},
        approve_predefined=True,
    )
    assert result["answer"].startswith("0 billing documents match the requested filters.")
    assert result["llm_calls"] == 0
    assert result["meta"]["credits_used"] is False


def test_missing_currency_question_uses_the_real_basic_pattern_without_a_model():
    question = "How many billing documents are missing a currency code in 2001?"
    def execute(sql):
        assert 'FROM "VBRK"' in sql
        assert '"waerk"' in sql and 'IS NULL' in sql
        assert '"fkdat"' in sql and '2001%' in sql
        return {"ok": True, "sql": sql, "source": "business",
                "rows": [{"billing_document_count": 0}]}

    result = run_basic_sql_answer(question, execute=execute, approve_predefined=True)
    assert result["answer_status"] == "SUCCESS"
    assert result["answer"].startswith("0 billing documents match the requested filters.")
    assert result["llm_calls"] == 0


def test_document_count_does_not_get_billed_net_drilldown_warning():
    from app.services.analyst_drilldown import drilldown_note

    assert drilldown_note('SELECT COUNT(*) AS "billing_document_count" FROM "VBRK"',
                          [{"billing_document_count": 0}], {}) is None


def test_hardcoded_question_is_explained_without_a_model():
    called = {"n": 0}

    def execute(sql):
        called["n"] += 1
        return {"ok": True, "sql": sql, "rows": []}

    result = run_basic_sql_answer("are you harded coded?", execute=execute)
    assert called["n"] == 0
    assert result["llm_calls"] == 0
    assert result["mode"] == "general_chat"
    assert "total billed sales in 2001" in result["answer"]


def test_repeat_question_reuses_saved_sql_without_a_model(monkeypatch):
    monkeypatch.setattr(
        "app.services.four_stage_db_pipeline.pipeline3_sql_generation",
        lambda question, ctx, templates_only=False: "",
    )
    monkeypatch.setattr(
        "app.services.schema_intelligence_registry.get_schema_registry",
        lambda: type("R", (), {"lightweight_table_catalog": lambda self, include_operational=False: []})(),
    )
    saved = 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY waerk'
    seen = {}

    def execute(sql):
        seen["sql"] = sql
        return {"ok": True, "sql": sql, "source": "business", "rows": [{"currency": "DEM", "total_sales": "10"}]}

    result = run_basic_sql_answer(
        "Please show total billed sales",
        execute=execute,
        prior_examples=[{"question": "total billed sales", "sql": saved}],
    )
    assert seen["sql"] == saved
    assert result["llm_calls"] == 0
    assert "already asked" in result["answer"]


def test_close_wording_reuses_the_saved_query_without_a_model():
    saved = 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY waerk'
    examples = [{"question": "total billed sales in 2001", "sql": saved}]
    assert recall_saved_sql("what were billed sales during 2001", examples) == saved
    assert recall_saved_sql("billed sales by customer in 2001", examples) == ""
    assert recall_saved_sql("billed sales for Germany in 2001", [{"question": "billed sales for France in 2001", "sql": saved}]) == ""
    assert recall_saved_sql("top 10 customers by billed sales", [{"question": "top 5 customers by billed sales", "sql": saved}]) == ""


def test_different_year_is_not_treated_as_the_same_question():
    saved = 'SELECT waerk AS currency, SUM(netwr) AS total_sales FROM "VBRK" GROUP BY waerk'
    assert recall_saved_sql("billed sales in 2001", [{"question": "billed sales in 2002", "sql": saved}]) == ""
    assert recall_saved_sql("show billed sales in 2001", [{"question": "billed sales in 2001", "sql": saved}]) == saved


def test_total_billed_sales_uses_a_saved_pattern_without_a_model():
    seen = {}

    def execute(sql):
        seen["sql"] = sql
        return {"ok": True, "sql": sql, "source": "business", "rows": [{"total_sales": "1"}]}

    result = run_basic_sql_answer("total billed sales in 2001", execute=execute, approve_predefined=True)
    assert "2001" in seen["sql"]
    assert "total_sales" in seen["sql"]
    assert result["llm_calls"] == 0
    assert result["meta"]["credits_used"] is False


def test_legacy_saved_mixed_currency_total_uses_the_current_safe_pattern():
    question = "total billed sales in 2001"
    legacy = 'SELECT SUM(netwr) AS total_sales FROM "VBRK" WHERE fkdat LIKE \'2001%\''
    seen = []

    def execute(sql):
        seen.append(sql)
        return {"ok": True, "sql": sql, "rows": [{"currency": "DEM", "total_sales": "10"}]}

    result = run_basic_sql_answer(question, execute=execute,
                                  prior_examples=[{"question": question, "sql": legacy}], approve_predefined=True)
    assert len(seen) == 1 and seen[0] != legacy
    assert 'GROUP BY' in seen[0] and 'waerk' in seen[0]
    assert result["meta"]["retrieval"]["reused"] is False
    assert result["llm_calls"] == 0


def test_bad_saved_profit_total_is_never_executed_as_checked_profit():
    bad = 'SELECT SUM("BSAD"."dmbtr") AS "total_sales" FROM "BSAD"'
    question = "show me highest profit"
    result = run_basic_sql_answer(question,
        execute=lambda *_: pytest.fail("Clearing total must not execute as checked profit"),
        prior_examples=[{"question": question, "sql": bad}])
    assert result["sql"] == "" and result["meta"]["needs_agent"] is True
    assert result["llm_calls"] == 0


def test_list_some_questions_returns_examples_without_a_model():
    called = {"n": 0}

    def execute(sql):
        called["n"] += 1
        return {"ok": True, "sql": sql, "rows": []}

    result = run_basic_sql_answer("list some questions to ask", execute=execute)
    assert called["n"] == 0
    assert "total billed sales in 2001" in result["answer"]
    assert result["mode"] == "general_chat"


def test_top_customers_limit_is_a_plain_integer():
    from app.api.adaptive_query import _load_schema
    from app.services.analyst_agent_sql import validate_agent_sql
    from app.services.four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
    from app.services.schema_intelligence_registry import get_schema_registry
    from app.services.semantic_requirements import enrich_semantic_with_requirements

    question = "top customers by billed sales"
    tables = [str(item.get("table") or "") for item in get_schema_registry().lightweight_table_catalog(include_operational=False) if item.get("table")]
    ctx = VerifiedDbContext(question=question, tables=tables, semantic_requirements=enrich_semantic_with_requirements(question))
    sql = pipeline3_sql_generation(question, ctx, templates_only=True)
    assert "LIMIT 10 *" not in sql
    safe, _sources = validate_agent_sql(sql, _load_schema())
    assert "LIMIT" in safe.upper()


def test_customers_in_germany_is_a_country_list_not_a_ranking():
    from app.services.four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
    from app.services.schema_intelligence_registry import get_schema_registry
    from app.services.semantic_requirements import enrich_semantic_with_requirements

    question = "list customers in Germany"
    tables = [str(item.get("table") or "") for item in get_schema_registry().lightweight_table_catalog(include_operational=False) if item.get("table")]
    ctx = VerifiedDbContext(question=question, tables=tables, semantic_requirements=enrich_semantic_with_requirements(question))
    sql = pipeline3_sql_generation(question, ctx, templates_only=True)
    assert "rank_within_currency" not in sql
    assert "'DE'" in sql


def test_mixed_currency_total_explains_why_invoices_cannot_open():
    from app.api.adaptive_query import _load_schema
    from app.services.analyst_drilldown import drilldown_note
    from app.services.four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
    from app.services.schema_intelligence_registry import get_schema_registry
    from app.services.semantic_requirements import enrich_semantic_with_requirements

    question = "total billed sales in 2001"
    tables = [str(item.get("table") or "") for item in get_schema_registry().lightweight_table_catalog(include_operational=False) if item.get("table")]
    ctx = VerifiedDbContext(question=question, tables=tables, semantic_requirements=enrich_semantic_with_requirements(question))
    sql = pipeline3_sql_generation(question, ctx, templates_only=True)
    schema = _load_schema()
    assert 'AS "currency"' in sql
    assert drilldown_note(sql, [{"total_sales": "10", "invoice_count": "2", "currency": "DEM"}], schema) is None
    mixed = 'SELECT SUM("netwr") AS "total_sales" FROM "VBRK" WHERE SUBSTRING("fkdat", 1, 4) = \'2001\''
    note = drilldown_note(mixed, [{"total_sales": "10"}], schema)
    assert "currenc" in note.lower()


def test_breakdowns_are_answered_without_a_model():
    from app.services.basic_sql_answer import prepare_basic_question
    from app.services.four_stage_db_pipeline import VerifiedDbContext, pipeline3_sql_generation
    from app.services.schema_intelligence_registry import get_schema_registry
    from app.services.semantic_requirements import enrich_semantic_with_requirements

    tables = [str(item.get("table") or "") for item in get_schema_registry().lightweight_table_catalog(include_operational=False) if item.get("table")]

    def sql_for(question):
        prepared = prepare_basic_question(question)
        ctx = VerifiedDbContext(question=prepared, tables=tables, semantic_requirements=enrich_semantic_with_requirements(prepared))
        return pipeline3_sql_generation(prepared, ctx, templates_only=True) or ""

    by_customer = sql_for("billed sales by customer in 2001")
    assert "customer_name" in by_customer and "2001" in by_customer and "currency" in by_customer
    assert "'DE'" in sql_for("billed sales for Germany in 2001")
    assert "NOT EXISTS" in sql_for("customers with no billing in 2001")
    assert "2001" in sql_for("how much did we bill in 2001")


def test_paid_provider_refuses_while_basic_blocks_credits(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_native_pipeline.llm_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")),
    )
    token = block_paid_models()
    try:
        with pytest.raises(RuntimeError, match="paid model"):
            analyze_json("system", "user")
    finally:
        restore_paid_models(token)


def test_short_followups_stay_on_the_previous_billing_question():
    previous = "total billed sales in 2001"
    assert continue_basic_question("compare it with year", previous) == "compare it with year"
    assert continue_basic_question("compare it with 2002", previous) == "compare total billed sales in 2001 and 2002"
    assert continue_basic_question("by quarter", previous) == "total billed sales in 2001 by quarter"
    assert continue_basic_question("what about 2002", previous) == "total billed sales in 2002"
    assert continue_basic_question("in DEM", previous) == "total billed sales in 2001 in DEM"
    assert continue_basic_question("for Germany", previous) == "total billed sales in 2001 for Germany"
    assert continue_basic_question("total billed sales in 2002", previous) == "total billed sales in 2002"
    assert continue_basic_question("how many sales orders by year", previous) == "how many sales orders by year"


def test_followup_about_which_customers_and_countries_keeps_previous_question():
    previous = "Compare sales orders and linked invoices by customer and country for 2000"
    assert continue_basic_question("Which customers and countries are they?", previous) == (
        "Compare sales orders and linked invoices by customer and country for 2000. "
        "Which customers and countries are they?"
    )


def test_comparison_preserves_checked_metric_filters_and_requires_explicit_year():
    previous = "top 5 customers by profit for Germany in USD in 2001"
    assert continue_basic_question("compare it with 2002", previous) == "compare top 5 customers by profit for Germany in USD in 2001 and 2002"
    result = run_basic_sql_answer("compare it with year", previous_question=previous,
        execute=lambda *_: pytest.fail("Ambiguous year must not execute SQL"),
        local_agent=lambda *_: pytest.fail("Ambiguous year needs no model"))
    assert result["answer_status"] == "CLARIFICATION" and result["llm_calls"] == 0


def test_products_for_identified_invoices_runs_without_model(monkeypatch):
    from app.services import adaptive_structured_sql as structured

    columns = {
        "VBRK": {"mandt", "vbeln", "fkdat", "waerk", "netwr"},
        "VBRP": {"mandt", "vbeln", "posnr", "matnr", "arktx", "netwr", "fkimg"},
        "MAKT": {"matnr", "maktx", "spras"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    monkeypatch.setattr(
        "app.services.analytical_sql_safety.column_names",
        lambda table: sorted(columns.get(str(table).upper(), set())),
    )
    monkeypatch.setattr(
        "app.data_catalog.physical.column_names",
        lambda table: sorted(columns.get(str(table).upper(), set())),
    )
    monkeypatch.setattr(
        "app.services.schema_intelligence_registry.get_schema_registry",
        lambda: type(
            "R",
            (),
            {"lightweight_table_catalog": lambda self, include_operational=False: [
                {"table": "VBRK"}, {"table": "VBRP"}, {"table": "MAKT"},
            ]},
        )(),
    )
    monkeypatch.setattr(
        "app.services.four_stage_db_pipeline.pipeline3_sql_generation",
        lambda *args, **kwargs: pytest.fail("Product drill-down must not fall through to templates"),
    )

    captured = {}

    def execute(sql, step=None):
        captured["sql"] = sql
        captured["step"] = step
        assert paid_models_blocked()
        assert step and step.get("basic_predefined_template") == "products_for_identified_invoices"
        return {
            "ok": True,
            "sql": sql,
            "source": "business",
            "rows": [
                {"billing_document": "90000001", "billing_item": "10", "material_id": "M1"},
                {"billing_document": "90000002", "billing_item": "10", "material_id": "M2"},
            ],
        }

    prior_rows = [
        {"billing_document": "90000001", "billed_amount": 100},
        {"billing_document": "90000002", "billed_amount": 80},
        {"billing_document": "90000003", "billed_amount": 60},
    ]
    result = run_basic_sql_answer(
        "for the three identified invoices show me the products sold",
        execute=execute,
        previous_question="top 3 billing documents by billed sales in 2001",
        previous_sql='SELECT vbeln AS billing_document FROM "VBRK" LIMIT 3',
        previous_rows=prior_rows,
        local_agent=lambda *_: pytest.fail("Product drill-down must not call Ollama"),
    )
    assert result["answer_status"] == "SUCCESS"
    assert result["llm_calls"] == 0
    assert result["meta"]["basic_predefined_template"] == "products_for_identified_invoices"
    assert "90000001" in captured["sql"] and "90000002" in captured["sql"] and "90000003" in captured["sql"]
    assert '"VBRP"' in captured["sql"]
    assert "material_id" in captured["sql"]
    assert 'i."vbeln" = h."vbeln"' in captured["sql"]
    assert "MAKT" not in captured["sql"]
    assert len(result["data"]) == 2


def test_products_for_identified_invoices_builder_scopes_prior_ids(monkeypatch):
    from app.services.adaptive_structured_sql import build_products_for_identified_invoices_sql
    from app.services import adaptive_structured_sql as structured
    from app.services.sql_structure import sql_structure_errors

    columns = {
        "VBRK": {"mandt", "vbeln", "waerk"},
        "VBRP": {"mandt", "vbeln", "posnr", "matnr", "netwr"},
        "MAKT": {"mandt", "matnr", "maktx", "spras"},
    }
    monkeypatch.setattr(structured, "has_table", lambda table: table.upper() in columns)
    monkeypatch.setattr(
        structured,
        "has_column",
        lambda table, column: column.lower() in columns.get(table.upper(), set()),
    )
    monkeypatch.setattr(structured, "resolve_table_name", lambda table: table.upper())
    monkeypatch.setattr(
        "app.services.analytical_sql_safety.column_names",
        lambda table: sorted(columns.get(str(table).upper(), set())),
    )
    monkeypatch.setattr(
        "app.data_catalog.physical.column_names",
        lambda table: sorted(columns.get(str(table).upper(), set())),
    )
    sql = build_products_for_identified_invoices_sql(
        "breakdown on product level for the same invoices",
        ["VBRK", "VBRP"],
        {"prior_result_rows": [{"billing_document": "A1"}, {"invoice_number": "B2"}]},
    )
    assert sql and "IN (" in sql and "A1" in sql and "B2" in sql
    assert 'i."mandt" = h."mandt" AND i."vbeln" = h."vbeln"' in sql
    # Product drill-down stays on VBRP/VBRK only — no MAKT language join.
    assert "MAKT" not in sql
    assert not sql_structure_errors(sql)
    assert build_products_for_identified_invoices_sql(
        "show products sold", ["VBRK", "VBRP"], {"prior_result_rows": [{"billing_document": "A1"}]}
    ) is None
