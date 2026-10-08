"""Read-only mixed-question acceptance against configured model and database.

Does not run background persistence, write DB records, or save database rows.
Run from zodiac-api with Python; writes a credential-free test report.
"""
from __future__ import annotations
import argparse, json, logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from fastapi import BackgroundTasks
from sqlalchemy import text, inspect
from app.database import SessionLocal
from app.api.adaptive_query import _post_query_adaptive_body
from app.services.investigation_budget import end_investigation

CASES = [
    ('numeric arithmetic', 'What is 2 plus 2?', 'calc', '4'),
    ('mistyped arithmetic', 'whst i2 plus 2', 'calc', '4'),
    ('general explanation', 'Explain what an API is in simple language.', 'general', 'api'),
    ('coding', 'Write a Python function that squares a number.', 'general', 'def '),
    ('topic change after coding', 'What is 0.1 + 0.2?', 'calc', '0.3'),
    ('percentage calculation', '15 percent of 240', 'calc', '36'),
    ('table count', 'How many tables are there?', 'metadata', None),
    ('schema description', 'Describe the VBRK table columns.', 'metadata', None),
    ('sales order count', 'How many sales orders are there?', 'count', 'VBAK'),
    ('billed invoice count', 'How many billed invoices are there?', 'count', 'VBRK'),
    ('customer ranking', 'Show top 5 customers by billed sales.', 'ranking', None),
    ('database follow-up', 'Show only the top 3 from that result.', 'followup', None),
    ('arithmetic after database result', 'Compute (12 + 8) / 5', 'calc', '4'),
    ('division by zero', 'Calculate 5 / 0', 'undefined', None),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-db-only', action='store_true', help='Disable both external model transports; keep all database results local.')
    args = parser.parse_args()
    if args.local_db_only:
        from app.services import ai_native_pipeline
        def no_external_model(*args, **kwargs):
            raise RuntimeError('External model transport disabled for local database verification')
        # Legacy paths can create SDK clients directly. Disable HTTP sends as
        # well as shared providers so database results cannot reach any model.
        import httpx, urllib.request, openai
        httpx.Client.send = no_external_model
        httpx.AsyncClient.send = no_external_model
        urllib.request.urlopen = no_external_model
        openai.OpenAI = no_external_model
        ai_native_pipeline._openai_chat = no_external_model
        ai_native_pipeline._gemini_chat = no_external_model
    logging.basicConfig(level=logging.ERROR)
    db = SessionLocal()
    report = []
    ctx = None
    history = []
    user = type('ReadOnlyVerificationUser', (), {'id': 0})()
    try:
        # The configured database is also the SAP extract in this deployment.
        names = inspect(db.bind).get_table_names()
        print('Database connectivity: OK; table_count:', len(names), flush=True)
        for label, question, kind, expected in CASES:
            started = time.monotonic()
            reference = None
            if kind == 'count' and expected in names:
                reference = int(db.execute(text('SELECT COUNT(DISTINCT (TRIM(CAST(mandt AS TEXT)), TRIM(CAST(vbeln AS TEXT)))) FROM "' + expected + '" WHERE NULLIF(TRIM(CAST(vbeln AS TEXT)), \'\') IS NOT NULL')).scalar())
                db.rollback()
            try:
                # A READ ONLY transaction provides an independent DB write guard.
                db.execute(text('SET TRANSACTION READ ONLY'))
                result = _post_query_adaptive_body(
                    q=question, original_question=question, tableHint=None, contextData=ctx,
                    overrideSql=None, threadId=None, investigationId=None, db=db,
                    current_user=user, conversation_history=history, background_tasks=BackgroundTasks(),
                )
                status = str(result.get('answer_status') or '')
                mode = str(result.get('mode') or '')
                answer = str(result.get('answer') or result.get('summary') or '')
                rows = result.get('data') or []
                issue = (result.get('meta') or {}).get('service_issue')
                passed = status in {'SUCCESS', 'SUCCESS_EMPTY'}
                if kind == 'calc': passed = passed and (result.get('meta') or {}).get('value') == expected and not result.get('sql')
                elif kind == 'undefined': passed = passed and 'undefined' in answer and not result.get('sql')
                elif kind == 'general': passed = passed and mode == 'general_chat' and expected in answer.lower() and not result.get('sql')
                elif kind == 'metadata': passed = passed and mode == 'database_metadata' and ('vbrk' in answer.lower() if 'VBRK' in question else str(len(names)) in answer)
                elif kind == 'count':
                    values = [str(v) for row in rows for v in row.values()]
                    passed = passed and reference is not None and str(reference) in values and bool(result.get('sql'))
                elif kind == 'ranking':
                    if rows and all('rank_within_currency' in row for row in rows):
                        groups = {}
                        for row in rows: groups.setdefault(str(row.get('currency') or ''), []).append(row)
                        passed = passed and all(len(group) <= 5 and all(int(row['rank_within_currency']) <= 5 for row in group) for group in groups.values()) and 'per currency' in answer.lower() and bool(result.get('sql'))
                    else:
                        passed = passed and 0 < len(rows) <= 5 and bool(result.get('sql'))
                elif kind == 'followup': passed = passed and len(rows) == 3
                blocked = not passed and issue in {'quota_exhausted', 'rate_limited', 'model_unavailable', 'provider_configuration'}
                entry = {'case':label,'question':question,'passed':passed,'outcome':'PASS' if passed else 'BLOCKED' if blocked else 'FAIL',
                         'answer_status':status,'mode':mode,'row_count':len(rows),'service_issue':issue,
                         'seconds':round(time.monotonic()-started,2),'sql_executed':bool(result.get('sql')), 'sql':result.get('sql') or '', 'error':result.get('error'), 'error_kind':result.get('error_kind'), 'failure_class':result.get('failure_class'), 'column_names':list(rows[0]) if rows else [], 'validation_warnings':(result.get('meta') or {}).get('validation_warnings')}
                history.extend([{'role':'user','content':question},{'role':'assistant','content':answer}])
                ctx={'previousQuestion':question,'previousSQL':result.get('sql') or '',
                     'previousPlan':result.get('query_plan') or {},'previousAnswerStatus':status,'data':rows}
            except Exception as exc:
                entry={'case':label,'question':question,'passed':False,'outcome':'FAIL','error_type':type(exc).__name__,
                       'seconds':round(time.monotonic()-started,2)}
            finally:
                end_investigation()
                db.rollback()
            report.append(entry)
            print(entry['outcome'],label,entry.get('answer_status',''),str(entry['seconds'])+'s',flush=True)
    finally:
        db.close()
    output={'external_model_transport_disabled': args.local_db_only, 'counts':{k:sum(r['outcome']==k for r in report) for k in ('PASS','BLOCKED','FAIL')},'cases':report}
    Path(__file__).with_name('adaptive_local_runtime_report.json' if args.local_db_only else 'adaptive_mixed_runtime_report.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output['counts']),flush=True)
    return 0 if all(r['passed'] for r in report) else 1

if __name__=='__main__':
    raise SystemExit(main())
