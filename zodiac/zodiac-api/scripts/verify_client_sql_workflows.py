"""Read-only local SQL acceptance against the configured SAP extract.

Uses the existing staff user's actual execution scope. Does not persist chats,
training examples, or database changes. Never calls any model provider.
The local report can contain the requested invoice's records; it is git-ignored.
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user-email', required=True)
    parser.add_argument('--invoice', required=True)
    parser.add_argument('--metadata-only', action='store_true')
    parser.add_argument('--basic-replay', action='store_true', help='Also rerun the existing saved 1999 comparison without models')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', encoding='utf-8-sig', override=True)
    from sqlalchemy import text
    from app.database import SessionLocal
    from app.services.adaptive_analyst.live_schema import load_live_schema
    from app.services.adaptive_trusted_scope import analyst_scope_for_user, set_trusted_scope, reset_trusted_scope
    from app.api.adaptive_query import _execute_sql

    report = {'database_writes': False, 'model_calls': 0, 'cases': []}
    output = Path(__file__).with_name('client_sql_workflows_live_results.json')
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        user = db.execute(text('SELECT id,is_admin,is_customer_user FROM zodiac_users WHERE lower(email)=lower(:email) AND is_active'),
                          {'email': args.user_email}).mappings().one()
        user = SimpleNamespace(**dict(user))
        if user.is_customer_user and not user.is_admin:
            raise SystemExit('This standalone staff acceptance runner does not bypass customer workspace assignments.')
        scope = analyst_scope_for_user(user)
        scope_token = set_trusted_scope(scope)
        try:
            schema, origin = load_live_schema(db, {})
            if origin != 'live_database_metadata':
                raise SystemExit('Connected schema could not be verified')
            report['schema'] = {t: len(c) for t, c in schema.items()}
            print(f'CATALOG: {len(schema)} tables, {sum(map(len, schema.values()))} columns', flush=True)
            # Independent header/item inspection provides an oracle for the
            # requested invoice, preserving its leading zeros and physical case.
            index = {t.lower(): t for t in schema}
            quote = db.get_bind().dialect.identifier_preparer.quote
            for name, wanted in [('vbrk', 'mandt vbeln fkdat netwr waerk knumv'),
                                 ('vbrp', 'mandt vbeln posnr aubel aupos netwr fkimg vrkme netpr kpein kmein')]:
                table = index.get(name)
                if not table:
                    continue
                columns = {c['col'].lower(): c['col'] for c in schema[table]}
                fields = [quote(columns[c]) for c in wanted.split() if c in columns]
                report.setdefault('independent_invoice_evidence', {})[table] = [dict(r) for r in db.execute(
                    text(f'SELECT {", ".join(fields)} FROM {quote(table)} WHERE {quote(columns["vbeln"])}=:invoice LIMIT 200'),
                    {'invoice': args.invoice}).mappings()]
            item_table = index.get('vbrp')
            for name, wanted, join in [
                ('vbak', 'mandt vbeln audat netwr waerk knumv', 'o.mandt=p.mandt AND o.vbeln=p.aubel'),
                ('vbap', 'mandt vbeln posnr netwr kwmeng vrkme netpr kpein kmein', 'o.mandt=p.mandt AND o.vbeln=p.aubel AND o.posnr=p.aupos'),
                ('vbkd', 'mandt vbeln posnr prsdt', 'o.mandt=p.mandt AND o.vbeln=p.aubel'),
                ('vbap', 'mandt vbeln posnr netwr kwmeng vrkme netpr kpein kmein', 'o.mandt=p.mandt AND o.vbeln=p.aubel'),
            ]:
                table = index.get(name)
                if not table or not item_table:
                    continue
                columns = {c['col'].lower(): c['col'] for c in schema[table]}
                fields = [f'o.{quote(columns[c])}' for c in wanted.split() if c in columns]
                label = 'all_order_items' if name == 'vbap' and 'aupos' not in join else table
                report.setdefault('independent_order_evidence', {})[label] = [dict(r) for r in db.execute(
                    text(f'SELECT {", ".join(fields)} FROM {quote(item_table)} p LEFT JOIN {quote(table)} o '
                         f'ON {join} WHERE p.vbeln=:invoice LIMIT 200'), {'invoice': args.invoice}).mappings()]
            db.rollback()
            if not args.metadata_only:
                from app.services.analyst_agent import AnalystTools
                tools = AnalystTools(db, _execute_sql, lambda: schema, manual_sql_training=True)
                header_sql = (ROOT / 'scripts/sql/sap_order_invoice_pairs.sql').read_text()
                amount = lambda alias: f"CAST(NULLIF(TRIM(CAST({alias}.netwr AS TEXT)), '') AS NUMERIC)"
                invoice_literal = "'" + args.invoice.replace("'", "''") + "'"
                item_sql = f'''WITH order_base AS (
                    SELECT o.mandt,o.vbeln AS order_no,o.posnr AS order_item,{amount('o')} AS order_net_value,h.waerk AS order_currency
                    FROM "VBAP" o JOIN "VBAK" h ON h.mandt=o.mandt AND h.vbeln=o.vbeln),
                    invoice_base AS (SELECT i.mandt,i.vbeln AS invoice_no,i.posnr AS invoice_item,{amount('i')} AS invoice_net_value,r.waerk AS invoice_currency
                    FROM {quote(item_table)} i JOIN "VBRK" r ON r.mandt=i.mandt AND r.vbeln=i.vbeln),
                    non_monetary_link AS (SELECT DISTINCT f.mandt,f.vbelv AS ref_order_no,f.posnv AS ref_order_item,
                    f.vbeln AS invoice_no,f.posnn AS invoice_item FROM "VBFA" f WHERE f.vbtyp_n='M' AND f.vbtyp_v='C')
                    SELECT l.mandt,l.ref_order_no AS order_no,l.ref_order_item AS order_item,l.invoice_no,l.invoice_item,
                    o.order_net_value,o.order_currency,i.invoice_net_value,i.invoice_currency,
                    CASE WHEN o.order_currency=i.invoice_currency THEN o.order_net_value-i.invoice_net_value ELSE NULL END AS difference
                    FROM non_monetary_link l JOIN order_base o ON o.mandt=l.mandt AND o.order_no=l.ref_order_no AND o.order_item=l.ref_order_item
                    JOIN invoice_base i ON i.mandt=l.mandt AND i.invoice_no=l.invoice_no AND i.invoice_item=l.invoice_item
                    WHERE l.invoice_no={invoice_literal} LIMIT 200'''
                aggregate_sql = item_sql.replace(f"{amount('o')} AS order_net_value", f"SUM({amount('o')}) AS order_net_value").replace(
                    'AND h.vbeln=o.vbeln)', 'AND h.vbeln=o.vbeln GROUP BY o.mandt,o.vbeln,o.posnr,h.waerk)')
                reference_sql = f'''WITH links AS (SELECT DISTINCT p.mandt,p.vbeln,p.aubel FROM {quote(item_table)} p)
                    SELECT b.mandt AS client,b.vbeln AS invoice_no,l.mandt AS linked_client,l.aubel AS linked_order_reference,
                    o.vbeln AS order_no,{amount('o')} AS order_net_value,{amount('b')} AS invoice_net_value,
                    o.waerk AS order_currency,b.waerk AS invoice_currency,
                    CASE WHEN o.waerk=b.waerk THEN {amount('o')}-{amount('b')} ELSE NULL END AS difference
                    FROM "VBRK" b LEFT JOIN links l ON l.mandt=b.mandt AND l.vbeln=b.vbeln
                    LEFT JOIN "VBAK" o ON o.mandt=l.mandt AND o.vbeln=l.aubel
                    WHERE b.vbeln={invoice_literal} LIMIT 200'''
                missing_item_sql = f'''SELECT p.mandt,p.vbeln AS invoice_no,p.posnr AS invoice_item,
                    p.aubel AS linked_order_reference,p.aupos AS linked_order_item,
                    o.vbeln AS order_no,o.posnr AS order_item,{amount('p')} AS invoice_item_net_value,
                    {amount('o')} AS order_item_net_value,b.waerk AS invoice_currency,h.waerk AS order_currency,
                    CASE WHEN o.vbeln IS NULL THEN 'Referenced sales order item is absent from this extract'
                    ELSE 'Linked item is present; compare recorded quantities and prices' END AS observed_difference
                    FROM {quote(item_table)} p JOIN "VBRK" b ON b.mandt=p.mandt AND b.vbeln=p.vbeln
                    LEFT JOIN "VBAK" h ON h.mandt=p.mandt AND h.vbeln=p.aubel
                    LEFT JOIN "VBAP" o ON o.mandt=p.mandt AND o.vbeln=p.aubel AND o.posnr=p.aupos
                    WHERE p.vbeln={invoice_literal} LIMIT 200'''
                from app.services.investigation_budget import begin_investigation, end_investigation
                for name, sql in [('headers_1999', header_sql), ('item_flow', item_sql), ('aggregated_item_flow', aggregate_sql),
                                  ('header_reference', reference_sql), ('missing_item_reference', missing_item_sql)]:
                    begin_investigation('Read-only client SQL acceptance')
                    try:
                        result = tools.call('run_readonly_sql', {'source': 'application', 'sql': sql, 'purpose': 'Verify client comparison SQL'})
                        report['cases'].append({'case': name, 'ok': result.get('ok'), 'rows': result.get('row_count'),
                                                'error': result.get('error'), 'sql': result.get('sql'), 'data': result.get('rows')})
                        print(f'{name}: ok={result.get("ok")}, rows={result.get("row_count")}, error={result.get("error")}', flush=True)
                    finally:
                        end_investigation()
                        db.rollback()
                if args.basic_replay:
                    from sqlalchemy import select
                    from app.services.analyst_drilldown import scope_digest
                    from app.services.basic_sql_training import examples, load_replay_example
                    from app.services.basic_sql_answer import run_basic_sql_answer
                    wording = 'Identify the difference in the sales amount for order value and invoice value from the year 1999'
                    stored = db.execute(select(examples.c.id, examples.c.revision).where(
                        examples.c.user_id == scope.user_id, examples.c.scope_digest == scope_digest(scope),
                        examples.c.question == wording, examples.c.source == 'application')).mappings().one()
                    begin_investigation('Read-only saved comparison acceptance')
                    try:
                        example = load_replay_example(db.get_bind(), scope, stored['id'], stored['revision'], wording, False)
                        def execute_saved(sql, step):
                            return tools.call('run_readonly_sql', {'source': step['source'], 'sql': sql,
                                                                 'purpose': 'Verify selected checked SQL replay'})
                        result = run_basic_sql_answer(wording, execute=execute_saved, selected_training_example=example,
                                                      local_agent=lambda *_: (_ for _ in ()).throw(RuntimeError('Model calls forbidden')))
                        passed = result['answer_status'].startswith('SUCCESS') and result['llm_calls'] == 0
                        report['cases'].append({'case': 'selected_basic_replay', 'ok': passed, 'rows': result['rowCount'],
                                                'model_calls': result['llm_calls'], 'retrieval': result['meta'].get('retrieval'),
                                                'error': None if passed else result.get('answer')})
                        print(f'selected_basic_replay: ok={passed}, rows={result["rowCount"]}, model_calls={result["llm_calls"]}', flush=True)
                        from app.services.basic_rag import load_basic_examples, retrieve_examples
                        prior_examples = load_basic_examples(db.get_bind(), scope, False)
                        candidates = retrieve_examples(wording, prior_examples, use_embeddings=False)
                        selected = next((item for item in candidates if item.get('reusable')), {})
                        report['typed_basic_match'] = {key: selected.get(key) for key in
                                                       ('source', 'training_example', 'training_example_id', 'training_revision', 'retrieval')}
                        print(f'typed_basic_match: {report["typed_basic_match"]}', flush=True)
                        def execute_typed(sql, step):
                            if not step.get('training_example'):
                                raise RuntimeError('Typed replay lost its training provenance')
                            return execute_saved(sql, step)
                        typed = run_basic_sql_answer(wording, execute=execute_typed, prior_examples=prior_examples,
                                                      local_agent=lambda *_: (_ for _ in ()).throw(RuntimeError('Model calls forbidden')))
                        passed = typed['answer_status'].startswith('SUCCESS') and typed['llm_calls'] == 0
                        report['cases'].append({'case': 'typed_basic_replay', 'ok': passed, 'rows': typed['rowCount'],
                                                'model_calls': typed['llm_calls'],
                                                'error': None if passed else typed.get('answer')})
                        print(f'typed_basic_replay: ok={passed}, rows={typed["rowCount"]}, model_calls={typed["llm_calls"]}', flush=True)
                    finally:
                        end_investigation()
                        db.rollback()
                tools.close()
            output.write_text(json.dumps(report, default=str, indent=2), encoding='utf-8')
        finally:
            reset_trusted_scope(scope_token)
            db.rollback()
    print(f'Report: {output}', flush=True)
    return int(any(not c.get('ok') for c in report['cases']))


if __name__ == '__main__':
    raise SystemExit(main())
