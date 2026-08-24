#!/usr/bin/env python3
"""Verify Andy deep-dive questions against an adaptive API endpoint."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("ADAPTIVE_API", "https://zodiac-back.vercel.app/api/query/adaptive").rstrip("/")
MODE = os.environ.get("VERIFY_MODE", "live")  # live | local

ANDY_QUESTIONS = [
    "Show me product with highest profits and show me the breakdown of components",
    "Show me cost of goods",
    "Show me products with lowest margins",
    "Show me products expiring by industry",
    "Show me customers with industry data and regions",
    "What type of products are bought by which customers?",
    "And how long have they been buying them?",
    "Compare it with year",
    "Show me the process involved behind selling it",
    "Show me the process involved behind buying it",
    "Show me the buying process and selling process",
    "Show me logistics cost",
    "Show me net profit",
]

CHAIN = [
    "Show the top 10 products by profit.",
    "Show their customers.",
    "Break that down by industry.",
    "Show the regions.",
    "Compare 2004 and 2005.",
    "Show COGS.",
    "Show the margins.",
    "Which products had the biggest margin decline?",
    "Why did those margins decline?",
    "Show me the cost components.",
    "Show me the buying process behind these products.",
    "Show the selling process.",
]


def post(question: str, ctx: dict | None) -> tuple[dict | None, float, str | None]:
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
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload, time.perf_counter() - t0, None
    except Exception as exc:
        return None, time.perf_counter() - t0, str(exc)


def ctx_from(question: str, payload: dict) -> dict:
    return {
        "previousQuestion": question,
        "previousSQL": payload.get("sql") or "",
        "previousPlan": payload.get("query_plan"),
        "previousAnswerStatus": payload.get("answer_status"),
        "data": (payload.get("data") or [])[:20],
    }


def intent_of(payload: dict) -> str:
    qp = payload.get("query_plan") or {}
    ac = qp.get("analytical_context") if isinstance(qp, dict) else {}
    if isinstance(ac, dict):
        return str(ac.get("intent") or qp.get("intent") or "")
    return str(qp.get("intent") or "")


def classify(payload: dict | None, err: str | None) -> str:
    if err:
        return "FAIL"
    if not payload:
        return "FAIL"
    status = str(payload.get("answer_status") or "").upper()
    pipeline = str(payload.get("pipeline") or payload.get("sql_generation_method") or "")
    reason = str((payload.get("meta") or {}).get("reason") or payload.get("summary") or "")
    rows = len(payload.get("data") or [])
    ql = (payload.get("meta") or {}).get("requested") or ""

    if "vbrk" in reason.lower() and "does not exist" in reason.lower():
        return "FAIL (deploy)"
    if status == "CANNOT_ANSWER" and ("logistics" in reason.lower() or "net profit" in reason.lower() or "operating" in reason.lower()):
        return "DATA GAP"
    if status == "CANNOT_ANSWER":
        return "FAIL"
    if status == "SUCCESS" and pipeline == "deep_multidim" and rows > 0:
        return "PASS"
    if status == "SUCCESS" and pipeline == "deep_multidim" and rows == 0:
        return "PARTIAL (empty)"
    if status == "SUCCESS":
        return "PARTIAL"
    return "FAIL"


def run_list(title: str, questions: list[str], carry: bool = True) -> list[dict]:
    print(f"\n=== {title} ===")
    print(f"API: {API}\n")
    results = []
    ctx = None
    for i, q in enumerate(questions, 1):
        payload, sec, err = post(q, ctx if carry else None)
        status_label = classify(payload, err)
        pipeline = (payload or {}).get("pipeline") or (payload or {}).get("sql_generation_method") or ""
        intent = intent_of(payload) if payload else ""
        rows = len((payload or {}).get("data") or [])
        row = {
            "i": i,
            "question": q,
            "sec": round(sec, 2),
            "status_label": status_label,
            "answer_status": (payload or {}).get("answer_status"),
            "pipeline": pipeline,
            "intent": intent,
            "rows": rows,
            "error": err,
        }
        if payload and rows:
            top = payload["data"][0]
            row["top_keys"] = list(top.keys())[:8]
            row["sample"] = {
                k: top.get(k)
                for k in ("product", "product_name", "customer_name", "industry", "country", "gross_profit", "gross_margin_pct", "revenue", "cogs")
                if k in top
            }
        results.append(row)
        print(f"[{i:02d}] {status_label:16s} {sec:5.2f}s | {pipeline:16s} | rows={rows:3d} | intent={intent}")
        print(f"     Q: {q}")
        if err:
            print(f"     ERR: {err[:200]}")
        elif status_label == "FAIL (deploy)":
            reason = str(((payload or {}).get("meta") or {}).get("reason") or "")[:180]
            print(f"     REASON: {reason}")
        elif row.get("sample"):
            print(f"     SAMPLE: {row['sample']}")

        if payload and carry:
            st = str(payload.get("answer_status") or "").upper()
            if st == "SUCCESS" and ((payload.get("sql") or "").strip() or rows == 0):
                # keep context on empty year compare success too
                if (payload.get("query_plan") or {}).get("analytical_context") or st == "SUCCESS":
                    ctx = ctx_from(q, payload)
            elif st == "CANNOT_ANSWER" and status_label == "DATA GAP":
                pass  # keep prior ctx
    return results


def run_local_db() -> list[dict]:
    from dotenv import load_dotenv

    load_dotenv()
    from app.database import SessionLocal
    from app.api.adaptive_query import _execute_sql
    from app.services.analytical_deep_dive import try_deep_multidim_analysis

    print("\n=== LOCAL SAP DB (direct module) ===\n")
    db = SessionLocal()
    results = []
    ctx = None
    rows_cache = None
    all_q = ANDY_QUESTIONS + CHAIN
    for i, q in enumerate(all_q, 1):
        t0 = time.perf_counter()
        payload = try_deep_multidim_analysis(q, db, _execute_sql, prior_plan=ctx, prior_rows=rows_cache)
        sec = time.perf_counter() - t0
        if not payload:
            results.append({"i": i, "question": q, "status_label": "MISS", "sec": round(sec, 2)})
            print(f"[{i:02d}] MISS           {sec:5.2f}s | {q}")
            continue
        label = classify(payload, None)
        intent = intent_of(payload)
        rows = len(payload.get("data") or [])
        results.append({
            "i": i,
            "question": q,
            "status_label": label,
            "sec": round(sec, 2),
            "pipeline": payload.get("pipeline"),
            "intent": intent,
            "rows": rows,
        })
        print(f"[{i:02d}] {label:16s} {sec:5.2f}s | {payload.get('pipeline'):16s} | rows={rows:3d} | intent={intent}")
        print(f"     Q: {q}")
        st = str(payload.get("answer_status") or "").upper()
        if st == "SUCCESS":
            ctx = payload.get("query_plan")
            if payload.get("data"):
                rows_cache = payload.get("data")
    db.close()
    return results


def main() -> int:
    print(f"VERIFY_MODE={MODE}")
    if MODE == "local":
        results = run_local_db()
    else:
        andy = run_list("ANDY EXACT QUESTIONS (chained)", ANDY_QUESTIONS, carry=True)
        chain = run_list("FULL DEEP CHAIN (chained)", CHAIN, carry=True)
        results = andy + chain

    passes = sum(1 for r in results if r.get("status_label") == "PASS")
    gaps = sum(1 for r in results if r.get("status_label") == "DATA GAP")
    fails = sum(1 for r in results if str(r.get("status_label", "")).startswith("FAIL"))
    partial = sum(1 for r in results if "PARTIAL" in str(r.get("status_label", "")))
    print(f"\nSUMMARY: PASS={passes} PARTIAL={partial} DATA_GAP={gaps} FAIL={fails} / {len(results)}")
    out = os.environ.get("VERIFY_OUT", "andy_verify_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"api": API, "mode": MODE, "results": results}, f, indent=2, default=str)
    print(f"Wrote {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
