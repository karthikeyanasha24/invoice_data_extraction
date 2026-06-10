"""Quick local smoke test for run_planner (no HTTP auth required)."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.config.config import OPENAI_API_KEY
from app.database import SessionLocal
from app.services.multi_stage_planner import run_planner

QUESTIONS = [
    "Show all inbound SAT documents ordered by received date",
    "Which suppliers sent the most SAT documents?",
    "Show SAT documents received this week",
    "Show failed EDI invoices and error reasons",
    "Show top 10 customers by revenue",
    "Show sales order count by month",
    "Show billing documents with amounts and currency",
    "Show open purchase orders by vendor",
    "Show SAT document count by type (invoice, credit note, payment)",
    "Show supplier with highest total invoice amount",
]


def main() -> int:
    api_key = OPENAI_API_KEY or os.getenv("OPEN_AI_KEY", "")
    if not api_key:
        print("ERROR: OPENAI_API_KEY / OPEN_AI_KEY not set")
        return 1

    db = SessionLocal()
    ok_count = 0
    try:
        for i, q in enumerate(QUESTIONS, 1):
            t0 = time.time()
            try:
                payload = run_planner(
                    db,
                    api_key,
                    q,
                    [],
                    days=365,
                    time_scope="current",
                )
                elapsed = round(time.time() - t0, 1)
                rows = len(payload.get("rows_preview") or [])
                path = payload.get("sql_path_reason") or payload.get("reason") or ""
                reply = (payload.get("reply") or "").strip()
                err = (payload.get("query_telemetry") or {}).get("execution_error")
                success = bool(reply) and not err
                if path.startswith("operational_"):
                    success = bool(reply)
                if success:
                    ok_count += 1
                tag = "OK" if success else "WARN"
                print(f"{i:2}. [{tag}] {elapsed:6.1f}s rows={rows} path={path}")
                print(f"    Q: {q}")
                print(f"    R: {reply[:120]}")
                if err:
                    print(f"    SQL err: {str(err)[:160]}")
            except Exception as exc:
                print(f"{i:2}. [ERR] {q}")
                print(f"    {type(exc).__name__}: {exc}")
    finally:
        db.close()

    print(f"\nSUMMARY: {ok_count}/{len(QUESTIONS)} returned usable replies")
    return 0 if ok_count >= 7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
