"""Hit /api/query/adaptive with a 120s cap per question."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
EMAIL = "puspesh@gmail.com"
PASSWORD = "12345"
TIMEOUT = 120

QUESTIONS = [
    "Show all inbound SAT documents ordered by received date",
    "Which suppliers sent the most SAT documents?",
    "Show SAT documents received this week",
    "Show SAT document count by type (invoice, credit note, payment)",
    "How many SAT documents were received this week?",
    "List SAT documents with a missing or empty CFDI UUID",
    "Show failed EDI invoices and error reasons",
    "Show supplier with highest total invoice amount",
    "Show top 10 customers by revenue",
    "Show sales order count by month",
    "Show billing documents with amounts and currency",
    "Show open purchase orders by vendor",
]


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


def ask(token: str, question: str) -> tuple[str, dict | str]:
    body = json.dumps({"question": question, "contextData": None}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/query/adaptive",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        return "ok", {**data, "_elapsed": elapsed}
    except TimeoutError:
        return "timeout", f">{TIMEOUT}s"
    except urllib.error.URLError as exc:
        elapsed = time.time() - t0
        if elapsed >= TIMEOUT - 1:
            return "timeout", str(exc)
        return "error", str(exc)


def main() -> int:
    token = login()
    ok = 0
    for i, q in enumerate(QUESTIONS, 1):
        status, payload = ask(token, q)
        if status != "ok":
            print(f"{i:2}. [SKIP-{status.upper()}] {q}")
            print(f"    {payload}")
            continue
        elapsed = payload.get("_elapsed", 0)
        rows = payload.get("rowCount")
        pipe = payload.get("pipeline") or payload.get("answer_status")
        summary = (payload.get("summary") or "")[:140].replace("\n", " ")
        tag = "OK"
        if payload.get("answer_status") == "CLARIFICATION":
            tag = "CLARIFY"
        elif elapsed > TIMEOUT:
            tag = "SLOW"
        else:
            ok += 1
        print(f"{i:2}. [{tag}] {elapsed:5.1f}s rows={rows} pipe={pipe}")
        print(f"    Q: {q}")
        print(f"    {summary}")
    print(f"\n{ok}/{len(QUESTIONS)} usable answers (skipped if >{TIMEOUT}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
