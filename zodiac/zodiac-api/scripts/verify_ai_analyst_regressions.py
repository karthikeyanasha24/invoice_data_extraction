"""Read-only, real-model verification of the reported AI Analyst failures.

Run from zodiac-api: python scripts/verify_ai_analyst_regressions.py
Use --cases schema,ranking,year,documents to select independent conversations.
The report contains SQL and aggregate diagnostics, but no credentials or rows.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
SCENARIOS = {
    "schema": [
        "Which table and field store the billing document number?",
        "Which date and amount fields are available for billing documents?",
    ],
    "ranking": [
        "Show the top five countries by billed sales in the latest complete year available in the data",
        "Which country was highest in that result?",
        "For that country, show billed sales by year for the last five complete years available.",
    ],
    "year": [
        "Show total billed sales and billing-document count by calendar year.",
    ],
    "documents": [
        "Show the ten most negative billed documents, with document number, customer, date, and amount.",
        "For those same documents, include the linked sales orders if the data supports that link.",
    ],
    "customer": [
        "Show the top five customers by billed sales in the latest complete year available in the data.",
        "Show the top ten billing documents behind the leading customer's total.",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=",".join(SCENARIOS))
    parser.add_argument("--debug", action="store_true", help="show backend warning diagnostics")
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.WARNING)
    else:
        logging.disable(logging.CRITICAL)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.api.adaptive_query import _post_query_adaptive_body

    url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not url:
        print("DATABASE_URL is not configured.")
        return 1
    engine = create_engine(
        url.replace("postgresql+asyncpg://", "postgresql://"),
        connect_args={"connect_timeout": 5, "options": "-c default_transaction_read_only=on"},
    )
    reports = []
    for name in args.cases.split(","):
        if name not in SCENARIOS:
            parser.error(f"Unknown case {name}")
        previous = None
        db = sessionmaker(bind=engine)()
        try:
            for question in SCENARIOS[name]:
                started = time.monotonic()
                context = None
                if previous:
                    context = {
                        "previousQuestion": previous["question"],
                        "previousSQL": previous.get("sql") or "",
                        "previousPlan": previous.get("query_plan") or {},
                        "previousAnswerStatus": previous.get("answer_status"),
                        "data": previous.get("data") or [],
                    }
                result = _post_query_adaptive_body(
                    q=question, original_question=question, tableHint=None,
                    contextData=context, overrideSql=None, threadId=None,
                    investigationId=None, db=db, current_user=None,
                    conversation_history=None, new_question=False,
                )
                rows = result.get("data") or []
                plan = result.get("query_plan") or {}
                report = {
                    "scenario": name, "question": question,
                    "status": result.get("answer_status"),
                    "sql_status": result.get("sql_status"),
                    "row_count": result.get("rowCount"),
                    "columns": list(rows[0]) if rows else [],
                    "latency_s": round(time.monotonic() - started, 2),
                    "summary": result.get("summary"),
                    "sql": result.get("sql"),
                    "resolved_question": result.get("resolved_question"),
                    "verified_context": plan.get("verified_db_context"),
                    "pipeline_log": plan.get("pipeline_log"),
                    "validation_warnings": (result.get("meta") or {}).get("validation_warnings"),
                    "diagnostics": {
                        key: result.get(key)
                        for key in ("mode", "type", "failure_class", "error_kind", "error_class", "pipeline", "pipeline_stage")
                        if result.get(key) is not None
                    },
                    "meta": result.get("meta"),
                    "detail": result.get("detail"),
                }
                reports.append(report)
                print(json.dumps({k: report[k] for k in (
                    "scenario", "question", "status", "sql_status", "row_count", "columns", "latency_s", "summary"
                )}, default=str), flush=True)
                previous = {**result, "question": question}
                db.rollback()
        except Exception as exc:
            reports.append({"scenario": name, "status": "ERROR", "error_type": type(exc).__name__})
            print(f"{name}: {type(exc).__name__}", flush=True)
        finally:
            db.close()
    output = Path(__file__).with_name("ai_analyst_regression_verification.json")
    output.write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
    return 0 if all(r.get("status") == "SUCCESS" for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
