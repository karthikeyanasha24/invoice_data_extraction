#!/usr/bin/env python3
"""
Cross-check dashboard intent SQL for "top N customers by revenue in {year}" against the live DB.

Usage (from zodiac-api, with DATABASE_URL in .env):
  python scripts/verify_top_customers_year.py
  python scripts/verify_top_customers_year.py --year 2004 --limit 10

Reuses the same intent path as the UI: extract_intent → build_sql_plan → generate_sql
(+ catalog quoting + prepare_sql when available).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--question",
        default="what is the highest sales for the year 2004 by customer top 10",
        help="Natural language question (default: Andy-style phrasing)",
    )
    parser.add_argument("--year", type=int, default=2004, help="Expected calendar year in filters (for sanity)")
    parser.add_argument("--limit", type=int, default=10, help="Expected LIMIT (informational)")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    db_url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set in environment or .env")
        return 1
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    from sqlalchemy import create_engine, text

    engine = create_engine(db_url, pool_pre_ping=True)

    from app.services.schema_loader import load_schema_from_mapping_file
    from app.services.intent_extractor import extract_intent
    from app.services.intent_sql_planner import build_sql_plan, generate_sql

    schema = load_schema_from_mapping_file(max_columns_per_table=None)
    intent = extract_intent(args.question, schema)
    plan = build_sql_plan(intent, schema)
    sql = generate_sql(plan)

    try:
        from app.services.sap_sql_agent import _quote_catalog_sql_tables

        sql = _quote_catalog_sql_tables(sql)
    except Exception as e:
        print("Note: _quote_catalog_sql_tables skipped:", e)

    try:
        from app.services.sql_generation_sanitizers import prepare_sql_for_sqlalchemy_text_execution as _prep

        safe_sql = _prep(sql)
    except Exception:
        safe_sql = sql

    print("=== Intent snapshot ===")
    print("intent_type:", intent.get("intent_type"))
    print("ranking:", intent.get("ranking"))
    print("filters:", intent.get("filters"))
    print("dimensions:", intent.get("dimensions"))
    print()
    print("=== SQL ===")
    print(safe_sql)
    print()

    with engine.connect() as conn:
        rows = conn.execute(text(safe_sql)).mappings().all()

    print(f"=== Results ({len(rows)} rows) ===")
    for i, r in enumerate(rows, 1):
        d = dict(r)
        print(f"{i:2}.", d)

    # Heuristic checks
    y = str(args.year)
    sql_u = (safe_sql or "").upper()
    if y not in sql_u:
        print(f"\nWARNING: year {y} not found as literal in SQL text (may still filter via expression).")
    if "GJAHR" in sql_u and f"GJAHR = '{y}'" in sql_u.replace(" ", ""):
        print("WARNING: SQL appears to filter fiscal year GJAHR for calendar year — often wrong for billing.")

    print("\nDone. Compare customer IDs and totals with the dashboard table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
