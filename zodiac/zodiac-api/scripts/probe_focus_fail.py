"""Focused re-cert of previously failing generic capabilities."""
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


def ask(token: str, q: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=json.dumps({"question": q, "investigationId": f"foc{int(time.time()*1000)}"}).encode(),
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
    qs = [
        ("N1", "List the top 8 vendors by purchase order value."),
        ("R3D", "Which vendors generated the highest purchase order value?"),
        ("N8", "Which industries generated the most billed sales?"),
        ("J", "Show invoices from last month."),
        ("K", "Which customers had billed sales above the average customer sales?"),
        ("F", "Which suppliers have purchase orders but no invoices?"),
        ("FQ1", "Show the top 10 suppliers by invoice amount."),
        ("P4", "Customers with billed sales above the average."),
        ("P7", "Which country declined the most in billed sales between 2004 and 2005?"),
    ]
    for label, q in qs:
        try:
            d = ask(token, q)
        except Exception as exc:
            print(label, "ERROR", exc)
            continue
        rows = d.get("data") or []
        cols = list(rows[0].keys()) if rows else []
        print(
            label,
            d.get("answer_status"),
            f"rows={len(rows)}",
            f"elapsed={d.get('_elapsed')}",
            cols[:5],
            (d.get("sql") or "")[:100].replace("\n", " "),
        )


if __name__ == "__main__":
    main()
