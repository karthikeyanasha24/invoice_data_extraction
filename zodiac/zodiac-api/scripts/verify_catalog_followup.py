"""Read-only live catalog continuity check; no model calls or saved DB records."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.database import SessionLocal
from app.api.adaptive_query import _post_query_adaptive_body
from app.services import ai_native_pipeline
from app.services.investigation_budget import end_investigation


def no_model(*_args, **_kwargs):
    raise AssertionError("Catalog follow-ups must not require a model")


def main():
    # Block SDK and shared transports independently. Only DB catalog reads run.
    import httpx
    import urllib.request
    httpx.Client.send = no_model
    httpx.AsyncClient.send = no_model
    urllib.request.urlopen = no_model
    ai_native_pipeline._openai_chat = no_model
    ai_native_pipeline._gemini_chat = no_model
    context = None
    with SessionLocal() as db:
        for question in ("How many tables are there?", "list those", "count those"):
            try:
                db.execute(text("SET TRANSACTION READ ONLY"))
                result = _post_query_adaptive_body(
                    q=question, original_question=question, tableHint=None,
                    contextData=context, overrideSql=None, threadId=None,
                    investigationId="catalog-followup-verification", db=db,
                    current_user=type("ReadOnlyUser", (), {"id": 0, "is_admin": False})(),
                    agent_mode=True,
                )
                assert result["answer_status"] == "SUCCESS", result["summary"]
                assert result["meta"]["schema_source"] == "live_database_metadata", "Live catalog was unavailable"
                if question == "list those":
                    assert result["rowCount"] == expected_count
                    assert len({row["table"] for row in result["data"]}) == expected_count
                else:
                    expected_count = result["data"][0]["table_count"]
                print(f"PASS: {question} ({expected_count} tables)", flush=True)
                context = {
                    "previousQuestion": question, "previousSQL": "",
                    "previousPlan": result["query_plan"], "previousAnswerStatus": "SUCCESS",
                    "data": result["data"],
                }
            finally:
                end_investigation()
                db.rollback()


if __name__ == "__main__":
    main()
