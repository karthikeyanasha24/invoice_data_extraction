"""Join validation must inspect relational predicates, not comparisons in output expressions."""

from app.services.sap_sql_precision_validator import validate_sql_precision
from app.services.schema_loader import load_schema_from_mapping_file
from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout


def test_currency_case_expression_is_not_misread_as_vbak_vbrk_join():
    sql = '''
    WITH order_invoice_links AS (
        SELECT mandt, vbelv AS order_number, vbeln AS invoice_number
        FROM "VBFA" WHERE vbtyp_v = 'C' AND vbtyp_n = 'M'
        UNION
        SELECT mandt, aubel AS order_number, vbeln AS invoice_number
        FROM "VBRP" WHERE NULLIF(TRIM(CAST(aubel AS TEXT)), '') IS NOT NULL
    )
    SELECT h.mandt, h.vbeln, i.vbeln,
           CASE WHEN h.waerk = i.waerk THEN i.netwr - h.netwr END AS difference
    FROM "VBAK" h
    LEFT JOIN order_invoice_links l
      ON h.mandt = l.mandt AND h.vbeln = l.order_number
    LEFT JOIN "VBRK" i
      ON l.mandt = i.mandt AND l.invoice_number = i.vbeln
    '''

    result = validate_sql_precision(
        sql, load_schema_from_mapping_file(),
        question="Compare sales orders and linked invoices net values",
    )

    assert not any("Join keys for VBAK <-> VBRK" in error for error in result.errors)
    # Fixing the false join-key diagnosis must not make a row-expanding header
    # comparison safe: an order can have multiple linked billing documents.
    assert sql_has_unsafe_monetary_fanout(sql)


def test_direct_vbak_vbrk_currency_only_join_remains_rejected():
    sql = '''
    SELECT h.vbeln, i.vbeln
    FROM "VBAK" h
    JOIN "VBRK" i ON h.waerk = i.waerk
    '''

    result = validate_sql_precision(sql, load_schema_from_mapping_file())

    assert any("Join keys for VBAK <-> VBRK" in error for error in result.errors)
