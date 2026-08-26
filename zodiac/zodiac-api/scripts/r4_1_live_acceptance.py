"""R4-1 live production acceptance against zodiac-back."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API = "https://zodiac-back.vercel.app/api/query/adaptive"
OUT = "r4_1_live_acceptance.json"


def post(q: str, ctx=None) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {"question": q}
    if ctx:
        body["contextData"] = ctx
    t0 = time.perf_counter()
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.load(resp)
    return out, int((time.perf_counter() - t0) * 1000)


def ctx_from(q: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql", ""),
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status", ""),
        "data": (r.get("data") or [])[:20],
    }


def intent_of(r: Dict[str, Any]) -> str:
    qp = r.get("query_plan") or {}
    ac = qp.get("analytical_context") or {}
    return str(ac.get("intent") or qp.get("intent") or "")


def summarize(q: str, r: Dict[str, Any], ms: int, expected: Optional[str] = None) -> Dict[str, Any]:
    sql = r.get("sql") or ""
    su = sql.upper()
    data = r.get("data") or []
    first = data[0] if data and isinstance(data[0], dict) else {}
    periods = [
        row.get("year_month") or row.get("year_quarter")
        for row in data[:8]
        if isinstance(row, dict)
    ]
    chron_ok = None
    if periods and all(isinstance(p, str) and p for p in periods):
        chron_ok = periods == sorted(periods) or "ORDER BY" in su and (
            "YEAR_MONTH" in su or "YEAR_QUARTER" in su
        )
    banned = [t for t in ("EKPO", "VBFA", "KONV", "BSEG", "MBEW", "MARD") if t in su]
    row = {
        "question": q,
        "ms": ms,
        "status": r.get("answer_status"),
        "pipeline": r.get("pipeline") or r.get("sql_generation_method"),
        "intent": intent_of(r),
        "expected_intent": expected,
        "rows": r.get("rowCount", 0),
        "dims": (r.get("query_plan") or {}).get("analytical_context", {}).get("dimensions"),
        "metrics": (r.get("query_plan") or {}).get("analytical_context", {}).get("metrics"),
        "selected_products": (r.get("query_plan") or {}).get("analytical_context", {}).get(
            "selected_products"
        ),
        "has_substring": "SUBSTRING" in su,
        "has_cast_as_date": "AS DATE" in su,
        "has_year_month": "YEAR_MONTH" in su or "year_month" in (first or {}),
        "has_year_quarter": "YEAR_QUARTER" in su or "year_quarter" in (first or {}),
        "has_vbrp": "VBRP" in su,
        "has_vbrk": "VBRK" in su,
        "banned_joins": banned,
        "sample_periods": periods[:5],
        "sample_keys": list(first.keys())[:12] if first else [],
        "sample_row": {
            k: first.get(k)
            for k in (
                "year_month",
                "year_quarter",
                "revenue",
                "cogs",
                "gross_profit",
                "gross_margin_pct",
                "quantity",
                "avg_selling_price",
                "invoice_count",
                "currency",
            )
            if first.get(k) is not None
        },
        "sql_head": " ".join(sql.split())[:280],
        "summary_head": (r.get("summary") or "")[:180],
    }
    ok = r.get("answer_status") == "SUCCESS" and (
        expected is None or intent_of(r) == expected
    )
    if expected and expected.endswith("_gap"):
        ok = r.get("answer_status") == "CANNOT_ANSWER"
    row["result"] = "PASS" if ok else "FAIL"
    if expected and intent_of(r) != expected and r.get("answer_status") == "SUCCESS":
        row["result"] = f"FAIL(intent={intent_of(r)})"
    if r.get("answer_status") == "CANNOT_ANSWER":
        row["result"] = "DATA_GAP"
    return row


def run() -> Dict[str, Any]:
    report: Dict[str, Any] = {"api": API, "sections": {}}

    # Gate
    gate = []
    for q, exp in [
        ("Show monthly revenue.", "monthly_trend"),
        ("Show quarterly revenue.", "quarterly_trend"),
    ]:
        r, ms = post(q)
        gate.append(summarize(q, r, ms, exp))
    report["sections"]["gate"] = gate

    # Core probes
    probes = [
        ("Show monthly revenue.", "monthly_trend"),
        ("Show quarterly revenue.", "quarterly_trend"),
        ("Show monthly COGS.", "monthly_trend"),
        ("Show quarterly COGS.", "quarterly_trend"),
        ("Show monthly margins.", "monthly_trend"),
        ("Show quarterly margins.", "quarterly_trend"),
        ("Which month had the highest revenue?", "monthly_trend"),
        ("Which quarter had the highest gross profit?", "quarterly_trend"),
        ("Compare this month with last month.", "monthly_trend"),
        ("Compare this quarter with last quarter.", "quarterly_trend"),
        ("Compare 2004 and 2005 by month.", "monthly_trend"),
        ("Compare 2004 and 2005 by quarter.", "quarterly_trend"),
    ]
    probe_rows = []
    last = None
    last_q = None
    for q, exp in probes:
        ctx = ctx_from(last_q, last) if last else None
        r, ms = post(q, ctx)
        probe_rows.append(summarize(q, r, ms, exp))
        last, last_q = r, q
    report["sections"]["probes"] = probe_rows

    # Product-filtered trend chain
    chain_q = [
        ("Show the highest-profit products.", "product_profitability"),
        ("Show their monthly revenue.", "monthly_trend"),
        ("Show their quarterly revenue.", "quarterly_trend"),
        ("Compare 2004 and 2005.", None),  # may stay on quarterly or period_compare
        ("Show COGS.", None),
        ("Show margins.", None),
        ("Which quarter had the biggest decline?", "quarterly_trend"),
        ("Why?", None),
    ]
    chain_rows = []
    ctx = None
    for q, exp in chain_q:
        r, ms = post(q, ctx)
        row = summarize(q, r, ms, exp)
        ac = (r.get("query_plan") or {}).get("analytical_context") or {}
        row["products_n"] = len(ac.get("selected_products") or [])
        chain_rows.append(row)
        ctx = ctx_from(q, r)
    report["sections"]["context_chain"] = chain_rows

    # Short follow-ups after monthly revenue
    r0, _ = post("Show monthly revenue.")
    ctx = ctx_from("Show monthly revenue.", r0)
    followups = [
        ("Show COGS.", "monthly_trend"),
        ("Show margins.", "monthly_trend"),
        ("Show customers.", "customers_of_selection"),
        ("Show regions.", "country_breakdown"),
        ("Show quarterly.", "quarterly_trend"),
        ("Compare last year.", None),
        ("Which month was best?", "monthly_trend"),
        ("Which quarter was worst?", "quarterly_trend"),
        ("Why?", None),
        ("Show the components.", "profit_components"),
    ]
    fu_rows = []
    for q, exp in followups:
        r, ms = post(q, ctx)
        fu_rows.append(summarize(q, r, ms, exp))
        ctx = ctx_from(q, r)
    report["sections"]["followups"] = fu_rows

    # Empty period
    empty = []
    for q in ["Show monthly revenue for 2024.", "Show quarterly revenue for 2025."]:
        r, ms = post(q)
        row = summarize(q, r, ms, None)
        summary = (r.get("summary") or "").lower()
        empty_ok = (
            r.get("rowCount", 0) == 0
            or "no billing" in summary
            or "not available" in summary
            or "current extract" in summary
            or (r.get("meta") or {}).get("empty_period")
        )
        row["honest_empty"] = bool(empty_ok)
        row["result"] = "PASS" if empty_ok and r.get("answer_status") in {"SUCCESS", "CANNOT_ANSWER"} else "FAIL"
        empty.append(row)
    report["sections"]["empty_period"] = empty

    # Root cause
    rc = []
    r1, ms1 = post("Which month had the biggest margin decline?")
    rc.append(summarize("Which month had the biggest margin decline?", r1, ms1, "monthly_trend"))
    r2, ms2 = post("Why?", ctx_from("Which month had the biggest margin decline?", r1))
    row2 = summarize("Why?", r2, ms2, None)
    s = (r2.get("summary") or "").lower()
    row2["observed_language"] = "observed" in s or "contributor" in s
    row2["causal_claim"] = "caused the decline" in s
    rc.append(row2)
    report["sections"]["root_cause"] = rc

    # DATA GAP recovery into R4-1
    gap = []
    steps = [
        ("Show highest-profit products.", "product_profitability", "PASS"),
        ("Show logistics cost.", None, "DATA_GAP"),
        ("Show net profit.", None, "DATA_GAP"),
        ("Show COGS.", None, "PASS"),
        ("Show monthly revenue.", "monthly_trend", "PASS"),
        ("Show quarterly revenue.", "quarterly_trend", "PASS"),
    ]
    ctx = None
    for q, exp, want in steps:
        r, ms = post(q, ctx)
        row = summarize(q, r, ms, exp)
        if want == "DATA_GAP":
            row["result"] = "DATA_GAP" if r.get("answer_status") == "CANNOT_ANSWER" else "FAIL"
        elif want == "PASS":
            ok = r.get("answer_status") == "SUCCESS" and (
                exp is None or intent_of(r) == exp
            )
            row["result"] = "PASS" if ok else f"FAIL({intent_of(r)}/{r.get('answer_status')})"
        gap.append(row)
        ctx = ctx_from(q, r)
    report["sections"]["data_gap_recovery"] = gap

    # Basic GA regression
    ga = []
    for chain in [
        ["2004", "Meaning of life", "Top 5"],
        ["2004", "Meaning of life", "Show sales for 2005", "Top 3"],
    ]:
        ctx = None
        for q in chain:
            r, ms = post(q, ctx)
            intent = intent_of(r)
            hijacked = intent in {"monthly_trend", "quarterly_trend"} and q.lower() in {
                "2004",
                "meaning of life",
                "top 5",
                "top 3",
            }
            ga.append(
                {
                    "question": q,
                    "ms": ms,
                    "status": r.get("answer_status"),
                    "pipeline": r.get("pipeline"),
                    "intent": intent,
                    "hijacked_by_r4": hijacked,
                    "result": "FAIL" if hijacked else "PASS",
                }
            )
            ctx = ctx_from(q, r)
    report["sections"]["basic_ga"] = ga

    # Counts
    flat = []
    for sec, rows in report["sections"].items():
        for row in rows:
            flat.append({**row, "section": sec})
    report["counts"] = {
        "PASS": sum(1 for r in flat if r.get("result") == "PASS"),
        "DATA_GAP": sum(1 for r in flat if r.get("result") == "DATA_GAP"),
        "FAIL": sum(1 for r in flat if str(r.get("result", "")).startswith("FAIL")),
        "total": len(flat),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report["counts"], indent=2))
    for r in flat:
        mark = r.get("result")
        print(f"[{r['section']}] {mark} | {r.get('ms')}ms | {r.get('intent')} | {r.get('question')}")
    return report


if __name__ == "__main__":
    run()
