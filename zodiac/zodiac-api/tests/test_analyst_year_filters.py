"""Exact date scope for independent annual order/invoice comparisons."""
import pytest
from app.services.analyst_filters import filter_issues


@pytest.mark.parametrize('predicate', [
    "o.audat >= '20000101' AND o.audat < '20020101'",
    "o.audat >= DATE '2000-01-01' AND o.audat < DATE '2002-01-01'",
    "o.audat BETWEEN '20000101' AND '20011231'",
    "SUBSTRING(o.audat, 1, 4) IN ('2000','2001')",
    "EXTRACT(YEAR FROM o.audat::date) IN (2000,2001)",
])
def test_complete_two_year_scope_is_accepted(predicate):
    rule = dict(table='VBAK', column='audat', operator='year', values=['2000','2001'])
    assert not filter_issues('SELECT o.netwr FROM "VBAK" o WHERE ' + predicate, [rule])


@pytest.mark.parametrize('predicate', [
    "o.audat >= '20000101' AND o.audat < '20010101'",
    "o.audat >= '19990101' AND o.audat < '20020101'",
    "o.audat >= '20000101' AND o.audat < '20030101'",
    "SUBSTRING(o.audat, 1, 4) IN ('2000','2001','2002')",
    "o.audat >= '20000101' OR 1=1",
    "o.audat >= '20000101' AND o.erdat < '20020101'",
    "EXTRACT(YEAR FROM o.audat::date) + 1 IN (2000,2001)",
    "o.audat + 1 >= '20000101' AND o.audat + 1 < '20020101'",
])
def test_missing_broadened_or_wrong_column_scope_is_rejected(predicate):
    rule = dict(table='VBAK', column='audat', operator='year', values=['2000','2001'])
    assert filter_issues('SELECT o.netwr FROM "VBAK" o WHERE ' + predicate, [rule])


def test_dates_on_orders_do_not_prove_billing_scope():
    sql = '''SELECT o.netwr,b.netwr FROM "VBAK" o JOIN "VBRK" b ON o.mandt=b.mandt
             WHERE o.audat >= '20000101' AND o.audat < '20020101' '''
    rules = [dict(table=t, column=c, operator='year', values=['2000','2001'])
             for t,c in [('VBAK','audat'), ('VBRK','fkdat')]]
    errors = filter_issues(sql, rules)
    assert len(errors) == 1 and 'VBRK.fkdat' in errors[0]


def test_nonconsecutive_years_cannot_be_proven_by_broad_range():
    rule = dict(table='VBAK', column='audat', operator='year', values=['2000','2002'])
    assert filter_issues('''SELECT o.netwr FROM "VBAK" o
        WHERE o.audat >= '20000101' AND o.audat < '20030101' ''', [rule])


def test_single_year_prefix_remains_supported():
    rule = dict(table='VBAK', column='audat', operator='year', values=['2000'])
    assert not filter_issues('''SELECT o.netwr FROM "VBAK" o WHERE o.audat LIKE '2000%' ''', [rule])
