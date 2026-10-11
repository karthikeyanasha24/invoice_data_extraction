"""Live model + connected DB smoke check; no writes or printed business records.

Unlike verify_analyst_agent_runtime.py, this sends tool evidence to the configured
OpenAI model. It uses the existing application connections and read-only SQL.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", encoding="utf-8-sig", override=True)

from app.database import SessionLocal
from app.api.adaptive_query import _post_query_adaptive_body
from app.services import analyst_agent
from app.services.investigation_budget import end_investigation


def main():
    from sqlglot import exp, parse_one
    original_tool_call = analyst_agent.AnalystTools._call
    def approved_tools(self, name, arguments):
        if name == "run_readonly_sql":
            tree = parse_one(arguments["sql"], read="postgres")
            expression = tree.expressions[0] if isinstance(tree, exp.Select) and len(tree.expressions) == 1 else None
            expression = expression.this if isinstance(expression, exp.Alias) else expression
            tables = list(tree.find_all(exp.Table))
            allowed = (isinstance(expression, exp.Count) and isinstance(expression.this, exp.Star)
                       and len(tables) == 1 and tables[0].name.lower() == "vbrk"
                       and not any(tree.args.get(key) for key in ["where", "group", "having", "joins", "with", "with_"])
                       and not any(tree.find_all(exp.Subquery)))
            if not allowed:
                raise ValueError("Approval for this live check permits only SELECT COUNT(*) FROM VBRK. Individual business records cannot be read or sent.")
        return original_tool_call(self, name, arguments)
    analyst_agent.AnalystTools._call = approved_tools
    logging.basicConfig(level=logging.ERROR)
    cases = [
        ("general conversation", "Hi, what can you help me with?", "general_chat"),
        ("live catalog count", "How many tables are there?", "database_metadata"),
        ("catalog followup", "List those.", "database_metadata"),
        ("live SQL", "How many rows are in VBRK?", "database_analysis"),
        ("general topic after SQL", "What is generative AI? Explain briefly.", "general_chat"),
    ]
    report, context, catalog_count = [], None, None
    with SessionLocal() as db:
        for label, question, expected_mode in cases:
            started = time.monotonic()
            try:
                result = _post_query_adaptive_body(
                    q=question, original_question=question, tableHint=None,
                    contextData=context, overrideSql=None, threadId=None,
                    investigationId="agent-live-smoke-check", db=db,
                    current_user=type("ReadOnlyVerificationUser", (), {"id": 0, "is_admin": False})(),
                    agent_mode=True,
                )
                trace = result.get("query_plan", {}).get("agent_trace", [])
                successful = str(result.get("answer_status", "")).startswith("SUCCESS")
                checks = {
                    "successful": successful,
                    "agent_pipeline": result.get("pipeline") == "analyst_agent",
                    "expected_mode": result.get("mode") == expected_mode,
                }
                if expected_mode == "general_chat":
                    checks["no_sql"] = not result.get("sql")
                if expected_mode == "database_metadata":
                    checks["catalog_tool_used"] = any(step.get("tool") == "list_tables" and step.get("status") in {"completed", "cached"} for step in trace)
                    if label == "live catalog count":
                        rows = result.get("data") or []
                        catalog_count = rows[0].get("table_count") if rows else None
                        checks["grounded_count"] = isinstance(catalog_count, int) and catalog_count > 0
                    else:
                        checks["followup_matches_count"] = catalog_count is not None and result.get("rowCount") == catalog_count
                if expected_mode == "database_analysis":
                    checks["sql_executed"] = result.get("sql_status") == "executed" and bool(result.get("sql"))
                    checks["aggregate_result"] = result.get("rowCount") == 1
                passed = all(checks.values())
                report.append({"case": label, "status": "PASS" if passed else "FAIL",
                               "seconds": round(time.monotonic() - started, 2),
                               "answer_status": result.get("answer_status"), "mode": result.get("mode"),
                               "checks": checks, "tool_trace": trace,
                               "service_issue": result.get("meta", {}).get("service_issue")})
                print(("PASS: " if passed else "FAIL: ") + label, flush=True)
                if not passed:
                    break
                context = {"previousQuestion": question, "previousSQL": result.get("sql", ""),
                           "previousPlan": result.get("query_plan", {}),
                           "previousAnswerStatus": result.get("answer_status"), "data": result.get("data", [])}
            finally:
                end_investigation()
                db.rollback()
    output = {"live_model_decisions": True, "database_evidence_sent_to_configured_provider": True,
              "database_writes": False, "cases": report}
    Path(__file__).with_name("analyst_agent_live_report.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    if len(report) != len(cases) or any(item["status"] != "PASS" for item in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
