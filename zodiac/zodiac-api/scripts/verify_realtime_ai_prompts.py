"""
Cross-check Dashboard AI Real-time suggestion strings against operational_query_resolver.

Usage (from zodiac-api directory):
  python scripts/verify_realtime_ai_prompts.py

Optional: execute SQL on the app DB (requires DATABASE_URL / SessionLocal working):
  python scripts/verify_realtime_ai_prompts.py --execute

Keep REALTIME_QUERIES in sync with:
  zodiac-front/src/components/DashboardAIAnalysis.tsx  →  REALTIME_PROMPTS

Domain chips ("What can you ask?") are verified with:
  python scripts/verify_domain_ai_prompts.py
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.operational_query_resolver import (
    resolve_operational_query,
    try_operational_dashboard_fast_path,
)

# Mirror tests/test_operational_realtime_prompts.py
REALTIME_QUERIES: List[Tuple[str, str, Optional[str]]] = [
    (
        "Failed invoices",
        "Summarize failed invoices and main failure reasons in the last 30 days (Zodiac EDI failure tables)",
        "failed_invoices_summary",
    ),
    (
        "Inbound SAT",
        "Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers (sat_canonical_merged)",
        "inbound_sat_merge",
    ),
    (
        "Top customers",
        "Show top customers with currency and ranked invoice counts from extracted Zodiac invoice business data (last 30 days)",
        "top_customers_business_currency",
    ),
    (
        "Outbound flow",
        "Show outbound process flow with document counts per V2 funnel stage (received, validated, failed, pending)",
        "outbound_funnel",
    ),
    (
        "EDI status",
        "EDI status: count succeeded vs failed EDI submissions by Zodiac account for the last 30 days",
        "edi_customer_status",
    ),
    (
        "Conversion rate",
        "What is the V2 invoice conversion success rate versus documents received, and which funnel step shows the largest backlog?",
        "invoice_conversion_kpi",
    ),
    (
        "Open orders",
        "Show open purchase requisitions (EBAN) and purchase orders that are still pending in SAP",
        None,
    ),
    (
        "Delivery status",
        "Show recent delivery header and item status for current shipments from LIKP and LIPS tables",
        None,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run try_operational_dashboard_fast_path on app DB (first row only per query)",
    )
    args = parser.parse_args()

    failed = False
    for label, query, expected in REALTIME_QUERIES:
        resolved = resolve_operational_query(query, time_scope="current", api_key=None)
        got_type = None if resolved is None else resolved[1]
        ok = got_type == expected
        status = "OK" if ok else "MISMATCH"
        if not ok:
            failed = True
        print(f"[{status}] {label!r} -> operational={got_type!r} (expected {expected!r})")

        if args.execute and resolved is not None:
            try:
                from app.database import SessionLocal

                db = SessionLocal()
                try:
                    payload = try_operational_dashboard_fast_path(
                        db,
                        query,
                        api_key=None,
                        days=30,
                        time_scope="current",
                    )
                    n = len((payload or {}).get("rows_preview") or [])
                    print(f"       executed rows_preview={n} reply_len={len((payload or {}).get('reply') or '')}")
                finally:
                    db.close()
            except Exception as ex:
                print(f"       execute ERROR: {ex}")
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
