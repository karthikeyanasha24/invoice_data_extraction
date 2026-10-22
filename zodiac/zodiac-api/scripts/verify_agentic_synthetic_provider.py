"""Real Agentic/provider acceptance tests against an isolated synthetic SQLite DB.

Never opens the configured application/SAP database. Only invented fixtures and
their schema may reach the configured model. Does not replace model responses.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
os.environ['AI_ANALYST_MAX_MODEL_CALLS'] = '12'
os.environ['AI_ANALYST_MAX_TOTAL_TOKENS'] = '110000'
os.environ['AI_ANALYST_MAX_OUTPUT_TOKENS'] = '6000'

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlglot import transpile


@event.listens_for(Engine, 'before_cursor_execute')
def only_synthetic_database(connection, cursor, statement, parameters, context, executemany):
    if connection.dialect.name != 'sqlite':
        raise RuntimeError('Synthetic acceptance test forbids application/SAP DB access')


@event.listens_for(Engine, 'do_connect')
def only_sqlite_connections(dialect, connection_record, connection_args, connection_params):
    if dialect.name != 'sqlite':
        raise RuntimeError('Synthetic acceptance test forbids non-SQLite connections')


from app.services import analyst_agent as agent
from app.services.adaptive_trusted_scope import TrustedAiExecutionScope, set_trusted_scope, reset_trusted_scope
from app.services.analyst_agent_sql import enforce_agent_user_scope
from app.services.analyst_usage import usage_summary
from app.services.agent_query_contract import output_lineage
from app.services.investigation_budget import begin_investigation, current_budget, end_investigation

FIELDS = {
    'VBAK': 'mandt vbeln bstnk audat netwr waerk',
    'VBAP': 'mandt vbeln posnr netwr kwmeng vrkme',
    'VBRK': 'mandt vbeln fkdat netwr waerk',
    'VBRP': 'mandt vbeln posnr netwr fkimg vrkme aubel aupos',
    'VBFA': 'mandt vbelv posnv vbeln posnn vbtyp_v vbtyp_n',
}
MEASURES = {'netwr', 'kwmeng', 'fkimg'}
SCHEMA = {table: [{'col': col, 'type': 'numeric' if col in MEASURES else 'text'}
                  for col in columns.split()] for table, columns in FIELDS.items()}
DATA = {
    'VBAK': [
        ('999', 'SYNTH-O-1', 'SYNTH-PO-1', '20000101', 200, 'USD'),
        ('999', 'SYNTH-O-MISSING', 'SYNTH-PO-2', '20000101', 200, 'USD'),
        ('999', 'SYNTH-O-FX', 'SYNTH-PO-3', '20000101', 200, 'USD'),
    ],
    'VBAP': [('999', 'SYNTH-O-1', '000010', 200, 10, 'EA'),
             ('999', 'SYNTH-O-FX', '000010', 200, 10, 'EA')],
    'VBRK': [('999', 'SYNTH-I-1', '20000105', 100, 'USD'),
             ('999', 'SYNTH-I-MISSING', '20000105', 100, 'USD'),
             ('999', 'SYNTH-I-FX', '20000105', 100, 'EUR')],
    'VBRP': [('999', 'SYNTH-I-1', '000010', 100, 5, 'EA', 'SYNTH-O-1', '000010'),
             ('999', 'SYNTH-I-MISSING', '000010', 100, 5, 'EA', 'SYNTH-O-MISSING', '000010'),
             ('999', 'SYNTH-I-FX', '000010', 100, 5, 'EA', 'SYNTH-O-FX', '000010')],
    'VBFA': [('999', 'SYNTH-O-1', '000010', 'SYNTH-I-1', '000010', 'C', 'M'),
             ('999', 'SYNTH-O-1', '000010', 'SYNTH-I-1', '000010', 'C', 'M')],
}
QUESTIONS = {
    'quantity': 'Why is synthetic invoice SYNTH-I-1 lower in net value than its referenced sales order? '
                'Check the linked item quantities, units and net values to distinguish quantity from price. '
                'Show both document identities and currencies and the verified supporting data.',
    'missing': 'Why is synthetic invoice SYNTH-I-MISSING different from its referenced sales order? '
               'Check item quantities and prices, retain the original order/item references when no target exists, '
               'and clearly explain any missing evidence instead of guessing a cause.',
    'currency': 'Compare the recorded net value of synthetic invoice SYNTH-I-FX with its referenced sales order. '
                'Show both document identities and currencies. Only subtract values if the currencies match; '
                'no exchange rates or currency conversion are available.',
}


def acceptance_checks(case, result):
    evidence = result.get('agent_results') or []
    bound = []
    for item in evidence:
        if item.get('kind') != 'analysis':
            continue
        lineage = {alias: {(table.upper(), column) for table, column in origins}
                   for alias, origins in output_lineage(item['sql']).items()}
        for row in item.get('rows') or []:
            bound.append((row, lineage))

    def has(table, column, value):
        return any(origins == {(table, column)} and row.get(alias) == value
                   for row, lineage in bound for alias, origins in lineage.items())

    checks = {'successful_answer': result.get('answer_status') == 'SUCCESS',
              'executed_evidence': bool(bound)}
    if case == 'quantity':
        checks.update(ordered_quantity=has('VBAP', 'kwmeng', 10), billed_quantity=has('VBRP', 'fkimg', 5),
                      order_item_value=has('VBAP', 'netwr', 200), invoice_item_value=has('VBRP', 'netwr', 100),
                      order_currency=has('VBAK', 'waerk', 'USD'), invoice_currency=has('VBRK', 'waerk', 'USD'))
        observations = ' '.join(str(value).lower() for row, _ in bound for value in row.values() if isinstance(value, str))
        checks['quantity_observation'] = 'quantit' in observations and any(word in observations for word in ('lower', 'less', 'partial', 'fewer'))
    elif case == 'missing':
        checks.update(original_order_reference=has('VBRP', 'aubel', 'SYNTH-O-MISSING'),
                      original_item_reference=has('VBRP', 'aupos', '000010'),
                      missing_target_exposed=has('VBAP', 'vbeln', None) or has('VBAP', 'posnr', None))
        checks['evidence_gap_explained'] = 'missing' in result.get('answer', '').lower()
    else:
        checks.update(order_currency=has('VBAK', 'waerk', 'USD'), invoice_currency=has('VBRK', 'waerk', 'EUR'))
        checks['no_unconverted_numeric_difference'] = all(not isinstance(row.get(alias), (int, float))
            for row, lineage in bound for alias, origins in lineage.items()
            if {table for table, column in origins if column == 'netwr'} == {'VBAK', 'VBRK'})
        checks['mismatch_explained'] = 'mismatch' in result.get('answer', '').lower()
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=list(QUESTIONS), required=True)
    args = parser.parse_args()
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        for table, cols in SCHEMA.items():
            declaration = ','.join('"%s" %s' % (col['col'], 'NUMERIC' if col['col'] in MEASURES else 'TEXT') for col in cols)
            connection.execute(text('CREATE TABLE "%s" (%s)' % (table, declaration)))
            names = [col['col'] for col in cols]
            connection.execute(text('INSERT INTO "%s" VALUES (%s)' %
                                    (table, ','.join(':'+name for name in names))),
                               [dict(zip(names, row)) for row in DATA[table]])
        connection.execute(text('PRAGMA query_only=ON'))
    executed = []
    tool_calls = []
    original_call = agent.AnalystTools.call

    def audited_call(tools, name, arguments):
        if name == 'research_public_context':
            raise RuntimeError('This isolated acceptance test permits no public research')
        result = original_call(tools, name, arguments)
        tool_calls.append({'tool': name, 'arguments': arguments, 'result': result})
        print(json.dumps({'tool': name, 'ok': result.get('ok'), 'rows': result.get('row_count'),
                          'error': result.get('error')}), flush=True)
        return result

    def execute(session, sql, question=''):
        assert current_budget().diagnostics.get('agent_read_only') is True
        scoped, params = enforce_agent_user_scope(sql, SCHEMA)
        sqlite_sql = transpile(scoped, read='postgres', write='sqlite')[0]
        rows = [dict(row) for row in session.execute(text(sqlite_sql), params).mappings()]
        executed.append({'sql': sql, 'rows': rows})
        return rows

    token = set_trusted_scope(TrustedAiExecutionScope(user_id=999, sap_access='full'))
    started = time.monotonic()
    begin_investigation(QUESTIONS[args.case], limit_s=210)
    try:
        with Session(engine) as session, \
             patch.object(agent.AnalystTools, 'schema', lambda *_: (SCHEMA, 'live_database_metadata')), \
             patch.object(agent.AnalystTools, 'call', audited_call):
            result = agent.run_analyst_agent(QUESTIONS[args.case], session, execute,
                                             schema_loader=lambda: SCHEMA, context={}, conversation=[], use_sap=False)
        report = {'case': args.case, 'synthetic_only': True, 'real_provider': True,
                  'application_database_used': False, 'elapsed_s': round(time.monotonic()-started, 2),
                  'usage': usage_summary(), 'executed': executed, 'tool_calls': tool_calls, 'result': result}
        report['checks'] = acceptance_checks(args.case, result)
        report['passed'] = all(report['checks'].values())
        report_path = Path(__file__).with_name('agentic_synthetic_%s_live_results.json' % args.case)
        report_path.write_text(json.dumps(report, default=str, indent=2), encoding='utf-8')
        print(json.dumps({'case': args.case, 'answer_status': result.get('answer_status'),
                          'failure_class': result.get('failure_class'), 'row_count': result.get('rowCount'),
                          'model_calls': len(report['usage']['calls']), 'tokens': report['usage']['total_tokens'],
                          'passed': report['passed'], 'checks': report['checks'],
                          'report': str(report_path), 'answer': result.get('answer')}), flush=True)
        if not report['passed']:
            raise SystemExit(1)
    finally:
        end_investigation()
        reset_trusted_scope(token)
        engine.dispose()


if __name__ == '__main__':
    main()
