from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.analyst_model_policy import (
    analyst_model_task, analyst_openai_model, analyst_output_limit, analyst_reasoning_effort,
)
from app.services.analyst_result_evidence import result_evidence


@pytest.fixture
def clean_model_env(monkeypatch):
    import os
    for name in list(os.environ):
        if name.startswith(('AI_ANALYST_', 'AI_NATIVE_', 'OPENAI_MODEL', 'LANGGRAPH_OPENAI_MODEL',
                            'OPENAI_REASONING_EFFORT', 'AI_JSON_MAX_TOKENS', 'AI_RESPONSE_MAX_TOKENS')):
            monkeypatch.delenv(name, raising=False)


def test_helper_setting_cannot_override_analyst_model(monkeypatch, clean_model_env):
    monkeypatch.setenv('AI_FAST_MODEL', 'small-helper')
    monkeypatch.setenv('OPENAI_MODEL', 'main-model')
    assert analyst_openai_model() == 'main-model'
    monkeypatch.setenv('AI_ANALYST_MODEL', 'analyst-model')
    assert analyst_openai_model() == 'analyst-model'
    monkeypatch.setenv('AI_ANALYST_PLANNING_MODEL', 'planner-model')
    with analyst_model_task('planning'):
        assert analyst_openai_model() == 'planner-model'
        assert analyst_reasoning_effort() == 'medium'
    assert analyst_openai_model() == 'analyst-model'


def test_answer_has_room_for_detailed_json_and_restores_task(clean_model_env):
    with analyst_model_task('planning'):
        assert analyst_output_limit(True) == 6000
        with analyst_model_task('answer'):
            assert analyst_output_limit(True) == 8000
            assert analyst_reasoning_effort() == 'low'
        assert analyst_reasoning_effort() == 'medium'


@pytest.mark.parametrize('model', ['gpt-5', 'gpt-6-astra', 'gpt-6.1-sol'])
def test_reasoning_model_parameters_are_compatible(model, monkeypatch):
    from app.utils.openai_chat_params import openai_chat_temperature_kwargs, openai_completion_limit_kwargs
    monkeypatch.delenv('OPENAI_USE_MAX_COMPLETION_TOKENS', raising=False)
    assert openai_chat_temperature_kwargs(model, 0.1) == {}
    kwargs = openai_completion_limit_kwargs(model, 8000, reasoning_effort='medium')
    assert 'max_tokens' not in kwargs and kwargs['max_completion_tokens'] >= 8000
    assert kwargs['reasoning_effort'] == 'medium'


def test_explicit_openai_preference_wins_over_legacy_gemini_flag(monkeypatch):
    from app.services import ai_native_pipeline as native
    monkeypatch.setenv('AI_CHAT_PROVIDER', 'openai')
    monkeypatch.setenv('AI_PREFER_GEMINI', 'true')
    monkeypatch.setattr(native, '_openai_key', lambda: 'unit-test-key')
    monkeypatch.setattr(native, '_google_key', lambda: 'unit-test-key')
    monkeypatch.setattr(native, '_provider_available', lambda provider: True)
    openai = MagicMock(return_value='actual answer')
    gemini = MagicMock(return_value='other answer')
    monkeypatch.setattr(native, '_openai_chat', openai)
    monkeypatch.setattr(native, '_gemini_chat', gemini)
    assert native.llm_text('system', 'message') == ('actual answer', 'openai')
    gemini.assert_not_called()


def test_disabled_fallback_does_not_send_to_other_provider(monkeypatch):
    from app.services import ai_native_pipeline as native
    monkeypatch.setenv('AI_CHAT_PROVIDER', 'openai')
    monkeypatch.setenv('AI_ANALYST_ALLOW_PROVIDER_FALLBACK', 'false')
    monkeypatch.setattr(native, '_openai_key', lambda: 'unit-test-key')
    monkeypatch.setattr(native, '_google_key', lambda: 'unit-test-key')
    monkeypatch.setattr(native, '_provider_available', lambda provider: True)
    monkeypatch.setattr(native, '_provider_failed', lambda *args: None)
    monkeypatch.setattr(native, '_openai_chat', MagicMock(side_effect=RuntimeError('unavailable')))
    gemini = MagicMock()
    monkeypatch.setattr(native, '_gemini_chat', gemini)
    with pytest.raises(RuntimeError, match='unavailable'):
        native.llm_text('system', 'message')
    gemini.assert_not_called()


def comparison_sql():
    return '''SELECT customer_id, SUM(CASE WHEN year='2012' THEN amount ELSE 0 END) AS period_a,
    SUM(CASE WHEN year='2015' THEN amount ELSE 0 END) AS period_b FROM facts
    WHERE amount < 0 GROUP BY customer_id'''


def test_evidence_retains_complete_filters_labels_nulls_and_scope():
    sql = comparison_sql().replace('WHERE', '/*' + 'evidence ' * 250 + '*/ WHERE')
    rows = [{'customer_id': 'A', 'currency': 'USD', 'period_a': -10, 'period_b': None}]
    evidence = result_evidence(sql, rows, {})
    assert evidence['executed_sql'] == sql
    assert evidence['negative_values_only'] is True
    assert evidence['zero_default_expressions']
    assert evidence['null_columns'] == ['period_b']
    assert evidence['currencies'] == ['USD']
    assert evidence['rows'][0]['customer_id'] == 'A'
    assert evidence['sample_is_complete'] is True
    assert result_evidence(sql.replace('amount < 0', "year='2012'"), rows, {})['negative_values_only'] is False


def test_evidence_sample_stays_valid_json_at_row_boundaries():
    rows = [{'customer_name': 'a' * 15000, 'amount': -1} for _ in range(8)]
    evidence = json.loads(json.dumps(result_evidence('SELECT * FROM facts', rows, {})))
    assert 0 < evidence['sample_row_count'] < evidence['returned_row_count']
    assert evidence['sample_is_complete'] is False
    assert all(row['customer_name'] == 'a' * 15000 for row in evidence['rows'])


def test_answer_stage_gets_full_sql_and_structured_evidence(monkeypatch):
    from app.services import four_stage_db_pipeline as pipeline
    sql = comparison_sql() + ' /*' + 'full query ' * 200 + '*/'
    rows = [{'customer_id': 'A', 'currency': 'USD', 'period_a': -10, 'period_b': -8}]
    captured = {}
    def model(system, user):
        captured.update(json.loads(user))
        with_context = analyst_output_limit(True)
        assert with_context >= 8000
        return {'answer': 'A has -10 in 2012 and -8 in 2015.', 'summary': 'A improved.'}, 'controlled'
    monkeypatch.setattr(pipeline, 'analyze_json', model)
    answer = pipeline.pipeline4_result_analysis('Explain all details', sql, rows, pipeline.VerifiedDbContext('question'))
    assert answer['answer'].startswith('A has')
    assert captured['execution_evidence']['executed_sql'] == sql
    assert captured['execution_evidence']['rows'] == rows


def test_long_message_keeps_late_constraints_for_understanding_and_response(monkeypatch):
    from app.services.adaptive_analyst import understanding as und
    question = 'Explain the following carefully. ' + 'context ' * 650 + 'END: exclude cancelled records and keep currencies separate.'
    seen = []
    def understand(system, user):
        seen.append(user)
        return {'intent': 'knowledge', 'requires_database': False, 'goal': 'Explain'}, 'controlled'
    monkeypatch.setattr(und, 'analyze_json', understand)
    turn = und.understand_turn(question, capability_context={})
    def respond(system, user):
        assert json.loads(user.split('\n', 1)[1])['current_user_message'] == question
        return 'A detailed explanation.', 'controlled'
    monkeypatch.setattr(und, 'complete_text', respond)
    und.generate_grounded_response(question, turn, evidence={})
    assert question in seen[0]


def test_comparison_chart_has_category_axis_and_both_period_measures():
    from app.api.adaptive_query import _auto_charts
    rows = [{'customer_id': key, 'currency': 'USD', 'period_a': -10 - i, 'period_b': -8 - i, 'change': 2}
            for i, key in enumerate(('A', 'B', 'C'))]
    chart = _auto_charts('Compare billed sales across periods', comparison_sql(), rows)[0]
    assert chart['chart_type'] == 'bar'
    assert chart['x_key'] == 'customer_id'
    assert 'period_a' in chart['y_keys'] and 'period_b' in chart['y_keys']
    assert 'over time' not in chart['description']


def test_chart_data_preserves_missing_value_instead_of_inventing_zero():
    from app.services.chart_decision_engine import _format_data
    assert _format_data([{'customer': 'A', 'amount': None}])[0]['amount'] is None


def test_long_previous_request_keeps_late_constraints_on_followup(monkeypatch):
    from app.services.adaptive_analyst import understanding as und
    from app.services.adaptive_analyst.conversation_state import InvestigationState
    question = 'Explain this comparison. ' + 'context ' * 650 + 'END: exclude cancelled records.'
    state = InvestigationState()
    state.remember_turn(question, 'Verified explanation.', mode='database_analysis')
    assert state.last_user_question == question
    captured = {}
    def model(system, user):
        captured['payload'] = user
        return {'intent': 'conversation', 'requires_database': False, 'goal': 'Explain'}, 'controlled'
    monkeypatch.setattr(und, 'analyze_json', model)
    und.understand_turn('Explain that again', prior_question=state.last_user_question, capability_context={})
    assert question in captured['payload']


def test_one_slow_call_does_not_disable_answer_provider(monkeypatch):
    from app.services import ai_native_pipeline as native
    monkeypatch.setattr(native, '_PROVIDER_FAILURE_UNTIL', {})
    monkeypatch.setattr(native, '_openai_key', lambda: 'fake-key')
    monkeypatch.setattr(native, '_openai_model', lambda: 'test-model')
    native._provider_failed('openai', TimeoutError('one task ran slowly'))
    assert native._provider_available('openai')
    native._provider_failed('openai', RuntimeError('provider configuration unavailable'))
    assert not native._provider_available('openai')


def test_supported_semantic_renderer_skips_discarded_model_plan(monkeypatch):
    from app.services import four_stage_db_pipeline as pipeline
    ctx = pipeline.VerifiedDbContext('compare')
    monkeypatch.setattr(pipeline, '_resolve_latest_data_years', lambda *a: True)
    monkeypatch.setattr(pipeline, '_resolve_relative_period_years', lambda *a: None)
    render = MagicMock(return_value='SELECT verified_comparison')
    model = MagicMock()
    monkeypatch.setattr(pipeline, 'pipeline3_sql_generation', render)
    monkeypatch.setattr(pipeline, 'build_structured_query_plan', model)
    pipeline.pipeline25_query_plan('compare', ctx)
    render.assert_called_once_with('compare', ctx, templates_only=True)
    model.assert_not_called()


def test_table_discovery_keeps_current_turn_semantics_without_repeating_model(monkeypatch):
    from app.services import four_stage_db_pipeline as pipeline
    semantic = {'measure': {'concept': 'sales'}, 'dimensions': ['customer']}
    ctx = pipeline.VerifiedDbContext('current question', semantic_requirements=semantic)
    extraction = MagicMock()
    monkeypatch.setattr(pipeline, 'extract_semantic_requirements', extraction)
    registry = MagicMock()
    registry.lightweight_table_catalog.return_value = []
    registry.compact_catalog_text.return_value = ''
    registry.resolve_data_limitation.return_value = None
    monkeypatch.setattr(pipeline, 'get_schema_registry', lambda: registry)
    monkeypatch.setattr(pipeline, 'analyze_json', lambda *a: ({'selected_tables': []}, 'controlled'))
    monkeypatch.setattr(pipeline, '_ensure_measure_source_tables', lambda *a: None)
    monkeypatch.setattr(pipeline, 'ensure_complete_table_coverage', lambda *a, **k: None)
    pipeline.pipeline1_table_selection('current question', ctx)
    extraction.assert_not_called()
    assert ctx.semantic_requirements == semantic


def test_postgres_substring_syntax_is_not_an_unknown_field(monkeypatch):
    from app.services import adaptive_structured_sql as structured
    monkeypatch.setattr(structured, 'resolve_table_name', lambda t: t)
    monkeypatch.setattr(structured, 'has_column', lambda t, c: t == 'facts' and c == 'posted')
    monkeypatch.setattr(structured, 'column_names', lambda t: ['posted'])
    assert not structured._validate_expression_refs('SUBSTRING(CAST(facts.posted AS TEXT) FROM 1 FOR 4)', ['facts'])
    assert structured._validate_expression_refs('SUBSTRING(CAST(facts.unknown AS TEXT) FROM 1 FOR 4)', ['facts'])


def test_linked_order_period_aliases_satisfy_year_date_comparison():
    from app.services.plan_satisfaction import sql_has_period_comparison
    sql = ('WITH p AS (SELECT SUM(CASE WHEN o.erdat >= \'20000101\' AND o.erdat < \'20010101\' '
           'THEN o.netwr END) AS "order_amount_2000", '
           'SUM(CASE WHEN o.erdat >= \'20010101\' AND o.erdat < \'20020101\' '
           'THEN o.netwr END) AS "order_amount_2001" FROM VBAK o) '
           'SELECT p.order_amount_2001 - p.order_amount_2000 AS absolute_change FROM p')
    assert sql_has_period_comparison(sql, ['2000', '2001'])
    invalid = sql.replace('p.order_amount_2001 - p.order_amount_2000 AS absolute_change',
                          'p.order_amount_2001 AS amount')
    assert not sql_has_period_comparison(invalid, ['2000', '2001'])


def test_invoice_charts_separate_currencies_and_do_not_plot_rank_as_money():
    from app.api.adaptive_query import _auto_charts
    rows = [{'billing_document': f'I{i}', 'invoice_date': '20150101', 'invoice_rank': i + 1,
             'invoice_amount': -10 - i, 'currency': currency} for i, currency in enumerate(('USD', 'EUR', 'USD', 'EUR'))]
    charts = _auto_charts('Compare the lowest invoices in each period', 'SELECT invoices', rows)
    assert len(charts) == 2
    for chart in charts:
        assert chart['chart_type'] == 'bar'
        assert chart['x_key'] == 'billing_document'
        assert chart['y_keys'] == ['invoice_amount']
        assert len({row['currency'] for row in chart['data']}) == 1


def test_same_invoice_reference_does_not_block_linked_order_comparison():
    from app.services.analytical_operations import extract_analytical_operations
    question = ('Independently select negative invoices in each year 2012 and 2015. '
                'Then compare linked sales orders relevant to those same invoices by year; show billing document numbers.')
    assert extract_analytical_operations(question).get('clarification', {}).get('type') != 'document_period_comparison'


def test_linked_order_followup_replans_when_prior_result_is_only_customer_aggregate():
    from app.services.result_first_followup import try_answer_from_prior_rows
    rows = [{'currency': 'DEM', 'customer_id': 'R111', 'customer_name': 'Customer',
             'period_a': -12.19, 'period_b': -10.19, 'change': 2.0}]
    result = try_answer_from_prior_rows(
        'Use the invoices from this result to compare, then compare them with the sales orders relevant to those linked invoices.',
        rows,
        prior_sql='SELECT customer_id, SUM(netwr) AS period_a, SUM(netwr) AS period_b FROM VBRK GROUP BY customer_id',
        prior_plan={'dimensions': ['customer']},
        prior_question='Show lowest negative invoice sales in 2000 and compare with 2001.',
    )
    # No invoice keys means it must use the original request to replan at
    # document grain instead of ending in a canned clarification.
    assert result and result['needs_plan_expansion']
    assert 'Show lowest negative invoice sales in 2000 and compare with 2001.' in result['expanded_question']
    assert 'billing-document IDs' in result['expanded_question']


def test_linked_invoice_followup_recognizes_natural_reference_to_those_linked_invoices():
    from app.services.result_first_followup import try_answer_from_prior_rows
    rows = [{'currency': 'DEM', 'customer_id': 'R111', 'period_a': -12.19, 'period_b': -10.19}]
    result = try_answer_from_prior_rows(
        'Use first invoices to compare and then compare with sales orders relevant to those linked invoices.',
        rows,
        prior_sql='SELECT customer_id, SUM(netwr) AS period_a FROM VBRK GROUP BY customer_id',
        prior_plan={'dimensions': ['customer']},
        prior_question='Show me lowest negative sales in the year 2000 and make comparison with the year 2001.',
    )
    assert result and result['needs_plan_expansion']
    assert result['missing_concept'] == 'invoice_document_keys_for_linked_order_comparison'
    assert 'billing document number first' in result['expanded_question'].lower()
    assert 'year 2000' in result['expanded_question'].lower()
    assert 'year 2001' in result['expanded_question'].lower()


def test_linked_invoice_followup_expands_after_a_clarification_with_no_result_rows():
    from app.services.result_first_followup import try_answer_from_prior_rows
    result = try_answer_from_prior_rows(
        'Use invoices from 2000 first, then compare the sales orders linked to those invoices across 2000 and 2001.',
        [],
        prior_plan={'pending_clarification': {'type': 'document_period_comparison'}},
        prior_question='Show me the lowest negative billed sales in calendar year 2000 and compare with 2001.',
    )
    assert result and result['needs_plan_expansion']
    assert 'Original analysis request:' in result['expanded_question']
    assert 'billing document number first' in result['expanded_question'].lower()


def test_model_fallback_explains_unavailable_linked_order_comparison():
    from app.services.four_stage_db_pipeline import _verified_result_fallback
    result = _verified_result_fallback([{
        'billing_document': 'I-1', 'customer_id': 'C-1', 'invoice_amount': -12,
        'linked_sales_orders': None, 'order_amount_2000': None, 'order_amount_2001': None,
        'absolute_change': None, 'percent_change': None,
    }])
    assert 'no verified linked sales-order IDs were found' in result['answer']
    assert '2000, 2001' in result['answer']
    assert 'do not mean zero sales' in result['answer']
    assert result['findings'] == [result['answer']]


def test_model_fallback_explains_gross_profit_rankings_without_mixing_currencies():
    from app.services.four_stage_db_pipeline import _verified_result_fallback
    result = _verified_result_fallback([
        {
            'material_id': 'SER-1', 'material_name': 'Standard 5x10',
            'currency': 'EUR', 'gross_profit': 1234.5, 'rank_within_currency': 1,
        },
        {
            'material_id': 'SER-2', 'material_name': 'Pump',
            'currency': 'USD', 'gross_profit': 998.0, 'rank_within_currency': 1,
        },
        {
            'material_id': 'NO-DESCRIPTION', 'material_name': None,
            'currency': 'CAD', 'gross_profit': 15.0, 'rank_within_currency': 1,
        },
    ])
    assert 'billing-item gross-profit' in result['answer']
    assert 'cannot be compared directly' in result['answer']
    assert 'EUR: Standard 5x10 (SER-1) — 1,234.5' in result['answer']
    assert 'USD: Pump (SER-2) — 998' in result['answer']
    assert 'CAD: NO-DESCRIPTION — 15' in result['answer']


def test_preaggregated_linked_order_comparison_is_safe_at_invoice_grain():
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    safe = '''WITH invoice_cohort AS (SELECT vbeln AS "billing_document", netwr, waerk AS "currency" FROM VBRK),
    linked_orders AS (SELECT i."billing_document", o.vbeln AS order_id, o.netwr FROM invoice_cohort i JOIN VBFA f ON f.vbeln = i."billing_document" JOIN VBRP b ON b.vbeln = i."billing_document" JOIN VBAK o ON o.vbeln = b.aubel),
    order_periods AS (SELECT l."billing_document", i."currency", SUM(l.netwr) AS "order_amount_2001" FROM linked_orders l JOIN invoice_cohort i ON i."billing_document" = l."billing_document" GROUP BY l."billing_document", i."currency")
    SELECT i.netwr AS invoice_amount, p."order_amount_2001" FROM invoice_cohort i LEFT JOIN order_periods p ON p."billing_document" = i."billing_document"'''
    unsafe = 'SELECT SUM(i.netwr), SUM(o.netwr) FROM VBRP i JOIN VBAK o ON o.vbeln = i.aubel'
    assert not sql_has_unsafe_monetary_fanout(safe)
    assert sql_has_unsafe_monetary_fanout(unsafe)


def test_detailed_plain_language_request_is_not_forced_to_one_sentence():
    from app.services.adaptive_analyst.understanding import _is_simplification_followup
    assert not _is_simplification_followup('Explain in plain language in detail with examples.', 'knowledge')
    assert _is_simplification_followup('Explain that in plain language.', 'conversation')
