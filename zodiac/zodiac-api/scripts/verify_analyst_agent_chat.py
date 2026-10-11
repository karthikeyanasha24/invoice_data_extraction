"""Live conversation smoke check with all database tools disabled.

No database connection, schema, rows, or saved analytical context is loaded.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", encoding="utf-8-sig", override=True)
from app.services import analyst_agent as agent


def main():
    original = agent.AnalystTools.call
    def conversation_tools(self, name, arguments):
        if name != "calculate":
            return {"ok": False, "error": "Database access is disabled for this conversation-only check."}
        return original(self, name, arguments)
    def no_database(*_args, **_kwargs):
        raise AssertionError("This check cannot access a database")
    agent.AnalystTools.call = conversation_tools
    report, context = [], None
    try:
        for question in ["Hi, what can you help me with?", "What is generative AI? Explain in one sentence."]:
            result = agent.run_analyst_agent(question, None, no_database, schema_loader=no_database, context=context)
            passed = result.get("answer_status") == "SUCCESS" and result.get("mode") == "general_chat" and not result.get("sql")
            report.append({"question": question, "status": "PASS" if passed else "FAIL",
                           "mode": result.get("mode"), "answer_status": result.get("answer_status"),
                           "answer": result.get("answer"), "llm_calls": result.get("llm_calls")})
            print(json.dumps(report[-1]), flush=True)
            if not passed:
                break
            context = {"previousQuestion": question, "previousPlan": result.get("query_plan"),
                       "previousAnswerStatus": result.get("answer_status")}
    finally:
        agent.AnalystTools.call = original
    output = {"live_model_decisions": True, "database_access_disabled": True,
              "database_evidence_sent": False, "cases": report}
    Path(__file__).with_name("analyst_agent_chat_report.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    if len(report) != 2 or any(item["status"] != "PASS" for item in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
