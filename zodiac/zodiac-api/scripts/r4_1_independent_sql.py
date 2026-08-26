"""Independent SQL validation for R4-1 month/quarter metrics vs live AI answers."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

API = "https://zodiac-back.vercel.app/api/query/adaptive"
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

YM = '(SUBSTRING(TRIM(CAST(vk."fkdat" AS TEXT)), 1, 4) || \'-\' || SUBSTRING(TRIM(CAST(vk."fkdat" AS TEXT)), 5, 2))'
YQ = (
    '(SUBSTRING(TRIM(CAST(vk."fkdat" AS TEXT)), 1, 4) || \'-Q\' || '
    'CAST((((CAST(SUBSTRING(TRIM(CAST(vk."fkdat" AS TEXT)), 5, 2) AS INTEGER) - 1) / 3) + 1) AS TEXT))'
)
VALID = (
    'vk."fkdat" IS NOT NULL AND TRIM(CAST(vk."fkdat" AS TEXT)) <> \'\' '
    "AND LENGTH(TRIM(CAST(vk.\"fkdat\" AS TEXT))) >= 6 "
    "AND SUBSTRING(TRIM(CAST(vk.\"fkdat\" AS TEXT)), 1, 4) ~ '^[12][0-9]{3}$' "
    "AND SUBSTRING(TRIM(CAST(vk.\"fkdat\" AS TEXT)), 5, 2) ~ '^(0[1-9]|1[0-2])$'"
)
REV = "CAST(NULLIF(TRIM(CAST(v.\"netwr\" AS TEXT)), '') AS NUMERIC)"
COGS = "CAST(NULLIF(TRIM(CAST(COALESCE(v.\"wavwr\", '0') AS TEXT)), '') AS NUMERIC)"
QTY = "CAST(NULLIF(TRIM(CAST(v.\"fkimg\" AS TEXT)), '') AS NUMERIC)"


def post(q: str):
    req = urllib.request.Request(
        API,
        data=json.dumps({"question": q}).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    return out, int((time.perf_counter() - t0) * 1000)


def period_sql(period_expr: str, period_alias: str) -> str:
    return f"""
SELECT
  {period_expr} AS {period_alias},
  vk.waerk AS currency,
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
WHERE {REV} IS NOT NULL
  AND {VALID}
GROUP BY {period_expr}, vk.waerk
ORDER BY {period_alias}, currency
LIMIT 120
""".strip()


def cmp_rows(ai_rows, ind_rows, period_key: str, metric: str, tol_pct: float = 0.5):
    ai_map = {}
    for r in ai_rows:
        k = (str(r.get(period_key)), str(r.get("currency")))
        ai_map[k] = float(r.get(metric) or 0)
    ind_map = {}
    for r in ind_rows:
        k = (str(r.get(period_key)), str(r.get("currency")))
        ind_map[k] = float(r.get(metric) or 0)
    keys = sorted(set(ai_map) | set(ind_map))
    diffs = []
    for k in keys[:40]:
        a = ai_map.get(k)
        b = ind_map.get(k)
        if a is None or b is None:
            diffs.append({"period": k, "ai": a, "ind": b, "status": "MISSING"})
            continue
        denom = abs(b) if abs(b) > 1e-9 else 1.0
        pct = abs(a - b) / denom * 100.0
        diffs.append(
            {
                "period": k,
                "ai": a,
                "ind": b,
                "diff": a - b,
                "diff_pct": round(pct, 4),
                "status": "OK" if pct <= tol_pct else "MISMATCH",
            }
        )
    mismatch = [d for d in diffs if d["status"] != "OK"]
    return {
        "metric": metric,
        "period_key": period_key,
        "compared": len(diffs),
        "mismatches": len(mismatch),
        "sample": diffs[:8],
        "result": "PASS" if not mismatch else "FAIL",
    }


def main():
    url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not url:
        print("BLOCKED: DATABASE_URL unavailable")
        return
    eng = create_engine(url, pool_pre_ping=True)
    cases = [
        ("Show monthly revenue.", YM, "year_month", "revenue"),
        ("Show quarterly revenue.", YQ, "year_quarter", "revenue"),
        ("Show monthly COGS.", YM, "year_month", "cogs"),
        ("Show quarterly profit.", YQ, "year_quarter", "gross_profit"),
        ("Show monthly revenue.", YM, "year_month", "avg_selling_price"),
        ("Show quarterly margins.", YQ, "year_quarter", "gross_margin_pct"),
    ]
    results = []
    with eng.connect() as conn:
        for q, expr, pkey, metric in cases:
            ai, ms = post(q)
            ai_rows = ai.get("data") or []
            ind = [dict(r) for r in conn.execute(text(period_sql(expr, pkey))).mappings()]
            # Align AI ordering for comparison: use period+currency keys
            cmp = cmp_rows(ai_rows, ind, pkey, metric)
            cmp.update(
                {
                    "question": q,
                    "ai_ms": ms,
                    "ai_intent": ((ai.get("query_plan") or {}).get("analytical_context") or {}).get(
                        "intent"
                    ),
                    "ai_rows": len(ai_rows),
                    "ind_rows": len(ind),
                    "chron_ok": [r[pkey] for r in ind[:5]],
                }
            )
            results.append(cmp)
            print(cmp["result"], metric, q, "mismatches", cmp["mismatches"], "ai_ms", ms)

    out = {"result": "PASS" if all(r["result"] == "PASS" for r in results) else "FAIL", "cases": results}
    Path("r4_1_independent_sql.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("OVERALL", out["result"])


if __name__ == "__main__":
    main()
