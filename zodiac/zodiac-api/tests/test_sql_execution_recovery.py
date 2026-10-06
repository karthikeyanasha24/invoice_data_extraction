"""Execution failures get bounded repairs, without bypassing query validation."""
from unittest.mock import MagicMock
import pytest
from app.services import four_stage_db_pipeline as pipeline


@pytest.mark.parametrize('repair,expected_calls', [
    ('SELECT 2 AS value', 2),
    ('SELECT SUM(o.netwr), SUM(i.netwr) FROM "VBAK" o JOIN vbrp i ON o.vbeln=i.aubel', 1),
])
def test_join_error_repair_is_revalidated_before_execution(monkeypatch, repair, expected_calls):
    ctx = pipeline.VerifiedDbContext(question='Compare the available measures')
    monkeypatch.setattr(pipeline, '_apply_followup_to_context', lambda *a: ctx)
    monkeypatch.setattr(pipeline, 'extract_semantic_requirements', lambda *a: {})
    generation = MagicMock(side_effect=['SELECT 1 AS value', repair])
    monkeypatch.setattr(pipeline, 'pipeline3_sql_generation', generation)
    monkeypatch.setattr(pipeline, '_apply_currency_if_needed', lambda q, sql, *a: sql)
    monkeypatch.setattr(pipeline, '_validate_sql_against_context', lambda *a: [])
    monkeypatch.setattr(pipeline, 'pipeline4_result_analysis', lambda *a, **k: {'answer': 'Test boundary'})
    execute = MagicMock(side_effect=[
        RuntimeError('FULL JOIN is only supported with merge-joinable or hash-joinable join conditions'),
        [{'value': 2}],
    ])
    result = pipeline.run_four_stage_database_query(ctx.question, MagicMock(), execute)
    assert generation.call_count == 2
    assert ctx.pipeline_log['SQL_VALIDATION_RETRY_FEEDBACK']['failure_class'] == 'invalid_join'
    if expected_calls == 2:
        correction = generation.call_args.kwargs['validation_feedback']
        assert correction['kind'] == 'execution_repair'
        assert correction['failure_class'] == 'invalid_join'
        assert 'SELECT 1 AS value' in correction['previous_sql']
        assert correction['database_error']
    assert execute.call_count == expected_calls
    if expected_calls == 1:
        assert result['error'] == 'sql_execution_failed'
        assert 'SQL_REPAIR_REJECTED' in ctx.pipeline_log
    else:
        assert not result.get('error')
        assert result['rows'] == [{'value': 2}]


def test_validation_repair_bypasses_rejected_deterministic_templates(monkeypatch):
    import app.services.adaptive_structured_sql as structured

    ctx = pipeline.VerifiedDbContext(
        question='Show the lowest billed sales by material in the latest year.',
        tables=['VBRK', 'vbrp'],
        columns=['VBRK.vbeln', 'vbrp.vbeln', 'vbrp.posnr', 'vbrp.netwr', 'vbrp.matnr'],
    )
    monkeypatch.setattr(
        structured,
        'build_dimension_ranking_sql',
        lambda *_args, **_kwargs: pytest.fail('validation retry reused the rejected template'),
    )
    observed = {}

    def corrected_sql(system, prompt):
        observed['prompt'] = prompt
        return '```sql\nSELECT 2 AS value\n```', 'test-provider'

    monkeypatch.setattr(pipeline, 'complete_text', corrected_sql)
    result = pipeline.pipeline3_sql_generation(
        ctx.question,
        ctx,
        validation_feedback={
            'kind': 'sql_validation_repair',
            'validation_errors': ['Deduplicate identical VBRP item rows before aggregation.'],
        },
    )

    assert 'SELECT 2 AS value' in result
    assert 'Deduplicate identical VBRP item rows before aggregation.' in observed['prompt']
