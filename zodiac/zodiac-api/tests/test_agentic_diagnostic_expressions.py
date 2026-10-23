"""Diagnostic calculations retain monetary currency and document-grain proofs."""
import pytest
from sqlalchemy import create_engine, text

from app.services.agent_query_contract import RelationshipCatalog, identified_value_proof


def diagnostic_sql(expression):
    schema = {t: [{'col': c, 'type': 'text'} for c in fields.split()] for t, fields in {
        'VBRK': 'mandt vbeln waerk', 'VBAK': 'mandt vbeln waerk',
        'VBRP': 'mandt vbeln posnr aubel aupos netwr fkimg vrkme',
        'VBAP': 'mandt vbeln posnr netwr kwmeng vrkme',
    }.items()}
    catalog = RelationshipCatalog(schema)
    catalog.keys = {t: [set('mandt vbeln posnr'.split() if t in {'VBRP', 'VBAP'} else 'mandt vbeln'.split())] for t in schema}
    catalog.add_edge('VBRK', 'VBRP', [('vbeln', 'vbeln')], 'test')
    catalog.add_edge('VBAK', 'VBAP', [('vbeln', 'vbeln')], 'test')
    catalog.add_edge('VBRP', 'VBAP', [('aubel', 'vbeln'), ('aupos', 'posnr')], 'test')
    sql = f'''SELECT i.mandt,i.vbeln,i.posnr,i.aubel,i.aupos,o.vbeln AS order_no,o.posnr AS order_item,
                     i.netwr AS invoice_net,o.netwr AS order_net,i.fkimg,o.kwmeng,
                     b.waerk AS invoice_currency,h.waerk AS order_currency,{expression} AS observation
              FROM VBRP i JOIN VBRK b ON b.mandt=i.mandt AND b.vbeln=i.vbeln
              LEFT JOIN VBAP o ON o.mandt=i.mandt AND o.vbeln=i.aubel AND o.posnr=i.aupos
              LEFT JOIN VBAK h ON h.mandt=o.mandt AND h.vbeln=o.vbeln'''
    return catalog, sql


MEASURES = [('VBRP', 'netwr'), ('VBAP', 'netwr'), ('VBRP', 'fkimg'), ('VBAP', 'kwmeng')]
GUARD = 'b.waerk=h.waerk AND i.vrkme=o.vrkme'
PRICE_DELTA = '(i.netwr/NULLIF(i.fkimg,0)-o.netwr/NULLIF(o.kwmeng,0))'


@pytest.mark.parametrize('expression', [
    'CASE WHEN i.vrkme=o.vrkme THEN i.fkimg-o.kwmeng END',
    f'CASE WHEN {GUARD} THEN i.fkimg*{PRICE_DELTA} END',
    f"CASE WHEN {GUARD} AND {PRICE_DELTA}=0 AND i.fkimg<o.kwmeng THEN 'Lower billed quantity; same net per unit' ELSE 'Insufficient evidence' END",
    f"CASE WHEN o.vbeln IS NULL THEN 'Missing order item' WHEN {GUARD} AND {PRICE_DELTA}=0 THEN 'Same net per unit' ELSE 'Insufficient evidence' END",
])
def test_guarded_item_diagnostics_pass_and_execute(expression):
    catalog, sql = diagnostic_sql(expression)
    assert identified_value_proof(sql, catalog, MEASURES, allow_currency_matched_difference=True) == (True, [])
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as db:
            db.execute(text('CREATE TABLE VBRK(mandt TEXT,vbeln TEXT,waerk TEXT)'))
            db.execute(text('CREATE TABLE VBAK(mandt TEXT,vbeln TEXT,waerk TEXT)'))
            db.execute(text('CREATE TABLE VBRP(mandt TEXT,vbeln TEXT,posnr TEXT,aubel TEXT,aupos TEXT,netwr NUMERIC,fkimg NUMERIC,vrkme TEXT)'))
            db.execute(text('CREATE TABLE VBAP(mandt TEXT,vbeln TEXT,posnr TEXT,netwr NUMERIC,kwmeng NUMERIC,vrkme TEXT)'))
            db.execute(text("INSERT INTO VBRK VALUES('999','I1','USD')"))
            db.execute(text("INSERT INTO VBAK VALUES('999','O1','USD')"))
            db.execute(text("INSERT INTO VBRP VALUES('999','I1','10','O1','10',100,5,'EA')"))
            db.execute(text("INSERT INTO VBAP VALUES('999','O1','10',200,10,'EA')"))
            row = db.execute(text(sql)).mappings().one()
            assert row['observation'] in (-5, 0, 'Lower billed quantity; same net per unit', 'Same net per unit')
            assert row['invoice_net'] == 100 and row['order_net'] == 200
    finally:
        engine.dispose()


@pytest.mark.parametrize('expression', [
    f'i.fkimg*{PRICE_DELTA}',
    f'CASE WHEN {GUARD} THEN i.netwr*o.netwr END',
    f'CASE WHEN {GUARD} THEN i.fkimg*{PRICE_DELTA} ELSE 0 END',
    f"CASE WHEN {PRICE_DELTA}=0 THEN 'Same price' ELSE 'Other' END",
    f"CASE WHEN (b.waerk=h.waerk OR i.vbeln='I1') AND {PRICE_DELTA}=0 THEN 'Same price' ELSE 'Other' END",
    f"CASE WHEN {GUARD} AND {PRICE_DELTA}=0 THEN 'Same price' WHEN {PRICE_DELTA}>0 THEN 'Higher price' ELSE 'Other' END",
])
def test_unguarded_money_diagnostics_remain_rejected(expression):
    catalog, sql = diagnostic_sql(expression)
    assert not identified_value_proof(sql, catalog, MEASURES, allow_currency_matched_difference=True)[0]


def test_diagnostic_still_requires_displayed_currencies_and_client_keys():
    expression = f"CASE WHEN {GUARD} AND {PRICE_DELTA}=0 THEN 'Same price' ELSE 'Other' END"
    catalog, sql = diagnostic_sql(expression)
    for unsafe in [sql.replace('b.waerk AS invoice_currency,h.waerk AS order_currency,', ''),
                   sql.replace('o.mandt=i.mandt AND ', '')]:
        assert not identified_value_proof(unsafe, catalog, MEASURES, allow_currency_matched_difference=True)[0]


def test_missing_item_diagnosis_requires_verified_unfiltered_null_target():
    from app.services.analyst_agent import _missing_order_item_gap
    _, sql = diagnostic_sql("'Evidence only'")
    evidence = {'sql': sql, 'identified_pair_listing': True,
                'rows': [{'aubel': 'SYNTH-O-1', 'aupos': '10', 'order_item': None}]}
    assert 'cannot be established' in _missing_order_item_gap(evidence)
    for bad in [
        {**evidence, 'identified_pair_listing': False},
        {**evidence, 'truncated': True},
        {**evidence, 'rows': []},
        {**evidence, 'rows': [{'aubel': 'SYNTH-O-1', 'aupos': '10', 'order_item': '10'}]},
        {**evidence, 'rows': [{'aubel': '', 'aupos': '10', 'order_item': None}]},
        {**evidence, 'rows': [{'aubel': 'SYNTH-O-1', 'aupos': '10'}]},
        {**evidence, 'sql': sql.replace('LEFT JOIN VBAP', 'JOIN VBAP')},
        {**evidence, 'sql': sql.replace('AND o.posnr=i.aupos', "AND o.posnr=i.aupos AND o.netwr<0")},
    ]:
        assert _missing_order_item_gap(bad) == ''
