"""Extra R4-2 live probes for post-deploy acceptance (no product changes)."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

API = "https://zodiac-back.vercel.app/api/query/adaptive"
OUT = "r4_2_post_deploy_extra_probes.json"


def post(q: str, ctx=None) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {"question": q}
    if ctx:
        body["contextData"] = ctx
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.load(r)
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


def row(q: str, r: Dict[str, Any], ms: int, expected: Optional[str] = None) -> Dict[str, Any]:
    sql = r.get("sql") or ""
    su = sql.upper()
    ac = (r.get("query_plan") or {}).get("analytical_context") or {}
    first = (r.get("data") or [{}])[0] if r.get("data") else {}
    banned = [t for t in ("EKPO", "EKKO", "LFA1", "VBFA", "KONV", "BSEG") if t in su and "VBRP" in su]
    # supplier/inventory intents may include those tables intentionally
    intent = intent_of(r)
    if intent in {
        "suppliers_of_selection",
        "inventory_analysis",
        "inventory_sales_comparison",
        "inventory_risk_analysis",
        "inventory_by_plant",
    }:
        banned = []
    out = {
        "question": q,
        "ms": ms,
        "status": r.get("answer_status"),
        "pipeline": r.get("pipeline") or r.get("sql_generation_method"),
        "intent": intent,
        "expected": expected,
        "rows": r.get("rowCount"),
        "change_mode": ac.get("change_mode") or (ac.get("filters") or {}).get("change_mode"),
        "growth_metric": ac.get("growth_metric") or (ac.get("filters") or {}).get("growth_metric"),
        "growth_direction": ac.get("growth_direction") or (ac.get("filters") or {}).get("growth_direction"),
        "period_grain": (ac.get("filters") or {}).get("period_grain"),
        "selected_products_n": len(ac.get("selected_products") or []),
        "has_change_abs": "CHANGE_ABS" in su or first.get("revenue_change_abs") is not None,
        "has_change_pct": "CHANGE_PCT" in su or first.get("revenue_change_pct") is not None,
        "period_status": first.get("period_status"),
        "cast_as_date": "AS DATE" in su,
        "billing_grain": "VBRP" in su and "VBRK" in su,
        "banned_joins": banned,
        "order_by": (
            "pct"
            if "ORDER BY REVENUE_CHANGE_PCT" in su or "ORDER BY revenue_change_pct" in sql
            else (
                "abs"
                if "ORDER BY REVENUE_CHANGE_ABS" in su or "ORDER BY revenue_change_abs" in sql
                else (
                    "margin_pp"
                    if "MARGIN_CHANGE_PP" in su
                    else "other"
                )
            )
        ),
        "sql_head": " ".join(sql.split())[:260],
        "summary_head": (r.get("summary") or "")[:180],
        "observed_language": (
            "observed" in (r.get("summary") or "").lower()
            or "contributor" in (r.get("summary") or "").lower()
        ),
    }
    ok = True
    if expected and intent != expected and r.get("answer_status") == "SUCCESS":
        ok = False
    if expected and expected.endswith("_gap"):
        ok = r.get("answer_status") == "CANNOT_ANSWER"
    if banned:
        ok = False
    if r.get("answer_status") == "CANNOT_ANSWER" and expected and expected.endswith("_gap"):
        out["result"] = "DATA_GAP"
    elif ok and r.get("answer_status") == "SUCCESS":
        out["result"] = "PASS"
    elif r.get("answer_status") == "CANNOT_ANSWER":
        out["result"] = "DATA_GAP"
    else:
        out["result"] = f"FAIL(intent={intent},status={r.get('answer_status')})"
    return out


def main():
    report: Dict[str, Any] = {"api": API, "sections": {}}

    # Absolute vs percentage
    abs_pct = []
    for q, exp, want_mode in [
        ("Which products grew the fastest?", "product_growth_decline", "pct"),
        ("Which products added the most revenue?", "product_growth_decline", "absolute"),
        ("Which products increased revenue by the highest percentage?", "product_growth_decline", "pct"),
        ("Which products increased their revenue the most?", "product_growth_decline", "absolute"),
    ]:
        r, ms = post(q)
        rec = row(q, r, ms, exp)
        rec["want_mode"] = want_mode
        rec["mode_ok"] = rec.get("change_mode") == want_mode or (
            want_mode == "pct" and rec.get("order_by") == "pct"
        ) or (want_mode == "absolute" and rec.get("order_by") == "abs")
        if not rec["mode_ok"] and rec["result"] == "PASS":
            rec["result"] = f"FAIL(mode={rec.get('change_mode')},order={rec.get('order_by')})"
        abs_pct.append(rec)
    report["sections"]["abs_vs_pct"] = abs_pct

    # Metric variants
    metrics = []
    for q, exp in [
        ("Which products grew the most in revenue?", "product_growth_decline"),
        ("Which products declined the most in revenue?", "product_growth_decline"),
        ("Which products had the biggest gross profit growth?", "product_growth_decline"),
        ("Which products had the biggest gross profit decline?", "product_growth_decline"),
        ("Which products improved their margins?", "product_growth_decline"),
        ("Which products had the biggest margin decline?", "margin_decline_drivers"),  # R3 preserve
        ("Show products whose margins declined.", "product_growth_decline"),
        ("Which products grew fastest by quantity?", "product_growth_decline"),
        ("Which products had the biggest quantity decline?", "product_growth_decline"),
        ("Which products had the biggest ASP increase?", "product_growth_decline"),
        ("Which products had the biggest ASP decline?", "product_growth_decline"),
    ]:
        r, ms = post(q)
        metrics.append(row(q, r, ms, exp))
    report["sections"]["metrics"] = metrics

    # Time
    time_rows = []
    for q, exp in [
        ("Which products grew month over month?", "product_growth_decline"),
        ("Which products declined month over month?", "product_growth_decline"),
        ("Which products grew quarter over quarter?", "product_growth_decline"),
        ("Which products declined quarter over quarter?", "product_growth_decline"),
        ("Which products grew year over year?", "product_growth_decline"),
        ("Which products declined year over year?", "product_growth_decline"),
        ("Which products grew the most from 2004 to 2005?", "product_growth_decline"),
    ]:
        r, ms = post(q)
        rec = row(q, r, ms, exp)
        sql = r.get("sql") or ""
        rec["has_lag"] = "LAG(" in sql.upper()
        rec["has_yyyy_mm"] = "YYYY-MM" in sql or "-" in sql
        time_rows.append(rec)
    report["sections"]["time"] = time_rows

    # Empty period
    empty = []
    for q in ["Which products grew from 2004 to 2099?", "Which products grew in 2099?"]:
        r, ms = post(q)
        rec = row(q, r, ms, None)
        summary = (r.get("summary") or "").lower()
        honest = (
            r.get("rowCount", 0) == 0
            or "no billing" in summary
            or "not available" in summary
            or "current extract" in summary
            or "2099" in summary
            or (r.get("meta") or {}).get("empty_period")
        )
        rec["honest_empty"] = bool(honest)
        rec["result"] = "PASS" if honest and r.get("answer_status") in {"SUCCESS", "CANNOT_ANSWER"} else "FAIL"
        empty.append(rec)
    report["sections"]["empty_period"] = empty

    # Basic GA regression
    basic = []
    ctx = None
    for q in ["2004", "Meaning of life", "Top 5"]:
        r, ms = post(q, ctx)
        rec = row(q, r, ms, None)
        # Must NOT be product_growth_decline hijack for these
        if intent_of(r) == "product_growth_decline":
            rec["result"] = "FAIL(hijack)"
        else:
            rec["result"] = "PASS"
        basic.append(rec)
        ctx = ctx_from(q, r)
    report["sections"]["basic_ga"] = basic

    # Growth driver mini-chain
    chain = []
    ctx = None
    for q, exp in [
        ("Which products declined the most?", "product_growth_decline"),
        ("Why?", "product_growth_decline"),
        ("What drove the decline?", "product_growth_decline"),
        ("Show their customers.", "customers_of_selection"),
        ("Show their ASP.", None),
    ]:
        r, ms = post(q, ctx)
        rec = row(q, r, ms, exp)
        chain.append(rec)
        ctx = ctx_from(q, r)
    report["sections"]["driver_chain"] = chain

    # DATA GAP recovery
    gap = []
    r0, ms0 = post("Which products grew the most?")
    gap.append(row("Which products grew the most?", r0, ms0, "product_growth_decline"))
    ctx = ctx_from("Which products grew the most?", r0)
    for q, exp in [
        ("Show logistics cost.", "logistics_cost_gap"),
        ("Show net profit.", "net_profit_gap"),
        ("Show revenue growth.", None),
        ("Show COGS.", None),
        ("Show customers.", "customers_of_selection"),
    ]:
        r, ms = post(q, ctx)
        gap.append(row(q, r, ms, exp))
        ctx = ctx_from(q, r)
    report["sections"]["data_gap_recovery"] = gap

    # Product groups after growth (abce857 fingerprint)
    r0, ms0 = post("Which products grew the most?")
    ctx = ctx_from("Which products grew the most?", r0)
    r1, ms1 = post("Show their product groups.", ctx)
    report["sections"]["product_group_followup"] = [
        row("Which products grew the most?", r0, ms0, "product_growth_decline"),
        row("Show their product groups.", r1, ms1, "product_group_breakdown"),
    ]

    all_rows = []
    for sec in report["sections"].values():
        all_rows.extend(sec)
    report["totals"] = {
        "total": len(all_rows),
        "PASS": sum(1 for x in all_rows if x.get("result") == "PASS"),
        "DATA_GAP": sum(1 for x in all_rows if x.get("result") == "DATA_GAP"),
        "FAIL": sum(1 for x in all_rows if str(x.get("result", "")).startswith("FAIL")),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report["totals"], indent=2))
    for sec, rows in report["sections"].items():
        fails = [x for x in rows if str(x.get("result", "")).startswith("FAIL")]
        if fails:
            print("FAIL section", sec)
            for x in fails:
                print(" ", x.get("result"), "|", x.get("intent"), "|", x.get("question"))


if __name__ == "__main__":
    main()
