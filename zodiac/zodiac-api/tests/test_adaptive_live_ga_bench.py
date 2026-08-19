"""
Live LLM + DB benches for adaptive query GA hardening.

Skipped unless LIVE_GA_BENCH=1 (and typically a running API + OpenAI key).
CI stays on mocked unit tests; this file fails the build when the env is set
and p95 or product-SQL flake budgets are missed.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("LIVE_GA_BENCH", "").strip().lower() not in ("1", "true", "yes", "on"),
    reason="Set LIVE_GA_BENCH=1 to run live LLM/DB adaptive benches",
)

LIVE_API = os.getenv("LIVE_GA_API", "http://127.0.0.1:8000").rstrip("/")
P95_TARGET_S = float(os.getenv("LIVE_GA_P95_SECONDS", "15"))
PRODUCT_QUESTION = os.getenv(
    "LIVE_GA_PRODUCT_QUESTION",
    "Show top products by sales",
)

BENCH_QUESTIONS = [
    "Show me highest sales for the year 2004 with customer and industry",
    "What are total sales for 2004?",
    "Show top 10 customers.",
    "five biggest customers",
    "Show sales by industry.",
    "Compare 2003 vs 2004.",
    "Show product-level sales for 2004.",
    "How many invoices per customer?",
    "Show sales for EUR currency.",
    "Top 5 customers.",
]


def _post_adaptive(question: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    import urllib.request
    import json

    body: Dict[str, Any] = {"question": question}
    if context:
        body["contextData"] = context
    req = urllib.request.Request(
        f"{LIVE_API}/api/query/adaptive",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_live_p95_latency_under_target():
    times: List[float] = []
    statuses: List[str] = []
    methods: List[str] = []
    llm_calls: List[Any] = []
    for q in BENCH_QUESTIONS:
        t0 = time.perf_counter()
        payload = _post_adaptive(q)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        statuses.append(str(payload.get("answer_status") or payload.get("type") or ""))
        methods.append(str(payload.get("sql_generation_method") or payload.get("pipeline") or ""))
        llm_calls.append(payload.get("llm_calls") or (payload.get("stage_timings") or {}).get("sql_llm_calls"))
        st = payload.get("stage_timings") or {}
        print(
            f"live_p95_row question={q!r} total_ms={elapsed*1000:.0f} "
            f"method={methods[-1]} llm={llm_calls[-1]} "
            f"schema_ms={st.get('schema')} sql_generation_ms={st.get('sql_llm')} "
            f"DB_ms={st.get('db')} summary_ms={st.get('summary')} "
            f"retry_count={st.get('sql_llm_calls') or 0} timings={st}"
        )
    times_sorted = sorted(times)
    n = len(times_sorted)
    p50 = times_sorted[n // 2]
    p95_idx = max(0, min(n - 1, int((0.95 * n) - 1e-9)))
    p95 = times_sorted[p95_idx]
    mx = times_sorted[-1]
    print(
        f"\nlive_p95 timings seconds: samples={[round(t, 2) for t in times]} "
        f"p50={p50:.2f} p95={p95:.2f} max={mx:.2f} cold={times[0]:.2f} "
        f"statuses={statuses} methods={methods} llm_calls={llm_calls}"
    )
    assert p95 < P95_TARGET_S, (
        f"p95 {p95:.1f}s exceeds {P95_TARGET_S}s; p50={p50:.1f} max={mx:.1f} "
        f"samples={[round(t, 2) for t in times]} statuses={statuses}"
    )


def test_live_product_sql_ten_times_zero_cannot_answer():
    failures = []
    times: List[float] = []
    for i in range(10):
        t0 = time.perf_counter()
        payload = _post_adaptive(PRODUCT_QUESTION)
        times.append(time.perf_counter() - t0)
        status = str(payload.get("answer_status") or "")
        if status == "CANNOT_ANSWER" or payload.get("type") == "cannot_answer":
            failures.append((i, status, (payload.get("summary") or "")[:200]))
    ts = sorted(times)
    p50 = ts[len(ts) // 2]
    p95 = ts[max(0, min(len(ts) - 1, int((0.95 * len(ts)) - 1e-9)))]
    print(
        f"\nproduct_10x min={ts[0]:.2f} p50={p50:.2f} p95={p95:.2f} max={ts[-1]:.2f} "
        f"samples={[round(t, 2) for t in times]}"
    )
    assert failures == [], f"CANNOT_ANSWER on product SQL retries: {failures}"


def test_live_six_step_followup_under_warm_latency():
    ctx: Dict[str, Any] | None = None
    steps = [
        "Show me highest sales for the year 2004 with customer and industry",
        "Only the Trading industry",
        "Now show the top 5",
        "Compare with 2003",
        "Remove the Trading filter",
        "Show invoice count instead",
    ]
    rows: List[Dict[str, Any]] = []
    for i, q in enumerate(steps):
        t0 = time.perf_counter()
        payload = _post_adaptive(q, ctx)
        elapsed = time.perf_counter() - t0
        method = str(payload.get("sql_generation_method") or payload.get("pipeline") or "")
        rec = {
            "step": i + 1,
            "question": q,
            "seconds": round(elapsed, 2),
            "method": method,
            "llm_calls": payload.get("llm_calls"),
            "status": payload.get("answer_status"),
            "rows": len(payload.get("data") or []),
            "title": ((payload.get("charts") or [{}])[0] or {}).get("title"),
        }
        rows.append(rec)
        print(f"six_step {rec}")
        if i == 0:
            assert elapsed < P95_TARGET_S, rec
        else:
            assert elapsed < P95_TARGET_S, rec
            assert method != "universal_llm", rec
        assert "CONTINUATION" not in str(rec.get("title") or "").upper()
        ctx = {
            "previousQuestion": q,
            "previousSQL": payload.get("sql") or "",
            "previousPlan": payload.get("query_plan"),
            "previousAnswerStatus": payload.get("answer_status"),
            "data": (payload.get("data") or [])[:20],
        }
    assert len(rows) == 6
