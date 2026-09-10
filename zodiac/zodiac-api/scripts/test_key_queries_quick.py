"""Quick smoke test for dashboard router client questions."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.config.config import OPENAI_API_KEY
from app.database import SessionLocal
from app.services.dashboard_query_router import run_dashboard_query
from app.services.operational_query_resolver import resolve_operational_query

TESTS = [
    "Show all inbound SAT documents ordered by received date",
    "Which suppliers sent the most SAT documents?",
    "Show SAT documents received this week",
    "Show SAT document count by type (invoice, credit note, payment)",
    "How many SAT documents were received this week?",
    "List SAT documents with a missing or empty CFDI UUID",
    "Show failed EDI invoices and error reasons",
    "Show supplier with highest total invoice amount",
    "Show top 10 customers by revenue",
    "Show sales order count by month",
    "Show billing documents with amounts and currency",
    "Show open purchase orders by vendor",
]


def main() -> int:
    print("--- resolver routing ---")
    for q in TESTS:
        r = resolve_operational_query(q, time_scope="current")
        print(f"  {r[1] if r else 'SAP/catalog/intent':40} | {q[:60]}")

    key = OPENAI_API_KEY or os.getenv("OPEN_AI_KEY", "")
    if not key:
        print("ERROR: no API key")
        return 1
    db = SessionLocal()
    ok = 0
    print("\n--- dashboard router ---")
    try:
        for q in TESTS:
            t0 = time.time()
            r = run_dashboard_query(db, key, q, [], time_scope="current", days=30)
            elapsed = time.time() - t0
            path = r.get("sql_path_reason") or r.get("reason") or "?"
            rows = len(r.get("rows_preview") or [])
            err = (r.get("query_telemetry") or {}).get("execution_error")
            success = path != "no_match" and not err
            if success:
                ok += 1
            tag = "OK" if success else "FAIL"
            print(f"[{tag}] {elapsed:6.1f}s rows={rows:3d} path={path[:40]:40} | {q[:55]}")
            if err:
                print(f"       err: {str(err)[:160]}")
    finally:
        db.close()
    print(f"\n{ok}/{len(TESTS)} passed")
    return 0 if ok == len(TESTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
