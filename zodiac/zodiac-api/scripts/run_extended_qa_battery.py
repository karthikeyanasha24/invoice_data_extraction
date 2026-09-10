"""Extended QA battery — 35 client-facing questions via adaptive orchestrator (matches UI)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Answers contain typographic characters (−, », …) that crash cp1252 consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.api.adaptive_query import _execute_sql
from app.database import SessionLocal
from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator

# (id, question, expectation, category)
TESTS = [
    # Rankings & aggregations
    ("rank_top3_countries", "Top 3 countries by billed revenue", "rows_exact_3", "ranking"),
    ("rank_lowest_cust_2004", "Which customer had the lowest sales in 2004?", "rows_1_to_10", "ranking"),
    ("rank_top10_prod_2005", "Top 10 products by revenue in 2005", "rows_1_to_10", "ranking"),
    ("rank_five_biggest_invcount", "Show the five biggest customers by invoice count", "rows_1_to_5", "ranking"),
    ("rank_industry_most_rev", "Which industry generated the most revenue?", "rows_1_to_3", "ranking"),
    # Time & trends
    ("time_compare_2004_2005", "Compare sales in 2004 and 2005", "rows_exact_2", "time"),
    ("time_monthly_2004", "Show monthly sales for 2004", "rows_1_to_12", "time"),
    ("time_total_2003", "What were total billed sales in 2003?", "rows_exact_1", "time"),
    ("time_quarter_trend", "Sales trend by quarter", "rows_min_1", "time"),
    # Filters & drill-downs
    ("filt_negative_2005", "Show negative billing documents in 2005", "rows_or_empty_ok", "filter"),
    ("filt_customers_germany", "List all customers in Germany", "rows_or_empty_ok", "filter"),
    ("filt_docs_for_customer", "Show billing documents for customer 0000045000", "rows_or_empty_ok", "filter"),
    ("filt_zero_qty_materials", "Materials with zero billed quantity", "rows_or_empty_ok", "filter"),
    ("filt_industry_chemicals", "Show sales for industry Chemicals", "rows_or_empty_ok", "filter"),
    # Master data / lists
    ("mast_material_names", "List all material names", "rows_min_1", "master"),
    ("mast_vendor_names", "Show vendor names", "rows_min_1", "master"),
    ("mast_count_customers", "How many customers do we have?", "rows_min_1", "master"),
    ("mast_count_sales_orders", "How many sales orders are there?", "rows_or_clarify", "master"),
    # Multi-dimensional
    ("multi_country_industry", "Which country and industry combination has the highest sales?", "rows_1_to_3", "multidim"),
    ("multi_top5_with_dims", "Top 5 customers by sales with country and industry", "rows_1_to_5", "multidim"),
    ("multi_rev_above_1m", "Show customers, countries, and industries with revenue above 1 million", "rows_min_1", "multidim"),
    # Profit / margin
    ("margin_gross_by_product", "What is gross margin by product?", "rows_or_limitation", "margin"),
    ("margin_lowest_products", "Which products have the lowest margins?", "rows_or_limitation", "margin"),
    ("margin_net_profit_cust", "Show net profit by customer", "data_limitation", "margin"),
    # Operational / non-SAP
    ("ops_failed_sat", "Show failed SAT processing steps", "rows_or_empty_ok", "ops"),
    ("ops_latest_sat_errors", "Latest SAT processing errors", "rows_or_empty_ok", "ops"),
    ("ops_edi_status", "Show EDI invoice pipeline status", "rows_or_limitation", "ops"),
    # Edge cases
    ("edge_hello", "hello there", "general_chat", "edge"),
    ("edge_what_tables", "What tables do we have?", "no_crash", "edge"),
    ("edge_show_sales", "Show sales", "no_crash", "edge"),
    ("edge_gibberish", "asdfgh random text", "no_crash", "edge"),
    ("edge_top_cust_so", "Top customers by sales orders", "no_crash", "edge"),
]

# Follow-up chains: (id, question, expectation, category, chain_key)
FOLLOWUPS = [
    ("fu_top10_a", "Top 10 customers by sales", "rows_exact_10", "followup", "chain1"),
    ("fu_top10_b_us_only", "Only US customers", "rows_or_empty_ok", "followup", "chain1"),
    ("fu_year_a", "Show sales by year", "rows_min_1", "followup", "chain2"),
    ("fu_year_b_just_2004", "Just 2004", "rows_1_to_10", "followup", "chain2"),
    ("fu_mat_a", "Top 5 materials by quantity", "rows_exact_5", "followup", "chain3"),
    ("fu_mat_b_top2", "Make it top 2", "rows_1_to_5", "followup", "chain3"),
]


def _rows(out: dict) -> list:
    return list(out.get("rows") or out.get("data") or [])


def _sql(out: dict) -> str:
    return str(out.get("sql") or "")


def _mode(out: dict) -> str:
    return str(out.get("mode") or out.get("type") or "").lower()


def _detail(out: dict) -> str:
    return str(out.get("detail") or out.get("summary") or out.get("answer") or "")


def expect(name: str, out: dict, question: str) -> tuple[bool, str]:
    err = out.get("error")
    rows = _rows(out)
    mode = _mode(out)
    detail = _detail(out)
    n = len(rows)

    is_limitation = mode in {"data_limitation", "cannot_answer"} or str(
        out.get("answer_status") or ""
    ).upper() == "CANNOT_ANSWER"
    is_clarify = mode == "clarification" or str(out.get("answer_status") or "").upper() == "CLARIFICATION"

    if name == "general_chat":
        ok = mode == "general_chat"
        return ok, f"mode={mode}"

    if name == "no_crash":
        # Any graceful outcome is acceptable; only hard pipeline errors fail.
        if mode == "error" and err == "sql_execution_failed":
            return False, f"hard failure: {detail[:120]}"
        return True, f"graceful mode={mode} rows={n}"

    if name == "data_limitation":
        return is_limitation, f"mode={mode}"

    if name == "rows_or_limitation":
        if is_limitation:
            return True, "honest data limitation"
        if mode == "error":
            return False, f"mode=error: {detail[:120]}"
        return n >= 1, f"{n} rows"

    if name == "rows_or_clarify":
        if is_clarify:
            return True, "clarification (expected)"
        if mode == "error":
            return False, f"mode=error: {detail[:120]}"
        return n >= 1, f"{n} rows"

    if name == "rows_or_empty_ok":
        # Genuinely empty result sets are valid answers; SQL failure is not.
        if mode == "error":
            return False, f"mode=error: {detail[:120]}"
        if is_limitation:
            return True, "data limitation"
        return True, f"{n} rows"

    if mode == "error":
        return False, f"mode=error: {detail[:120]}"
    if is_limitation:
        return False, f"unexpected data_limitation: {detail[:120]}"

    if name == "rows_min_1":
        return n >= 1, f"{n} rows"

    m = re.fullmatch(r"rows_exact_(\d+)", name)
    if m:
        need = int(m.group(1))
        return n == need, f"expected exactly {need}, got {n}"

    m = re.fullmatch(r"rows_(\d+)_to_(\d+)", name)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return lo <= n <= hi, f"expected {lo}-{hi} rows, got {n}"

    return not bool(err), f"default check, rows={n}"


def run_one(question: str, prior: dict | None = None) -> dict:
    db = SessionLocal()
    try:
        kwargs: dict = {}
        if prior:
            kwargs["prior_plan"] = prior.get("query_plan")
            kwargs["prior_sql"] = prior.get("sql") or ""
            kwargs["prior_rows"] = _rows(prior)
            kwargs["prior_question"] = prior.get("question") or ""
            kwargs["prior_status"] = str(prior.get("answer_status") or "")
        return run_adaptive_orchestrator(question, db, _execute_sql, **kwargs)
    finally:
        db.close()


def main() -> int:
    results: list[dict] = []
    passed = failed = 0
    t0 = time.time()
    chains: dict[str, dict] = {}

    plan = [(t[0], t[1], t[2], t[3], None) for t in TESTS] + list(FOLLOWUPS)
    print(f"Extended QA battery started {datetime.now().isoformat()} — {len(plan)} questions\n")

    for tid, question, exp, category, chain_key in plan:
        print(f"[{tid}] ({category}) {question}")
        t1 = time.time()
        try:
            prior = chains.get(chain_key) if chain_key else None
            out = run_one(question, prior)
            ok, note = expect(exp, out, question)
            elapsed = round(time.time() - t1, 1)

            log = out.get("pipeline_log") or (out.get("query_plan") or {}).get("pipeline_log") or {}
            src = log.get("PIPELINE_3_SQL_GENERATION") if isinstance(log, dict) else None
            source = src.get("source", "") if isinstance(src, dict) else ""

            results.append({
                "id": tid,
                "category": category,
                "question": question,
                "expectation": exp,
                "pass": ok,
                "note": note,
                "seconds": elapsed,
                "mode": _mode(out),
                "rows": len(_rows(out)),
                "error": out.get("error"),
                "source": source,
                "sql_prefix": _sql(out)[:220],
                "answer_prefix": _detail(out)[:220],
            })
            print(f"  => {'PASS' if ok else 'FAIL'} ({elapsed}s, rows={len(_rows(out))}, mode={_mode(out)}) {note}")
            if not ok:
                print(f"  detail: {_detail(out)[:220]}")
            if ok:
                passed += 1
            else:
                failed += 1
            if chain_key and chain_key not in chains:
                chains[chain_key] = {**out, "question": question}
        except Exception as exc:
            failed += 1
            results.append({
                "id": tid, "category": category, "question": question,
                "expectation": exp, "pass": False, "note": f"EXCEPTION: {exc}",
                "seconds": round(time.time() - t1, 1),
            })
            print(f"  => FAIL EXCEPTION: {exc}")
        print()

    total = round(time.time() - t0, 1)
    by_cat: dict[str, dict] = {}
    for r in results:
        c = r.get("category") or "?"
        by_cat.setdefault(c, {"pass": 0, "fail": 0})
        by_cat[c]["pass" if r.get("pass") else "fail"] += 1

    summary = {
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "total_seconds": total,
        "by_category": by_cat,
        "results": results,
    }
    out_path = os.path.join(os.path.dirname(__file__), "qa_extended_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("=" * 64)
    for c, v in sorted(by_cat.items()):
        print(f"  {c:<10} {v['pass']} passed / {v['fail']} failed")
    print("=" * 64)
    print(f"DONE: {passed} passed, {failed} failed of {len(results)} — {total}s total")
    print(f"Results: {out_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
