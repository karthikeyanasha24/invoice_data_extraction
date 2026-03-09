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
        (["po", "purchase", "cost", "vendor", "ekko", "ekpo"], 3),
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
