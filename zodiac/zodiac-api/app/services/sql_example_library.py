"""
Static question→SQL examples derived from verified scripts.

Used as few-shot examples so the web app generates SQL similar to our
known-good scripts (lowest_sales_by_customer_country, compare_sales_vs_invoice,
run_cost_summary_example).
"""

from typing import Dict, List, Optional

# Verified SQL from scripts - concrete patterns for the LLM to follow.
# Use LIMIT 20; date filters are optional (agent adds when user specifies year).
SCRIPT_SQL_EXAMPLES: List[Dict[str, str]] = [
    {
        "user_query": "Show lowest sales by customer and country",
        "sql_query": '''
SELECT
    k."name1" AS customer_name,
    k."land1" AS country,
    vbrk."waerk" AS currency,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_sales,
    COUNT(DISTINCT vbrp."vbeln") AS doc_count
FROM "vbrp" AS vbrp
LEFT JOIN "VBRK" AS vbrk ON vbrp."vbeln" = vbrk."vbeln"
LEFT JOIN "KNA1" AS k ON vbrk."kunag" = k."kunnr"
WHERE vbrk."vbeln" IS NOT NULL
  AND k."kunnr" IS NOT NULL
  AND NULLIF(TRIM(vbrp."netwr"::text), '') IS NOT NULL
GROUP BY k."name1", k."land1", vbrk."waerk"
HAVING SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) > 0
ORDER BY total_sales ASC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Compare sales data with invoice data by currency",
        "sql_query": '''
SELECT
    vbrk."waerk" AS currency,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_sales,
    COUNT(DISTINCT vbrp."vbeln") AS doc_count
FROM "vbrp" AS vbrp
LEFT JOIN "VBRK" AS vbrk ON vbrp."vbeln" = vbrk."vbeln"
WHERE vbrk."vbeln" IS NOT NULL
GROUP BY vbrk."waerk"
ORDER BY total_sales DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Total vendor invoice amounts by vendor and currency",
        "sql_query": '''
SELECT
    lifnr AS vendor,
    waers AS currency,
    SUM(NULLIF(rmwwr, '')::numeric) AS total_invoice_amount,
    COUNT(*) AS invoice_count
FROM public."RBKP"
GROUP BY lifnr, waers
ORDER BY total_invoice_amount DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Total PO value by vendor and currency",
        "sql_query": '''
SELECT
    ekko.lifnr AS vendor,
    ekko.waers AS currency,
    SUM(ekpo.netwr::numeric) AS total_po_value
FROM public."EKKO" ekko
JOIN public."EKPO" ekpo ON ekko.ebeln = ekpo.ebeln
GROUP BY ekko.lifnr, ekko.waers
ORDER BY total_po_value DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Sales by country and industry",
        "sql_query": '''
SELECT
    k."land1" AS country,
    t."brtxt" AS industry_name,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_sales,
    COUNT(DISTINCT vbrk."kunag") AS customer_count
FROM "vbrp" vbrp
LEFT JOIN "VBRK" vbrk ON vbrp."vbeln" = vbrk."vbeln"
LEFT JOIN "KNA1" k ON vbrk."kunag" = k."kunnr"
LEFT JOIN "T016T" t ON k."brsch" = t."brsch"
WHERE vbrk."vbeln" IS NOT NULL AND k."kunnr" IS NOT NULL
  AND NULLIF(TRIM(vbrp."netwr"::text), '') IS NOT NULL
GROUP BY k."land1", t."brtxt"
ORDER BY total_sales DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Which industry has highest revenues",
        "sql_query": '''
SELECT
    t."brtxt" AS industry_name,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_revenue,
    COUNT(DISTINCT vbrk."kunag") AS customer_count
FROM "vbrp" vbrp
LEFT JOIN "VBRK" vbrk ON vbrp."vbeln" = vbrk."vbeln"
LEFT JOIN "KNA1" k ON vbrk."kunag" = k."kunnr"
LEFT JOIN "T016T" t ON k."brsch" = t."brsch"
WHERE vbrk."vbeln" IS NOT NULL AND k."kunnr" IS NOT NULL
  AND NULLIF(TRIM(vbrp."netwr"::text), '') IS NOT NULL
GROUP BY t."brtxt"
ORDER BY total_revenue DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Top 10 customers by revenue",
        "sql_query": '''
SELECT
    k."name1" AS customer_name,
    k."land1" AS country,
    vbrk."waerk" AS currency,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_revenue
FROM "vbrp" vbrp
LEFT JOIN "VBRK" vbrk ON vbrp."vbeln" = vbrk."vbeln"
LEFT JOIN "KNA1" k ON vbrk."kunag" = k."kunnr"
WHERE vbrk."vbeln" IS NOT NULL AND k."kunnr" IS NOT NULL
  AND NULLIF(TRIM(vbrp."netwr"::text), '') IS NOT NULL
GROUP BY k."name1", k."land1", vbrk."waerk"
ORDER BY total_revenue DESC
LIMIT 10
'''.strip(),
    },
    {
        "user_query": "Highest sales by customer and product and country",
        "sql_query": '''
SELECT
    k."name1" AS customer_name,
    COALESCE(m."maktx", vbrp."matnr") AS product_name,
    k."land1" AS country,
    vbrk."waerk" AS currency,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_sales
FROM "vbrp" vbrp
LEFT JOIN "VBRK" vbrk ON vbrp."vbeln" = vbrk."vbeln"
LEFT JOIN "KNA1" k ON vbrk."kunag" = k."kunnr"
LEFT JOIN "MAKT" m ON vbrp."matnr" = m."matnr"
WHERE vbrk."vbeln" IS NOT NULL AND k."kunnr" IS NOT NULL
  AND NULLIF(TRIM(vbrp."netwr"::text), '') IS NOT NULL
GROUP BY k."name1", COALESCE(m."maktx", vbrp."matnr"), k."land1", vbrk."waerk"
ORDER BY total_sales DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Highest sales by product",
        "sql_query": '''
SELECT
    COALESCE(m."maktx", vbrp."matnr") AS product_name,
    vbrk."waerk" AS currency,
    SUM(NULLIF(TRIM(vbrp."netwr"::text), '')::numeric) AS total_sales
FROM "vbrp" vbrp
LEFT JOIN "VBRK" vbrk ON vbrp."vbeln" = vbrk."vbeln"
LEFT JOIN "MAKT" m ON vbrp."matnr" = m."matnr"
WHERE vbrk."vbeln" IS NOT NULL AND NULLIF(TRIM(vbrp."netwr"::text), '') IS NOT NULL
GROUP BY COALESCE(m."maktx", vbrp."matnr"), vbrk."waerk"
ORDER BY total_sales DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Top products by quantity sold",
        "sql_query": '''
SELECT
    COALESCE(m."maktx", vbrp."matnr") AS product_name,
    SUM(NULLIF(TRIM(vbrp."smeng"::text), '')::numeric) AS total_quantity_sold
FROM "vbrp" vbrp
LEFT JOIN "MAKT" m ON vbrp."matnr" = m."matnr"
WHERE NULLIF(TRIM(vbrp."smeng"::text), '') IS NOT NULL
GROUP BY COALESCE(m."maktx", vbrp."matnr")
HAVING SUM(NULLIF(TRIM(vbrp."smeng"::text), '')::numeric) > 0
ORDER BY total_quantity_sold DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Deliveries by customer",
        "sql_query": '''
SELECT
    k."kunnr" AS customer_number,
    k."name1" AS customer_name,
    SUM(NULLIF(TRIM(l."lfimg"::text), '')::numeric) AS total_quantity
FROM "LIKP" l1
LEFT JOIN "LIPS" l ON l1."vbeln" = l."vbeln"
LEFT JOIN "KNA1" k ON l1."kunnr" = k."kunnr"
WHERE l1."vbeln" IS NOT NULL
  AND k."kunnr" IS NOT NULL
  AND NULLIF(TRIM(l."lfimg"::text), '') IS NOT NULL
GROUP BY k."kunnr", k."name1"
HAVING SUM(NULLIF(TRIM(l."lfimg"::text), '')::numeric) > 0
ORDER BY total_quantity DESC
LIMIT 20
'''.strip(),
    },
    {
        "user_query": "Actual costs by cost center and cost element for 2024",
        "sql_query": '''
SELECT
    c."kostl" AS cost_center,
    c."kstar" AS cost_element,
    SUM(NULLIF(TRIM(c."wtgbtr"::text), '')::numeric) AS total_amount
FROM "COEP" c
WHERE c."gjahr" = '2024'
  AND NULLIF(TRIM(c."wtgbtr"::text), '') IS NOT NULL
GROUP BY c."kostl", c."kstar"
ORDER BY total_amount DESC
LIMIT 50
'''.strip(),
    },
    {
        "user_query": "GL balances by account and period",
        "sql_query": '''
SELECT
    f."racct" AS gl_account,
    f."ryear" AS fiscal_year,
    f."poper" AS period,
    SUM(NULLIF(TRIM(f."hsl"::text), '')::numeric) AS total_balance
FROM "FAGLFLEXA" f
WHERE NULLIF(TRIM(f."hsl"::text), '') IS NOT NULL
GROUP BY f."racct", f."ryear", f."poper"
ORDER BY f."ryear" DESC, f."poper" DESC, total_balance DESC
LIMIT 100
'''.strip(),
    },
    {
        "user_query": "PO totals by vendor, currency and year",
        "sql_query": '''
SELECT
    e."lifnr" AS vendor,
    e."waers" AS currency,
    EXTRACT(YEAR FROM e."bedat")::int AS year,
    SUM(NULLIF(TRIM(p."netwr"::text), '')::numeric) AS total_po_value
FROM "EKKO" e
JOIN "EKPO" p ON e."ebeln" = p."ebeln"
WHERE NULLIF(TRIM(p."netwr"::text), '') IS NOT NULL
GROUP BY e."lifnr", e."waers", EXTRACT(YEAR FROM e."bedat")
ORDER BY year DESC, total_po_value DESC
LIMIT 100
'''.strip(),
    },
    {
        "user_query": "Vendor invoices total amount by vendor and currency",
        "sql_query": '''
SELECT
    r."lifnr" AS vendor,
    r."waers" AS currency,
    SUM(NULLIF(TRIM(r."rmwwr"::text), '')::numeric) AS total_invoice_amount
FROM "RBKP" r
WHERE NULLIF(TRIM(r."rmwwr"::text), '') IS NOT NULL
GROUP BY r."lifnr", r."waers"
ORDER BY total_invoice_amount DESC
LIMIT 100
'''.strip(),
    },
    {
        "user_query": "Purchase requisitions by plant, material group and status",
        "sql_query": '''
SELECT
    e."werks" AS plant,
    e."matkl" AS material_group,
    e."bsart" AS doc_type,
    COUNT(*) AS requisition_count,
    SUM(NULLIF(TRIM(e."menge"::text), '')::numeric) AS total_quantity
FROM "EBAN" e
GROUP BY e."werks", e."matkl", e."bsart"
ORDER BY requisition_count DESC
LIMIT 100
'''.strip(),
    },
    {
        "user_query": "Customer payments by customer and period",
        "sql_query": '''
SELECT
    k."name1" AS customer_name,
    b."kunnr" AS customer_number,
    b."gjahr" AS fiscal_year,
    b."monat" AS period,
    SUM(NULLIF(TRIM(b."dmbtr"::text), '')::numeric) AS total_amount
FROM "BSAD" b
LEFT JOIN "KNA1" k ON b."kunnr" = k."kunnr"
WHERE NULLIF(TRIM(b."dmbtr"::text), '') IS NOT NULL
GROUP BY k."name1", b."kunnr", b."gjahr", b."monat"
ORDER BY b."gjahr" DESC, b."monat" DESC, total_amount DESC
LIMIT 100
'''.strip(),
    },
    {
        "user_query": "Sales orders by customer, status and order date",
        "sql_query": '''
SELECT
    k."name1" AS customer_name,
    v."vbeln" AS sales_order,
    v."audat" AS order_date,
    v."vbtyp" AS doc_type,
    v."faksk" AS billing_block,
    v."lifsk" AS delivery_block,
    v."netwr" AS order_value
FROM "VBAK" v
LEFT JOIN "KNA1" k ON v."kunnr" = k."kunnr"
ORDER BY v."audat" DESC, v."vbeln" DESC
LIMIT 200
'''.strip(),
    },
    {
        "user_query": "Outbound delivery quantities by product",
        "sql_query": '''
SELECT
    COALESCE(m."maktx", l."matnr") AS product_name,
    SUM(NULLIF(TRIM(l."lfimg"::text), '')::numeric) AS total_quantity
FROM "LIPS" l
LEFT JOIN "MAKT" m ON l."matnr" = m."matnr"
WHERE NULLIF(TRIM(l."lfimg"::text), '') IS NOT NULL
GROUP BY COALESCE(m."maktx", l."matnr")
ORDER BY total_quantity DESC
LIMIT 100
'''.strip(),
    },
    # ── Invoice + payer name + industry (the classic invoice-bot pattern) ──
    {
        "user_query": "Show invoices with payer names by industry",
        "sql_query": '''
SELECT
    v."vbeln" AS invoice_number,
    v."fkdat" AS billing_date,
    v."kunag" AS customer_number,
    k."name1" AS payer_name,
    COALESCE(t."brtxt", k."brsch") AS industry,
    k."land1" AS country,
    NULLIF(TRIM(v."netwr"::text), '')::numeric AS invoice_amount,
    v."waerk" AS currency
FROM "VBRK" AS v
LEFT JOIN "KNA1" AS k ON v."kunag" = k."kunnr"
LEFT JOIN "T016T" AS t ON k."brsch" = t."brsch"
WHERE v."fkdat" IS NOT NULL
ORDER BY industry ASC, v."fkdat" DESC
LIMIT 200
'''.strip(),
    },
    # ── Invoice list with customer names ──────────────────────────────────
    {
        "user_query": "List all invoices with customer names",
        "sql_query": '''
SELECT
    v."vbeln" AS invoice_number,
    v."fkdat" AS billing_date,
    v."kunag" AS customer_number,
    k."name1" AS customer_name,
    k."land1" AS country,
    NULLIF(TRIM(v."netwr"::text), '')::numeric AS invoice_amount,
    v."waerk" AS currency
FROM "VBRK" AS v
LEFT JOIN "KNA1" AS k ON v."kunag" = k."kunnr"
WHERE v."fkdat" IS NOT NULL
ORDER BY v."fkdat" DESC
LIMIT 200
'''.strip(),
    },
    # ── Sales (billing line items) with product names ─────────────────────
    {
        "user_query": "Show billing line items with product names and amounts",
        "sql_query": '''
SELECT
    vk."vbeln" AS invoice_number,
    vk."fkdat" AS billing_date,
    v."posnr" AS item_number,
    COALESCE(m."maktx", v."matnr") AS product_name,
    NULLIF(TRIM(v."fkimg"::text), '')::numeric AS quantity,
    v."vrkme" AS unit,
    NULLIF(TRIM(v."netwr"::text), '')::numeric AS line_amount,
    vk."waerk" AS currency
FROM "vbrp" AS v
JOIN "VBRK" AS vk ON v."vbeln" = vk."vbeln"
LEFT JOIN "MAKT" AS m ON v."matnr" = m."matnr" AND m."spras" = \'E\'
WHERE vk."fkdat" IS NOT NULL
ORDER BY vk."fkdat" DESC
LIMIT 200
'''.strip(),
    },
    # ── FAGLFLEXA: Total cost by profit center ────────────────────────────
    {
        "user_query": "Total cost by profit center from FAGLFLEXA",
        "sql_query": '''
SELECT
    fg."prctr" AS profit_center,
    COALESCE(c."name1", fg."prctr") AS profit_center_name,
    SUM(fg."hsl") AS total_cost,
    fg."rtcur" AS currency
FROM "FAGLFLEXA" AS fg
LEFT JOIN "CEPC" AS c ON fg."prctr" = c."prctr"
WHERE fg."prctr" IS NOT NULL AND TRIM(fg."prctr") != ''
GROUP BY fg."prctr", c."name1", fg."rtcur"
ORDER BY total_cost DESC NULLS LAST
LIMIT 100
'''.strip(),
    },
    # ── FAGLFLEXA: Link profit center costs to customers and products ───────
    {
        "user_query": "Link FAGLFLEXA profit center costs back to major customers and products where possible",
        "sql_query": '''
SELECT
    v."prctr" AS profit_center,
    COALESCE(epc."name1", v."prctr") AS profit_center_name,
    c."name1" AS customer_name,
    vk."kunag" AS customer_number,
    COALESCE(m."maktx", v."matnr") AS product_name,
    v."matnr" AS material_number,
    f.total_cost AS profit_center_total_cost,
    SUM(CAST(NULLIF(TRIM(v."netwr"), '') AS NUMERIC)) AS revenue
FROM "vbrp" AS v
JOIN "VBRK" AS vk ON TRIM(v."vbeln") = TRIM(vk."vbeln")
LEFT JOIN "KNA1" AS c ON vk."kunag" = c."kunnr"
LEFT JOIN "MAKT" AS m ON v."matnr" = m."matnr" AND (m."spras" = 'E' OR m."spras" IS NULL)
LEFT JOIN "CEPC" AS epc ON v."prctr" = epc."prctr"
LEFT JOIN (
    SELECT "prctr", SUM("hsl") AS total_cost
    FROM "FAGLFLEXA"
    WHERE "prctr" IS NOT NULL AND TRIM("prctr") != ''
    GROUP BY "prctr"
) f ON v."prctr" = f."prctr"
WHERE v."prctr" IS NOT NULL AND TRIM(v."prctr") != ''
  AND CAST(NULLIF(TRIM(v."netwr"), '') AS NUMERIC) IS NOT NULL
GROUP BY v."prctr", epc."name1", vk."kunag", c."name1", v."matnr", m."maktx", f.total_cost
ORDER BY revenue DESC NULLS LAST
LIMIT 100
'''.strip(),
    },
    # ── Complaints by customer (VBRP.compreas) ─────────────────────────────
    {
        "user_query": "Complaints by customer",
        "sql_query": '''
SELECT vk.kunag AS customer_number, COALESCE(k.name1, '') AS customer_name, COUNT(*) AS complaint_count, STRING_AGG(DISTINCT TRIM(v.compreas), ', ') AS complaint_reasons FROM vbrp v JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln) LEFT JOIN kna1 k ON TRIM(vk.kunag) = TRIM(k.kunnr) WHERE v.compreas IS NOT NULL AND TRIM(COALESCE(v.compreas, '')) != '' GROUP BY vk.kunag, k.name1 ORDER BY complaint_count DESC LIMIT 100
'''.strip(),
    },
    # ── Complaints by reason (VBRP.compreas) ───────────────────────────────
    {
        "user_query": "Complaints by reason",
        "sql_query": '''
SELECT TRIM(v.compreas) AS complaint_reason, COUNT(*) AS complaint_count, COUNT(DISTINCT vk.kunag) AS customer_count FROM vbrp v JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln) WHERE v.compreas IS NOT NULL AND TRIM(COALESCE(v.compreas, '')) != '' GROUP BY TRIM(v.compreas) ORDER BY complaint_count DESC LIMIT 100
'''.strip(),
    },
    # ── Open/unfulfilled reservations by material (RESB bdmng - enmng) ────
    {
        "user_query": "Open reservations by material",
        "sql_query": '''
SELECT m.maktx AS material_name, rs.matnr AS material_number, rs.werks AS plant, SUM(CAST(COALESCE(rs.bdmng, 0) AS NUMERIC) - CAST(COALESCE(rs.enmng, 0) AS NUMERIC)) AS open_reserved_qty, rs.meins AS unit FROM RESB rs LEFT JOIN MAKT m ON TRIM(rs.matnr) = TRIM(m.matnr) AND (m.spras = 'E' OR m.spras IS NULL) WHERE rs.matnr IS NOT NULL AND TRIM(rs.matnr) != '' GROUP BY rs.matnr, m.maktx, rs.werks, rs.meins HAVING SUM(CAST(COALESCE(rs.bdmng, 0) AS NUMERIC) - CAST(COALESCE(rs.enmng, 0) AS NUMERIC)) > 0 ORDER BY open_reserved_qty DESC LIMIT 100
'''.strip(),
    },
    # ── Reservations by material (RESB) ────────────────────────────────────
    {
        "user_query": "Materials with highest total quantity reserved in RESB",
        "sql_query": '''
SELECT m.maktx AS material_name, rs.matnr AS material_number, SUM(rs.bdmng) AS reserved_quantity, SUM(rs.enmng) AS issued_quantity FROM RESB rs LEFT JOIN MAKT m ON rs.matnr = m.matnr AND m.spras = 'E' WHERE rs.matnr IS NOT NULL AND rs.matnr != '' GROUP BY rs.matnr, m.maktx HAVING SUM(rs.bdmng) > 0 ORDER BY reserved_quantity DESC LIMIT 20
'''.strip(),
    },
    # ── Recent invoices list ──────────────────────────────────────────────
    {
        "user_query": "Show recent invoices",
        "sql_query": '''
SELECT vk.vbeln AS invoice_number, vk.fkdat AS billing_date, vk.kunag AS customer_number, CAST(NULLIF(TRIM(vk.netwr), '') AS NUMERIC) AS invoice_amount, vk.waerk AS currency, vk.vkorg AS sales_org, vk.fkart AS invoice_type FROM VBRK vk WHERE vk.fkdat IS NOT NULL ORDER BY vk.fkdat DESC LIMIT 200
'''.strip(),
    },
    # ── Profit margin by product (VBRP + CKIS) ──────────────────────────────
    {
        "user_query": "What was the profit margin on certain products?",
        "sql_query": '''
SELECT v.matnr, COALESCE(m.maktx, v.matnr) AS material_name, SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) AS revenue, COALESCE(c.total_cost, 0) AS cost, SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) - COALESCE(c.total_cost, 0) AS margin, CASE WHEN SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) > 0 THEN ROUND(100.0 * (SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)) - COALESCE(c.total_cost, 0)) / SUM(CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC)), 2) ELSE NULL END AS margin_pct FROM vbrp v LEFT JOIN VBRK vk ON TRIM(v.vbeln) = TRIM(vk.vbeln) LEFT JOIN MAKT m ON v.matnr = m.matnr AND (m.spras = 'E' OR m.spras IS NULL) LEFT JOIN (SELECT matnr, SUM(CAST(COALESCE(wertn, 0) AS NUMERIC)) AS total_cost FROM CKIS GROUP BY matnr) c ON v.matnr = c.matnr WHERE CAST(NULLIF(TRIM(v.netwr), '') AS NUMERIC) IS NOT NULL GROUP BY v.matnr, m.maktx, c.total_cost ORDER BY margin DESC NULLS LAST LIMIT 100
'''.strip(),
    },
    # ── Costs of manufacturing (CKIS) ───────────────────────────────────────
    {
        "user_query": "Costs of manufacturing",
        "sql_query": '''
SELECT m.maktx AS material_name, ci.matnr AS material_number, SUM(ci.wertn) AS total_cost_value, ci.hwaer AS currency FROM CKIS ci LEFT JOIN MAKT m ON ci.matnr = m.matnr AND m.spras = 'E' WHERE ci.matnr IS NOT NULL AND ci.wertn IS NOT NULL GROUP BY ci.matnr, m.maktx, ci.hwaer HAVING SUM(ci.wertn) > 0 ORDER BY total_cost_value DESC LIMIT 20
'''.strip(),
    },
    # ── Negative / lowest sales LINE ITEMS for a year (not year totals) ─────
    {
        "user_query": "Show sales by negative or lowest for year 2000",
        "sql_query": '''
SELECT
    v."vbeln" AS billing_doc,
    v."posnr" AS line_pos,
    r."fkdat" AS billing_date,
    r."kunag" AS sold_to_party,
    NULLIF(TRIM(v."netwr"::text), '')::numeric AS netwr_line_amount,
    r."waerk" AS currency
FROM vbrp v
JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"), 10, '0') = LPAD(TRIM(r."vbeln"), 10, '0')
WHERE SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000'
ORDER BY NULLIF(TRIM(v."netwr"::text), '')::numeric ASC NULLS LAST
LIMIT 100
'''.strip(),
    },
    {
        "user_query": "Lowest years by sales",
        "sql_query": '''
SELECT
    SUBSTRING(TRIM(r."fkdat"), 1, 4) AS year,
    SUM(NULLIF(TRIM(v."netwr"::text), '')::numeric) AS sales,
    COUNT(*) AS records,
    COUNT(DISTINCT r."vbeln") AS invoice_count
FROM vbrp v
JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"), 10, '0') = LPAD(TRIM(r."vbeln"), 10, '0')
WHERE LENGTH(TRIM(COALESCE(r."fkdat", ''))) >= 4
GROUP BY SUBSTRING(TRIM(r."fkdat"), 1, 4)
HAVING SUM(NULLIF(TRIM(v."netwr"::text), '')::numeric) IS NOT NULL
ORDER BY sales ASC NULLS LAST
LIMIT 20
'''.strip(),
    },
]


def get_sql_examples_for_question(
    question: str,
    max_examples: int = 3,
    additional_examples: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """
    Return relevant few-shot examples for the given question.

    Matches by keyword overlap. Always includes at least one script example.
    Merges with additional_examples (e.g. from training_data_collector).

    Args:
        question: User's natural language question.
        max_examples: Maximum total examples to return.
        additional_examples: Extra examples from DB (e.g. high-rated past queries).

    Returns:
        List of {"user_query": str, "sql_query": str} for few-shot prompting.
    """
    q_lower = (question or "").lower()
    scored: List[tuple[float, Dict[str, str]]] = []

    keywords_map = [
        (["lowest", "bottom", "minimum", "customer", "country"], 0),
        (["compare", "sales", "invoice", "difference", "currency"], 1),
        (["vendor", "invoice", "rbkp", "supplier"], 2),
        (["po", "purchase", "cost", "ekko", "ekpo"], 3),
        (["sales", "country", "industry"], 4),
        (["industry", "highest", "revenue", "revenues"], 5),
        (["top", "10", "customers", "revenue", "customer"], 6),
        (["highest", "sales", "customer", "product", "country"], 7),
        (["highest", "sales", "product", "product sales"], 8),
        (["top", "products", "quantity", "sold"], 9),
        (["deliveries", "delivery", "customer"], 10),
        (["actual", "costs", "cost center", "cost element"], 11),
        (["gl balances", "gl account", "period"], 12),
        (["po totals", "vendor", "currency", "year"], 13),
        (["vendor invoices", "total amount", "rbkp"], 14),
        (["purchase requisitions", "eban", "plant", "material group", "status"], 15),
        (["customer payments", "bsad", "cleared items"], 16),
        (["sales orders", "vbak", "order date", "status"], 17),
        (["outbound delivery quantities", "lips", "product"], 18),
        # Invoice + payer name + industry (the core invoice-bot pattern)
        (["invoices", "payer", "industry", "payers", "billing documents"], 19),
        # Invoice list with customer names
        (["invoices", "customer name", "list invoices", "show invoices", "billing"], 20),
        # Billing line items with product names
        (["billing", "line items", "product names", "billing items", "vbrp", "line amount"], 21),
        # FAGLFLEXA profit center costs
        (["faglflexa", "profit center", "cost", "total cost by profit center"], 22),
        # Link FAGLFLEXA to customers/products
        (["link", "faglflexa", "profit center", "costs", "customers", "products", "back to", "major", "where possible"], 23),
        # Complaints by customer
        (["complaint", "complaints", "client", "customer", "compreas", "claim"], 24),
        # Complaints by reason
        (["complaint", "complaints", "reason", "reasons", "breakdown", "compreas"], 25),
        # Open/unfulfilled reservations by material
        (["open", "unfulfilled", "pending", "reservation", "reserved", "material", "resb", "bdmng", "enmng"], 26),
        # Reservations by material (total reserved)
        (["reservation", "reserved", "material", "quantity", "resb", "bdmng", "highest reserved"], 27),
        # Recent invoices list
        (["recent invoices", "list invoices", "all invoices", "billing documents", "latest invoices"], 28),
        # Profit margin by product
        (["profit margin", "margin", "profitability", "revenue vs cost", "certain products", "margin by product"], 29),
        # Costs of manufacturing
        (["costs of manufacturing", "manufacturing cost", "cost of manufacturing", "ckis", "production cost"], 30),
        # Negative / lowest billing lines for a year (credit memos = negative NETWR)
        (["negative", "lowest", "sales", "year", "credit", "line", "billing"], 31),
        # Calendar years with lowest total sales (FKDAT)
        (["lowest years", "years", "sales", "weakest", "smallest sales by year"], 32),
    ]

    for kw, idx in keywords_map:
        if idx >= len(SCRIPT_SQL_EXAMPLES):
            continue
        score = sum(1 for k in kw if k in q_lower)
        if score > 0:
            scored.append((score, SCRIPT_SQL_EXAMPLES[idx]))

    scored.sort(key=lambda x: -x[0])
    selected = [ex for _, ex in scored[:max_examples]]

    if not selected:
        selected = [SCRIPT_SQL_EXAMPLES[0]]

    if additional_examples:
        remaining = max_examples - len(selected)
        for ex in additional_examples[:remaining]:
            uq = ex.get("user_query") or ""
            sql = ex.get("sql_query") or ""
            if uq and sql:
                selected.append({"user_query": uq, "sql_query": sql})

    return selected[:max_examples]
