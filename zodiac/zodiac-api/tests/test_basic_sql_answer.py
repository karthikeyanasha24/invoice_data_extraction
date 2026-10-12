"""Basic mode and greetings must not call a paid model."""
import pytest
from app.services.adaptive_analyst.llm_provider import analyze_json
from app.services.adaptive_nl_sql_hardening import is_greeting_or_chitchat
from app.services.basic_sql_answer import recall_saved_sql, run_basic_sql_answer
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
    saved = 'SELECT SUM(netwr) FROM "VBRK"'
    seen = {}

    def execute(sql):
        seen["sql"] = sql
        return {"ok": True, "sql": sql, "source": "business", "rows": [{"sum": "10"}]}

    result = run_basic_sql_answer(
        "Please show total billed sales",
        execute=execute,
        prior_examples=[{"question": "total billed sales", "sql": saved}],
    )
    assert seen["sql"] == saved
    assert result["llm_calls"] == 0
    assert "already asked" in result["answer"]


def test_close_wording_reuses_the_saved_query_without_a_model():
    saved = 'SELECT SUM(netwr) FROM "VBRK"'
    examples = [{"question": "total billed sales in 2001", "sql": saved}]
    assert recall_saved_sql("what were billed sales during 2001", examples) == saved
    assert recall_saved_sql("billed sales by customer in 2001", examples) == ""
    assert recall_saved_sql("billed sales for Germany in 2001", [{"question": "billed sales for France in 2001", "sql": saved}]) == ""
    assert recall_saved_sql("top 10 customers by billed sales", [{"question": "top 5 customers by billed sales", "sql": saved}]) == ""


def test_different_year_is_not_treated_as_the_same_question():
    saved = 'SELECT SUM(netwr) FROM "VBRK"'
    assert recall_saved_sql("billed sales in 2001", [{"question": "billed sales in 2002", "sql": saved}]) == ""
    assert recall_saved_sql("show billed sales in 2001", [{"question": "billed sales in 2001", "sql": saved}]) == saved


def test_total_billed_sales_uses_a_saved_pattern_without_a_model():
    seen = {}

    def execute(sql):
        seen["sql"] = sql
        return {"ok": True, "sql": sql, "source": "business", "rows": [{"total_sales": "1"}]}

    result = run_basic_sql_answer("total billed sales in 2001", execute=execute)
    assert "2001" in seen["sql"]
    assert "total_sales" in seen["sql"]
    assert result["llm_calls"] == 0
    assert result["meta"]["credits_used"] is False


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
    note = drilldown_note(sql, [{"total_sales": "10", "invoice_count": "2"}], _load_schema())
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
