import pytest
from sqlalchemy import create_engine

from app.services.adaptive_trusted_scope import TrustedAiExecutionScope
from app.services.basic_sql_training import (
    apply_training_filters, check_query_scope, edit_example, list_examples, record_run, save_run,
)
from app.services.basic_rag import adapt_training_year_filter, load_basic_examples
from app.services.basic_rag import profit_question_without_profit_sql
from app.services.basic_sql_answer import run_basic_sql_answer


SCHEMA = {"billing": [
    {"col": "customer_id", "type": "text"},
    {"col": "net_value", "type": "numeric"},
]}


def test_schema_scoped_read_only_sql_validation():
    check_query_scope("SELECT customer_id, SUM(net_value) FROM billing GROUP BY customer_id", SCHEMA)
    safe_star_sql = check_query_scope("SELECT * FROM billing", SCHEMA)
    assert "customer_id" in safe_star_sql and "net_value" in safe_star_sql
    with pytest.raises(ValueError):
        check_query_scope("SELECT secret FROM billing", SCHEMA)
    with pytest.raises(ValueError):
        check_query_scope("SELECT * FROM other_table", SCHEMA)
    with pytest.raises(ValueError):
        check_query_scope("DELETE FROM billing", SCHEMA)
    with pytest.raises(ValueError):
        check_query_scope("SELECT customer_id FROM billing; SELECT net_value FROM billing", SCHEMA)


def test_training_filters_apply_sap_include_exclude_ranges_and_comparisons():
    sql = "SELECT customer_id, net_value FROM billing"
    filters = [
        {"table": "billing", "column": "customer_id", "operator": "include_value", "value": "C1"},
        {"table": "billing", "column": "customer_id", "operator": "exclude_value", "value": "C9"},
        {"table": "billing", "column": "customer_id", "operator": "exclude_range", "value": "C8", "upper": "C9"},
        {"table": "billing", "column": "net_value", "operator": "greater_than", "value": "1,25"},
        {"table": "billing", "column": "net_value", "operator": "less_than", "value": "9,50"},
    ]
    result = apply_training_filters(sql, filters, SCHEMA)
    assert '"billing"."customer_id" = \'C1\'' in result
    assert '"billing"."customer_id" <> \'C9\'' in result
    assert 'NOT "billing"."customer_id" BETWEEN \'C8\' AND \'C9\'' in result
    assert 'CAST("billing"."net_value" AS DECIMAL) > 1.25' in result
    assert 'CAST("billing"."net_value" AS DECIMAL) < 9.5' in result
    assert "AND CAST(\"billing\".\"net_value\" AS DECIMAL) <" in result
    checked = check_query_scope(result, SCHEMA)
    assert "WHERE" in checked.upper()


def test_training_filter_includes_ranges_and_rejects_unselected_fields():
    filters = [{"table": "billing", "column": "net_value", "operator": "include_range", "value": "1", "upper": "5"}]
    result = apply_training_filters("SELECT net_value FROM billing", filters, SCHEMA)
    assert 'CAST("billing"."net_value" AS DECIMAL) BETWEEN 1 AND 5' in result
    with pytest.raises(ValueError, match="selected in the accessible schema"):
        apply_training_filters("SELECT customer_id FROM billing", [{"table": "billing", "column": "net_value", "operator": "include_value", "value": "3"}], {"billing": [{"col": "customer_id", "type": "text"}]})


def test_training_filters_support_sap_character_dates_and_native_date_ranges():
    schema = {"VBRK": [
        {"col": "fkdat", "type": "character varying"},
        {"col": "created_at", "type": "timestamp without time zone"},
        {"col": "valdt", "type": "text"},
        {"col": "wrbtr", "type": "text"},
    ]}
    result = apply_training_filters(
        'SELECT "fkdat", "created_at" FROM "VBRK"',
        [
            {"table": "VBRK", "column": "fkdat", "operator": "include_range", "value": "2000-01-01", "upper": "31.12.2001"},
            {"table": "VBRK", "column": "created_at", "operator": "exclude_range", "value": "2025-03-01", "upper": "2025-03-31"},
            {"table": "VBRK", "column": "valdt", "operator": "greater_than", "value": "2001-01-01"},
            {"table": "VBRK", "column": "wrbtr", "operator": "include_range", "value": "1,25", "upper": "9,50"},
        ], schema,
    )
    assert '"VBRK"."fkdat" BETWEEN \'20000101\' AND \'20011231\'' in result
    assert "AND NOT CAST(\"VBRK\".\"created_at\" AS DATE) BETWEEN '2025-03-01' AND '2025-03-31'" in result
    assert 'CAST("VBRK"."created_at" AS DATE)' in result
    assert '"VBRK"."valdt" > \'20010101\'' in result
    assert 'CAST("VBRK"."wrbtr" AS DECIMAL) BETWEEN 1.25 AND 9.5' in result


def test_training_filter_rejects_invalid_or_reversed_dates():
    schema = {"VBRK": [{"col": "fkdat", "type": "text"}]}
    with pytest.raises(ValueError, match="valid date"):
        apply_training_filters('SELECT "fkdat" FROM "VBRK"', [
            {"table": "VBRK", "column": "fkdat", "operator": "include_value", "value": "31.02.2001"},
        ], schema)
    with pytest.raises(ValueError, match="lower date"):
        apply_training_filters('SELECT "fkdat" FROM "VBRK"', [
            {"table": "VBRK", "column": "fkdat", "operator": "include_range", "value": "2001-12-31", "upper": "2000-01-01"},
        ], schema)


def test_training_examples_persist_with_revision_and_are_owner_scoped(tmp_path):
    path = tmp_path / "training.db"
    engine = create_engine(f"sqlite:///{path}")
    owner = TrustedAiExecutionScope(user_id=17, sap_access="full")
    other = TrustedAiExecutionScope(user_id=18, sap_access="full")
    run_id = record_run(engine, owner, "business", "sales by customer", SCHEMA,
                        "SELECT customer_id, SUM(net_value) FROM billing GROUP BY customer_id",
                        {"ok": True, "rows": [{"customer_id": "A", "sum": 4}]})
    saved = save_run(engine, owner, run_id, "sales by customer")
    assert saved["saved"] and saved["revision"] == 1
    assert len(list_examples(engine, owner)) == 1
    assert list_examples(engine, other) == []

    changed = edit_example(engine, owner, saved["id"], "SELECT customer_id FROM billing")
    assert changed["revision"] == 2 and changed["validation_status"] == "needs_validation"
    assert len(list_examples(engine, other)) == 0
    engine.dispose()

    cold_engine = create_engine(f"sqlite:///{path}")
    reopened = list_examples(cold_engine, owner)[0]
    assert reopened["revision"] == 2
    assert len(reopened["history"]) == 1
    assert reopened["schema"]["billing"][0]["col"] == "customer_id"
    cold_engine.dispose()


def test_save_requires_successful_run_and_exact_question():
    engine = create_engine("sqlite://")
    owner = TrustedAiExecutionScope(user_id=7, sap_access="full")
    run_id = record_run(engine, owner, "business", "sales in 2001", SCHEMA,
                        "SELECT customer_id FROM billing", {"ok": False, "rows": []})
    with pytest.raises(PermissionError):
        save_run(engine, owner, run_id, "sales in 2001")
    engine.dispose()


def test_saved_sql_training_example_is_reused_by_basic_without_model(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'basic-training-reuse.db'}")
    owner = TrustedAiExecutionScope(user_id=31, sap_access="full")
    question = "show the lowest sales between 2000 and 2001"
    sql = "SELECT customer_id, SUM(net_value) AS total_sales FROM billing GROUP BY customer_id ORDER BY total_sales ASC LIMIT 10"
    run_id = record_run(engine, owner, "business", question, SCHEMA, sql,
                        {"ok": True, "rows": [{"customer_id": "A", "total_sales": 2}]})
    saved = save_run(engine, owner, run_id, question)
    examples = load_basic_examples(engine, owner, use_sap=True)
    assert any(item.get("training_example_id") == saved["id"] for item in examples)

    calls = []
    def execute(statement, step=None):
        calls.append((statement, step))
        return {"ok": True, "sql": statement, "rows": [{"customer_id": "A", "total_sales": 2}], "source": "business"}

    def local_agent(*_args, **_kwargs):
        pytest.fail("Basic should reuse the saved SQL without calling Ollama")

    result = run_basic_sql_answer(question, execute=execute, prior_examples=examples, local_agent=local_agent)
    assert result["answer_status"] == "SUCCESS"
    assert result["sql"] == sql
    assert calls and calls[0][0] == sql
    assert calls[0][1]["training_example"] is True
    assert result["llm_calls"] == 0
    assert result["meta"]["retrieval"]["reused"] is True
    engine.dispose()


def test_basic_adapts_only_requested_years_in_a_generic_checked_template():
    saved_question = "show me the lowest sales for specific years in SAP ERP"
    sql = (
        'SELECT SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) AS "salesyear", '
        '"VBRK"."waerk" AS "currency", MIN(CAST("VBRK"."netwr" AS DECIMAL)) AS "lowestsale" '
        'FROM "VBRK" WHERE SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) IN (\'2024\', \'2025\', \'2026\') '
        'GROUP BY SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4), "VBRK"."waerk" ORDER BY "lowestsale" LIMIT 20'
    )
    example = {"question": saved_question, "sql": sql, "source": "business", "training_example": True}
    adapted = adapt_training_year_filter("show me the lowest sales for specific years 2000 and 2001", [example])
    assert adapted is not None
    assert "'2000'" in adapted["sql"] and "'2001'" in adapted["sql"]
    assert "'2024'" not in adapted["sql"] and adapted["training_year_adaptation"] == ["2000", "2001"]
    assert example["sql"] == sql  # Never mutate the stored checked SQL.
    assert adapt_training_year_filter("show me the lowest sales for Germany in 2000", [example]) is None
    assert adapt_training_year_filter("show me the highest profit in 2000", [example]) is None


def test_basic_executes_adapted_training_template_without_model():
    question = "show me the lowest sales for specific years 2000 and 2001"
    template = {
        "question": "show me the lowest sales for specific years in SAP ERP",
        "sql": 'SELECT SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) AS "salesyear", "VBRK"."waerk" AS "currency", '
               'MIN(CAST("VBRK"."netwr" AS DECIMAL)) AS "lowestsale" FROM "VBRK" '
               'WHERE SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) IN (\'2024\', \'2025\', \'2026\') '
               'GROUP BY SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4), "VBRK"."waerk" ORDER BY "lowestsale" LIMIT 20',
        "source": "business", "training_example": True,
    }
    calls = []
    def execute(statement, step=None):
        calls.append((statement, step))
        return {"ok": True, "sql": statement, "rows": [{"salesyear": "2000", "currency": "USD", "lowestsale": 1}], "source": "business"}
    def local_agent(*_args, **_kwargs):
        pytest.fail("Basic should adapt this checked year template without calling Ollama")

    result = run_basic_sql_answer(question, execute=execute, prior_examples=[template], local_agent=local_agent)
    assert result["answer_status"] == "SUCCESS"
    assert "'2000'" in result["sql"] and "'2001'" in result["sql"]
    assert "'2024'" not in result["sql"]
    assert calls[0][1]["training_example"] is True
    assert result["llm_calls"] == 0
    assert result["meta"]["retrieval"]["method"] == "training_year_filter"


def test_basic_discloses_builtin_pattern_and_waits_for_choice(monkeypatch):
    from app.services import four_stage_db_pipeline
    sql = "SELECT SUBSTRING(fkdat FROM 1 FOR 4) AS salesyear, SUM(netwr) AS total_billed_sales FROM VBRK GROUP BY SUBSTRING(fkdat FROM 1 FOR 4)"
    monkeypatch.setattr(four_stage_db_pipeline, "pipeline3_sql_generation", lambda *_args, **_kwargs: sql)
    executed = []
    def execute(statement, step=None):
        executed.append(statement)
        return {"ok": True, "sql": statement, "rows": [{"total_billed_sales": 5}], "source": "business"}

    question = "show me the lowest sales for the year 2001"
    pending = run_basic_sql_answer(question, execute=execute)
    assert pending["answer_status"] == "CLARIFICATION"
    assert "does not identify a lowest sale" in pending["meta"]["basic_pattern_confirmation"]["warning"]
    assert "total billed sales by year" in pending["meta"]["basic_pattern_confirmation"]["logic"]
    assert executed == []  # No misleading query runs before the user chooses.

    approved = run_basic_sql_answer(question, execute=execute, approve_predefined=True)
    assert approved["answer_status"] == "SUCCESS"
    assert executed == [sql]


def test_profitability_synonym_does_not_accept_billed_sales_as_profit():
    billed_sales_sql = 'SELECT matnr, SUM(netwr) AS total_billed_sales FROM "VBRP" GROUP BY matnr'
    assert profit_question_without_profit_sql(
        "show me products with the best profitability for year 2000", [{"sql": billed_sales_sql}],
    )
