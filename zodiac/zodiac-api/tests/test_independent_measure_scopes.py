"""Different monetary facts may be compared only after proven aggregation."""
import pytest
from app.services.sql_grain_guard import sql_has_unsafe_monetary_fanout
from app.services.sap_sql_precision_validator import validate_sql_precision
from app.services.schema_loader import load_schema_from_mapping_file


def comparison(order_group='waerk', invoice_group='waerk', join='a.currency = b.currency', outer='a.amount, b.amount'):
    return f'''
    WITH x AS (
        SELECT waerk AS currency, {"kunnr AS customer," if ',' in order_group else ''}
               SUM(netwr) AS amount FROM "VBAK" GROUP BY {order_group}
    ), y AS (
        SELECT waerk AS currency, {"kunag AS customer," if ',' in invoice_group else ''}
               SUM(netwr) AS amount FROM "VBRK"
        WHERE EXISTS (SELECT 1 FROM "VBFA" f WHERE f.vbeln = "VBRK".vbeln)
        GROUP BY {invoice_group}
    ) SELECT {outer} FROM x a FULL JOIN y b ON {join}
    '''


def test_independent_header_sums_and_exists_links_are_safe():
    assert not sql_has_unsafe_monetary_fanout(comparison())


def test_independent_header_totals_with_correlated_document_flow_filter_are_safe():
    sql = '''
    WITH order_rows AS (
        SELECT h.mandt, h.vbeln, h.waerk AS currency, h.netwr AS net_value
        FROM "VBAK" h
    ), invoice_rows AS (
        SELECT i.mandt, i.vbeln, i.waerk AS currency, i.netwr AS net_value
        FROM "VBRK" i
        WHERE EXISTS (
            SELECT 1 FROM "VBFA" f
            JOIN "VBAK" h ON h.mandt = f.mandt AND h.vbeln = f.vbelv
            WHERE f.mandt = i.mandt AND f.vbeln = i.vbeln
              AND f.vbtyp_v = 'C' AND f.vbtyp_n = 'M'
        )
    ), order_totals AS (
        SELECT mandt, currency, COUNT(*) AS order_count,
               SUM(net_value) AS order_net_value
        FROM order_rows GROUP BY mandt, currency
    ), invoice_totals AS (
        SELECT mandt, currency, COUNT(*) AS invoice_count,
               SUM(net_value) AS invoice_net_value
        FROM invoice_rows GROUP BY mandt, currency
    )
    SELECT o.mandt, i.mandt, o.currency, i.currency,
           o.order_count, i.invoice_count, o.order_net_value,
           i.invoice_net_value, o.order_net_value - i.invoice_net_value AS change,
           CASE WHEN o.order_count IS NULL THEN 'invoice only'
                WHEN i.invoice_count IS NULL THEN 'order only'
                ELSE 'matched' END AS comparison_status
    FROM order_totals o FULL OUTER JOIN invoice_totals i
      ON o.mandt = i.mandt AND o.currency = i.currency
    '''
    assert not sql_has_unsafe_monetary_fanout(sql)


def test_linked_invoice_cte_aggregate_with_coalesced_group_keys_is_safe():
    sql = '''
    WITH order_rows AS (
        SELECT h.mandt, h.vbeln, h.waerk,
               CAST(NULLIF(TRIM(CAST(h.netwr AS TEXT)), '') AS NUMERIC) AS net_value
        FROM "VBAK" h
    ), linked_invoice_rows AS (
        SELECT i.mandt, i.vbeln, i.waerk,
               CAST(NULLIF(TRIM(CAST(i.netwr AS TEXT)), '') AS NUMERIC) AS net_value
        FROM "VBRK" i
        WHERE EXISTS (
            SELECT 1 FROM "VBFA" f
            INNER JOIN order_rows o
              ON o.mandt = f.mandt AND o.vbeln = f.vbelv
            WHERE f.mandt = i.mandt AND f.vbeln = i.vbeln
              AND f.vbtyp_v = 'C' AND f.vbtyp_n = 'M'
        )
    ), order_totals AS (
        SELECT mandt, waerk, COUNT(*) AS sales_order_count,
               SUM(net_value) AS sales_order_net_value
        FROM order_rows GROUP BY mandt, waerk
    ), invoice_totals AS (
        SELECT mandt, waerk, COUNT(*) AS linked_invoice_count,
               SUM(net_value) AS linked_invoice_net_value
        FROM linked_invoice_rows GROUP BY mandt, waerk
    )
    SELECT COALESCE(o.mandt, i.mandt) AS client,
           COALESCE(o.waerk, i.waerk) AS currency,
           o.sales_order_count, i.linked_invoice_count,
           o.sales_order_net_value, i.linked_invoice_net_value,
           o.sales_order_net_value - i.linked_invoice_net_value AS change,
           CASE WHEN o.sales_order_count IS NULL THEN 'Invoices only'
                WHEN i.linked_invoice_count IS NULL THEN 'Orders only'
                ELSE 'Matched' END AS comparison_status,
           COALESCE(o.mandt, i.mandt) IS NULL AS missing_client,
           COALESCE(o.waerk, i.waerk) IS NULL AS missing_currency
    FROM order_totals o FULL OUTER JOIN invoice_totals i
      ON o.mandt = i.mandt AND o.waerk = i.waerk
    '''
    assert not sql_has_unsafe_monetary_fanout(sql)
    validation = validate_sql_precision(sql, load_schema_from_mapping_file())
    assert validation.is_valid, validation.errors


def test_independent_header_totals_still_require_every_grouping_key():
    sql = '''
    WITH order_totals AS (
        SELECT mandt, waerk AS currency, kunnr, SUM(netwr) AS amount
        FROM "VBAK" GROUP BY mandt, waerk, kunnr
    ), invoice_totals AS (
        SELECT mandt, waerk AS currency, kunag AS customer, SUM(netwr) AS amount
        FROM "VBRK" GROUP BY mandt, waerk, kunag
    )
    SELECT o.amount, i.amount FROM order_totals o
    FULL OUTER JOIN invoice_totals i
      ON o.mandt = i.mandt AND o.currency = i.currency
    '''
    assert sql_has_unsafe_monetary_fanout(sql)


def test_arbitrary_cte_names_do_not_determine_safety():
    sql = comparison().replace('x AS', 'first_measure AS').replace('y AS', 'second_measure AS')
    sql = sql.replace('FROM x a', 'FROM first_measure a').replace('JOIN y b', 'JOIN second_measure b')
    assert not sql_has_unsafe_monetary_fanout(sql)


def test_all_grouping_keys_must_be_joined():
    sql = comparison('waerk,kunnr', 'waerk,kunag')
    assert sql_has_unsafe_monetary_fanout(sql)
    assert not sql_has_unsafe_monetary_fanout(comparison(
        'waerk,kunnr', 'waerk,kunag', 'a.currency=b.currency AND a.customer=b.customer'))


@pytest.mark.parametrize('join,outer', [
    ('a.currency=b.currency OR a.amount=b.amount', 'a.amount,b.amount'),
    ('a.currency=b.currency', 'SUM(a.amount),SUM(b.amount)'),
])
def test_ambiguous_join_or_resumming_is_unsafe(join, outer):
    assert sql_has_unsafe_monetary_fanout(comparison(join=join, outer=outer))


def test_raw_document_flow_join_is_not_proven_safe():
    sql = comparison().replace('FROM "VBRK"', 'FROM "VBRK" JOIN "VBFA" ON "VBFA".vbeln="VBRK".vbeln')
    assert sql_has_unsafe_monetary_fanout(sql)


def test_unproven_dimension_join_is_not_exempted():
    sql = comparison().replace('FROM "VBRK"', 'FROM "VBRK" JOIN "KNA1" ON "KNA1".kunnr="VBRK".kunag')
    assert sql_has_unsafe_monetary_fanout(sql)


def test_independent_scalar_sums_can_cross_join():
    assert not sql_has_unsafe_monetary_fanout('''
        WITH a AS (SELECT SUM(netwr) n FROM "VBAK"),
        b AS (SELECT SUM(netwr) n FROM "VBRK")
        SELECT a.n,b.n FROM a CROSS JOIN b''')


def test_raw_order_item_join_is_still_unsafe():
    assert sql_has_unsafe_monetary_fanout('''SELECT SUM(o.netwr), SUM(i.netwr)
        FROM "VBAK" o JOIN vbrp i ON o.vbeln=i.aubel''')


def test_order_item_amount_filtered_by_not_exists_billing_items_is_safe():
    sql = '''
    WITH order_item_rows AS (
        SELECT DISTINCT src.mandt, src.vbeln, src.posnr, src.netwr, src.waerk
        FROM "VBAP" src
    )
    SELECT i.vbeln, i.posnr, i.netwr, i.waerk
    FROM order_item_rows i
    WHERE NOT EXISTS (
        SELECT 1 FROM "VBRP" p
        WHERE p.mandt = i.mandt AND p.aubel = i.vbeln AND p.aupos = i.posnr
    )
    '''
    assert not sql_has_unsafe_monetary_fanout(sql)


def row_cte_comparison(join='''o.mandt = i.mandt AND o.vbeln = i.aubel
        AND o.posnr = i.aupos AND o.currency = i.currency'''):
    return f'''
    WITH order_rows AS (
        SELECT mandt, vbeln, posnr, waerk AS currency, netwr AS net_value
        FROM "VBAP"
    ), invoice_rows AS (
        SELECT mandt, aubel, aupos, waerk AS currency, netwr AS net_value
        FROM "VBRP"
    ), order_values AS (
        SELECT mandt, vbeln, posnr, currency, SUM(net_value) AS amount
        FROM order_rows GROUP BY mandt, vbeln, posnr, currency
    ), invoice_values AS (
        SELECT mandt, aubel, aupos, currency, SUM(net_value) AS amount
        FROM invoice_rows GROUP BY mandt, aubel, aupos, currency
    )
    SELECT o.mandt, o.vbeln, o.posnr, o.currency, o.amount, i.amount
    FROM order_values o FULL JOIN invoice_values i ON {join}
    '''


def test_row_ctes_keep_distinct_document_facts_separate_until_full_grain_join():
    assert not sql_has_unsafe_monetary_fanout(row_cte_comparison())


def test_row_cte_aggregate_comparison_still_requires_currency_key():
    assert sql_has_unsafe_monetary_fanout(row_cte_comparison(
        'o.mandt = i.mandt AND o.vbeln = i.aubel AND o.posnr = i.aupos'))


def test_row_ctes_can_attach_a_unique_header_before_independent_aggregation():
    sql = '''
    WITH order_rows AS (
        SELECT mandt, vbeln, posnr, waerk AS currency, netwr AS net_value
        FROM "VBAP"
        WHERE EXISTS (SELECT 1 FROM "VBAK" h
                      WHERE h.mandt = "VBAP".mandt AND h.vbeln = "VBAP".vbeln)
    ), invoice_headers AS (
        SELECT mandt, vbeln, MAX(waerk) AS currency
        FROM "VBRK" GROUP BY mandt, vbeln
    ), invoice_items AS (
        SELECT DISTINCT mandt, vbeln, posnr, aubel, aupos, netwr
        FROM "VBRP"
    ), invoice_rows AS (
        SELECT d.mandt, d.aubel, d.aupos, h.currency, d.netwr AS net_value
        FROM invoice_items d
        JOIN invoice_headers h ON h.mandt = d.mandt AND h.vbeln = d.vbeln
        WHERE EXISTS (SELECT 1 FROM order_rows o
                      WHERE o.mandt = d.mandt AND o.vbeln = d.aubel
                        AND o.posnr = d.aupos)
    ), order_values AS (
        SELECT mandt, vbeln, posnr, currency, SUM(net_value) AS amount
        FROM order_rows GROUP BY mandt, vbeln, posnr, currency
    ), invoice_values AS (
        SELECT mandt, aubel, aupos, currency, SUM(net_value) AS amount
        FROM invoice_rows GROUP BY mandt, aubel, aupos, currency
    )
    SELECT o.amount, i.amount
    FROM order_values o FULL JOIN invoice_values i
      ON o.mandt = i.mandt AND o.vbeln = i.aubel
     AND o.posnr = i.aupos AND o.currency = i.currency
    '''
    assert not sql_has_unsafe_monetary_fanout(sql)
