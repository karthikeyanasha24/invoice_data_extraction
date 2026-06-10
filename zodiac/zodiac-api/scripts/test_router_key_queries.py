"""Targeted smoke test for scalable dashboard router (3 critical paths)."""
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
    ("SAT operational", "Show all inbound SAT documents ordered by received date"),
    ("SAP revenue", "Show top 10 customers by revenue"),
    ("Open PO catalog", "Show open purchase orders by vendor"),
]


def main() -> int:
    api_key = OPENAI_API_KEY or os.getenv("OPEN_AI_KEY", "")
    if not api_key:
        print("ERROR: OPENAI_API_KEY / OPEN_AI_KEY not set")
        return 1

    db = SessionLocal()
    ok = 0
    try:
        for label, q in QUESTIONS:
            t0 = time.time()
            payload = run_planner(db, api_key, q, [], days=365, time_scope="current")
            elapsed = round(time.time() - t0, 1)
            path = payload.get("sql_path_reason") or payload.get("reason") or ""
            rows = len(payload.get("rows_preview") or [])
            reply = (payload.get("reply") or "").strip()[:100]
            success = bool(reply) and path != "no_match"
            if label == "SAP revenue":
                success = success and not path.startswith("operational_")
            if label == "Open PO catalog":
                success = success and rows > 0 and path in ("sql_catalog", "intent_sql_fast", "universal_adaptive")
            if success:
                ok += 1
            tag = "OK" if success else "FAIL"
            print(f"[{tag}] {label}: {elapsed}s rows={rows} path={path}")
            print(f"       {reply}")
    finally:
        db.close()

    print(f"\n{ok}/{len(QUESTIONS)} passed")
    return 0 if ok == len(QUESTIONS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
