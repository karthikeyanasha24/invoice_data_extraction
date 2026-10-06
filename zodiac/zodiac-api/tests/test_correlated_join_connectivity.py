"""Correlated semi-joins must prove a document link, not just existence."""
import pytest
from pathlib import Path
from app.services.sap_sql_precision_validator import validate_sql_precision

SCHEMA = {
    "VBAK": ["mandt", "vbeln", "netwr", "waerk"],
    "VBRK": ["mandt", "vbeln", "netwr", "waerk"],
    "VBFA": ["mandt", "vbelv", "vbeln", "vbtyp_v", "vbtyp_n"],
}
LINK = '''EXISTS (SELECT 1 FROM "VBFA" f WHERE
    f.mandt=o.mandt AND f.vbelv=o.vbeln AND f.mandt=i.mandt
    AND f.vbeln=i.vbeln AND f.vbtyp_v='C' AND f.vbtyp_n='M')'''


def query(on=LINK):
    return f'''SELECT o.mandt, o.vbeln AS sales_order, o.netwr AS order_value,
        o.waerk AS order_currency, i.vbeln AS invoice, i.netwr AS invoice_value,
        i.waerk AS invoice_currency FROM "VBAK" o JOIN "VBRK" i ON {on} LIMIT 200'''


def connected(sql):
    return not any("not fully connected" in e for e in validate_sql_precision(sql, SCHEMA).errors)


def test_positive_correlated_join_exists_connects_outer_documents():
    assert validate_sql_precision(query(), SCHEMA).is_valid


def test_exists_in_conjunction_and_renamed_aliases():
    assert connected(query(f'o.mandt=i.mandt AND ({LINK})').replace('f.', 'flow.').replace('VBFA" f', 'VBFA" flow'))


@pytest.mark.parametrize('on', [
    f'{LINK} OR TRUE', f'NOT {LINK}',
    "EXISTS (SELECT 1 FROM \"VBFA\" f WHERE f.vbtyp_n='M')",
    LINK.replace('f.vbelv=o.vbeln', 'f.mandt=o.mandt').replace('f.vbeln=i.vbeln', 'f.mandt=i.mandt'),
    LINK.replace('f.vbeln=i.vbeln', '(f.vbeln=i.vbeln OR TRUE)'),
    LINK.replace('SELECT 1', 'SELECT COUNT(*)'),
    LINK.replace('"VBFA" f', '"VBFA" i').replace('f.', 'i.'),
])
def test_non_relationship_exists_does_not_connect(on):
    assert not connected(query(on))


def test_where_anti_join_does_not_require_target_in_outer_graph():
    sql = '''SELECT o.vbeln FROM "VBAK" o WHERE NOT EXISTS
        (SELECT 1 FROM "VBFA" f WHERE f.vbelv=o.vbeln)'''
    assert validate_sql_precision(sql, SCHEMA).is_valid


def test_where_exists_cannot_rescue_uncorrelated_join_on():
    assert not connected(query('TRUE').replace(' LIMIT 200', f' WHERE {LINK} LIMIT 200'))


def test_item_bridge_requires_document_and_position_keys():
    from app.services.sap_sql_precision_validator import _exists_bridge_edges
    sql = '''SELECT a.vbeln,k.vbeln FROM "VBAP" a JOIN "VBRK" k ON EXISTS
        (SELECT 1 FROM vbrp p WHERE p.aubel=a.vbeln AND p.aupos=a.posnr AND p.vbeln=k.vbeln)'''
    assert _exists_bridge_edges(sql)
    assert not _exists_bridge_edges(sql.replace('p.aubel=a.vbeln AND ', ''))


def test_identified_pair_values_do_not_aggregate_header_values():
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    assert not sql_has_unsafe_monetary_fanout(query())
    assert sql_has_unsafe_monetary_fanout(query().replace('i.netwr AS invoice_value', 'SUM(i.netwr) AS invoice_value'))
    assert sql_has_unsafe_monetary_fanout(query().replace('i.vbeln AS invoice,', ''))
    assert sql_has_unsafe_monetary_fanout(query().replace('o.netwr AS order_value', 'o.netwr-i.netwr AS difference'))
    assert sql_has_unsafe_monetary_fanout(query().replace('o.netwr AS order_value', 'o.netwr*i.netwr AS difference'))
    assert sql_has_unsafe_monetary_fanout(query().replace(' LIMIT 200', ' JOIN "VBFA" x ON x.vbelv=o.vbeln'))


def test_aggregate_filter_columns_are_input_scope_not_grouped_projection():
    from app.services.sql_structure import sql_structure_errors
    sql = 'SELECT client, COUNT(*) FILTER (WHERE amount IS NULL) n FROM items GROUP BY client'
    assert not sql_structure_errors(sql)
    assert sql_structure_errors(sql.replace('SELECT client,', 'SELECT client, amount,'))
    assert sql_structure_errors(sql.replace('COUNT(*) FILTER (WHERE amount IS NULL)',
                                           'COUNT(*) FILTER (WHERE amount IS NULL) OVER ()'))


def reconciliation():
    return (Path(__file__).parent / 'fixtures/generated_order_reconciliation.sql').read_text()


def test_item_amounts_survive_unique_header_join_then_order_aggregation():
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    assert not sql_has_unsafe_monetary_fanout(reconciliation())
    assert not sql_has_unsafe_monetary_fanout(reconciliation().replace('billing_by_order', 'arbitrary_group_name'))


@pytest.mark.parametrize('old,new', [
    ('"vbrp"."mandt" = "VBRK"."mandt"', 'TRUE'),
    ('"vbrp"."vbeln" = "VBRK"."vbeln"', '"vbrp"."vbeln" = "VBRK"."vbeln" OR TRUE'),
    ('"vbrp"."netwr" AS TEXT', '"VBRK"."netwr" AS TEXT'),
    ('"orders"."sales_order" = "billing_by_order"."sales_order"', 'TRUE'),
    ('    "billing_by_order"."invoice_currency",\n    "billing_by_order"."linked_invoice_net_value",',
     '    "billing_by_order"."linked_invoice_net_value",'),
    ('    "orders"."order_net_value",', '    SUM("orders"."order_net_value") AS order_net_value,'),
])
def test_unproven_document_grain_stays_blocked(old, new):
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    sql = reconciliation()
    assert old in sql
    assert sql_has_unsafe_monetary_fanout(sql.replace(old, new))


def test_verified_duplicates_require_row_dedup_before_aggregation():
    from app.services.document_identity_quality import document_identity_errors
    profile = {'vbrp': {'verified': True, 'keys': ['mandt','vbeln','posnr'],
                        'duplicate_identity_groups': 1, 'conflicting_identity_groups': 0}}
    sql = reconciliation()
    assert document_identity_errors(sql, profile)
    dedup = sql.replace('"linked_invoice_items" AS (\n    SELECT', '"linked_invoice_items" AS (\n    SELECT DISTINCT')
    assert not document_identity_errors(dedup, profile)
    assert document_identity_errors(sql.replace('SUM(', 'SUM(DISTINCT '), profile)
    assert document_identity_errors(dedup.replace('"vbrp"."posnr" AS "invoice_item",', ''), profile)
    profile['vbrp']['conflicting_identity_groups'] = 1
    assert document_identity_errors(dedup, profile)


def test_currency_lineage_survives_arbitrary_cte_aliases():
    from app.services.adaptive_currency_strategy import sql_groups_currency_dimension
    sql = reconciliation()
    assert sql_groups_currency_dimension(sql)
    assert sql_groups_currency_dimension(sql.replace('invoice_currency', 'bucket_unit'))
    assert not sql_groups_currency_dimension(sql.replace('"VBRK"."waerk"', '"VBRK"."vbtyp"'))


def test_currency_repair_preserves_existing_inner_aggregation(monkeypatch):
    from app.services.four_stage_db_pipeline import _apply_currency_if_needed, VerifiedDbContext
    sql = reconciliation()
    assert _apply_currency_if_needed('Compare document net values', sql, VerifiedDbContext('Compare document net values'), None) == sql


def test_independent_facts_use_dynamic_sql_without_an_inexpressible_flat_plan(monkeypatch):
    from app.services import four_stage_db_pipeline as pipeline
    ctx = pipeline.VerifiedDbContext('Compare two sources', columns=['VBAK.netwr','VBRK.netwr'])
    monkeypatch.setattr(pipeline, 'pipeline3_sql_generation', lambda *a, **kw: '')
    monkeypatch.setattr(pipeline, 'build_structured_query_plan', lambda *a, **kw: pytest.fail('flat plan cannot declare independent scopes'))
    pipeline.pipeline25_query_plan(ctx.question, ctx)
    assert ctx.pipeline_log['QUERY_PLAN']['source'] == 'dynamic_sql_multi_measure'


def test_independent_cte_lineage_full_join_requires_all_keys():
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    sql = (Path(__file__).parent / 'fixtures/generated_independent_order_reconciliation.sql').read_text()
    assert not sql_has_unsafe_monetary_fanout(sql)
    assert sql_has_unsafe_monetary_fanout(sql.replace('AND "o"."currency" = "i"."currency"', ''))
    assert sql_has_unsafe_monetary_fanout(sql.replace('ON "o"."mandt" = "i"."mandt"', 'ON TRUE'))


def test_identity_profile_is_metadata_driven_and_reports_conflicts(monkeypatch):
    from contextlib import nullcontext
    from app.services import document_identity_quality as quality
    monkeypatch.setattr(quality, '_load_schema_ai_config', lambda: {'document_identity_rules': {
        'ORDERS': {'keys': ['CLIENT','ORDER_ID'], 'attributes': ['NETWR','CURRENCY']}}})
    monkeypatch.setattr(quality, 'resolve_table_name', lambda t: t)
    monkeypatch.setattr(quality, 'column_names', lambda t: ['client','order_id','netwr','currency'])
    class Result:
        def mappings(self): return self
        def one(self): return {'duplicate_identity_groups': 2, 'extra_rows': 3, 'conflicting_identity_groups': 1}
    class Db:
        def begin_nested(self): return nullcontext()
        def execute(self, sql):
            assert 'FROM "ORDERS"' in str(sql)
            return Result()
    profile = quality.profile_document_identities(Db(), ['ORDERS'], ['ORDERS.netwr'])['ORDERS']
    assert profile['verified'] and profile['keys'] == ['client','order_id']
    assert profile['conflicting_identity_groups'] == 1
    class FailedDb(Db):
        def execute(self, sql): raise RuntimeError('internal connection detail')
    failed = quality.profile_document_identities(FailedDb(), ['ORDERS'], ['ORDERS.netwr'])['ORDERS']
    assert not failed['verified']
    assert 'internal connection detail' not in str(failed)
