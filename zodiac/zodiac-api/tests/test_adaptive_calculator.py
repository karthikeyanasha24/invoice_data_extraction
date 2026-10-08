from unittest.mock import MagicMock

import pytest

from app.services.adaptive_analyst.calculator import calculate_question
from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator


@pytest.mark.parametrize('question, expected', [
    ('What is 2 plus 2?', '4'), ('whst i2 plus 2', '4'),
    ('two plus two', '4'), ('Calculate (12 + 8) / 5', '4'),
    ('What is 0.1 + 0.2?', '0.3'), ('15 percent of 240', '36'),
    ('Compute 8 times 7 minus 6', '50'), ('Evaluate 2^10', '1024'),
    ('12 divided by 4', '3'), ('-3 + 8', '5'),
    ('100 - 37', '63'), ('2 × (3 + 4)', '14'),
])
def test_calculates_varied_expressions(question, expected):
    assert calculate_question(question).value == expected


@pytest.mark.parametrize('question', [
    'Show top 2 customers', '2', 'Show sales for 2025',
    'What is 2 plus 2 and explain an API?', '15 percent of our sales',
    '__import__("os").system("whoami")', '2 ** 10000000',
    '2 + customer_count', 'What is profit?', '(2 + 2',
])
def test_does_not_swallow_non_calculator_requests(question):
    assert calculate_question(question) is None


def test_zero_division_is_explained():
    answer = calculate_question('Calculate 5 / 0')
    assert answer.value is None
    assert 'undefined' in answer.answer


def test_calculation_survives_model_outage_and_keeps_conversation(monkeypatch):
    from app.services.adaptive_analyst import understanding, llm_provider
    unavailable = MagicMock(side_effect=RuntimeError('model offline'))
    monkeypatch.setattr(understanding, 'analyze_json', unavailable)
    monkeypatch.setattr(llm_provider, 'complete_text', unavailable)
    execute = MagicMock(side_effect=AssertionError('arithmetic must not query database'))
    out = run_adaptive_orchestrator('What is 2 plus 2?', MagicMock(), execute,
        prior_question='Call me Mira.',
        prior_plan={'recent_turns': [{'role': 'user', 'content': 'Call me Mira.'}]})
    assert out['answer_status'] == 'SUCCESS'
    assert out['meta']['value'] == '4'
    assert out['sql'] == ''
    assert out['query_plan']['investigation_state']['recent_turns'][0]['content'] == 'Call me Mira.'
    execute.assert_not_called()
    unavailable.assert_not_called()


def test_api_calculation_works_without_model_keys_and_ignores_old_percentage_rows(monkeypatch):
    from fastapi import BackgroundTasks
    from app.api.adaptive_query import _post_query_adaptive_body
    from app.services.investigation_budget import end_investigation
    for key in ('OPENAI_API_KEY', 'OPEN_AI_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GEMINI_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    tasks = BackgroundTasks()
    try:
        out = _post_query_adaptive_body(q='15 percent of 240', original_question='15 percent of 240',
            tableHint=None, contextData={'previousQuestion': 'Show sales', 'previousSQL': 'SELECT sales FROM invoices',
                'previousAnswerStatus': 'SUCCESS', 'data': [{'sales': 9000}]},
            overrideSql=None, threadId=None, investigationId=None, db=MagicMock(),
            current_user=type('User', (), {'id': 42})(), background_tasks=tasks)
        assert out['answer_status'] == 'SUCCESS'
        assert out['meta']['value'] == '36'
        assert out['sql'] == ''
    finally:
        end_investigation()


def test_nonterminating_decimal_is_marked_as_approximate():
    result = calculate_question('1 / 3')
    assert result.approximate is True
    assert '≈' in result.answer
    assert calculate_question('0.1 + 0.2').approximate is False
