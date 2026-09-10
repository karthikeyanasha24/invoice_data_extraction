"""Run AI Analyst QA battery locally (login + adaptive API or direct pipeline)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"

QUESTIONS = [
    ("general_chat", "ahi hello"),
    ("multidim_ranking", "Which country, customer, and industry has the highest sales?"),
    ("top_customers", "Top 5 customers by billed sales"),
    ("top_materials", "Top 20 materials by billed quantity"),
    ("sales_by_year", "Show sales by year"),
    ("customers_industries", "Customers and industries with billed revenue"),
    ("negative_sales", "show me negatives sales for the year 2000"),
    ("customer_names", "Show customer names only"),
    ("sat_logs", "Show SAT processing logs"),
    ("data_limitation", "What is our profit margin?"),
]


def login() -> str:
    payload = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/user/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data["access_token"]


def ask(token: str, question: str, thread_id: str | None = None) -> dict:
    body = {"question": question}
    if thread_id:
        body["threadId"] = thread_id
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def summarize(label: str, question: str, out: dict) -> str:
    mode = out.get("mode") or out.get("type") or "?"
    status = out.get("answer_status") or out.get("status") or "?"
    rows = out.get("rowCount")
    if rows is None and isinstance(out.get("data"), list):
        rows = len(out["data"])
    sql = (out.get("sql") or "")[:120]
    summary = (out.get("summary") or out.get("answer") or "")[:100]
    detail = out.get("detail") or []
    if isinstance(detail, list) and detail:
        summary = str(detail[0])[:120]
    pipeline = out.get("pipeline") or out.get("sql_generation_method") or ""
    return (
        f"[{label}] {status}/{mode} rows={rows} pipeline={pipeline}\n"
        f"  Q: {question}\n"
        f"  SQL: {sql}...\n"
        f"  Msg: {summary}"
    )


def main() -> int:
    print("Logging in...")
    try:
        token = login()
    except Exception as exc:
        print(f"LOGIN FAILED: {exc}")
        return 1

    print("Login OK\n")
    passed = 0
    failed = 0
    thread_id = None

    for label, question in QUESTIONS:
        try:
            out = ask(token, question, thread_id)
            tid = out.get("threadId") or out.get("thread_id")
            if tid and not thread_id:
                thread_id = tid
            line = summarize(label, question, out)
            print(line)
            if label == "general_chat":
                ok = (out.get("mode") == "general_chat" or "hello" in (out.get("answer") or out.get("summary") or "").lower())
            elif label == "data_limitation":
                ok = str(out.get("mode") or "").lower() in {"data_limitation", "cannot_answer"} or str(out.get("answer_status") or "") == "CANNOT_ANSWER"
            elif label == "negative_sales":
                ok = (out.get("rowCount") or 0) > 0 and "GROUP BY" not in (out.get("sql") or "").upper()
            elif label == "multidim_ranking":
                ok = (out.get("rowCount") or 0) > 0 and "data_limitation" not in str(out.get("mode") or "").lower()
            else:
                ok = str(out.get("mode") or "").lower() != "data_limitation" and str(out.get("answer_status") or "") != "CANNOT_ANSWER"
            print(f"  => {'PASS' if ok else 'FAIL'}\n")
            if ok:
                passed += 1
            else:
                failed += 1
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()[:300]
            print(f"[{label}] HTTP {exc.code}: {body}\n  => FAIL\n")
            failed += 1
        except Exception as exc:
            print(f"[{label}] ERROR: {exc}\n  => FAIL\n")
            failed += 1

    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
