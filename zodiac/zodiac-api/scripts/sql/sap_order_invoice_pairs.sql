-- One row per linked sales order / invoice pair for orders dated in 1999.
-- For year 2000, change the date bounds to 20000101 and 20010101.
-- Header values are shown per pair; do not sum them across these rows.
WITH document_pairs AS (
    SELECT DISTINCT f.mandt, f.vbelv AS sales_order, f.vbeln AS billing_document
    FROM "VBFA" f
    WHERE f.vbtyp_v = 'C' AND f.vbtyp_n = 'M'
)
SELECT o.mandt AS client,
       o.vbeln AS sales_order,
       o.bstnk AS customer_reference,
       o.audat AS order_date,
       p.billing_document,
       b.fkdat AS invoice_date,
       CAST(NULLIF(TRIM(CAST(o.netwr AS TEXT)), '') AS NUMERIC) AS order_net_value,
       CAST(NULLIF(TRIM(CAST(b.netwr AS TEXT)), '') AS NUMERIC) AS invoice_net_value,
       o.waerk AS order_currency,
       b.waerk AS invoice_currency,
       CAST(NULLIF(TRIM(CAST(o.netwr AS TEXT)), '') AS NUMERIC)
         - CAST(NULLIF(TRIM(CAST(b.netwr AS TEXT)), '') AS NUMERIC) AS difference_amount
FROM document_pairs p
JOIN "VBAK" o ON o.mandt = p.mandt AND o.vbeln = p.sales_order
JOIN "VBRK" b ON b.mandt = p.mandt AND b.vbeln = p.billing_document
WHERE o.audat >= '19990101' AND o.audat < '20000101'
  AND o.waerk = b.waerk
ORDER BY o.mandt, o.vbeln, p.billing_document
LIMIT 200;
