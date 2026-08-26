"""
R3 production performance harness against zodiac-back.

Measures warm-path percentiles and a cold/warm pair. Does not modify production.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API = "https://zodiac-back.vercel.app/api/query/adaptive"
N_WARM = 12  # practical sample; raise to 20 if latency budget allows


def pct(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def post(q: str, ctx: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {"question": q}
    if ctx:
        body["contextData"] = ctx
    data = json.dumps(body).encode()
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.load(resp)
    ms = int((time.perf_counter() - t0) * 1000)
    return out, ms


def ctx_from(q: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql", ""),
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status", ""),
        "data": (r.get("data") or [])[:20],
    }


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = sorted(s["total_ms"] for s in samples)
    plan = [s["plan_ms"] for s in samples if s.get("plan_ms") is not None]
    qcount = [s["query_count"] for s in samples if s.get("query_count") is not None]
    return {
        "n": len(samples),
        "p50": int(pct(totals, 50)),
        "p75": int(pct(totals, 75)),
        "p90": int(pct(totals, 90)),
        "p95": int(pct(totals, 95)),
        "p99": int(pct(totals, 99)),
        "max": int(max(totals)) if totals else 0,
        "min": int(min(totals)) if totals else 0,
        "mean": int(statistics.mean(totals)) if totals else 0,
        "plan_ms_median": int(statistics.median(plan)) if plan else None,
        "query_count_median": statistics.median(qcount) if qcount else None,
        "pipeline": samples[0].get("pipeline") if samples else None,
        "intent": samples[0].get("intent") if samples else None,
    }


def one(q: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r, ms = post(q, ctx)
    meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
    ac = (r.get("query_plan") or {}).get("analytical_context") or {}
    st = r.get("stage_timings") if isinstance(r.get("stage_timings"), dict) else {}
    return {
        "total_ms": ms,
        "status": r.get("answer_status"),
        "pipeline": r.get("pipeline"),
        "intent": ac.get("intent") or (r.get("query_plan") or {}).get("intent"),
        "plan_ms": meta.get("planning_ms") or st.get("deep_analysis_ms") or st.get("planner"),
        "query_count": meta.get("query_count"),
        "stage_timings": st,
        "rows": r.get("rowCount"),
        "response": r,
    }


def main() -> int:
    results: Dict[str, Any] = {"api": API, "n_warm": N_WARM, "scenarios": {}, "cold_warm": {}}

    # Seed context for follow-up scenarios
    seed, seed_ms = post("Show me the products with the highest profits.")
    seed_ctx = ctx_from("Show me the products with the highest profits.", seed)
    results["seed_ms"] = seed_ms

    scenarios: List[Tuple[str, str, Optional[Dict[str, Any]]]] = [
        ("basic_sales", "Show sales for 2005", None),
        ("highest_profit", "Show me the products with the highest profits.", None),
        ("cogs", "Show COGS.", seed_ctx),
        ("lowest_margin", "Show the lowest margin products.", None),
        ("product_customer", "Show their customers.", seed_ctx),
        ("product_industry", "Break that down by industry.", seed_ctx),
        ("supplier", "Show their suppliers.", seed_ctx),
        ("product_group", "Break them down by product group.", seed_ctx),
        ("asp", "Show the average selling price.", seed_ctx),
        ("inventory", "Show the inventory.", seed_ctx),
        ("purchase_history", "How long have they been buying them?", seed_ctx),
        ("root_cause", "Why did those margins decline?", seed_ctx),
        ("year_compare", "Compare 2004 and 2005.", seed_ctx),
        ("full_followup_regions", "Show the regions.", seed_ctx),
    ]

    for name, q, ctx in scenarios:
        print(f"=== {name} ({N_WARM} warm) ===", flush=True)
        samples = []
        # discard one warm-up
        try:
            one(q, ctx)
        except Exception as e:
            print(f"  warmup failed: {e}", flush=True)
        for i in range(N_WARM):
            try:
                s = one(q, ctx)
                samples.append({k: v for k, v in s.items() if k != "response"})
                print(
                    f"  [{i+1}/{N_WARM}] {s['total_ms']}ms pipe={s['pipeline']} "
                    f"intent={s['intent']} qcount={s['query_count']} plan_ms={s['plan_ms']}",
                    flush=True,
                )
                time.sleep(0.15)
            except Exception as e:
                print(f"  [{i+1}/{N_WARM}] ERROR {e}", flush=True)
        results["scenarios"][name] = {
            "question": q,
            "summary": summarize(samples),
            "samples": samples,
        }

    # Cold / warm pairs for slow scenarios
    print("=== cold/warm pairs ===", flush=True)
    for name, q in [
        ("purchase_history", "How long have they been buying them?"),
        ("highest_profit", "Show me the products with the highest profits."),
        ("year_compare", "Compare 2004 and 2005."),
    ]:
        pair = []
        for label in ("coldish_1", "warm_1", "gap_then_2", "warm_2"):
            if label == "gap_then_2":
                print("  sleeping 45s to encourage cold...", flush=True)
                time.sleep(45)
                continue
            ctx = seed_ctx if name != "highest_profit" else None
            s = one(q, ctx)
            pair.append({"label": label, **{k: v for k, v in s.items() if k != "response"}})
            print(f"  {name}/{label}: {s['total_ms']}ms qcount={s['query_count']}", flush=True)
            time.sleep(0.5)
        results["cold_warm"][name] = pair

    out_path = "r3_perf_baseline.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out_path}", flush=True)

    # Print summary table
    print("\nSCENARIO SUMMARY")
    print(f"{'scenario':<22} {'p50':>6} {'p95':>6} {'p99':>6} {'max':>6} {'q#':>4} {'plan':>6}")
    for name, block in results["scenarios"].items():
        s = block["summary"]
        print(
            f"{name:<22} {s['p50']:>6} {s['p95']:>6} {s['p99']:>6} {s['max']:>6} "
            f"{str(s['query_count_median'] or '-'):>4} {str(s['plan_ms_median'] or '-'):>6}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
