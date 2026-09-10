"""Focused retest of remaining FAIL/PARTIAL classes after judge + follow-up fixes."""
from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def login() -> str:
    req = urllib.request.Request(
        f"{BASE}/api/v1/user/auth/login",
        data=json.dumps({"email": "puspesh@gmail.com", "password": "12345"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def ask(token: str, q: str, context=None) -> dict:
    body = {"question": q, "contextData": context, "investigationId": f"fx{int(time.time()*1000)}"}
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=135) as r:
        d = json.loads(r.read())
    d["_elapsed"] = round(time.time() - t0, 2)
    return d


def main() -> None:
    token = login()
    print("login_ok")
    for label, q in [
        ("N1", "List the top 8 vendors by purchase order value."),
        ("R3D", "Which vendors generated the highest purchase order value?"),
        ("P3", "Top materials by billed quantity in each plant."),
        ("U5", "Which products experienced the strongest year-over-year decline?"),
    ]:
        d = ask(token, q)
        rows = d.get("data") or []
        cols = list(rows[0].keys()) if rows else []
        print(f"{label} status={d.get('answer_status')} rows={len(rows)} cols={cols[:6]} elapsed={d.get('_elapsed')}")

    q1 = ask(token, "Show the top 10 suppliers by invoice amount.")
    print(f"FQ1 status={q1.get('answer_status')} rows={len(q1.get('data') or [])} cols={list((q1.get('data') or [{}])[0].keys())[:6]}")
    ctx = {
        "previousQuestion": "Show the top 10 suppliers by invoice amount.",
        "previousSQL": q1.get("sql") or "",
        "previousPlan": q1.get("query_plan"),
        "previousAnswerStatus": q1.get("answer_status"),
        "data": q1.get("data") or [],
    }
    q2 = ask(token, "Which supplier appears most in this result?", context=ctx)
    print(f"FQ2 status={q2.get('answer_status')} pipe={q2.get('pipeline')} rows={len(q2.get('data') or [])} summary={(q2.get('summary') or '')[:120]}")


if __name__ == "__main__":
    main()
