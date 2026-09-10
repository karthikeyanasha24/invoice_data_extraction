"""Run QA battery via direct pipeline (no HTTP — avoids blocked API server)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.adaptive_query import _execute_sql
from app.database import SessionLocal
from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator
from app.services.four_stage_db_pipeline import run_four_stage_database_query

QUESTIONS = [
    ("multidim_ranking", "Which country, customer, and industry has the highest sales?", "four_stage"),
    ("top_customers", "Top 5 customers by billed sales", "four_stage"),
    ("top_materials", "Top 20 materials by billed quantity", "four_stage"),
    ("sales_by_year", "Show sales by year", "four_stage"),
    ("customers_industries", "Customers and industries with billed revenue", "four_stage"),
    ("negative_sales", "show me negatives sales for the year 2000", "four_stage"),
    ("customer_names", "Show customer names only", "four_stage"),
    ("sat_logs", "Show SAT processing logs", "four_stage"),
    ("data_limitation", "What is our profit margin?", "orchestrator"),
    ("general_chat", "ahi hello", "orchestrator"),
]


def run_four_stage(q: str) -> dict:
    db = SessionLocal()
    try:
        return run_four_stage_database_query(q, db, _execute_sql)
    finally:
        db.close()


def run_orch(q: str) -> dict:
    db = SessionLocal()
    try:
        return run_adaptive_orchestrator(q, db, _execute_sql)
    finally:
        db.close()


def check(label: str, q: str, out: dict) -> bool:
    if label == "general_chat":
        return out.get("mode") == "general_chat" or "hello" in str(out.get("answer") or out.get("summary") or "").lower()
    if label == "data_limitation":
        return str(out.get("mode") or "").lower() in {"data_limitation", "cannot_answer"} or str(out.get("answer_status") or "") == "CANNOT_ANSWER" or out.get("error") == "data_limitation"
    if label == "negative_sales":
        sql = (out.get("sql") or "").upper()
        rows = out.get("rows") or []
        return not out.get("error") and len(rows) > 0 and "GROUP BY" not in sql
    if label == "multidim_ranking":
        return not out.get("error") and len(out.get("rows") or []) > 0
    return not out.get("error") and out.get("error") != "data_limitation"


def main() -> int:
    passed = failed = 0
    for label, question, engine in QUESTIONS:
        print(f"\n=== [{label}] {question}")
        try:
            out = run_orch(question) if engine == "orchestrator" else run_four_stage(question)
            err = out.get("error")
            rows = len(out.get("rows") or out.get("data") or [])
            sql = (out.get("sql") or "")[:150]
            log = out.get("pipeline_log") or {}
            src = (log.get("PIPELINE_3_SQL_GENERATION") or {}).get("source", "")
            print(f"  error={err} rows={rows} source={src}")
            print(f"  sql={sql}...")
            ok = check(label, question, out)
            print(f"  => {'PASS' if ok else 'FAIL'}")
            if ok:
                passed += 1
            else:
                failed += 1
                if out.get("detail"):
                    print(f"  detail={out.get('detail')}")
        except Exception as exc:
            print(f"  EXCEPTION: {exc}")
            print("  => FAIL")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
