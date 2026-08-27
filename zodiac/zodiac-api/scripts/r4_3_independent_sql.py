"""Independent SQL validation for R4-3 inventory snapshot vs live AI answers."""
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
OUT = "r4_3_independent_sql.json"

SALK3 = "CAST(NULLIF(TRIM(CAST(b.\"salk3\" AS TEXT)), '') AS NUMERIC)"
LBKUM = "CAST(NULLIF(TRIM(CAST(b.\"lbkum\" AS TEXT)), '') AS NUMERIC)"
REV = "CAST(NULLIF(TRIM(CAST(v.\"netwr\" AS TEXT)), '') AS NUMERIC)"
QTY = "CAST(NULLIF(TRIM(CAST(v.\"fkimg\" AS TEXT)), '') AS NUMERIC)"

INV_TOP_SQL = f"""
SELECT
  TRIM(CAST(b."matnr" AS TEXT)) AS product,
  TRIM(CAST(b."bwkey" AS TEXT)) AS valuation_area,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(b."salk3", '0') AS TEXT)), '') AS NUMERIC)) AS stock_value,
  SUM(CAST(NULLIF(TRIM(CAST(COALESCE(b."lbkum", '0') AS TEXT)), '') AS NUMERIC)) AS stock_qty
FROM "MBEW" b
WHERE b."matnr" IS NOT NULL AND TRIM(CAST(b."matnr" AS TEXT)) <> ''
GROUP BY TRIM(CAST(b."matnr" AS TEXT)), TRIM(CAST(b."bwkey" AS TEXT))
ORDER BY stock_value DESC NULLS LAST
LIMIT 10
""".strip()

SALES_TOP_SQL = f"""
SELECT
  TRIM(CAST(v."matnr" AS TEXT)) AS product,
  SUM({REV}) AS revenue,
  SUM({QTY}) AS billed_qty
FROM "vbrp" v
JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
  AND {REV} IS NOT NULL
GROUP BY TRIM(CAST(v."matnr" AS TEXT))
ORDER BY revenue DESC NULLS LAST
LIMIT 10
""".strip()

COMPARE_SQL = f"""
WITH inventory_agg AS (
  SELECT
    TRIM(CAST(b."matnr" AS TEXT)) AS product,
    SUM({SALK3}) AS stock_value,
    SUM({LBKUM}) AS stock_qty
  FROM "MBEW" b
  WHERE b."matnr" IS NOT NULL AND TRIM(CAST(b."matnr" AS TEXT)) <> ''
  GROUP BY TRIM(CAST(b."matnr" AS TEXT))
),
sales_agg AS (
  SELECT
    TRIM(CAST(v."matnr" AS TEXT)) AS product,
    SUM({REV}) AS revenue,
    SUM({QTY}) AS billed_qty
  FROM "vbrp" v
  JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
  WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
    AND {REV} IS NOT NULL
  GROUP BY TRIM(CAST(v."matnr" AS TEXT))
)
SELECT
  COALESCE(i.product, s.product) AS product,
  i.stock_value,
  i.stock_qty,
  s.revenue,
  s.billed_qty
FROM inventory_agg i
FULL OUTER JOIN sales_agg s ON i.product = s.product
WHERE COALESCE(i.product, s.product) IS NOT NULL
ORDER BY COALESCE(i.stock_value, 0) DESC NULLS LAST
LIMIT 10
""".strip()

GROUP_SQL = f"""
WITH inventory_agg AS (
  SELECT
    COALESCE(NULLIF(TRIM(CAST(a."matkl" AS TEXT)), ''), 'Unknown') AS product_group,
    SUM({SALK3}) AS stock_value
  FROM "MBEW" b
  LEFT JOIN "MARA" a ON TRIM(CAST(b."matnr" AS TEXT)) = TRIM(CAST(a."matnr" AS TEXT))
  WHERE b."matnr" IS NOT NULL AND TRIM(CAST(b."matnr" AS TEXT)) <> ''
  GROUP BY 1
),
sales_agg AS (
  SELECT
    COALESCE(NULLIF(TRIM(CAST(a."matkl" AS TEXT)), ''), 'Unknown') AS product_group,
    SUM({REV}) AS revenue
  FROM "vbrp" v
  JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
  LEFT JOIN "MARA" a ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(a."matnr" AS TEXT))
  WHERE {REV} IS NOT NULL
  GROUP BY 1
)
SELECT
  COALESCE(i.product_group, s.product_group) AS product_group,
  i.stock_value,
  s.revenue
FROM inventory_agg i
FULL OUTER JOIN sales_agg s ON i.product_group = s.product_group
ORDER BY COALESCE(i.stock_value, 0) DESC NULLS LAST
LIMIT 10
""".strip()


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


def cmp_top(ai_rows, ind_rows, key: str, metric: str, tol_pct: float = 2.0):
    diffs = []
    for i, (a, b) in enumerate(zip(ai_rows[:5], ind_rows[:5])):
        ak = str(a.get(key) or "")
        bk = str(b.get(key) or "")
        try:
            av = float(a.get(metric) or 0)
        except (TypeError, ValueError):
            av = 0.0
        try:
            bv = float(b.get(metric) or 0)
        except (TypeError, ValueError):
            bv = 0.0
        denom = abs(bv) if bv else 1.0
        pct = abs(av - bv) / denom * 100.0
        diffs.append(
            {
                "rank": i + 1,
                "ai_key": ak,
                "ind_key": bk,
                "key_match": ak == bk,
                "metric": metric,
                "ai_value": av,
                "ind_value": bv,
                "diff": av - bv,
                "diff_pct": round(pct, 4),
                "ok": ak == bk and pct <= tol_pct,
            }
        )
    return diffs


def os_url() -> str:
    import os

    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
    if not url:
        raise SystemExit("BLOCKED: No DATABASE_URL in .env")
    return url


def run():
    url = os_url()
    eng = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 30},
        use_native_hstore=False,
    )
    cases_spec = [
        ("Show inventory.", INV_TOP_SQL, "product", "stock_value", "inventory value"),
        ("Which products have the highest inventory?", INV_TOP_SQL, "product", "stock_value", "inventory value"),
        ("Show inventory versus sales.", COMPARE_SQL, "product", "stock_value", "inventory vs sales"),
        ("Show inventory versus sales.", COMPARE_SQL, "product", "revenue", "sales revenue in comparison"),
        ("Show inventory by product group.", GROUP_SQL, "product_group", "stock_value", "product-group inventory"),
    ]
    cases = []
    with eng.connect() as conn:
        for q, sql, key, metric, note in cases_spec:
            ind = [dict(r) for r in conn.execute(text(sql)).mappings()]
            ai, ms = post(q)
            ai_rows = ai.get("data") or []
            # Snapshot SQL is MATNR+BWKEY; independent is MATNR. Compare first product's metric
            # after collapsing AI rows by product when needed.
            collapsed = []
            seen = set()
            for row in ai_rows:
                k = str(row.get(key) or "")
                if not k or k in seen:
                    continue
                seen.add(k)
                collapsed.append(row)
            diffs = cmp_top(collapsed, ind, key, metric)
            cases.append(
                {
                    "question": q,
                    "metric": metric,
                    "note": note,
                    "ms": ms,
                    "intent": ((ai.get("query_plan") or {}).get("analytical_context") or {}).get("intent"),
                    "ai_top": (collapsed[0] if collapsed else {}),
                    "ind_top": (ind[0] if ind else {}),
                    "diffs": diffs,
                    "mismatches": sum(1 for d in diffs if not d["ok"]),
                }
            )

    report = {
        "api": API,
        "period": "inventory=current snapshot; sales=all billed history in extract",
        "cases": cases,
        "total_mismatches": sum(c["mismatches"] for c in cases),
    }
    with open(ROOT / OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps({"total_mismatches": report["total_mismatches"], "cases": len(cases)}, indent=2))
    return report


if __name__ == "__main__":
    run()
