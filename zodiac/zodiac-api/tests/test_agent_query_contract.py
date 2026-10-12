"""Numeric and structural oracles for cross-source plans; no live model calls."""
from copy import deepcopy
import json
from types import SimpleNamespace
import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.agent_query_contract import (
    RelationshipCatalog, identified_value_proof, output_lineage, plan_sql_issues,
    requested_sources, source_coverage_issues, validate_plan, failed_sql_signature,
)


def schema(**tables):
    return {t: [{'col': c, 'type': 'text'} for c in cols.split()] for t, cols in tables.items()}


SCHEMA = schema(VBRK='mandt vbeln netwr waerk fkdat', vbrp='mandt vbeln posnr aubel', VBAK='mandt vbeln netwr waerk')
QUESTION = 'For year 2000 compare billing documents with their linked sales orders and show both net values side by side, lowest billing net first'
SQL = '''WITH links AS (SELECT DISTINCT p.mandt,p.vbeln,p.aubel FROM vbrp p)
SELECT b.mandt AS client,b.vbeln AS billing_document,o.vbeln AS sales_order,l.aubel AS linked_order_reference,
CAST(b.netwr AS NUMERIC) AS billing_net_value,CAST(o.netwr AS NUMERIC) AS order_net_value,
b.waerk AS billing_currency,o.waerk AS order_currency
FROM "VBRK" b LEFT JOIN links l ON l.mandt=b.mandt AND l.vbeln=b.vbeln
LEFT JOIN "VBAK" o ON o.mandt=l.mandt AND o.vbeln=l.aubel
WHERE b.fkdat >= '20000101' AND b.fkdat < '20010101'
ORDER BY billing_net_value ASC LIMIT 20'''


def catalog():
    c = RelationshipCatalog(SCHEMA)
    c.keys = {'VBRK': [{'mandt','vbeln'}], 'VBAK': [{'mandt','vbeln'}], 'vbrp': [{'mandt','vbeln','posnr'}]}
    c.add_edge('VBRK', 'vbrp', [('vbeln', 'vbeln')], 'test relationship')
    c.add_edge('vbrp', 'VBAK', [('aubel','vbeln')], 'test originating-order relationship')
    return c


def plan():
    fields = [('VBRK','mandt','client','identifier'),('VBRK','vbeln','billing_document','identifier'),
              ('VBAK','vbeln','sales_order','identifier'),('VBRK','netwr','billing_net_value','measure'),
              ('VBAK','netwr','order_net_value','measure'),('VBRK','waerk','billing_currency','currency'),
              ('VBAK','waerk','order_currency','currency')]
    return dict(tables=['VBRK','VBAK'], fields=[dict(zip(['table','column','alias','role'], f)) for f in fields], strategy='identified_values',
                grain='one row per identified billing/order pair', filters=['billing year 2000'],
                sort=[{'alias':'billing_net_value','direction':'ASC'}],limit=20,
                missing_handling='retain bills with missing orders as null',assumptions=['header values are not allocated'])


def test_current_guard_rejects_valid_bridge_but_new_proof_establishes_pair_identity():
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    assert sql_has_unsafe_monetary_fanout(SQL)  # original defect, no guard bypass
    assert identified_value_proof(SQL, catalog()) == (True, [])
    p = validate_plan(plan(), QUESTION, catalog())
    assert len(p['relationships'][0]) == 2
    assert not plan_sql_issues(SQL, p)
    assert not source_coverage_issues(QUESTION, SQL, SCHEMA)


@pytest.mark.parametrize('bad', [
    SQL.replace('SELECT DISTINCT p.mandt,p.vbeln,p.aubel', 'SELECT p.mandt,p.vbeln,p.aubel'),
    SQL.replace('o.mandt=l.mandt AND ', ''),
    SQL.replace('o.vbeln=l.aubel', 'o.vbeln=b.vbeln'),
    SQL.replace('b.vbeln AS billing_document,', ''),
    SQL.replace('CAST(b.netwr AS NUMERIC)', 'SUM(CAST(b.netwr AS NUMERIC))'),
])
def test_duplicate_bridges_missing_composite_keys_wrong_document_ids_and_sums_fail(bad):
    ok, errors = identified_value_proof(bad, catalog())
    assert not ok and errors


def test_plan_cannot_ignore_orders_or_currency_and_result_cannot_ignore_order_values():
    p = plan()
    p['tables'] = ['VBRK']
    with pytest.raises(ValueError, match='omits'):
        validate_plan(p, QUESTION, catalog())
    p = plan()
    p['fields'] = [f for f in p['fields'] if f['alias'] != 'order_currency']
    with pytest.raises(ValueError, match='currency'):
        validate_plan(p, QUESTION, catalog())
    missing = 'SELECT b.vbeln,b.netwr FROM "VBRK" b'
    assert source_coverage_issues(QUESTION, missing, SCHEMA)
    assert source_coverage_issues(QUESTION, SQL.replace('CAST(o.netwr AS NUMERIC) AS order_net_value,',''), SCHEMA)


def test_numeric_oracle_duplicate_items_multi_order_multi_bill_client_currency_and_nulls():
    engine = create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,netwr TEXT,waerk TEXT,fkdat TEXT)'))
        c.execute(text('CREATE TABLE VBAK(mandt TEXT,vbeln TEXT,netwr TEXT,waerk TEXT)'))
        c.execute(text('CREATE TABLE vbrp(mandt TEXT,vbeln TEXT,posnr TEXT,aubel TEXT)'))
        c.execute(text("INSERT INTO VBRK VALUES ('800','B1','-5','DEM','20000101'),('800','B2','20','USD','20000701'),('800','B3','0','EUR','20000801'),('810','B1','8','DEM','20000101'),('800','OLD','999','USD','19990101')"))
        c.execute(text("INSERT INTO VBAK VALUES ('800','O1','100','DEM'),('800','O2','200','EUR'),('810','O1','300','DEM')"))
        c.execute(text("INSERT INTO vbrp VALUES ('800','B1','1','O1'),('800','B1','2','O1'),('800','B1','3','O2'),('800','B2','1','O1'),('810','B1','1','O1')"))
        rows = [dict(r) for r in c.execute(text(SQL)).mappings()]
    assert len(rows) == 5  # repeated B1/O1 item link removed, B1/O2 retained
    assert [(r['billing_net_value'],r['order_net_value']) for r in rows] == [(-5,100),(-5,200),(0,None),(8,300),(20,100)]
    assert rows[1]['billing_currency'] != rows[1]['order_currency']
    assert rows[2]['sales_order'] is None  # no invented zero order amount


def test_arbitrary_four_table_path_and_pair_proof_without_sap_names():
    s = schema(charges='tenant charge_id value currency', hops='tenant charge_id intermediate_id',
               route='tenant intermediate_id agreement_id', agreements='tenant agreement_id value currency')
    c = RelationshipCatalog(s)
    c.keys = {'charges':[{'tenant','charge_id'}], 'hops':[{'tenant','charge_id','intermediate_id'}],
              'route':[{'tenant','intermediate_id'}], 'agreements':[{'tenant','agreement_id'}]}
    c.add_edge('charges','hops',[('tenant','tenant'),('charge_id','charge_id')],'declared FK')
    c.add_edge('hops','route',[('tenant','tenant'),('intermediate_id','intermediate_id')],'declared FK')
    c.add_edge('route','agreements',[('tenant','tenant'),('agreement_id','agreement_id')],'declared FK')
    sql = '''WITH paths AS (SELECT DISTINCT h.tenant,h.charge_id,r.agreement_id FROM hops h
             JOIN route r ON r.tenant=h.tenant AND r.intermediate_id=h.intermediate_id)
             SELECT a.tenant,a.charge_id,z.agreement_id,a.value AS charge_value,z.value AS agreement_value,
             a.currency AS charge_currency,z.currency AS agreement_currency FROM charges a
             JOIN paths p ON p.tenant=a.tenant AND p.charge_id=a.charge_id
             JOIN agreements z ON z.tenant=p.tenant AND z.agreement_id=p.agreement_id'''
    assert len(c.paths(['charges','agreements'])[0]) == 3
    assert identified_value_proof(sql, c, [('charges','value'),('agreements','value')]) == (True, [])
    assert not identified_value_proof(sql.replace('z.tenant=p.tenant AND ', ''), c, [('charges','value'),('agreements','value')])[0]


def test_real_connected_uniqueness_probe_rejects_duplicate_and_null_keys(monkeypatch):
    from app.services.adaptive_trusted_scope import TrustedAiExecutionScope
    monkeypatch.setattr('app.services.analyst_agent_sql.get_trusted_scope',lambda:TrustedAiExecutionScope(user_id=1,sap_access='full'))
    engine = create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,netwr TEXT)'))
        c.execute(text("INSERT INTO VBRK VALUES ('800','B1','4'),('800','B1','5')"))
    with Session(engine) as session:
        c = RelationshipCatalog(schema(VBRK='mandt vbeln netwr'))
        c.inspect_keys(session, ['VBRK'])
        assert c.keys['VBRK'] == []


def test_alias_renames_are_not_meaningful_sql_repairs():
    renamed = re.sub(r'\bb\b', 'bill', SQL.replace('links','renamed'))
    assert failed_sql_signature(SQL) == failed_sql_signature(renamed)


def test_unmatched_bridge_reference_cannot_be_hidden_by_nullable_order_id():
    assert not identified_value_proof(SQL.replace('l.aubel AS linked_order_reference,',''), catalog())[0]


def test_followup_freezes_document_cohort_and_requeries_it_without_injection():
    from app.services.agent_query_contract import prior_cohort, constrain_cohort
    context = {'previousAnswerStatus':'SUCCESS','previousSQL':SQL,
               'data':[{'client':'800','billing_document':"B1' OR 1=1 --",'sales_order':'O1'}]}
    cohort = prior_cohort(context, 'Compare those with linked sales orders', catalog())
    assert cohort['table'] == 'VBRK'
    c = catalog()
    c.keys = dict(reversed(list(c.keys.items())))
    assert prior_cohort(context, 'Compare those with linked sales orders', c)['table'] == 'VBRK'
    constrained = constrain_cohort(SQL, cohort)
    assert "B1'' OR 1=1 --" in constrained
    assert prior_cohort(context, 'How many billing documents overall?', catalog()) is None


def test_self_contained_comparison_pronoun_does_not_inherit_older_customer():
    from app.services.analyst_agent import _scope_question
    question = 'For year 2000, identify billing documents with lowest net values and compare them with their linked sales orders'
    assert _scope_question(question,'Did Insurance Company have sales in 2004?') == question
    followup = _scope_question('Compare those with linked sales orders','Show lowest billing documents in 2000')
    assert '2000' in followup and 'linked sales orders' in followup


@pytest.mark.parametrize('sql,expected', [
 ('SELECT h.vbeln FROM VBRK h WHERE h.fkdat>=\'20000101\' AND h.fkdat<\'20010101\'',True),
 ('SELECT h.vbeln FROM VBRK h WHERE h.fkdat>=\'20000101\' OR h.fkdat<\'20010101\'',False),
 ('SELECT h.vbeln FROM VBRK h WHERE h.fkdat>=\'20000101\' AND h.other_date<\'20010101\'',False),
])
def test_calendar_year_half_open_bounds_need_same_field_and_conjunction(sql,expected):
    from app.services.plan_satisfaction import sql_has_calendar_year
    assert sql_has_calendar_year(sql,'2000') is expected


def test_actual_agent_loop_repairs_relationship_instead_of_accepting_billing_only(monkeypatch):
    from app.services import analyst_agent as agent
    from app.services.investigation_budget import end_investigation
    c = catalog()
    c.inspect_keys = lambda *_:None
    monkeypatch.setattr(agent.AnalystTools,'schema',lambda *_:(SCHEMA,'live_database_metadata'))
    monkeypatch.setattr(agent.AnalystTools,'catalog',lambda *_:c)
    question = 'Compare billing documents with linked sales orders for 2000, with both net values side by side'
    def tool(name,args,i):
        return SimpleNamespace(output=[dict(type='function_call',name=name,arguments=json.dumps(args),call_id=str(i))],output_text='')
    def final():
        return SimpleNamespace(output=[],output_text=json.dumps(dict(kind='analysis',answer='Billing and linked order values are shown separately.',summary='Document comparison',result_ids=['result_2'],followups=[])))
    responses=iter([tool('prepare_analysis',{'source':'business',**plan()},1),
        tool('run_readonly_sql',{'source':'business','sql':SQL.replace('o.vbeln=l.aubel','o.vbeln=b.vbeln'),'purpose':'Compare values'},2),
        tool('run_readonly_sql',{'source':'business','sql':SQL,'purpose':'Compare values using verified links'},3),final()])
    monkeypatch.setattr(agent,'create_agent_response',lambda **_:next(responses))
    executed=[]
    def execute(db,sql,hint):
        executed.append(sql)
        return [{'client':'800','billing_document':'B1','sales_order':'O1','linked_order_reference':'O1',
                 'billing_net_value':-5,'order_net_value':100,'billing_currency':'DEM','order_currency':'DEM'}]
    try:
        result=agent.run_analyst_agent(question,None,execute,schema_loader=lambda:SCHEMA)
        assert result['answer_status']=='SUCCESS'
        assert len(executed)==1 and 'aubel' in executed[0]
        assert result['query_plan']['analysis_requirements']['validated']
        assert any(t['status']=='error' for t in result['query_plan']['agent_trace'])
    finally:
        end_investigation()


def test_independent_aggregate_proof_is_schema_independent_and_rejects_resumming():
    s = schema(payments='tenant payment_id agreement_id amount currency', agreements='tenant agreement_id amount currency')
    c = RelationshipCatalog(s)
    c.keys = {'payments':[{'tenant','payment_id'}], 'agreements':[{'tenant','agreement_id'}]}
    c.add_edge('payments','agreements',[('tenant','tenant'),('agreement_id','agreement_id')],'declared foreign key')
    sql = '''WITH totals AS (SELECT p.tenant,p.agreement_id,p.currency,SUM(p.amount) AS paid
             FROM payments p GROUP BY p.tenant,p.agreement_id,p.currency)
             SELECT t.tenant,t.agreement_id,t.currency AS paid_currency,a.currency AS agreement_currency,
             t.paid,a.amount AS agreement_amount FROM totals t
             JOIN agreements a ON a.tenant=t.tenant AND a.agreement_id=t.agreement_id'''
    money = [('payments','amount'),('agreements','amount')]
    assert identified_value_proof(sql,c,money) == (True,[])
    wrong = sql.replace('t.paid,a.amount AS agreement_amount','SUM(t.paid) AS paid,SUM(a.amount) AS agreement_amount')
    assert not identified_value_proof(wrong,c,money)[0]
    raw = '''SELECT p.tenant,p.agreement_id,SUM(p.amount) AS paid,SUM(a.amount) AS agreement_amount
             FROM payments p JOIN agreements a ON a.tenant=p.tenant AND a.agreement_id=p.agreement_id
             GROUP BY p.tenant,p.agreement_id'''
    assert not identified_value_proof(raw,c,money)[0]
    hidden_grain = sql.replace('SELECT t.tenant,t.agreement_id,t.currency AS paid_currency,', 'SELECT DISTINCT t.tenant,t.agreement_id,')
    assert not identified_value_proof(hidden_grain,c,money)[0]


def test_repeated_failed_sql_alias_rename_is_blocked_without_another_execution(monkeypatch):
    from app.services import analyst_agent as agent
    c = catalog()
    c.inspect_keys = lambda *_:None
    monkeypatch.setattr(agent.AnalystTools,'schema',lambda *_:(SCHEMA,'live_database_metadata'))
    monkeypatch.setattr(agent.AnalystTools,'catalog',lambda *_:c)
    executed=[]
    tools=agent.AnalystTools(None,lambda *_:executed.append(True),lambda:SCHEMA,question=QUESTION)
    assert tools.call('prepare_analysis',{'source':'business',**plan()})['ok']
    wrong=SQL.replace('o.vbeln=l.aubel','o.vbeln=b.vbeln')
    first=tools.call('run_readonly_sql',{'source':'business','sql':wrong,'purpose':'comparison'})
    second=tools.call('run_readonly_sql',{'source':'business','sql':re.sub(r'\bb\b','bill',wrong),'purpose':'retry'})
    assert not first['ok'] and not second['ok']
    assert 'Equivalent failed SQL' in second['error']
    assert not executed


def test_missing_industry_is_disclosed_without_filling_invented_values(monkeypatch):
    from app.services import analyst_agent as agent
    s = schema(customer_stats='industry')
    monkeypatch.setattr(agent.AnalystTools,'schema',lambda *_:(s,'live_database_metadata'))
    tools=agent.AnalystTools(None,lambda *_:[{'industry':None},{'industry':'Manufacturing'}],lambda:s,question='List industry values')
    result=tools.call('run_readonly_sql',{'source':'business','sql':'SELECT c.industry FROM customer_stats c','purpose':'Read industry coverage'})
    assert result['ok'] and result['rows'][0]['industry'] is None
    assert '1 of 2 returned rows' in result['data_gaps'][0]
