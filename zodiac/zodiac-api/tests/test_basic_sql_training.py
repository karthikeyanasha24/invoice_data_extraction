import pytest
from sqlalchemy import create_engine

from app.services.adaptive_trusted_scope import TrustedAiExecutionScope
from app.services.basic_sql_training import (
    answerability_issues, apply_training_filters, assert_training_restriction,
    check_query_scope, edit_example, list_examples, load_replay_example, record_run,
    save_run,
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


def test_training_blocks_unrestricted_fact_table_scans():
    selection = {"VBRK": [{"col": "vbeln", "type": "text"}, {"col": "fkdat", "type": "text"}, {"col": "netwr", "type": "text"}]}
    with pytest.raises(ValueError, match="Add a query restriction"):
        assert_training_restriction("SELECT vbeln, fkdat, netwr FROM VBRK", [], selection)
    assert_training_restriction(
        "SELECT vbeln FROM VBRK WHERE fkdat >= '20000101' AND fkdat < '20010101'",
        [],
        selection,
    )
    assert_training_restriction(
        "SELECT vbeln FROM VBRK",
        [{"table": "VBRK", "column": "vbeln", "operator": "include_value", "value": "0090000123"}],
        selection,
    )
    assert_training_restriction("SELECT vbeln FROM VBRK", [], selection, allow_unrestricted=True)
    assert_training_restriction(
        "SELECT customer_id FROM billing",
        [],
        {"billing": [{"col": "customer_id", "type": "text"}]},
    )


def test_sql_training_reports_the_parser_diagnostic_for_invalid_sql():
    with pytest.raises(ValueError, match=r"SQL syntax could not be parsed .*check PostgreSQL syntax"):
        check_query_scope("SELECT customer_id FROM billing WHERE (", SCHEMA)


def test_training_flags_incomplete_multi_year_sample_and_missing_dimensions():
    question = "Compare sales order and invoice value differences by customer and country between 2000 and 2004"
    sql = ('SELECT "VBAK"."audat" AS "order_date", "VBAK"."kunnr" AS "customer", '
           '"VBAK"."netwr" AS "order_value" FROM "VBAK" '
           'WHERE "VBAK"."audat" >= \'20000101\' AND "VBAK"."audat" < \'20050101\' '
           'ORDER BY "VBAK"."audat" LIMIT 200')
    rows = [{"order_date": "20000105", "customer": "C1", "order_value": 10}] * 200
    issues = answerability_issues(question, sql, rows)
    assert len(issues) == 3
    assert any("country column" in issue for issue in issues)
    assert any("no invoice table" in issue for issue in issues)
    assert any("LIMIT 200" in issue and "2000–2004" in issue for issue in issues)

    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=17, sap_access="full")
    run = record_run(engine, scope, "business", question, {}, sql,
                     {"ok": True, "rows": rows}, answer_issues=issues)
    with pytest.raises(PermissionError, match="successful SQL Training execution"):
        save_run(engine, scope, run, question)
    engine.dispose()


def test_training_rejects_sample_query_without_the_requested_year_filter():
    question = "Show major differences in sales order value and invoice by country and customer value for the 2000 year"
    sql = ('SELECT "VBAK"."vbeln" AS "vbeln", "VBAK"."kunnr" AS "kunnr", '
           '"VBAK"."audat" AS "audat", "VBAK"."netwr" AS "netwr" FROM "VBAK" LIMIT 10')
    issues = answerability_issues(question, sql, [{"audat": "19970107", "netwr": 100}])
    assert any("no matching date filter" in issue for issue in issues)
    assert any("returned dates are from 1997" in issue for issue in issues)
    assert any("no invoice table" in issue for issue in issues)
    assert any("country column" in issue for issue in issues)


def test_training_accepts_a_year_filter_that_matches_the_question():
    question = "Show sales for 2000"
    sql = ('SELECT "VBAK"."audat" AS "order_date", "VBAK"."netwr" AS "order_value" '
           'FROM "VBAK" WHERE "VBAK"."audat" >= \'20000101\' AND "VBAK"."audat" < \'20010101\'')
    assert answerability_issues(question, sql, [{"order_date": "20000107", "order_value": 100}]) == []


def test_training_accepts_year_breakdown_with_requested_dimensions():
    question = "Compare invoice value by customer and country between 2000 and 2004"
    sql = ('SELECT SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) AS "sales_year", '
           '"KNA1"."name1" AS "customer_name", "KNA1"."land1" AS "country", '
           'SUM("VBRK"."netwr") AS "invoice_value" FROM "VBRK" '
           'JOIN "KNA1" ON "VBRK"."kunag" = "KNA1"."kunnr" AND "VBRK"."mandt" = "KNA1"."mandt" '
           'WHERE "VBRK"."fkdat" >= \'20000101\' AND "VBRK"."fkdat" < \'20050101\' '
           'GROUP BY SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4), "KNA1"."name1", "KNA1"."land1" LIMIT 200')
    rows = [{"sales_year": year, "customer_name": "Acme", "country": "DE", "invoice_value": 10}
            for year in ("2000", "2001", "2002", "2003", "2004")]
    assert answerability_issues(question, sql, rows) == []


def test_picker_replay_is_bound_to_owner_scope_question_revision_and_configured_source():
    engine = create_engine("sqlite://")
    owner = TrustedAiExecutionScope(user_id=17, sap_access="full")
    other = TrustedAiExecutionScope(user_id=18, sap_access="full")
    question = "sales by customer"
    sql = "SELECT customer_id, net_value FROM billing"
    run = record_run(engine, owner, "business", question, SCHEMA, sql, {"ok": True, "rows": []})
    saved = save_run(engine, owner, run, question)
    example = load_replay_example(engine, owner, saved["id"], 1, question, True)
    assert example["sql"] == sql and example["training_example"] is True
    for scope in (other, None, TrustedAiExecutionScope(user_id=17, sap_access="none")):
        with pytest.raises(PermissionError):
            load_replay_example(engine, scope, saved["id"], 1, question, True)
    for revision, wording, use_sap in ((2, question, True), (True, question, True),
                                      (1, "sales in 2001", True), (1, question, False)):
        with pytest.raises(ValueError):
            load_replay_example(engine, owner, saved["id"], revision, wording, use_sap)
    edit_example(engine, owner, saved["id"], "SELECT customer_id FROM billing")
    with pytest.raises(ValueError, match="needs validation"):
        load_replay_example(engine, owner, saved["id"], 2, question, True)
    engine.dispose()


def test_legacy_mismatched_example_is_not_listed_as_replayable_or_loaded():
    engine = create_engine("sqlite://")
    owner = TrustedAiExecutionScope(user_id=29, sap_access="full")
    question = "Show major differences in sales order value and invoice by country and customer value for the 2000 year"
    sql = ('SELECT "VBAK"."vbeln" AS "vbeln", "VBAK"."kunnr" AS "kunnr", '
           '"VBAK"."audat" AS "audat", "VBAK"."netwr" AS "netwr" FROM "VBAK" LIMIT 10')
    run = record_run(engine, owner, "business", question, {}, sql,
                     {"ok": True, "rows": [{"audat": "19970107", "netwr": 100}]})
    saved = save_run(engine, owner, run, question)

    listed = list_examples(engine, owner)[0]
    assert listed["validation_status"] == "executed"  # Simulates a pre-guard saved record.
    assert listed["replayable"] is False
    issues = " ".join(listed["answerability_issues"])
    assert "no matching date filter" in issues
    assert "no invoice table" in issues and "no country column" in issues
    assert all(item.get("training_example_id") != saved["id"]
               for item in load_basic_examples(engine, owner, use_sap=True))
    with pytest.raises(ValueError, match="needs review and cannot run in Basic"):
        load_replay_example(engine, owner, saved["id"], 1, question, True)
    engine.dispose()


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
    question = "show sales by customer"
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


def test_basic_blocks_legacy_training_sql_that_does_not_answer_its_question():
    question = "Show major differences in sales order value and invoice by country and customer value for the 2000 year"
    sql = ('SELECT "VBAK"."vbeln" AS "vbeln", "VBAK"."kunnr" AS "kunnr", '
           '"VBAK"."audat" AS "audat", "VBAK"."netwr" AS "netwr" FROM "VBAK" LIMIT 10')
    example = {"question": question, "sql": sql, "source": "application", "training_example": True,
               "training_example_id": "legacy-example", "training_revision": 1, "reusable": True}

    def execute(statement, step=None):
        pytest.fail("Basic must reject this saved query before reading the database")

    def local_agent(*_args, **_kwargs):
        pytest.fail("An invalid saved training example must not fall back to a model")

    result = run_basic_sql_answer(question, execute=execute, selected_training_example=example,
                                  local_agent=local_agent)
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert "no matching date filter" in " ".join(result["meta"]["training_validation_issues"])
    assert "no country column" in " ".join(result["meta"]["training_validation_issues"])
    assert "no invoice table" in " ".join(result["meta"]["training_validation_issues"])
    assert result["sql_status"] == "needs_review"
    assert result["rowCount"] == 0
    assert result["llm_calls"] == 0


def test_basic_blocks_unscoped_multi_year_training_sql_before_database_read():
    question = "Compare sales order and invoice value by country and customer between 2000 and 2004"
    sql = ('SELECT "VBAK"."vbeln" AS "vbeln", "VBAK"."kunnr" AS "kunnr", '
           '"VBAK"."audat" AS "audat", "VBAK"."netwr" AS "netwr" FROM "VBAK" LIMIT 200')
    example = {"question": question, "sql": sql, "source": "application", "training_example": True,
               "training_example_id": "legacy-range-example", "training_revision": 1, "reusable": True}

    result = run_basic_sql_answer(
        question, selected_training_example=example,
        execute=lambda *_args, **_kwargs: pytest.fail("An unscoped date-range query must not execute"),
    )
    issues = " ".join(result["meta"]["training_validation_issues"])
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert "no matching date filter" in issues and "2000–2004" in issues
    assert "no country column" in issues and "no invoice table" in issues


def test_basic_blocks_training_result_whose_dates_contradict_the_question():
    question = "Show invoices for 2000"
    sql = ('SELECT "VBRK"."fkdat" AS "fkdat" FROM "VBRK" '
           'WHERE "VBRK"."fkdat" >= \'20000101\' AND "VBRK"."fkdat" < \'20010101\'')
    example = {"question": question, "sql": sql, "source": "application", "training_example": True,
               "training_example_id": "date-example", "training_revision": 1, "reusable": True}

    result = run_basic_sql_answer(
        question, selected_training_example=example,
        execute=lambda statement, step=None: {
            "ok": True, "sql": statement, "rows": [{"fkdat": "19970107"}], "source": "application",
        },
    )
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert "returned dates are from 1997" in " ".join(result["meta"]["training_validation_issues"])
    assert result["sql_status"] == "needs_review"


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


def test_basic_adapts_checked_full_year_date_bounds_for_another_year():
    saved = {
        "question": "Identify the difference in the sales amount for order value and invoice value from the year 1999",
        "sql": (
            'WITH "pairs" AS (SELECT "vbelv", "vbeln" FROM "VBFA") '
            'SELECT "o"."audat", "o"."netwr" - "b"."netwr" AS "difference_amount" '
            'FROM "pairs" AS "p" JOIN "VBAK" AS "o" ON "o"."vbeln" = "p"."vbelv" '
            'JOIN "VBRK" AS "b" ON "b"."vbeln" = "p"."vbeln" '
            'WHERE "o"."audat" >= \'19990101\' AND "o"."audat" < \'20000101\' '
            'AND "o"."waerk" = "b"."waerk" LIMIT 200'
        ),
        "source": "application", "training_example": True,
    }
    original_sql = saved["sql"]
    question = saved["question"].replace("1999", "2000")
    single = adapt_training_year_filter(question, [saved])
    assert single is not None
    assert "'20000101'" in single["sql"] and "'20010101'" in single["sql"]
    assert "'19990101'" not in single["sql"]
    assert single["training_year_adaptation"] == ["2000"]

    for first, last in (("2000", "2004"), ("1998", "2000")):
        ranged = adapt_training_year_filter(
            saved["question"].replace("the year 1999", f"the years between {first} and {last}"),
            [saved],
        )
        assert ranged is None  # The detail query's LIMIT can hide later years.

    assert saved["sql"] == original_sql
    assert adapt_training_year_filter(question + " by country", [saved]) is None
    assert adapt_training_year_filter(question.replace("2000", "2004 and 2000"), [saved]) is None
    assert adapt_training_year_filter(question, [{**saved, "sql": original_sql.replace("'20000101'", "'20000201'")}]) is None
    assert adapt_training_year_filter(question, [{**saved, "sql": original_sql.replace(" AND \"o\".\"audat\" <", " OR \"o\".\"audat\" <")}]) is None


def test_basic_expands_a_grouped_year_template_for_a_contiguous_range():
    saved = {
        "question": "show me the lowest sales for specific years in SAP ERP",
        "sql": 'SELECT SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) AS "salesyear", '
               'MIN("VBRK"."netwr") AS "lowestsale" FROM "VBRK" '
               'WHERE SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) IN (\'2024\', \'2025\') '
               'GROUP BY SUBSTRING("VBRK"."fkdat" FROM 1 FOR 4) LIMIT 20',
        "source": "application", "training_example": True,
    }
    for first, last in (("2000", "2004"), ("1998", "2000")):
        adapted = adapt_training_year_filter(
            f"show me the lowest sales between {first} and {last}", [saved])
        assert adapted is not None
        assert adapted["training_year_adaptation"] == [str(year) for year in range(int(first), int(last) + 1)]
        for year in adapted["training_year_adaptation"]:
            assert f"'{year}'" in adapted["sql"]


def test_basic_replays_changed_single_year_date_bounds_without_a_model():
    saved = {
        "question": "Identify the difference in the sales amount for order value and invoice value from the year 1999",
        "sql": 'SELECT "o"."audat" AS "order_date", "o"."netwr" - "b"."netwr" AS "difference_amount" '
               'FROM "VBAK" AS "o" JOIN "VBRK" AS "b" ON "o"."mandt" = "b"."mandt" AND "o"."vbeln" = "b"."vbeln" '
               'WHERE "o"."audat" >= \'19990101\' AND "o"."audat" < \'20000101\'',
        "source": "application", "training_example": True,
    }
    executed = []
    def execute(statement, step=None):
        executed.append((statement, step))
        return {"ok": True, "sql": statement, "rows": [{"order_date": "20000105", "difference_amount": 0}],
                "source": "application"}
    def local_agent(*_args, **_kwargs):
        pytest.fail("Changed-year Basic replay must not call a model")

    result = run_basic_sql_answer(saved["question"].replace("1999", "2000"),
                                  execute=execute, prior_examples=[saved], local_agent=local_agent)
    assert result["answer_status"] == "SUCCESS"
    assert result["llm_calls"] == 0
    assert executed[0][1]["training_example"] is True
    assert "'20000101'" in executed[0][0] and "'20010101'" in executed[0][0]


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


@pytest.mark.parametrize("approve_predefined", [False, True])
def test_basic_blocks_billing_line_extreme_when_pattern_uses_total_sales(monkeypatch, approve_predefined):
    from app.services import four_stage_db_pipeline
    sql = "SELECT industry, SUM(i.netwr) AS total_billed_sales FROM VBRP i GROUP BY industry"
    monkeypatch.setattr(four_stage_db_pipeline, "pipeline3_sql_generation", lambda *_args, **_kwargs: sql)
    executed = []

    def execute(statement, step=None):
        executed.append(statement)
        return {"ok": True, "sql": statement, "rows": [], "source": "business"}

    result = run_basic_sql_answer(
        "Show the lowest billing line amounts by industry in 1999",
        execute=execute,
        approve_predefined=approve_predefined,
    )
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert result["sql_status"] == "needs_review"
    assert "basic_pattern_confirmation" not in result["meta"]
    assert result["meta"]["basic_metric_validation_issues"]
    assert result["llm_calls"] == 0
    assert "No query was run" in result["answer"]
    assert executed == []
def test_profitability_synonym_does_not_accept_billed_sales_as_profit():
    billed_sales_sql = 'SELECT matnr, SUM(netwr) AS total_billed_sales FROM "VBRP" GROUP BY matnr'
    assert profit_question_without_profit_sql(
        "show me products with the best profitability for year 2000", [{"sql": billed_sales_sql}],
    )
