from unittest.mock import MagicMock
import pytest
from app.services.adaptive_analyst.live_schema import load_live_schema
from app.services.adaptive_structured_sql import build_document_total_count_sql


def test_live_metadata_supersedes_the_saved_snapshot():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {'table_name':'new_table','column_name':'id','data_type':'integer'},
        {'table_name':'VBRK','column_name':'vbeln','data_type':'text'},
    ]
    schema, source = load_live_schema(db, {'old_table': []})
    assert set(schema) == {'new_table', 'VBRK'}
    assert source == 'live_database_metadata'


def test_metadata_outage_uses_an_explicit_snapshot_source():
    db = MagicMock()
    db.execute.side_effect = RuntimeError('database unavailable')
    fallback = {'VBRK': [{'col': 'vbeln', 'type': 'text'}]}
    assert load_live_schema(db, fallback) == (fallback, 'schema_snapshot')
    db.rollback.assert_called_once()


@pytest.mark.parametrize('question, table, alias', [
    ('How many sales orders are there?', 'VBAK', 'sales_order_count'),
    ('How many billed invoices are there?', 'VBRK', 'billing_document_count'),
])
def test_count_uses_requested_documents_even_if_table_selection_proposes_ledger(question, table, alias):
    sql = build_document_total_count_sql(question, ['BKPF'])
    assert f'FROM "{table}"' in sql
    assert 'BKPF' not in sql
    assert alias in sql and 'COUNT(DISTINCT' in sql
    assert 'vbeln' in sql


@pytest.mark.parametrize('question', [
    'How many billed invoices for customer Acme?',
    'How many cancelled invoices?', 'How many vendor invoices?',
    'How many sales orders by country?', 'How many invoices last year?',
    'Count orders between 2000 and 2004',
])
def test_total_count_never_drops_extra_predicates(question):
    assert build_document_total_count_sql(question, []) is None


def test_document_count_keeps_an_explicit_year():
    sql = build_document_total_count_sql('How many sales orders in 2004?', [])
    assert '2004%' in sql and 'audat' in sql
