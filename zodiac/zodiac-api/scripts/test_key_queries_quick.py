"""Quick smoke test for dashboard router key queries."""
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

TESTS = [
    "Show profit center master records",
    "Show all inbound SAT documents ordered by received date",
    "Which suppliers sent the most SAT documents?",
    "Compare inbound SAT vs outbound invoices by supplier name for the last 30 days",
    "Compare inbound SAT vs outbound invoices by customer country for the last 30 days",
    "Show failed EDI invoices and error reasons",
    "Show top 10 customers by revenue",
    "Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers",
]


def main() -> int:
    key = OPENAI_API_KEY or os.getenv("OPEN_AI_KEY", "")
    if not key:
        print("ERROR: no API key")
        return 1
    db = SessionLocal()
    ok = 0
    try:
        for q in TESTS:
            t0 = time.time()
            r = run_dashboard_query(db, key, q, [], time_scope="current", days=30)
            elapsed = time.time() - t0
            path = r.get("sql_path_reason") or r.get("reason") or "?"
            rows = len(r.get("rows_preview") or [])
            success = path != "no_match"
            if success:
                ok += 1
            tag = "OK" if success else "FAIL"
            print(f"[{tag}] {elapsed:6.1f}s rows={rows:3d} path={path[:36]:36} | {q[:55]}")
    finally:
        db.close()
    print(f"\n{ok}/{len(TESTS)} passed")
    return 0 if ok == len(TESTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
