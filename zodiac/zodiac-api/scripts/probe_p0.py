"""Focused Round-3 P0 probes before full battery."""
from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"


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


def ask(token: str, question: str) -> dict:
    body = json.dumps(
        {
            "question": question,
            "contextData": None,
            "investigationId": f"p0{int(time.time()*1000)}",
        }
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=135) as resp:
        data = json.loads(resp.read().decode())
    data["_elapsed"] = round(time.time() - t0, 2)
    return data


def main() -> None:
    token = login()
    print("login_ok")
    qs = [
        ("C", "Which country generated the most billed sales?"),
        ("E", "Show the top 5 customers in each country by billed sales."),
        ("J", "Show invoices from last month"),
    ]
    for label, q in qs:
        print(f"\n=== {label}: {q}")
        try:
            data = ask(token, q)
        except Exception as exc:
            print("  ERROR", exc)
            continue
        status = data.get("answer_status")
        rows = data.get("data") or []
        cols = list(rows[0].keys()) if rows else []
        sql = (data.get("sql") or "").replace("\n", " ")[:220]
        src = data.get("sql_generation_method") or data.get("pipeline")
        print(f"  status={status} rows={len(rows)} elapsed={data.get('_elapsed')} src={src}")
        print(f"  cols={cols[:8]}")
        print(f"  sql={sql}")
        print(f"  summary={(data.get('summary') or '')[:160]}")


if __name__ == "__main__":
    main()
