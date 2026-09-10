"""Fast template check — builds SQL for each new template and executes it (no LLM calls)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.adaptive_query import _execute_sql
from app.database import SessionLocal
from app.services.adaptive_structured_sql import (
    build_country_customer_list_sql,
    build_customer_industry_revenue_sql,
    build_dimension_ranking_sql,
    build_multidim_ranking_sql,
    build_period_sales_sql,
    build_sat_logs_sql,
    build_total_measure_sql,
)

TABLES = ["VBRK", "vbrp", "KNA1", "T016T", "MAKT", "sat_processing_logs"]

CASES = [
    ("Top 3 countries by billed revenue", build_dimension_ranking_sql, 3),
    ("Which customer had the lowest sales in 2004?", build_dimension_ranking_sql, 1),
    ("Top 10 products by revenue in 2005", build_dimension_ranking_sql, None),
    ("Show the five biggest customers by invoice count", build_dimension_ranking_sql, 5),
    ("Which industry generated the most revenue?", build_dimension_ranking_sql, 1),
    ("Top 5 customers by billed sales", build_dimension_ranking_sql, 5),
    ("Top 20 materials by billed quantity", build_dimension_ranking_sql, 20),
    ("Top 10 customers by sales", build_dimension_ranking_sql, 10),
    ("Which country, customer, and industry has the highest sales?", build_multidim_ranking_sql, 1),
    ("Show sales by year", build_period_sales_sql, None),
    ("Show monthly sales for 2004", build_period_sales_sql, None),
    ("Sales trend by quarter", build_period_sales_sql, None),
    ("Compare sales in 2004 and 2005", build_period_sales_sql, 2),
    ("What were total billed sales in 2003?", build_total_measure_sql, 1),
    ("Customers and industries with billed revenue", build_customer_industry_revenue_sql, None),
    ("List all customers in Germany", build_country_customer_list_sql, None),
    ("Show SAT processing logs", build_sat_logs_sql, None),
    ("Show failed SAT processing steps", build_sat_logs_sql, None),
    ("Latest SAT processing errors", build_sat_logs_sql, None),
]


def main() -> int:
    db = SessionLocal()
    passed = failed = 0
    try:
        for question, builder, expect_rows in CASES:
            try:
                sql = builder(question, TABLES) if builder is build_country_customer_list_sql \
                    or builder is build_sat_logs_sql else builder(question, TABLES, {})
            except Exception as exc:
                print(f"[FAIL] {question}\n  builder raised: {exc}\n")
                failed += 1
                continue

            if not sql:
                print(f"[FAIL] {question}\n  builder returned None\n")
                failed += 1
                continue

            try:
                rows = _execute_sql(db, sql, question)
            except Exception as exc:
                print(f"[FAIL] {question}\n  SQL: {sql[:400]}\n  error: {str(exc)[:300]}\n")
                failed += 1
                continue

            if expect_rows is not None and len(rows) != expect_rows:
                print(f"[FAIL] {question}\n  expected {expect_rows} rows, got {len(rows)}\n  SQL: {sql[:300]}\n")
                failed += 1
                continue

            sample = rows[0] if rows else {}
            print(f"[ OK ] {question}\n  rows={len(rows)} sample={str(sample)[:150]}\n")
            passed += 1
    finally:
        db.close()

    print("=" * 60)
    print(f"{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
