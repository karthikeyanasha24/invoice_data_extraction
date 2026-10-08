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
