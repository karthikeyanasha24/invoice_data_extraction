"""Literal-only Responses readiness probe. Sends no schema or database records."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
import openai  # Load SDK before starting the short network-probe deadline.

from app.services.analyst_agent import _FINAL_SCHEMA
from app.services.analyst_agent_provider import create_agent_response
from app.services.adaptive_analyst.understanding import technical_understanding_failure
from app.services.investigation_budget import begin_investigation, end_investigation


def main():
    begin_investigation("Literal-only provider readiness probe", limit_s=30)
    try:
        response = create_agent_response(
            instructions="Return the required JSON with kind=conversation, answer=OK, summary=OK, result_ids=[], followups=[].",
            input=[{"role": "user", "content": "Reply OK."}], tools=[], output_schema=_FINAL_SCHEMA,
        )
        value = json.loads(response.output_text)
        assert value["answer"] == "OK"
        report = {"ready": True, "api": "responses", "database_data_sent": False}
    except Exception as error:
        failure = technical_understanding_failure("Literal-only readiness probe", error)
        cause = error
        while cause.__cause__ is not None:
            cause = cause.__cause__
        report = {"ready": False, "api": "responses", "database_data_sent": False,
                  "issue": failure["meta"]["service_issue"], "error_type": type(cause).__name__,
                  "http_status": getattr(cause, "status_code", None), "code": getattr(cause, "code", None)}
    finally:
        end_investigation()
    print(json.dumps(report), flush=True)
    Path(__file__).with_name("analyst_agent_provider_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
