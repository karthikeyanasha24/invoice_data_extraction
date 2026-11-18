"""Exact date scope for independent annual order/invoice comparisons."""
import pytest
from app.services.analyst_filters import filter_issues
from app.services.analytical_operations import (
    extract_analytical_operations, merge_semantic_requirements, year_scope_from_question,
)
from app.services.basic_sql_training import answerability_issues, needs_specific_years


def test_year_scope_modes_match_client_date_filter_rules():
    assert year_scope_from_question("lowest sales for all years by industry")["mode"] == "all_years"
    assert year_scope_from_question("lowest sales for the year 1999") == {"mode": "single", "years": ["1999"]}
    assert year_scope_from_question("sales between 2000 and 2005")["mode"] == "range"
    assert year_scope_from_question("sales between 2000 and 2005")["years"] == [
        "2000", "2001", "2002", "2003", "2004", "2005",
    ]
    assert year_scope_from_question("sales for 1999 and 2003") == {
        "mode": "selected", "years": ["1999", "2003"],
    }
    assert not needs_specific_years("lowest sales for all the years by country")


def test_multi_year_requirements_emit_fkdat_time_filters():
    selected = extract_analytical_operations("show sales for 1999 and 2003 by country")
    assert selected["year_scope"]["mode"] == "selected"
    selected_req = merge_semantic_requirements("show sales for 1999 and 2003 by country")
    assert selected_req["date_filter"]["operator"] == "in"
    assert selected_req["date_filter"]["years"] == ["1999", "2003"]
    assert selected_req["time_filter"]["years"] == ["1999", "2003"]

    ranged_q = "comparative analysis of sales between the years 2000 to 2005 by country"
    ranged = extract_analytical_operations(ranged_q)
    assert ranged["year_scope"]["mode"] == "range"
    assert "year" in ranged["group_by"]
    assert not ranged.get("period_compare")
    ranged_req = merge_semantic_requirements(ranged_q)
    assert ranged_req["date_filter"]["operator"] == "between"
    assert ranged_req["date_filter"]["years"][0] == "2000" and ranged_req["date_filter"]["years"][-1] == "2005"

    all_years = extract_analytical_operations("lowest sales for all years by industry and customer")
    all_req = merge_semantic_requirements("lowest sales for all years by industry and customer")
    assert all_years.get("years") in (None, [])
    assert all_req.get("date_filter", {}).get("type") == "all_years"
    assert not all_req.get("time_filter")


def test_all_years_training_examples_do_not_require_fkdat_filters():
    question = "show me the lowest sales for all the years by industry and customer and country"
    sql = ('SELECT "KNA1"."land1" AS country, "KNA1"."name1" AS customer, '
           'SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS total_sales FROM "VBRK" '
           'JOIN "KNA1" ON "VBRK"."kunag"="KNA1"."kunnr" AND "VBRK"."mandt"="KNA1"."mandt" '
           'GROUP BY "KNA1"."land1", "KNA1"."name1"')
    assert answerability_issues(question, sql, [{"country": "DE", "customer": "Acme", "total_sales": 1}]) == []


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
