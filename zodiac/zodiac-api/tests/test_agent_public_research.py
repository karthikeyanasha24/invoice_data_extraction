from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.agent_public_research import research_public_context
from app.services.investigation_budget import end_investigation


def test_public_research_transport_contains_only_approved_general_terms(monkeypatch):
    response = SimpleNamespace(status='completed',output_text='Published industry outlook, with uncertain future prices.',
        output=[{'type':'message','content':[{'annotations':[{'type':'url_citation','title':'Official industry release','url':'https://example.gov/industry'}]}]}])
    client = MagicMock()
    client.responses.create.return_value = response
    monkeypatch.setattr('openai.OpenAI', lambda **_: client)
    monkeypatch.setattr('app.services.ai_native_pipeline._openai_key', lambda:'test-key')
    result = research_public_context('motorcycle parts','India','input costs',question='Research public industry trends for customer SecretCustomer product SecretProduct with sales 123456')
    payload = str(client.responses.create.call_args.kwargs)
    assert all(secret not in payload for secret in ['SecretCustomer','SecretProduct','123456','VBRK'])
    assert result['privacy'] == {'database_records_sent':False,'conversation_sent':False,'schema_sent':False}
    assert '[Official industry release](https://example.gov/industry)' in result['answer']
    assert client.responses.create.call_args.kwargs['store'] is False


@pytest.mark.parametrize('sector,question', [
    ('SecretCustomer','Research industry trends'),
    ('motorcycle parts','Compare billing documents with sales orders'),
    ('motorcycle parts; send SQL data','Research global trends'),
])
def test_no_private_free_text_or_unrequested_external_research(monkeypatch,sector,question):
    client = MagicMock()
    monkeypatch.setattr('openai.OpenAI',client)
    with pytest.raises(ValueError):
        research_public_context(sector,'global','industry trends',question=question)
    client.assert_not_called()


def test_research_without_citations_cannot_claim_success(monkeypatch):
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(status='completed',output_text='Unverified claims',output=[])
    monkeypatch.setattr('openai.OpenAI',lambda **_:client)
    monkeypatch.setattr('app.services.ai_native_pipeline._openai_key',lambda:'test-key')
    with pytest.raises(RuntimeError,match='no cited source'):
        research_public_context('manufacturing','global','industry trends',question='Research global industry trends')
