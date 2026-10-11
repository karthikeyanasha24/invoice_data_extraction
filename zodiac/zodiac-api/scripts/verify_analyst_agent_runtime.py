"""Real DB tools + scripted model decisions. No external model calls or DB writes.

This proves execution/routing, not the intelligence of a funded live model.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.api.adaptive_query import _post_query_adaptive_body
from app.services import analyst_agent
from app.services.investigation_budget import end_investigation


def call(name, arguments, identifier):
    return SimpleNamespace(output=[{"type": "function_call", "call_id": identifier, "name": name,
                                    "arguments": json.dumps(arguments)}], output_text="")


def answer(kind, ids):
    body = {"kind": kind, "answer": "The requested result is shown below.",
            "summary": "Verified catalog or database result.", "result_ids": ids, "followups": []}
    return SimpleNamespace(output=[], output_text=json.dumps(body))


def main():
    import httpx
    import urllib.request
    def no_network(*_a, **_k):
        raise RuntimeError("External model transport is disabled during local verification")
    httpx.Client.send = no_network
    httpx.AsyncClient.send = no_network
    urllib.request.urlopen = no_network
    logging.basicConfig(level=logging.ERROR)
    cases = [
        ("catalog count", "How many tables are there?", [
            call("list_tables", {"source": "business", "name_filter": None, "include_names": False, "limit": None}, "catalog"),
            answer("metadata", ["result_1"]),
        ]),
        ("referential listing", "list those", [
            call("list_tables", {"source": "business", "name_filter": None, "include_names": True, "limit": None}, "listing"),
            answer("metadata", ["result_1"]),
        ]),
        ("schema inspection", "Describe VBRK columns", [
            call("describe_tables", {"source": "business", "tables": ["VBRK"], "column_filter": None}, "columns"),
            answer("metadata", ["result_1"]),
        ]),
        ("SQL validation and recovery", "How many rows are in VBRK?", [
            call("run_readonly_sql", {"source": "business", "sql": 'SELECT nonexistent_column FROM "VBRK"', "purpose": "Count rows in VBRK"}, "invalid"),
            call("run_readonly_sql", {"source": "business", "sql": 'SELECT COUNT(*) AS record_count FROM "VBRK"', "purpose": "Count rows in VBRK"}, "revised"),
            answer("analysis", ["result_1"]),
        ]),
    ]
    report, context = [], None
    with SessionLocal() as db:
        for label, question, sequence in cases:
            decisions = iter(sequence)
            analyst_agent.create_agent_response = lambda **_: next(decisions)
            started = time.monotonic()
            try:
                result = _post_query_adaptive_body(
                    q=question, original_question=question, tableHint=None,
                    contextData=context, overrideSql=None, threadId=None,
                    investigationId="agent-runtime-verification", db=db,
                    current_user=type("ReadOnlyVerificationUser", (), {"id": 0, "is_admin": False})(),
                    agent_mode=True,
                )
                assert result["answer_status"] == "SUCCESS", result.get("answer")
                assert result["pipeline"] == "analyst_agent"
                trace = result["query_plan"]["agent_trace"]
                if label == "SQL validation and recovery":
                    assert [step["status"] for step in trace] == ["error", "completed"]
                    assert result["sql_status"] == "executed" and result["rowCount"] == 1
                if label == "catalog count":
                    catalog_count = result["data"][0]["table_count"]
                if label == "referential listing":
                    assert result["rowCount"] == catalog_count
                report.append({"case": label, "status": "PASS", "seconds": round(time.monotonic()-started, 2), "tool_trace": trace})
                context = {"previousQuestion": question, "previousSQL": result["sql"],
                           "previousPlan": result["query_plan"], "previousAnswerStatus": result["answer_status"], "data": result["data"]}
                print("PASS:", label, flush=True)
            finally:
                end_investigation()
                db.rollback()
    output = {"scripted_model_decisions": True, "external_model_transport_disabled": True,
              "database_writes": False, "cases": report}
    Path(__file__).with_name("analyst_agent_runtime_report.json").write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
