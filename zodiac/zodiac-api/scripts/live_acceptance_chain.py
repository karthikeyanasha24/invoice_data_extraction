"""One-shot live acceptance: 17-turn chain + basic regression."""
from __future__ import annotations

import json
import time
import urllib.request

API = "https://zodiac-back.vercel.app/api/query/adaptive"

CHAIN = [
    "Show me the products with the highest profits.",
    "Show their customers.",
    "Break that down by industry.",
    "Show the regions.",
    "Compare 2004 and 2005.",
    "Show COGS.",
    "Show the margins.",
    "Which products had the biggest margin decline?",
    "Why did those margins decline?",
    "Show me the cost components.",
    "How long have they been buying them?",
    "Show me the buying process.",
    "Show me the selling process.",
    "Show me the delivery process.",
    "Show me logistics cost.",
    "Show me net profit.",
    "Now show me COGS again.",
]


def post(q: str, ctx=None):
    body = {"question": q}
    if ctx:
        body["contextData"] = ctx
    data = json.dumps(body).encode()
    t0 = time.perf_counter()
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.load(resp)
    out["_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def ctx_from(prev_q, prev):
    return {
        "previousQuestion": prev_q,
        "previousSQL": prev.get("sql", ""),
        "previousPlan": prev.get("query_plan") or {},
        "previousAnswerStatus": prev.get("answer_status", ""),
        "data": (prev.get("data") or [])[:20],
    }


def main():
    ctx = None
    times = []
    print("=== 17-TURN LIVE CHAIN ===")
    for i, q in enumerate(CHAIN, 1):
        r = post(q, ctx)
        status = r.get("answer_status")
        pipe = r.get("pipeline", "")
        qp = r.get("query_plan") or {}
        ac = qp.get("analytical_context") or {}
        intent = ac.get("intent") or qp.get("intent", "")
        if status == "CANNOT_ANSWER":
            label = "DATA GAP"
        elif status == "SUCCESS" and pipe == "deep_multidim":
            label = "PASS"
        else:
            label = "FAIL"
        times.append(r["_ms"])
        print(
            f"{i:02d} {label:8} {r['_ms']:4}ms status={status} pipe={pipe} "
            f"rows={r.get('rowCount', 0)} intent={intent} | {q}"
        )
        ctx = ctx_from(q, r)

    print("\n=== BASIC REGRESSION ===")
    for seq in [
        ["2004", "Meaning of life", "Top 5"],
        ["2004", "Meaning of life", "Show sales for 2005", "Top 3"],
    ]:
        print("---")
        ctx = None
        for q in seq:
            r = post(q, ctx)
            print(
                f"  {q!r} -> {r.get('answer_status')} pipe={r.get('pipeline', '')} "
                f"rows={r.get('rowCount', 0)}"
            )
            ctx = ctx_from(q, r)

    times.sort()
    n = len(times)
    p50 = times[n // 2]
    p95 = times[int(n * 0.95)] if n else 0
    print(f"\nPERF ms: p50={p50} p95={p95} max={max(times) if times else 0}")


if __name__ == "__main__":
    main()
