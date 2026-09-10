"""Acceptance A–H against POST /api/query/adaptive as new investigations."""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"
TIMEOUT = 125


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


def ask(token: str, question: str, context=None) -> dict:
    body = json.dumps({"question": question, "contextData": context}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        data["_elapsed"] = round(time.time() - t0, 2)
        data["_client"] = "ok"
        return data
    except TimeoutError:
        return {"_client": "timeout", "_elapsed": round(time.time() - t0, 2), "summary": "client timeout"}
    except urllib.error.URLError as exc:
        return {"_client": "error", "_elapsed": round(time.time() - t0, 2), "summary": str(exc)}


def preview(label: str, q: str, data: dict) -> None:
    rows = data.get("data") or []
    cols = list(rows[0].keys()) if rows else []
    print(f"\n=== {label} ===")
    print("Q:", q)
    print("client:", data.get("_client"), "elapsed:", data.get("_elapsed"), "status:", data.get("answer_status"), "pipeline:", data.get("pipeline") or data.get("sql_generation_method"))
    print("rows:", data.get("rowCount"), "cols:", cols[:8])
    print("sql:", (data.get("sql") or "")[:220].replace("\n", " "))
    print("summary:", (data.get("summary") or "")[:180].replace("\n", " "))
    if rows:
        print("sample:", json.dumps(rows[0], default=str)[:240])


def main() -> None:
    token = login()
    a = ask(token, "Show top 10 customers by revenue")
    preview("A revenue ranking", "Show top 10 customers by revenue", a)

    b = ask(token, "Show sales order count by month")
    preview("B monthly count", "Show sales order count by month", b)

    c = ask(token, "Show billing documents with amounts and currency")
    preview("C billing", "Show billing documents with amounts and currency", c)

    ctx = None
    if a.get("_client") == "ok" and a.get("data"):
        ctx = {
            "previousQuestion": "Show top 10 customers by revenue",
            "previousSQL": a.get("sql") or "",
            "previousPlan": a.get("query_plan"),
            "previousAnswerStatus": a.get("answer_status"),
            "data": a.get("data") or [],
        }
    d = ask(token, "Which supplier appears most in this result?", context=ctx)
    preview("D follow-up", "Which supplier appears most in this result?", d)

    e = ask(token, "Which country, customer, and industry has the highest sales?")
    preview("E multi-dim", "Which country, customer, and industry has the highest sales?", e)

    f = ask(token, "Show me negative sales for the year 2000")
    preview("F negative sales", "Show me negative sales for the year 2000", f)

    g = ask(token, "Top 20 materials by billed quantity")
    preview("G material ranking", "Top 20 materials by billed quantity", g)

    h = ask(token, "What is the average net value of billing documents by sales organization?")
    preview("H unseen", "What is the average net value of billing documents by sales organization?", h)


if __name__ == "__main__":
    main()
