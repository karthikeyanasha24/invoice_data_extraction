"""Exercise manual comparisons and saved Basic replay through the API handlers."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.adaptive_trusted_scope import (
    TrustedAiExecutionScope, reset_trusted_scope, set_trusted_scope,
)
from app.services.investigation_budget import current_budget, end_investigation


QUESTION = "Identify the difference in the sales amount for order value and invoice value from the year 1999"
SQL = (Path(__file__).resolve().parents[1] / "scripts/sql/sap_order_invoice_pairs.sql").read_text()
SCHEMA = {
    "VBAK": [{"col": c, "type": "text"} for c in "mandt vbeln bstnk audat netwr waerk".split()],
    "VBFA": [{"col": c, "type": "text"} for c in "mandt vbelv vbeln vbtyp_v vbtyp_n posnv".split()],
    "VBRK": [{"col": c, "type": "text"} for c in "mandt vbeln fkdat netwr waerk".split()],
    "VBKD": [{"col": c, "type": "text"} for c in "mandt vbeln posnr".split()],
}
USER = SimpleNamespace(id=1, is_admin=False, is_customer_user=False)


@pytest.fixture
def comparison_db(monkeypatch):
    from app.api import adaptive_query as api
    from app.services.analyst_agent import AnalystTools
    from app.services.analyst_agent_sql import enforce_agent_user_scope

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for table, columns in SCHEMA.items():
            conn.execute(text(f'CREATE TABLE "{table}" ({", ".join(c["col"] + " TEXT" for c in columns)})'))
        conn.execute(text("INSERT INTO VBAK VALUES "
            "('800','O1','PO1','19990101','1000','USD'),"
            "('800','O2','PO2','19991231','200','USD'),"
            "('800','O3','PO3','19990601','700','USD'),"
            "('800','O4','PO4','19990701',NULL,'USD'),"
            "('810','O1','OTHER-CLIENT','19990101','300','USD'),"
            "('800','OLD','OLD','19981231','500','USD'),"
            "('800','NEXT','NEXT','20000101','600','USD')"))
        conn.execute(text("INSERT INTO VBRK VALUES "
            "('800','B1','19990115','900','USD'),('800','B2','19990215','100','USD'),"
            "('800','B3','20000115','220','USD'),('800','B4','19990615','500','EUR'),"
            "('800','B5','19990715','','USD'),('810','B1','19990115','280','USD'),"
            "('800','OLD','19990101','450','USD'),('800','NEXT','20000115','550','USD')"))
        conn.execute(text("INSERT INTO VBFA VALUES "
            "('800','O1','B1','C','M','10'),('800','O1','B1','C','M','20'),"
            "('800','O1','B2','C','M','10'),('800','O2','B3','C','M','10'),"
            "('800','O3','B4','C','M','10'),('800','O4','B5','C','M','10'),"
            "('810','O1','B1','C','M','10'),('800','OLD','OLD','C','M','10'),"
            "('800','NEXT','NEXT','C','M','10')"))

    # SQLite adapts the DB boundary only. Keep the actual API, catalog,
    # connected key checks, selected-schema validation and grain proof.
    monkeypatch.setattr(AnalystTools, "schema", lambda *_: (SCHEMA, "live_database_metadata"))
    monkeypatch.setattr(api, "_load_schema", lambda: SCHEMA)
    monkeypatch.setattr(api, "USE_SAP_DB_FOR_AI", False)
    monkeypatch.setattr("app.core.workspace.context.list_assigned_customer_ids", lambda *_: [])
    monkeypatch.setattr("app.services.basic_hosted_provider.basic_llm_enabled", lambda: False)
    monkeypatch.setenv("BASIC_ALLOW_PAID_FALLBACK", "false")
    monkeypatch.setattr("app.services.basic_rag.save_verified_query", lambda *_: True)
    monkeypatch.setattr("app.services.basic_rag.capture_training_reference", lambda *_: None)
    monkeypatch.setattr("app.services.analyst_drilldown.capture_result", lambda *_: None)
    calls = []

    def execute(session, sql, _question=""):
        assert current_budget().diagnostics.get("agent_read_only") is True
        scoped_sql, parameters = enforce_agent_user_scope(sql, SCHEMA)
        calls.append(scoped_sql)
        return [dict(row) for row in session.execute(text(scoped_sql), parameters).mappings()]

    monkeypatch.setattr(api, "_execute_sql", execute)
    with Session(engine) as session:
        yield api, session, calls
    end_investigation()
    engine.dispose()


def run_training(api, db, sql=SQL):
    return api.basic_training_execute_endpoint({
        "source": "application", "question": QUESTION, "sql": sql,
        "selected_schema": {t: [c["col"] for c in cols] for t, cols in SCHEMA.items()},
    }, db=db, current_user=USER)


def run_basic(api, db):
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=USER.id, sap_access="full"))
    try:
        return api._post_query_adaptive_body(
            q=QUESTION, original_question=QUESTION, tableHint=None, contextData=None,
            overrideSql=None, threadId=None, investigationId=None, db=db,
            current_user=USER, analysis_mode="basic",
        )
    finally:
        reset_trusted_scope(token)
        end_investigation()


def test_manual_training_compares_real_values_without_duplicate_links_or_client_mix(comparison_db):
    api, db, calls = comparison_db
    result = run_training(api, db)
    assert result["status"] == "executed", result
    assert result["llm_calls"] == 0
    assert len(calls) == 1
    rows = result["rows"]
    assert [(r["client"], r["sales_order"], r["billing_document"], r["difference_amount"]) for r in rows] == [
        ("800", "O1", "B1", 100), ("800", "O1", "B2", 900),
        ("800", "O2", "B3", -20), ("800", "O4", "B5", None), ("810", "O1", "B1", 20),
    ]
    # This is an order-date cohort; its invoice may be dated in the next year.
    assert rows[2]["invoice_date"] == "20000115"
    assert all(r["order_currency"] == r["invoice_currency"] for r in rows)


@pytest.mark.parametrize("sql", [
    SQL.replace("SELECT DISTINCT f.mandt", "SELECT f.mandt"),
    SQL.replace("o.mandt = p.mandt AND ", ""),
    SQL.replace("AND o.waerk = b.waerk", ""),
    SQL.replace("o.waerk AS order_currency,", ""),
    SQL.replace("CAST(NULLIF(TRIM(CAST(o.netwr AS TEXT)), '') AS NUMERIC) AS order_net_value",
                "SUM(CAST(NULLIF(TRIM(CAST(o.netwr AS TEXT)), '') AS NUMERIC)) AS order_net_value"),
])
def test_manual_training_rejects_unsafe_comparisons_before_execution(comparison_db, sql):
    api, db, calls = comparison_db
    result = run_training(api, db, sql)
    assert result["status"] == "failed"
    assert calls == []
    assert "prepare_analysis" not in result["error"]


def test_basic_replays_saved_training_comparison_and_reads_updated_amounts(comparison_db):
    from app.services.basic_sql_training import save_run

    api, db, calls = comparison_db
    trained = run_training(api, db)
    assert trained["status"] == "executed", trained
    scope = TrustedAiExecutionScope(user_id=USER.id, sap_access="full")
    save_run(db.get_bind(), scope, trained["run_id"], QUESTION)
    db.execute(text("UPDATE VBRK SET netwr='850' WHERE mandt='800' AND vbeln='B1'"))
    db.commit()
    result = run_basic(api, db)
    assert result["answer_status"] == "SUCCESS", result.get("answer")
    assert result["llm_calls"] == 0
    assert len(calls) == 2
    assert result["data"][0]["difference_amount"] == 150
    assert result["meta"]["retrieval"]["reused"] is True


def test_basic_rechecks_saved_comparison_if_header_keys_become_nonunique(comparison_db):
    from app.services.basic_sql_training import save_run

    api, db, calls = comparison_db
    trained = run_training(api, db)
    assert trained["status"] == "executed", trained
    save_run(db.get_bind(), TrustedAiExecutionScope(user_id=USER.id, sap_access="full"),
             trained["run_id"], QUESTION)
    db.execute(text("INSERT INTO VBRK VALUES ('800','B1','19990115','850','USD')"))
    db.commit()
    result = run_basic(api, db)
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert result["data"] == []
    assert len(calls) == 1  # Never execute the now-unsafe saved comparison.


def test_nontraining_basic_query_still_requires_cross_source_planning(comparison_db, monkeypatch):
    api, db, calls = comparison_db
    monkeypatch.setattr("app.services.basic_rag.load_basic_examples", lambda *_: [
        {"question": QUESTION, "sql": SQL, "source": "application"},
    ])
    result = run_basic(api, db)
    assert result["answer_status"] == "CANNOT_ANSWER"
    assert "prepare_analysis" in result["answer"]
    assert calls == []
