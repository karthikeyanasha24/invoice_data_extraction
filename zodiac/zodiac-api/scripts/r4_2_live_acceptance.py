"""R4-2 live production acceptance against zodiac-back."""
from __future__ import annotations

from pathlib import Path
import sys
import json
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_http import adaptive_headers

API = "https://zodiac-back.vercel.app/api/query/adaptive"
OUT = "r4_2_live_acceptance.json"


def post(q: str, ctx=None) -> Tuple[Dict[str, Any], int]:
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
    ac = (r.get("query_plan") or {}).get("analytical_context") or {}
    banned = [t for t in ("EKPO", "VBFA", "KONV", "BSEG", "MBEW", "MARD") if t in su]
    row = {
        "question": q,
        "ms": ms,
        "status": r.get("answer_status"),
        "pipeline": r.get("pipeline") or r.get("sql_generation_method"),
        "intent": intent_of(r),
        "expected_intent": expected,
        "rows": r.get("rowCount", 0),
        "growth_metric": ac.get("growth_metric") or (ac.get("filters") or {}).get("growth_metric"),
        "growth_direction": ac.get("growth_direction") or (ac.get("filters") or {}).get("growth_direction"),
        "change_mode": ac.get("change_mode") or (ac.get("filters") or {}).get("change_mode"),
        "selected_products": ac.get("selected_products"),
        "has_change_abs": "CHANGE_ABS" in su or "revenue_change_abs" in (first or {}),
        "has_change_pct": "CHANGE_PCT" in su or "revenue_change_pct" in (first or {}),
        "has_period_status": "PERIOD_STATUS" in su or "period_status" in (first or {}),
        "has_vbrp": "VBRP" in su,
        "has_vbrk": "VBRK" in su,
        "banned_joins": banned,
        "sample_keys": list(first.keys())[:16] if first else [],
        "sample_row": {
            k: first.get(k)
            for k in (
                "product",
                "product_name",
                "previous_year",
                "current_year",
                "revenue_prev",
                "revenue_curr",
                "revenue_change_abs",
                "revenue_change_pct",
                "margin_change_pp",
                "period_status",
                "currency",
            )
            if first.get(k) is not None
        },
        "sql_head": " ".join(sql.split())[:320],
        "summary_head": (r.get("summary") or "")[:200],
        "observed_language": (
            "observed" in (r.get("summary") or "").lower()
            or "contributor" in (r.get("summary") or "").lower()
        ),
    }
    ok = r.get("answer_status") == "SUCCESS" and (expected is None or intent_of(r) == expected)
    if expected and expected.endswith("_gap"):
        ok = r.get("answer_status") == "CANNOT_ANSWER"
    row["result"] = "PASS" if ok else "FAIL"
    if expected and intent_of(r) != expected and r.get("answer_status") == "SUCCESS":
        row["result"] = f"FAIL(intent={intent_of(r)})"
    if r.get("answer_status") == "CANNOT_ANSWER":
        row["result"] = "DATA_GAP"
    if banned and r.get("answer_status") == "SUCCESS":
        # Supplier / inventory intents intentionally use non-billing joins.
        if intent_of(r) not in {
            "suppliers_of_selection",
            "inventory_analysis",
            "inventory_sales_comparison",
            "inventory_risk_analysis",
            "inventory_by_plant",
        }:
            row["result"] = "FAIL(fanout)"
    return row


def run() -> Dict[str, Any]:
    report: Dict[str, Any] = {"api": API, "sections": {}}

    probes = [
        ("Which products grew the most?", "product_growth_decline"),
        ("Which products declined the most?", "product_growth_decline"),
        ("Which products had the highest revenue growth?", "product_growth_decline"),
        ("Which products had the highest gross profit growth?", "product_growth_decline"),
        ("Which products grew the fastest?", "product_growth_decline"),
        ("Which products increased their revenue the most?", "product_growth_decline"),
        ("Which products grew the most from 2004 to 2005?", "product_growth_decline"),
        ("Which products grew month over month?", "product_growth_decline"),
        ("Which products declined quarter over quarter?", "product_growth_decline"),
        ("Show products whose margins improved.", "product_growth_decline"),
        ("Show products whose margins declined.", "product_growth_decline"),
        ("Which products had the biggest ASP increase?", "product_growth_decline"),
        ("Which products grew fastest by volume?", "product_growth_decline"),
    ]
    probe_rows = []
    for q, exp in probes:
        r, ms = post(q)
        probe_rows.append(summarize(q, r, ms, exp))
    report["sections"]["probes"] = probe_rows

    # Multi-turn growth chain
    chain = [
        ("Which products grew the most?", "product_growth_decline"),
        ("Show their customers.", "customers_of_selection"),
        ("Break them down by industry.", "industry_breakdown"),
        ("Show their regions.", "country_breakdown"),
        ("Compare their growth with the previous year.", None),
        ("Show their ASP.", None),
        ("Show their COGS.", None),
        ("Which of them had the biggest margin improvement?", "product_growth_decline"),
        ("Which products declined?", "product_growth_decline"),
        ("Why did those products decline?", "product_growth_decline"),
        ("Show the quantity change.", None),
        ("Show their product groups.", "product_group_breakdown"),
        ("Show their suppliers.", "suppliers_of_selection"),
        ("Show their inventory.", "inventory_analysis"),
    ]
    chain_rows: List[Dict[str, Any]] = []
    ctx = None
    for q, exp in chain:
        r, ms = post(q, ctx)
        chain_rows.append(summarize(q, r, ms, exp))
        ctx = ctx_from(q, r)
    report["sections"]["growth_chain"] = chain_rows

    # Decline chain
    dchain = [
        ("Which products declined the most?", "product_growth_decline"),
        ("Why?", "product_growth_decline"),
        ("Show their customers.", "customers_of_selection"),
        ("Show their ASP.", None),
        ("Show their quantity.", None),
        ("Show COGS.", None),
        ("Show margins.", None),
    ]
    drows = []
    ctx = None
    for q, exp in dchain:
        r, ms = post(q, ctx)
        drows.append(summarize(q, r, ms, exp))
        ctx = ctx_from(q, r)
    report["sections"]["decline_chain"] = drows

    # DATA GAP recovery
    r0, ms0 = post("Which products grew the most?")
    gap_rows = [summarize("Which products grew the most?", r0, ms0, "product_growth_decline")]
    ctx = ctx_from("Which products grew the most?", r0)
    r1, ms1 = post("Show their logistics cost.", ctx)
    gap_rows.append(summarize("Show their logistics cost.", r1, ms1, "logistics_cost_gap"))
    ctx = ctx_from("Show their logistics cost.", r1)
    r2, ms2 = post("Show their revenue growth.", ctx)
    gap_rows.append(summarize("Show their revenue growth.", r2, ms2, None))
    report["sections"]["data_gap_recovery"] = gap_rows

    # R3 / R4-1 non-regression fingerprints
    guards = []
    for q, exp in [
        ("Which products had the biggest margin decline?", "margin_decline_drivers"),
        ("Which month had the biggest margin decline?", "monthly_trend"),
        ("Show monthly sales.", "monthly_trend"),
        ("Show quarterly sales.", "quarterly_trend"),
    ]:
        r, ms = post(q)
        guards.append(summarize(q, r, ms, exp))
    report["sections"]["regression_guards"] = guards

    # Totals
    all_rows: List[Dict[str, Any]] = []
    for sec in report["sections"].values():
        all_rows.extend(sec)
    pass_n = sum(1 for x in all_rows if x.get("result") == "PASS")
    gap_n = sum(1 for x in all_rows if x.get("result") == "DATA_GAP")
    fail_n = sum(1 for x in all_rows if str(x.get("result", "")).startswith("FAIL"))
    report["totals"] = {
        "total": len(all_rows),
        "PASS": pass_n,
        "DATA_GAP": gap_n,
        "FAIL": fail_n,
        "latencies_ms": sorted(x.get("ms") or 0 for x in all_rows),
    }
    lats = report["totals"]["latencies_ms"]
    if lats:
        def pct(p: float) -> int:
            i = min(len(lats) - 1, max(0, int(round((p / 100.0) * (len(lats) - 1)))))
            return int(lats[i])

        report["totals"]["P50"] = pct(50)
        report["totals"]["P95"] = pct(95)
        report["totals"]["P99"] = pct(99)
        report["totals"]["Max"] = max(lats)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report["totals"], indent=2))
    return report


if __name__ == "__main__":
    run()
