"""Independent SQL validation for R4-2 product growth vs live AI answers."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

API = "https://zodiac-back.vercel.app/api/query/adaptive"
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
OUT = "r4_2_independent_sql.json"

YEAR = 'SUBSTRING(TRIM(CAST(vk."fkdat" AS TEXT)), 1, 4)'
REV = "CAST(NULLIF(TRIM(CAST(v.\"netwr\" AS TEXT)), '') AS NUMERIC)"
COGS = "CAST(NULLIF(TRIM(CAST(COALESCE(v.\"wavwr\", '0') AS TEXT)), '') AS NUMERIC)"
QTY = "CAST(NULLIF(TRIM(CAST(v.\"fkimg\" AS TEXT)), '') AS NUMERIC)"


GROWTH_SQL_TMPL = """
WITH yearly AS (
  SELECT
    {year} AS year,
    TRIM(CAST(v."matnr" AS TEXT)) AS product,
    COALESCE(MAX(m."maktx"), TRIM(CAST(v."matnr" AS TEXT))) AS product_name,
    vk."waerk" AS currency,
    SUM({rev}) AS revenue,
    SUM({cogs}) AS cogs,
    SUM({rev}) - SUM({cogs}) AS gross_profit,
    CASE WHEN SUM({rev}) > 0 THEN
      ROUND(100.0 * (SUM({rev}) - SUM({cogs})) / SUM({rev}), 2)
    ELSE NULL END AS gross_margin_pct,
    SUM({qty}) AS quantity,
    CASE WHEN SUM({qty}) > 0 THEN ROUND(SUM({rev}) / SUM({qty}), 4) ELSE NULL END AS avg_selling_price
  FROM "vbrp" v
  JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
  LEFT JOIN "MAKT" m ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
    AND (m."spras" = 'E' OR m."spras" IS NULL)
  WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
    AND {rev} IS NOT NULL
    AND {year} IN ('2004', '2005')
  GROUP BY {year}, TRIM(CAST(v."matnr" AS TEXT)), vk."waerk"
),
prev AS (SELECT * FROM yearly WHERE year = '2004'),
curr AS (SELECT * FROM yearly WHERE year = '2005')
SELECT
  COALESCE(a.product, b.product) AS product,
  COALESCE(a.product_name, b.product_name) AS product_name,
  COALESCE(a.currency, b.currency) AS currency,
  COALESCE(a.revenue, 0) AS revenue_prev,
  COALESCE(b.revenue, 0) AS revenue_curr,
  (COALESCE(b.revenue, 0) - COALESCE(a.revenue, 0)) AS revenue_change_abs,
  CASE WHEN COALESCE(a.revenue, 0) = 0 THEN NULL
       ELSE ROUND(100.0 * (COALESCE(b.revenue, 0) - COALESCE(a.revenue, 0)) / a.revenue, 2) END
    AS revenue_change_pct,
  COALESCE(a.gross_profit, 0) AS gross_profit_prev,
  COALESCE(b.gross_profit, 0) AS gross_profit_curr,
  (COALESCE(b.gross_profit, 0) - COALESCE(a.gross_profit, 0)) AS gross_profit_change_abs,
  (COALESCE(b.gross_margin_pct, 0) - COALESCE(a.gross_margin_pct, 0)) AS margin_change_pp,
  COALESCE(a.avg_selling_price, 0) AS asp_prev,
  COALESCE(b.avg_selling_price, 0) AS asp_curr
FROM prev a
FULL OUTER JOIN curr b
  ON a.product = b.product AND a.currency = b.currency
WHERE COALESCE(a.product, b.product) IS NOT NULL
ORDER BY {order_expr}
LIMIT 10
""".strip()


def growth_sql(order_expr: str) -> str:
    return GROWTH_SQL_TMPL.format(
        year=YEAR,
        rev=REV,
        cogs=COGS,
        qty=QTY,
        order_expr=order_expr,
    )


def post(q: str):
    req = urllib.request.Request(
        API,
        data=json.dumps({"question": q}).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.load(r)
    return out, int((time.perf_counter() - t0) * 1000)


def cmp_top(ai_rows, ind_rows, metric: str, tol_pct: float = 1.0):
    diffs = []
    for i, (a, b) in enumerate(zip(ai_rows[:5], ind_rows[:5])):
        ap = str(a.get("product") or "")
        bp = str(b.get("product") or "")
        av = float(a.get(metric) or 0)
        bv = float(b.get(metric) or 0)
        denom = abs(bv) if bv else 1.0
        pct = abs(av - bv) / denom * 100.0
        diffs.append(
            {
                "rank": i + 1,
                "ai_product": ap,
                "ind_product": bp,
                "product_match": ap == bp,
                "ai_value": av,
                "ind_value": bv,
                "diff": av - bv,
                "diff_pct": round(pct, 4),
                "ok": ap == bp and pct <= tol_pct,
            }
        )
    return diffs


def run():
    url = os_url()
    eng = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 30},
        use_native_hstore=False,
    )

    cases_spec = [
        (
            "Which products grew the most?",
            "revenue_change_abs",
            "absolute revenue",
            "revenue_change_abs DESC NULLS LAST",
        ),
        (
            "Which products increased their revenue the most?",
            "revenue_change_abs",
            "absolute revenue",
            "revenue_change_abs DESC NULLS LAST",
        ),
        (
            "Which products grew the fastest?",
            "revenue_change_pct",
            "pct revenue",
            "revenue_change_pct DESC NULLS LAST",
        ),
        (
            "Which products declined the most?",
            "revenue_change_abs",
            "decline abs",
            "revenue_change_abs ASC NULLS LAST",
        ),
        (
            "Which products had the highest gross profit growth?",
            "gross_profit_change_abs",
            "gp abs",
            "gross_profit_change_abs DESC NULLS LAST",
        ),
        (
            "Show products whose margins improved.",
            "margin_change_pp",
            "margin pp",
            "margin_change_pp DESC NULLS LAST",
        ),
    ]

    cases = []
    with eng.connect() as conn:
        for q, metric, mode_note, order_expr in cases_spec:
            ind = [dict(r) for r in conn.execute(text(growth_sql(order_expr))).mappings()]
            ai, ms = post(q)
            ai_rows = ai.get("data") or []
            diffs = cmp_top(ai_rows, ind, metric)
            cases.append(
                {
                    "question": q,
                    "metric": metric,
                    "mode": mode_note,
                    "order": order_expr,
                    "ms": ms,
                    "intent": ((ai.get("query_plan") or {}).get("analytical_context") or {}).get(
                        "intent"
                    ),
                    "ai_top": (ai_rows[0] if ai_rows else {}),
                    "ind_top": (ind[0] if ind else {}),
                    "diffs": diffs,
                    "mismatches": sum(1 for d in diffs if not d["ok"]),
                }
            )

    report = {
        "api": API,
        "independent_sql_head": " ".join(growth_sql("revenue_change_abs DESC NULLS LAST").split())[
            :400
        ],
        "cases": cases,
        "total_mismatches": sum(c["mismatches"] for c in cases),
    }
    with open(ROOT / OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps({"total_mismatches": report["total_mismatches"], "cases": len(cases)}, indent=2))
    return report


def os_url() -> str:
    import os

    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
    if not url:
        raise SystemExit("No DATABASE_URL in .env")
    return url


if __name__ == "__main__":
    run()
