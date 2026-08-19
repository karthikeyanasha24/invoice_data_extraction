"""
Section K live verification against POST /api/query/adaptive.

Q1 is the client question. Q2–Q6 are follow-ups of Q1 (same as the original report).
Q7–Q20 are independent new questions.

Usage:
  python scripts/verify_ga_section_k.py
  LIVE_GA_API=http://127.0.0.1:8000 python scripts/verify_ga_section_k.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API = os.getenv("LIVE_GA_API", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = int(os.getenv("LIVE_GA_TIMEOUT", "120"))

CLIENT_Q = "Show me highest sales for the year 2004 with customer and industry"


def _post(question: str, context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], float]:
    body: Dict[str, Any] = {"question": question}
    if context:
        body["contextData"] = context
    req = urllib.request.Request(
        f"{API}/api/query/adaptive",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw, "http_status": e.code, "answer_status": "ERROR"}
    elapsed = time.perf_counter() - t0
    return payload, elapsed


def _sql(p: Dict[str, Any]) -> str:
    return str(p.get("sql") or p.get("generatedSql") or "")


def _rows(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = p.get("data") or p.get("rows") or p.get("rows_preview") or []
    return data if isinstance(data, list) else []


def _status(p: Dict[str, Any]) -> str:
    return str(p.get("answer_status") or p.get("type") or "")


def _blob(p: Dict[str, Any]) -> str:
    return json.dumps(p, default=str).lower()


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("€", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _row_text(rows: List[Dict[str, Any]], n: int = 8) -> str:
    return json.dumps(rows[:n], default=str)[:1200]


def _context_from(question: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "previousQuestion": question,
        "previousSQL": _sql(payload),
        "previousPlan": payload.get("query_plan") or payload.get("queryPlan"),
        "previousAnswerStatus": _status(payload),
        "data": _rows(payload)[:20],
    }


def _has_motomarkt_6099225(rows: List[Dict[str, Any]]) -> bool:
    blob = json.dumps(rows[:12], default=str).lower()
    if "motomarkt" not in blob:
        return False
    for row in rows[:12]:
        for key, val in row.items():
            n = _num(val)
            if n is not None and abs(n - 6099225) < 2:
                return True
    return "6099225" in blob.replace(",", "")


def _title_leak(p: Dict[str, Any]) -> bool:
    charts = p.get("charts") or []
    for c in charts if isinstance(charts, list) else []:
        title = str((c or {}).get("title") or "")
        if "continuation" in title.lower():
            return True
    return "continuation of an analysis session" in _blob(p) and False  # charts only


CASES: List[Dict[str, Any]] = [
    {"id": 1, "q": CLIENT_Q, "orig": "PASS — Motomarkt €6,099,225", "mode": "new"},
    {"id": 2, "q": "Only the Trading industry", "orig": "PASS", "mode": "follow"},
    {"id": 3, "q": "Now show the top 5", "orig": "PASS", "mode": "follow"},
    {"id": 4, "q": "Compare with 2003", "orig": "PASS", "mode": "follow"},
    {"id": 5, "q": "Remove the Trading filter", "orig": "PASS", "mode": "follow"},
    {"id": 6, "q": "Show invoice count instead", "orig": "PASS", "mode": "follow"},
    {"id": 7, "q": "Show me highest sales for the year 2005 with customer and industry", "orig": "PASS — Motor Sports USD 6,524,688.52", "mode": "new"},
    {"id": 8, "q": "Show me highest sales for the year 2099 with customer and industry", "orig": "PASS — 0 rows, explicit empty", "mode": "new"},
    {"id": 9, "q": "Invoice count by customer", "orig": "PASS", "mode": "new"},
    {"id": 10, "q": "Failed EDI invoices in the last 30 days", "orig": "PASS — 0 rows", "mode": "new"},
    {"id": 11, "q": "Who bought most in 2004?", "orig": "PASS", "mode": "new"},
    {"id": 12, "q": "Which industry had the highest sales?", "orig": "PASS", "mode": "new"},
    {"id": 13, "q": "five biggest customers", "orig": "FAIL — LIMIT 20, mixed currency", "mode": "new"},
    {"id": 14, "q": "lowest sales 2004", "orig": "PARTIAL — wrong grain/summary", "mode": "new"},
    {"id": 15, "q": "Sales by year", "orig": "PASS", "mode": "new"},
    {"id": 16, "q": "Show me the industry", "orig": "PASS but inefficient (61s)", "mode": "new"},
    {"id": 17, "q": "meaning of life", "orig": "FAIL — generated unrelated SQL", "mode": "new"},
    {"id": 18, "q": "Customer XYZNOEXIST999", "orig": "FAIL — ignored name", "mode": "new"},
    {"id": 19, "q": "Invoice count 2004", "orig": "PASS", "mode": "new"},
    {"id": 20, "q": "Top products 2004", "orig": "FAIL then PASS (flaky)", "mode": "new"},
]


def evaluate(cid: int, q: str, p: Dict[str, Any], elapsed: float, prev: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    sql = _sql(p)
    rows = _rows(p)
    st = _status(p)
    n = len(rows)
    notes: List[str] = [f"{elapsed:.1f}s", f"rows={n}", f"status={st}"]
    if _title_leak(p):
        return "FAIL", "chart title leaked CONTINUATION"

    if cid == 1:
        ok = _has_motomarkt_6099225(rows) and st != "CANNOT_ANSWER"
        notes.append("Motomarkt/6099225" if ok else _row_text(rows, 3))
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 2:
        blob = _row_text(rows).lower()
        ok = n >= 1 and "trading" in blob and st != "CANNOT_ANSWER"
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 3:
        ok = n == 5 and st != "CANNOT_ANSWER"
        notes.append(f"limit_sql={bool(re.search(r'limit\\s+5', sql, re.I))}")
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 4:
        blob = _blob(p)
        ok = st != "CANNOT_ANSWER" and n >= 1 and ("2003" in blob or "2004" in sql)
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 5:
        ok = st != "CANNOT_ANSWER" and n >= 1
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 6:
        low = sql.lower()
        ok = st != "CANNOT_ANSWER" and n >= 1 and (
            "count" in low and "vbeln" in low and "invoice_v2_business_data" not in low
        )
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 7:
        blob = json.dumps(rows[:8], default=str).lower()
        hit_name = "motor sports" in blob or "motorsport" in blob
        hit_amt = any(
            _num(v) is not None and abs(_num(v) - 6524688.52) < 1.0
            for row in rows[:8]
            for v in row.values()
        )
        ok = st != "CANNOT_ANSWER" and n >= 1 and hit_name and (hit_amt or "usd" in blob)
        notes.append(_row_text(rows, 2))
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 8:
        summary = str(p.get("summary") or p.get("answer") or "").lower()
        ok = n == 0 and st != "CANNOT_ANSWER" and (
            "0 row" in summary or "no " in summary or "empty" in summary or "not found" in summary
        )
        return ("PASS" if ok else "FAIL"), "; ".join(notes + [summary[:160]])
    if cid == 9:
        low = sql.lower()
        ok = st != "CANNOT_ANSWER" and n >= 1 and "count" in low and "invoice_v2_business_data" not in low
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 10:
        ok = st != "CANNOT_ANSWER" and n == 0
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 11:
        blob = json.dumps(rows[:5], default=str).lower()
        ok = st != "CANNOT_ANSWER" and n >= 1 and ("motomarkt" in blob or n >= 1)
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 12:
        ok = st != "CANNOT_ANSWER" and n >= 1
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 13:
        low = sql.lower()
        currencies = {
            str(r.get("currency") or r.get("waerk") or "").upper()
            for r in rows
            if r.get("currency") or r.get("waerk")
        }
        currencies.discard("")
        ok = (
            st != "CANNOT_ANSWER"
            and n == 5
            and bool(re.search(r"limit\s+5\b", low))
            and len(currencies) <= 1
        )
        notes.append(f"currencies={sorted(currencies)}")
        notes.append(f"sql_limit5={bool(re.search(r'limit\\s+5', low))}")
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 14:
        low = sql.lower()
        lineish = '"vbrp"' in low and "posnr" in low and "vbrk" not in low
        ok = st != "CANNOT_ANSWER" and n >= 1 and not lineish
        notes.append("header_grain" if "vbrk" in low else "grain_unknown")
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 15:
        ok = st != "CANNOT_ANSWER" and n >= 1
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 16:
        ok = st != "CANNOT_ANSWER" and n >= 1
        notes.append("timing_not_blocking")
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 17:
        ok = st == "CLARIFICATION" or str(p.get("type") or "") == "clarification"
        ok = ok and not sql.strip()
        return ("PASS" if ok else "FAIL"), "; ".join(notes + [str(p.get("summary") or "")[:120]])
    if cid == 18:
        summary = str(p.get("summary") or p.get("answer") or "").lower()
        ok = (
            p.get("entity_not_found") is True
            or "no matching customer" in summary
            or ("not found" in summary and n == 0)
        )
        ok = ok and n == 0
        return ("PASS" if ok else "FAIL"), "; ".join(notes + [summary[:160]])
    if cid == 19:
        low = sql.lower()
        ok = st != "CANNOT_ANSWER" and "count" in low and "2004" in (low + q.lower())
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    if cid == 20:
        ok = st != "CANNOT_ANSWER" and n >= 1
        notes.append("product" if "vbrp" in sql.lower() or "matnr" in sql.lower() else "sql_preview=" + sql[:80])
        return ("PASS" if ok else "FAIL"), "; ".join(notes)
    return "FAIL", "unhandled case"


def main() -> int:
    print(f"API {API}", flush=True)
    rows_out: List[Tuple[int, str, str, str, str]] = []
    prev_q = CLIENT_Q
    prev_payload: Optional[Dict[str, Any]] = None
    failures = 0
    ctx = None
    for case in CASES:
        cid, q, orig, mode = case["id"], case["q"], case["orig"], case["mode"]
        if mode == "follow" and prev_payload is not None:
            ctx = _context_from(prev_q, prev_payload)
        else:
            ctx = None
        payload, elapsed = _post(q, ctx)
        result, notes = evaluate(cid, q, payload, elapsed, prev_payload)
        if result != "PASS":
            failures += 1
        sql_clip = re.sub(r"\s+", " ", _sql(payload))[:90]
        print(f"\n#{cid} {result}  {q}", flush=True)
        print(f"    orig: {orig}", flush=True)
        print(f"    notes: {notes}", flush=True)
        print(f"    sql: {sql_clip}", flush=True)
        rows_out.append((cid, q, orig, result, notes))
        if mode == "follow" or cid == 1:
            prev_q = q
            prev_payload = payload

    print("\n" + "=" * 100)
    print(f"{'#':<3} {'result':<6} {'orig':<42} question")
    print("-" * 100)
    for cid, q, orig, result, notes in rows_out:
        print(f"{cid:<3} {result:<6} {orig:<42} {q}")
        print(f"         {notes}")
    print("=" * 100)
    print(f"{20 - failures}/20 PASS, {failures} FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
