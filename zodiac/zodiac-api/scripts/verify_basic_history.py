"""Replay Andy's saved questions with zero model API calls. Optional read-only DB run."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-db", action="store_true")
    args = parser.parse_args()
    import httpx
    from app.services.basic_sql_answer import run_basic_sql_answer
    from app.services.analyst_agent_sql import validate_agent_sql
    from app.api.adaptive_query import _load_schema, _execute_sql
    from app.services.analyst_agent import AnalystTools
    from app.services.adaptive_trusted_scope import TrustedAiExecutionScope, set_trusted_scope, reset_trusted_scope
    from app.services.investigation_budget import begin_investigation, end_investigation
    from app.database import SessionLocal, get_sap_session
    from app.config.config import USE_SAP_DB_FOR_AI
    from sqlalchemy import text

    def blocked(*_a, **_k):
        raise RuntimeError("All model transports are disabled in this replay")
    httpx.Client.send = blocked
    logging.basicConfig(level=logging.ERROR)
    questions = [row["question"] for row in json.loads((ROOT / "andy_live_verify_results.json").read_text(encoding="utf-8"))["results"]]
    questions += ["total billed sales in 2001", "billed sales by customer in 2001", "billed sales by month in 2001"]
    schema = _load_schema()
    report = {"model_calls": 0, "live_database_attempted": args.live_db, "live_database": False, "database_writes": False, "cases": []}
    scope_token = set_trusted_scope(TrustedAiExecutionScope(user_id=1, sap_access="full"))
    db = SessionLocal() if args.live_db else None
    try:
        if args.live_db:
            connection = get_sap_session() if USE_SAP_DB_FOR_AI else db
            try:
                connection.execute(text("SELECT 1"))
                connection.rollback()
                report["live_database"] = True
            except Exception as error:
                report["database_unavailable"] = type(error).__name__
                args.live_db = False
            finally:
                if connection is not db:
                    connection.close()
        for question in questions:
            started = time.monotonic()
            begin_investigation(question)
            executor = AnalystTools(db, _execute_sql, _load_schema, use_sap=USE_SAP_DB_FOR_AI,
                                    sap_session_factory=get_sap_session, question=question) if args.live_db else None
            def execute(sql):
                if executor:
                    return executor.call("run_readonly_sql", {"source": "business" if USE_SAP_DB_FOR_AI else "application",
                                                               "sql": sql, "purpose": "Read-only historical Basic replay"})
                safe, _ = validate_agent_sql(sql, schema)
                return {"ok": True, "sql": safe, "rows": []}
            try:
                result = run_basic_sql_answer(question, execute=execute)
                verdict = "NEEDS_TAUGHT_QUERY_OR_MODEL" if not result.get("sql") and result.get("mode") == "general_chat" else (
                    "LIVE_EXECUTED" if args.live_db and result.get("sql_status") == "executed" else
                    "SQL_VALIDATED_ONLY" if result.get("sql_status") == "executed" else "REJECTED")
                report["cases"].append({"question": question, "verdict": verdict,
                    "answer_status": result["answer_status"] if args.live_db else "NOT_EXECUTED",
                    "rows": result.get("rowCount", 0) if args.live_db else None,
                    "model_calls": result.get("llm_calls", 0), "seconds": round(time.monotonic()-started, 2)})
            except Exception as error:
                report["cases"].append({"question": question, "verdict": "REJECTED", "error_type": type(error).__name__})
            finally:
                if executor:
                    executor.close()
                if db:
                    db.rollback()
                end_investigation()
        from collections import Counter
        report["counts"] = dict(Counter(row["verdict"] for row in report["cases"]))
    finally:
        if db:
            db.close()
        reset_trusted_scope(scope_token)
    path = ROOT / "scripts" / "basic_history_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"counts": report.get("counts"), "database_unavailable": report.get("database_unavailable"),
                      "report": str(path)}))


if __name__ == "__main__":
    main()
