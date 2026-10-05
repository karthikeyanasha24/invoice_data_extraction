"""Real-model clarification continuity and read-only database acceptance checks.

Reports contain query diagnostics, never credentials or database result rows.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", encoding="utf-8-sig")

CASES = [
    {
        "name": "reported_invoice_order_choice",
        "question": "Show me lowest negative sales in the year 2000 and make comparison with the year 2001",
        "clarification": "Do you want the bottom 10 negative amounts at the invoice level, by customer, by product, or another dimension? Should I compare the same dimension in 2001?",
        "reply": "Use first invoices to compare and then compare with sales orders relevant to those linked invoices",
        "terms": ["2000", "2001", "invoice", "order"],
    },
    {
        "name": "purchasing_grouping_choice",
        "question": "Compare purchasing costs in 2012 and 2013.",
        "clarification": "Should I group costs by supplier or by product?",
        "reply": "By supplier, both absolute and percent change for those periods.",
        "terms": ["2012", "2013", "supplier"],
    },
    {
        "name": "stock_grouping_choice",
        "question": "Show the highest stock balances for 2022.",
        "clarification": "Should I rank products or warehouses?",
        "reply": "Warehouses, twenty of them.",
        "terms": ["2022", "warehouse"],
    },
    {
        "name": "accept_proposed_defaults",
        "question": "Compare billed sales in 2018 and 2019.",
        "clarification": "I can compare total billed sales in each calendar year separately by currency with absolute and percentage change. Shall I use those defaults?",
        "reply": "Yes lets see",
        "terms": ["2018", "2019"],
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["understanding", "pipeline"], default="understanding")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    from app.services.adaptive_analyst.understanding import understand_turn
    reports = []
    for case in CASES if args.phase == "understanding" else CASES[:1]:
        question, clarification, reply = (case[key] for key in ("question", "clarification", "reply"))
        # This is the historic unanswered clarification supplied by the user,
        # not a successful query artifact. Test the production legacy status
        # shape as well as the model's new pending-request classification.
        plan = {"last_mode": "clarification", "investigation_state": {
            "mode": "clarification", "last_summary": clarification,
            "recent_turns": [{"role": "user", "content": question},
                             {"role": "assistant", "content": clarification, "mode": "clarification"}],
        }}
        started = time.monotonic()
        if args.phase == "understanding":
            # Understanding-only verification sends user/synthetic conversation
            # and generic rules, with no internal schema or result evidence.
            result = understand_turn(reply, prior_question=question, prior_status="CLARIFICATION", prior_plan=plan, capability_context={})
            report = {"case": case["name"], "verification_scope": "turn_continuity_only", "provider": result.provider, **result.to_public_dict()}
            resolved = str(result.resolved_question or "").lower()
            report["passed"] = result.turn_relation == "clarification_answer" and result.context_source == "pending_request" and all(term in resolved for term in case["terms"])
        else:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from app.api.adaptive_query import _post_query_adaptive_body

            url = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL is not configured")
            engine = create_engine(url.replace("postgresql+asyncpg://", "postgresql://"), connect_args={"connect_timeout": 5, "options": "-c default_transaction_read_only=on"})
            with sessionmaker(bind=engine)() as db:
                result = _post_query_adaptive_body(
                    q=reply, original_question=reply, tableHint=None, overrideSql=None,
                    threadId=None, investigationId=None, db=db, current_user=None,
                    contextData={"previousQuestion": question, "previousSQL": "", "previousAnswerStatus": "CLARIFICATION", "previousPlan": plan, "data": []},
                )
                db.rollback()
            report = {"case": case["name"], **{key: result.get(key) for key in (
                "answer_status", "failure_class", "sql_status", "rowCount", "resolved_question", "sql", "summary", "meta", "query_plan")}}
            report["passed"] = result.get("answer_status") in {"SUCCESS", "NO_DATA"}
        report["latency_s"] = round(time.monotonic() - started, 2)
        reports.append(report)
        print(json.dumps({key: report.get(key) for key in (
            "case", "passed", "latency_s", "intent", "turn_relation", "context_source", "resolved_question", "answer_status", "failure_class", "sql_status", "rowCount", "summary")}, default=str), flush=True)
    output = ROOT / "scripts" / f"pending_analysis_{args.phase}_verification.json"
    output.write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
    return 0 if all(report["passed"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
