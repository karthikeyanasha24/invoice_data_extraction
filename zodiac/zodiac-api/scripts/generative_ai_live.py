"""Generative AI page live probes: general chat + database + follow-up.

Does not replace R3/R4 suites. Uses the same login as other live scripts.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_http import adaptive_headers

API = "https://zodiac-back.vercel.app/api/query/adaptive"


def post(q: str, ctx: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {"question": q}
    if ctx:
        body["contextData"] = ctx
    t0 = time.perf_counter()
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(), headers=adaptive_headers()
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.load(resp)
    return out, int((time.perf_counter() - t0) * 1000)


def ctx_from(q: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql") or "",
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status") or "",
        "data": (r.get("data") or [])[:20],
    }


def snap(q: str, r: Dict[str, Any], ms: int) -> Dict[str, Any]:
    sql = (r.get("sql") or "").upper()
    return {
        "q": q,
        "ms": ms,
        "status": r.get("answer_status"),
        "mode": r.get("mode") or r.get("route"),
        "pipe": r.get("pipeline") or r.get("sql_generation_method"),
        "rows": r.get("rowCount"),
        "summary": (r.get("summary") or r.get("answer") or "")[:180],
        "fake_count": "INVOICE_BUSINESS_DATA" in sql and "TOTAL_ROWS" in sql,
        "too_short": "too_short" in str(r.get("keyFindings") or "").lower(),
    }


def main() -> int:
    probes = [
        "hello",
        "how are you?",
        "What is the meaning of life?",
        "How many sales orders are there?",
        "Show me information from VBAK",
        "Show me data from VBED",
    ]
    ctx = None
    prev_q = None
    fail = 0
    for q in probes:
        r, ms = post(q, ctx)
        row = snap(q, r, ms)
        print(json.dumps(row, ensure_ascii=True))
        if row["fake_count"] or row["too_short"]:
            fail += 1
        if q == "hello" and (r.get("sql") or "").strip():
            print("WARN: hello triggered SQL")
        ctx = ctx_from(q, r)
        prev_q = q

    r1, ms1 = post("Can you show me which customer and country and industry the highest sales reflected?")
    print("CLIENT", json.dumps(snap("client_q", r1, ms1), ensure_ascii=True))
    r2, ms2 = post("reflected?", ctx_from("client_q", r1))
    print("FOLLOW", json.dumps(snap("reflected?", r2, ms2), ensure_ascii=True))
    if snap("reflected?", r2, ms2)["fake_count"]:
        fail += 1
        print("FAIL reflected? used fake COUNT")
    print("FAILS", fail)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
