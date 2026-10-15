import pytest
from sqlalchemy import create_engine

from app.services.adaptive_trusted_scope import TrustedAiExecutionScope
from app.services.basic_sql_training import (
    check_query_scope, edit_example, list_examples, record_run, save_run,
)


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
