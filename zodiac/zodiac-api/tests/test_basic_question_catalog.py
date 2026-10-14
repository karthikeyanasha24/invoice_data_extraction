"""Keep the database-tested catalog executable without model generation."""
import pytest

from app.services.basic_question_catalog import DATABASE_QUESTIONS
from app.services.basic_sql_answer import _EXAMPLE_QUESTIONS, run_basic_sql_answer


def test_fifty_new_database_questions():
    questions = [question for _, question in DATABASE_QUESTIONS]
    assert len(questions) == len(set(questions)) == 50
    assert not set(questions).intersection(_EXAMPLE_QUESTIONS)


@pytest.mark.parametrize("category,question", DATABASE_QUESTIONS)
def test_catalog_sql_passes_schema_and_readonly_validation(category, question):
    from app.api.adaptive_query import _load_schema
    from app.services.analyst_agent_sql import validate_agent_sql
    from app.services.investigation_budget import paid_models_blocked
    calls = []
    def execute(sql):
        assert paid_models_blocked()
        safe, _ = validate_agent_sql(sql, _load_schema())
        calls.append(safe)
        return {"ok": True, "sql": safe, "rows": []}
    result = run_basic_sql_answer(question, execute=execute,
        local_agent=lambda *_: pytest.fail("Catalog question must not need a model"))
    assert len(calls) == 1 and result["sql_status"] == "executed"
    assert result["llm_calls"] == 0 and result["answer_status"] == "SUCCESS_EMPTY"
