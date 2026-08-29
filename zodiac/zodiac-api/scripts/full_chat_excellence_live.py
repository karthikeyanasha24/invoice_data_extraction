"""Clean-session Full Chat chain for product-excellence acceptance. Do not commit output JSON."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_http import adaptive_headers

API = "https://zodiac-back.vercel.app/api/query/adaptive"
CHAIN = [
    "Show the products with the highest profits.",
    "Show inventory.",
    "Show sales.",
    "Show high inventory with low sales.",
    "Show their product groups.",
    "Show their suppliers.",
    "Show their customers.",
    "Show their regions.",
    "Show inventory by plant.",
    "Compare their sales with last year.",
    "Why?",
    "Show inventory aging.",
    "Show inventory again.",
    "Show net profit.",
    "Show inventory again.",
    "Show supplier concentration.",
    "Show top 3.",
    "Show the percentage.",
    "Show their suppliers.",
]


def post(q: str, ctx=None):
    body = {"question": q}
    if ctx:
        body["contextData"] = ctx
    t0 = time.perf_counter()
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers=adaptive_headers())
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.load(resp)
    out["_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def ctx_from(q, r):
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql", ""),
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status", ""),
        "data": (r.get("data") or [])[:20],
    }


def intent_of(r):
    qp = r.get("query_plan") or {}
    ac = qp.get("analytical_context") or {}
    return str(ac.get("intent") or qp.get("intent") or "")


def main():
    ctx = None
    p = d = f = 0
    rows = []
    for i, q in enumerate(CHAIN, 1):
        r = post(q, ctx)
        st = r.get("answer_status", "")
        it = intent_of(r)
        sql = (r.get("sql") or "").upper()
        n = len(r.get("data") or [])
        summary = (r.get("summary") or "")[:80]
        if st == "CANNOT_ANSWER":
            lab = "DATA_GAP"
            d += 1
        elif st == "SUCCESS":
            lab = "PASS"
            p += 1
        else:
            lab = "FAIL"
            f += 1
        if "VBRP" in sql and "EKPO" in sql:
            lab = "FAIL(fanout)"
            f += 1
            if p:
                p -= 1
        print(f"{i:02d} {lab:8} {r['_ms']:5}ms n={n:3} intent={it:28} | {q}")
        if "Deep analysis" in summary or "intent " in summary.lower() and "_" in summary:
            print("  HEADING_SLUG", summary[:120])
        rows.append({"q": q, "ms": r["_ms"], "status": st, "intent": it, "n": n, "label": lab})
        ctx = ctx_from(q, r)
    print("COUNTS", {"PASS": p, "DATA_GAP": d, "FAIL": f})
    Path("full_chat_excellence_live.json").write_text(
        json.dumps({"counts": {"PASS": p, "DATA_GAP": d, "FAIL": f}, "rows": rows}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
