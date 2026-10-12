"""Independent numeric/security contracts for the 12 October reliability work."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import json
import pytest
from sqlalchemy import create_engine, text
from app.services.analyst_drilldown import compile_selection, page_sql, reconcile, store_artifact, load_artifact, select_row, frozen_page, list_sql
from app.services.analyst_agent_sql import enforce_agent_user_scope, validate_agent_sql
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope, analyst_scope_for_user, set_trusted_scope, reset_trusted_scope
from app.services.analyst_filters import filter_issues
from app.services.analyst_evidence import grounded_answer
from app.services.analyst_usage import record_response, usage_summary, model_limits, AnalystResourceLimit
from app.services.investigation_budget import begin_investigation, end_investigation
from app.services.agent_query_contract import RelationshipCatalog

SCHEMA = {'VBRK':[{'col':c,'type':'text'} for c in ['mandt','vbeln','kunag','waerk','netwr','fkdat']],
    'vbrp':[{'col':c,'type':'text'} for c in ['mandt','vbeln','posnr','netwr','waerk']]}
SQL = '''SELECT b.mandt AS client,b.kunag AS customer,b.waerk AS currency,SUM(CAST(b.netwr AS NUMERIC)) AS billed_sales
    FROM "VBRK" b WHERE b.fkdat>='20010101' AND b.fkdat<'20020101'
    GROUP BY b.mandt,b.kunag,b.waerk ORDER BY billed_sales DESC LIMIT 200'''
ROW = {'client':'800','customer':'C1','currency':'USD','billed_sales':'4630639.01'}


@pytest.fixture(autouse=True)
def cleanup_budget():
    yield
    end_investigation('completed')


def test_document_contributors_preserve_year_customer_client_currency_and_exact_total():
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,kunag TEXT,waerk TEXT,netwr TEXT,fkdat TEXT)'))
        db.execute(text("INSERT INTO VBRK VALUES ('800','B1','C1','USD','4630639.02','20010601'),('800','B2','C1','USD','-0.01','20010801'),('800','B3','C1','EUR','999','20010101'),('800','B4','C2','USD','999','20010101'),('810','B5','C1','USD','999','20010101'),('800','B6','C1','USD','999','20000101')"))
        selection = compile_selection(SQL,ROW,'billed_sales',SCHEMA)
        rows = db.execute(text(selection['details_sql'])).mappings().all()
    assert {r['billing_document'] for r in rows}=={'B1','B2'}
    # Independent Decimal oracle avoids SQLite's floating point SUM behavior.
    oracle = Decimal('4630639.02')+Decimal('-0.01')
    page = [dict(r,total_documents=2,reconciled_total=str(oracle),currency_count=1,snapshot_digest='v1') for r in rows]
    result = reconcile(selection,page,50)
    assert result['reconciliation']['difference']=='0.00'
    assert result['llm_calls']==0
    assert result['answer_status']=='SUCCESS'


def test_cte_ranking_selection_uses_original_aggregate_not_a_new_ranking():
    base = SQL.split(' ORDER BY')[0]
    sql = f'WITH totals AS ({base}), ranked AS (SELECT t.*,ROW_NUMBER() OVER (PARTITION BY currency ORDER BY billed_sales DESC) AS rank FROM totals t) SELECT r.client,r.customer,r.currency,r.billed_sales FROM ranked r WHERE r.rank<=10'
    selected = compile_selection(sql,ROW,'billed_sales',SCHEMA)
    assert '20010101' in selected['details_sql'] and "'C1'" in selected['details_sql']
    validate_agent_sql(page_sql(selected),SCHEMA)


def test_reconciliation_mismatch_and_changed_pages_are_never_success():
    selected = compile_selection(SQL,ROW,'billed_sales',SCHEMA)
    rows = [{'total_documents':1,'reconciled_total':'1','currency_count':1,'snapshot_digest':'new',
        'sap_client':'800','billing_document':'B1','currency':'USD','billed_sales':'1'}]
    assert reconcile(selected,rows,50)['answer_status']=='RECONCILIATION_MISMATCH'
    with pytest.raises(ValueError,match='changed'):
        reconcile(selected,rows,50,'old')
    with pytest.raises(ValueError,match='cursor'):
        page_sql(selected,['bad'])


def test_result_artifacts_are_owner_bound_permission_bound_and_immutable():
    engine=create_engine('sqlite://')
    owner=TrustedAiExecutionScope(user_id=1,sap_access='full')
    identifier=store_artifact(engine,owner,{'rows':[ROW]})
    assert load_artifact(engine,owner,identifier)['rows']==[ROW]
    for other in [TrustedAiExecutionScope(user_id=2,sap_access='full'),TrustedAiExecutionScope(user_id=1,sap_access='none')]:
        with pytest.raises(PermissionError):
            load_artifact(engine,other,identifier)


def test_ambiguous_typed_followups_cannot_choose_an_amount_alone():
    artifact={'rows':[dict(ROW,year='2001'),dict(ROW,year='2001',currency='EUR')],'measures':['billed_sales']}
    assert select_row(artifact,'Show related billing documents for 2001')=='ambiguous'
    assert select_row(artifact,'Show related billing documents for 2001 USD')==(0,'billed_sales')


def test_year_split_total_lists_only_contributing_invoices_for_that_currency():
    """Year-over-year totals keep the year inside the amount, not as its own column."""
    engine = create_engine('sqlite://')
    sql = '''SELECT b.mandt AS client, b.waerk AS currency,
        SUM(CASE WHEN SUBSTRING(b.fkdat,1,4)='2000' THEN CAST(b.netwr AS NUMERIC) ELSE 0 END) AS sales_2000,
        SUM(CASE WHEN SUBSTRING(b.fkdat,1,4)='2001' THEN CAST(b.netwr AS NUMERIC) ELSE 0 END) AS sales_2001
        FROM "VBRK" b GROUP BY b.mandt, b.waerk'''
    displayed = {'client':'800','currency':'DEM','sales_2000':'100.00','sales_2001':'4630839.02'}
    with engine.begin() as db:
        db.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,kunag TEXT,waerk TEXT,netwr TEXT,fkdat TEXT)'))
        db.execute(text("""INSERT INTO VBRK VALUES
            ('800','B2001','C1','DEM','4630839.02','20010601'),
            ('800','B2000','C1','DEM','100.00','20000101'),
            ('800','BEUR','C1','EUR','999','20010101'),
            ('810','BOTHER','C1','DEM','50','20010101')"""))
        selection = compile_selection(sql, displayed, 'sales_2001', SCHEMA)
        from sqlglot import parse_one
        sqlite_sql = parse_one(selection['details_sql'], read='postgres').sql(dialect='sqlite')
        rows = db.execute(text(sqlite_sql)).mappings().all()
    assert {r['billing_document'] for r in rows} == {'B2001'}
    artifact = {'rows':[displayed, {'client':'800','currency':'EUR','sales_2000':'0','sales_2001':'999'}],
        'measures':['sales_2000','sales_2001']}
    assert select_row(artifact, 'Show the related billing documents for the year 2001') == 'ambiguous'
    assert select_row(artifact, 'Show the related billing documents for the year 2001 DEM') == (0, 'sales_2001')
    assert select_row(artifact, 'Show the invoices for 2001') == 'ambiguous'
    assert select_row(artifact, 'Show the invoices for 2001 DEM') == (0, 'sales_2001')
    assert select_row(artifact, 'Show invoices for customer Insurance Company in 2001') is None


def _run(sql, displayed, measure):
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,kunag TEXT,waerk TEXT,netwr TEXT,fkdat TEXT)'))
        db.execute(text("""INSERT INTO VBRK VALUES
            ('800','B2001','C1','DEM','4630839.02','20010601'),
            ('800','B2000','C1','DEM','100.00','20000101'),
            ('800','BEUR','C1','EUR','999','20010101'),
            ('810','BOTHER','C1','DEM','50','20010101')"""))
        selection = compile_selection(sql, displayed, measure, SCHEMA)
        from sqlglot import parse_one
        sqlite_sql = parse_one(selection['details_sql'], read='postgres').sql(dialect='sqlite')
        rows = db.execute(text(sqlite_sql)).mappings().all()
    return selection, rows


def test_subquery_total_opens_only_the_selected_year_and_currency():
    sql = '''SELECT s.client, s.year, s.currency, SUM(s.netwr) AS billed_sales
        FROM (SELECT b.mandt AS client, SUBSTRING(b.fkdat,1,4) AS year, b.waerk AS currency, CAST(b.netwr AS NUMERIC) AS netwr
        FROM "VBRK" b) s GROUP BY 1,2,3'''
    displayed = {'client':'800','year':'2001','currency':'DEM','billed_sales':'4630839.02'}
    _, rows = _run(sql, displayed, 'billed_sales')
    assert {r['billing_document'] for r in rows} == {'B2001'}


def test_change_amount_keeps_both_years_with_opposite_signs():
    sql = '''SELECT b.mandt AS client, b.waerk AS currency,
        SUM(CASE WHEN SUBSTRING(b.fkdat,1,4)='2001' THEN CAST(b.netwr AS NUMERIC) ELSE 0 END)
        - SUM(CASE WHEN SUBSTRING(b.fkdat,1,4)='2000' THEN CAST(b.netwr AS NUMERIC) ELSE 0 END) AS change_amount
        FROM "VBRK" b GROUP BY 1,2'''
    displayed = {'client':'800','currency':'DEM','change_amount':'4630739.02'}
    selection, rows = _run(sql, displayed, 'change_amount')
    assert {r['billing_document'] for r in rows} == {'B2001','B2000'}
    assert sum(Decimal(str(r['billed_sales'])) for r in rows) == Decimal(selection['expected_total'])


def test_saved_document_pages_do_not_reread_the_database():
    documents = [{'sap_client':'800','billing_document':f'{i:04d}','currency':'DEM','billed_sales':'1.00'} for i in range(3)]
    selection = {'expected_total':'3.00','details_sql':'SELECT 1','measure':'billed_sales'}
    first = frozen_page(selection, documents, 2, frozen_at='2026-10-12T00:00:00+00:00', source_executed_at='2026-10-12T00:00:00+00:00')
    second = frozen_page(selection, documents, 2, first['next_cursor'], '2026-10-12T00:00:00+00:00', '2026-10-12T00:00:00+00:00')
    assert first['reconciliation']['frozen'] is True
    assert first['reconciliation']['document_total'] == second['reconciliation']['document_total'] == '3.00'
    assert [r['billing_document'] for r in first['data']+second['data']] == ['0000','0001','0002']
    selection = compile_selection(SQL, ROW, 'billed_sales', SCHEMA)
    validate_agent_sql(list_sql(selection), SCHEMA, max_rows=5000)


def test_model_sql_stays_capped_while_a_document_list_can_read_the_cohort():
    sql = 'SELECT b.vbeln FROM "VBRK" b LIMIT 5000'
    capped, _ = validate_agent_sql(sql, SCHEMA)
    opened, _ = validate_agent_sql(sql, SCHEMA, max_rows=5000)
    assert '201' in capped and '5000' in opened


@pytest.mark.parametrize('sql',[
    'SELECT b.vbeln FROM "VBRK" b WHERE 1=1 OR b.kunag=\'C2\'',
    'WITH x AS (SELECT * FROM "VBRK") SELECT vbeln FROM x UNION ALL SELECT vbeln FROM "VBRK"',
    'SELECT p.vbeln FROM vbrp p JOIN "VBRK" b ON b.vbeln=p.vbeln AND b.mandt=p.mandt',
])
def test_restricted_customers_cannot_escape_physical_source_scope(sql):
    engine=create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,kunag TEXT,waerk TEXT,netwr TEXT,fkdat TEXT)'))
        db.execute(text('CREATE TABLE vbrp(mandt TEXT,vbeln TEXT,posnr TEXT,netwr TEXT,waerk TEXT)'))
        db.execute(text("INSERT INTO VBRK VALUES ('800','B1','C1','USD','1','20010101'),('800','B2','C2','USD','2','20010101'),('810','B3','C1','USD','3','20010101')"))
        db.execute(text("INSERT INTO vbrp VALUES ('800','B1','1','1','USD'),('800','B2','1','2','USD')"))
        token=set_trusted_scope(TrustedAiExecutionScope(user_id=1,sap_access='limited',allowed_sap_pairs=[{'client':'800','customer':'C1'}]))
        try:
            scoped,parameters=enforce_agent_user_scope(sql,SCHEMA)
        finally:
            reset_trusted_scope(token)
        from sqlglot import parse_one
        sqlite_sql = parse_one(scoped,read='postgres').sql(dialect='sqlite')
        assert {r[0] for r in db.execute(text(sqlite_sql),parameters)}=={'B1'}


def test_customer_mapping_is_explicit_and_empty_lookup_denies(monkeypatch):
    user=SimpleNamespace(id=1,is_admin=False,is_customer_user=True)
    monkeypatch.setenv('AI_ANALYST_SAP_CUSTOMER_MAP',json.dumps({'portal-tax-id':[{'client':'800','customer':'C1'}]}))
    assert analyst_scope_for_user(user,[]).sap_access=='none'
    assert analyst_scope_for_user(user,['unknown']).sap_access=='none'
    assert analyst_scope_for_user(user,['portal-tax-id']).allowed_sap_pairs==[{'client':'800','customer':'C1'}]
    token=set_trusted_scope(analyst_scope_for_user(user,[]))
    try:
        with pytest.raises(PermissionError):
            enforce_agent_user_scope('SELECT * FROM "VBRK"',SCHEMA)
    finally:
        reset_trusted_scope(token)


def test_typed_filter_must_be_conjunctive_and_match_source_value():
    filters=[{'table':'VBRK','column':'waerk','operator':'eq','values':['USD']}]
    assert filter_issues('SELECT b.vbeln FROM "VBRK" b',filters)
    assert filter_issues('SELECT b.vbeln FROM "VBRK" b WHERE b.waerk=\'USD\' OR 1=1',filters)
    assert not filter_issues('SELECT b.vbeln FROM "VBRK" b WHERE b.waerk=\'USD\' AND b.mandt=\'800\'',filters)


def test_alternative_paths_are_not_silently_selected():
    schema={t:[{'col':'id','type':'text'},{'col':'parent','type':'text'}] for t in ['a','b']}
    catalog=RelationshipCatalog(schema)
    catalog.add_edge('a','b',[('id','id')],'one role')
    catalog.add_edge('a','b',[('parent','id')],'different role')
    with pytest.raises(ValueError,match='Ambiguous'):
        catalog.paths(['a','b'])


def test_grounded_answer_retains_value_entity_pairs():
    answer=grounded_answer([{'rows':[{'customer':'A','sales':'100.00'},{'customer':'B','sales':'200.00'}]}])
    assert '**customer:** A • **sales:** 100.00' in answer
    assert '**customer:** B • **sales:** 200.00' in answer


def test_actual_usage_accounts_cached_and_reasoning_without_double_counting(monkeypatch):
    begin_investigation('test')
    monkeypatch.setenv('AI_ANALYST_PRICING_JSON',json.dumps({'unit-model':{'version':'test','input':2,'output':8,'cached_input':1}}))
    response=SimpleNamespace(usage={'input_tokens':1000,'output_tokens':200,'total_tokens':1200,
        'input_tokens_details':{'cached_tokens':100},'output_tokens_details':{'reasoning_tokens':50}},model='unit-model')
    record_response(response,'unit-model',10)
    usage=usage_summary()
    assert usage['total_tokens']==1200 and usage['reasoning_tokens']==50
    assert Decimal(usage['estimated_cost_usd'])==Decimal('0.0035')
    monkeypatch.setenv('AI_ANALYST_MAX_TOTAL_TOKENS','1200')
    with pytest.raises(AnalystResourceLimit):
        model_limits([])
