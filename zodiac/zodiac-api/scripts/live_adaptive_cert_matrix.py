"""Live HTTP certification matrix for adaptive AI Analyst.

Uses LIVE_API_BASE + LIVE_API_TOKEN or LIVE_API_EMAIL/PASSWORD from the
environment. Never prints tokens or passwords. Never hardcodes credentials.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

BASE = (os.environ.get("LIVE_API_BASE") or "https://zodiac-back.vercel.app").rstrip("/")
EMAIL = (os.environ.get("LIVE_API_EMAIL") or "").strip()
PASSWORD = os.environ.get("LIVE_API_PASSWORD") or ""
TIMEOUT = int(os.environ.get("LIVE_CERT_TIMEOUT", "180"))


def login() -> str:
    existing = (os.environ.get("LIVE_API_TOKEN") or os.environ.get("ZODIAC_LIVE_TOKEN") or "").strip()
    if existing:
        return existing
    if not EMAIL or not PASSWORD:
        raise RuntimeError(
            "Set LIVE_API_TOKEN or LIVE_API_EMAIL+LIVE_API_PASSWORD for live certification"
        )
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/user/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    tok = (data.get("access_token") or "").strip()
    if not tok:
        raise RuntimeError("login returned no access_token")
    os.environ["LIVE_API_TOKEN"] = tok
    return tok


def login_as(email: str, password: str) -> Tuple[str, Dict[str, Any]]:
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/user/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    tok = (data.get("access_token") or "").strip()
    if not tok:
        raise RuntimeError(f"login failed for {email}")
    return tok, data.get("user") or {}


def fetch_health() -> Dict[str, Any]:
    req = urllib.request.Request(f"{BASE}/api/query/health", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def ask(
    token: str,
    question: str,
    *,
    context: Optional[dict] = None,
    override_sql: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {
        "question": question,
        "contextData": context,
        "investigationId": f"livecert{int(time.time() * 1000)}",
    }
    if override_sql:
        body["overrideSql"] = override_sql
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
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            out = json.loads(resp.read().decode())
            ms = int((time.perf_counter() - t0) * 1000)
            return out, ms
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            out = json.loads(raw)
        except Exception:
            out = {"error": "http_error", "status_code": e.code, "body": raw[:500]}
        out.setdefault("answer_status", f"HTTP_{e.code}")
        return out, ms


def snap(q: str, r: Dict[str, Any], ms: int) -> Dict[str, Any]:
    sql = r.get("sql") or ""
    charts = r.get("charts") or []
    data = r.get("data") or []
    chart_vals_ok = True
    for c in charts:
        if not isinstance(c, dict):
            continue
        cdata = c.get("data")
        if cdata is None:
            continue
        # Chart data must be a list of rows (possibly formatted), not free-form invented scalars.
        if not isinstance(cdata, list):
            chart_vals_ok = False
    return {
        "q": q,
        "ms": ms,
        "status": r.get("answer_status") or r.get("type"),
        "mode": r.get("mode") or r.get("route"),
        "pipe": r.get("pipeline") or r.get("sql_generation_method"),
        "rows": r.get("rowCount") if r.get("rowCount") is not None else len(data),
        "has_sql": bool(str(sql).strip()),
        "sql_preview": str(sql).replace("\n", " ")[:220],
        "summary": (r.get("summary") or r.get("answer") or "")[:220],
        "presentation": (r.get("presentation") or {}).get("type")
        if isinstance(r.get("presentation"), dict)
        else None,
        "charts": len(charts) if isinstance(charts, list) else 0,
        "chart_data_lists": chart_vals_ok,
        "failure_class": r.get("failure_class")
        or ((r.get("meta") or {}).get("failure_class") if isinstance(r.get("meta"), dict) else None),
        "diagnostics": bool(r.get("diagnostics") or ((r.get("meta") or {}).get("diagnostics"))),
    }


def ctx_from(q: str, r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "previousQuestion": q,
        "previousSQL": r.get("sql") or "",
        "previousPlan": r.get("query_plan") or {},
        "previousAnswerStatus": r.get("answer_status") or "",
        "data": (r.get("data") or [])[:30],
    }


def main() -> int:
    print(json.dumps({"base": BASE, "email": EMAIL or "(token)", "phase": "health"}))
    try:
        health = fetch_health()
        print(json.dumps({"health": health}, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"health_error": str(exc)[:200]}))
        health = {}

    print(json.dumps({"phase": "login"}))
    token = login()
    print(json.dumps({"login": "ok", "ai_release": health.get("ai_release"), "build_id": health.get("build_id")}))

    results: List[Dict[str, Any]] = []

    def run(label: str, q: str, **kwargs) -> Dict[str, Any]:
        tok = kwargs.pop("token", token)
        r, ms = ask(tok, q, **kwargs)
        row = {"label": label, **snap(q, r, ms)}
        results.append(row)
        print(json.dumps(row, ensure_ascii=True))
        return {"raw": r, "snap": row}

    # --- General ---
    for q in ("Hi", "What can I ask?", "What is SAP?"):
        out = run("general", q)
        # expect no unnecessary sql
        if out["snap"]["has_sql"] and out["snap"]["mode"] not in {"general_chat", "general"}:
            out["snap"]["warn"] = "general_with_sql"

    # --- Basic / unseen / ranking / trend / compare / contribution / investigation ---
    for label, q in [
        ("basic_db", "What was our revenue in 2025?"),
        ("unseen", "How much money did we generate during 2025?"),
        ("ranking", "Which five customers brought in the most revenue?"),
        ("trend", "Show me how revenue moved month by month in 2025."),
        ("compare", "How much did revenue change between 2024 and 2025?"),
        (
            "contribution",
            "Which three customers contributed most to the revenue decline between 2024 and 2025?",
        ),
        ("investigation", "Why did revenue fall in 2025?"),
    ]:
        run(label, q)

    # --- Follow-up chain ---
    first = run("followup_1", "Show me the top 5 customers by revenue.")
    ctx = ctx_from("Show me the top 5 customers by revenue.", first["raw"])
    second = run("followup_2", "Which one grew the most?", context=ctx)
    ctx2 = ctx_from("Which one grew the most?", second["raw"])
    ctx2["previousQuestion"] = "Which one grew the most?"
    # keep prior ranking entities in context
    ctx2["data"] = (first["raw"].get("data") or [])[:10]
    run("followup_3", "Show its monthly trend.", context=ctx2)

    # --- Presentation ---
    chart = run("present_chart", "Show the top 10 customers by revenue as a chart.")
    ctxp = ctx_from("Show the top 10 customers by revenue as a chart.", chart["raw"])
    run("present_table", "Show the same result as a table.", context=ctxp)
    run("present_both", "Give me both the chart and the table.", context=ctxp)

    # --- NO_DATA: far-future year unlikely in extract ---
    run("no_data", "What was our revenue in 2099?")

    # --- Clarification ---
    run("clarification", "Show me the growth.")

    # --- Cannot-answer ---
    run("cannot_answer", "What is our profit margin by customer sentiment score?")

    # --- SQL safety (override destructive) ---
    for bad in (
        "DELETE FROM \"VBRK\"",
        "DROP TABLE \"KNA1\"",
        'SELECT 1; DROP TABLE "KNA1"',
    ):
        out = run("sql_safety", "run override", override_sql=bad)
        st = str(out["snap"]["status"] or "").upper()
        # should not succeed with data mutation
        out["snap"]["blocked"] = st not in {"SUCCESS"} or not out["snap"].get("has_sql")

    # --- Cross-tenant adversarial read (app table) ---
    adv = (
        'SELECT id, user_id, supplier_name, total FROM sat_documents '
        "WHERE user_id <> 0 ORDER BY id DESC LIMIT 5"
    )
    run("cross_tenant_read", "show sat documents", override_sql=adv)

    # Summary flags
    summary = {
        "base": BASE,
        "count": len(results),
        "by_label": {},
    }
    for row in results:
        summary["by_label"].setdefault(row["label"], []).append(
            {
                "status": row["status"],
                "mode": row["mode"],
                "has_sql": row["has_sql"],
                "rows": row["rows"],
                "ms": row["ms"],
            }
        )
    print(json.dumps({"summary": summary}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"fatal": type(exc).__name__, "message": str(exc)[:400]}))
        raise SystemExit(2)
