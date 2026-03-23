"""
Verification tooling for AI analysis quality.

This script runs deterministic, constraint-specific SQL (year + billing category/type
+ count vs sum + optional currency) against the same DB connections the app uses,
prints the expected aggregates, and optionally validates that the generated SQL
contains the required predicates.

Usage example (edit values as needed):
  python scripts/verify_ai_analysis_stakeholder_scenarios.py --year 1999 --billing-category A --currency USD
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.config import USE_SAP_DB_FOR_AI
from app.database import SessionLocal, get_sap_session
from app.services.deterministic_sql_resolver import resolve_deterministic_sql
from app.services.schema_loader import get_schema_dict
from app.services.sap_sql_agent import _quote_catalog_sql_tables, _run_sql, SqlAgentResult
from app.services.sql_validator import validate_sql as schema_validate_sql


def _run_deterministic_question(
    db,  # SQLAlchemy Session
    *,
    question: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    schema = get_schema_dict(db)
    avail = list(schema.keys())
    schema_table_case = {t.upper(): t for t in avail}
    sql = resolve_deterministic_sql(question, available_tables=avail, schema_table_case=schema_table_case)
    if not sql:
        raise RuntimeError(f"Deterministic resolver returned no SQL for: {question}")

    ok, _ = schema_validate_sql(sql, schema)
    if not ok:
        raise RuntimeError(f"Deterministic SQL failed schema validation.\nSQL:\n{sql}")

    quoted_sql = _quote_catalog_sql_tables(sql)
    rows = _run_sql(db, quoted_sql)
    return quoted_sql, rows or []


def _assert_required_substrings(sql: str, required: List[str]) -> None:
    missing = [x for x in required if x.lower() not in (sql or "").lower()]
    if missing:
        raise AssertionError(f"Generated SQL missing required fragments: {missing}\nSQL:\n{sql}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True, help="Calendar year, e.g. 1999")
    parser.add_argument("--billing-category", required=True, help="VBRK.FKTYP value (e.g. A, B, C...)")
    parser.add_argument("--billing-type", default=None, help="Optional VBRK.FKART value")
    parser.add_argument("--currency", default=None, help="Optional WAERK currency code to filter, e.g. USD")
    parser.add_argument("--skip-sql-fragment-check", action="store_true")
    args = parser.parse_args()

    year = str(args.year)
    billing_cat = str(args.billing_category)
    billing_type = str(args.billing_type) if args.billing_type else None
    currency = str(args.currency) if args.currency else None

    db = None
    sap_db = None
    try:
        sap_db = get_sap_session() if USE_SAP_DB_FOR_AI else None
        db = sap_db or SessionLocal()

        # Scenario 1: invoice count for year + billing category (+ optional currency)
        q_count = f"invoice count for year {year} and billing category {billing_cat}"
        if currency:
            q_count += f" in {currency}"
        if billing_type:
            q_count += f" and billing type {billing_type}"

        # Scenario 2: total revenue/value for year + billing category (+ optional currency)
        q_sum = f"total sales for year {year} and billing category {billing_cat}"
        if currency:
            q_sum += f" in {currency}"
        if billing_type:
            q_sum += f" and billing type {billing_type}"

        for label, q in [("COUNT", q_count), ("SUM", q_sum)]:
            quoted_sql, rows = _run_deterministic_question(db, question=q)
            print("\n" + "=" * 80)
            print(f"[{label}] Question: {q}")
            print(f"[{label}] SQL:\n{quoted_sql}")
            print(f"[{label}] Rows ({len(rows)}):")
            for r in rows[:5]:
                print(" ", r)

            if not args.skip_sql_fragment_check:
                required = [
                    # Year must be fkdat-based.
                    f"'{year}'",
                    "fkdat",
                    # Category predicate must exist for these scenarios.
                    "fktyp",
                    f"'{billing_cat}'",
                ]
                if currency:
                    required += ["waerk", f"'{currency}'"]
                if label == "COUNT":
                    required += ["count("]
                if label == "SUM":
                    required += ["sum("]
                _assert_required_substrings(quoted_sql, required)

        print("\nAll stakeholder scenarios verified (deterministic SQL fragment checks passed).")
        return 0
    except Exception as e:
        print(f"\n❌ Verification failed: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            if sap_db is not None:
                sap_db.close()
        except Exception:
            pass
        try:
            if db is not None and db is not sap_db:
                db.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

