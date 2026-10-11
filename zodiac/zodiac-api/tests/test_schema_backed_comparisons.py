import sqlite3
import pytest
from app.services.schema_backed_comparisons import build_schema_backed_comparison
from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
from app.services.document_identity_quality import document_identity_errors


def fixture_db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE EKPO(mandt TEXT, ebeln TEXT, ebelp TEXT, matnr TEXT, netwr TEXT, loekz TEXT);
    CREATE TABLE EKKO(mandt TEXT, ebeln TEXT, lifnr TEXT, waers TEXT, bedat TEXT, loekz TEXT);
    CREATE TABLE LFA1(mandt TEXT, lifnr TEXT, name1 TEXT);
    CREATE TABLE MBEW(mandt TEXT, matnr TEXT, bwkey TEXT, bwtar TEXT, lbkum TEXT);
    CREATE TABLE MARA(mandt TEXT, matnr TEXT, meins TEXT);
    CREATE TABLE vbrp(mandt TEXT, vbeln TEXT, posnr TEXT, matnr TEXT, meins TEXT, fklmg TEXT, netwr TEXT);
    CREATE TABLE VBRK(mandt TEXT, vbeln TEXT, waerk TEXT, fkdat TEXT);
    INSERT INTO EKKO VALUES
      ('001','P1','A','EUR','20040101',''), ('001','P1','A','EUR','20040101',''),
      ('001','P2','B','EUR','20040101',''), ('001','P3','A','USD','20050101',''),
      ('001','P4','B','USD','20050101',''), ('001','PD','C','EUR','20040101','L');
    INSERT INTO EKPO VALUES
      ('001','P1','10','M1','10',''), ('001','P1','10','M1','10',''),
      ('001','P1','20','M2','20',''), ('001','P2','10','M1','20',''),
      ('001','P3','10','M1','5',''), ('001','P4','10','M1','5',''),
      ('001','PD','10','M1','100',''), ('001','P1','30','M1','200','L');
    INSERT INTO LFA1 VALUES ('001','A','Supplier A'), ('001','A','Supplier A'), ('001','B','Supplier B');
    INSERT INTO MBEW VALUES
      ('001','M1','W1','','10'), ('001','M1','W1','','10'),
      ('001','M1','W1','X','4'), ('001','M1','W2','','5'),
      ('001','M2','W1','','9'), ('002','M1','W1','','100');
    INSERT INTO MARA VALUES ('001','M1','EA'), ('001','M1','EA'), ('001','M2','EA'), ('002','M1','EA');
    INSERT INTO VBRK VALUES ('001','B1','EUR','20040101'), ('001','B1','EUR','20040101'),
      ('001','B2','USD','20050101'), ('001','B3','EUR','20040101'), ('002','B1','EUR','20040101');
    INSERT INTO vbrp VALUES ('001','B1','10','M1','EA','2','20'), ('001','B1','10','M1','EA','2','20'),
      ('001','B2','10','M1','EA','3','30'), ('001','B3','10','M3','EA','4','40'), ('002','B1','10','M1','EA','50','500');
    ''')
    return db


def run(question):
    plan = build_schema_backed_comparison(question)
    assert plan is not None
    db = fixture_db()
    try:
        return plan, [dict(row) for row in db.execute(plan.sql)]
    finally:
        db.close()


def test_supplier_share_uses_complete_currency_denominator_before_top_n():
    plan, rows = run('Show top 1 suppliers by purchase share.')
    assert len(rows) == 2
    shares = {row['currency']: row['share_of_po_value_pct'] for row in rows}
    assert shares == {'EUR': 60, 'USD': 50}
    assert all(row['supplier'] == 'A' for row in rows)
    assert not sql_has_unsafe_monetary_fanout(plan.sql)


def test_supplier_share_keeps_year_and_currency_filters():
    _, rows = run('Show supplier concentration in 2004 in EUR.')
    assert len(rows) == 2
    assert all(row['currency'] == 'EUR' for row in rows)
    assert sum(row['purchase_value'] for row in rows) == 50
    assert sum(row['share_of_po_value_pct'] for row in rows) == 100


def test_inventory_uses_same_base_units_without_fanout_or_mixed_currencies():
    plan, rows = run('Show inventory versus sales.')
    matched = [row for row in rows if row['client'] == '001' and row['product'] == 'M1']
    assert len(matched) == 2
    assert all(row['stock_qty'] == 15 and row['base_unit'] == 'EA' for row in matched)
    assert {row['currency']: (row['billed_qty'], row['total_sales']) for row in matched} == {'EUR': (2, 20), 'USD': (3, 30)}
    other_client = next(row for row in rows if row['client'] == '002')
    assert other_client['stock_qty'] == 100 and other_client['billed_qty'] == 50
    assert not sql_has_unsafe_monetary_fanout(plan.sql)


def test_inventory_missing_side_is_not_fabricated_as_zero():
    _, rows = run('Show inventory versus sales.')
    stock_only = next(row for row in rows if row['product'] == 'M2')
    sales_only = next(row for row in rows if row['product'] == 'M3')
    assert stock_only['billed_qty'] is None and stock_only['stock_qty'] == 9
    assert sales_only['stock_qty'] is None and sales_only['billed_qty'] == 4


def test_inventory_period_filters_only_billing_not_the_snapshot():
    _, rows = run('Compare inventory with sales in 2004.')
    matched = [row for row in rows if row['client'] == '001' and row['product'] == 'M1']
    assert len(matched) == 1 and matched[0]['stock_qty'] == 15
    assert matched[0]['currency'] == 'EUR' and matched[0]['billed_qty'] == 2


@pytest.mark.parametrize('question', [
    'Show supplier concentration for customer Acme.',
    'Show supplier concentration excluding vendor A.',
    'Compare those products with inventory.',
    'Show inventory value versus sales.',
    'Show inventory versus sales by plant.',
    'Show supplier concentration last year.',
])
def test_constraints_requiring_extra_planning_are_never_discarded(question):
    assert build_schema_backed_comparison(question) is None


def test_absent_base_quantity_column_does_not_guess_a_unit_conversion(monkeypatch):
    from app.services import schema_backed_comparisons as module
    real_has_column = module.has_column
    monkeypatch.setattr(module, 'has_column', lambda table, column: False if column == 'fklmg' else real_has_column(table, column))
    assert build_schema_backed_comparison('Show inventory versus sales.') is None


def test_duplicate_identity_guard_recognizes_complete_key_deduplication():
    plan = build_schema_backed_comparison('Show inventory versus sales.')
    profiles = {'vbrp': {'verified':True, 'keys':['mandt','vbeln','posnr'], 'duplicate_identity_groups':1,'conflicting_identity_groups':0}}
    assert document_identity_errors(plan.sql, profiles) == []
    profiles['vbrp']['conflicting_identity_groups'] = 1
    assert any('conflicting' in error for error in document_identity_errors(plan.sql, profiles))


def test_date_prefix_is_a_verified_year_filter():
    from app.services.plan_satisfaction import sql_has_calendar_year, sql_satisfies_analytical_intent
    for question in ['Show supplier concentration in 2004 in EUR.', 'Compare inventory with sales in 2004.']:
        plan = build_schema_backed_comparison(question)
        assert sql_has_calendar_year(plan.sql, '2004')
        assert sql_satisfies_analytical_intent(plan.sql, question)
    assert not sql_has_calendar_year("SELECT '2004%' AS label FROM events", '2004')
    assert not sql_has_calendar_year("SELECT * FROM events WHERE customer_id LIKE '2004%'", '2004')


def test_stock_comparison_cannot_be_replaced_with_a_sales_only_total():
    from app.services.plan_satisfaction import result_matches_analytical_intent, sql_satisfies_analytical_intent
    sql = "SELECT '2004' AS year, SUM(netwr) AS total_sales FROM VBRK"
    question = 'Compare inventory with sales in 2004.'
    assert not sql_satisfies_analytical_intent(sql, question)
    warnings = result_matches_analytical_intent([{'year':'2004','total_sales':10}], question, sql=sql)
    assert any('stock measure' in error for error in warnings)


def test_qualifying_a_table_without_joining_it_is_rejected():
    from app.services.sql_structure import sql_structure_errors
    assert any('not bound' in error for error in sql_structure_errors('SELECT EKKO.bedat FROM EKPO'))
    assert not sql_structure_errors('SELECT p.netwr FROM EKPO p WHERE EXISTS (SELECT 1 FROM EKKO h WHERE h.ebeln = p.ebeln)')


def test_monthly_charts_keep_every_period_and_stock_axes_do_not_mix_money():
    from app.api.adaptive_query import _auto_charts
    rows = [{'month': f'{2000 + n // 12}{n % 12 + 1:02}', 'currency':'EUR','total_sales':n} for n in range(70)]
    charts = _auto_charts('Show monthly revenue.', '', rows)
    assert len(charts[0]['data']) == 70
    stock = [{'client':'001','product':'M1','base_unit':'EA','currency':'EUR','stock_qty':15,'billed_qty':2,'total_sales':20}]
    charts = _auto_charts('Show inventory versus sales.', '', stock)
    assert charts[0]['y_keys'] == ['stock_qty','billed_qty']
    assert charts[0]['data'][0]['product_unit'] == 'M1 (EA)'


def test_common_execution_sanitizers_keep_comparison_date_filter_in_its_scope():
    from app.services.sql_generation_sanitizers import sanitize_generated_sap_sql
    from app.services.sap_sql_agent import _quote_catalog_sql_tables
    from app.services.sql_structure import sql_structure_errors
    question = 'Compare inventory with sales in 2004.'
    plan = build_schema_backed_comparison(question)
    sanitized = _quote_catalog_sql_tables(sanitize_generated_sap_sql(plan.sql, question))
    assert not sql_structure_errors(sanitized, question), sanitized


def test_missing_billing_date_filter_is_injected_in_the_header_scope():
    from app.services.sql_generation_sanitizers import inject_fkdat_calendar_year_filter
    from app.services.sql_structure import sql_structure_errors
    question = 'Compare inventory with sales in 2004.'
    plan = build_schema_backed_comparison('Show inventory versus sales.')
    fixed, notes = inject_fkdat_calendar_year_filter(plan.sql, question)
    assert notes
    assert not sql_structure_errors(fixed, question)
    db = fixture_db()
    try:
        from sqlglot import transpile
        sqlite_sql = transpile(fixed, read='postgres', write='sqlite')[0]
        rows = [dict(row) for row in db.execute(sqlite_sql)]
    finally:
        db.close()
    assert all(row['currency'] != 'USD' for row in rows)
    assert next(row for row in rows if row['client']=='001' and row['product']=='M1')['stock_qty'] == 15


def test_unverified_identity_probe_cannot_be_reported_as_a_verified_comparison():
    from unittest.mock import MagicMock
    from app.services.four_stage_db_pipeline import VerifiedDbContext, _validate_sql_against_context
    plan = build_schema_backed_comparison('Show inventory versus sales.')
    context = VerifiedDbContext(question='Show inventory versus sales.', tables=list(plan.columns))
    context.pipeline_log['schema_backed_comparison'] = {'intent':plan.intent}
    context.semantic_requirements['document_identity_profiles'] = {'vbrp':{'verified':False}}
    assert any('could not be verified' in error for error in _validate_sql_against_context(plan.sql, context, MagicMock()))
