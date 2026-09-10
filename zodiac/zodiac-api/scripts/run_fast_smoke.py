"""Fast smoke tests: deterministic SQL templates + direct execution (no LLM)."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.adaptive_query import _execute_sql
from app.database import SessionLocal
from app.services.adaptive_structured_sql import build_filter_list_sql, build_multidim_ranking_sql

TOP5 = (
    'SELECT TRIM(k."kunag") AS customer_id, TRIM(c."name1") AS customer_name, '
    'SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') AS NUMERIC)) AS total_billed '
    'FROM "vbrp" p '
    'JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"), 10, \'0\') = LPAD(TRIM(k."vbeln"), 10, \'0\') '
    'LEFT JOIN "KNA1" c ON LPAD(TRIM(k."kunag"), 10, \'0\') = LPAD(TRIM(c."kunnr"), 10, \'0\') '
    'WHERE NULLIF(TRIM(CAST(p."netwr" AS TEXT)), \'\') IS NOT NULL '
    'GROUP BY 1, 2 ORDER BY total_billed DESC NULLS LAST LIMIT 5'
)

TOP20_MAT = (
    'SELECT TRIM(p."matnr") AS material_id, TRIM(m."maktx") AS material_name, '
    'SUM(CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), \'\') AS NUMERIC)) AS billed_quantity '
    'FROM "vbrp" p '
    'LEFT JOIN "MAKT" m ON TRIM(p."matnr") = TRIM(m."matnr") '
    'WHERE NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), \'\') IS NOT NULL '
    'GROUP BY 1, 2 ORDER BY billed_quantity DESC NULLS LAST LIMIT 20'
)

CASES = [
    ("multidim_ranking", build_multidim_ranking_sql(
        "Which country, customer, and industry has the highest sales?",
        ["VBRK", "KNA1", "T016T"],
        {},
    )),
    ("negative_sales_2000", build_filter_list_sql(
        "show me negatives sales for the year 2000",
        ["vbrp", "MAKT", "KNA1"],
        {},
    )),
    ("top5_customers", TOP5),
    ("top20_materials", TOP20_MAT),
    ("customer_names", 'SELECT TRIM("name1") AS customer_name FROM "KNA1" WHERE NULLIF(TRIM("name1"), \'\') IS NOT NULL LIMIT 50'),
    ("sat_logs", (
        'SELECT step_name, step_status, message, created_at FROM "sat_processing_logs" '
        "ORDER BY created_at DESC LIMIT 10"
    )),
]


def main() -> int:
    db = SessionLocal()
    passed = failed = 0
    try:
        for label, sql in CASES:
            print(f"\n[{label}]")
            if not sql:
                print("  FAIL — no SQL generated")
                failed += 1
                continue
            print(f"  SQL: {sql[:120]}...")
            t0 = time.time()
            try:
                rows = _execute_sql(db, sql, label) or []
                elapsed = round(time.time() - t0, 2)
                print(f"  PASS — {len(rows)} rows in {elapsed}s")
                if rows:
                    print(f"  sample: {rows[0]}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL — {exc}")
                failed += 1
    finally:
        db.close()

    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
