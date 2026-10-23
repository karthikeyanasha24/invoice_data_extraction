"""Offline regression checks for incomplete data and bounded repair feedback."""
from unittest.mock import MagicMock
import pytest
from app.services.analyst_agent import AnalystTools, _comparison_data_gaps, _sql_repair_feedback
from app.services.adaptive_analyst.understanding import technical_understanding_failure


PLAN = {'fields': [
    {'alias': 'order_currency', 'role': 'currency'},
    {'alias': 'invoice_currency', 'role': 'currency'},
    {'alias': 'order_value', 'role': 'measure'},
    {'alias': 'invoice_value', 'role': 'measure'},
]}


def test_mixed_currency_and_missing_amount_are_explicit_gaps():
    rows = [dict(order_currency='DEM',invoice_currency='USD',order_value=100,invoice_value=50),
            dict(order_currency=None,invoice_currency='DEM',order_value=None,invoice_value=0)]
    gaps = _comparison_data_gaps(rows, PLAN)
    assert len(gaps) == 2
    assert '1 returned comparison rows' in gaps[0] and 'exchange rates' in gaps[0]
    assert 'order_value' in gaps[1] and 'unknown, not zero' in gaps[1]
    assert rows[1]['order_value'] is None  # source evidence remains unchanged


def test_matching_currency_zero_amounts_and_empty_results_are_not_missing_data():
    assert not _comparison_data_gaps([dict(order_currency='DEM',invoice_currency='DEM',
                                         order_value=0,invoice_value=0)],PLAN)
    assert not _comparison_data_gaps([],PLAN)


@pytest.mark.parametrize('detail,expected', [
    ('invalid input syntax for type numeric: "1,23"', 'Do not turn them into zero'),
    ('date/time field value out of range: "00000000"', 'missing dates'),
    ('Unproven measure window over joined facts', 'Annual totals'),
    ('Unproven row grain', 'document-pair listings'),
    ('currency difference is unproven', 'verified exchange rates'),
])
def test_repairs_receive_actionable_feedback(detail,expected):
    assert expected in _sql_repair_feedback(detail)


def test_repair_limit_retains_last_validation_issue_without_executing_again():
    execute = MagicMock()
    tools = AnalystTools(MagicMock(),execute,lambda: {})
    tools.sql_repairs = 3
    tools.trace = [{'tool':'run_readonly_sql','error':'Query validation: Missing billing year filter'}]
    result = tools.call('run_readonly_sql',{'source':'business','sql':'SELECT b.netwr FROM "VBRK" b','purpose':'Compare'})
    assert not result['ok']
    assert 'SQL repair limit' in result['error'] and 'Missing billing year filter' in result['error']
    execute.assert_not_called()


def test_missing_provider_configuration_is_not_reported_as_transient_outage():
    error = RuntimeError('No configured key')
    error.code = 'provider_configuration'
    result = technical_understanding_failure('Compare values',error)
    assert result['meta']['service_issue'] == 'provider_configuration'
    assert 'configuration needs attention' in result['answer']
