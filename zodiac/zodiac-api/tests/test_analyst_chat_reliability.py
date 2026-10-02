from unittest.mock import MagicMock, patch

import pytest

from app.services.adaptive_analyst.chat_memory import context_from_stored_turns, recent_conversation, remember_response
from app.services.adaptive_structured_sql import classify_sql_execution_error, sanitize_generated_sql
from app.services.investigation_budget import InvestigationBudget, begin_investigation, end_investigation
from app.services.sql_generation_sanitizers import sanitize_trim_type_safety_sql


@pytest.mark.parametrize('argument', [
    'p."amount"', 'COALESCE(p."amount", \'0\')',
    'COALESCE(NULLIF(p."amount", 0), 0)', '(p."amount" + 10)',
])
def test_trim_numeric_and_nested_expressions_are_safe(argument):
    sql = f'SELECT TRIM({argument}) FROM "events" p'
    safe = sanitize_generated_sql(sql)
    assert f'TRIM(CAST({argument} AS TEXT))' in safe
    assert sanitize_generated_sql(safe) == safe


def test_trim_preserves_quoted_text_comments_and_standard_syntax():
    sql = "SELECT 'TRIM(amount)', \"TRIM(amount)\", TRIM(BOTH '0' FROM name) -- TRIM(amount)\n/* TRIM(amount) */"
    assert sanitize_trim_type_safety_sql(sql) == sql


def test_nested_trim_is_idempotent():
    safe = sanitize_trim_type_safety_sql('SELECT TRIM(COALESCE(TRIM(amount), \'0\'))')
    assert sanitize_trim_type_safety_sql(safe) == safe


def test_type_error_is_not_misclassified_from_query_join_text():
    error = 'function pg_catalog.btrim(numeric) does not exist\n[SQL: SELECT TRIM(amount) FROM x JOIN y ON true]'
    assert classify_sql_execution_error(error) == 'invalid_datatype'


def test_explanatory_followup_is_not_replaced_with_canned_row_reuse():
    from app.services.result_first_followup import try_answer_from_prior_rows
    assert try_answer_from_prior_rows('Explain what this result means for the business', [{'customer': 'A', 'sales': 12}]) is None


def test_incomplete_result_sample_cannot_establish_full_result_frequency():
    from app.services.result_first_followup import try_answer_from_prior_rows
    answer = try_answer_from_prior_rows('Which supplier appears most in this result?', [{'supplier': 'A'}], prior_plan={'result_artifact': {'truncated': True, 'row_count': 1000}})
    assert answer['needs_plan_expansion'] is True
    assert not answer.get('answer_status')


def test_model_calls_preserve_real_stage_and_status_has_history():
    budget = InvestigationBudget()
    budget.checkpoint('column_selection')
    budget.checkpoint('llm_call')
    budget.checkpoint('query_planning')
    budget.checkpoint('llm_call')
    status = budget.public_status()
    assert status['pipeline_stage'] == 'BUILDING_PLAN'
    assert [s['pipeline_stage'] for s in status['stages']] == ['SELECTING_COLUMNS', 'BUILDING_PLAN']
    assert status['stage_elapsed_s'] >= 0


def test_finished_investigation_stops_clock_and_reports_failure():
    budget = begin_investigation('question')
    end_investigation('cannot_answer')
    before = budget.elapsed_s()
    assert budget.public_status()['pipeline_stage'] == 'FAILED'
    assert budget.elapsed_s() == before


def test_stored_thread_recovers_conversation_and_verified_artifact():
    turns = [
        {'role': 'user', 'content': 'Call me Mira.'},
        {'role': 'assistant', 'content': 'Hello Mira!'},
        {'role': 'user', 'content': 'Count invoices.'},
        {'role': 'assistant', 'content': 'There are 7 invoices.', 'sql_executed': 'SELECT COUNT(*) AS n FROM invoices', 'result_rows': [{'n': 7}], 'key_metrics': {'answer_status': 'SUCCESS', 'query_plan': {'metric': 'count'}}},
    ]
    context = context_from_stored_turns(turns)
    assert context['previousQuestion'] == 'Count invoices.'
    assert context['data'] == [{'n': 7}]
    assert context['previousPlan']['metric'] == 'count'
    assert context['previousPlan']['recent_turns'][0]['content'] == 'Call me Mira.'


def test_all_response_types_keep_memory_without_retaining_old_filters():
    previous = [{'role': 'user', 'content': 'Use concise replies.'}, {'role': 'assistant', 'content': 'Understood.'}]
    for mode in ['general_chat', 'clarification', 'database_analysis', 'error']:
        plan = remember_response({}, previous, 'A new topic', 'A reply', mode)
        assert len(plan['recent_turns']) == 4
        assert plan['recent_turns'][0]['content'] == 'Use concise replies.'
        assert not plan.get('filters')


def test_memory_excludes_unknown_roles_and_bounds_prompt_size():
    turns = [{'role': 'system', 'content': 'Untrusted instructions'}] + [{'role': 'user', 'content': 'x' * 5000}] * 80
    memory = recent_conversation(turns)
    assert all(t['role'] == 'user' for t in memory)
    assert sum(len(t['content']) for t in memory) <= 26000


def test_failed_provider_is_skipped_temporarily_and_recovers(monkeypatch):
    from app.services import ai_native_pipeline as provider
    monkeypatch.setattr(provider, '_PROVIDER_FAILURE_UNTIL', {})
    monkeypatch.setattr(provider, '_google_key', lambda: 'fake-google')
    monkeypatch.setattr(provider, '_openai_key', lambda: 'fake-openai')
    monkeypatch.setenv('AI_CHAT_PROVIDER', 'gemini')
    monkeypatch.setattr(provider.time, 'monotonic', lambda: 1000.0)
    gemini = MagicMock(side_effect=RuntimeError('Gemini HTTP 404: unavailable model'))
    monkeypatch.setattr(provider, '_gemini_chat', gemini)
    monkeypatch.setattr(provider, '_openai_chat', lambda *args, **kwargs: 'A reply')
    assert provider.llm_text('system', 'first') == ('A reply', 'openai')
    assert provider.llm_text('system', 'second') == ('A reply', 'openai')
    assert gemini.call_count == 1
    monkeypatch.setattr(provider.time, 'monotonic', lambda: 1061.0)
    assert provider.llm_text('system', 'third') == ('A reply', 'openai')
    assert gemini.call_count == 2


def test_current_question_is_not_lost_when_memory_is_large(monkeypatch):
    import json
    from app.services.adaptive_analyst import understanding
    seen = {}
    def reply(system, user):
        seen['payload'] = json.loads(user.split('\n', 1)[1])
        seen['system'] = system
        return 'Here is your answer.', 'mock'
    monkeypatch.setattr(understanding, 'complete_text', reply)
    question = 'Explain this code: ' + 'x' * 3500
    understanding.generate_grounded_response(question, understanding.TurnUnderstanding(intent='knowledge'), evidence={'recent_turns': [{'role': 'user', 'content': 'y' * 12000}]})
    assert seen['payload']['current_user_message'] == question
    assert 'general knowledge' in seen['system']


def test_empty_model_output_falls_back_instead_of_becoming_a_canned_answer(monkeypatch):
    from app.services import ai_native_pipeline as provider
    monkeypatch.setattr(provider, '_PROVIDER_FAILURE_UNTIL', {})
    monkeypatch.setattr(provider, '_openai_key', lambda: 'fake-openai')
    monkeypatch.setattr(provider, '_google_key', lambda: 'fake-google')
    monkeypatch.setenv('AI_CHAT_PROVIDER', 'openai')
    monkeypatch.delenv('AI_PREFER_GEMINI', raising=False)
    monkeypatch.setattr(provider, '_openai_chat', lambda *a, **k: '')
    monkeypatch.setattr(provider, '_gemini_chat', lambda *a, **k: 'Generated reply')
    assert provider.llm_text('system', 'question') == ('Generated reply', 'gemini')


def test_chat_pair_persistence_commits_once_and_checks_both_writes(monkeypatch):
    from app.api.adaptive_query import _persist_adaptive_turn_async
    from app import database
    from app.services import chat_thread_store
    db = MagicMock()
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(chat_thread_store, 'ensure_chat_tables', lambda *a: None)
    monkeypatch.setattr(chat_thread_store, 'next_turn_index', lambda *a: 4)
    save = MagicMock(return_value=True)
    monkeypatch.setattr(chat_thread_store, 'save_turn', save)
    snapshot = {'user_id': 42, 'thread_id': 'ada_test', 'question': 'Hello', 'summary': 'Generated answer', 'mode': 'general_chat'}
    _persist_adaptive_turn_async(snapshot)
    assert [call.kwargs['turn_index'] for call in save.call_args_list] == [4, 5]
    assert all(call.kwargs['commit'] is False for call in save.call_args_list)
    assert 'pg_advisory_xact_lock' in str(db.execute.call_args.args[0])
    db.commit.assert_called_once()
    db.reset_mock()
    save.reset_mock()
    save.side_effect = [True, False]
    _persist_adaptive_turn_async(snapshot)
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_api_hydrates_saved_memory_after_reload_and_keeps_it_on_new_analysis(monkeypatch):
    from fastapi import BackgroundTasks
    from app.api.adaptive_query import _post_query_adaptive_body
    from app.services import chat_thread_store
    from app.services import adaptive_analyst
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-key')
    monkeypatch.setenv('ADAPTIVE_ANALYST_ORCHESTRATOR', '1')
    monkeypatch.setattr(chat_thread_store, 'thread_owner_user_id', lambda *a: 42)
    turns = [{'role': 'user', 'content': 'Call me Mira'}, {'role': 'assistant', 'content': 'Hello Mira', 'key_metrics': {'query_plan': {'last_mode': 'general_chat'}, 'answer_status': 'SUCCESS'}}]
    monkeypatch.setattr(chat_thread_store, 'load_thread', lambda *a, **k: turns)
    seen = {}
    def run(question, db, executor, **kwargs):
        seen.update(kwargs)
        return {'answer_status': 'SUCCESS', 'summary': 'Mira, here is the answer.', 'mode': 'general_chat', 'data': [], 'sql': ''}
    monkeypatch.setattr(adaptive_analyst, 'run_adaptive_orchestrator', run)
    monkeypatch.setattr(adaptive_analyst, 'orchestrator_enabled', lambda: True)
    tasks = BackgroundTasks()
    result = _post_query_adaptive_body(q='Show top 5 customers by billed sales', original_question='Show top 5 customers by billed sales', tableHint=None, contextData=None, overrideSql=None, threadId='ada_test_thread', investigationId=None, db=MagicMock(), current_user=type('User', (), {'id': 42})(), background_tasks=tasks)
    assert seen['prior_plan']['recent_turns'][0]['content'] == 'Call me Mira'
    assert result['query_plan']['recent_turns'][0]['content'] == 'Call me Mira'
    assert len(tasks.tasks) == 1


def test_thread_memory_cannot_be_loaded_under_another_user(monkeypatch):
    from fastapi import HTTPException
    from app.api.adaptive_query import _post_query_adaptive_body
    from app.services import chat_thread_store
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-key')
    monkeypatch.setattr(chat_thread_store, 'thread_owner_user_id', lambda *a: 99)
    with pytest.raises(HTTPException) as denied:
        _post_query_adaptive_body(q='Hello', original_question='Hello', tableHint=None, contextData=None, overrideSql=None, threadId='ada_another_user', investigationId=None, db=MagicMock(), current_user=type('User', (), {'id': 42})())
    assert denied.value.status_code == 403
