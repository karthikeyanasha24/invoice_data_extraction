from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst.understanding import technical_understanding_failure


@pytest.mark.parametrize('code, status, issue', [
    ('credit_balance_exhausted', 429, 'quota_exhausted'),
    ('insufficient_quota', 429, 'quota_exhausted'),
    ('rate_limit_exceeded', 429, 'rate_limited'),
    ('invalid_api_key', 401, 'provider_configuration'),
])
def test_service_failure_explains_the_correct_action(code, status, issue):
    error = RuntimeError('provider failure')
    error.code = code
    error.status_code = status
    result = technical_understanding_failure('Explain an API', error)
    assert result['meta']['service_issue'] == issue
    assert result['answer_status'] == 'CANNOT_ANSWER'
    assert not result['data'] and not result['sql']


def test_cooldown_preserves_quota_reason_without_repeating_provider_call(monkeypatch):
    from app.services import ai_native_pipeline as provider
    monkeypatch.setattr(provider, '_PROVIDER_FAILURE_UNTIL', {})
    monkeypatch.setattr(provider, '_PROVIDER_FAILURE_ERRORS', {})
    monkeypatch.setattr(provider, '_LAST_PROBE_REQUEST', {})
    monkeypatch.setattr(provider, '_openai_key', lambda: 'fake-test-key')
    monkeypatch.setattr(provider, '_google_key', lambda: '')
    monkeypatch.setenv('AI_CHAT_PROVIDER', 'openai')
    error = RuntimeError('credit_balance_exhausted')
    error.code = 'credit_balance_exhausted'
    error.status_code = 429
    call = MagicMock(side_effect=error)
    monkeypatch.setattr(provider, '_openai_chat', call)
    for _ in range(2):
        with pytest.raises(RuntimeError) as failure:
            provider.llm_text('system', 'question')
        assert technical_understanding_failure('question', failure.value)['meta']['service_issue'] == 'quota_exhausted'
    assert call.call_count == 1


def test_new_investigation_probes_openai_after_quota_cooldown(monkeypatch):
    from app.services import ai_native_pipeline as provider
    from app.services.investigation_budget import begin_investigation, end_investigation
    monkeypatch.setattr(provider, '_PROVIDER_FAILURE_UNTIL', {})
    monkeypatch.setattr(provider, '_PROVIDER_FAILURE_ERRORS', {})
    monkeypatch.setattr(provider, '_LAST_PROBE_REQUEST', {})
    monkeypatch.setattr(provider, '_openai_key', lambda: 'fake-test-key')
    monkeypatch.setattr(provider, '_google_key', lambda: '')
    monkeypatch.setenv('AI_CHAT_PROVIDER', 'openai')
    error = RuntimeError('credit_balance_exhausted')
    error.code = 'credit_balance_exhausted'
    error.status_code = 429
    call = MagicMock(side_effect=[error, 'restored after credits'])
    monkeypatch.setattr(provider, '_openai_chat', call)
    begin_investigation('first', request_id='quota-1')
    try:
        with pytest.raises(RuntimeError):
            provider.llm_text('system', 'question')
        with pytest.raises(RuntimeError):
            provider.llm_text('system', 'retry same investigation')
        assert call.call_count == 1
    finally:
        end_investigation()
    begin_investigation('after credits', request_id='quota-2')
    try:
        text, used = provider.llm_text('system', 'question')
        assert text == 'restored after credits' and used == 'openai'
        assert call.call_count == 2
        assert provider._provider_available('openai')
    finally:
        end_investigation()


def test_timeout_is_not_a_generic_outage():
    error = TimeoutError('The read operation timed out')
    result = technical_understanding_failure('Compare invoice 0090010427', error)
    assert result['meta']['service_issue'] == 'timeout'
    assert 'timed out' in result['answer']
    assert 'unavailable' not in result['answer']


def test_quota_code_inside_openai_body_is_classified():
    error = RuntimeError('Error code: 429')
    error.status_code = 429
    error.body = {'error': {'code': 'insufficient_quota', 'message': 'You exceeded your current quota'}}
    result = technical_understanding_failure('Compare invoice 0090010427', error)
    assert result['meta']['service_issue'] == 'quota_exhausted'
