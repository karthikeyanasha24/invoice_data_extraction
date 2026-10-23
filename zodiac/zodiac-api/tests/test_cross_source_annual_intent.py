"""Full question-to-SQL/result gates for cross-source annual comparisons."""
import pytest
from app.services.analytical_operations import extract_analytical_operations
from app.services.semantic_requirements import required_semantics, enrich_semantic_with_requirements
from app.services.analyst_agent import _analysis_issues
from test_agent_query_contract import ANNUAL_SQL

QUESTION = 'Identify the difference in the sales amount for order value and invoice value from the year 2000 and 2001.'
SQL = ANNUAL_SQL.replace('o.amount AS order_value,b.amount AS invoice_value',
    'o.amount AS order_value,b.amount AS invoice_value, CASE WHEN o.currency=b.currency THEN o.amount-b.amount ELSE NULL END AS value_difference')
ROWS = [dict(order_client='800',invoice_client='800',order_currency='DEM',invoice_currency='DEM',
             order_year=y,invoice_year=y,order_value=o,invoice_value=i,value_difference=o-i)
        for y,o,i in [('2000',150,50),('2001',90,70)]]


def test_exact_customer_question_passes_sql_and_final_result_gates():
    req = required_semantics(QUESTION)
    assert req['period_compare'] is None and req['growth'] is False
    assert req['date_filter'] == {'type':'calendar_years','years':['2000','2001']}
    assert not _analysis_issues(QUESTION,dict(sql=SQL,rows=ROWS,coverage_issues=[]))
    sem = enrich_semantic_with_requirements(QUESTION)
    assert sem['time_filter']['type'] == 'calendar_years'
    assert not required_semantics(QUESTION,sem)['period_compare']


def test_model_inferred_growth_cannot_override_source_value_comparison():
    req = required_semantics(QUESTION,{'period_compare': {'base_period':{'year':'2000'},'comparison_period':{'year':'2001'}}})
    assert req['period_compare'] is None


@pytest.mark.parametrize('question', [
    'Compare year-over-year growth in order value and invoice value from 2000 to 2001.',
    'Compare 2000 and 2001 sales orders and invoices and show the percentage change.',
    'Show invoice sales growth in 2000 versus 2001.',
])
def test_explicit_period_changes_keep_their_two_period_contract(question):
    assert required_semantics(question)['period_compare']


@pytest.mark.parametrize('bad', [
    SQL.replace("o.audat < '20020101'", "o.audat < '20010101'"),
    SQL.replace("b.fkdat < '20020101'", "b.fkdat < '20030101'"),
    SQL.replace("b.fkdat >= '20000101' AND b.fkdat < '20020101'", '1=1'),
])
def test_final_gate_rejects_missing_or_wrong_year_scope_on_either_fact(bad):
    assert _analysis_issues(QUESTION,dict(sql=bad,rows=ROWS,coverage_issues=[]))


def test_side_by_side_values_cannot_replace_requested_difference():
    assert any('difference' in s for s in _analysis_issues(QUESTION,dict(sql=ANNUAL_SQL,rows=ROWS,coverage_issues=[])))


def test_missing_executed_sql_is_a_validation_failure_not_an_exception():
    assert _analysis_issues(QUESTION,dict(sql='',rows=ROWS,coverage_issues=[]))


def test_real_agent_tool_loop_prepares_executes_and_returns_the_annual_comparison(monkeypatch):
    """Script only model choices; use real planning, SQL proof, DB and final gates."""
    import json
    from types import SimpleNamespace
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import Session
    from sqlglot import transpile
    from app.services import analyst_agent as agent
    from app.services.adaptive_trusted_scope import TrustedAiExecutionScope,set_trusted_scope,reset_trusted_scope
    from test_agent_query_contract import annual_catalog
    import httpx
    monkeypatch.setattr(httpx.Client,'send',lambda *_a,**_k: pytest.fail('No external model calls'))
    schema = annual_catalog().schema
    monkeypatch.setattr('app.services.adaptive_analyst.live_schema.load_live_schema', lambda *_: (schema,'live_database_metadata'))
    fields = [('VBAK','mandt','order_client','identifier'),('VBRK','mandt','invoice_client','identifier'),
              ('VBAK','waerk','order_currency','currency'),('VBRK','waerk','invoice_currency','currency'),
              ('VBAK','audat','order_year','date'),('VBRK','fkdat','invoice_year','date'),
              ('VBAK','netwr','order_value','measure'),('VBRK','netwr','invoice_value','measure')]
    plan = dict(source='business',tables=['VBAK','VBRK'],strategy='independent_aggregates',grain='year/client/currency',
                fields=[dict(zip(['table','column','alias','role'],f)) for f in fields],sort=[],limit=200,
                filters=[dict(table=t,column=d,operator='year',values=['2000','2001']) for t,d in [('VBAK','audat'),('VBRK','fkdat')]],
                missing_handling='Retain unmatched dimensions as null',assumptions=['Independent annual populations'])
    decisions = iter([('prepare_analysis',plan),('run_readonly_sql',dict(source='business',sql=SQL,purpose='Compare annual totals'))])
    def respond(**_kwargs):
        name,args = next(decisions)
        return SimpleNamespace(output=[dict(type='function_call',call_id=name,name=name,arguments=json.dumps(args))],output_text='')
    monkeypatch.setattr(agent,'create_agent_response',respond)
    engine = create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE VBAK(mandt TEXT,vbeln TEXT,netwr TEXT,waerk TEXT,audat TEXT)'))
        c.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,netwr TEXT,waerk TEXT,fkdat TEXT)'))
        c.execute(text("INSERT INTO VBAK VALUES ('800','O1','150','DEM','20000101'),('800','O2','90','DEM','20010101')"))
        c.execute(text("INSERT INTO VBRK VALUES ('800','I1','50','DEM','20000101'),('800','I2','70','DEM','20010101')"))
    def execute(session,sql,_purpose):
        return [dict(row) for row in session.execute(text(transpile(sql,read='postgres',write='sqlite')[0])).mappings()]
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=1,sap_access='full'))
    try:
        with Session(engine) as session:
            result = agent.run_analyst_agent(QUESTION,session,execute,schema_loader=lambda:schema)
    finally:
        reset_trusted_scope(token)
    assert result['answer_status'] == 'SUCCESS', result['answer']
    assert [r['value_difference'] for r in result['data']] == [100,20]
    assert all(t['status'] == 'completed' for t in result['query_plan']['agent_trace'])
