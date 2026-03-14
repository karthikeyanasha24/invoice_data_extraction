#!/usr/bin/env python3
"""
Generate sql_catalog.json — a library of pre-validated PostgreSQL queries for the SAP SQL agent.

Why this exists:
  The LLM-based SQL generator sometimes fails to parse JSON or picks the wrong table.
  For the 80% of "standard aggregation" questions (top N by X, totals by dimension, etc.)
  we can answer directly from this pre-built catalog — no LLM SQL generation needed.

How the catalog is used (sap_sql_agent._lookup_sql_catalog):
  1. Keyword-score the user question against every catalog entry.
  2. If the top-scoring entry is confident enough, run its SQL directly.
  3. Fall back to LLM generation only for specific/filtered queries not in the catalog.

Run:
  cd zodiac-api
  python3 generate_sql_catalog.py
  → writes app/sql_catalog.json
"""

import json
from pathlib import Path

# ─── TRIM+CAST helper for tables that store numerics as VARCHAR ───────────────
# (SAP exports billing / sales tables as VARCHAR; must cast to NUMERIC for SUM)
TRIM_TABLES = {"VBRP", "vbrp", "VBRK", "VBAP", "VBAK", "LIKP", "LIPS"}

def tc(table: str, col: str, alias: str = None) -> str:
    """Safe numeric cast: CAST(NULLIF(TRIM(ref.col),'') AS NUMERIC) for VARCHAR tables.

    IMPORTANT: If the SQL uses a table alias (e.g. FROM VBRK vk), pass the alias as
    the third argument:  tc('VBRK', 'netwr', 'vk')  → CAST(NULLIF(TRIM(vk.netwr),'') AS NUMERIC)
    Without the alias, PostgreSQL will raise 'missing FROM-clause entry' errors.
    """
    ref = alias if alias else table
    if table.upper() in {t.upper() for t in TRIM_TABLES}:
        return f"CAST(NULLIF(TRIM({ref}.{col}), '') AS NUMERIC)"
    return f"{ref}.{col}"


# ─── Catalog container ────────────────────────────────────────────────────────
entries = []

def q(id_: str, desc: str, patterns: list, keywords: list, tables: list, sql: str,
      neg_keywords: list = None, priority: int = 0):
    """Add one catalog entry."""
    entries.append({
        "id": id_,
        "description": desc,
        "question_patterns": patterns,   # full example sentences (for LLM-based matching)
        "keywords": keywords,             # individual words for fast keyword scoring
        "neg_keywords": neg_keywords or [],
        "tables": tables,
        "sql": sql.strip(),
        "priority": priority,             # higher = prefer when scores tie
    })


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: BILLING / SALES — VBRK + vbrp
# ══════════════════════════════════════════════════════════════════════════════

q("sales_total_overall",
  "Grand total sales/revenue (all periods)",
  ["what is the total sales", "total revenue overall", "overall billing amount", "grand total sales"],
  ["total", "sales", "revenue", "overall", "billing", "grand"],
  ["VBRK", "vbrp"],
  f"""
SELECT SUM({tc('vbrp','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE {tc('vbrp','netwr')} IS NOT NULL
GROUP BY vk.waerk
ORDER BY total_sales DESC
""",
  neg_keywords=["by year","by month","by country","by customer","by product","by industry"],
  priority=1)

# ── Sales by year ─────────────────────────────────────────────────────────────
q("sales_by_year",
  "Total sales by year",
  ["sales by year","revenue by year","annual sales","yearly sales","sales per year","sales each year","sales trend by year"],
  ["sales","year","annual","yearly","revenue","trend","billing"],
  ["VBRK","vbrp"],
  f"""
SELECT SUBSTRING(vk.fkdat, 1, 4) AS year,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE vk.fkdat IS NOT NULL AND vk.fkdat != ''
GROUP BY year, vk.waerk
ORDER BY year ASC
""",
  neg_keywords=["month","by country","by customer","by product"],
  priority=2)

# ── Sales by year and month ───────────────────────────────────────────────────
q("sales_by_year_month",
  "Total sales by year and month (monthly trend)",
  ["monthly sales","sales by month","monthly revenue","monthly billing","sales trend monthly"],
  ["sales","month","monthly","revenue","trend","billing"],
  ["VBRK","vbrp"],
  f"""
SELECT SUBSTRING(vk.fkdat, 1, 4) AS year,
       SUBSTRING(vk.fkdat, 5, 2) AS month,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE vk.fkdat IS NOT NULL AND vk.fkdat != ''
GROUP BY year, month, vk.waerk
ORDER BY year ASC, month ASC
""",
  priority=3)

# ── Sales by country ──────────────────────────────────────────────────────────
q("sales_by_country_top20",
  "Top 20 countries by total sales",
  ["highest sales by country","top countries by sales","sales by country","revenue by country",
   "which country has highest sales","best countries by revenue","top 20 countries by sales"],
  ["country","sales","revenue","top","highest","land1","countries"],
  ["VBRK"],
  f"""
SELECT vk.land1 AS country,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency,
       COUNT(DISTINCT vk.vbeln) AS invoice_count
FROM VBRK vk
WHERE vk.land1 IS NOT NULL AND vk.land1 != ''
GROUP BY vk.land1, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""",
  priority=4)

q("sales_by_country_bottom20",
  "Bottom 20 countries by total sales (lowest)",
  ["lowest sales by country","least sales by country","countries with lowest revenue","bottom countries by sales"],
  ["country","sales","lowest","bottom","least","revenue"],
  ["VBRK"],
  f"""
SELECT vk.land1 AS country,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
WHERE vk.land1 IS NOT NULL AND vk.land1 != ''
GROUP BY vk.land1, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales ASC
LIMIT 20
""")

# ── Sales by customer ─────────────────────────────────────────────────────────
q("sales_by_customer_top20",
  "Top 20 customers by total sales",
  ["highest sales by customer","top customers by sales","top customers by revenue","top 20 customers",
   "which customer has highest sales","best customers","largest customers by revenue","top customers"],
  ["customer","sales","revenue","top","highest","best","kunag","biggest","customers"],
  ["VBRK","KNA1"],
  f"""
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       k.land1 AS country,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency,
       COUNT(DISTINCT vk.vbeln) AS invoice_count
FROM VBRK vk
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
GROUP BY vk.kunag, k.name1, k.land1, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""",
  priority=5)

q("sales_by_customer_bottom20",
  "Bottom 20 customers by total sales (lowest)",
  ["lowest sales by customer","customers with least revenue","bottom customers by sales",
   "customers with lowest purchases"],
  ["customer","sales","lowest","bottom","least","revenue","customers"],
  ["VBRK","KNA1"],
  f"""
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       k.land1 AS country,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
GROUP BY vk.kunag, k.name1, k.land1, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales ASC
LIMIT 20
""")

# ── Sales by product/material ─────────────────────────────────────────────────
q("sales_by_product_top20",
  "Top 20 products/materials by total sales",
  ["highest sales by product","top products by sales","top 20 products by revenue",
   "best selling products","which product has highest sales","top selling materials",
   "highest revenue products","top materials by sales","products by revenue"],
  ["product","material","sales","revenue","top","highest","selling","matnr","products","materials"],
  ["vbrp","VBRK","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       TRIM(v.matnr) AS material_number,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       SUM({tc('vbrp','fkimg')}) AS total_quantity,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND m.spras = 'E'
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) != ''
GROUP BY TRIM(v.matnr), m.maktx, vk.waerk
HAVING SUM({tc('vbrp','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""",
  priority=5)

q("sales_by_product_bottom20",
  "Bottom 20 products/materials by total sales (lowest)",
  ["lowest sales by product","least sold products","bottom products by sales","products with lowest revenue"],
  ["product","material","sales","lowest","bottom","least","revenue","products"],
  ["vbrp","VBRK","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       TRIM(v.matnr) AS material_number,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       SUM({tc('vbrp','fkimg')}) AS total_quantity,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND m.spras = 'E'
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) != ''
GROUP BY TRIM(v.matnr), m.maktx, vk.waerk
HAVING SUM({tc('vbrp','netwr')}) > 0
ORDER BY total_sales ASC
LIMIT 20
""")

# ── Sales by quantity ─────────────────────────────────────────────────────────
q("quantity_by_product_top20",
  "Top 20 products by total quantity sold",
  ["top products by quantity sold","most sold products by quantity","highest quantity sold by product",
   "products with highest quantity","top 20 products by quantity"],
  ["product","material","quantity","sold","top","highest","fkimg","most"],
  ["vbrp","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       TRIM(v.matnr) AS material_number,
       SUM({tc('vbrp','fkimg')}) AS total_quantity,
       SUM({tc('vbrp','netwr')}) AS total_sales
FROM vbrp v
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND m.spras = 'E'
WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) != ''
GROUP BY TRIM(v.matnr), m.maktx
HAVING SUM({tc('vbrp','fkimg')}) > 0
ORDER BY total_quantity DESC
LIMIT 20
""",
  neg_keywords=["purchase","cost","vendor"])

# ── Sales by industry ─────────────────────────────────────────────────────────
q("sales_by_industry_top20",
  "Top 20 industries by total sales",
  ["sales by industry","highest sales by industry","which industry has highest sales",
   "top industries by revenue","revenue by industry","industry breakdown by sales"],
  ["industry","sales","revenue","top","highest","brsch","industries"],
  ["VBRK","KNA1","T016T"],
  f"""
SELECT t.brtxt AS industry_name,
       k.brsch AS industry_code,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency,
       COUNT(DISTINCT vk.kunag) AS customer_count
FROM VBRK vk
JOIN KNA1 k ON vk.kunag = k.kunnr
LEFT JOIN T016T t ON k.brsch = t.brsch
WHERE k.brsch IS NOT NULL AND k.brsch != ''
GROUP BY k.brsch, t.brtxt, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""",
  priority=5)

# ── Sales by customer + country ───────────────────────────────────────────────
q("sales_by_customer_country_top20",
  "Top 20 customers with country by total sales",
  ["highest sales by customer and country","top customers by sales and country",
   "sales by customer with country","customer sales by country"],
  ["customer","country","sales","top","highest","revenue"],
  ["VBRK","KNA1"],
  f"""
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       vk.land1 AS country,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
GROUP BY vk.kunag, k.name1, vk.land1, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""")

# ── Sales by customer + product ───────────────────────────────────────────────
q("sales_by_customer_product_top20",
  "Top 20 customer-product combinations by total sales",
  ["highest sales by customer and product","top sales by customer and product",
   "which customer bought which product the most","customer product revenue breakdown"],
  ["customer","product","material","sales","top","highest","revenue"],
  ["vbrp","VBRK","KNA1","MAKT"],
  f"""
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       m.maktx AS material_name,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
LEFT JOIN MAKT m ON TRIM(v.matnr) = TRIM(m.matnr) AND m.spras = 'E'
GROUP BY vk.kunag, k.name1, m.maktx, vk.waerk
HAVING SUM({tc('vbrp','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""")

# ── Sales by sales organization ───────────────────────────────────────────────
q("sales_by_sales_org",
  "Sales by sales organization",
  ["sales by sales organization","revenue by sales org","sales org breakdown","vkorg sales"],
  ["sales","organization","org","vkorg","sales org"],
  ["VBRK"],
  f"""
SELECT vk.vkorg AS sales_org,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency,
       COUNT(DISTINCT vk.vbeln) AS invoice_count
FROM VBRK vk
GROUP BY vk.vkorg, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
""")

# ── Sales by distribution channel ────────────────────────────────────────────
q("sales_by_distribution_channel",
  "Sales by distribution channel",
  ["sales by distribution channel","revenue by channel","distribution channel sales","vtweg sales"],
  ["distribution","channel","sales","vtweg","revenue"],
  ["VBRK"],
  f"""
SELECT vk.vtweg AS distribution_channel,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
GROUP BY vk.vtweg, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
""")

# ── Invoice count by customer ─────────────────────────────────────────────────
q("invoice_count_by_customer",
  "Number of invoices per customer (top 20)",
  ["invoice count by customer","how many invoices per customer","number of invoices by customer",
   "customers with most invoices","invoices per customer"],
  ["invoice","count","customer","number","how many","invoices"],
  ["VBRK","KNA1"],
  f"""
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       COUNT(DISTINCT vk.vbeln) AS invoice_count,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
GROUP BY vk.kunag, k.name1, vk.waerk
ORDER BY invoice_count DESC
LIMIT 20
""")

# ── Average sales per customer ────────────────────────────────────────────────
q("sales_avg_per_customer",
  "Average sales per customer",
  ["average sales per customer","average revenue per customer","mean sales per customer","avg revenue by customer"],
  ["average","avg","mean","sales","customer","revenue","per"],
  ["VBRK","KNA1"],
  f"""
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       AVG({tc('VBRK','netwr')}) AS avg_invoice_value,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       COUNT(DISTINCT vk.vbeln) AS invoice_count,
       vk.waerk AS currency
FROM VBRK vk
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
GROUP BY vk.kunag, k.name1, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY avg_invoice_value DESC
LIMIT 20
""")

# ── Revenue by plant / division ───────────────────────────────────────────────
q("sales_by_division",
  "Sales by division/product group (spart)",
  ["sales by division","revenue by division","sales by product group","division breakdown"],
  ["division","spart","product","group","sales","revenue"],
  ["VBRK"],
  f"""
SELECT vk.spart AS division,
       SUM({tc('VBRK','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
WHERE vk.spart IS NOT NULL AND vk.spart != ''
GROUP BY vk.spart, vk.waerk
HAVING SUM({tc('VBRK','netwr')}) > 0
ORDER BY total_sales DESC
""")

# ── Sales compare year over year (2 best years in data) ──────────────────────
q("sales_year_comparison",
  "Sales comparison across years (year-over-year)",
  ["compare sales by year","year over year sales","yoy sales","sales comparison by year",
   "how did sales change by year","sales growth by year"],
  ["compare","year","sales","yoy","growth","change","revenue"],
  ["VBRK","vbrp"],
  f"""
SELECT SUBSTRING(vk.fkdat, 1, 4) AS year,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       COUNT(DISTINCT vk.vbeln) AS invoice_count,
       COUNT(DISTINCT vk.kunag) AS customer_count,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE vk.fkdat IS NOT NULL AND vk.fkdat != ''
GROUP BY year, vk.waerk
ORDER BY year ASC
""",
  priority=3)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: CUSTOMER MASTER — KNA1
# ══════════════════════════════════════════════════════════════════════════════

q("customer_list",
  "List all customers with country",
  ["list all customers","show all customers","all customers","customer names","customer list",
   "show me customers","who are my customers","list customer names"],
  ["customer","list","all","show","names","customers","kna1"],
  ["KNA1"],
  f"""
SELECT k.kunnr AS customer_number,
       k.name1 AS customer_name,
       k.land1 AS country,
       k.ort01 AS city,
       k.brsch AS industry_code
FROM KNA1 k
WHERE k.name1 IS NOT NULL AND k.name1 != ''
ORDER BY k.name1 ASC
LIMIT 500
""",
  neg_keywords=["sales","revenue","by","top","purchase","invoice"])

q("customer_count_by_country",
  "Number of customers by country",
  ["customer count by country","how many customers per country","customers per country",
   "number of customers by country","customers in each country"],
  ["customer","count","country","how many","per","number"],
  ["KNA1"],
  f"""
SELECT k.land1 AS country,
       COUNT(DISTINCT k.kunnr) AS customer_count
FROM KNA1 k
WHERE k.land1 IS NOT NULL AND k.land1 != ''
GROUP BY k.land1
ORDER BY customer_count DESC
""")

q("customer_count_by_industry",
  "Number of customers by industry",
  ["customer count by industry","customers per industry","how many customers in each industry",
   "number of customers by industry","industry breakdown of customers"],
  ["customer","count","industry","per","how many","number","brsch"],
  ["KNA1","T016T"],
  f"""
SELECT t.brtxt AS industry_name,
       k.brsch AS industry_code,
       COUNT(DISTINCT k.kunnr) AS customer_count
FROM KNA1 k
LEFT JOIN T016T t ON k.brsch = t.brsch
WHERE k.brsch IS NOT NULL AND k.brsch != ''
GROUP BY k.brsch, t.brtxt
ORDER BY customer_count DESC
""")

q("customers_by_country_list",
  "List customers in each country",
  ["customers by country","list customers by country","which customers are in each country"],
  ["customer","country","list","names","land1"],
  ["KNA1"],
  f"""
SELECT k.land1 AS country,
       k.kunnr AS customer_number,
       k.name1 AS customer_name,
       k.ort01 AS city
FROM KNA1 k
WHERE k.land1 IS NOT NULL AND k.land1 != ''
ORDER BY k.land1 ASC, k.name1 ASC
LIMIT 500
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: PURCHASING — EKKO + EKPO
# ══════════════════════════════════════════════════════════════════════════════

q("purchase_total",
  "Grand total purchase amount (all vendors)",
  ["total purchase amount","total procurement","overall purchase value","total purchasing spend"],
  ["total","purchase","procurement","purchasing","overall","spend"],
  ["EKPO","EKKO"],
  f"""
SELECT SUM(ep.netwr) AS total_purchase_amount,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
WHERE ep.netwr IS NOT NULL
GROUP BY ek.waers
ORDER BY total_purchase_amount DESC
""",
  neg_keywords=["by vendor","by material","by year","by plant","top","highest"])

q("purchase_by_vendor_top20",
  "Top 20 vendors by total purchase amount",
  ["top vendors by purchase","highest purchase by vendor","top 20 vendors by spend",
   "vendors by purchase amount","which vendor has highest purchases","top suppliers by purchase",
   "vendor purchase ranking","largest vendors by order value",
   "purchase by vendor","purchases by vendor","vendor purchases"],
  ["vendor","purchase","top","highest","supplier","spend","amount","vendors","suppliers",
   "by vendor","purchase by vendor"],
  ["EKPO","EKKO","LFA1"],
  f"""
SELECT l.name1 AS vendor_name,
       ek.lifnr AS vendor_number,
       SUM(ep.netwr) AS total_purchase_amount,
       SUM(ep.menge) AS total_quantity,
       COUNT(DISTINCT ek.ebeln) AS po_count,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
LEFT JOIN LFA1 l ON ek.lifnr = l.lifnr
WHERE ep.netwr IS NOT NULL
GROUP BY ek.lifnr, l.name1, ek.waers
HAVING SUM(ep.netwr) > 0
ORDER BY total_purchase_amount DESC
LIMIT 20
""",
  priority=5)

q("purchase_by_material_top20",
  "Top 20 materials by total purchase amount",
  ["top materials by purchase amount","purchased materials by cost","top 20 materials by cost",
   "total purchase cost by material","materials with highest purchase cost",
   "what materials are purchased most by value"],
  ["material","purchase","top","highest","cost","amount","materials","purchased"],
  ["EKPO","EKKO","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       ep.matnr AS material_number,
       SUM(ep.netwr) AS total_purchase_amount,
       SUM(ep.menge) AS total_quantity,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
LEFT JOIN MAKT m ON ep.matnr = m.matnr AND m.spras = 'E'
WHERE ep.matnr IS NOT NULL AND ep.matnr != '' AND ep.netwr IS NOT NULL
GROUP BY ep.matnr, m.maktx, ek.waers
HAVING SUM(ep.netwr) > 0
ORDER BY total_purchase_amount DESC
LIMIT 20
""",
  priority=5)

q("purchase_quantity_by_material_top20",
  "Top 20 materials by total purchase quantity",
  ["top materials by quantity purchased","most purchased materials by quantity",
   "highest quantity purchased by material","materials ordered most by quantity",
   "what is total purchase quantity by material","top 10 products by total purchase quantity and cost"],
  ["material","quantity","purchase","top","purchased","most","menge","ordered"],
  ["EKPO","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       ep.matnr AS material_number,
       SUM(ep.menge) AS total_quantity,
       SUM(ep.netwr) AS total_purchase_amount
FROM EKPO ep
LEFT JOIN MAKT m ON ep.matnr = m.matnr AND m.spras = 'E'
WHERE ep.matnr IS NOT NULL AND ep.matnr != '' AND ep.menge IS NOT NULL
GROUP BY ep.matnr, m.maktx
HAVING SUM(ep.menge) > 0
ORDER BY total_quantity DESC
LIMIT 20
""",
  priority=5)

q("purchase_by_year",
  "Total purchase amount by year",
  ["purchases by year","annual purchasing","purchase trend by year","yearly purchasing",
   "purchasing by year","procurement by year"],
  ["purchase","year","annual","yearly","trend","procurement"],
  ["EKPO","EKKO"],
  f"""
SELECT SUBSTRING(ek.bedat, 1, 4) AS year,
       SUM(ep.netwr) AS total_purchase_amount,
       COUNT(DISTINCT ek.ebeln) AS po_count,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
WHERE ek.bedat IS NOT NULL AND ek.bedat != '' AND ep.netwr IS NOT NULL
GROUP BY year, ek.waers
ORDER BY year ASC
""")

q("purchase_by_month",
  "Total purchase amount by year and month",
  ["purchases by month","monthly purchasing","monthly procurement","purchase trend by month"],
  ["purchase","month","monthly","procurement","trend"],
  ["EKPO","EKKO"],
  f"""
SELECT SUBSTRING(ek.bedat, 1, 4) AS year,
       SUBSTRING(ek.bedat, 5, 2) AS month,
       SUM(ep.netwr) AS total_purchase_amount,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
WHERE ek.bedat IS NOT NULL AND ek.bedat != '' AND ep.netwr IS NOT NULL
GROUP BY year, month, ek.waers
ORDER BY year ASC, month ASC
""")

q("po_count_by_vendor",
  "Number of purchase orders by vendor (top 20)",
  ["purchase order count by vendor","how many orders per vendor","po count by vendor",
   "number of pos per vendor","vendors with most purchase orders"],
  ["purchase","order","count","vendor","number","how many","po","orders"],
  ["EKKO","LFA1"],
  f"""
SELECT l.name1 AS vendor_name,
       ek.lifnr AS vendor_number,
       COUNT(DISTINCT ek.ebeln) AS po_count,
       SUM(ep.netwr) AS total_amount,
       ek.waers AS currency
FROM EKKO ek
LEFT JOIN LFA1 l ON ek.lifnr = l.lifnr
LEFT JOIN EKPO ep ON ek.ebeln = ep.ebeln
GROUP BY ek.lifnr, l.name1, ek.waers
ORDER BY po_count DESC
LIMIT 20
""")

q("purchase_by_material_vendor",
  "Top 20 material-vendor combinations by purchase amount",
  ["purchase by material and vendor","materials from each vendor","vendor material cost breakdown",
   "which vendor supplies which material at what cost"],
  ["material","vendor","purchase","cost","supplier","supply"],
  ["EKPO","EKKO","MAKT","LFA1"],
  f"""
SELECT m.maktx AS material_name,
       l.name1 AS vendor_name,
       SUM(ep.netwr) AS total_amount,
       SUM(ep.menge) AS total_quantity,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
LEFT JOIN MAKT m ON ep.matnr = m.matnr AND m.spras = 'E'
LEFT JOIN LFA1 l ON ek.lifnr = l.lifnr
WHERE ep.matnr IS NOT NULL
GROUP BY m.maktx, l.name1, ek.waers
HAVING SUM(ep.netwr) > 0
ORDER BY total_amount DESC
LIMIT 20
""")

q("purchase_by_plant",
  "Purchase amount by plant (top 20)",
  ["purchase by plant","procurement by plant","purchasing by plant","plant purchase breakdown"],
  ["purchase","plant","werks","procurement"],
  ["EKPO","EKKO"],
  f"""
SELECT ep.werks AS plant,
       SUM(ep.netwr) AS total_purchase_amount,
       COUNT(DISTINCT ek.ebeln) AS po_count,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
WHERE ep.werks IS NOT NULL AND ep.werks != '' AND ep.netwr IS NOT NULL
GROUP BY ep.werks, ek.waers
HAVING SUM(ep.netwr) > 0
ORDER BY total_purchase_amount DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: VENDOR INVOICES — RBKP + RSEG
# ══════════════════════════════════════════════════════════════════════════════

q("vendor_invoice_total",
  "Grand total vendor invoice amount (accounts payable)",
  ["total vendor invoice amount","total accounts payable","total vendor spend",
   "total ap amount","total invoice value"],
  ["total","vendor","invoice","spend","accounts","payable","ap","overall"],
  ["RBKP"],
  f"""
SELECT SUM(rb.rmwwr) AS total_invoice_amount,
       rb.waers AS currency,
       COUNT(DISTINCT rb.belnr) AS invoice_count
FROM RBKP rb
WHERE rb.rmwwr IS NOT NULL
GROUP BY rb.waers
ORDER BY total_invoice_amount DESC
""",
  neg_keywords=["by vendor","by material","by year","by month","top","highest"])

q("vendor_spend_top20",
  "Top 20 vendors by total invoice/spend amount (AP)",
  ["highest spend by vendor","top vendors by spend","largest vendor invoices",
   "top 20 vendors by invoice","vendors with highest spend","which vendor has highest spend",
   "top vendor spend","total spend by vendor","vendor spend ranking","vendor ap spend"],
  ["vendor","spend","invoice","top","highest","largest","supplier","ap","accounts","payable","rbkp"],
  ["RBKP","LFA1"],
  f"""
SELECT l.name1 AS vendor_name,
       rb.lifnr AS vendor_number,
       SUM(rb.rmwwr) AS total_invoice_amount,
       COUNT(DISTINCT rb.belnr) AS invoice_count,
       rb.waers AS currency
FROM RBKP rb
LEFT JOIN LFA1 l ON rb.lifnr = l.lifnr
WHERE rb.rmwwr IS NOT NULL
GROUP BY rb.lifnr, l.name1, rb.waers
HAVING SUM(rb.rmwwr) > 0
ORDER BY total_invoice_amount DESC
LIMIT 20
""",
  priority=6)

q("vendor_invoice_by_year",
  "Vendor invoice amount by year",
  ["vendor invoices by year","accounts payable by year","invoice trend by year",
   "yearly vendor invoices","annual vendor spend"],
  ["vendor","invoice","year","annual","yearly","ap","spend"],
  ["RBKP"],
  f"""
SELECT SUBSTRING(rb.budat, 1, 4) AS year,
       SUM(rb.rmwwr) AS total_invoice_amount,
       COUNT(DISTINCT rb.belnr) AS invoice_count,
       rb.waers AS currency
FROM RBKP rb
WHERE rb.budat IS NOT NULL AND rb.budat != '' AND rb.rmwwr IS NOT NULL
GROUP BY year, rb.waers
ORDER BY year ASC
""")

q("vendor_invoice_by_month",
  "Vendor invoice amount by year and month",
  ["vendor invoices by month","monthly vendor invoices","monthly accounts payable",
   "monthly vendor spend"],
  ["vendor","invoice","month","monthly","ap","spend"],
  ["RBKP"],
  f"""
SELECT SUBSTRING(rb.budat, 1, 4) AS year,
       SUBSTRING(rb.budat, 5, 2) AS month,
       SUM(rb.rmwwr) AS total_invoice_amount,
       rb.waers AS currency
FROM RBKP rb
WHERE rb.budat IS NOT NULL AND rb.budat != '' AND rb.rmwwr IS NOT NULL
GROUP BY year, month, rb.waers
ORDER BY year ASC, month ASC
""")

q("invoice_count_by_vendor",
  "Number of vendor invoices by vendor (top 20)",
  ["invoice count by vendor","how many invoices per vendor","number of invoices by vendor",
   "vendors with most invoices","invoice frequency by vendor"],
  ["invoice","count","vendor","number","how many","frequency"],
  ["RBKP","LFA1"],
  f"""
SELECT l.name1 AS vendor_name,
       rb.lifnr AS vendor_number,
       COUNT(DISTINCT rb.belnr) AS invoice_count,
       SUM(rb.rmwwr) AS total_amount,
       rb.waers AS currency
FROM RBKP rb
LEFT JOIN LFA1 l ON rb.lifnr = l.lifnr
GROUP BY rb.lifnr, l.name1, rb.waers
ORDER BY invoice_count DESC
LIMIT 20
""")

q("vendor_invoice_by_material",
  "Top 20 materials by vendor invoice amount (RSEG)",
  ["materials in vendor invoices by cost","top materials by invoice amount",
   "vendor invoice by material","what materials appear in vendor invoices"],
  ["material","vendor","invoice","rseg","cost","amount","materials"],
  ["RSEG","RBKP","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       rs.matnr AS material_number,
       SUM(rs.wrbtr) AS total_amount,
       rb.waers AS currency
FROM RSEG rs
JOIN RBKP rb ON rs.belnr = rb.belnr AND rs.gjahr = rb.gjahr
LEFT JOIN MAKT m ON rs.matnr = m.matnr AND m.spras = 'E'
WHERE rs.matnr IS NOT NULL AND rs.matnr != '' AND rs.wrbtr IS NOT NULL
GROUP BY rs.matnr, m.maktx, rb.waers
HAVING SUM(rs.wrbtr) > 0
ORDER BY total_amount DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: VENDOR MASTER — LFA1
# ══════════════════════════════════════════════════════════════════════════════

q("vendor_list",
  "List all vendors",
  ["list all vendors","show all vendors","all vendors","vendor names","vendor list",
   "show me vendors","who are my vendors","list vendor names","list suppliers"],
  ["vendor","list","all","show","names","vendors","suppliers","lfa1"],
  ["LFA1"],
  f"""
SELECT l.lifnr AS vendor_number,
       l.name1 AS vendor_name,
       l.land1 AS country,
       l.ort01 AS city
FROM LFA1 l
WHERE l.name1 IS NOT NULL AND l.name1 != ''
ORDER BY l.name1 ASC
LIMIT 500
""",
  neg_keywords=["spend","invoice","purchase","top","by","count"])

q("vendor_count_by_country",
  "Number of vendors by country",
  ["vendor count by country","vendors per country","how many vendors by country",
   "number of vendors by country","vendors in each country"],
  ["vendor","count","country","per","how many","number","vendors"],
  ["LFA1"],
  f"""
SELECT l.land1 AS country,
       COUNT(DISTINCT l.lifnr) AS vendor_count
FROM LFA1 l
WHERE l.land1 IS NOT NULL AND l.land1 != ''
GROUP BY l.land1
ORDER BY vendor_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: GENERAL LEDGER — FAGLFLEXA
# ══════════════════════════════════════════════════════════════════════════════

q("gl_by_year",
  "Total GL posting amount by fiscal year (FAGLFLEXA)",
  ["GL amount by year","general ledger by year","FAGLFLEXA by year",
   "GL entries by year","total gl by year","GL total per year"],
  ["gl","general","ledger","year","fiscal","faglflexa","posting","ryear"],
  ["FAGLFLEXA"],
  f"""
SELECT fg.ryear AS fiscal_year,
       SUM(fg.hsl) AS total_local_amount,
       SUM(fg.wsl) AS total_transaction_amount,
       fg.rtcur AS currency,
       COUNT(*) AS entry_count
FROM FAGLFLEXA fg
GROUP BY fg.ryear, fg.rtcur
ORDER BY fg.ryear ASC
""")

q("gl_by_period",
  "GL posting amount by fiscal year and period (FAGLFLEXA)",
  ["GL amount by period","general ledger by period","GL entries by period",
   "FAGLFLEXA by period","GL monthly breakdown","posting period analysis"],
  ["gl","period","ledger","fiscal","faglflexa","poper","posting"],
  ["FAGLFLEXA"],
  f"""
SELECT fg.ryear AS fiscal_year,
       fg.poper AS posting_period,
       SUM(fg.hsl) AS total_local_amount,
       fg.rtcur AS currency
FROM FAGLFLEXA fg
GROUP BY fg.ryear, fg.poper, fg.rtcur
ORDER BY fg.ryear ASC, fg.poper ASC
""")

q("gl_by_account",
  "GL amount by GL account (top 20 by absolute value)",
  ["GL by account","GL entries by account number","which GL account has highest amount",
   "top GL accounts by amount","account balance from FAGLFLEXA"],
  ["gl","account","ledger","faglflexa","racct","amount"],
  ["FAGLFLEXA"],
  f"""
SELECT fg.racct AS gl_account,
       SUM(fg.hsl) AS net_local_amount,
       SUM(CASE WHEN fg.hsl > 0 THEN fg.hsl ELSE 0 END) AS debit_amount,
       SUM(CASE WHEN fg.hsl < 0 THEN ABS(fg.hsl) ELSE 0 END) AS credit_amount,
       fg.rtcur AS currency,
       COUNT(*) AS entry_count
FROM FAGLFLEXA fg
WHERE fg.racct IS NOT NULL
GROUP BY fg.racct, fg.rtcur
ORDER BY ABS(SUM(fg.hsl)) DESC
LIMIT 20
""")

q("gl_by_company_code",
  "GL amount by company code",
  ["GL by company code","FAGLFLEXA by company","general ledger by company code",
   "company code GL summary"],
  ["gl","company","code","bukrs","rbukrs","ledger","faglflexa"],
  ["FAGLFLEXA"],
  f"""
SELECT fg.rbukrs AS company_code,
       fg.ryear AS fiscal_year,
       SUM(fg.hsl) AS total_local_amount,
       fg.rtcur AS currency
FROM FAGLFLEXA fg
GROUP BY fg.rbukrs, fg.ryear, fg.rtcur
ORDER BY fg.rbukrs ASC, fg.ryear ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: STANDARD COSTS — KEKO + CKIS
# ══════════════════════════════════════════════════════════════════════════════

q("standard_cost_by_material",
  "Standard cost/price by material (top 20 highest)",
  ["standard cost by material","material standard cost","highest standard cost",
   "top materials by standard cost","standard price by material","standard price list"],
  ["standard","cost","material","price","keko","highest","stprs"],
  ["KEKO","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       k.matnr AS material_number,
       k.stprs AS standard_price,
       k.peinh AS price_unit,
       k.hwaer AS currency,
       k.werks AS plant
FROM KEKO k
LEFT JOIN MAKT m ON k.matnr = m.matnr AND m.spras = 'E'
WHERE k.stprs IS NOT NULL AND CAST(k.stprs AS TEXT) != '0'
ORDER BY k.stprs DESC
LIMIT 20
""",
  priority=3)

q("cost_details_by_material",
  "Top 20 materials by total itemized cost value (CKIS)",
  ["costing by material","cost elements by material","production cost by material",
   "itemized cost by material","CKIS cost by material"],
  ["cost","costing","material","ckis","element","production","itemized","wertn"],
  ["CKIS","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       ci.matnr AS material_number,
       SUM(ci.wertn) AS total_cost_value,
       ci.hwaer AS currency
FROM CKIS ci
LEFT JOIN MAKT m ON ci.matnr = m.matnr AND m.spras = 'E'
WHERE ci.matnr IS NOT NULL AND ci.wertn IS NOT NULL
GROUP BY ci.matnr, m.maktx, ci.hwaer
HAVING SUM(ci.wertn) > 0
ORDER BY total_cost_value DESC
LIMIT 20
""")

q("standard_cost_by_plant",
  "Standard cost by plant",
  ["standard cost by plant","material cost by plant","KEKO by plant"],
  ["standard","cost","plant","werks","keko"],
  ["KEKO","MAKT"],
  f"""
SELECT k.werks AS plant,
       COUNT(DISTINCT k.matnr) AS material_count,
       AVG(k.stprs) AS avg_standard_price,
       k.hwaer AS currency
FROM KEKO k
WHERE k.stprs IS NOT NULL
GROUP BY k.werks, k.hwaer
ORDER BY avg_standard_price DESC
""")

q("actual_cost_by_period",
  "Actual material cost by period (CKMLCR)",
  ["actual cost by period","material actual cost","CKMLCR cost","moving average price by period"],
  ["actual","cost","period","ckmlcr","moving","average","price"],
  ["CKMLCR","CKMLHD","MAKT"],
  f"""
SELECT cr.bdatj AS fiscal_year,
       cr.poper AS period,
       cr.stprs AS standard_price,
       cr.pvprs AS moving_avg_price,
       hd.matnr AS material_number,
       m.maktx AS material_name
FROM CKMLCR cr
JOIN CKMLHD hd ON cr.kalnr = hd.kalnr
LEFT JOIN MAKT m ON hd.matnr = m.matnr AND m.spras = 'E'
WHERE cr.stprs IS NOT NULL
ORDER BY cr.bdatj ASC, cr.poper ASC
LIMIT 200
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: MATERIAL MASTER — MAKT, MARC
# ══════════════════════════════════════════════════════════════════════════════

q("all_materials",
  "List all materials with descriptions",
  ["list all materials","show all materials","all products","material list","list of products",
   "show me all materials","all material descriptions","material catalog"],
  ["material","list","all","show","products","makt","catalog","descriptions"],
  ["MAKT"],
  f"""
SELECT m.matnr AS material_number,
       m.maktx AS material_description
FROM MAKT m
WHERE m.spras = 'E' AND m.maktx IS NOT NULL AND m.maktx != ''
ORDER BY m.maktx ASC
LIMIT 500
""",
  neg_keywords=["sales","purchase","cost","vendor","top","highest","by"])

q("materials_by_plant",
  "Materials assigned to each plant (MARC)",
  ["materials by plant","material plant assignment","which materials are in each plant",
   "plants per material","materials per plant"],
  ["material","plant","werks","marc","assigned","plants"],
  ["MARC","MAKT"],
  f"""
SELECT mc.werks AS plant,
       mc.matnr AS material_number,
       m.maktx AS material_name,
       mc.maabc AS abc_class,
       mc.dismm AS mrp_type,
       mc.prctr AS profit_center
FROM MARC mc
LEFT JOIN MAKT m ON mc.matnr = m.matnr AND m.spras = 'E'
WHERE mc.matnr IS NOT NULL
ORDER BY mc.werks ASC, m.maktx ASC
LIMIT 500
""")

q("material_count_by_plant",
  "Number of materials per plant",
  ["material count by plant","how many materials per plant","number of materials by plant",
   "materials in each plant count"],
  ["material","count","plant","how many","number","per","werks"],
  ["MARC"],
  f"""
SELECT mc.werks AS plant,
       COUNT(DISTINCT mc.matnr) AS material_count
FROM MARC mc
GROUP BY mc.werks
ORDER BY material_count DESC
""")

q("batch_managed_materials",
  "Materials with batch management active (xchar='X')",
  ["batch managed materials","materials with batch","batch materials","batch tracking materials"],
  ["batch","material","xchar","managed","tracking"],
  ["MARC","MAKT"],
  f"""
SELECT mc.matnr AS material_number,
       m.maktx AS material_name,
       mc.werks AS plant
FROM MARC mc
LEFT JOIN MAKT m ON mc.matnr = m.matnr AND m.spras = 'E'
WHERE mc.xchar = 'X'
ORDER BY m.maktx ASC
LIMIT 200
""")

q("material_count_by_abc",
  "Material count by ABC class",
  ["material count by ABC class","ABC classification materials",
   "how many materials in each ABC class","ABC indicator breakdown"],
  ["material","abc","class","classification","count","indicator"],
  ["MARC"],
  f"""
SELECT mc.maabc AS abc_class,
       mc.werks AS plant,
       COUNT(DISTINCT mc.matnr) AS material_count
FROM MARC mc
WHERE mc.maabc IS NOT NULL AND mc.maabc != ''
GROUP BY mc.maabc, mc.werks
ORDER BY mc.maabc ASC
""")

q("material_count_by_mrp_type",
  "Material count by MRP type (dismm)",
  ["material count by MRP type","MRP type breakdown","materials by planning type"],
  ["material","mrp","planning","dismm","type","count"],
  ["MARC"],
  f"""
SELECT mc.dismm AS mrp_type,
       COUNT(DISTINCT mc.matnr) AS material_count
FROM MARC mc
WHERE mc.dismm IS NOT NULL AND mc.dismm != ''
GROUP BY mc.dismm
ORDER BY material_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: ACCOUNTS RECEIVABLE — BSAD
# ══════════════════════════════════════════════════════════════════════════════

q("ar_by_customer_top20",
  "Top 20 customers by cleared AR amount (BSAD)",
  ["accounts receivable by customer","cleared AR by customer","BSAD top customers",
   "customer AR balance","top customers by AR"],
  ["accounts","receivable","ar","bsad","cleared","customer"],
  ["BSAD","KNA1"],
  f"""
SELECT k.name1 AS customer_name,
       bs.kunnr AS customer_number,
       SUM(bs.dmbtr) AS total_amount,
       bs.waers AS currency,
       COUNT(DISTINCT bs.belnr) AS document_count
FROM BSAD bs
LEFT JOIN KNA1 k ON bs.kunnr = k.kunnr
WHERE bs.dmbtr IS NOT NULL
GROUP BY bs.kunnr, k.name1, bs.waers
HAVING SUM(bs.dmbtr) > 0
ORDER BY total_amount DESC
LIMIT 20
""")

q("ar_by_year",
  "Accounts receivable amount by year (BSAD)",
  ["AR by year","accounts receivable by year","BSAD by year","AR trend by year"],
  ["accounts","receivable","ar","bsad","year","gjahr"],
  ["BSAD"],
  f"""
SELECT bs.gjahr AS fiscal_year,
       SUM(bs.dmbtr) AS total_amount,
       bs.waers AS currency
FROM BSAD bs
WHERE bs.dmbtr IS NOT NULL
GROUP BY bs.gjahr, bs.waers
ORDER BY bs.gjahr ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: COST CENTER ACTUALS — COEP
# ══════════════════════════════════════════════════════════════════════════════

q("cost_by_cost_center_top20",
  "Top 20 cost centers by actual cost (COEP)",
  ["cost by cost center","top cost centers","highest cost centers",
   "actual cost by cost center","cost center spending"],
  ["cost","center","actual","coep","csks","highest","top","spending","kostl"],
  ["COEP","CSKS"],
  f"""
SELECT cp.kostl AS cost_center,
       cs.ltext AS cost_center_name,
       SUM(cp.wtgbtr) AS total_actual_cost,
       cp.kokrs AS controlling_area
FROM COEP cp
LEFT JOIN CSKS cs ON cp.kostl = cs.kostl AND cp.kokrs = cs.kokrs
WHERE cp.wtgbtr IS NOT NULL
GROUP BY cp.kostl, cs.ltext, cp.kokrs
HAVING SUM(cp.wtgbtr) > 0
ORDER BY total_actual_cost DESC
LIMIT 20
""")

q("cost_by_year_coep",
  "Actual cost by year from COEP",
  ["actual cost by year","COEP by year","cost center cost by year"],
  ["cost","actual","year","coep","period","fiscal"],
  ["COEP"],
  f"""
SELECT SUBSTRING(cp.perio, 1, 4) AS fiscal_year,
       SUM(cp.wtgbtr) AS total_actual_cost,
       COUNT(*) AS entry_count
FROM COEP cp
WHERE cp.wtgbtr IS NOT NULL AND cp.perio IS NOT NULL AND cp.perio != ''
GROUP BY fiscal_year
ORDER BY fiscal_year ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: DELIVERIES — LIKP + LIPS
# ══════════════════════════════════════════════════════════════════════════════

q("deliveries_by_customer_top20",
  "Top 20 customers by number of deliveries",
  ["deliveries by customer","top customers by delivery","how many deliveries per customer"],
  ["delivery","customer","top","count","deliveries","likp","lips"],
  ["LIKP","KNA1"],
  f"""
SELECT lk.kunnr AS customer_number,
       k.name1 AS customer_name,
       COUNT(DISTINCT lk.vbeln) AS delivery_count,
       lk.vstel AS shipping_point
FROM LIKP lk
LEFT JOIN KNA1 k ON lk.kunnr = k.kunnr
WHERE lk.kunnr IS NOT NULL
GROUP BY lk.kunnr, k.name1, lk.vstel
ORDER BY delivery_count DESC
LIMIT 20
""")

q("deliveries_by_year",
  "Delivery count by year",
  ["deliveries by year","delivery trend by year","annual deliveries"],
  ["delivery","year","annual","deliveries","likp"],
  ["LIKP"],
  f"""
SELECT SUBSTRING(lk.erdat, 1, 4) AS year,
       COUNT(DISTINCT lk.vbeln) AS delivery_count
FROM LIKP lk
WHERE lk.erdat IS NOT NULL AND lk.erdat != ''
GROUP BY year
ORDER BY year ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: BILL OF MATERIALS — STKO + STPO
# ══════════════════════════════════════════════════════════════════════════════

q("bom_by_material",
  "BOM component count per material (top 20 most complex)",
  ["BOM by material","bill of materials components","number of components per product",
   "BOM structure","most complex products by components"],
  ["bom","bill","materials","components","stko","stpo","structure"],
  ["STKO","STPO"],
  f"""
SELECT st.stlnr AS bom_number,
       st.stlty AS bom_type,
       COUNT(sp.stlkn) AS component_count
FROM STKO st
JOIN STPO sp ON st.stlnr = sp.stlnr AND st.stlal = sp.stlal
GROUP BY st.stlnr, st.stlty
ORDER BY component_count DESC
LIMIT 50
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13: RESERVATIONS — RESB
# ══════════════════════════════════════════════════════════════════════════════

q("reservations_by_material",
  "Top 20 materials by reserved quantity (RESB)",
  ["material reservations","reserved quantity by material","top reserved materials",
   "what materials are reserved","reservation list by material"],
  ["reservation","reserved","material","quantity","resb","bdmng"],
  ["RESB","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       rs.matnr AS material_number,
       SUM(rs.bdmng) AS reserved_quantity,
       SUM(rs.enmng) AS issued_quantity
FROM RESB rs
LEFT JOIN MAKT m ON rs.matnr = m.matnr AND m.spras = 'E'
WHERE rs.matnr IS NOT NULL AND rs.matnr != ''
GROUP BY rs.matnr, m.maktx
HAVING SUM(rs.bdmng) > 0
ORDER BY reserved_quantity DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14: PURCHASE REQUISITIONS — EBAN
# ══════════════════════════════════════════════════════════════════════════════

q("purchase_req_by_material",
  "Purchase requisitions by material (top 20)",
  ["purchase requisitions by material","purchase requests by material","PR by material",
   "requisition count by material"],
  ["requisition","request","material","eban","pr","banfn"],
  ["EBAN","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       eb.matnr AS material_number,
       COUNT(DISTINCT eb.banfn) AS requisition_count,
       SUM(eb.menge) AS total_quantity
FROM EBAN eb
LEFT JOIN MAKT m ON eb.matnr = m.matnr AND m.spras = 'E'
WHERE eb.matnr IS NOT NULL AND eb.matnr != ''
GROUP BY eb.matnr, m.maktx
ORDER BY requisition_count DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15: MATERIAL DOCUMENTS — MKPF
# ══════════════════════════════════════════════════════════════════════════════

q("material_docs_by_year",
  "Material document count by year (MKPF — header only, no material detail)",
  ["material documents by year","goods movements by year","MKPF by year",
   "how many goods movements per year"],
  ["material","document","year","mkpf","goods","movement","mblnr"],
  ["MKPF"],
  f"""
SELECT SUBSTRING(mk.budat, 1, 4) AS year,
       COUNT(DISTINCT mk.mblnr) AS document_count
FROM MKPF mk
WHERE mk.budat IS NOT NULL AND mk.budat != ''
GROUP BY year
ORDER BY year ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16: INTERNAL ORDERS — AUFK
# ══════════════════════════════════════════════════════════════════════════════

q("orders_by_type",
  "Internal order count by order type (AUFK)",
  ["internal orders by type","order count by type","AUFK by order type",
   "how many orders per type"],
  ["order","type","aufk","internal","count","auart"],
  ["AUFK"],
  f"""
SELECT ak.auart AS order_type,
       ak.werks AS plant,
       COUNT(DISTINCT ak.aufnr) AS order_count
FROM AUFK ak
WHERE ak.auart IS NOT NULL
GROUP BY ak.auart, ak.werks
ORDER BY order_count DESC
""")

q("orders_by_plant",
  "Internal orders by plant (AUFK)",
  ["internal orders by plant","AUFK by plant","orders per plant"],
  ["order","plant","aufk","werks","internal"],
  ["AUFK"],
  f"""
SELECT ak.werks AS plant,
       COUNT(DISTINCT ak.aufnr) AS order_count
FROM AUFK ak
WHERE ak.werks IS NOT NULL AND ak.werks != ''
GROUP BY ak.werks
ORDER BY order_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17: KONV — PRICING CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════

q("pricing_conditions_top20",
  "Top 20 pricing condition types by value (KONV)",
  ["pricing conditions","pricing by condition type","KONV top conditions"],
  ["pricing","condition","konv","kschl","kbetr"],
  ["KONV"],
  f"""
SELECT kv.kschl AS condition_type,
       SUM(kv.kbetr) AS total_condition_value,
       kv.waers AS currency,
       COUNT(*) AS condition_count
FROM KONV kv
WHERE kv.kbetr IS NOT NULL AND kv.kschl IS NOT NULL
GROUP BY kv.kschl, kv.waers
HAVING SUM(kv.kbetr) > 0
ORDER BY total_condition_value DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18: CROSS-TABLE SUMMARIES
# ══════════════════════════════════════════════════════════════════════════════

q("total_sales_vs_purchase",
  "Compare total sales revenue vs total purchase cost",
  ["compare sales and purchase","sales vs purchase comparison","revenue vs cost overall",
   "total sales versus total purchase","overall revenue vs spend"],
  ["compare","sales","purchase","versus","vs","revenue","cost","overall"],
  ["VBRK","vbrp","EKPO","EKKO"],
  f"""
SELECT 'Sales Revenue' AS category,
       SUM({tc('vbrp','netwr')}) AS total_amount
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
UNION ALL
SELECT 'Purchase Cost',
       SUM(ep.netwr)
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
WHERE ep.netwr IS NOT NULL
""")

q("sales_purchase_by_material",
  "Sales revenue vs purchase cost by material (top 20)",
  ["product profitability","margin by product","sales vs cost by product",
   "revenue vs purchase cost by material","profit margin by material"],
  ["profitability","margin","product","material","revenue","cost","profit","sales","purchase"],
  ["vbrp","VBRK","EKPO","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       s.matnr AS material_number,
       s.total_sales,
       p.total_purchase_cost
FROM (
  SELECT TRIM(v.matnr) AS matnr, SUM({tc('vbrp','netwr')}) AS total_sales
  FROM vbrp v
  JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
  WHERE v.matnr IS NOT NULL AND TRIM(v.matnr) != ''
  GROUP BY TRIM(v.matnr)
) s
JOIN (
  SELECT ep.matnr, SUM(ep.netwr) AS total_purchase_cost
  FROM EKPO ep
  WHERE ep.matnr IS NOT NULL AND ep.netwr IS NOT NULL
  GROUP BY ep.matnr
) p ON s.matnr = p.matnr
LEFT JOIN MAKT m ON s.matnr = m.matnr AND m.spras = 'E'
ORDER BY s.total_sales DESC
LIMIT 20
""")

q("sales_ekpo_purchase_by_material",
  "Total purchase quantity and cost for each material using EKPO",
  ["total purchased quantity and cost by material using EKPO","EKPO quantity and cost",
   "what is total purchase quantity and cost for each material",
   "purchase quantity and cost per material EKPO"],
  ["purchase","quantity","cost","material","ekpo","total","each"],
  ["EKPO","EKKO","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       ep.matnr AS material_number,
       SUM(ep.menge) AS total_quantity,
       SUM(ep.netwr) AS total_purchase_cost,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
LEFT JOIN MAKT m ON ep.matnr = m.matnr AND m.spras = 'E'
WHERE ep.matnr IS NOT NULL AND ep.matnr != ''
GROUP BY ep.matnr, m.maktx, ek.waers
HAVING SUM(ep.menge) > 0 OR SUM(ep.netwr) > 0
ORDER BY total_purchase_cost DESC NULLS LAST
LIMIT 50
""",
  priority=8)  # High priority — matches the exact client complaint


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 19: MARA — General Material Data
# (material type, base UOM, weight, industry sector, product hierarchy)
# ══════════════════════════════════════════════════════════════════════════════

q("mara_by_material_type",
  "Material count by material type (MARA)",
  ["materials by type","material type breakdown","how many materials of each type",
   "MARA by material type","raw materials vs finished goods count"],
  ["material","type","mara","mtart","count","raw","finished","goods"],
  ["MARA"],
  f"""
SELECT ma.mtart AS material_type,
       COUNT(DISTINCT ma.matnr) AS material_count
FROM MARA ma
WHERE ma.mtart IS NOT NULL AND ma.mtart != ''
GROUP BY ma.mtart
ORDER BY material_count DESC
""")

q("mara_material_list",
  "List all materials with type and unit of measure (MARA)",
  ["material master list","all materials with details","material type and UOM",
   "MARA material list","material base unit"],
  ["material","master","mara","type","uom","unit","measure","mtart","meins"],
  ["MARA","MAKT"],
  f"""
SELECT ma.matnr AS material_number,
       m.maktx AS material_name,
       ma.mtart AS material_type,
       ma.meins AS base_uom,
       ma.matkl AS material_group,
       ma.brgew AS gross_weight,
       ma.gewei AS weight_unit
FROM MARA ma
LEFT JOIN MAKT m ON ma.matnr = m.matnr AND m.spras = 'E'
WHERE ma.matnr IS NOT NULL
ORDER BY m.maktx ASC
LIMIT 500
""")

q("mara_by_material_group",
  "Material count by material group (MARA)",
  ["materials by material group","material group breakdown","how many materials per group"],
  ["material","group","matkl","mara","count"],
  ["MARA"],
  f"""
SELECT ma.matkl AS material_group,
       COUNT(DISTINCT ma.matnr) AS material_count
FROM MARA ma
WHERE ma.matkl IS NOT NULL AND ma.matkl != ''
GROUP BY ma.matkl
ORDER BY material_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 20: MBEW — Material Valuation (stock values by plant)
# ══════════════════════════════════════════════════════════════════════════════

q("stock_value_by_material",
  "Top 20 materials by stock value (MBEW)",
  ["stock value by material","inventory value by material","material stock worth",
   "which material has highest stock value","MBEW top materials"],
  ["stock","value","material","inventory","mbew","worth","highest"],
  ["MBEW","MAKT"],
  f"""
SELECT mb.matnr AS material_number,
       m.maktx AS material_name,
       mb.bwkey AS valuation_area,
       mb.stprs AS standard_price,
       mb.verpr AS moving_avg_price,
       mb.lbkum AS total_stock_qty,
       mb.salk3 AS total_stock_value,
       mb.waers AS currency
FROM MBEW mb
LEFT JOIN MAKT m ON mb.matnr = m.matnr AND m.spras = 'E'
WHERE mb.salk3 IS NOT NULL
ORDER BY mb.salk3 DESC
LIMIT 20
""")

q("stock_value_by_plant",
  "Total inventory/stock value by plant (MBEW)",
  ["stock value by plant","inventory value by plant","MBEW by plant","plant inventory worth"],
  ["stock","value","plant","inventory","mbew","werks","bwkey"],
  ["MBEW"],
  f"""
SELECT mb.bwkey AS valuation_area_plant,
       SUM(mb.salk3) AS total_stock_value,
       SUM(mb.lbkum) AS total_stock_qty,
       mb.waers AS currency
FROM MBEW mb
WHERE mb.salk3 IS NOT NULL
GROUP BY mb.bwkey, mb.waers
HAVING SUM(mb.salk3) > 0
ORDER BY total_stock_value DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 21: MARD — Storage Location Stock
# ══════════════════════════════════════════════════════════════════════════════

q("stock_by_storage_location",
  "Stock quantity by storage location (MARD)",
  ["stock by storage location","inventory by location","MARD stock","storage location stock",
   "unrestricted stock by location"],
  ["stock","storage","location","mard","lgort","unrestricted","inventory","sloc"],
  ["MARD","MAKT"],
  f"""
SELECT md.matnr AS material_number,
       m.maktx AS material_name,
       md.werks AS plant,
       md.lgort AS storage_location,
       md.labst AS unrestricted_stock,
       md.einme AS restricted_stock,
       md.umlme AS stock_in_transfer
FROM MARD md
LEFT JOIN MAKT m ON md.matnr = m.matnr AND m.spras = 'E'
WHERE md.labst > 0
ORDER BY md.labst DESC
LIMIT 100
""")

q("stock_by_plant_location",
  "Total unrestricted stock by plant and storage location (MARD)",
  ["total stock by plant and location","plant storage stock summary","MARD by plant",
   "where is stock located","stock location summary"],
  ["stock","plant","location","mard","unrestricted","summary"],
  ["MARD"],
  f"""
SELECT md.werks AS plant,
       md.lgort AS storage_location,
       COUNT(DISTINCT md.matnr) AS material_count,
       SUM(md.labst) AS total_unrestricted_stock
FROM MARD md
WHERE md.labst IS NOT NULL
GROUP BY md.werks, md.lgort
HAVING SUM(md.labst) > 0
ORDER BY total_unrestricted_stock DESC
LIMIT 50
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 22: MSEG — Material Document Items (Goods Movements)
# NOTE: May or may not be in DB — the DB notes say MSEG may be absent.
# Catalog entry is included; SQL will fail gracefully if table doesn't exist.
# ══════════════════════════════════════════════════════════════════════════════

q("goods_movements_by_material",
  "Top 20 materials by goods movement quantity (MSEG)",
  ["goods movements by material","MSEG by material","goods receipt by material",
   "goods issue by material","material movements"],
  ["goods","movement","material","mseg","receipt","issue","bwart","mblnr"],
  ["MSEG","MAKT"],
  f"""
SELECT ms.matnr AS material_number,
       m.maktx AS material_name,
       ms.bwart AS movement_type,
       SUM(ms.menge) AS total_quantity,
       ms.meins AS unit
FROM MSEG ms
LEFT JOIN MAKT m ON ms.matnr = m.matnr AND m.spras = 'E'
WHERE ms.matnr IS NOT NULL AND ms.matnr != '' AND ms.menge IS NOT NULL
GROUP BY ms.matnr, m.maktx, ms.bwart, ms.meins
HAVING SUM(ms.menge) > 0
ORDER BY total_quantity DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 23: SKA1 + SKAT — GL Account Master
# ══════════════════════════════════════════════════════════════════════════════

q("gl_account_list",
  "List all GL accounts with descriptions (SKA1 + SKAT)",
  ["list GL accounts","all GL accounts","GL account master","chart of accounts",
   "show GL accounts","GL account descriptions"],
  ["gl","account","chart","accounts","ska1","skat","description","list"],
  ["SKA1","SKAT"],
  f"""
SELECT sa.saknr AS gl_account,
       st.txt20 AS short_description,
       st.txt50 AS long_description,
       sa.ktoks AS account_group
FROM SKA1 sa
LEFT JOIN SKAT st ON sa.saknr = st.saknr AND sa.ktopl = st.ktopl AND st.spras = 'E'
WHERE sa.saknr IS NOT NULL
ORDER BY sa.saknr ASC
LIMIT 500
""")

q("gl_account_count_by_group",
  "GL account count by account group (SKA1)",
  ["GL accounts by group","account group breakdown","how many GL accounts per group"],
  ["gl","account","group","count","ska1","ktoks"],
  ["SKA1"],
  f"""
SELECT sa.ktoks AS account_group,
       COUNT(DISTINCT sa.saknr) AS account_count
FROM SKA1 sa
WHERE sa.ktoks IS NOT NULL AND sa.ktoks != ''
GROUP BY sa.ktoks
ORDER BY account_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 24: T001 — Company Codes
# ══════════════════════════════════════════════════════════════════════════════

q("company_codes_list",
  "List all company codes (T001)",
  ["list company codes","all company codes","company code master","which company codes exist",
   "show company codes"],
  ["company","code","t001","bukrs","list","all"],
  ["T001"],
  f"""
SELECT t.bukrs AS company_code,
       t.butxt AS company_name,
       t.land1 AS country,
       t.waers AS currency
FROM T001 t
WHERE t.bukrs IS NOT NULL
ORDER BY t.bukrs ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 25: T001W — Plants
# ══════════════════════════════════════════════════════════════════════════════

q("plant_list",
  "List all plants (T001W)",
  ["list all plants","all plants","plant master","which plants exist","show plants","plant names"],
  ["plant","t001w","werks","list","all","plants","name"],
  ["T001W"],
  f"""
SELECT t.werks AS plant,
       t.name1 AS plant_name,
       t.land1 AS country,
       t.ort01 AS city,
       t.bukrs AS company_code
FROM T001W t
WHERE t.werks IS NOT NULL
ORDER BY t.werks ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 26: TCURR — Exchange Rates
# ══════════════════════════════════════════════════════════════════════════════

q("exchange_rates",
  "Current exchange rates (TCURR)",
  ["exchange rates","currency rates","conversion rates","USD to EUR rate",
   "what is exchange rate","currency conversion table"],
  ["exchange","rate","currency","tcurr","conversion","usd","eur","kurs"],
  ["TCURR"],
  f"""
SELECT tc.fcurr AS from_currency,
       tc.tcurr AS to_currency,
       tc.ukurs AS exchange_rate,
       tc.gdatu AS valid_from_date
FROM TCURR tc
WHERE tc.kurst = 'M'
ORDER BY tc.gdatu DESC
LIMIT 100
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 27: EKBE — Purchase Order History (GR/IR)
# ══════════════════════════════════════════════════════════════════════════════

q("po_history_by_vendor",
  "Purchase order goods receipt/invoice history by vendor (EKBE)",
  ["PO history by vendor","goods receipt history","EKBE by vendor","purchase order completion",
   "which POs have been received","GR IR matching"],
  ["purchase","order","history","ekbe","goods","receipt","invoice","gr","ir","vendor"],
  ["EKBE","EKKO","LFA1"],
  f"""
SELECT l.name1 AS vendor_name,
       ek.lifnr AS vendor_number,
       be.vgabe AS transaction_type,
       COUNT(DISTINCT be.ebeln) AS po_count,
       SUM(be.menge) AS total_quantity,
       SUM(be.wrbtr) AS total_amount,
       ek.waers AS currency
FROM EKBE be
JOIN EKKO ek ON be.ebeln = ek.ebeln
LEFT JOIN LFA1 l ON ek.lifnr = l.lifnr
WHERE be.wrbtr IS NOT NULL
GROUP BY l.name1, ek.lifnr, be.vgabe, ek.waers
HAVING SUM(be.wrbtr) > 0
ORDER BY total_amount DESC
LIMIT 20
""")

q("po_open_vs_received",
  "PO ordered vs received quantity by material (EKBE)",
  ["open purchase orders","PO delivery status","ordered vs received","how much of PO is received"],
  ["purchase","order","open","received","delivered","ekbe","menge","status"],
  ["EKBE","EKPO","MAKT"],
  f"""
SELECT ep.matnr AS material_number,
       m.maktx AS material_name,
       SUM(ep.menge) AS ordered_quantity,
       SUM(CASE WHEN be.vgabe = '1' THEN be.menge ELSE 0 END) AS received_quantity,
       ep.meins AS unit
FROM EKPO ep
LEFT JOIN EKBE be ON ep.ebeln = be.ebeln AND ep.ebelp = be.ebelp
LEFT JOIN MAKT m ON ep.matnr = m.matnr AND m.spras = 'E'
WHERE ep.matnr IS NOT NULL AND ep.matnr != ''
GROUP BY ep.matnr, m.maktx, ep.meins
HAVING SUM(ep.menge) > 0
ORDER BY ordered_quantity DESC
LIMIT 50
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 28: KNB1 — Customer Company Code Data
# ══════════════════════════════════════════════════════════════════════════════

q("customer_by_company_code",
  "Customer count by company code (KNB1)",
  ["customers by company code","customer assignment to company","KNB1 company code",
   "how many customers per company code"],
  ["customer","company","code","knb1","bukrs","count"],
  ["KNB1"],
  f"""
SELECT kb.bukrs AS company_code,
       COUNT(DISTINCT kb.kunnr) AS customer_count
FROM KNB1 kb
WHERE kb.bukrs IS NOT NULL
GROUP BY kb.bukrs
ORDER BY customer_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 29: MAST — Material to BOM Link
# ══════════════════════════════════════════════════════════════════════════════

q("bom_by_parent_material",
  "BOM structure: components for each parent material (MAST + STPO)",
  ["BOM by material","bill of materials for product","components of each product",
   "what is in each product BOM","BOM structure by material","MAST STPO components"],
  ["bom","bill","material","components","mast","stpo","structure","parent"],
  ["MAST","STPO","MAKT"],
  f"""
SELECT pm.maktx AS parent_material_name,
       ms.matnr AS parent_material_number,
       cm.maktx AS component_name,
       sp.idnrk AS component_number,
       sp.menge AS component_quantity,
       sp.meins AS unit
FROM MAST ms
JOIN STPO sp ON ms.stlnr = sp.stlnr AND ms.stlal = sp.stlal
LEFT JOIN MAKT pm ON ms.matnr = pm.matnr AND pm.spras = 'E'
LEFT JOIN MAKT cm ON sp.idnrk = cm.matnr AND cm.spras = 'E'
WHERE ms.matnr IS NOT NULL
ORDER BY pm.maktx ASC, sp.posnr ASC
LIMIT 200
""",
  priority=3)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 30: COSP — Cost Center Plan Costs
# ══════════════════════════════════════════════════════════════════════════════

q("planned_cost_by_cost_center",
  "Planned cost by cost center (COSP)",
  ["planned cost by cost center","budget by cost center","COSP cost center plan",
   "cost center planned vs actual","budgeted cost per cost center"],
  ["planned","cost","center","budget","cosp","versn","gjahr"],
  ["COSP","CSKS"],
  f"""
SELECT cs.objnr AS object_number,
       cs.gjahr AS fiscal_year,
       SUM(cs.wtp001 + cs.wtp002 + cs.wtp003 + cs.wtp004 + cs.wtp005 +
           cs.wtp006 + cs.wtp007 + cs.wtp008 + cs.wtp009 + cs.wtp010 +
           cs.wtp011 + cs.wtp012) AS total_planned_cost
FROM COSP cs
WHERE cs.versn = '0' AND cs.wrttp = '01'
GROUP BY cs.objnr, cs.gjahr
HAVING SUM(cs.wtp001 + cs.wtp002 + cs.wtp003 + cs.wtp004 + cs.wtp005 +
           cs.wtp006 + cs.wtp007 + cs.wtp008 + cs.wtp009 + cs.wtp010 +
           cs.wtp011 + cs.wtp012) > 0
ORDER BY total_planned_cost DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 31: KEPH — Cost Component Split (detailed breakdown)
# ══════════════════════════════════════════════════════════════════════════════

q("cost_component_split",
  "Cost component split by material (KEPH + KEKO)",
  ["cost component breakdown","material cost split","KEPH cost elements",
   "material cost by component","cost structure by element"],
  ["cost","component","split","keph","keko","breakdown","element","structure"],
  ["KEPH","KEKO","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       ke.matnr AS material_number,
       ke.werks AS plant,
       kh.keart AS cost_component,
       SUM(kh.kstpr) AS plan_cost_value,
       ke.hwaer AS currency
FROM KEPH kh
JOIN KEKO ke ON kh.kalnr = ke.kalnr AND kh.kalka = ke.kalka
LEFT JOIN MAKT m ON ke.matnr = m.matnr AND m.spras = 'E'
WHERE kh.kstpr IS NOT NULL AND kh.kstpr != 0
GROUP BY m.maktx, ke.matnr, ke.werks, kh.keart, ke.hwaer
ORDER BY ABS(SUM(kh.kstpr)) DESC
LIMIT 50
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 32: VBUK + VBUP — Sales Document Status
# ══════════════════════════════════════════════════════════════════════════════

q("sales_order_status",
  "Sales order status breakdown (VBUK)",
  ["sales order status","order completion status","open orders","completed orders",
   "VBUK order status","how many orders are open vs completed"],
  ["sales","order","status","vbuk","open","completed","gbsta","uvall"],
  ["VBUK"],
  f"""
SELECT vk.gbsta AS overall_status,
       COUNT(DISTINCT vk.vbeln) AS order_count
FROM VBUK vk
WHERE vk.vbeln IS NOT NULL
GROUP BY vk.gbsta
ORDER BY order_count DESC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 33: CEPC — Profit Center Master
# ══════════════════════════════════════════════════════════════════════════════

q("profit_center_list",
  "List all profit centers (CEPC)",
  ["list profit centers","all profit centers","profit center master","CEPC profit centers",
   "show profit centers"],
  ["profit","center","cepc","prctr","list","all","name"],
  ["CEPC"],
  f"""
SELECT cp.prctr AS profit_center,
       cp.kokrs AS controlling_area,
       cp.abtei AS department,
       cp.verak AS person_responsible
FROM CEPC cp
WHERE cp.prctr IS NOT NULL AND cp.prctr != ''
ORDER BY cp.kokrs ASC, cp.prctr ASC
LIMIT 200
""")

q("sales_by_profit_center",
  "Sales by profit center (vbrp.prctr)",
  ["sales by profit center","revenue by profit center","profit center sales"],
  ["profit","center","sales","revenue","prctr"],
  ["vbrp","VBRK"],
  f"""
SELECT v.prctr AS profit_center,
       SUM({tc('vbrp','netwr')}) AS total_sales,
       vk.waerk AS currency
FROM vbrp v
JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln)
WHERE v.prctr IS NOT NULL AND v.prctr != ''
GROUP BY v.prctr, vk.waerk
HAVING SUM({tc('vbrp','netwr')}) > 0
ORDER BY total_sales DESC
LIMIT 20
""")

q("purchase_by_profit_center",
  "Purchase amount by profit center (EKPO.prctr)",
  ["purchase by profit center","procurement by profit center","cost by profit center"],
  ["profit","center","purchase","procurement","prctr","ekpo"],
  ["EKPO","EKKO"],
  f"""
SELECT ep.prctr AS profit_center,
       SUM(ep.netwr) AS total_purchase_amount,
       ek.waers AS currency
FROM EKPO ep
JOIN EKKO ek ON ep.ebeln = ek.ebeln
WHERE ep.prctr IS NOT NULL AND ep.prctr != '' AND ep.netwr IS NOT NULL
GROUP BY ep.prctr, ek.waers
HAVING SUM(ep.netwr) > 0
ORDER BY total_purchase_amount DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 34: VBFA — Sales Document Flow
# ══════════════════════════════════════════════════════════════════════════════

q("order_to_billing_flow",
  "Sales document flow: orders to deliveries to invoices (VBFA)",
  ["sales document flow","order to invoice","order fulfillment flow","VBFA document flow",
   "how many orders are billed"],
  ["sales","document","flow","vbfa","billing","delivery","order","fulfillment"],
  ["VBFA"],
  f"""
SELECT vf.vbtyp_n AS target_doc_type,
       COUNT(DISTINCT vf.vbelv) AS source_doc_count,
       COUNT(DISTINCT vf.vbeln) AS target_doc_count,
       SUM(vf.rfwrt) AS total_value,
       vf.waers AS currency
FROM VBFA vf
WHERE vf.vbtyp_n IS NOT NULL
GROUP BY vf.vbtyp_n, vf.waers
ORDER BY total_value DESC NULLS LAST
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 35: CRHD — Work Centers / Resource Master
# ══════════════════════════════════════════════════════════════════════════════

q("work_centers_list",
  "List work centers (CRHD)",
  ["list work centers","work center master","production resources","CRHD work centers",
   "manufacturing work centers"],
  ["work","center","crhd","resource","production","manufacturing","objid"],
  ["CRHD"],
  f"""
SELECT cr.objid AS work_center,
       cr.objty AS object_type,
       cr.werks AS plant,
       cr.begda AS valid_from,
       cr.endda AS valid_to
FROM CRHD cr
WHERE cr.objid IS NOT NULL AND cr.objty = 'A'
ORDER BY cr.werks ASC, cr.objid ASC
LIMIT 200
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 36: MVKE — Material Sales Data
# ══════════════════════════════════════════════════════════════════════════════

q("material_sales_data",
  "Materials with sales organization data (MVKE)",
  ["material sales data","product sales org assignment","MVKE materials",
   "which materials are active for sales"],
  ["material","sales","organization","mvke","vkorg","active"],
  ["MVKE","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       mv.matnr AS material_number,
       mv.vkorg AS sales_org,
       mv.vtweg AS distribution_channel,
       mv.vmsta AS sales_status
FROM MVKE mv
LEFT JOIN MAKT m ON mv.matnr = m.matnr AND m.spras = 'E'
WHERE mv.matnr IS NOT NULL
ORDER BY mv.vkorg ASC, m.maktx ASC
LIMIT 200
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 37: VBAK — Sales Orders (header)
# ══════════════════════════════════════════════════════════════════════════════

q("sales_orders_by_customer_top20",
  "Top 20 customers by number of sales orders (VBAK)",
  ["sales orders by customer","top customers by orders","VBAK by customer",
   "who has most sales orders","order count by customer"],
  ["sales","order","customer","vbak","count","orders","kunnr","kunag"],
  ["VBAK","KNA1"],
  f"""
SELECT va.kunnr AS customer_number,
       k.name1 AS customer_name,
       COUNT(DISTINCT va.vbeln) AS order_count,
       va.auart AS order_type
FROM VBAK va
LEFT JOIN KNA1 k ON va.kunnr = k.kunnr
WHERE va.kunnr IS NOT NULL
GROUP BY va.kunnr, k.name1, va.auart
ORDER BY order_count DESC
LIMIT 20
""")

q("sales_orders_by_year",
  "Sales orders by year (VBAK)",
  ["sales orders by year","annual order count","VBAK by year","order trend by year"],
  ["sales","order","year","annual","vbak","trend","count"],
  ["VBAK"],
  f"""
SELECT SUBSTRING(va.audat, 1, 4) AS year,
       COUNT(DISTINCT va.vbeln) AS order_count
FROM VBAK va
WHERE va.audat IS NOT NULL AND va.audat != ''
GROUP BY year
ORDER BY year ASC
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 38: LSEG — Warehouse Transfer Orders
# ══════════════════════════════════════════════════════════════════════════════

q("warehouse_transfers_by_material",
  "Top 20 materials by warehouse transfer quantity (LSEG)",
  ["warehouse transfers by material","LSEG transfers","warehouse movements by material"],
  ["warehouse","transfer","material","lseg","lgnum","menge"],
  ["LSEG","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       ls.matnr AS material_number,
       ls.werks AS plant,
       SUM(ls.menge) AS transfer_quantity
FROM LSEG ls
LEFT JOIN MAKT m ON ls.matnr = m.matnr AND m.spras = 'E'
WHERE ls.matnr IS NOT NULL AND ls.menge IS NOT NULL
GROUP BY ls.matnr, m.maktx, ls.werks
HAVING SUM(ls.menge) > 0
ORDER BY transfer_quantity DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 39: KNVV — Customer Sales Data (payment terms, pricing)
# ══════════════════════════════════════════════════════════════════════════════

q("customer_payment_terms",
  "Customer payment terms distribution (KNVV)",
  ["customer payment terms","payment terms by customer","KNVV payment","zterm distribution"],
  ["payment","terms","customer","knvv","zterm"],
  ["KNVV","KNA1"],
  f"""
SELECT kv.zterm AS payment_terms,
       COUNT(DISTINCT kv.kunnr) AS customer_count
FROM KNVV kv
WHERE kv.zterm IS NOT NULL AND kv.zterm != ''
GROUP BY kv.zterm
ORDER BY customer_count DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 40: EBAN — Purchase Requisitions (by year, by status)
# ══════════════════════════════════════════════════════════════════════════════

q("purchase_req_by_year",
  "Purchase requisition count by year (EBAN)",
  ["purchase requisitions by year","PR count by year","EBAN by year","annual requisitions"],
  ["requisition","year","eban","annual","pr","count","banfn"],
  ["EBAN"],
  f"""
SELECT SUBSTRING(eb.erdat, 1, 4) AS year,
       COUNT(DISTINCT eb.banfn) AS requisition_count,
       SUM(eb.menge) AS total_quantity
FROM EBAN eb
WHERE eb.erdat IS NOT NULL AND eb.erdat != ''
GROUP BY year
ORDER BY year ASC
""")

q("purchase_req_open",
  "Open/pending purchase requisitions (EBAN statu not ordered)",
  ["open purchase requisitions","pending PRs","requisitions not yet ordered",
   "unprocessed purchase requests"],
  ["open","pending","requisition","pr","eban","statu","unprocessed"],
  ["EBAN","MAKT"],
  f"""
SELECT m.maktx AS material_name,
       eb.matnr AS material_number,
       COUNT(DISTINCT eb.banfn) AS open_req_count,
       SUM(eb.menge) AS total_quantity
FROM EBAN eb
LEFT JOIN MAKT m ON eb.matnr = m.matnr AND m.spras = 'E'
WHERE eb.statu NOT IN ('N', 'X') OR eb.statu IS NULL
  AND eb.matnr IS NOT NULL AND eb.matnr != ''
GROUP BY eb.matnr, m.maktx
ORDER BY open_req_count DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 41: BSEG — FI Document Line Items
# ══════════════════════════════════════════════════════════════════════════════

q("bseg_by_account",
  "FI document line items by GL account (BSEG top 20)",
  ["FI line items by account","BSEG by account","financial postings by GL account",
   "document items per GL account"],
  ["fi","line","item","bseg","account","saknr","posting","financial"],
  ["BSEG"],
  f"""
SELECT bs.saknr AS gl_account,
       bs.hkont AS hk_account,
       SUM(bs.dmbtr) AS total_local_amount,
       SUM(bs.wrbtr) AS total_transaction_amount,
       bs.waers AS currency,
       COUNT(*) AS line_count
FROM BSEG bs
WHERE bs.dmbtr IS NOT NULL AND bs.saknr IS NOT NULL
GROUP BY bs.saknr, bs.hkont, bs.waers
ORDER BY ABS(SUM(bs.dmbtr)) DESC
LIMIT 20
""")


# ══════════════════════════════════════════════════════════════════════════════
# Write the catalog
# ══════════════════════════════════════════════════════════════════════════════

def _fix_alias_mismatches(catalog: list) -> int:
    """Post-process: fix any remaining tablename.col refs where the table has an alias.
    PostgreSQL requires alias.col, not tablename.col, once an alias is defined."""
    import re
    SQL_KEYWORDS = {
        'ON','WHERE','SET','INNER','LEFT','RIGHT','CROSS','FULL','OUTER','JOIN',
        'GROUP','ORDER','HAVING','LIMIT','UNION','EXCEPT','INTERSECT','AS','BY',
        'SELECT','FROM','AND','OR','NOT','IS','IN','BETWEEN','LIKE','NULL',
    }
    fixed = 0
    for entry in catalog:
        sql = entry["sql"]
        alias_map = {}
        for m in re.finditer(r'\b(FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)', sql, re.IGNORECASE):
            tbl, alias = m.group(2), m.group(3)
            if alias.upper() not in SQL_KEYWORDS:
                alias_map[tbl.lower()] = alias
                alias_map[tbl.upper()] = alias
        if not alias_map:
            continue
        def replace_ref(match):
            tbl = match.group(1); col = match.group(2)
            a = alias_map.get(tbl) or alias_map.get(tbl.lower()) or alias_map.get(tbl.upper())
            return f"{a}.{col}" if a else match.group(0)
        new_sql = re.sub(r'\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_]\w*)\b', replace_ref, sql)
        if new_sql != sql:
            entry["sql"] = new_sql
            fixed += 1
    return fixed


if __name__ == "__main__":
    # Auto-fix any alias mismatches before writing
    n_fixed = _fix_alias_mismatches(entries)
    if n_fixed:
        print(f"⚠️  Auto-fixed alias mismatches in {n_fixed} entries")

    out = Path(__file__).parent / "app" / "sql_catalog.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    print(f"✅ Generated {len(entries)} catalog entries → {out}")
    print()
    for e in entries:
        print(f"  [{e['id']:50s}] {e['description']}")
