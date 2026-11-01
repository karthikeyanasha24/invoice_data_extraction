"""Regressions from deployed-client failures; fixtures contain invented data."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import analyst_agent as agent, adaptive_structured_sql as templates
from app.services.analyst_invoice_diagnostics import invoice_item_evidence_sql
from app.services.analyst_line_metrics import billing_line_metric_issues
from app.services.basic_sql_training import answerability_issues, list_examples, load_replay_example, record_run, save_run
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope
from app.services.agent_query_contract import RelationshipCatalog, identified_value_proof


FIELDS = {
    "VBAK": "mandt vbeln kunnr audat netwr waerk",
    "VBRK": "mandt vbeln kunag fkdat netwr waerk fksto",
    "KNA1": "mandt kunnr land1 name1",
    "VBRP": "mandt vbeln posnr aubel aupos netwr fkimg vrkme",
    "VBAP": "mandt vbeln posnr netwr kwmeng vrkme netpr kpein",
}
SCHEMA = {t: [{"col": c, "type": "text"} for c in fields.split()] for t, fields in FIELDS.items()}


def comparison_template(monkeypatch):
    monkeypatch.setattr(templates, "has_table", lambda t: t.upper() in SCHEMA)
    monkeypatch.setattr(templates, "has_column", lambda t, c: c.lower() in FIELDS[t.upper()].split())
    monkeypatch.setattr(templates, "resolve_table_name", lambda t: t.upper())
    return templates.build_sales_order_invoice_customer_comparison_sql(
        "Compare sales order and invoice values by country and customer in 2000", list(SCHEMA))


def catalog():
    c = RelationshipCatalog(SCHEMA)
    c.keys = {t: [set("mandt vbeln posnr".split() if t in {"VBAP", "VBRP"}
                           else "mandt kunnr".split() if t == "KNA1" else "mandt vbeln".split())] for t in SCHEMA}
    c.master_tables.add("KNA1")
    for left, right, pairs in [
        ("VBAK", "KNA1", [("kunnr", "kunnr")]), ("VBRK", "KNA1", [("kunag", "kunnr")]),
        ("VBRP", "VBRK", [("vbeln", "vbeln")]), ("VBRP", "VBAK", [("aubel", "vbeln")]),
        ("VBRP", "VBAP", [("aubel", "vbeln"), ("aupos", "posnr")]),
        ("VBAP", "VBAK", [("vbeln", "vbeln")]),
    ]:
        c.add_edge(left, right, pairs, "synthetic verified relationship")
    return c


def test_comparison_template_has_a_postgresql_hash_join_and_preserves_grain(monkeypatch):
    from sqlglot import exp, parse_one
    sql = comparison_template(monkeypatch)
    join = next(j for j in parse_one(sql, read="postgres").find_all(exp.Join) if j.args.get("side") == "FULL")
    assert join.args["on"].find(exp.EQ) is not None
    assert identified_value_proof(sql, catalog(), allow_currency_matched_difference=True) == (True, [])
    assert not identified_value_proof(sql.replace('AND o."year" IS NOT DISTINCT FROM i."year"', ''), catalog(), allow_currency_matched_difference=True)[0]


def test_approved_template_failure_does_not_call_local_model(monkeypatch):
    from app.services.basic_sql_answer import run_basic_sql_answer
    sql = comparison_template(monkeypatch)
    monkeypatch.setattr("app.services.four_stage_db_pipeline.pipeline3_sql_generation", lambda *_a, **_k: sql)
    monkeypatch.setattr("app.services.schema_intelligence_registry.get_schema_registry", lambda: MagicMock(
        lightweight_table_catalog=lambda **_: [{"table": t} for t in SCHEMA]))
    local = MagicMock(side_effect=AssertionError("An approved deterministic pattern must not call a model"))
    result = run_basic_sql_answer("Compare sales order and invoice values by country and customer in 2000",
        execute=lambda *_: {"ok": False, "error": "Synthetic SQL failure"}, local_agent=local, approve_predefined=True)
    assert result["answer_status"] == "CANNOT_ANSWER" and result["llm_calls"] == 0
    assert result["meta"]["basic_predefined_template"] == "sales_order_invoice_customer_comparison"
    assert result["sql_status"] == "execution_failed"
    local.assert_not_called()


@pytest.mark.parametrize("predicate, accepted", [
    ("audat >= '20000101' AND audat < '20020101'", True),
    ("audat BETWEEN '20000101' AND '20011231'", True),
    ("audat >= '19990101' AND audat < '20020101'", False),
    ("audat >= '20000101' OR audat < '20020101'", False),
    ("audat >= '20000101' AND erdat < '20020101'", False),
])
def test_training_proves_the_actual_two_year_date_range(predicate, accepted):
    issues = answerability_issues("Sales order net values in 2000 and 2001", "SELECT audat,netwr FROM VBAK WHERE " + predicate, [])
    assert (not issues) is accepted


def test_training_rejects_a_result_with_both_matching_and_wrong_years():
    sql = "SELECT audat,netwr FROM VBAK WHERE audat LIKE '2000%'"
    assert answerability_issues("Sales in 2000", sql, [{"audat": "20000101"}, {"audat": "19970101"}])


@pytest.mark.parametrize('period', ['2000 to 2004', '2000–2004', 'between 2004 and 2000'])
def test_training_checks_every_year_in_an_inclusive_range(period):
    sql = "SELECT audat,netwr FROM VBAK WHERE audat >= '20000101' AND audat < '20050101'"
    assert not answerability_issues('Sales in ' + period, sql, [{'audat':'20020101'}])


def test_legacy_join_without_client_is_unavailable_before_replay():
    engine = create_engine("sqlite://")
    scope = TrustedAiExecutionScope(user_id=17, sap_access="full")
    question = "Show invoices and their sales order reference"
    sql = "SELECT b.vbeln,p.aubel FROM VBRK b JOIN VBRP p ON b.vbeln=p.vbeln"
    run = record_run(engine, scope, "application", question, {}, sql, {"ok": True, "rows": []})
    saved = save_run(engine, scope, run, question)
    listed = list_examples(engine, scope)[0]
    assert not listed["replayable"] and "MANDT" in " ".join(listed["answerability_issues"])
    with pytest.raises(ValueError, match="MANDT"):
        load_replay_example(engine, scope, saved["id"], 1, question, False)
    engine.dispose()


@pytest.mark.parametrize("sql, accepted", [
    ("SELECT MIN(i.netwr) AS lowest_line FROM VBRP i", True),
    ("WITH m AS (SELECT MIN(i.netwr) AS x FROM VBRP i) SELECT x FROM m", True),
    ("SELECT SUM(i.netwr) AS lowest_line FROM VBRP i", False),
    ("SELECT SUM(i.netwr) AS x FROM VBRP i HAVING MIN(i.netwr)>0", False),
    ("SELECT i.mandt,i.vbeln,i.posnr,i.netwr FROM VBRP i ORDER BY i.netwr LIMIT 10", True),
])
def test_lowest_billing_line_is_not_an_industry_sum(sql, accepted):
    assert (not billing_line_metric_issues("Lowest billing line amounts by industry in 1999", sql)) is accepted


def test_customer_aliases_resolve_the_shared_master_key():
    sql = '''WITH o AS (
      SELECT v.mandt AS client,v.waerk AS currency,k.kunnr AS customer,k.land1 AS country,
      SUBSTRING(v.audat,1,4) AS year,SUM(CAST(v.netwr AS NUMERIC)) AS amount
      FROM VBAK v JOIN KNA1 k ON k.mandt=v.mandt AND k.kunnr=v.kunnr
      GROUP BY v.mandt,v.waerk,k.kunnr,k.land1,SUBSTRING(v.audat,1,4)),
      b AS (SELECT v.mandt AS client,v.waerk AS currency,k.kunnr AS customer,k.land1 AS country,
      SUBSTRING(v.fkdat,1,4) AS year,SUM(CAST(v.netwr AS NUMERIC)) AS amount
      FROM VBRK v JOIN KNA1 k ON k.mandt=v.mandt AND k.kunnr=v.kunag
      GROUP BY v.mandt,v.waerk,k.kunnr,k.land1,SUBSTRING(v.fkdat,1,4))
      SELECT o.client,b.client,o.currency,b.currency,o.customer,b.customer,o.country,b.country,
      o.year,b.year,o.amount AS order_amount,b.amount AS invoice_amount FROM o FULL JOIN b
      ON o.client=b.client AND o.currency=b.currency AND o.customer=b.customer
      AND o.country=b.country AND o.year=b.year'''
    assert identified_value_proof(sql, catalog()) == (True, [])
    assert not identified_value_proof(sql.replace("o.country=b.country", "o.country=b.customer"), catalog())[0]


@pytest.mark.parametrize("question", [
    "For invoice SYNTH-I1 explain the main recorded cause of the amount difference",
    "For order SYNTH-O1 and invoice SYNTH-I1 investigate and state the supported cause",
])
def test_missing_order_item_completes_with_exact_evidence_and_no_model(monkeypatch, question):
    from app.services.investigation_budget import end_investigation
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for table, fields in FIELDS.items():
            conn.execute(text('CREATE TABLE "' + table + '" (' + ','.join(c + ' TEXT' for c in fields.split()) + ')'))
        conn.execute(text("INSERT INTO VBRK VALUES('999','SYNTH-I1','C1','20000101','100','USD','')"))
        conn.execute(text("INSERT INTO VBAK VALUES('999','SYNTH-O1','C1','20000101','200','USD')"))
        conn.execute(text("INSERT INTO VBRP VALUES('999','SYNTH-I1','10','SYNTH-O1','10','100','5','EA')"))
    monkeypatch.setattr(agent.AnalystTools, "schema", lambda *_: (SCHEMA, "live_database_metadata"))
    c = catalog()
    monkeypatch.setattr(c, "inspect_keys", lambda *_: None)
    monkeypatch.setattr(agent.AnalystTools, "catalog", lambda *_: c)
    provider = MagicMock(side_effect=AssertionError("Missing item evidence needs no model"))
    monkeypatch.setattr(agent, "create_agent_response", provider)
    try:
        with Session(engine) as db:
            result = agent.run_analyst_agent(question, db,
                lambda session, sql, *_: [dict(r) for r in session.execute(text(sql)).mappings()], schema_loader=lambda: SCHEMA)
        assert result["answer_status"].startswith("SUCCESS"), result
        assert result["llm_calls"] == 0 and result["meta"]["diagnostic_evidence_gap"]
        assert result["data"][0]["linked_order_reference"] == "SYNTH-O1"
        assert result["data"][0]["order_item"] is None
        assert "cannot be established" in result["answer"]
        provider.assert_not_called()
    finally:
        end_investigation()
        engine.dispose()


def test_invoice_probe_does_not_guess_a_document_or_use_incomplete_schema():
    assert invoice_item_evidence_sql("Why do invoice values differ in 2000?", SCHEMA) is None
    assert invoice_item_evidence_sql("Explain invoice I1 and invoice I2", SCHEMA) is None
    assert invoice_item_evidence_sql("Explain invoice I1", {"VBRK": SCHEMA["VBRK"]}) is None


@pytest.mark.parametrize('period, expected_years', [
    ('for the 2000 year', {'2000'}),
    ('between 2000 and 2004', {'2000','2002','2004'}),
    ('2000 to 2004', {'2000','2002','2004'}),
    ('2000–2004', {'2000','2002','2004'}),
    ('in 2000 and 2004', {'2000','2004'}),
])
def test_agentic_checked_customer_comparison_runs_real_sql_without_a_model(monkeypatch, period, expected_years):
    from sqlglot import transpile
    from app.services.investigation_budget import end_investigation
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.connection.driver_connection.create_function('LPAD', 3, lambda s,n,p: str(s).rjust(n,p))
        for table, fields in FIELDS.items():
            conn.execute(text('CREATE TABLE "' + table + '" (' + ','.join(c + ' TEXT' for c in fields.split()) + ')'))
        conn.execute(text("INSERT INTO KNA1 VALUES('999','C1','AA','Invented customer')"))
        for year in ['1997','2000','2002','2004']:
            conn.execute(text("INSERT INTO VBAK VALUES('999',:doc,'C1',:date,'200','USD')"),dict(doc='O'+year,date=year+'0101'))
            conn.execute(text("INSERT INTO VBRK VALUES('999',:doc,'C1',:date,'100','USD','')"),dict(doc='I'+year,date=year+'0101'))
    monkeypatch.setattr(agent.AnalystTools,'schema',lambda *_:(SCHEMA,'live_database_metadata'))
    c = catalog()
    monkeypatch.setattr(c,'inspect_keys',lambda *_:None)
    monkeypatch.setattr(agent.AnalystTools,'catalog',lambda *_:c)
    provider = MagicMock(side_effect=AssertionError('The checked comparison needs no model'))
    monkeypatch.setattr(agent,'create_agent_response',provider)
    try:
        with Session(engine) as db:
            result = agent.run_analyst_agent('Show major differences in sales order value and invoice by country and customer value '+period,db,
                lambda session,sql,*_: [dict(r) for r in session.execute(text(transpile(sql,read='postgres',write='sqlite')[0])).mappings()],
                schema_loader=lambda:SCHEMA)
        assert result['answer_status'].startswith('SUCCESS'), result
        assert result['llm_calls'] == 0 and result['meta']['checked_customer_comparison']
        assert {r['year'] for r in result['data']} == expected_years
        assert all(r['order_minus_invoice_net_value'] == 100 for r in result['data'])
        assert 'document pair' not in result['answer']
        provider.assert_not_called()
    finally:
        end_investigation()
        engine.dispose()


@pytest.mark.parametrize('extra', ['in USD','for customer 000001','where country is US','top 5','excluding cancelled orders','and explain the cause','in $','with industry names','for country IN','for customer Sales'])
def test_checked_comparison_never_discards_extra_constraints(extra):
    from app.services.analyst_customer_comparison import customer_comparison_sql
    question = 'Compare sales order and invoice values by country and customer in 2000 ' + extra
    assert customer_comparison_sql(question,SCHEMA) is None


def test_checked_comparison_does_not_merge_source_specific_periods():
    from app.services.analyst_customer_comparison import customer_comparison_sql
    assert customer_comparison_sql('Compare sales order values in 2000 versus invoice values in 2004 by country and customer',SCHEMA) is None
    assert customer_comparison_sql('Compare sales order and invoice values by country and customer between 2000 and 2004 and 2007',SCHEMA) is None
    assert customer_comparison_sql('Compare sales order and invoice values by country IN and customer in 2000',SCHEMA) is None
    assert customer_comparison_sql('Compare sales order and invoice values by country and customer Sales in 2000',SCHEMA) is None
