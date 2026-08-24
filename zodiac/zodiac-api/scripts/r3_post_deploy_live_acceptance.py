"""R3 post-deployment live acceptance against zodiac-back."""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API = "https://zodiac-back.vercel.app/api/query/adaptive"


def post(q: str, ctx=None) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {"question": q}
    if ctx:
        body["contextData"] = ctx
    data = json.dumps(body).encode()
    t0 = time.perf_counter()
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
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


def intent_of(r: Dict[str, Any]) -> str:
    qp = r.get("query_plan") or {}
    ac = qp.get("analytical_context") or {}
    return str(ac.get("intent") or qp.get("intent") or "")


def classify(label: str, r: Dict[str, Any], expected_intents: Optional[List[str]] = None) -> str:
    status = r.get("answer_status", "")
    pipe = r.get("pipeline", "")
    intent = intent_of(r)
    if status == "CANNOT_ANSWER":
        return "DATA_GAP"
    if status == "SUCCESS" and pipe == "deep_multidim":
        if expected_intents and intent not in expected_intents:
            return f"PARTIAL(intent={intent})"
        return "PASS"
    if status == "CLARIFICATION":
        return "FAIL(CLARIFICATION)"
    return f"FAIL({status}/{pipe})"


def run_chain(steps: List[str], start_ctx=None) -> List[Dict[str, Any]]:
    ctx = start_ctx
    rows = []
    for q in steps:
        r, ms = post(q, ctx)
        intent = intent_of(r)
        sql = (r.get("sql") or "").upper()
        row = {
            "question": q,
            "ms": ms,
            "status": r.get("answer_status"),
            "pipe": r.get("pipeline"),
            "intent": intent,
            "rows": r.get("rowCount", 0),
            "has_ekpo": "EKPO" in sql,
            "has_matkl": "MATKL" in sql,
            "has_mbew": "MBEW" in sql,
            "has_avg_selling_price": bool(r.get("data") and isinstance(r["data"][0], dict) and "avg_selling_price" in r["data"][0]),
        }
        rows.append(row)
        ctx = ctx_from(q, r)
    return rows


def main() -> int:
    results: List[Dict[str, Any]] = []
    latencies: List[int] = []

    # Phase 4: baseline chain
    baseline = [
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
    chain = run_chain(baseline)
    for i, row in enumerate(chain, 1):
        exp = "DATA_GAP" if i in (15, 16) else "PASS"
        got = classify("", {"answer_status": row["status"], "pipeline": row["pipe"]})
        results.append({"phase": "baseline_chain", "turn": i, **row, "expected": exp, "result": got})
        latencies.append(row["ms"])

    # Phase 5: R3 dimensions chain
    r3 = [
        "Show me the products with the highest profits.",
        "Show their suppliers.",
        "Show their purchase history.",
        "Break the products down by product group.",
        "Show the average selling price.",
        "Show the inventory.",
        "Which products have the highest inventory?",
        "Which suppliers are associated with these products?",
        "Which products have increasing purchase costs?",
        "Why are their margins declining?",
    ]
    r3_rows = run_chain(r3)
    r3_expected = {
        1: ["product_profitability"],
        2: ["suppliers_of_selection"],
        3: ["purchase_history"],
        4: ["product_group_breakdown"],
        5: ["product_profitability", "margin_by_product", "cogs_by_product", "dimensional_extend"],
        6: ["inventory_analysis"],
        7: ["inventory_analysis"],
        8: ["suppliers_of_selection"],
        9: ["period_compare_selection", "margin_decline_drivers", "dimensional_extend"],
        10: ["margin_decline_drivers"],
    }
    for i, row in enumerate(r3_rows, 1):
        got = classify("", {"answer_status": row["status"], "pipeline": row["pipe"]}, r3_expected.get(i))
        results.append({"phase": "r3_chain", "turn": i, **row, "expected_intents": r3_expected.get(i), "result": got})
        latencies.append(row["ms"])

    # Phase 6: supplier profit safety
    r, ms = post("Which suppliers generated the most profit?")
    results.append({
        "phase": "supplier_profit_safety",
        "question": "Which suppliers generated the most profit?",
        "ms": ms,
        "status": r.get("answer_status"),
        "intent": intent_of(r),
        "result": "PASS" if r.get("answer_status") in {"CANNOT_ANSWER", "CLARIFICATION"} or "purchase" in (r.get("summary") or "").lower() or intent_of(r) == "suppliers_of_selection" else "FAIL(false supplier profit)",
    })

    # Phase 11: data gap recovery
    dg_chain = run_chain([
        "Show me the highest-profit products.",
        "Show logistics cost.",
        "Show net profit.",
        "Show COGS.",
        "Show their customers.",
    ])
    dg_exp = ["PASS", "DATA_GAP", "DATA_GAP", "PASS", "PASS"]
    for i, row in enumerate(dg_chain, 1):
        got = classify("", {"answer_status": row["status"], "pipeline": row["pipe"]})
        results.append({"phase": "data_gap_recovery", "turn": i, **row, "expected": dg_exp[i-1], "result": got})

    # Phase 13: new question reset
    reset = run_chain([
        "Show the highest-profit products.",
        "Show their customers.",
        "What were total sales in 2010?",
        "Show COGS.",
    ])
    for i, row in enumerate(reset, 1):
        results.append({"phase": "new_question_reset", "turn": i, **row})

    # Phase 12: short follow-ups
    ctx = None
    r0, _ = post("Show me the products with the highest profits.")
    ctx = ctx_from("Show me the products with the highest profits.", r0)
    shorts = [
        "Show COGS.", "Show cost.", "Show margins.", "Show customers.", "Show industries.",
        "Show regions.", "Show suppliers.", "Show product groups.", "Show inventory.",
        "Show purchase history.", "Show ASP.", "Compare last year.", "Break that down.",
        "Why?", "What changed?", "Show the components.", "Show the process.",
    ]
    short_pass = 0
    for q in shorts:
        r, ms = post(q, ctx)
        ok = r.get("answer_status") in {"SUCCESS", "CANNOT_ANSWER"} and r.get("pipeline") == "deep_multidim"
        if ok:
            short_pass += 1
        results.append({
            "phase": "short_followup",
            "question": q,
            "ms": ms,
            "status": r.get("answer_status"),
            "intent": intent_of(r),
            "result": "PASS" if ok else "FAIL",
        })
        latencies.append(ms)

    # Accuracy spot-check
    top = r0.get("data", [{}])[0] if r0.get("data") else {}
    results.append({
        "phase": "accuracy",
        "product": top.get("product"),
        "revenue": top.get("revenue"),
        "cogs": top.get("cogs"),
        "gross_profit": top.get("gross_profit"),
        "margin": top.get("gross_margin_pct"),
    })

    # Summary
    baseline_pass = sum(1 for x in results if x.get("phase") == "baseline_chain" and str(x.get("result", "")).startswith("PASS"))
    baseline_gap = sum(1 for x in results if x.get("phase") == "baseline_chain" and x.get("result") == "DATA_GAP")
    baseline_fail = sum(1 for x in results if x.get("phase") == "baseline_chain" and str(x.get("result", "")).startswith("FAIL"))
    r3_supplier = next((x for x in results if x.get("phase") == "r3_chain" and x.get("turn") == 2), {})
    r3_pg = next((x for x in results if x.get("phase") == "r3_chain" and x.get("turn") == 4), {})
    r3_deployed = r3_supplier.get("intent") == "suppliers_of_selection" and r3_pg.get("intent") == "product_group_breakdown"

    summary = {
        "baseline_pass": baseline_pass,
        "baseline_data_gap": baseline_gap,
        "baseline_fail": baseline_fail,
        "short_followup_pass": short_pass,
        "short_followup_total": len(shorts),
        "r3_deployed_evidence": r3_deployed,
        "r3_supplier_intent": r3_supplier.get("intent"),
        "r3_product_group_intent": r3_pg.get("intent"),
        "r3_supplier_has_ekpo": r3_supplier.get("has_ekpo"),
        "r3_product_group_has_matkl": r3_pg.get("has_matkl"),
        "perf_p50_ms": int(statistics.median(latencies)) if latencies else 0,
        "perf_p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
        "perf_max_ms": max(latencies) if latencies else 0,
    }

    out = {"summary": summary, "results": results}
    path = "r3_post_deploy_live_results.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {path}")
    return 0 if baseline_fail == 0 and baseline_pass >= 15 else 1


if __name__ == "__main__":
    sys.exit(main())
