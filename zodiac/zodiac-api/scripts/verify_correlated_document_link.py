"""Read-only acceptance check for correlated document links, without an LLM."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from sqlalchemy import text
    from app.database import SessionLocal
    from app.data_catalog.physical import column_names, resolve_table_name
    from app.services.sap_sql_precision_validator import validate_sql_precision
    from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
    from app.services.document_identity_quality import profile_document_identities, document_identity_errors

    sql = '''SELECT o.mandt, o.vbeln AS sales_order,
        CAST(NULLIF(TRIM(CAST(o.netwr AS TEXT)), '') AS NUMERIC) AS order_value,
        o.waerk AS order_currency, i.vbeln AS invoice,
        CAST(NULLIF(TRIM(CAST(i.netwr AS TEXT)), '') AS NUMERIC) AS invoice_value,
        i.waerk AS invoice_currency FROM "VBAK" o JOIN "VBRK" i ON EXISTS
        (SELECT 1 FROM "VBFA" f WHERE f.mandt=o.mandt AND f.vbelv=o.vbeln
         AND f.mandt=i.mandt AND f.vbeln=i.vbeln AND f.vbtyp_v='C' AND f.vbtyp_n='M')
        ORDER BY o.mandt, o.vbeln, i.vbeln LIMIT 200'''
    if len(sys.argv) > 1:
        from sqlglot import parse_one
        sql = parse_one(Path(sys.argv[1]).read_text(), read='postgres').limit(200).sql(dialect='postgres')
    schema = {t: column_names(resolve_table_name(t) or t) for t in ('VBAK', 'VBAP', 'VBRK', 'vbrp', 'VBFA')}
    validation = validate_sql_precision(sql, schema)
    assert validation.is_valid, validation.errors
    assert not sql_has_unsafe_monetary_fanout(sql)
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        db.execute(text("SET LOCAL statement_timeout = '60s'"))
        for table, keys in [('VBAK', 'mandt,vbeln'), ('VBRK', 'mandt,vbeln')]:
            duplicates = db.execute(text(f'SELECT {keys} FROM "{table}" GROUP BY {keys} HAVING COUNT(*)>1 LIMIT 1')).first()
            assert duplicates is None, f'{table} document identity is not unique in the connected data'
        profiles = profile_document_identities(db, list(schema), ['VBAK.netwr', 'VBRK.netwr', 'vbrp.netwr'])
        assert not document_identity_errors(sql, profiles), document_identity_errors(sql, profiles)
        rows = [dict(r) for r in db.execute(text(validation.normalized_sql)).mappings()]
        db.rollback()
    print(json.dumps({'validation': 'passed', 'execution': 'passed', 'row_count': len(rows),
                      'identity_profiles': profiles,
                      'grain': 'order and invoice currency' if len(sys.argv)>1 else 'document pairs; header values are not allocated amounts'}, default=str))


if __name__ == '__main__':
    main()
