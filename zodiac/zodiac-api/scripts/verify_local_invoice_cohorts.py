"""Read-only independent checks of the local browser's invoice comparison."""
import json
from decimal import Decimal

from sqlalchemy import text

from app.database import engine


checks = {
    "negative_invoice_periods": '''SELECT SUBSTRING(TRIM(CAST(fkdat AS TEXT)),1,4) AS year,
        waerk AS currency, COUNT(*) AS negative_invoice_count,
        SUM(CAST(NULLIF(TRIM(CAST(netwr AS TEXT)),'') AS NUMERIC)) AS negative_invoice_amount
        FROM "VBRK" WHERE SUBSTRING(TRIM(CAST(fkdat AS TEXT)),1,4) IN ('2000','2001')
        AND CAST(NULLIF(TRIM(CAST(netwr AS TEXT)),'') AS NUMERIC) < 0 GROUP BY 1,2 ORDER BY 1,2''',
    "invoice_relationship_coverage": '''WITH ranked AS (
        SELECT vbeln, SUBSTRING(TRIM(CAST(fkdat AS TEXT)),1,4) AS year,
        ROW_NUMBER() OVER (PARTITION BY SUBSTRING(TRIM(CAST(fkdat AS TEXT)),1,4), waerk
        ORDER BY CAST(NULLIF(TRIM(CAST(netwr AS TEXT)),'') AS NUMERIC), vbeln) AS rank
        FROM "VBRK" WHERE SUBSTRING(TRIM(CAST(fkdat AS TEXT)),1,4) IN ('2000','2001')
        AND CAST(NULLIF(TRIM(CAST(netwr AS TEXT)),'') AS NUMERIC) < 0
        ), cohort AS (SELECT * FROM ranked WHERE rank <= 10), links AS (
        SELECT i.year, i.vbeln AS invoice, o.vbeln AS sales_order, o.erdat AS order_date, 'flow' AS route
        FROM cohort i JOIN "VBFA" f ON f.vbeln=i.vbeln JOIN "VBAK" o ON o.vbeln=f.vbelv
        UNION
        SELECT i.year, i.vbeln, o.vbeln, o.erdat, 'item'
        FROM cohort i JOIN "vbrp" p ON p.vbeln=i.vbeln JOIN "VBAK" o ON o.vbeln=p.aubel
        ) SELECT c.year, COUNT(DISTINCT c.vbeln) AS selected_invoice_count,
        COUNT(DISTINCT l.invoice) AS invoices_with_linked_orders,
        COUNT(DISTINCT l.sales_order) AS distinct_linked_orders,
        MIN(l.order_date) AS earliest_linked_order_date, MAX(l.order_date) AS latest_linked_order_date,
        COUNT(DISTINCT CASE WHEN l.route='flow' THEN l.sales_order END) AS flow_order_count,
        COUNT(DISTINCT CASE WHEN l.route='item' THEN l.sales_order END) AS item_order_count
        FROM cohort c LEFT JOIN links l ON l.invoice=c.vbeln GROUP BY c.year ORDER BY c.year''',
}

with engine.connect() as connection:
    transaction = connection.begin()
    try:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        output = {name: [dict(row) for row in connection.execute(text(sql)).mappings()]
                  for name, sql in checks.items()}
        print(json.dumps(output, default=lambda v: str(v) if isinstance(v, Decimal) else v, indent=2))
    finally:
        transaction.rollback()
