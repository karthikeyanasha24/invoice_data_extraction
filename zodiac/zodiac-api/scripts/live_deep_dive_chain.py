#!/usr/bin/env python3
"""Live deep-dive chain against POST /api/query/adaptive.

Requires a running API with SAP/data access. Does not invent results.

Usage:
  set ADAPTIVE_API=http://127.0.0.1:8000/api/query/adaptive
  python scripts/live_deep_dive_chain.py
"""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request

API = os.environ.get("ADAPTIVE_API", "http://127.0.0.1:8000/api/query/adaptive").rstrip("/")

ANDY_EXACT = [
    "Show me product with highest profits and show me the breakdown of components.",
    "Show me cost of goods.",
    "Show me products with lowest margins.",
    "Show me product expiring by industry.",
    "Show me customers with industry data and regions.",
    "What type of products are bought by which customers?",
    "And how long have they been buying them?",
    "Compare it with product.",
    "Compare it with year.",
    "Show me the process involved behind selling it.",
    "Show me the process involved behind buying it.",
    "Show me the buying process and selling process.",
]

LONG_CHAIN = [
    "Show the top 10 products by profit.",
    "Show their customers.",
    "Break that down by industry.",
    "Show the regions.",
    "Compare 2024 and 2025.",
    "Show COGS.",
    "Show the margins.",
    "Which products had the biggest margin decline?",
    "Why did those margins decline?",
    "Show me the cost components.",
    "Show me the buying process behind these products.",
    "Show the selling process.",
    "Show the delivery/logistics relationship if available.",
]

BASIC_REGRESSION = [
    "Show me highest sales for the year 2004 with customer and industry",
    "Meaning of life",
    "Top 5",
]


def post(question: str, ctx: dict | None) -> tuple[dict, float]:
    body: dict = {"question": question}
    if ctx:
        body["contextData"] = ctx
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload, time.perf_counter() - t0


def ctx_from(question: str, payload: dict) -> dict:
    return {
        "previousQuestion": question,
        "previousSQL": payload.get("sql") or "",
        "previousPlan": payload.get("query_plan"),
        "previousAnswerStatus": payload.get("answer_status"),
        "data": (payload.get("data") or [])[:20],
    }


def summarize(label: str, question: str, payload: dict, sec: float) -> dict:
    qp = payload.get("query_plan") or {}
    ac = qp.get("analytical_context") if isinstance(qp, dict) else {}
    row = {
        "label": label,
        "question": question,
        "sec": round(sec, 3),
        "status": payload.get("answer_status"),
        "pipeline": payload.get("pipeline") or payload.get("sql_generation_method"),
        "intent": (ac or {}).get("intent") or qp.get("intent"),
        "products": (ac or {}).get("selected_products") or [],
        "rows": len(payload.get("data") or []),
        "sql_preview": (payload.get("sql") or "")[:180].replace("\n", " "),
        "followups": (payload.get("suggested_followups") or [])[:5],
    }
    print(
        f"[{label}] {sec:.2f}s status={row['status']} pipeline={row['pipeline']} "
        f"intent={row['intent']} rows={row['rows']} products={len(row['products'])}"
    )
    print(f"  Q: {question}")
    if row["sql_preview"]:
        print(f"  SQL: {row['sql_preview']}...")
    return row


def run_chain(name: str, questions: list[str], carry_ctx: bool = True) -> list[dict]:
    results = []
    ctx = None
    for i, q in enumerate(questions, 1):
        try:
            payload, sec = post(q, ctx if carry_ctx else None)
        except Exception as exc:
            print(f"[{name}/{i}] FAIL {q!r}: {exc}")
            results.append({"label": f"{name}/{i}", "question": q, "error": str(exc)})
            break
        row = summarize(f"{name}/{i}", q, payload, sec)
        results.append(row)
        # Keep last successful analytical context for follow-ups
        status = str(payload.get("answer_status") or "").upper()
        if status in {"SUCCESS", "PARTIAL"} and (payload.get("sql") or "").strip():
            ctx = ctx_from(q, payload)
        elif status == "CANNOT_ANSWER" and ctx is None:
            ctx = ctx_from(q, payload)
    return results


def latency_stats(seconds: list[float]) -> dict:
    if not seconds:
        return {}
    s = sorted(seconds)
    def pct(p: float) -> float:
        if len(s) == 1:
            return s[0]
        k = (len(s) - 1) * p
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] + (s[c] - s[f]) * (k - f)
    return {
        "n": len(s),
        "p50": round(pct(0.50), 3),
        "p95": round(pct(0.95), 3),
        "max": round(max(s), 3),
        "mean": round(statistics.mean(s), 3),
    }


def main() -> int:
    print("API =", API)
    # Warmup / health
    try:
        post("Invoice count 2004", None)
    except urllib.error.URLError as exc:
        print("API unreachable:", exc)
        print("Start the API (with SAP DB) or set ADAPTIVE_API, then re-run.")
        return 2

    all_rows: list[dict] = []
    all_rows.extend(run_chain("basic", BASIC_REGRESSION, carry_ctx=True))
    all_rows.extend(run_chain("andy", ANDY_EXACT, carry_ctx=True))
    all_rows.extend(run_chain("long", LONG_CHAIN, carry_ctx=True))

    secs = [r["sec"] for r in all_rows if "sec" in r]
    stats = latency_stats(secs)
    print("\n=== LATENCY (all successful HTTP turns) ===")
    print(json.dumps(stats, indent=2))

    out = os.environ.get("DEEP_LIVE_OUT", "live_deep_dive_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"api": API, "latency": stats, "turns": all_rows}, f, indent=2)
    print("Wrote", out)
    return 0 if not any("error" in r for r in all_rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
