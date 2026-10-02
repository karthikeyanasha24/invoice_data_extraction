"""Read-only verification using the configured database and optional live models.

Run from zodiac-api: python scripts/verify_analyst_chat.py [--live-models]
No credentials, row samples, or model answers are written to the report.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text
from app.database import SessionLocal, get_sap_session
from app.config.config import USE_SAP_DB_FOR_AI
from app.services.sql_generation_sanitizers import sanitize_generated_sap_sql
from app.services.investigation_budget import begin_investigation, end_investigation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-models', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    report = []
    db = get_sap_session() if USE_SAP_DB_FOR_AI else SessionLocal()
    try:
        query = "SELECT TRIM(COALESCE(CAST(42.5 AS NUMERIC), '0')) AS value"
        result = db.execute(text(sanitize_generated_sap_sql(query))).scalar()
        db.rollback()
        report.append({'case': 'nested numeric TRIM on PostgreSQL', 'passed': result == '42.5'})

        if args.live_models:
            from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator
            from app.api.adaptive_query import _execute_sql, _load_schema
            previous = {}
            questions = [
                ('remember a preference', 'My name is Mira. Please keep your answers to two sentences in this chat.'),
                ('recall and general knowledge', 'What name did I give you, and what is an API?'),
                ('flexible coding answer', 'Write a Python function that squares a number.'),
                ('database query', 'Show the products with the highest profits.'),
                ('database follow-up', 'Show only the top 3 from that result.'),
            ]
            for case, question in questions:
                budget = begin_investigation(question)
                started = time.monotonic()
                try:
                    result = run_adaptive_orchestrator(
                        question, db, _execute_sql, use_sap=bool(USE_SAP_DB_FOR_AI),
                        get_sap_session=get_sap_session, schema_for_metadata=_load_schema(),
                        prior_question=previous.get('question', ''), prior_sql=previous.get('sql', ''),
                        prior_plan=previous.get('query_plan'), prior_rows=previous.get('data', []),
                        prior_status=previous.get('answer_status', ''),
                    )
                    success = result.get('answer_status') == 'SUCCESS'
                    answer = str(result.get('summary') or result.get('answer') or '')
                    if case == 'recall and general knowledge':
                        success = success and 'mira' in answer.lower() and not result.get('sql')
                    elif case == 'flexible coding answer':
                        success = success and 'def ' in answer and not result.get('sql')
                    elif case == 'database query':
                        success = success and bool(result.get('sql')) and bool(result.get('data'))
                    elif case == 'database follow-up':
                        success = success and len(result.get('data') or []) == 3
                    report.append({
                        'case': case, 'passed': success, 'answer_status': result.get('answer_status'),
                        'mode': result.get('mode'), 'row_count': result.get('rowCount', 0),
                        'latency_s': round(time.monotonic() - started, 2),
                        'stages': budget.public_status()['stages'],
                    })
                    previous = {**result, 'question': question}
                except Exception as exc:
                    report.append({'case': case, 'passed': False, 'error_type': type(exc).__name__})
                finally:
                    end_investigation()
                    db.rollback()
    finally:
        db.close()
    output = Path(__file__).with_name('analyst_chat_verification.json')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for case in report:
        print(f"{'PASS' if case['passed'] else 'FAIL'}: {case['case']} ({case.get('latency_s', 0)}s)")
    return 0 if all(case['passed'] for case in report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
