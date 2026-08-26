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


GROWTH_SQL = f"""
WITH yearly AS (
  SELECT
    {YEAR} AS year,
    TRIM(CAST(v."matnr" AS TEXT)) AS product,
    COALESCE(MAX(m."maktx"), TRIM(CAST(v."matnr" AS TEXT))) AS product_name,
    vk."waerk" AS currency,
    SUM({REV}) AS revenue,
    SUM({COGS}) AS cogs,
    SUM({REV}) - SUM({COGS}) AS gross_profit,
    CASE WHEN SUM({REV}) > 0 THEN
      ROUND(100.0 * (SUM({REV}) - SUM({COGS})) / SUM({REV}), 2)
    ELSE NULL END AS gross_margin_pct,
    SUM({QTY}) AS quantity,
    CASE WHEN SUM({QTY}) > 0 THEN ROUND(SUM({REV}) / SUM({QTY}), 4) ELSE NULL END AS avg_selling_price
  FROM "vbrp" v
  JOIN "VBRK" vk ON TRIM(CAST(v."vbeln" AS TEXT)) = TRIM(CAST(vk."vbeln" AS TEXT))
  LEFT JOIN "MAKT" m ON TRIM(CAST(v."matnr" AS TEXT)) = TRIM(CAST(m."matnr" AS TEXT))
    AND (m."spras" = 'E' OR m."spras" IS NULL)
  WHERE v."matnr" IS NOT NULL AND TRIM(CAST(v."matnr" AS TEXT)) <> ''
    AND {REV} IS NOT NULL
    AND {YEAR} IN ('2004', '2005')
  GROUP BY {YEAR}, TRIM(CAST(v."matnr" AS TEXT)), vk."waerk"
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
ORDER BY revenue_change_abs DESC NULLS LAST
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
    eng = create_engine(url)
    with eng.connect() as conn:
        ind = [dict(r) for r in conn.execute(text(GROWTH_SQL)).mappings()]

    cases = []
    for q, metric, mode_note in [
        ("Which products grew the most?", "revenue_change_abs", "absolute revenue"),
        ("Which products increased their revenue the most?", "revenue_change_abs", "absolute revenue"),
        ("Which products grew the fastest?", "revenue_change_pct", "pct revenue"),
        ("Which products declined the most?", "revenue_change_abs", "decline abs"),
        ("Which products had the highest gross profit growth?", "gross_profit_change_abs", "gp abs"),
        ("Show products whose margins improved.", "margin_change_pp", "margin pp"),
    ]:
        ai, ms = post(q)
        ai_rows = ai.get("data") or []
        # For decline / margin, re-sort independent when needed
        ind_sorted = list(ind)
        if "declined" in q.lower():
            ind_sorted = sorted(ind_sorted, key=lambda r: float(r.get("revenue_change_abs") or 0))
        elif "margins improved" in q.lower():
            ind_sorted = sorted(
                ind_sorted, key=lambda r: float(r.get("margin_change_pp") or 0), reverse=True
            )
        elif "gross profit" in q.lower():
            ind_sorted = sorted(
                ind_sorted, key=lambda r: float(r.get("gross_profit_change_abs") or 0), reverse=True
            )
        elif "fastest" in q.lower():
            ind_sorted = sorted(
                [
                    r
                    for r in ind_sorted
                    if r.get("revenue_change_pct") is not None
                ],
                key=lambda r: float(r.get("revenue_change_pct") or 0),
                reverse=True,
            )
        diffs = cmp_top(ai_rows, ind_sorted, metric)
        cases.append(
            {
                "question": q,
                "metric": metric,
                "mode": mode_note,
                "ms": ms,
                "intent": ((ai.get("query_plan") or {}).get("analytical_context") or {}).get("intent"),
                "ai_top": (ai_rows[0] if ai_rows else {}),
                "ind_top": (ind_sorted[0] if ind_sorted else {}),
                "diffs": diffs,
                "mismatches": sum(1 for d in diffs if not d["ok"]),
            }
        )

    report = {
        "api": API,
        "independent_sql_head": " ".join(GROWTH_SQL.split())[:400],
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
