"""Full QA battery — all test questions via adaptive orchestrator (matches UI)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.adaptive_query import _execute_sql
from app.database import SessionLocal
from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator

# (id, question, expect_fn_name)
TESTS = [
    ("multidim_highest", "Which country, customer, and industry has the highest sales?", "multidim"),
    ("top5_customers", "Top 5 customers by billed sales", "rows_min_1"),
    ("top20_materials", "Top 20 materials by billed quantity", "rows_at_least_20"),
    ("sales_by_year", "Show sales by year", "rows_min_1"),
    ("customers_industries", "Customers and industries with billed revenue", "rows_min_1"),
    ("negative_sales", "show me negatives sales for the year 2000", "negative_sales"),
    ("customer_names", "Show customer names only", "rows_min_1"),
    ("sat_logs", "Show SAT processing logs", "rows_or_honest_gap"),
    ("profit_margin", "What is our profit margin?", "data_limitation"),
    ("general_chat", "ahi hello", "general_chat"),
]

FOLLOWUP = [
    ("top10_then_top3_a", "Top 10 customers by sales", "rows_min_1"),
    ("top10_then_top3_b", "Make it top 3", "rows_max_5"),
]


def _rows(out: dict) -> list:
    return list(out.get("rows") or out.get("data") or [])


def _sql(out: dict) -> str:
    return str(out.get("sql") or "")


def _mode(out: dict) -> str:
    return str(out.get("mode") or out.get("type") or "").lower()


def expect(name: str, out: dict, question: str) -> tuple[bool, str]:
    err = out.get("error")
    rows = _rows(out)
    sql = _sql(out).upper()
    detail = out.get("detail") or out.get("summary") or ""

    if name == "general_chat":
        ok = _mode(out) == "general_chat" or "hello" in str(out.get("answer") or detail).lower()
        return ok, "general_chat mode expected"

    if name == "data_limitation":
        ok = (
            _mode(out) in {"data_limitation", "cannot_answer"}
            or str(out.get("answer_status") or "") == "CANNOT_ANSWER"
            or "cannot" in str(detail).lower()
            or "not available" in str(detail).lower()
            or "limitation" in str(detail).lower()
        )
        return ok, "honest data limitation expected"

    if name == "negative_sales":
        if err or _mode(out) == "data_limitation":
            return False, f"error={err} mode={_mode(out)}"
        if "GROUP BY" in sql:
            return False, "should be row-level, no GROUP BY"
        if len(rows) < 1:
            return False, "expected rows > 0"
        return True, f"{len(rows)} rows"

    if name == "multidim":
        if err or _mode(out) == "data_limitation" or _mode(out) == "error":
            return False, f"error={err} mode={_mode(out)}"
        if len(rows) < 1:
            return False, "no rows"
        if len(rows) > 3:
            return False, f"expected LIMIT 1-3 for superlative, got {len(rows)} rows"
        return True, f"{len(rows)} rows"

    if name == "rows_at_least_20":
        if err == "sql_execution_failed" or _mode(out) == "data_limitation":
            return False, f"failed: {detail[:120] if detail else err}"
        if _mode(out) == "error":
            return False, f"mode=error: {(detail or out.get('summary') or '')[:120]}"
        m = re.search(r"\btop\s+(\d+)", question, re.I)
        need = int(m.group(1)) if m else 20
        if len(rows) >= need:
            return True, f"{len(rows)} rows"
        return False, f"expected >={need} rows, got {len(rows)}"

    if name == "rows_min_1":
        if err == "sql_execution_failed" or _mode(out) == "data_limitation":
            return False, f"failed: {detail[:120] if detail else err}"
        if _mode(out) == "error":
            return False, f"mode=error: {(detail or out.get('summary') or '')[:120]}"
        if len(rows) >= 1:
            return True, f"{len(rows)} rows"
        return False, "0 rows and no tabular result"

    if name == "rows_or_honest_gap":
        if len(rows) >= 1:
            return True, f"{len(rows)} rows"
        if _mode(out) in {"data_limitation", "cannot_answer"} or "not" in str(detail).lower():
            return True, "honest gap if table missing"
        if out.get("answer") or out.get("summary"):
            return True, "text answer"
        return False, "unexpected empty"

    if name == "rows_max_5":
        if err or _mode(out) == "data_limitation":
            return False, str(err or detail)[:120]
        if 1 <= len(rows) <= 5:
            return True, f"{len(rows)} rows"
        if out.get("answer"):
            return True, "follow-up answer"
        return False, f"expected 1-5 rows, got {len(rows)}"

    return not bool(err), "default no error"


def run_one(question: str, prior: dict | None = None) -> dict:
    db = SessionLocal()
    try:
        kwargs = {}
        if prior:
            kwargs["prior_plan"] = prior.get("query_plan")
            kwargs["prior_sql"] = prior.get("sql") or ""
            kwargs["prior_rows"] = _rows(prior)
            kwargs["prior_question"] = prior.get("question") or ""
        return run_adaptive_orchestrator(question, db, _execute_sql, **kwargs)
    finally:
        db.close()


def main() -> int:
    results = []
    passed = failed = 0
    t0 = time.time()
    prior_out = None

    print(f"Full QA battery started {datetime.now().isoformat()}\n")

    for tid, question, exp in TESTS + FOLLOWUP:
        print(f"[{tid}] {question}")
        t1 = time.time()
        try:
            use_prior = tid == "top10_then_top3_b"
            out = run_one(question, prior_out if use_prior else None)
            ok, note = expect(exp, out, question)
            elapsed = round(time.time() - t1, 1)
            log = out.get("pipeline_log") or out.get("query_plan") or {}
            if isinstance(log, dict):
                src = (log.get("PIPELINE_3_SQL_GENERATION") or {})
                source = src.get("source", "") if isinstance(src, dict) else ""
            else:
                source = ""
            row = {
                "id": tid,
                "question": question,
                "pass": ok,
                "note": note,
                "seconds": elapsed,
                "error": out.get("error"),
                "mode": _mode(out),
                "rows": len(_rows(out)),
                "source": source,
                "sql_prefix": _sql(out)[:200],
            }
            results.append(row)
            status = "PASS" if ok else "FAIL"
            print(f"  => {status} ({elapsed}s, rows={row['rows']}, mode={row['mode']}) {note}")
            if not ok and (out.get("detail") or out.get("summary")):
                print(f"  detail: {str(out.get('detail') or out.get('summary'))[:200]}")
            if ok:
                passed += 1
            else:
                failed += 1
            if tid == "top10_then_top3_a":
                prior_out = {**out, "question": question}
        except Exception as exc:
            failed += 1
            results.append({"id": tid, "question": question, "pass": False, "note": str(exc)})
            print(f"  => FAIL EXCEPTION: {exc}")
        print()

    total = round(time.time() - t0, 1)
    summary = {"passed": passed, "failed": failed, "total_seconds": total, "results": results}
    out_path = os.path.join(os.path.dirname(__file__), "qa_battery_full_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("=" * 60)
    print(f"DONE: {passed} passed, {failed} failed, {total}s total")
    print(f"Results: {out_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
