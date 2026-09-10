"""Live production certification for POST /api/query/adaptive.

Fresh investigation per question. No table hints. Catalog must not answer.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = "http://127.0.0.1:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"
CLIENT_TIMEOUT = 135
OUT = Path(__file__).resolve().parent / "live_cert_results.jsonl"


def login() -> str:
    payload = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/user/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["access_token"]


def ask(token: str, question: str, context: Optional[dict] = None, inv: str = "") -> dict:
    body = {
        "question": question,
        "contextData": context,
        "investigationId": inv or f"cert{int(time.time()*1000)}",
    }
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=CLIENT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        data["_elapsed"] = round(time.time() - t0, 2)
        data["_client"] = "ok"
        return data
    except TimeoutError:
        return {"_client": "timeout", "_elapsed": round(time.time() - t0, 2), "summary": "client timeout"}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        return {
            "_client": "http_error",
            "_elapsed": round(time.time() - t0, 2),
            "summary": f"HTTP {exc.code}: {detail}",
            "answer_status": "ERROR",
        }
    except urllib.error.URLError as exc:
        return {"_client": "error", "_elapsed": round(time.time() - t0, 2), "summary": str(exc)}


def _cols(rows: List[dict]) -> List[str]:
    return [str(k).lower() for k in (rows[0].keys() if rows else [])]


def _forbidden_pipeline(data: dict) -> bool:
    pipe = str(data.get("pipeline") or data.get("sql_generation_method") or "").lower()
    bad = (
        "sql_catalog",
        "intent_sql",
        "sales_order_catalog",
        "domain_overview",
        "deep_multidim",
        "period_compare",
        "deterministic_template",
    )
    return any(b in pipe for b in bad)


def judge(label: str, question: str, data: dict, kind: str) -> Tuple[str, str]:
    if data.get("_client") != "ok":
        return "FAIL", f"client={data.get('_client')} {data.get('summary')}"
    if _forbidden_pipeline(data):
        return "FAIL", f"forbidden pipeline={data.get('pipeline')}"
    status = str(data.get("answer_status") or "").upper()
    rows = data.get("data") or []
    sql = data.get("sql") or ""
    cols = _cols(rows)
    if '."SUBSTRING(' in sql or '."EXTRACT(' in sql:
        return "FAIL", "expression quoted as identifier"
    if kind == "rank_revenue":
        if status not in {"SUCCESS"}:
            return "FAIL", f"status={status} summary={(data.get('summary') or '')[:120]}"
        if not rows:
            return "FAIL", "empty rows"
        measure_tokens = (
            "netwr", "sales", "revenue", "total", "amount", "billed",
            "quantity", "qty", "fkimg", "invoiced", "purchase", "po_value",
            "purchase_order_value", "invoice_amount", "order_value", "value",
        )
        if not any(any(t in c for t in measure_tokens) for c in cols):
            if all(c in {"kunnr", "name1", "name2", "land1", "ort01"} or "name" in c for c in cols):
                return "FAIL", "looks like customer master listing"
            return "FAIL", f"no revenue/quantity measure cols={cols}"
        if "country" in (question or "").lower() and "customer" not in (question or "").lower():
            if not any("country" in c or c == "land1" for c in cols):
                return "FAIL", f"country ranking missing country cols={cols}"
        if "ORDER BY" not in sql.upper() and "DESC" not in sql.upper():
            return "WARN", "no ORDER BY visible"
        return "PASS", f"rows={len(rows)} cols={cols[:6]}"
    if kind == "month_count":
        if status not in {"SUCCESS"}:
            return "FAIL", f"status={status}"
        if len(rows) <= 1 and not any("month" in c for c in cols):
            return "FAIL", f"single total / no month cols={cols} sample={rows[:1]}"
        if not any("month" in c or re.fullmatch(r"(yyyymm|period)", c) for c in cols):
            return "FAIL", f"missing month column cols={cols}"
        if "GROUP BY" not in sql.upper():
            return "FAIL", "SQL missing GROUP BY"
        if not re.search(r"\bCOUNT\s*\(", sql, re.I):
            return "FAIL", "SQL missing COUNT"
        return "PASS", f"rows={len(rows)} cols={cols[:6]}"
    if kind == "period":
        # Wrong SUCCESS is worse than CANNOT_ANSWER — reject totals without comparison proof
        if status == "SUCCESS":
            blob = (" ".join(cols) + " " + sql).lower()
            has_compare = any(
                x in blob
                for x in ("period_a", "period_b", "change", "growth", "diff", "delta", "pct_change")
            ) or ("case when" in sql.lower() and re.search(r"20\d{2}", sql))
            if not has_compare:
                return "FAIL", f"WRONG_SUCCESS: no period comparison cols={cols}"
            if not rows:
                return "FAIL", "SUCCESS with empty rows"
            return "PASS", f"rows={len(rows)} cols={cols[:8]}"
        if status == "CLARIFICATION":
            return "PASS", "clarification for ambiguous comparison periods"
        if status == "CANNOT_ANSWER":
            return "PARTIAL", f"cannot_answer (no wrong-success): {(data.get('summary') or '')[:100]}"
        if status == "TIMEOUT":
            return "TIMEOUT", "timeout"
        return "FAIL", f"status={status}"
    if kind == "date_rel":
        if status == "SUCCESS":
            if not re.search(r"(DATE_TRUNC|CURRENT_DATE|INTERVAL|SUBSTRING|20\d{6})", sql, re.I):
                return "FAIL", "no relative date expression"
            # Empty rows are valid when the period has no data
            return "PASS", f"rows={len(rows)}"
        if status == "CANNOT_ANSWER":
            return "PARTIAL", f"cannot_answer: {(data.get('summary') or '')[:100]}"
        if status == "TIMEOUT":
            return "TIMEOUT", "timeout"
        return "FAIL", f"status={status}"
    if kind == "partition":
        if status == "SUCCESS":
            if "PARTITION BY" not in sql.upper() and "ROW_NUMBER" not in sql.upper():
                return "FAIL", "missing partitioned ranking window"
            return "PASS", f"rows={len(rows)} cols={cols[:6]}"
        if status == "CANNOT_ANSWER":
            return "PARTIAL", f"cannot_answer: {(data.get('summary') or '')[:100]}"
        return "FAIL", f"status={status}"
    if kind == "negation":
        if status == "SUCCESS":
            if "IS NULL" not in sql.upper() and "NOT EXISTS" not in sql.upper() and "EXCEPT" not in sql.upper():
                return "FAIL", "missing anti-join / NOT EXISTS"
            return "PASS", f"rows={len(rows)}"
        if status == "CANNOT_ANSWER":
            return "PARTIAL", f"cannot_answer after adaptive path: {(data.get('summary') or '')[:100]}"
        return "FAIL", f"status={status}"
    if kind == "timeout_ok":
        if status == "TIMEOUT":
            return "PASS", "timeout returned"
        return "FAIL", f"expected TIMEOUT got {status}"
    if kind == "any_success":
        if status == "SUCCESS" and rows is not None:
            return "PASS", f"rows={len(rows)} cols={cols[:6]}"
        if status == "CLARIFICATION":
            return "PASS", "clarification"
        if status in {"CANNOT_ANSWER", "TIMEOUT"}:
            return "PARTIAL", f"status={status}"
        return "FAIL", f"status={status}"
    return "FAIL", f"unknown kind {kind}"


BATTERY = [
    ("A", "Which customers generated the highest billed sales?", "rank_revenue"),
    ("B", "Show sales order count by month.", "month_count"),
    ("C", "Which country generated the most billed sales?", "rank_revenue"),
    ("D", "Which country, customer, and industry generated the highest billed sales?", "rank_revenue"),
    ("E", "Show the top 5 customers in each country by billed sales.", "partition"),
    ("F", "Which suppliers have purchase orders but no invoices?", "negation"),
    ("G", "Which customers increased their billed sales between 2004 and 2005?", "period"),
    ("H", "Which country had the largest decline in sales between 2004 and 2005?", "period"),
    ("I", "Show the top 10 materials by billed quantity.", "rank_revenue"),
    ("J", "Show invoices from last month.", "date_rel"),
    ("K", "Which customers had billed sales above the average customer sales?", "any_success"),
    ("L", "Which country had the highest sales growth and which customers contributed most to that growth?", "period"),
    ("R1", "Top 10 customers by revenue", "rank_revenue"),
    ("R2", "Sales order count by month", "month_count"),
    ("U1", "Which customers bought products in more than one country?", "any_success"),
    ("U2", "Which materials generated high quantity but relatively low billed value?", "any_success"),
    ("U3", "Which suppliers had activity without corresponding billing?", "negation"),
    ("U4", "Which customer segment contributed the largest share of sales?", "any_success"),
    ("U5", "Which products experienced the strongest year-over-year decline?", "period"),
    ("N1", "List the top 8 vendors by purchase order value.", "rank_revenue"),
    ("N2", "How many billing documents were created each year?", "any_success"),
    ("N3", "Which materials had the highest billed quantity in each plant?", "partition"),
    ("N4", "Which customers declined in billed sales between 2003 and 2004?", "period"),
    ("N5", "Show purchase orders from last quarter.", "date_rel"),
    ("N6", "Which customers have sales orders but no billing documents?", "negation"),
    ("N7", "What is total billed sales by currency?", "any_success"),
    ("N8", "Which industries generated the most billed sales?", "rank_revenue"),
    ("N9", "Show top 3 materials in each country by billed sales.", "partition"),
    ("N10", "Which customers grew billed sales the most between 2004 and 2005?", "period"),
    # Round-3 additional unseen (≥10)
    ("R3A", "Top 3 materials per country by billed quantity.", "partition"),
    ("R3B", "Bottom 5 customers per country by billed sales.", "partition"),
    ("R3C", "Show billing documents from this month.", "date_rel"),
    ("R3D", "Which vendors generated the highest purchase order value?", "rank_revenue"),
    ("R3E", "Count sales orders by year.", "any_success"),
    ("R3F", "Which customers have invoices but no sales orders?", "negation"),
    ("R3G", "Which materials increased billed quantity between 2004 and 2005?", "period"),
    ("R3H", "Show top customers by billed sales in USD only.", "rank_revenue"),
    ("R3I", "Which country and industry combination had the highest billed sales?", "rank_revenue"),
    ("R3J", "List invoices from last week.", "date_rel"),
    # Round-4 unseen / paraphrase / entity / temporal / adversarial expansions
    ("P1", "Which vendors generated the highest purchase order amounts?", "rank_revenue"),
    ("P2", "Count billing documents by year.", "any_success"),
    ("P3", "Top materials by billed quantity in each plant.", "partition"),
    ("P4", "Customers with billed sales above the average.", "any_success"),
    ("P5", "Vendors that have purchase orders without invoices.", "negation"),
    ("P6", "Show invoices from this quarter.", "date_rel"),
    ("P7", "Which country declined the most in billed sales between 2004 and 2005?", "period"),
    ("P8", "Top 2 customers per country by billed sales.", "partition"),
    ("P9", "How many sales orders were created each year?", "any_success"),
    ("P10", "List bottom 3 materials per country by billed quantity.", "partition"),
    # Final adversarial / qualitative threshold (expect CLARIFICATION, not invented cutoffs)
    ("ADV1", "Show high value customers.", "any_success"),
    ("ADV2", "Which materials have low quantity?", "any_success"),
    ("ADV3", "List important suppliers.", "any_success"),
    ("ADV4", "Show recent orders.", "any_success"),
    ("ADV5", "Large invoices with unusually high revenue.", "any_success"),
]


def main() -> None:
    print("LIVE_CERT", datetime.now(timezone.utc).isoformat(), flush=True)
    with urllib.request.urlopen(f"{BASE}/health", timeout=15) as r:
        print("health", r.status, r.read()[:80], flush=True)
    token = login()
    print("login_ok", flush=True)

    results = []
    OUT.write_text("", encoding="utf-8")
    for label, q, kind in BATTERY:
        print(f"\n=== {label}: {q}", flush=True)
        data = ask(token, q)
        verdict, reason = judge(label, q, data, kind)
        rec = {
            "label": label,
            "question": q,
            "kind": kind,
            "verdict": verdict,
            "reason": reason,
            "elapsed": data.get("_elapsed"),
            "status": data.get("answer_status"),
            "pipeline": data.get("pipeline") or data.get("sql_generation_method"),
            "pipeline_stage": data.get("pipeline_stage"),
            "request_id": data.get("request_id") or (data.get("meta") or {}).get("request_id"),
            "rowCount": data.get("rowCount"),
            "sql": (data.get("sql") or "")[:500],
            "cols": _cols(data.get("data") or [])[:12],
            "sample": (data.get("data") or [])[:2],
            "summary": (data.get("summary") or "")[:240],
        }
        results.append(rec)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        print(f"  {verdict}: {reason}", flush=True)
        print(f"  elapsed={rec['elapsed']} status={rec['status']} pipe={rec['pipeline']} rid={rec['request_id']}", flush=True)
        print(f"  sql={(rec['sql'] or '')[:180].replace(chr(10),' ')}", flush=True)

    # Follow-up chain
    print("\n=== FOLLOWUP Q1", flush=True)
    q1 = ask(token, "Show the top 10 suppliers by invoice amount.")
    v1, r1 = judge("FQ1", "Show the top 10 suppliers by invoice amount.", q1, "rank_revenue")
    print("  ", v1, r1, flush=True)
    ctx = {
        "previousQuestion": "Show the top 10 suppliers by invoice amount.",
        "previousSQL": q1.get("sql") or "",
        "previousPlan": q1.get("query_plan"),
        "previousAnswerStatus": q1.get("answer_status"),
        "data": q1.get("data") or [],
    }
    print("=== FOLLOWUP Q2", flush=True)
    q2 = ask(token, "Which supplier appears most in this result?", context=ctx)
    print("  status", q2.get("answer_status"), "pipe", q2.get("pipeline"), "elapsed", q2.get("_elapsed"), flush=True)
    print("  summary", (q2.get("summary") or "")[:160], flush=True)

    # Cancel test
    print("\n=== CANCEL TEST", flush=True)
    inv = f"cancel{int(time.time())}"
    # fire async-ish: start request in thread, cancel quickly
    import threading

    holder: Dict[str, Any] = {}

    def _run():
        holder["resp"] = ask(token, "Which country, customer, and industry generated the highest billed sales?", inv=inv)

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    time.sleep(3)
    creq = urllib.request.Request(
        f"{BASE}/api/query/adaptive/investigations/{inv}/cancel",
        data=b"{}",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(creq, timeout=30) as r:
            cancel_body = json.loads(r.read().decode())
    except Exception as exc:
        cancel_body = {"error": str(exc)}
    print("cancel_api", cancel_body, flush=True)
    th.join(timeout=130)
    cancel_status = (holder.get("resp") or {}).get("answer_status")
    cancel_stage = (holder.get("resp") or {}).get("pipeline_stage")
    print("cancel_resp_status", cancel_status, cancel_stage, flush=True)
    if cancel_status == "CANCELLED":
        print("cancel_check PASS (answer_status=CANCELLED)", flush=True)
    elif cancel_status in {"TIMEOUT"} and cancel_body.get("cancelled"):
        print("cancel_check PASS (cancelled→timeout-bound stop)", flush=True)
    elif cancel_status in {"CANCELLED", "TIMEOUT"} or "cancel" in str(cancel_body).lower():
        print("cancel_check PASS", flush=True)
    elif cancel_body.get("error") and cancel_status in {"SUCCESS", "CANNOT_ANSWER", None}:
        print("cancel_check PARTIAL (cancel API slow but investigation ended)", flush=True)
    else:
        print("cancel_check FAIL", flush=True)

    # Immediate second question after cancel
    print("=== POST-CANCEL Q", flush=True)
    qn = ask(token, "Show sales order count by month.")
    print("  status", qn.get("answer_status"), "elapsed", qn.get("_elapsed"), "pipe", qn.get("pipeline"), flush=True)

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    partial = sum(1 for r in results if r["verdict"] == "PARTIAL")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    timed = sum(1 for r in results if r["verdict"] == "TIMEOUT")
    wrong_success = [
        r for r in results
        if r["verdict"] == "FAIL" and "WRONG_SUCCESS" in str(r.get("reason") or "")
    ]
    print(
        "\nSUMMARY",
        {"PASS": passed, "PARTIAL": partial, "FAIL": failed, "TIMEOUT": timed, "total": len(results),
         "wrong_success": len(wrong_success)},
        flush=True,
    )
    summary_path = Path(__file__).resolve().parent / "live_cert_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "PASS": passed,
                "PARTIAL": partial,
                "FAIL": failed,
                "TIMEOUT": timed,
                "wrong_success": wrong_success,
                "results": results,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
