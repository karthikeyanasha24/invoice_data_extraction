"""Validate all catalog questions without model calls or database writes.

Use --live-db for actual read-only execution. The report records result shape,
never row values, connection strings, or credentials.
"""
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-db", action="store_true")
    parser.add_argument("--question", action="append", default=[])
    parser.add_argument("--user-id", type=int, default=1, help="Application user scope for this developer verification run (default: 1)")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True, encoding="utf-8-sig")
    import httpx
    def blocked(*_a, **_k):
        raise RuntimeError("Model and HTTP transports disabled during catalog verification")
    httpx.Client.send = blocked
    logging.disable(logging.CRITICAL)
    from sqlalchemy import text
    from app.database import SessionLocal, get_sap_session
    from app.config.config import USE_SAP_DB_FOR_AI
    from app.api.adaptive_query import _execute_sql, _load_schema
    from app.services.analyst_agent import AnalystTools, _analysis_issues
    from app.services.analyst_agent_sql import validate_agent_sql
    from app.services.basic_question_catalog import DATABASE_QUESTIONS
    from app.services.basic_sql_answer import run_basic_sql_answer
    from app.services.adaptive_trusted_scope import TrustedAiExecutionScope, set_trusted_scope, reset_trusted_scope
    from app.services.investigation_budget import begin_investigation, end_investigation

    questions = DATABASE_QUESTIONS
    if args.question:
        wanted = set(args.question)
        questions = [item for item in DATABASE_QUESTIONS if item[1] in wanted]
        missing = wanted.difference(item[1] for item in questions)
        if missing:
            raise SystemExit("Unknown catalog question: " + ", ".join(sorted(missing)))
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "live_database": args.live_db,
              "model_calls": 0, "database_writes": False, "cases": []}
    schema = _load_schema()
    # Developer-only verification uses an explicit application identity and staff
    # SAP scope. Dashboard requests always use their authenticated user's scope.
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=args.user_id, sap_access="full"))
    try:
        for category, question in questions:
            db = SessionLocal() if args.live_db else None
            executor = None
            case = {"category": category, "question": question}
            begin_investigation(question)
            try:
                if db:
                    executor = AnalystTools(db, _execute_sql, _load_schema, use_sap=USE_SAP_DB_FOR_AI,
                                            sap_session_factory=get_sap_session, question=question)
                    source = "business" if USE_SAP_DB_FOR_AI else "application"
                    executor.session(source).execute(text("SET statement_timeout = '20s'"))
                def execute(sql):
                    safe, _ = validate_agent_sql(sql, schema)
                    case["sql_sha256"] = hashlib.sha256(safe.encode()).hexdigest()
                    if not executor:
                        return {"ok": True, "sql": safe, "rows": []}
                    result = executor.call("run_readonly_sql", {"source": source,
                        "sql": safe, "purpose": "Verify predefined database question"})
                    if not result.get("ok"):
                        case["error"] = str(result.get("error") or "Rejected")[:500]
                    elif result.get("rows"):
                        issues = _analysis_issues(question, result)
                        if issues:
                            case["issues"] = issues
                            return {**result, "ok": False}
                    return result
                result = run_basic_sql_answer(question, execute=execute)
                rows = result.get("data") or []
                case.update(status=result.get("answer_status"), executed=result.get("sql_status") == "executed",
                            row_count=len(rows) if args.live_db else None,
                            columns=list(rows[0]) if rows else [], model_calls=result.get("llm_calls", 0))
                if not result.get("sql"):
                    case["error"] = "No deterministic query available"
            except Exception as error:
                case.update(status="ERROR", error_type=type(error).__name__, executed=False)
            finally:
                if executor: executor.close()
                if db: db.rollback(); db.close()
                end_investigation()
            report["cases"].append(case)
            print(f'{len(report["cases"]):02} {case["status"]}: {question}', flush=True)
    finally:
        reset_trusted_scope(token)
    report["passed"] = sum(case.get("executed", False) and case.get("model_calls") == 0
                           and case.get("status") in {"SUCCESS", "EMPTY"}
                           and not case.get("error") and not case.get("issues")
                           for case in report["cases"])
    path = ROOT / ("scripts/basic_catalog_subset_report.json" if args.question else "scripts/basic_catalog_report.json")
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f'{report["passed"]}/{len(questions)} passed; report: {path}')
    return 0 if report["passed"] == len(questions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
