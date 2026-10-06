"""Run real, read-only analyst acceptance turns using configured OpenAI and DB.

Writes diagnostic evidence locally; credentials are never printed.
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from app.database import SessionLocal
    from app.api.adaptive_query import _execute_sql
    from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator

    logging.basicConfig(filename=ROOT / 'scripts/adaptive_conversation_acceptance.log',
                        level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
    questions = sys.argv[1:] or ['Compare sales orders and linked invoices net values',
                                'What does this result mean? Explain it clearly.']
    prior = {}
    report = []
    with SessionLocal() as db:
        for question in questions:
            result = run_adaptive_orchestrator(question, db, _execute_sql, **prior)
            report.append({'question': question, 'result': result})
            rows = result.get('data') or result.get('rows') or []
            print(json.dumps({'question': question, 'mode': result.get('mode'),
                              'status': result.get('status'), 'error': result.get('error'),
                              'row_count': len(rows), 'answer': result.get('answer'),
                              'meta': result.get('meta')}, default=str), flush=True)
            (ROOT / 'scripts/adaptive_conversation_acceptance.json').write_text(
                json.dumps(report, indent=2, default=str), encoding='utf-8')
            prior = {'prior_question': question, 'prior_sql': result.get('sql') or '',
                     'prior_plan': result.get('query_plan') or {}, 'prior_rows': rows,
                     'prior_status': result.get('answer_status') or result.get('status') or ''}


if __name__ == '__main__':
    main()
