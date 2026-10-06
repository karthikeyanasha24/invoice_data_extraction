WITH "order_rows" AS (
    SELECT
        "VBAK"."mandt",
        "VBAK"."vbeln",
        NULLIF(TRIM(CAST("VBAK"."waerk" AS TEXT)), '') AS "currency",
        CAST(NULLIF(TRIM(CAST("VBAK"."netwr" AS TEXT)), '') AS NUMERIC) AS "net_value"
    FROM "VBAK"
    WHERE "VBAK"."vbtyp" = 'C'
),
"billing_item_rows" AS (
    SELECT DISTINCT
        "vbrp"."mandt",
        "vbrp"."vbeln",
        "vbrp"."posnr",
        "vbrp"."aubel",
        "vbrp"."aupos",
        "vbrp"."netwr",
        "vbrp"."shkzg"
    FROM "vbrp"
),
"order_values" AS (
    SELECT
        "order_rows"."mandt",
        "order_rows"."vbeln",
        "order_rows"."currency",
        SUM("order_rows"."net_value") AS "sales_order_net_value",
        COUNT(*) FILTER (
            WHERE "order_rows"."net_value" IS NULL
        ) AS "missing_order_amount_count"
    FROM "order_rows"
    GROUP BY
        "order_rows"."mandt",
        "order_rows"."vbeln",
        "order_rows"."currency"
),
"invoice_values" AS (
    SELECT
        "billing_item_rows"."mandt",
        "billing_item_rows"."aubel" AS "order_number",
        NULLIF(TRIM(CAST("VBRK"."waerk" AS TEXT)), '') AS "currency",
        COUNT(DISTINCT "billing_item_rows"."vbeln") AS "linked_invoice_count",
        COUNT(*) AS "linked_invoice_item_count",
        SUM(
            CAST(
                NULLIF(TRIM(CAST("billing_item_rows"."netwr" AS TEXT)), '')
                AS NUMERIC
            )
        ) AS "linked_invoice_item_net_value",
        COUNT(*) FILTER (
            WHERE NULLIF(
                TRIM(CAST("billing_item_rows"."netwr" AS TEXT)), ''
            ) IS NULL
        ) AS "missing_invoice_item_amount_count"
    FROM "billing_item_rows"
    INNER JOIN "VBRK"
        ON "VBRK"."mandt" = "billing_item_rows"."mandt"
       AND "VBRK"."vbeln" = "billing_item_rows"."vbeln"
    WHERE "VBRK"."vbtyp" = 'M'
      AND EXISTS (
          SELECT 1
          FROM "VBAP"
          INNER JOIN "VBAK"
              ON "VBAK"."mandt" = "VBAP"."mandt"
             AND "VBAK"."vbeln" = "VBAP"."vbeln"
          WHERE "VBAP"."mandt" = "billing_item_rows"."mandt"
            AND "VBAP"."vbeln" = "billing_item_rows"."aubel"
            AND "VBAP"."posnr" = "billing_item_rows"."aupos"
            AND "VBAK"."vbtyp" = 'C'
      )
    GROUP BY
        "billing_item_rows"."mandt",
        "billing_item_rows"."aubel",
        NULLIF(TRIM(CAST("VBRK"."waerk" AS TEXT)), '')
)
SELECT
    COALESCE("o"."mandt", "i"."mandt") AS "client",
    COALESCE("o"."vbeln", "i"."order_number") AS "sales_order",
    "o"."currency" AS "order_currency",
    "i"."currency" AS "invoice_currency",
    "o"."sales_order_net_value",
    "i"."linked_invoice_count",
    "i"."linked_invoice_item_count",
    "i"."linked_invoice_item_net_value",
    CASE
        WHEN "o"."missing_order_amount_count" = 0
         AND "i"."missing_invoice_item_amount_count" = 0
         AND "o"."currency" = "i"."currency"
        THEN "o"."sales_order_net_value" - "i"."linked_invoice_item_net_value"
    END AS "order_minus_invoice_net_value",
    "o"."missing_order_amount_count",
    "i"."missing_invoice_item_amount_count",
    CASE
        WHEN "o"."vbeln" IS NULL THEN 'Linked billing only at this currency'
        WHEN "i"."order_number" IS NULL THEN 'Order only at this currency'
        ELSE 'Matched'
    END AS "group_match_status",
    (
        NULLIF(TRIM(CAST(COALESCE("o"."mandt", "i"."mandt") AS TEXT)), '') IS NULL
        OR NULLIF(
            TRIM(CAST(COALESCE("o"."vbeln", "i"."order_number") AS TEXT)), ''
        ) IS NULL
        OR COALESCE("o"."currency", "i"."currency") IS NULL
    ) AS "missing_grouping_key",
    'Client, originating sales order, currency' AS "comparison_grain",
    'All dates; orders C; billing M; no cancellation exclusions or sign adjustments'
        AS "scope",
    'Identical billing-item copies deduplicated by full item identity, references, net value and sign attribute'
        AS "source_quality"
FROM "order_values" AS "o"
FULL OUTER JOIN "invoice_values" AS "i"
    ON "o"."mandt" = "i"."mandt"
   AND "o"."vbeln" = "i"."order_number"
   AND "o"."currency" = "i"."currency"
ORDER BY
    "client",
    "sales_order",
    "order_currency" NULLS LAST,
    "invoice_currency" NULLS LAST