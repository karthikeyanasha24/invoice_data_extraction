"""
Query Optimizer - Pattern matching and SQL template application.

Provides fast-path execution for common query patterns using pre-built SQL templates.
Reduces latency from 8-15s to 2-3s for 60-70% of queries.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class QueryPattern:
    """Represents a reusable query pattern."""
    pattern_name: str
    pattern_template: str
    sql_template: str
    required_tables: List[str]
    parameters: Dict[str, str]  # Extracted parameters


def extract_year_from_query(query: str) -> Optional[int]:
    """Extract year from query (2020-2030)."""
    match = re.search(r'\b(202[0-9]|2030)\b', query)
    if match:
        return int(match.group(1))
    
    # Check for "last year", "this year", "next year"
    from datetime import datetime
    current_year = datetime.now().year
    
    if "last year" in query.lower():
        return current_year - 1
    if "this year" in query.lower():
        return current_year
    if "next year" in query.lower():
        return current_year + 1
    
    return None


def extract_top_n_from_query(query: str) -> int:
    """Extract number N from 'top N' queries (default 10)."""
    match = re.search(r'\btop\s+(\d+)\b', query.lower())
    if match:
        return min(int(match.group(1)), 100)  # Cap at 100
    return 10


def extract_dimension_from_query(query: str) -> Optional[str]:
    """Extract dimension (customer, product, country, etc.) from query."""
    dimensions = {
        "customer": ["customer", "client", "buyer"],
        "product": ["product", "material", "item", "sku"],
        "country": ["country", "region", "nation"],
        "industry": ["industry", "sector", "vertical"],
        "vendor": ["vendor", "supplier"],
    }
    
    q = query.lower()
    for dim, keywords in dimensions.items():
        if any(kw in q for kw in keywords):
            return dim
    
    return None


# ============================================================================
# COMMON QUERY PATTERNS
# ============================================================================

BUILTIN_PATTERNS = [
    {
        "pattern_name": "sales_by_dimension_for_year",
        "pattern_template": "sales by {dimension} for {year}",
        "keywords": ["sales", "revenue", "for year", "for 20"],
        "sql_template": """
SELECT 
    {dimension_column} as dimension,
    SUM(CAST(NETWR as DECIMAL(15,2))) as total_sales,
    COUNT(*) as invoice_count
FROM {table}
WHERE 
    EXTRACT(YEAR FROM ERDAT::DATE) = {year}
    AND {dimension_column} IS NOT NULL
GROUP BY {dimension_column}
ORDER BY total_sales DESC
LIMIT {limit}
""",
        "required_tables": ["VBRP", "VBRK", "KNA1"],
        "dimension_map": {
            "customer": {"table": "VBRP", "column": "KUNAG", "join": "LEFT JOIN KNA1 ON VBRP.KUNAG = KNA1.KUNNR"},
            "product": {"table": "VBRP", "column": "MATNR", "join": ""},
            "country": {"table": "VBRP", "column": "LAND1", "join": "LEFT JOIN KNA1 ON VBRP.KUNAG = KNA1.KUNNR"},
        },
    },
    {
        "pattern_name": "top_customers_by_revenue",
        "pattern_template": "top {n} customers by revenue",
        "keywords": ["top", "customer", "revenue", "sales"],
        "sql_template": """
SELECT 
    v.KUNAG as customer_id,
    k.NAME1 as customer_name,
    k.LAND1 as country,
    SUM(CAST(v.NETWR as DECIMAL(15,2))) as total_revenue,
    COUNT(DISTINCT v.VBELN) as invoice_count
FROM VBRP v
LEFT JOIN KNA1 k ON v.KUNAG = k.KUNNR
WHERE v.KUNAG IS NOT NULL
GROUP BY v.KUNAG, k.NAME1, k.LAND1
ORDER BY total_revenue DESC
LIMIT {n}
""",
        "required_tables": ["VBRP", "KNA1"],
    },
    {
        "pattern_name": "top_products_by_sales",
        "pattern_template": "top {n} products by sales",
        "keywords": ["top", "product", "sales", "revenue", "material"],
        "sql_template": """
SELECT 
    v.MATNR as product_id,
    m.MAKTX as product_name,
    SUM(CAST(v.NETWR as DECIMAL(15,2))) as total_sales,
    SUM(CAST(v.FKIMG as DECIMAL(15,3))) as total_quantity,
    COUNT(DISTINCT v.VBELN) as invoice_count
FROM VBRP v
LEFT JOIN MAKT m ON v.MATNR = m.MATNR
WHERE v.MATNR IS NOT NULL
GROUP BY v.MATNR, m.MAKTX
ORDER BY total_sales DESC
LIMIT {n}
""",
        "required_tables": ["VBRP", "MAKT"],
    },
    {
        "pattern_name": "revenue_by_country",
        "pattern_template": "revenue by country",
        "keywords": ["revenue", "sales", "country", "nation", "region"],
        "sql_template": """
SELECT 
    k.LAND1 as country,
    SUM(CAST(v.NETWR as DECIMAL(15,2))) as total_revenue,
    COUNT(DISTINCT v.VBELN) as invoice_count,
    COUNT(DISTINCT v.KUNAG) as customer_count
FROM VBRP v
LEFT JOIN KNA1 k ON v.KUNAG = k.KUNNR
WHERE k.LAND1 IS NOT NULL
GROUP BY k.LAND1
ORDER BY total_revenue DESC
LIMIT 50
""",
        "required_tables": ["VBRP", "KNA1"],
    },
    {
        "pattern_name": "sales_trend_over_time",
        "pattern_template": "sales trend over {period}",
        "keywords": ["trend", "over time", "daily", "weekly", "monthly"],
        "sql_template": """
SELECT 
    DATE_TRUNC('{period}', ERDAT::DATE) as period,
    SUM(CAST(NETWR as DECIMAL(15,2))) as total_sales,
    COUNT(DISTINCT VBELN) as invoice_count
FROM VBRP
WHERE ERDAT IS NOT NULL
GROUP BY DATE_TRUNC('{period}', ERDAT::DATE)
ORDER BY period DESC
LIMIT 100
""",
        "required_tables": ["VBRP"],
    },
]


# ============================================================================
# DETERMINISTIC QUERY PATTERNS (FROM run_sap_business_queries_full.py)
# These reuse the exact SQL logic from the 2800+ script, so the AI can
# choose a specific hard-coded query instead of generating new SQL.
# ============================================================================

SCRIPT_QUERY_PATTERNS = [
    {
        "pattern_name": "sales_highest_sales_by_product",
        "pattern_template": "highest sales by product",
        "keywords": ["highest", "sales", "product"],
        "sql_template": """
SELECT
    m."maktx" AS product,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
LEFT JOIN "MAKT" AS m ON p."matnr" = m."matnr"
GROUP BY m."maktx"
ORDER BY revenue DESC
LIMIT 20
""",
        "required_tables": ["vbrp", "VBRK", "MAKT"],
    },
    {
        "pattern_name": "sales_top10_customers_by_revenue",
        "pattern_template": "top customers by revenue",
        "keywords": ["top", "customers", "revenue"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
GROUP BY k."name1", k."land1"
ORDER BY revenue DESC
LIMIT 10
""",
        "required_tables": ["vbrp", "VBRK", "KNA1"],
    },
    {
        "pattern_name": "sales_by_country",
        "pattern_template": "sales by country",
        "keywords": ["sales", "by country"],
        "sql_template": """
SELECT
    k."land1" AS country,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue,
    COUNT(DISTINCT h."vbeln") AS invoice_count
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
GROUP BY k."land1"
ORDER BY revenue DESC
""",
        "required_tables": ["vbrp", "VBRK", "KNA1"],
    },
    {
        "pattern_name": "customers_highest_total_open_ar",
        "pattern_template": "customers with highest total open ar",
        "keywords": ["highest", "open", "ar", "customers"],
        "sql_template": """
SELECT
    b."kunnr" AS customer_id,
    k."name1" AS customer,
    k."land1" AS country,
    SUM(NULLIF(TRIM(b."wrbtr"::text), '')::numeric) AS ar_amount
FROM "BSAD" AS b
JOIN "KNA1" AS k ON b."kunnr" = k."kunnr"
GROUP BY b."kunnr", k."name1", k."land1"
ORDER BY ar_amount DESC
LIMIT 50
""",
        "required_tables": ["BSAD", "KNA1"],
    },
    {
        "pattern_name": "purchasing_total_cost_by_vendor",
        "pattern_template": "total cost by vendor",
        "keywords": ["total", "cost", "vendor"],
        "sql_template": """
SELECT
    l."name1" AS vendor,
    l."land1" AS country,
    SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric) AS po_value
FROM "EKPO" AS i
JOIN "EKKO" AS h ON i."ebeln" = h."ebeln"
JOIN "LFA1" AS l ON h."lifnr" = l."lifnr"
GROUP BY l."name1", l."land1"
ORDER BY po_value DESC
""",
        "required_tables": ["EKPO", "EKKO", "LFA1"],
    },
    {
        "pattern_name": "purchasing_vendor_invoice_totals_by_currency",
        "pattern_template": "vendor invoice totals by currency",
        "keywords": ["vendor", "invoice", "totals", "currency"],
        "sql_template": """
SELECT
    h."waers" AS currency,
    SUM(NULLIF(TRIM(h."rmwwr"::text), '')::numeric) AS total_invoice_amount
FROM "RBKP" AS h
GROUP BY h."waers"
ORDER BY total_invoice_amount DESC
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "logistics_deliveries_by_customer",
        "pattern_template": "deliveries by customer",
        "keywords": ["deliveries", "by customer"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    SUM(NULLIF(TRIM(i."lfimg"::text), '')::numeric) AS delivered_qty
FROM "LIPS" AS i
JOIN "LIKP" AS h ON i."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunnr" = k."kunnr"
GROUP BY k."name1", k."land1"
ORDER BY delivered_qty DESC
LIMIT 50
""",
        "required_tables": ["LIPS", "LIKP", "KNA1"],
    },
    {
        "pattern_name": "finance_gl_balances_by_account_period",
        "pattern_template": "gl balances by account and period",
        "keywords": ["gl", "balances", "account", "period"],
        "sql_template": """
SELECT
    "racct" AS gl_account,
    "rbukrs" AS company_code,
    "ryear" AS fiscal_year,
    "poper" AS period,
    SUM(NULLIF(TRIM("hsl"::text), '')::numeric) AS balance_local
FROM "FAGLFLEXA"
GROUP BY "racct", "rbukrs", "ryear", "poper"
ORDER BY "ryear", "poper", gl_account
LIMIT 200
""",
        "required_tables": ["FAGLFLEXA"],
    },
    {
        "pattern_name": "manufacturing_orders_by_plant_status",
        "pattern_template": "orders by plant and status",
        "keywords": ["orders", "plant", "status"],
        "sql_template": """
SELECT
    "werks" AS plant,
    "aufk_status" AS status,
    COUNT(*) AS order_count
FROM "AUFK"
GROUP BY "werks", "aufk_status"
ORDER BY plant, status
""",
        "required_tables": ["AUFK"],
    },
    {
        "pattern_name": "master_industry_mapping",
        "pattern_template": "industry mapping",
        "keywords": ["industry", "mapping"],
        "sql_template": """
SELECT DISTINCT
    k."brsch" AS industry_code,
    t."brtxt" AS industry_text
FROM "KNA1" AS k
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
ORDER BY industry_code
""",
        "required_tables": ["KNA1", "T016T"],
    },
    # --- Additional mappings from run_sap_business_queries_full.py (Sales & Customers & Purchasing & Logistics & Inventory) ---
    {
        "pattern_name": "sales_by_country_and_industry",
        "pattern_template": "sales by country and industry",
        "keywords": ["sales", "country", "industry"],
        "sql_template": """
SELECT
    k."land1" AS country,
    t."brtxt" AS industry,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY k."land1", t."brtxt"
ORDER BY country, revenue DESC
""",
        "required_tables": ["vbrp", "VBRK", "KNA1", "T016T"],
    },
    {
        "pattern_name": "sales_industry_with_highest_revenues",
        "pattern_template": "industry with highest revenues",
        "keywords": ["industry", "highest", "revenues"],
        "sql_template": """
SELECT
    t."brtxt" AS industry,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY t."brtxt"
ORDER BY revenue DESC
LIMIT 20
""",
        "required_tables": ["vbrp", "VBRK", "KNA1", "T016T"],
    },
    {
        "pattern_name": "sales_lowest_sales_by_customer_country",
        "pattern_template": "lowest sales by customer and country",
        "keywords": ["lowest", "sales", "customer", "country"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
GROUP BY k."name1", k."land1"
HAVING SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) > 0
ORDER BY revenue ASC
LIMIT 20
""",
        "required_tables": ["vbrp", "VBRK", "KNA1"],
    },
    {
        "pattern_name": "sales_by_customer_script",
        "pattern_template": "sales by customer (script)",
        "keywords": ["sales", "customer"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
GROUP BY k."name1"
ORDER BY revenue DESC
""",
        "required_tables": ["vbrp", "VBRK", "KNA1"],
    },
    {
        "pattern_name": "sales_highest_sales_by_customer_product_country",
        "pattern_template": "highest sales by customer product and country",
        "keywords": ["highest", "sales", "customer", "product", "country"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    m."maktx" AS product,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
LEFT JOIN "MAKT" AS m ON p."matnr" = m."matnr"
GROUP BY k."name1", k."land1", m."maktx"
ORDER BY revenue DESC
LIMIT 50
""",
        "required_tables": ["vbrp", "VBRK", "KNA1", "MAKT"],
    },
    {
        "pattern_name": "sales_top_products_by_quantity_sold_script",
        "pattern_template": "top products by quantity sold (script)",
        "keywords": ["top", "products", "quantity", "sold"],
        "sql_template": """
SELECT
    m."maktx" AS product,
    SUM(NULLIF(TRIM(p."fkimg"::text), '')::numeric) AS quantity
FROM "vbrp" AS p
LEFT JOIN "MAKT" AS m ON p."matnr" = m."matnr"
GROUP BY m."maktx"
ORDER BY quantity DESC
LIMIT 50
""",
        "required_tables": ["vbrp", "MAKT"],
    },
    {
        "pattern_name": "sales_by_product_hierarchy_script",
        "pattern_template": "sales by product hierarchy (script)",
        "keywords": ["sales", "product", "hierarchy"],
        "sql_template": """
SELECT
    v."vkorg" AS sales_org,
    v."vtweg" AS dist_channel,
    mv."prodh" AS product_hierarchy,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS v ON p."vbeln" = v."vbeln"
JOIN "MVKE" AS mv ON p."matnr" = mv."matnr"
GROUP BY v."vkorg", v."vtweg", mv."prodh"
ORDER BY revenue DESC
LIMIT 50
""",
        "required_tables": ["vbrp", "VBRK", "MVKE"],
    },
    {
        "pattern_name": "sales_compare_2023_vs_2024_script",
        "pattern_template": "compare 2023 vs 2024 revenue (script)",
        "keywords": ["compare", "2023", "2024", "revenue"],
        "sql_template": """
SELECT
    EXTRACT(YEAR FROM v."fkdat"::date)::int AS year,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS v ON p."vbeln" = v."vbeln"
WHERE EXTRACT(YEAR FROM v."fkdat"::date) IN (2023, 2024)
GROUP BY EXTRACT(YEAR FROM v."fkdat"::date)
ORDER BY year
""",
        "required_tables": ["vbrp", "VBRK"],
    },
    {
        "pattern_name": "sales_for_year_2024_script",
        "pattern_template": "revenue for 2024 (script)",
        "keywords": ["revenue", "2024"],
        "sql_template": """
SELECT
    m."maktx" AS product,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS v ON p."vbeln" = v."vbeln"
LEFT JOIN "MAKT" AS m ON p."matnr" = m."matnr"
WHERE EXTRACT(YEAR FROM v."fkdat"::date) = 2024
GROUP BY m."maktx"
ORDER BY revenue DESC
LIMIT 50
""",
        "required_tables": ["vbrp", "VBRK", "MAKT"],
    },
    {
        "pattern_name": "sales_revenue_last_30_days_script",
        "pattern_template": "revenue last 30 days (script)",
        "keywords": ["revenue", "last 30 days"],
        "sql_template": """
SELECT
    v."fkdat"::date AS billing_date,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS v ON p."vbeln" = v."vbeln"
WHERE v."fkdat"::date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY v."fkdat"::date
ORDER BY v."fkdat"::date
""",
        "required_tables": ["vbrp", "VBRK"],
    },
    {
        "pattern_name": "sales_avg_order_value_by_customer_country_industry_script",
        "pattern_template": "average order value by customer country industry (script)",
        "keywords": ["average", "order value", "customer", "country", "industry"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    t."brtxt" AS industry,
    COUNT(DISTINCT v."vbeln") AS invoice_count,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS total_revenue,
    CASE WHEN COUNT(DISTINCT v."vbeln") > 0
         THEN SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) / COUNT(DISTINCT v."vbeln")
         ELSE NULL END AS avg_invoice_value
FROM "vbrp" AS p
JOIN "VBRK" AS v ON p."vbeln" = v."vbeln"
JOIN "KNA1" AS k ON v."kunag" = k."kunnr"
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY k."name1", k."land1", t."brtxt"
ORDER BY avg_invoice_value DESC NULLS LAST
LIMIT 50
""",
        "required_tables": ["vbrp", "VBRK", "KNA1", "T016T"],
    },
    {
        "pattern_name": "compare_sales_vs_invoice_totals_script",
        "pattern_template": "compare sales data with order values (script)",
        "keywords": ["compare", "sales", "order", "invoice"],
        "sql_template": """
SELECT
    h."vbeln" AS invoice,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS invoice_value,
    SUM(NULLIF(TRIM(o."netwr"::text), '')::numeric) AS order_value,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) - SUM(NULLIF(TRIM(o."netwr"::text), '')::numeric) AS difference
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "VBFA" AS f ON f."vbeln" = p."vbeln"
JOIN "VBAP" AS o ON f."vbelv" = o."vbeln" AND f."posnv" = o."posnr"
GROUP BY h."vbeln"
ORDER BY ABS(SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) - SUM(NULLIF(TRIM(o."netwr"::text), '')::numeric)) DESC
LIMIT 50
""",
        "required_tables": ["vbrp", "VBRK", "VBFA", "VBAP"],
    },
    # Customers & AR
    {
        "pattern_name": "customers_list_by_country_region_city",
        "pattern_template": "customers list by country region city",
        "keywords": ["customers", "country", "region", "city"],
        "sql_template": """
SELECT
    "land1" AS country,
    "regio" AS region,
    "ort01" AS city,
    "kunnr" AS customer_id,
    "name1" AS customer_name,
    "brsch" AS industry_code
FROM "KNA1"
ORDER BY country, region, city, customer_name
""",
        "required_tables": ["KNA1"],
    },
    {
        "pattern_name": "customers_list_by_industry_script",
        "pattern_template": "customers list by industry (script)",
        "keywords": ["customers", "list", "industry"],
        "sql_template": """
SELECT
    k."brsch" AS industry_code,
    t."brtxt" AS industry_name,
    COUNT(*) AS customer_count
FROM "KNA1" AS k
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY k."brsch", t."brtxt"
ORDER BY customer_count DESC
""",
        "required_tables": ["KNA1", "T016T"],
    },
    {
        "pattern_name": "customers_revenue_by_industry_script",
        "pattern_template": "customers revenue by industry (script)",
        "keywords": ["revenue", "industry", "customers"],
        "sql_template": """
SELECT
    t."brtxt" AS industry,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS v ON p."vbeln" = v."vbeln"
JOIN "KNA1" AS k ON v."kunag" = k."kunnr"
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY t."brtxt"
ORDER BY revenue DESC
""",
        "required_tables": ["vbrp", "VBRK", "KNA1", "T016T"],
    },
    {
        "pattern_name": "ar_cleared_amounts_by_country_script",
        "pattern_template": "ar cleared amounts by country (script)",
        "keywords": ["ar", "cleared", "country"],
        "sql_template": """
SELECT
    k."land1" AS country,
    SUM(NULLIF(TRIM(b."wrbtr"::text), '')::numeric) AS ar_amount
FROM "BSAD" AS b
JOIN "KNA1" AS k ON b."kunnr" = k."kunnr"
GROUP BY k."land1"
ORDER BY ar_amount DESC
""",
        "required_tables": ["BSAD", "KNA1"],
    },
    # Purchasing
    {
        "pattern_name": "purch_po_totals_by_material_script",
        "pattern_template": "po totals by material (script)",
        "keywords": ["po", "totals", "material"],
        "sql_template": """
SELECT
    i."matnr" AS material,
    SUM(NULLIF(TRIM(i."menge"::text), '')::numeric) AS po_qty,
    SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric) AS po_value
FROM "EKPO" AS i
GROUP BY i."matnr"
ORDER BY po_value DESC
LIMIT 50
""",
        "required_tables": ["EKPO"],
    },
    {
        "pattern_name": "purch_po_totals_by_vendor_currency_script",
        "pattern_template": "po totals by vendor and currency (script)",
        "keywords": ["po", "totals", "vendor", "currency"],
        "sql_template": """
SELECT
    l."name1" AS vendor,
    h."waers" AS currency,
    SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric) AS po_value
FROM "EKPO" AS i
JOIN "EKKO" AS h ON i."ebeln" = h."ebeln"
JOIN "LFA1" AS l ON h."lifnr" = l."lifnr"
GROUP BY l."name1", h."waers"
ORDER BY po_value DESC
""",
        "required_tables": ["EKPO", "EKKO", "LFA1"],
    },
    {
        "pattern_name": "purch_vendor_invoice_totals_by_vendor_country_script",
        "pattern_template": "vendor invoice totals by vendor and country (script)",
        "keywords": ["vendor", "invoice", "totals", "country"],
        "sql_template": """
SELECT
    v."name1" AS vendor,
    v."land1" AS country,
    SUM(NULLIF(TRIM(h."rmwwr"::text), '')::numeric) AS total_invoice_amount
FROM "RBKP" AS h
JOIN "LFA1" AS v ON h."lifnr" = v."lifnr"
GROUP BY v."name1", v."land1"
ORDER BY total_invoice_amount DESC
""",
        "required_tables": ["RBKP", "LFA1"],
    },
    {
        "pattern_name": "purch_compare_po_vs_vendor_invoices_script",
        "pattern_template": "compare po values vs vendor invoice values (script)",
        "keywords": ["compare", "po", "vendor", "invoice"],
        "sql_template": """
SELECT
    i."ebeln" AS po_number,
    SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric) AS po_value,
    SUM(NULLIF(TRIM(s."wrbtr"::text), '')::numeric) AS invoice_value,
    SUM(NULLIF(TRIM(s."wrbtr"::text), '')::numeric) - SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric) AS difference
FROM "EKPO" AS i
LEFT JOIN "RSEG" AS s
    ON i."ebeln" = s."ebeln" AND i."ebelp" = s."ebelp"
GROUP BY i."ebeln"
HAVING SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric) IS NOT NULL
ORDER BY ABS(SUM(NULLIF(TRIM(s."wrbtr"::text), '')::numeric) - SUM(NULLIF(TRIM(i."netwr"::text), '')::numeric)) DESC
LIMIT 50
""",
        "required_tables": ["EKPO", "RSEG"],
    },
    # Logistics
    {
        "pattern_name": "log_outbound_qty_by_product_script",
        "pattern_template": "outbound delivery quantities by product (script)",
        "keywords": ["outbound", "delivery", "quantities", "product"],
        "sql_template": """
SELECT
    m."maktx" AS product,
    SUM(NULLIF(TRIM(i."lfimg"::text), '')::numeric) AS delivered_qty
FROM "LIPS" AS i
LEFT JOIN "MAKT" AS m ON i."matnr" = m."matnr"
GROUP BY m."maktx"
ORDER BY delivered_qty DESC
LIMIT 50
""",
        "required_tables": ["LIPS", "MAKT"],
    },
    {
        "pattern_name": "log_total_delivered_qty_by_customer_country_script",
        "pattern_template": "total delivered quantity by customer and country (script)",
        "keywords": ["delivered", "quantity", "customer", "country"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    SUM(NULLIF(TRIM(i."lfimg"::text), '')::numeric) AS delivered_qty
FROM "LIPS" AS i
JOIN "LIKP" AS h ON i."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunnr" = k."kunnr"
GROUP BY k."name1", k."land1"
ORDER BY delivered_qty DESC
LIMIT 50
""",
        "required_tables": ["LIPS", "LIKP", "KNA1"],
    },
    {
        "pattern_name": "log_goods_movements_by_material_plant_script",
        "pattern_template": "goods movements by material and plant (script)",
        "keywords": ["goods", "movements", "material", "plant"],
        "sql_template": """
SELECT
    m."matnr" AS material,
    m."werks" AS plant,
    COUNT(*) AS movement_count
FROM "MKPF" AS h
JOIN "RESB" AS m
    ON h."mjahr" = m."werks"
GROUP BY m."matnr", m."werks"
ORDER BY movement_count DESC
LIMIT 50
""",
        "required_tables": ["MKPF", "RESB"],
    },
    {
        "pattern_name": "log_reservations_by_material_plant_script",
        "pattern_template": "reservations by material and plant (script)",
        "keywords": ["reservations", "material", "plant"],
        "sql_template": """
SELECT
    "matnr" AS material,
    "werks" AS plant,
    SUM(NULLIF(TRIM("bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB"
GROUP BY "matnr", "werks"
ORDER BY reserved_qty DESC
LIMIT 50
""",
        "required_tables": ["RESB"],
    },
    # Inventory
    {
        "pattern_name": "inv_material_master_overview_by_plant_script",
        "pattern_template": "material master overview by plant (script)",
        "keywords": ["material master", "overview", "plant"],
        "sql_template": """
SELECT
    m."matnr" AS material,
    m."werks" AS plant,
    m."dispo" AS mrp_controller,
    m."dismm" AS mrp_type,
    m."eisbe" AS safety_stock,
    m."minbe" AS reorder_point
FROM "MARC" AS m
ORDER BY m."werks", m."matnr"
LIMIT 200
""",
        "required_tables": ["MARC"],
    },
    {
        "pattern_name": "inv_materials_with_highest_stock_quantity_script",
        "pattern_template": "materials with highest reserved quantity (script)",
        "keywords": ["materials", "highest", "reserved", "quantity"],
        "sql_template": """
SELECT
    r."matnr" AS material,
    r."werks" AS plant,
    SUM(NULLIF(TRIM(r."bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB" AS r
GROUP BY r."matnr", r."werks"
ORDER BY reserved_qty DESC
LIMIT 50
""",
        "required_tables": ["RESB"],
    },
    # Finance / GL / profitability (from q_fin_*)
    {
        "pattern_name": "fin_actual_costs_by_cost_center_element_2024_script",
        "pattern_template": "actual costs by cost center and cost element for 2024 (script)",
        "keywords": ["actual", "costs", "cost center", "2024"],
        "sql_template": """
SELECT
    s."kokrs" AS controlling_area,
    s."kostl" AS cost_center,
    c."kstar" AS cost_element,
    SUM(NULLIF(TRIM(c."wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP" AS c
JOIN "CSKS" AS s ON c."objnr" = s."objnr"
WHERE c."gjahr" = '2024'
GROUP BY s."kokrs", s."kostl", c."kstar"
ORDER BY actual_amount DESC
LIMIT 100
""",
        "required_tables": ["COEP", "CSKS"],
    },
    {
        "pattern_name": "fin_top20_cost_centers_by_total_cost_script",
        "pattern_template": "top 20 cost centers by total cost (script)",
        "keywords": ["top", "cost centers", "total cost"],
        "sql_template": """
SELECT
    s."kostl" AS cost_center,
    SUM(NULLIF(TRIM(c."wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP" AS c
JOIN "CSKS" AS s ON c."objnr" = s."objnr"
GROUP BY s."kostl"
ORDER BY actual_amount DESC
LIMIT 20
""",
        "required_tables": ["COEP", "CSKS"],
    },
    {
        "pattern_name": "fin_planned_vs_actual_by_cost_center_period_script",
        "pattern_template": "planned vs actual by cost center and period (script)",
        "keywords": ["planned", "actual", "cost center", "period"],
        "sql_template": """
SELECT
    s."kokrs" AS controlling_area,
    s."kostl" AS cost_center,
    c."gjahr" AS year,
    c."perio" AS period,
    SUM(NULLIF(TRIM(c."wkgbtr"::text), '')::numeric) AS actual_amount,
    SUM(NULLIF(TRIM(p."wog001"::text), '')::numeric) AS planned_amount
FROM "COEP" AS c
JOIN "CSKS" AS s ON c."objnr" = s."objnr"
LEFT JOIN "COSP" AS p
    ON c."objnr" = p."objnr"
   AND c."gjahr" = p."gjahr"
   AND c."wrttp" = p."wrttp"
   AND c."versn" = p."versn"
GROUP BY s."kokrs", s."kostl", c."gjahr", c."perio"
ORDER BY c."gjahr", c."perio", s."kostl"
LIMIT 200
""",
        "required_tables": ["COEP", "CSKS", "COSP"],
    },
    # Manufacturing & costing (from q_mfg_*)
    {
        "pattern_name": "mfg_total_planned_vs_actual_by_order_type_script",
        "pattern_template": "total actual value by order type (script)",
        "keywords": ["total", "actual", "order type"],
        "sql_template": """
SELECT
    a."auart" AS order_type,
    COUNT(DISTINCT a."aufnr") AS order_count,
    SUM(NULLIF(TRIM(e."wkgbtr"::text), '')::numeric) AS actual_cost
FROM "AUFK" AS a
LEFT JOIN "COEP" AS e ON a."objnr" = e."objnr"
GROUP BY a."auart"
ORDER BY actual_cost DESC
""",
        "required_tables": ["AUFK", "COEP"],
    },
    {
        "pattern_name": "mfg_costing_runs_status_by_company_code_script",
        "pattern_template": "costing runs and status by company code (script)",
        "keywords": ["costing runs", "status", "company code"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    "statk" AS status,
    COUNT(*) AS run_count
FROM "CKHS"
GROUP BY "bukrs", "statk"
ORDER BY company_code, status
""",
        "required_tables": ["CKHS"],
    },
    {
        "pattern_name": "mfg_cost_component_breakdown_for_material_script",
        "pattern_template": "cost component breakdown per material and plant (script)",
        "keywords": ["cost component", "material", "plant"],
        "sql_template": """
SELECT
    c."matnr" AS material,
    c."werks" AS plant,
    c."kstar" AS cost_element,
    SUM(NULLIF(TRIM(c."wertn"::text), '')::numeric) AS value
FROM "CKIS" AS c
GROUP BY c."matnr", c."werks", c."kstar"
ORDER BY value DESC
LIMIT 50
""",
        "required_tables": ["CKIS"],
    },
    {
        "pattern_name": "mfg_costing_item_descriptions_script",
        "pattern_template": "costing item descriptions (script)",
        "keywords": ["costing item", "descriptions"],
        "sql_template": """
SELECT
    "kalnr" AS costing_number,
    "kadky" AS costing_date_key,
    "ltext" AS item_text
FROM "CKIT"
ORDER BY "kalnr", "kadky"
LIMIT 200
""",
        "required_tables": ["CKIT"],
    },
    {
        "pattern_name": "mfg_actual_vs_standard_cost_per_material_plant_2024p01_script",
        "pattern_template": "actual vs standard cost per material plant 2024 01 (script)",
        "keywords": ["actual", "standard", "cost", "2024", "01"],
        "sql_template": """
SELECT
    h."matnr" AS material,
    h."bwkey" AS valuation_area,
    c."poper" AS period,
    c."bdatj" AS year,
    NULLIF(TRIM(c."stprs"::text), '')::numeric AS standard_price,
    NULLIF(TRIM(c."salk3"::text), '')::numeric AS total_stock_value
FROM "CKMLCR" AS c
JOIN "CKMLHD" AS h ON c."kalnr" = h."kalnr"
WHERE c."bdatj" = '2024' AND c."poper" = '01'
LIMIT 200
""",
        "required_tables": ["CKMLCR", "CKMLHD"],
    },
    {
        "pattern_name": "mfg_standard_cost_estimate_by_plant_script",
        "pattern_template": "standard cost estimate count by plant (script)",
        "keywords": ["standard cost", "estimate", "plant"],
        "sql_template": """
SELECT
    "werks" AS plant,
    COUNT(*) AS cost_objects
FROM "KEKO"
GROUP BY "werks"
ORDER BY plant
""",
        "required_tables": ["KEKO"],
    },
    {
        "pattern_name": "mfg_cost_element_costs_script",
        "pattern_template": "cost by cost element (script)",
        "keywords": ["cost", "cost element"],
        "sql_template": """
SELECT
    "kstar" AS cost_element,
    SUM(NULLIF(TRIM("wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP"
GROUP BY "kstar"
ORDER BY actual_amount DESC
LIMIT 50
""",
        "required_tables": ["COEP"],
    },
    # Master data & reference (from q_master_*)
    {
        "pattern_name": "master_profit_centers_script",
        "pattern_template": "profit center list (script)",
        "keywords": ["profit centers", "list"],
        "sql_template": """
SELECT
    "prctr" AS profit_center,
    "bukrs" AS company_code,
    "land1" AS country,
    "name1" AS name
FROM "CEPC"
ORDER BY company_code, profit_center
LIMIT 200
""",
        "required_tables": ["CEPC"],
    },
    {
        "pattern_name": "master_cost_centers_script",
        "pattern_template": "cost center list (script)",
        "keywords": ["cost centers", "list"],
        "sql_template": """
SELECT
    "kokrs" AS controlling_area,
    "kostl" AS cost_center,
    "bukrs" AS company_code,
    "prctr" AS profit_center,
    "name1" AS name
FROM "CSKS"
ORDER BY controlling_area, cost_center
LIMIT 200
""",
        "required_tables": ["CSKS"],
    },
    # Extra analytics for AUFK / BSAD / BSEG / CEPC / CKHS
    {
        "pattern_name": "aufk_orders_by_plant_script",
        "pattern_template": "aufk orders by plant (script)",
        "keywords": ["orders", "plant", "aufk"],
        "sql_template": """
SELECT
    "werks" AS plant,
    COUNT(*) AS order_count
FROM "AUFK"
GROUP BY "werks"
ORDER BY order_count DESC
""",
        "required_tables": ["AUFK"],
    },
    {
        "pattern_name": "aufk_orders_by_company_code_script",
        "pattern_template": "aufk orders by company code (script)",
        "keywords": ["orders", "company code", "aufk"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    COUNT(*) AS order_count
FROM "AUFK"
GROUP BY "bukrs"
ORDER BY order_count DESC
""",
        "required_tables": ["AUFK"],
    },
    {
        "pattern_name": "aufk_orders_by_order_type_script",
        "pattern_template": "aufk orders by order type (script)",
        "keywords": ["orders", "order type", "aufk"],
        "sql_template": """
SELECT
    "auart" AS order_type,
    COUNT(*) AS order_count
FROM "AUFK"
GROUP BY "auart"
ORDER BY order_count DESC
""",
        "required_tables": ["AUFK"],
    },
    {
        "pattern_name": "aufk_orders_created_by_month_script",
        "pattern_template": "aufk orders created by month (script)",
        "keywords": ["orders", "created", "month", "aufk"],
        "sql_template": """
SELECT
    EXTRACT(YEAR FROM to_date("erdat", 'YYYYMMDD'))::int AS year,
    EXTRACT(MONTH FROM to_date("erdat", 'YYYYMMDD'))::int AS month,
    COUNT(*) AS order_count
FROM "AUFK"
WHERE "erdat" ~ '^[0-9]{8}$'
  AND "erdat" <> '00000000'
GROUP BY
    EXTRACT(YEAR FROM to_date("erdat", 'YYYYMMDD')),
    EXTRACT(MONTH FROM to_date("erdat", 'YYYYMMDD'))
ORDER BY year, month
""",
        "required_tables": ["AUFK"],
    },
    {
        "pattern_name": "aufk_orders_by_status_script",
        "pattern_template": "aufk orders by status (script)",
        "keywords": ["orders", "status", "aufk"],
        "sql_template": """
SELECT
    "aufk_status" AS status,
    COUNT(*) AS order_count
FROM "AUFK"
GROUP BY "aufk_status"
ORDER BY order_count DESC
""",
        "required_tables": ["AUFK"],
    },
    {
        "pattern_name": "bsad_total_cleared_payments_by_customer_script",
        "pattern_template": "total cleared payments by customer (script)",
        "keywords": ["cleared payments", "customer", "bsad"],
        "sql_template": """
SELECT
    b."kunnr" AS customer_id,
    k."name1" AS customer_name,
    k."land1" AS country,
    SUM(NULLIF(TRIM(b."wrbtr"::text), '')::numeric) AS cleared_amount
FROM "BSAD" AS b
LEFT JOIN "KNA1" AS k ON b."kunnr" = k."kunnr"
GROUP BY b."kunnr", k."name1", k."land1"
ORDER BY cleared_amount DESC
""",
        "required_tables": ["BSAD", "KNA1"],
    },
    {
        "pattern_name": "bsad_payments_by_year_script",
        "pattern_template": "bsad payments by posting year (script)",
        "keywords": ["payments", "posting year", "bsad"],
        "sql_template": """
SELECT
    EXTRACT(YEAR FROM "budat"::date)::int AS year,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS cleared_amount
FROM "BSAD"
GROUP BY EXTRACT(YEAR FROM "budat"::date)
ORDER BY year
""",
        "required_tables": ["BSAD"],
    },
    {
        "pattern_name": "bsad_ar_cleared_by_industry_script",
        "pattern_template": "bsad ar cleared by industry (script)",
        "keywords": ["ar", "cleared", "industry", "bsad"],
        "sql_template": """
SELECT
    t."brtxt" AS industry,
    SUM(NULLIF(TRIM(b."wrbtr"::text), '')::numeric) AS cleared_amount
FROM "BSAD" AS b
JOIN "KNA1" AS k ON b."kunnr" = k."kunnr"
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY t."brtxt"
ORDER BY cleared_amount DESC
""",
        "required_tables": ["BSAD", "KNA1", "T016T"],
    },
    {
        "pattern_name": "bseg_gl_postings_by_account_script",
        "pattern_template": "bseg gl postings by account and year (script)",
        "keywords": ["gl postings", "account", "bseg"],
        "sql_template": """
SELECT
    "hkont" AS gl_account,
    "bukrs" AS company_code,
    "gjahr" AS fiscal_year,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS amount
FROM "BSEG"
GROUP BY "hkont", "bukrs", "gjahr"
ORDER BY fiscal_year, gl_account
LIMIT 200
""",
        "required_tables": ["BSEG"],
    },
    {
        "pattern_name": "bseg_costs_by_cost_center_script",
        "pattern_template": "bseg costs by cost center (script)",
        "keywords": ["costs", "cost center", "bseg"],
        "sql_template": """
SELECT
    "kostl" AS cost_center,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS amount
FROM "BSEG"
WHERE "kostl" IS NOT NULL
GROUP BY "kostl"
ORDER BY amount DESC
LIMIT 50
""",
        "required_tables": ["BSEG"],
    },
    {
        "pattern_name": "bseg_amounts_by_profit_center_script",
        "pattern_template": "bseg amounts by profit center (script)",
        "keywords": ["amounts", "profit center", "bseg"],
        "sql_template": """
SELECT
    "prctr" AS profit_center,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS amount
FROM "BSEG"
WHERE "prctr" IS NOT NULL
GROUP BY "prctr"
ORDER BY amount DESC
LIMIT 50
""",
        "required_tables": ["BSEG"],
    },
    {
        "pattern_name": "cepc_profit_centers_by_company_code_script",
        "pattern_template": "profit centers by company code (script)",
        "keywords": ["profit centers", "company code", "cepc"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    COUNT(*) AS profit_center_count
FROM "CEPC"
GROUP BY "bukrs"
ORDER BY profit_center_count DESC
""",
        "required_tables": ["CEPC"],
    },
    {
        "pattern_name": "cepc_profit_centers_by_country_script",
        "pattern_template": "profit centers by country (script)",
        "keywords": ["profit centers", "country", "cepc"],
        "sql_template": """
SELECT
    "land1" AS country,
    COUNT(*) AS profit_center_count
FROM "CEPC"
GROUP BY "land1"
ORDER BY profit_center_count DESC
""",
        "required_tables": ["CEPC"],
    },
    {
        "pattern_name": "ckhs_cost_estimates_by_company_code_script",
        "pattern_template": "cost estimates by company code (script)",
        "keywords": ["cost estimates", "company code", "ckhs"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    COUNT(*) AS estimate_count
FROM "CKHS"
GROUP BY "bukrs"
ORDER BY estimate_count DESC
""",
        "required_tables": ["CKHS"],
    },
    {
        "pattern_name": "ckhs_cost_estimates_by_year_variant_script",
        "pattern_template": "cost estimates by year and variant (script)",
        "keywords": ["cost estimates", "year", "variant", "ckhs"],
        "sql_template": """
SELECT
    "gjahr" AS fiscal_year,
    "bwvar" AS costing_variant,
    COUNT(*) AS estimate_count
FROM "CKHS"
GROUP BY "gjahr", "bwvar"
ORDER BY fiscal_year, costing_variant
""",
        "required_tables": ["CKHS"],
    },
    # ---------------------------------------------------------------------------
    # 10. CKIS / CKIT / CKMLCR / CKMLHD / CKMLPP – PRODUCT COSTING ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "ckis_cost_breakdown_by_material_script",
        "pattern_template": "CKIS cost breakdown by material (script)",
        "keywords": ["ckis", "cost", "breakdown", "material"],
        "sql_template": """
SELECT
    "matnr" AS material,
    SUM(NULLIF(TRIM("wertn"::text), '')::numeric) AS total_cost,
    SUM(NULLIF(TRIM("menge"::text), '')::numeric) AS total_quantity
FROM "CKIS"
GROUP BY "matnr"
ORDER BY total_cost DESC
LIMIT 50
""",
        "required_tables": ["CKIS"],
    },
    {
        "pattern_name": "ckis_cost_breakdown_by_plant_script",
        "pattern_template": "CKIS cost breakdown by plant (script)",
        "keywords": ["ckis", "cost", "breakdown", "plant"],
        "sql_template": """
SELECT
    "werks" AS plant,
    SUM(NULLIF(TRIM("wertn"::text), '')::numeric) AS total_cost
FROM "CKIS"
GROUP BY "werks"
ORDER BY total_cost DESC
""",
        "required_tables": ["CKIS"],
    },
    {
        "pattern_name": "ckis_cost_breakdown_by_cost_element_script",
        "pattern_template": "CKIS cost breakdown by cost element (script)",
        "keywords": ["ckis", "cost", "breakdown", "cost element"],
        "sql_template": """
SELECT
    "kstar" AS cost_element,
    SUM(NULLIF(TRIM("wertn"::text), '')::numeric) AS total_cost
FROM "CKIS"
GROUP BY "kstar"
ORDER BY total_cost DESC
LIMIT 50
""",
        "required_tables": ["CKIS"],
    },
    {
        "pattern_name": "ckis_top_cost_components_by_value_script",
        "pattern_template": "CKIS top cost components by value (script)",
        "keywords": ["ckis", "cost", "components", "value"],
        "sql_template": """
SELECT
    "matnr" AS material,
    "werks" AS plant,
    "elemt" AS component_type,
    "kstar" AS cost_element,
    SUM(NULLIF(TRIM("wertn"::text), '')::numeric) AS value
FROM "CKIS"
GROUP BY "matnr", "werks", "elemt", "kstar"
ORDER BY value DESC
LIMIT 50
""",
        "required_tables": ["CKIS"],
    },
    {
        "pattern_name": "ckit_descriptions_by_costing_number_script",
        "pattern_template": "CKIT descriptions by costing number (script)",
        "keywords": ["ckit", "descriptions", "costing", "number"],
        "sql_template": """
SELECT
    "kalnr" AS costing_number,
    "kadky" AS costing_date_key,
    "spras" AS language,
    "ltext" AS description
FROM "CKIT"
ORDER BY "kalnr", "spras"
LIMIT 200
""",
        "required_tables": ["CKIT"],
    },
    {
        "pattern_name": "ckmlcr_actual_cost_by_material_plant_period_script",
        "pattern_template": "CKMLCR actual cost by material plant period (script)",
        "keywords": ["ckmlcr", "actual", "cost", "material", "plant", "period"],
        "sql_template": """
SELECT
    h."matnr" AS material,
    h."bwkey" AS valuation_area,
    c."bdatj" AS year,
    c."poper" AS period,
    NULLIF(TRIM(c."stprs"::text), '')::numeric AS standard_price,
    NULLIF(TRIM(c."salk3"::text), '')::numeric AS inventory_value
FROM "CKMLCR" AS c
JOIN "CKMLHD" AS h ON c."kalnr" = h."kalnr"
ORDER BY c."bdatj", c."poper", h."matnr", h."bwkey"
LIMIT 200
""",
        "required_tables": ["CKMLCR", "CKMLHD"],
    },
    {
        "pattern_name": "ckmlcr_standard_vs_periodic_price_script",
        "pattern_template": "CKMLCR standard vs periodic price (script)",
        "keywords": ["ckmlcr", "standard", "periodic", "price"],
        "sql_template": """
SELECT
    h."matnr" AS material,
    h."bwkey" AS valuation_area,
    c."bdatj" AS year,
    c."poper" AS period,
    NULLIF(TRIM(c."stprs"::text), '')::numeric AS standard_price,
    NULLIF(TRIM(c."pvprs"::text), '')::numeric AS periodic_price
FROM "CKMLCR" AS c
JOIN "CKMLHD" AS h ON c."kalnr" = h."kalnr"
ORDER BY c."bdatj", c."poper", h."matnr", h."bwkey"
LIMIT 200
""",
        "required_tables": ["CKMLCR", "CKMLHD"],
    },
    {
        "pattern_name": "ckmlpp_inventory_quantity_by_material_period_script",
        "pattern_template": "CKMLPP inventory quantity by material period (script)",
        "keywords": ["ckmlpp", "inventory", "quantity", "material", "period"],
        "sql_template": """
SELECT
    "kalnr" AS costing_number,
    "bdatj" AS year,
    "poper" AS period,
    NULLIF(TRIM("lbkum"::text), '')::numeric AS inventory_qty
FROM "CKMLPP"
ORDER BY "bdatj", "poper", "kalnr"
LIMIT 200
""",
        "required_tables": ["CKMLPP"],
    },
    # ---------------------------------------------------------------------------
    # 11. COEP / COSP – DETAILED CONTROLLING ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "coep_actual_cost_by_cost_element_script",
        "pattern_template": "COEP actual cost by cost element (script)",
        "keywords": ["coep", "actual", "cost", "cost element"],
        "sql_template": """
SELECT
    "kstar" AS cost_element,
    SUM(NULLIF(TRIM("wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP"
GROUP BY "kstar"
ORDER BY actual_amount DESC
LIMIT 50
""",
        "required_tables": ["COEP"],
    },
    {
        "pattern_name": "coep_actual_cost_by_profit_center_script",
        "pattern_template": "COEP actual cost by profit center (script)",
        "keywords": ["coep", "actual", "cost", "profit center"],
        "sql_template": """
SELECT
    s."prctr" AS profit_center,
    SUM(NULLIF(TRIM(c."wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP" AS c
JOIN "CSKS" AS s ON c."objnr" = s."objnr"
WHERE s."prctr" IS NOT NULL
GROUP BY s."prctr"
ORDER BY actual_amount DESC
LIMIT 50
""",
        "required_tables": ["COEP", "CSKS"],
    },
    {
        "pattern_name": "coep_costs_by_material_plant_script",
        "pattern_template": "COEP costs by material and plant (script)",
        "keywords": ["coep", "costs", "material", "plant"],
        "sql_template": """
SELECT
    "matnr" AS material,
    "werks" AS plant,
    SUM(NULLIF(TRIM("wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP"
WHERE "matnr" IS NOT NULL
GROUP BY "matnr", "werks"
ORDER BY actual_amount DESC
LIMIT 50
""",
        "required_tables": ["COEP"],
    },
    {
        "pattern_name": "coep_costs_by_internal_order_script",
        "pattern_template": "COEP costs by internal order (script)",
        "keywords": ["coep", "costs", "internal", "order"],
        "sql_template": """
SELECT
    a."aufnr" AS order_number,
    SUM(NULLIF(TRIM(c."wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP" AS c
JOIN "AUFK" AS a ON c."objnr" = a."objnr"
WHERE a."aufnr" IS NOT NULL
GROUP BY a."aufnr"
ORDER BY actual_amount DESC
LIMIT 50
""",
        "required_tables": ["COEP", "AUFK"],
    },
    {
        "pattern_name": "coep_actual_costs_by_year_period_script",
        "pattern_template": "COEP actual costs by year period (script)",
        "keywords": ["coep", "actual", "costs", "year", "period"],
        "sql_template": """
SELECT
    "gjahr" AS year,
    "perio" AS period,
    SUM(NULLIF(TRIM("wkgbtr"::text), '')::numeric) AS actual_amount
FROM "COEP"
GROUP BY "gjahr", "perio"
ORDER BY "gjahr", "perio"
""",
        "required_tables": ["COEP"],
    },
    {
        "pattern_name": "cosp_planned_cost_by_cost_center_period_script",
        "pattern_template": "COSP planned cost by object year version (script)",
        "keywords": ["cosp", "planned", "cost", "object", "year", "version"],
        "sql_template": """
SELECT
    "objnr" AS object_number,
    "gjahr" AS year,
    "versn" AS version,
    "wrttp" AS value_type,
    SUM(NULLIF(TRIM("wog001"::text), '')::numeric) AS planned_amount
FROM "COSP"
GROUP BY "objnr", "gjahr", "versn", "wrttp"
ORDER BY "gjahr", "objnr"
LIMIT 200
""",
        "required_tables": ["COSP"],
    },
    # ---------------------------------------------------------------------------
    # 12. CRHD / CSKS – WORK CENTER AND COST CENTER ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "crhd_work_centers_by_plant_script",
        "pattern_template": "CRHD work centers by plant (script)",
        "keywords": ["crhd", "work", "centers", "plant"],
        "sql_template": """
SELECT
    "werks" AS plant,
    COUNT(*) AS work_center_count
FROM "CRHD"
GROUP BY "werks"
ORDER BY work_center_count DESC
""",
        "required_tables": ["CRHD"],
    },
    {
        "pattern_name": "crhd_work_centers_by_group_script",
        "pattern_template": "CRHD work centers by group (script)",
        "keywords": ["crhd", "work", "centers", "group"],
        "sql_template": """
SELECT
    "logrp" AS work_center_group,
    COUNT(*) AS work_center_count
FROM "CRHD"
GROUP BY "logrp"
ORDER BY work_center_count DESC
""",
        "required_tables": ["CRHD"],
    },
    {
        "pattern_name": "csks_cost_centers_by_company_code_script",
        "pattern_template": "CSKS cost centers by company code (script)",
        "keywords": ["csks", "cost", "centers", "company code"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    COUNT(*) AS cost_center_count
FROM "CSKS"
GROUP BY "bukrs"
ORDER BY cost_center_count DESC
""",
        "required_tables": ["CSKS"],
    },
    {
        "pattern_name": "csks_cost_centers_by_plant_script",
        "pattern_template": "CSKS cost centers by plant (script)",
        "keywords": ["csks", "cost", "centers", "plant"],
        "sql_template": """
SELECT
    "werks" AS plant,
    COUNT(*) AS cost_center_count
FROM "CSKS"
GROUP BY "werks"
ORDER BY cost_center_count DESC
""",
        "required_tables": ["CSKS"],
    },
    # ---------------------------------------------------------------------------
    # 13. EBAN / EKKO – PROCUREMENT PIPELINE ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "eban_requisitions_by_plant_script",
        "pattern_template": "EBAN requisitions by plant (script)",
        "keywords": ["eban", "requisitions", "plant"],
        "sql_template": """
SELECT
    "werks" AS plant,
    COUNT(*) AS requisition_count
FROM "EBAN"
GROUP BY "werks"
ORDER BY requisition_count DESC
""",
        "required_tables": ["EBAN"],
    },
    {
        "pattern_name": "eban_requisitions_by_material_script",
        "pattern_template": "EBAN requisitions by material (script)",
        "keywords": ["eban", "requisitions", "material"],
        "sql_template": """
SELECT
    "matnr" AS material,
    COUNT(*) AS requisition_count
FROM "EBAN"
GROUP BY "matnr"
ORDER BY requisition_count DESC
LIMIT 50
""",
        "required_tables": ["EBAN"],
    },
    {
        "pattern_name": "eban_requisitions_by_status_script",
        "pattern_template": "EBAN requisitions by status (script)",
        "keywords": ["eban", "requisitions", "status"],
        "sql_template": """
SELECT
    "statu" AS status,
    COUNT(*) AS requisition_count
FROM "EBAN"
GROUP BY "statu"
ORDER BY requisition_count DESC
""",
        "required_tables": ["EBAN"],
    },
    {
        "pattern_name": "ekko_purchase_orders_by_vendor_script",
        "pattern_template": "EKKO purchase orders by vendor (script)",
        "keywords": ["ekko", "purchase", "orders", "vendor"],
        "sql_template": """
SELECT
    "lifnr" AS vendor,
    COUNT(*) AS po_count
FROM "EKKO"
GROUP BY "lifnr"
ORDER BY po_count DESC
LIMIT 50
""",
        "required_tables": ["EKKO"],
    },
    {
        "pattern_name": "ekko_purchase_orders_by_company_code_script",
        "pattern_template": "EKKO purchase orders by company code (script)",
        "keywords": ["ekko", "purchase", "orders", "company code"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    COUNT(*) AS po_count
FROM "EKKO"
GROUP BY "bukrs"
ORDER BY po_count DESC
""",
        "required_tables": ["EKKO"],
    },
    {
        "pattern_name": "ekko_purchase_orders_by_currency_script",
        "pattern_template": "EKKO purchase orders by currency (script)",
        "keywords": ["ekko", "purchase", "orders", "currency"],
        "sql_template": """
SELECT
    "waers" AS currency,
    COUNT(*) AS po_count
FROM "EKKO"
GROUP BY "waers"
ORDER BY po_count DESC
""",
        "required_tables": ["EKKO"],
    },
    {
        "pattern_name": "eban_requisition_to_po_conversion_script",
        "pattern_template": "EBAN requisition to PO conversion (script)",
        "keywords": ["eban", "requisition", "po", "conversion"],
        "sql_template": """
SELECT
    COUNT(*) FILTER (WHERE "ebeln" IS NULL) AS requisitions_without_po,
    COUNT(*) FILTER (WHERE "ebeln" IS NOT NULL) AS requisitions_with_po
FROM "EBAN"
""",
        "required_tables": ["EBAN"],
    },
    # ---------------------------------------------------------------------------
    # 14. MKPF – MATERIAL DOCUMENT ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "mkpf_list_all_documents_script",
        "pattern_template": "MKPF list all material documents (script)",
        "keywords": ["mkpf", "list", "material", "documents"],
        "sql_template": """
SELECT
    "mblnr" AS document_number,
    "mjahr" AS year,
    "blart" AS document_type,
    "budat" AS posting_date,
    "bldat" AS document_date,
    "tcode" AS transaction_code,
    "usnam" AS created_by
FROM "MKPF"
ORDER BY "mjahr" DESC, "mblnr" DESC
LIMIT 200
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_by_year_script",
        "pattern_template": "MKPF documents by year (script)",
        "keywords": ["mkpf", "documents", "year"],
        "sql_template": """
SELECT
    "mjahr" AS year,
    COUNT(*) AS document_count
FROM "MKPF"
GROUP BY "mjahr"
ORDER BY year
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_by_posting_date_script",
        "pattern_template": "MKPF documents by posting date (script)",
        "keywords": ["mkpf", "documents", "posting", "date"],
        "sql_template": """
SELECT
    "budat"::date AS posting_date,
    COUNT(*) AS document_count
FROM "MKPF"
GROUP BY "budat"::date
ORDER BY posting_date
LIMIT 200
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_by_document_type_script",
        "pattern_template": "MKPF documents by document type (script)",
        "keywords": ["mkpf", "documents", "document type"],
        "sql_template": """
SELECT
    "blart" AS document_type,
    COUNT(*) AS document_count
FROM "MKPF"
GROUP BY "blart"
ORDER BY document_count DESC
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_by_tcode_script",
        "pattern_template": "MKPF documents by transaction code (script)",
        "keywords": ["mkpf", "documents", "transaction", "code"],
        "sql_template": """
SELECT
    "tcode" AS transaction_code,
    COUNT(*) AS document_count
FROM "MKPF"
GROUP BY "tcode"
ORDER BY document_count DESC
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_goods_movements_per_day_script",
        "pattern_template": "MKPF goods movements per day (script)",
        "keywords": ["mkpf", "goods", "movements", "day"],
        "sql_template": """
SELECT
    "budat"::date AS posting_date,
    COUNT(*) AS movement_count
FROM "MKPF"
GROUP BY "budat"::date
ORDER BY posting_date
LIMIT 200
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_goods_movements_per_month_script",
        "pattern_template": "MKPF goods movements per month (script)",
        "keywords": ["mkpf", "goods", "movements", "month"],
        "sql_template": """
SELECT
    EXTRACT(YEAR FROM "budat"::date)::int AS year,
    EXTRACT(MONTH FROM "budat"::date)::int AS month,
    COUNT(*) AS movement_count
FROM "MKPF"
GROUP BY EXTRACT(YEAR FROM "budat"::date), EXTRACT(MONTH FROM "budat"::date)
ORDER BY year, month
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_goods_movements_per_user_script",
        "pattern_template": "MKPF goods movements per user (script)",
        "keywords": ["mkpf", "goods", "movements", "user"],
        "sql_template": """
SELECT
    "usnam" AS created_by,
    COUNT(*) AS movement_count
FROM "MKPF"
GROUP BY "usnam"
ORDER BY movement_count DESC
LIMIT 50
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_goods_movements_by_creation_date_script",
        "pattern_template": "MKPF goods movements by creation date (script)",
        "keywords": ["mkpf", "goods", "movements", "creation", "date"],
        "sql_template": """
SELECT
    to_date("cpudt", 'YYYYMMDD') AS creation_date,
    COUNT(*) AS movement_count
FROM "MKPF"
WHERE "cpudt" ~ '^[0-9]{8}$'
  AND "cpudt" <> '00000000'
GROUP BY to_date("cpudt", 'YYYYMMDD')
ORDER BY creation_date
LIMIT 200
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_by_reference_number_script",
        "pattern_template": "MKPF documents by reference number (script)",
        "keywords": ["mkpf", "documents", "reference", "number"],
        "sql_template": """
SELECT
    "xblnr" AS reference_number,
    COUNT(*) AS document_count
FROM "MKPF"
WHERE "xblnr" IS NOT NULL AND "xblnr" <> ''
GROUP BY "xblnr"
ORDER BY document_count DESC
LIMIT 100
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_related_to_deliveries_script",
        "pattern_template": "MKPF documents related to deliveries (script)",
        "keywords": ["mkpf", "documents", "deliveries"],
        "sql_template": """
SELECT
    m."mblnr" AS material_document,
    m."mjahr" AS year,
    m."budat" AS posting_date,
    m."le_vbeln" AS delivery_number
FROM "MKPF" AS m
WHERE m."le_vbeln" IS NOT NULL AND m."le_vbeln" <> ''
ORDER BY m."budat"::date DESC, m."mblnr" DESC
LIMIT 200
""",
        "required_tables": ["MKPF"],
    },
    {
        "pattern_name": "mkpf_documents_linked_to_ewm_script",
        "pattern_template": "MKPF documents linked to EWM (script)",
        "keywords": ["mkpf", "documents", "ewm"],
        "sql_template": """
SELECT
    "mblnr" AS material_document,
    "mjahr" AS year,
    "spe_mdnum_ewm" AS ewm_document
FROM "MKPF"
WHERE "spe_mdnum_ewm" IS NOT NULL AND "spe_mdnum_ewm" <> ''
ORDER BY "mjahr" DESC, "mblnr" DESC
LIMIT 200
""",
        "required_tables": ["MKPF"],
    },
    # ---------------------------------------------------------------------------
    # 15. MVKE – MATERIAL SALES DATA ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "mvke_materials_by_sales_org_script",
        "pattern_template": "MVKE materials by sales org (script)",
        "keywords": ["mvke", "materials", "sales", "org"],
        "sql_template": """
SELECT
    "vkorg" AS sales_org,
    COUNT(DISTINCT "matnr") AS material_count
FROM "MVKE"
GROUP BY "vkorg"
ORDER BY material_count DESC
""",
        "required_tables": ["MVKE"],
    },
    {
        "pattern_name": "mvke_materials_by_distribution_channel_script",
        "pattern_template": "MVKE materials by distribution channel (script)",
        "keywords": ["mvke", "materials", "distribution", "channel"],
        "sql_template": """
SELECT
    "vtweg" AS distribution_channel,
    COUNT(DISTINCT "matnr") AS material_count
FROM "MVKE"
GROUP BY "vtweg"
ORDER BY material_count DESC
""",
        "required_tables": ["MVKE"],
    },
    {
        "pattern_name": "mvke_materials_by_product_hierarchy_script",
        "pattern_template": "MVKE materials by product hierarchy (script)",
        "keywords": ["mvke", "materials", "product", "hierarchy"],
        "sql_template": """
SELECT
    "prodh" AS product_hierarchy,
    COUNT(DISTINCT "matnr") AS material_count
FROM "MVKE"
GROUP BY "prodh"
ORDER BY material_count DESC
LIMIT 100
""",
        "required_tables": ["MVKE"],
    },
    {
        "pattern_name": "mvke_materials_by_pricing_group_script",
        "pattern_template": "MVKE materials by pricing group (script)",
        "keywords": ["mvke", "materials", "pricing", "group"],
        "sql_template": """
SELECT
    "ktgrm" AS pricing_group,
    COUNT(DISTINCT "matnr") AS material_count
FROM "MVKE"
GROUP BY "ktgrm"
ORDER BY material_count DESC
""",
        "required_tables": ["MVKE"],
    },
    {
        "pattern_name": "mvke_materials_with_bonus_eligibility_script",
        "pattern_template": "MVKE materials with bonus eligibility (script)",
        "keywords": ["mvke", "materials", "bonus", "eligibility"],
        "sql_template": """
SELECT
    "vkorg" AS sales_org,
    "vtweg" AS distribution_channel,
    "matnr" AS material,
    "bonus" AS bonus_indicator
FROM "MVKE"
WHERE "bonus" IS NOT NULL AND "bonus" <> ''
ORDER BY "vkorg", "vtweg", "matnr"
LIMIT 200
""",
        "required_tables": ["MVKE"],
    },
    {
        "pattern_name": "mvke_materials_with_delivery_settings_script",
        "pattern_template": "MVKE materials with delivery settings (script)",
        "keywords": ["mvke", "materials", "delivery", "settings"],
        "sql_template": """
SELECT
    "matnr" AS material,
    "dwerk" AS delivery_plant,
    "vrkme" AS sales_unit
FROM "MVKE"
WHERE "dwerk" IS NOT NULL AND "dwerk" <> ''
ORDER BY "dwerk", "matnr"
LIMIT 200
""",
        "required_tables": ["MVKE"],
    },
    {
        "pattern_name": "mvke_materials_availability_status_script",
        "pattern_template": "MVKE materials availability status (script)",
        "keywords": ["mvke", "materials", "availability", "status"],
        "sql_template": """
SELECT
    "vmsta" AS sales_status,
    COUNT(*) AS material_sales_records
FROM "MVKE"
GROUP BY "vmsta"
ORDER BY material_sales_records DESC
""",
        "required_tables": ["MVKE"],
    },
    # ---------------------------------------------------------------------------
    # 16. RBKP – VENDOR INVOICE ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "rbkp_list_all_invoices_script",
        "pattern_template": "RBKP list all vendor invoices (script)",
        "keywords": ["rbkp", "list", "vendor", "invoices"],
        "sql_template": """
SELECT
    "belnr" AS invoice_number,
    "gjahr" AS fiscal_year,
    "bukrs" AS company_code,
    "lifnr" AS vendor,
    "waers" AS currency,
    "budat" AS posting_date,
    "rmwwr" AS amount
FROM "RBKP"
ORDER BY "gjahr" DESC, "belnr" DESC
LIMIT 200
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_by_company_code_script",
        "pattern_template": "RBKP invoices by company code (script)",
        "keywords": ["rbkp", "invoices", "company code"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    COUNT(*) AS invoice_count,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS total_amount
FROM "RBKP"
GROUP BY "bukrs"
ORDER BY total_amount DESC
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_by_vendor_script",
        "pattern_template": "RBKP invoices by vendor (script)",
        "keywords": ["rbkp", "invoices", "vendor"],
        "sql_template": """
SELECT
    "lifnr" AS vendor,
    COUNT(*) AS invoice_count,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS total_amount
FROM "RBKP"
GROUP BY "lifnr"
ORDER BY total_amount DESC
LIMIT 100
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_total_invoice_value_by_currency_script",
        "pattern_template": "RBKP total invoice value by currency (script)",
        "keywords": ["rbkp", "invoice", "value", "currency"],
        "sql_template": """
SELECT
    "waers" AS currency,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS total_amount
FROM "RBKP"
GROUP BY "waers"
ORDER BY total_amount DESC
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_by_posting_year_script",
        "pattern_template": "RBKP invoices by posting year (script)",
        "keywords": ["rbkp", "invoices", "posting", "year"],
        "sql_template": """
SELECT
    "gjahr" AS fiscal_year,
    COUNT(*) AS invoice_count,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS total_amount
FROM "RBKP"
GROUP BY "gjahr"
ORDER BY fiscal_year
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_by_posting_date_script",
        "pattern_template": "RBKP invoices by posting date (script)",
        "keywords": ["rbkp", "invoices", "posting", "date"],
        "sql_template": """
SELECT
    "budat"::date AS posting_date,
    COUNT(*) AS invoice_count,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS total_amount
FROM "RBKP"
GROUP BY "budat"::date
ORDER BY posting_date
LIMIT 200
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_by_creation_date_script",
        "pattern_template": "RBKP invoices by creation date (script)",
        "keywords": ["rbkp", "invoices", "creation", "date"],
        "sql_template": """
SELECT
    "cpudt"::date AS creation_date,
    COUNT(*) AS invoice_count
FROM "RBKP"
GROUP BY "cpudt"::date
ORDER BY creation_date
LIMIT 200
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_by_payment_terms_script",
        "pattern_template": "RBKP invoices by payment terms (script)",
        "keywords": ["rbkp", "invoices", "payment", "terms"],
        "sql_template": """
SELECT
    "zterm" AS payment_terms,
    COUNT(*) AS invoice_count,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS total_amount
FROM "RBKP"
GROUP BY "zterm"
ORDER BY total_amount DESC
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_blocked_released_cancelled_invoices_script",
        "pattern_template": "RBKP invoice status blocked released cancelled (script)",
        "keywords": ["rbkp", "invoice", "status", "blocked"],
        "sql_template": """
SELECT
    "rbstat" AS status,
    COUNT(*) AS invoice_count
FROM "RBKP"
GROUP BY "rbstat"
ORDER BY invoice_count DESC
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "rbkp_invoices_with_tax_and_totals_by_vendor_script",
        "pattern_template": "RBKP total tax amounts by vendor (script)",
        "keywords": ["rbkp", "tax", "amounts", "vendor"],
        "sql_template": """
SELECT
    "lifnr" AS vendor,
    SUM(NULLIF(TRIM("wmwst1"::text), '')::numeric) AS tax_amount_1,
    SUM(NULLIF(TRIM("wmwst2"::text), '')::numeric) AS tax_amount_2
FROM "RBKP"
GROUP BY "lifnr"
ORDER BY (COALESCE(SUM(NULLIF(TRIM("wmwst1"::text), '')::numeric),0)
        + COALESCE(SUM(NULLIF(TRIM("wmwst2"::text), '')::numeric),0)) DESC
LIMIT 100
""",
        "required_tables": ["RBKP"],
    },
    # ---------------------------------------------------------------------------
    # RSEG – INVOICE ITEMS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "rseg_invoice_items_by_vendor_script",
        "pattern_template": "RSEG invoice items by vendor (script)",
        "keywords": ["rseg", "invoice", "items", "vendor"],
        "sql_template": """
SELECT
    "lifnr" AS vendor,
    COUNT(*) AS item_count,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS total_value
FROM "RSEG"
GROUP BY "lifnr"
ORDER BY total_value DESC
LIMIT 100
""",
        "required_tables": ["RSEG"],
    },
    {
        "pattern_name": "rseg_invoice_items_by_material_script",
        "pattern_template": "RSEG invoice items by material (script)",
        "keywords": ["rseg", "invoice", "items", "material"],
        "sql_template": """
SELECT
    "matnr" AS material,
    COUNT(*) AS item_count,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS total_value
FROM "RSEG"
GROUP BY "matnr"
ORDER BY total_value DESC
LIMIT 100
""",
        "required_tables": ["RSEG"],
    },
    {
        "pattern_name": "rseg_quantity_purchased_per_material_script",
        "pattern_template": "RSEG quantity purchased per material (script)",
        "keywords": ["rseg", "quantity", "purchased", "material"],
        "sql_template": """
SELECT
    "matnr" AS material,
    SUM(NULLIF(TRIM("menge"::text), '')::numeric) AS quantity
FROM "RSEG"
GROUP BY "matnr"
ORDER BY quantity DESC
LIMIT 100
""",
        "required_tables": ["RSEG"],
    },
    {
        "pattern_name": "rseg_quantity_purchased_per_vendor_script",
        "pattern_template": "RSEG quantity purchased per vendor (script)",
        "keywords": ["rseg", "quantity", "purchased", "vendor"],
        "sql_template": """
SELECT
    "lifnr" AS vendor,
    SUM(NULLIF(TRIM("menge"::text), '')::numeric) AS quantity
FROM "RSEG"
GROUP BY "lifnr"
ORDER BY quantity DESC
LIMIT 100
""",
        "required_tables": ["RSEG"],
    },
    {
        "pattern_name": "rseg_invoice_items_po_linkage_script",
        "pattern_template": "RSEG invoice items with without purchase orders (script)",
        "keywords": ["rseg", "invoice", "items", "purchase", "orders"],
        "sql_template": """
SELECT
    COUNT(*) FILTER (WHERE "ebeln" IS NOT NULL) AS items_with_po,
    COUNT(*) FILTER (WHERE "ebeln" IS NULL) AS items_without_po
FROM "RSEG"
""",
        "required_tables": ["RSEG"],
    },
    {
        "pattern_name": "rseg_item_taxes_by_tax_code_script",
        "pattern_template": "RSEG item taxes by tax code (script)",
        "keywords": ["rseg", "item", "taxes", "tax", "code"],
        "sql_template": """
SELECT
    "mwskz" AS tax_code,
    COUNT(*) AS item_count,
    SUM(NULLIF(TRIM("wrbtr"::text), '')::numeric) AS total_value
FROM "RSEG"
GROUP BY "mwskz"
ORDER BY total_value DESC
""",
        "required_tables": ["RSEG"],
    },
    # ---------------------------------------------------------------------------
    # RESB – MATERIAL RESERVATIONS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "resb_list_all_reservations_script",
        "pattern_template": "RESB list all material reservations (script)",
        "keywords": ["resb", "list", "material", "reservations"],
        "sql_template": """
SELECT
    "rsnum" AS reservation_number,
    "rspos" AS item,
    "matnr" AS material,
    "werks" AS plant,
    "lgort" AS storage_location,
    "bdter" AS requirement_date,
    "bdmng" AS required_qty
FROM "RESB"
ORDER BY "rsnum", "rspos"
LIMIT 200
""",
        "required_tables": ["RESB"],
    },
    {
        "pattern_name": "resb_reservations_by_material_script",
        "pattern_template": "RESB reservations by material (script)",
        "keywords": ["resb", "reservations", "material"],
        "sql_template": """
SELECT
    "matnr" AS material,
    COUNT(*) AS reservation_count,
    SUM(NULLIF(TRIM("bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB"
GROUP BY "matnr"
ORDER BY reserved_qty DESC
LIMIT 100
""",
        "required_tables": ["RESB"],
    },
    {
        "pattern_name": "resb_reservations_by_plant_script",
        "pattern_template": "RESB reservations by plant (script)",
        "keywords": ["resb", "reservations", "plant"],
        "sql_template": """
SELECT
    "werks" AS plant,
    COUNT(*) AS reservation_count,
    SUM(NULLIF(TRIM("bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB"
GROUP BY "werks"
ORDER BY reserved_qty DESC
""",
        "required_tables": ["RESB"],
    },
    {
        "pattern_name": "resb_reserved_quantities_by_storage_location_script",
        "pattern_template": "RESB reserved quantities by storage location (script)",
        "keywords": ["resb", "reserved", "quantities", "storage", "location"],
        "sql_template": """
SELECT
    "werks" AS plant,
    "lgort" AS storage_location,
    SUM(NULLIF(TRIM("bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB"
GROUP BY "werks", "lgort"
ORDER BY reserved_qty DESC
LIMIT 100
""",
        "required_tables": ["RESB"],
    },
    {
        "pattern_name": "resb_reservations_linked_to_orders_and_pr_script",
        "pattern_template": "RESB reservations linked to orders requisitions (script)",
        "keywords": ["resb", "reservations", "orders", "requisitions"],
        "sql_template": """
SELECT
    COUNT(*) FILTER (WHERE "aufnr" IS NOT NULL) AS reservations_for_orders,
    COUNT(*) FILTER (WHERE "banfn" IS NOT NULL) AS reservations_for_requisitions
FROM "RESB"
""",
        "required_tables": ["RESB"],
    },
    {
        "pattern_name": "resb_materials_with_highest_reservation_demand_script",
        "pattern_template": "RESB materials with highest reservation demand (script)",
        "keywords": ["resb", "materials", "highest", "reservation", "demand"],
        "sql_template": """
SELECT
    "matnr" AS material,
    SUM(NULLIF(TRIM("bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB"
GROUP BY "matnr"
ORDER BY reserved_qty DESC
LIMIT 50
""",
        "required_tables": ["RESB"],
    },
    # ---------------------------------------------------------------------------
    # STKO / STPO – BOM
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "stko_bom_headers_overview_script",
        "pattern_template": "STKO BOM headers overview (script)",
        "keywords": ["stko", "bom", "headers", "overview"],
        "sql_template": """
SELECT
    "stlty" AS bom_category,
    "stlnr" AS bom_number,
    "stlal" AS alternative_bom,
    "datuv" AS valid_from,
    "stlst" AS status,
    "stktx" AS description
FROM "STKO"
ORDER BY "stlty", "stlnr"
LIMIT 200
""",
        "required_tables": ["STKO"],
    },
    {
        "pattern_name": "stko_boms_by_validity_date_script",
        "pattern_template": "STKO BOMs by validity date (script)",
        "keywords": ["stko", "boms", "validity", "date"],
        "sql_template": """
SELECT
    "datuv"::date AS valid_from,
    COUNT(*) AS bom_count
FROM "STKO"
GROUP BY "datuv"::date
ORDER BY valid_from
LIMIT 200
""",
        "required_tables": ["STKO"],
    },
    {
        "pattern_name": "stko_active_vs_deleted_boms_script",
        "pattern_template": "STKO active vs deleted BOMs (script)",
        "keywords": ["stko", "active", "deleted", "boms"],
        "sql_template": """
SELECT
    "loekz" AS deletion_flag,
    COUNT(*) AS bom_count
FROM "STKO"
GROUP BY "loekz"
ORDER BY bom_count DESC
""",
        "required_tables": ["STKO"],
    },
    {
        "pattern_name": "stko_boms_changed_by_user_script",
        "pattern_template": "STKO BOMs modified by user (script)",
        "keywords": ["stko", "boms", "modified", "user"],
        "sql_template": """
SELECT
    "aenam" AS changed_by,
    COUNT(*) AS bom_count
FROM "STKO"
GROUP BY "aenam"
ORDER BY bom_count DESC
LIMIT 50
""",
        "required_tables": ["STKO"],
    },
    {
        "pattern_name": "stpo_components_per_bom_script",
        "pattern_template": "STPO components per BOM (script)",
        "keywords": ["stpo", "components", "bom"],
        "sql_template": """
SELECT
    "stlty" AS bom_category,
    "stlnr" AS bom_number,
    COUNT(*) AS component_count
FROM "STPO"
GROUP BY "stlty", "stlnr"
ORDER BY component_count DESC
LIMIT 100
""",
        "required_tables": ["STPO"],
    },
    {
        "pattern_name": "stpo_component_quantities_per_bom_script",
        "pattern_template": "STPO component quantities per BOM (script)",
        "keywords": ["stpo", "component", "quantities", "bom"],
        "sql_template": """
SELECT
    "stlty" AS bom_category,
    "stlnr" AS bom_number,
    SUM(NULLIF(TRIM("menge"::text), '')::numeric) AS total_component_qty
FROM "STPO"
GROUP BY "stlty", "stlnr"
ORDER BY total_component_qty DESC
LIMIT 100
""",
        "required_tables": ["STPO"],
    },
    {
        "pattern_name": "stpo_materials_used_as_components_script",
        "pattern_template": "STPO materials used as components in multiple BOMs (script)",
        "keywords": ["stpo", "materials", "components", "boms"],
        "sql_template": """
SELECT
    "idnrk" AS component_material,
    COUNT(DISTINCT "stlnr") AS bom_count
FROM "STPO"
GROUP BY "idnrk"
ORDER BY bom_count DESC
LIMIT 100
""",
        "required_tables": ["STPO"],
    },
    # ---------------------------------------------------------------------------
    # T016T – INDUSTRY
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "t016t_customers_by_industry_script",
        "pattern_template": "T016T customers by industry (script)",
        "keywords": ["t016t", "customers", "industry"],
        "sql_template": """
SELECT
    t."brtxt" AS industry,
    COUNT(*) AS customer_count
FROM "KNA1" AS k
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY t."brtxt"
ORDER BY customer_count DESC
""",
        "required_tables": ["KNA1", "T016T"],
    },
    {
        "pattern_name": "t016t_orders_by_industry_script",
        "pattern_template": "T016T orders and value by industry (script)",
        "keywords": ["t016t", "orders", "industry"],
        "sql_template": """
SELECT
    t."brtxt" AS industry,
    COUNT(*) AS order_count,
    SUM(NULLIF(TRIM(v."netwr"::text), '')::numeric) AS total_order_value
FROM "VBAK" AS v
JOIN "KNA1" AS k ON v."kunnr" = k."kunnr"
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
GROUP BY t."brtxt"
ORDER BY total_order_value DESC
""",
        "required_tables": ["VBAK", "KNA1", "T016T"],
    },
    # ---------------------------------------------------------------------------
    # 17. VBAK / VBAP / VBEP / VBFA / VBRK / VBRP – SALES ORDERS & BILLING
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "vbak_list_all_sales_orders_script",
        "pattern_template": "VBAK list all sales orders (script)",
        "keywords": ["vbak", "list", "sales", "orders"],
        "sql_template": """
SELECT
    "vbeln" AS sales_order,
    "kunnr" AS customer,
    "vkorg" AS sales_org,
    "vtweg" AS distribution_channel,
    "spart" AS division,
    "audat" AS order_date,
    "netwr" AS net_value,
    "waerk" AS currency
FROM "VBAK"
ORDER BY "audat"::date DESC, "vbeln" DESC
LIMIT 200
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "vbak_orders_by_customer_script",
        "pattern_template": "VBAK orders and value by customer (script)",
        "keywords": ["vbak", "orders", "customer"],
        "sql_template": """
SELECT
    "kunnr" AS customer,
    COUNT(*) AS order_count,
    SUM(NULLIF(TRIM("netwr"::text), '')::numeric) AS total_order_value
FROM "VBAK"
GROUP BY "kunnr"
ORDER BY total_order_value DESC
LIMIT 100
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "vbak_orders_by_sales_org_script",
        "pattern_template": "VBAK orders and value by sales organization (script)",
        "keywords": ["vbak", "orders", "sales", "org"],
        "sql_template": """
SELECT
    "vkorg" AS sales_org,
    COUNT(*) AS order_count,
    SUM(NULLIF(TRIM("netwr"::text), '')::numeric) AS total_order_value
FROM "VBAK"
GROUP BY "vkorg"
ORDER BY total_order_value DESC
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "vbak_orders_per_day_month_year_script",
        "pattern_template": "VBAK orders per day with year month (script)",
        "keywords": ["vbak", "orders", "day", "month", "year"],
        "sql_template": """
SELECT
    EXTRACT(YEAR FROM "audat"::date)::int AS year,
    EXTRACT(MONTH FROM "audat"::date)::int AS month,
    EXTRACT(DAY FROM "audat"::date)::int AS day,
    COUNT(*) AS order_count
FROM "VBAK"
GROUP BY EXTRACT(YEAR FROM "audat"::date),
         EXTRACT(MONTH FROM "audat"::date),
         EXTRACT(DAY FROM "audat"::date)
ORDER BY year, month, day
LIMIT 365
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "vbak_orders_by_sales_office_group_script",
        "pattern_template": "VBAK orders by sales office and group (script)",
        "keywords": ["vbak", "orders", "sales", "office", "group"],
        "sql_template": """
SELECT
    "vkbur" AS sales_office,
    "vkgrp" AS sales_group,
    COUNT(*) AS order_count,
    SUM(NULLIF(TRIM("netwr"::text), '')::numeric) AS total_order_value
FROM "VBAK"
GROUP BY "vkbur", "vkgrp"
ORDER BY total_order_value DESC
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "vbak_open_blocked_cancelled_orders_script",
        "pattern_template": "VBAK open blocked cancelled orders (script)",
        "keywords": ["vbak", "open", "blocked", "cancelled", "orders"],
        "sql_template": """
SELECT
    "faksk" AS billing_block_status,
    "lifsk" AS delivery_block_status,
    COUNT(*) AS order_count
FROM "VBAK"
GROUP BY "faksk", "lifsk"
ORDER BY order_count DESC
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "vbap_products_sold_by_quantity_and_value_script",
        "pattern_template": "VBAP products sold by quantity and value (script)",
        "keywords": ["vbap", "products", "sold", "quantity", "value"],
        "sql_template": """
SELECT
    "matnr" AS material,
    SUM(NULLIF(TRIM("kwmeng"::text), '')::numeric) AS total_order_qty,
    SUM(NULLIF(TRIM("netwr"::text), '')::numeric) AS total_order_value
FROM "VBAP"
GROUP BY "matnr"
ORDER BY total_order_value DESC
LIMIT 100
""",
        "required_tables": ["VBAP"],
    },
    {
        "pattern_name": "vbap_items_by_plant_and_storage_location_script",
        "pattern_template": "VBAP items by plant and storage location (script)",
        "keywords": ["vbap", "items", "plant", "storage", "location"],
        "sql_template": """
SELECT
    "werks" AS plant,
    "lgort" AS storage_location,
    COUNT(*) AS item_count,
    SUM(NULLIF(TRIM("kwmeng"::text), '')::numeric) AS total_order_qty
FROM "VBAP"
GROUP BY "werks", "lgort"
ORDER BY total_order_qty DESC
LIMIT 100
""",
        "required_tables": ["VBAP"],
    },
    {
        "pattern_name": "vbap_order_items_per_order_script",
        "pattern_template": "VBAP order items per order (script)",
        "keywords": ["vbap", "order", "items", "order"],
        "sql_template": """
SELECT
    "vbeln" AS sales_order,
    COUNT(*) AS item_count,
    SUM(NULLIF(TRIM("kwmeng"::text), '')::numeric) AS total_order_qty
FROM "VBAP"
GROUP BY "vbeln"
ORDER BY item_count DESC
LIMIT 100
""",
        "required_tables": ["VBAP"],
    },
    {
        "pattern_name": "vbep_delivery_schedule_by_order_script",
        "pattern_template": "VBEP delivery schedule by order (script)",
        "keywords": ["vbep", "delivery", "schedule", "order"],
        "sql_template": """
SELECT
    "vbeln" AS sales_order,
    COUNT(*) AS schedule_line_count,
    SUM(NULLIF(TRIM("bmeng"::text), '')::numeric) AS scheduled_qty
FROM "VBEP"
GROUP BY "vbeln"
ORDER BY scheduled_qty DESC
LIMIT 100
""",
        "required_tables": ["VBEP"],
    },
    {
        "pattern_name": "vbep_scheduled_quantity_by_date_script",
        "pattern_template": "VBEP scheduled quantity by date (script)",
        "keywords": ["vbep", "scheduled", "quantity", "date"],
        "sql_template": """
SELECT
    "edatu"::date AS schedule_date,
    SUM(NULLIF(TRIM("bmeng"::text), '')::numeric) AS scheduled_qty
FROM "VBEP"
GROUP BY "edatu"::date
ORDER BY schedule_date
LIMIT 200
""",
        "required_tables": ["VBEP"],
    },
    {
        "pattern_name": "vbep_confirmed_quantity_by_product_script",
        "pattern_template": "VBEP confirmed quantity by product (script)",
        "keywords": ["vbep", "confirmed", "quantity", "product"],
        "sql_template": """
SELECT
    p."matnr" AS material,
    SUM(NULLIF(TRIM(e."wmeng"::text), '')::numeric) AS confirmed_qty
FROM "VBEP" AS e
JOIN "VBAP" AS p ON e."vbeln" = p."vbeln" AND e."posnr" = p."posnr"
GROUP BY p."matnr"
ORDER BY confirmed_qty DESC
LIMIT 100
""",
        "required_tables": ["VBEP", "VBAP"],
    },
    {
        "pattern_name": "vbfa_sales_flow_order_to_delivery_to_invoice_script",
        "pattern_template": "VBFA sales order delivery invoice flow (script)",
        "keywords": ["vbfa", "sales", "flow", "order", "delivery", "invoice"],
        "sql_template": """
SELECT
    f."vbelv" AS preceding_document,
    f."vbtyp_v" AS preceding_type,
    f."vbeln" AS subsequent_document,
    f."vbtyp_n" AS subsequent_type,
    COUNT(*) AS link_count
FROM "VBFA" AS f
GROUP BY f."vbelv", f."vbtyp_v", f."vbeln", f."vbtyp_n"
ORDER BY link_count DESC
LIMIT 200
""",
        "required_tables": ["VBFA"],
    },
    {
        "pattern_name": "vbfa_orders_linked_to_deliveries_and_invoices_script",
        "pattern_template": "VBFA orders linked to deliveries and invoices (script)",
        "keywords": ["vbfa", "orders", "linked", "deliveries", "invoices"],
        "sql_template": """
SELECT
    COUNT(*) FILTER (WHERE "vbtyp_v" = 'C' AND "vbtyp_n" = 'J') AS order_to_delivery_links,
    COUNT(*) FILTER (WHERE "vbtyp_v" = 'J' AND "vbtyp_n" = 'M') AS delivery_to_invoice_links
FROM "VBFA"
""",
        "required_tables": ["VBFA"],
    },
    {
        "pattern_name": "vbrk_list_all_billing_documents_script",
        "pattern_template": "VBRK list all billing documents (script)",
        "keywords": ["vbrk", "list", "billing", "documents"],
        "sql_template": """
SELECT
    "vbeln" AS billing_document,
    "fkart" AS billing_type,
    "fkdat" AS billing_date,
    "vkorg" AS sales_org,
    "vtweg" AS dist_channel,
    "spart" AS division,
    "kunag" AS customer
FROM "VBRK"
ORDER BY "fkdat"::date DESC, "vbeln" DESC
LIMIT 200
""",
        "required_tables": ["VBRK"],
    },
    {
        "pattern_name": "vbrk_revenue_by_customer_script",
        "pattern_template": "VBRK VBRP total revenue by customer (script)",
        "keywords": ["vbrk", "revenue", "customer"],
        "sql_template": """
SELECT
    k."name1" AS customer,
    k."land1" AS country,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
GROUP BY k."name1", k."land1"
ORDER BY revenue DESC
LIMIT 100
""",
        "required_tables": ["vbrp", "VBRK", "KNA1"],
    },
    {
        "pattern_name": "vbrk_revenue_by_month_and_year_script",
        "pattern_template": "VBRK VBRP revenue by month and year (script)",
        "keywords": ["vbrk", "revenue", "month", "year"],
        "sql_template": """
SELECT
    EXTRACT(YEAR FROM "fkdat"::date)::int AS year,
    EXTRACT(MONTH FROM "fkdat"::date)::int AS month,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
GROUP BY EXTRACT(YEAR FROM "fkdat"::date), EXTRACT(MONTH FROM "fkdat"::date)
ORDER BY year, month
""",
        "required_tables": ["vbrp", "VBRK"],
    },
    {
        "pattern_name": "vbrk_revenue_by_sales_org_and_channel_script",
        "pattern_template": "VBRK VBRP revenue by sales org and channel (script)",
        "keywords": ["vbrk", "revenue", "sales", "org", "channel"],
        "sql_template": """
SELECT
    h."vkorg" AS sales_org,
    h."vtweg" AS dist_channel,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
GROUP BY h."vkorg", h."vtweg"
ORDER BY revenue DESC
""",
        "required_tables": ["vbrp", "VBRK"],
    },
    {
        "pattern_name": "vbrk_revenue_by_country_script",
        "pattern_template": "VBRK VBRP revenue by country (script)",
        "keywords": ["vbrk", "revenue", "country"],
        "sql_template": """
SELECT
    k."land1" AS country,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS revenue
FROM "vbrp" AS p
JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
JOIN "KNA1" AS k ON h."kunag" = k."kunnr"
GROUP BY k."land1"
ORDER BY revenue DESC
""",
        "required_tables": ["vbrp", "VBRK", "KNA1"],
    },
    {
        "pattern_name": "vbrp_product_profitability_proxy_script",
        "pattern_template": "VBRP product revenue and quantity profitability proxy (script)",
        "keywords": ["vbrp", "product", "profitability", "revenue"],
        "sql_template": """
SELECT
    m."maktx" AS product,
    p."matnr" AS material,
    SUM(NULLIF(TRIM(p."fkimg"::text), '')::numeric) AS quantity_sold,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS sales_revenue
FROM "vbrp" AS p
LEFT JOIN "MAKT" AS m ON p."matnr" = m."matnr"
GROUP BY m."maktx", p."matnr"
ORDER BY sales_revenue DESC
LIMIT 100
""",
        "required_tables": ["vbrp", "MAKT"],
    },
    # ---------------------------------------------------------------------------
    # 18. PIPELINE / CROSS-TABLE / ADVANCED ANALYTICS
    # ---------------------------------------------------------------------------
    {
        "pattern_name": "pipeline_orders_with_delivery_schedules_script",
        "pattern_template": "pipeline orders with delivery schedules (script)",
        "keywords": ["pipeline", "orders", "delivery", "schedules"],
        "sql_template": """
SELECT
    v."vbeln" AS sales_order,
    COUNT(DISTINCT a."posnr") AS item_count,
    COUNT(DISTINCT e."etenr") AS schedule_line_count
FROM "VBAK" AS v
JOIN "VBAP" AS a ON v."vbeln" = a."vbeln"
LEFT JOIN "VBEP" AS e ON a."vbeln" = e."vbeln" AND a."posnr" = e."posnr"
GROUP BY v."vbeln"
ORDER BY schedule_line_count DESC
LIMIT 100
""",
        "required_tables": ["VBAK", "VBAP", "VBEP"],
    },
    {
        "pattern_name": "pipeline_orders_with_delayed_deliveries_script",
        "pattern_template": "pipeline orders with delayed deliveries (script)",
        "keywords": ["pipeline", "orders", "delayed", "deliveries"],
        "sql_template": """
SELECT
    e."vbeln" AS sales_order,
    MIN(to_date(e."edatu", 'YYYYMMDD')) AS first_scheduled_date,
    MAX(to_date(e."wadat", 'YYYYMMDD')) AS last_actual_delivery_date,
    (MAX(to_date(e."wadat", 'YYYYMMDD')) - MIN(to_date(e."edatu", 'YYYYMMDD'))) AS delay_days
FROM "VBEP" AS e
WHERE e."wadat" IS NOT NULL
  AND e."edatu" ~ '^[0-9]{8}$'
  AND e."edatu" <> '00000000'
  AND e."wadat" ~ '^[0-9]{8}$'
  AND e."wadat" <> '00000000'
GROUP BY e."vbeln"
HAVING MAX(to_date(e."wadat", 'YYYYMMDD')) > MIN(to_date(e."edatu", 'YYYYMMDD'))
ORDER BY delay_days DESC
LIMIT 100
""",
        "required_tables": ["VBEP"],
    },
    {
        "pattern_name": "order_to_cash_orders_converted_to_invoices_script",
        "pattern_template": "order to cash orders converted to invoices (script)",
        "keywords": ["order", "cash", "orders", "converted", "invoices"],
        "sql_template": """
SELECT
    v."vbeln" AS sales_order,
    COUNT(DISTINCT h."vbeln") AS billing_documents,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS billed_revenue
FROM "VBAK" AS v
JOIN "VBFA" AS f ON f."vbelv" = v."vbeln"
JOIN "VBRK" AS h ON f."vbeln" = h."vbeln"
JOIN "vbrp" AS p ON h."vbeln" = p."vbeln"
GROUP BY v."vbeln"
ORDER BY billed_revenue DESC
LIMIT 100
""",
        "required_tables": ["VBAK", "VBFA", "VBRK", "vbrp"],
    },
    {
        "pattern_name": "daily_sales_invoices_goods_movements_script",
        "pattern_template": "daily sales invoices goods movements last 30 days (script)",
        "keywords": ["daily", "sales", "invoices", "goods", "movements"],
        "sql_template": """
SELECT
    d.day::date AS date,
    COALESCE(s.sales_amount, 0) AS sales_amount,
    COALESCE(i.invoice_amount, 0) AS invoice_amount,
    COALESCE(g.movement_count, 0) AS goods_movements
FROM (
    SELECT generate_series(
        (CURRENT_DATE - INTERVAL '30 days')::date,
        CURRENT_DATE,
        INTERVAL '1 day'
    ) AS day
) AS d
LEFT JOIN (
    SELECT
        "fkdat"::date AS day,
        SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS sales_amount
    FROM "vbrp" AS p
    JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
    GROUP BY "fkdat"::date
) AS s ON d.day = s.day
LEFT JOIN (
    SELECT
        "budat"::date AS day,
        SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS invoice_amount
    FROM "RBKP"
    GROUP BY "budat"::date
) AS i ON d.day = i.day
LEFT JOIN (
    SELECT
        "budat"::date AS day,
        COUNT(*) AS movement_count
    FROM "MKPF"
    GROUP BY "budat"::date
) AS g ON d.day = g.day
ORDER BY d.day
""",
        "required_tables": ["vbrp", "VBRK", "RBKP", "MKPF"],
    },
    {
        "pattern_name": "monthly_vendor_spending_script",
        "pattern_template": "monthly vendor spending by company code (script)",
        "keywords": ["monthly", "vendor", "spending", "company", "code"],
        "sql_template": """
SELECT
    "bukrs" AS company_code,
    EXTRACT(YEAR FROM "budat"::date)::int AS year,
    EXTRACT(MONTH FROM "budat"::date)::int AS month,
    SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS vendor_spend
FROM "RBKP"
GROUP BY "bukrs",
         EXTRACT(YEAR FROM "budat"::date),
         EXTRACT(MONTH FROM "budat"::date)
ORDER BY company_code, year, month
""",
        "required_tables": ["RBKP"],
    },
    {
        "pattern_name": "yearly_revenue_and_procurement_cost_script",
        "pattern_template": "yearly revenue vs procurement cost (script)",
        "keywords": ["yearly", "revenue", "procurement", "cost"],
        "sql_template": """
SELECT
    y.year,
    y.sales_revenue,
    p.procurement_cost
FROM (
    SELECT
        EXTRACT(YEAR FROM h."fkdat"::date)::int AS year,
        SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS sales_revenue
    FROM "vbrp" AS p
    JOIN "VBRK" AS h ON p."vbeln" = h."vbeln"
    GROUP BY EXTRACT(YEAR FROM h."fkdat"::date)
) AS y
LEFT JOIN (
    SELECT
        EXTRACT(YEAR FROM "budat"::date)::int AS year,
        SUM(NULLIF(TRIM("rmwwr"::text), '')::numeric) AS procurement_cost
    FROM "RBKP"
    GROUP BY EXTRACT(YEAR FROM "budat"::date)
) AS p ON y.year = p.year
ORDER BY y.year
""",
        "required_tables": ["vbrp", "VBRK", "RBKP"],
    },
    {
        "pattern_name": "advanced_customer_repeat_orders_script",
        "pattern_template": "advanced repeat customer analysis (script)",
        "keywords": ["advanced", "repeat", "customer", "analysis"],
        "sql_template": """
SELECT
    "kunnr" AS customer,
    COUNT(*) AS order_count,
    SUM(NULLIF(TRIM("netwr"::text), '')::numeric) AS total_order_value
FROM "VBAK"
GROUP BY "kunnr"
HAVING COUNT(*) > 1
ORDER BY total_order_value DESC
LIMIT 100
""",
        "required_tables": ["VBAK"],
    },
    {
        "pattern_name": "advanced_product_demand_trends_script",
        "pattern_template": "advanced product demand trends by month (script)",
        "keywords": ["advanced", "product", "demand", "trends"],
        "sql_template": """
SELECT
    a."matnr" AS material,
    EXTRACT(YEAR FROM v."audat"::date)::int AS year,
    EXTRACT(MONTH FROM v."audat"::date)::int AS month,
    SUM(NULLIF(TRIM(a."kwmeng"::text), '')::numeric) AS order_qty
FROM "VBAP" AS a
JOIN "VBAK" AS v ON a."vbeln" = v."vbeln"
GROUP BY a."matnr",
         EXTRACT(YEAR FROM v."audat"::date),
         EXTRACT(MONTH FROM v."audat"::date)
ORDER BY a."matnr", year, month
LIMIT 500
""",
        "required_tables": ["VBAP", "VBAK"],
    },
    {
        "pattern_name": "advanced_delivery_lead_times_script",
        "pattern_template": "advanced delivery lead times per order (script)",
        "keywords": ["advanced", "delivery", "lead", "times"],
        "sql_template": """
SELECT
    "vbeln" AS sales_order,
    AVG(to_date("wadat", 'YYYYMMDD') - to_date("edatu", 'YYYYMMDD')) AS avg_lead_time_days
FROM "VBEP"
WHERE "wadat" IS NOT NULL
  AND "edatu" IS NOT NULL
  AND "edatu" ~ '^[0-9]{8}$'
  AND "edatu" <> '00000000'
  AND "wadat" ~ '^[0-9]{8}$'
  AND "wadat" <> '00000000'
GROUP BY "vbeln"
ORDER BY avg_lead_time_days DESC
LIMIT 100
""",
        "required_tables": ["VBEP"],
    },
    {
        "pattern_name": "advanced_material_reservation_trends_script",
        "pattern_template": "advanced material reservation trends (script)",
        "keywords": ["advanced", "material", "reservation", "trends"],
        "sql_template": """
SELECT
    "matnr" AS material,
    EXTRACT(YEAR FROM to_date("bdter", 'YYYYMMDD'))::int AS year,
    EXTRACT(MONTH FROM to_date("bdter", 'YYYYMMDD'))::int AS month,
    SUM(NULLIF(TRIM("bdmng"::text), '')::numeric) AS reserved_qty
FROM "RESB"
WHERE "bdter" ~ '^[0-9]{8}$'
  AND "bdter" <> '00000000'
GROUP BY "matnr",
         EXTRACT(YEAR FROM to_date("bdter", 'YYYYMMDD')),
         EXTRACT(MONTH FROM to_date("bdter", 'YYYYMMDD'))
ORDER BY material, year, month
LIMIT 500
""",
        "required_tables": ["RESB"],
    },
]

ALL_PATTERNS = BUILTIN_PATTERNS + SCRIPT_QUERY_PATTERNS


def match_builtin_pattern(user_query: str) -> Optional[Dict[str, Any]]:
    """
    Match against built-in query patterns using keyword detection.
    Fast path that doesn't require database lookup.
    
    Args:
        user_query: User's natural language query
    
    Returns:
        Matching pattern info or None
    """
    q = user_query.lower()
    
    for pattern in ALL_PATTERNS:
        # Check if all keywords are present
        keywords = pattern.get("keywords", [])
        if keywords and all(kw in q for kw in keywords):
            logger.info(f"✅ Matched built-in pattern: {pattern['pattern_name']}")
            return pattern
    
    return None


def apply_pattern_template(
    pattern: Dict[str, Any],
    user_query: str,
    db: Session,
) -> Optional[str]:
    """
    Apply pattern template with extracted parameters.
    
    Args:
        pattern: Pattern dictionary
        user_query: Original query
        db: Database session
    
    Returns:
        Executable SQL string or None
    """
    try:
        sql_template = pattern["sql_template"]
        pattern_name = pattern["pattern_name"]
        pattern_template = pattern.get("pattern_template", "") or ""
        
        logger.info(f"📝 Applying pattern template: {pattern_name}")
        
        # Extract parameters based on pattern type
        params = {}
        
        if pattern_template and "year" in pattern_template.lower():
            year = extract_year_from_query(user_query)
            if year:
                params["year"] = year
            else:
                logger.warning("Could not extract year from query")
                return None
        
        if pattern_template and "{n}" in pattern_template:
            params["n"] = extract_top_n_from_query(user_query)
            params["limit"] = params["n"]
        
        if pattern_template and "{dimension}" in pattern_template:
            dimension = extract_dimension_from_query(user_query)
            if dimension and "dimension_map" in pattern:
                dim_config = pattern["dimension_map"].get(dimension)
                if dim_config:
                    params["dimension"] = dimension
                    params["dimension_column"] = dim_config["column"]
                    params["table"] = dim_config["table"]
                    params["join"] = dim_config.get("join", "")
                else:
                    logger.warning(f"Unknown dimension: {dimension}")
                    return None
            else:
                logger.warning("Could not extract dimension from query")
                return None
        
        if pattern_template and "{period}" in pattern_template:
            if "daily" in user_query.lower() or "day" in user_query.lower():
                params["period"] = "day"
            elif "weekly" in user_query.lower() or "week" in user_query.lower():
                params["period"] = "week"
            elif "monthly" in user_query.lower() or "month" in user_query.lower():
                params["period"] = "month"
            else:
                params["period"] = "month"  # Default
        
        # Set default limit if not set
        if "{limit}" in sql_template and "limit" not in params:
            params["limit"] = 20
        
        # Apply parameters to template
        sql = sql_template
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            sql = sql.replace(placeholder, str(value))
        
        # Clean up whitespace
        sql = "\n".join(line.strip() for line in sql.split("\n") if line.strip())
        
        logger.info(f"✅ Generated SQL from pattern: {len(sql)} chars")
        logger.debug(f"SQL: {sql[:200]}...")
        
        return sql
    
    except Exception as e:
        logger.error(f"❌ Failed to apply pattern template: {e}")
        return None


def try_pattern_optimization(
    user_query: str,
    db: Session,
) -> Optional[Dict[str, Any]]:
    """
    Try to optimize query using pattern matching.
    
    Args:
        user_query: User's query
        db: Database session
    
    Returns:
        Dict with sql and pattern_used, or None if no match
    """
    # Try built-in patterns first (fastest)
    pattern = match_builtin_pattern(user_query)
    
    if not pattern:
        # Try cached patterns from database (semantic search)
        from .table_schema_manager import find_matching_pattern
        pattern = find_matching_pattern(db, user_query, threshold=0.82)
    
    if not pattern:
        logger.info("No matching pattern found")
        return None
    
    # Apply template
    sql = apply_pattern_template(pattern, user_query, db)
    
    if not sql:
        logger.warning(f"Failed to apply template for pattern: {pattern.get('pattern_name')}")
        return None
    
    return {
        "sql": sql,
        "pattern_used": pattern.get("pattern_name"),
        "pattern_similarity": pattern.get("similarity", 1.0),
    }


def register_successful_pattern(
    db: Session,
    user_query: str,
    sql: str,
    execution_time_ms: int,
) -> None:
    """
    Learn from successful queries by storing them as potential patterns.
    This builds up the pattern library over time.
    
    Args:
        db: Database session
        user_query: Original user query
        sql: Executed SQL
        execution_time_ms: Execution time
    """
    try:
        # This is a placeholder for future ML-based pattern extraction
        # For now, we just log it for manual review
        logger.debug(f"Successful query: {user_query[:100]} -> {execution_time_ms}ms")
    
    except Exception as e:
        logger.warning(f"Failed to register pattern: {e}")
