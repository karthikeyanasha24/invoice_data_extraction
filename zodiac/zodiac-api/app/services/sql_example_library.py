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
