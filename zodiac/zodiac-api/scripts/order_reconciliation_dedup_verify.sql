-- Grain: sales order and linked invoice currency; all dates.
-- Order headers: category C. Invoice headers: category M.
-- Invoice item amounts are used as stored, without sign adjustments
-- or cancellation exclusions. Order values must not be summed across
-- multiple invoice-currency rows.
WITH "orders" AS (
    SELECT
        "VBAK"."mandt" AS "client",
        "VBAK"."vbeln" AS "sales_order",
        CAST(NULLIF(TRIM(CAST("VBAK"."netwr" AS TEXT)), '') AS NUMERIC)
            AS "order_net_value",
        NULLIF(TRIM(CAST("VBAK"."waerk" AS TEXT)), '') AS "order_currency"
    FROM "VBAK"
    WHERE TRIM(CAST("VBAK"."vbtyp" AS TEXT)) = 'C'
),
"linked_invoice_items" AS (
    SELECT DISTINCT
        "vbrp"."mandt" AS "client",
        "vbrp"."aubel" AS "sales_order",
        "vbrp"."vbeln" AS "invoice",
        "vbrp"."posnr" AS "invoice_item",
        NULLIF(TRIM(CAST("VBRK"."waerk" AS TEXT)), '') AS "invoice_currency",
        CAST(NULLIF(TRIM(CAST("vbrp"."netwr" AS TEXT)), '') AS NUMERIC)
            AS "invoice_item_net_value"
    FROM "vbrp"
    INNER JOIN "VBRK"
        ON "vbrp"."mandt" = "VBRK"."mandt"
       AND "vbrp"."vbeln" = "VBRK"."vbeln"
    WHERE TRIM(CAST("VBRK"."vbtyp" AS TEXT)) = 'M'
      AND EXISTS (
          SELECT 1
          FROM "VBAP"
          INNER JOIN "orders"
              ON "VBAP"."mandt" = "orders"."client"
             AND "VBAP"."vbeln" = "orders"."sales_order"
          WHERE "VBAP"."mandt" = "vbrp"."mandt"
            AND "VBAP"."vbeln" = "vbrp"."aubel"
            AND "VBAP"."posnr" = "vbrp"."aupos"
      )
),
"billing_by_order" AS (
    SELECT
        "linked_invoice_items"."client",
        "linked_invoice_items"."sales_order",
        "linked_invoice_items"."invoice_currency",
        COUNT(DISTINCT "linked_invoice_items"."invoice") AS "linked_invoice_count",
        COUNT(*) AS "billing_item_count",
        COUNT(*) FILTER (
            WHERE "linked_invoice_items"."invoice_item_net_value" IS NULL
        ) AS "missing_amount_count",
        SUM("linked_invoice_items"."invoice_item_net_value")
            AS "linked_invoice_net_value"
    FROM "linked_invoice_items"
    GROUP BY
        "linked_invoice_items"."client",
        "linked_invoice_items"."sales_order",
        "linked_invoice_items"."invoice_currency"
)
SELECT
    "orders"."client",
    "orders"."sales_order",
    "orders"."order_net_value",
    "orders"."order_currency",
    "billing_by_order"."invoice_currency",
    "billing_by_order"."linked_invoice_net_value",
    "billing_by_order"."linked_invoice_count",
    "billing_by_order"."billing_item_count",
    "billing_by_order"."missing_amount_count" AS "missing_invoice_amount_count",
    CASE
        WHEN "orders"."order_currency" = "billing_by_order"."invoice_currency"
         AND "billing_by_order"."missing_amount_count" = 0
        THEN "orders"."order_net_value"
             - "billing_by_order"."linked_invoice_net_value"
        ELSE NULL
    END AS "order_minus_linked_invoice_net_value",
    CASE
        WHEN "billing_by_order"."billing_item_count" IS NULL
            THEN 'no_linked_invoice'
        WHEN "orders"."order_net_value" IS NULL
          OR "billing_by_order"."missing_amount_count" > 0
            THEN 'missing_amount'
        WHEN "orders"."order_currency" IS NULL
          OR "billing_by_order"."invoice_currency" IS NULL
            THEN 'missing_currency'
        WHEN "orders"."order_currency" <> "billing_by_order"."invoice_currency"
            THEN 'currency_mismatch'
        ELSE 'comparable'
    END AS "comparison_status"
FROM "orders"
LEFT JOIN "billing_by_order"
    ON "orders"."client" = "billing_by_order"."client"
   AND "orders"."sales_order" = "billing_by_order"."sales_order"
ORDER BY
    "orders"."client",
    "orders"."sales_order",
    "billing_by_order"."invoice_currency"