"""R4-3 live production acceptance against zodiac-back."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_http import adaptive_headers

API = "https://zodiac-back.vercel.app/api/query/adaptive"
OUT = "r4_3_live_acceptance.json"

INV_INTENTS = {
    "inventory_analysis",
    "inventory_sales_comparison",
    "inventory_risk_analysis",
    "inventory_by_plant",
    "suppliers_of_selection",
}


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
    banned = [t for t in ("EKPO", "VBFA", "KONV", "BSEG") if t in su and "VBRP" in su]
    row = {
        "question": q,
        "ms": ms,
        "status": r.get("answer_status"),
        "pipeline": r.get("pipeline") or r.get("sql_generation_method"),
        "intent": intent_of(r),
        "expected_intent": expected,
        "rows": r.get("rowCount", 0),
        "selected_products": ac.get("selected_products"),
        "has_stock_value": "stock_value" in first or "STOCK_VALUE" in su,
        "has_stock_qty": "stock_qty" in first,
        "has_revenue": "revenue" in first,
        "has_overstock": "overstock_score" in first,
        "has_undersupply": "undersupply_score" in first,
        "has_plant": "plant" in first,
        "data_availability": first.get("data_availability"),
        "join_mard_from_vbrp": 'JOIN "MARD"' in sql or "JOIN MARD" in su,
        "has_vbrp": "VBRP" in su,
        "has_mbew": "MBEW" in su,
        "has_mard": "MARD" in su,
        "sample_keys": list(first.keys())[:18] if first else [],
        "sample_row": {
            k: first.get(k)
            for k in (
                "product",
                "product_name",
                "product_group",
                "plant",
                "stock_value",
                "stock_qty",
                "revenue",
                "billed_qty",
                "overstock_score",
                "unrestricted_stock_qty",
                "data_availability",
            )
            if first.get(k) is not None
        },
        "sql_head": " ".join(sql.split())[:360],
        "summary_head": (r.get("summary") or "")[:240],
        "plan_ms": (r.get("meta") or {}).get("plan_ms") or (r.get("stage_timings") or {}).get("plan_ms"),
        "db_ms": (r.get("meta") or {}).get("db_ms") or (r.get("stage_timings") or {}).get("db_ms"),
        "transform_ms": (r.get("meta") or {}).get("transform_ms"),
        "total_ms": (r.get("meta") or {}).get("planning_ms") or ms,
    }
    ok = r.get("answer_status") == "SUCCESS" and (expected is None or intent_of(r) == expected)
    if expected and expected.endswith("_gap"):
        ok = r.get("answer_status") == "CANNOT_ANSWER"
    row["result"] = "PASS" if ok else "FAIL"
    if expected and intent_of(r) != expected and r.get("answer_status") == "SUCCESS":
        row["result"] = f"FAIL(intent={intent_of(r)})"
    if r.get("answer_status") == "CANNOT_ANSWER":
        row["result"] = "DATA_GAP" if (expected or "").endswith("_gap") or expected is None else (
            "DATA_GAP" if (expected or "").endswith("_gap") else f"FAIL(unexpected_gap intent={intent_of(r)})"
        )
        if expected and expected.endswith("_gap"):
            row["result"] = "DATA_GAP"
    if banned and r.get("answer_status") == "SUCCESS" and intent_of(r) not in INV_INTENTS:
        row["result"] = "FAIL(fanout)"
    if row.get("join_mard_from_vbrp") and "NETWR" in su and r.get("answer_status") == "SUCCESS":
        row["result"] = "FAIL(inventory_fanout)"
    return row


def run() -> Dict[str, Any]:
    report: Dict[str, Any] = {"api": API, "sections": {}}

    probes = [
        ("Show inventory.", "inventory_analysis"),
        ("Show inventory value.", "inventory_analysis"),
        ("Which products have the highest inventory?", "inventory_analysis"),
        ("Which products have the lowest inventory?", "inventory_analysis"),
        ("Show inventory versus sales.", "inventory_sales_comparison"),
        ("Which products have high inventory but low sales?", "inventory_risk_analysis"),
        ("Which products have low inventory but high sales?", "inventory_risk_analysis"),
        ("Show inventory by product group.", "inventory_sales_comparison"),
        ("Show inventory by plant.", "inventory_by_plant"),
        ("Show inventory aging.", "inventory_aging_gap"),
        ("Show inventory turnover.", "inventory_turnover_gap"),
        ("Show inventory trend.", "inventory_trend_gap"),
    ]
    probe_rows = []
    for q, exp in probes:
        r, ms = post(q)
        probe_rows.append(summarize(q, r, ms, exp))
    report["sections"]["probes"] = probe_rows

    chain = [
        ("Show the products with the highest profits.", "product_profitability"),
        ("Show their inventory.", "inventory_analysis"),
        ("Show their sales.", None),
        ("Which have high inventory but low sales?", "inventory_risk_analysis"),
        ("Show their product groups.", "product_group_breakdown"),
        ("Show their suppliers.", "suppliers_of_selection"),
        ("Show their customers.", "customers_of_selection"),
        ("Show their regions.", "country_breakdown"),
        ("Show inventory by plant.", "inventory_by_plant"),
        ("Compare their sales with last year.", None),
        ("Why?", None),
        ("Show inventory aging.", "inventory_aging_gap"),
        ("Show inventory again.", "inventory_analysis"),
    ]
    chain_rows: List[Dict[str, Any]] = []
    ctx = None
    for q, exp in chain:
        r, ms = post(q, ctx)
        chain_rows.append(summarize(q, r, ms, exp))
        ctx = ctx_from(q, r)
    report["sections"]["product_context_chain"] = chain_rows

    # DATA GAP recovery
    r0, ms0 = post("Show inventory.")
    gap_rows = [summarize("Show inventory.", r0, ms0, "inventory_analysis")]
    ctx = ctx_from("Show inventory.", r0)
    r1, ms1 = post("Show inventory aging.", ctx)
    gap_rows.append(summarize("Show inventory aging.", r1, ms1, "inventory_aging_gap"))
    ctx = ctx_from("Show inventory aging.", r1)
    r2, ms2 = post("Show sales.", ctx)
    gap_rows.append(summarize("Show sales.", r2, ms2, None))
    ctx = ctx_from("Show sales.", r2)
    r3, ms3 = post("Show inventory again.", ctx)
    gap_rows.append(summarize("Show inventory again.", r3, ms3, "inventory_analysis"))
    r4, ms4 = post("Show inventory.")
    ctx = ctx_from("Show inventory.", r4)
    gap_rows.append(summarize("Show inventory.", r4, ms4, "inventory_analysis"))
    r5, ms5 = post("Show net profit.", ctx)
    gap_rows.append(summarize("Show net profit.", r5, ms5, "net_profit_gap"))
    ctx = ctx_from("Show net profit.", r5)
    r6, ms6 = post("Show inventory.", ctx)
    gap_rows.append(summarize("Show inventory.", r6, ms6, "inventory_analysis"))
    report["sections"]["data_gap_recovery"] = gap_rows

    guards = []
    for q, exp in [
        ("Which products had the biggest margin decline?", "margin_decline_drivers"),
        ("Which month had the biggest margin decline?", "monthly_trend"),
        ("Which products grew the most?", "product_growth_decline"),
        ("Show monthly sales.", "monthly_trend"),
        ("Show quarterly sales.", "quarterly_trend"),
    ]:
        r, ms = post(q)
        guards.append(summarize(q, r, ms, exp))
    report["sections"]["regression_guards"] = guards

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
