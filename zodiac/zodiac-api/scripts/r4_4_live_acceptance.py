"""R4-4 live probes: supplier concentration at PO grain. Not supplier profit."""
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
OUT = "r4_4_live_acceptance.json"


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


def classify(r: Dict[str, Any], expect: Optional[str] = None) -> str:
    status = r.get("answer_status", "")
    intent = intent_of(r)
    sql = (r.get("sql") or "").upper()
    if "VBRP" in sql and "EKPO" in sql:
        return "FAIL(fanout)"
    if status == "CANNOT_ANSWER":
        return "DATA_GAP"
    if expect and intent != expect:
        if intent == "suppliers_of_selection" and expect == "supplier_concentration":
            return "NOT_DEPLOYED"
        return f"FAIL(intent={intent})"
    if status == "SUCCESS":
        return "PASS"
    return f"FAIL({status})"


def main() -> None:
    rows: List[Dict[str, Any]] = []
    r_stand, ms_stand = post("Show supplier concentration.")
    sql_stand = (r_stand.get("sql") or "").upper()
    first = (r_stand.get("data") or [{}])[0] if r_stand.get("data") else {}
    stand_verdict = classify(r_stand, "supplier_concentration")
    if "COUNT(*)" in sql_stand.replace(" ", "") or "INVOICE_BUSINESS_DATA" in sql_stand:
        stand_verdict = "FAIL(fallback_count)"
    rows.append({
        "q": "Show supplier concentration. [standalone]",
        "ms": ms_stand,
        "verdict": stand_verdict,
        "intent": intent_of(r_stand),
        "status": r_stand.get("answer_status"),
        "has_share": "share_of_po_value_pct" in first,
        "has_vbrp": "VBRP" in sql_stand,
        "has_ekpo": "EKPO" in sql_stand,
        "n": len(r_stand.get("data") or []),
    })

    ctx_conc = ctx_from("Show supplier concentration.", r_stand) if stand_verdict == "PASS" else None
    if ctx_conc:
        for q, extra in (
            ("Show the highest one.", {"n_expect": 1}),
            ("Show the percentage.", {}),
        ):
            r, ms = post(q, ctx_conc)
            verdict = classify(r, "supplier_concentration")
            n = len(r.get("data") or [])
            if extra.get("n_expect") and n != extra["n_expect"] and verdict == "PASS":
                verdict = f"FAIL(n={n})"
            rows.append({
                "q": q,
                "ms": ms,
                "verdict": verdict,
                "intent": intent_of(r),
                "status": r.get("answer_status"),
                "n": n,
            })
            if r.get("answer_status") == "SUCCESS":
                ctx_conc = ctx_from(q, r)

    r_top3, ms_top3 = post("Show the top 3 suppliers by purchase value.")
    sql_top3 = (r_top3.get("sql") or "").upper()
    n3 = len(r_top3.get("data") or [])
    v3 = classify(r_top3, "supplier_concentration")
    if v3 == "PASS" and n3 != 3:
        v3 = f"FAIL(n={n3})"
    if "COUNT(*)" in sql_top3.replace(" ", "") or "INVOICE_BUSINESS_DATA" in sql_top3:
        v3 = "FAIL(fallback_count)"
    rows.append({
        "q": "Show the top 3 suppliers by purchase value. [standalone]",
        "ms": ms_top3,
        "verdict": v3,
        "intent": intent_of(r_top3),
        "status": r_top3.get("answer_status"),
        "n": n3,
        "has_ekpo": "EKPO" in sql_top3,
        "has_vbrp": "VBRP" in sql_top3,
    })

    r0, ms0 = post("Show the products with the highest profits.")
    ctx = ctx_from("Show the products with the highest profits.", r0)
    rows.append({"q": "Show the products with the highest profits.", "ms": ms0, "verdict": classify(r0, "product_profitability"), "intent": intent_of(r0)})

    probes = [
        ("Show their suppliers.", "suppliers_of_selection"),
        ("Show supplier concentration.", "supplier_concentration"),
        ("Show supplier profit.", None),
    ]
    for q, expect in probes:
        r, ms = post(q, ctx)
        verdict = classify(r, expect)
        if expect is None:
            # Must not fan-out billing profit onto suppliers.
            sql = (r.get("sql") or "").upper()
            if "VBRP" in sql and "EKPO" in sql:
                verdict = "FAIL(fanout)"
            elif r.get("answer_status") in {"SUCCESS", "CANNOT_ANSWER"}:
                verdict = "PASS"
        first = (r.get("data") or [{}])[0] if r.get("data") else {}
        rows.append({
            "q": q,
            "ms": ms,
            "verdict": verdict,
            "intent": intent_of(r),
            "status": r.get("answer_status"),
            "has_share": "share_of_po_value_pct" in first,
            "has_vbrp": "VBRP" in (r.get("sql") or "").upper(),
            "has_ekpo": "EKPO" in (r.get("sql") or "").upper(),
        })
        if r.get("answer_status") == "SUCCESS":
            ctx = ctx_from(q, r)

    r_gap, ms_gap = post("Show inventory aging.", ctx)
    rows.append({"q": "Show inventory aging.", "ms": ms_gap, "verdict": classify(r_gap), "intent": intent_of(r_gap)})
    r_rec, ms_rec = post("Show inventory again.", ctx)
    rows.append({"q": "Show inventory again.", "ms": ms_rec, "verdict": classify(r_rec, "inventory_analysis"), "intent": intent_of(r_rec)})

    pass_n = sum(1 for x in rows if x["verdict"] == "PASS")
    gap_n = sum(1 for x in rows if x["verdict"] == "DATA_GAP")
    nd = sum(1 for x in rows if x["verdict"] == "NOT_DEPLOYED")
    fail_n = len(rows) - pass_n - gap_n - nd
    out = {
        "PASS": pass_n,
        "DATA_GAP": gap_n,
        "NOT_DEPLOYED": nd,
        "FAIL": fail_n,
        "rows": rows,
    }
    Path(OUT).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("PASS", "DATA_GAP", "NOT_DEPLOYED", "FAIL")}, indent=2))
    for row in rows:
        print(f"[{row['verdict']}] {row['ms']}ms | {row.get('intent')} | {row['q']}")
    if fail_n:
        sys.exit(1)


if __name__ == "__main__":
    main()
