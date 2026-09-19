"""Prove ChatGPT-style adaptive path on 10 mixed questions (no HTTP required).

Runs run_adaptive_orchestrator with real LLM keys from .env / .env.local.
Fails if canned capability_summary / no_business_signal / greeting_fast appear.

Usage (from zodiac-api):
  .venv\\Scripts\\python scripts\\chatgpt_style_10q_proof.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)
load_dotenv(ROOT / ".env.vercel", override=True)
sys.path.insert(0, str(ROOT))

from app.services.adaptive_analyst.orchestrator import run_adaptive_orchestrator
from app.services.adaptive_analyst.database_metadata import answer_database_metadata
from app.data_catalog.physical import load_physical_schema

CANNED_MARKERS = [
    "i can answer governed questions across",
    "didn't catch a business metric",
    "83 migrated sap business tables",
    "hi there! how can i help you today?",
]

# 10 questions: random chat + related table/sales continuity
QUESTIONS: List[Tuple[str, str]] = [
    ("hai how are you", "chat"),
    ("what can you answer?", "capability"),
    ("is that hardcoded or do you decide dynamically?", "chat"),
    ("list out the tables", "metadata"),
    ("how many tables are there?", "metadata"),
    ("which tables look related to customers?", "metadata"),
    ("ok list the sales for top customers", "analytics_or_clarify"),
    ("what did you just tell me about tables?", "chat_tables_memory"),
    ("can you explain that simpler?", "chat"),
    ("show billed sales by customer top 5", "analytics_run"),
]


def _bad_canned(text: str) -> Optional[str]:
    low = (text or "").lower()
    for m in CANNED_MARKERS:
        if m in low:
            return m
    return None


def _schema() -> Dict[str, Any]:
    try:
        return load_physical_schema() or {}
    except Exception:
        return {"VBAK": [{"name": "VBELN"}], "KNA1": [{"name": "KUNNR"}]}


def main() -> int:
    if not (
        os.getenv("OPEN_AI_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GEMINI_API_KEY")
    ):
        print("FAIL: no LLM API key in env (.env / .env.local)")
        return 2

    schema = _schema()
    prior_q = ""
    prior_plan: Optional[Dict[str, Any]] = None
    prior_status = ""
    prior_sql = ""
    results: List[Dict[str, Any]] = []
    passed = 0

    def _exec_sql(_db, sql, _q=""):
        # Analytics may attempt SQL — return empty safe rows (proof is routing + no canned).
        return []

    for i, (q, expect) in enumerate(QUESTIONS, 1):
        t0 = time.time()
        try:
            out = run_adaptive_orchestrator(
                q,
                MagicMock(),
                _exec_sql,
                use_sap=False,
                prior_question=prior_q,
                prior_plan=prior_plan,
                prior_status=prior_status,
                prior_sql=prior_sql,
                schema_for_metadata=schema,
            )
        except Exception as exc:
            print(f"{i:2}. FAIL  [{expect}] {q}")
            print(f"    exception: {type(exc).__name__}: {exc}")
            results.append({"q": q, "ok": False, "error": str(exc)})
            continue

        elapsed = round(time.time() - t0, 1)
        summary = (out.get("summary") or out.get("answer") or "")[:220]
        mode = str(out.get("mode") or "")
        status = str(out.get("answer_status") or out.get("status") or "").upper()
        method = str(out.get("sql_generation_method") or "")
        meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
        understood = bool(meta.get("understanding_model_called"))
        intent = str(meta.get("selected_capability") or "")
        canned = _bad_canned(summary)

        ok = True
        reasons: List[str] = []
        if canned:
            ok = False
            reasons.append(f"canned:{canned}")
        if method == "greeting_fast":
            ok = False
            reasons.append("greeting_fast")
        if expect in {"chat", "capability"} and not understood:
            ok = False
            reasons.append("no_understanding")
        if expect == "capability" and intent not in {"capability", "conversation", "knowledge"}:
            # allow conversation if model phrased it as chat about abilities
            if "can" not in summary.lower() and "help" not in summary.lower():
                ok = False
                reasons.append(f"bad_capability_intent:{intent}")
        if expect == "metadata":
            if mode not in {"database_metadata", "clarification"} and "table" not in summary.lower():
                ok = False
                reasons.append(f"not_metadata:{mode}")
        if expect == "analytics_or_clarify":
            if status not in {"SUCCESS", "SUCCESS_EMPTY", "CLARIFICATION", "CANNOT_ANSWER"}:
                ok = False
                reasons.append(f"bad_status:{status}")
            if "didn't catch a business metric" in summary.lower():
                ok = False
                reasons.append("no_business_signal")
        if expect == "chat":
            if mode != "general_chat" and status == "CLARIFICATION" and "business metric" in summary.lower():
                ok = False
                reasons.append("metric_clarify_on_chat")
        if expect == "chat_tables_memory":
            if not understood or mode != "general_chat":
                ok = False
                reasons.append(f"bad_memory_mode:{mode}")
            low = summary.lower()
            remembers = (
                ("121" in summary)
                or ("35" in summary and "customer" in low)
                or ("kna1" in low)
                or (
                    bool(re.search(r"\b(afko|vbak|kna1|customers?)\b", low))
                    and "table" in low
                    and "didn" not in low
                )
            )
            if "didn" in low and "table" in low and "121" not in summary:
                remembers = False
            if not remembers:
                ok = False
                reasons.append("forgot_table_context")
        if expect == "analytics_run":
            if status == "CLARIFICATION":
                ok = False
                reasons.append("should_not_clarify")
            if "didn't catch a business metric" in summary.lower():
                ok = False
                reasons.append("no_business_signal")
            if mode not in {"database_analysis", "data_limitation", "error"} and status not in {
                "SUCCESS",
                "NO_DATA",
                "SUCCESS_EMPTY",
                "CANNOT_ANSWER",
            }:
                ok = False
                reasons.append(f"expected_analytics_got:{mode}/{status}")
            if mode == "database_analysis" or status in {"SUCCESS", "NO_DATA", "SUCCESS_EMPTY"}:
                pass  # routed to analytics — pass even if mock SQL empty
            elif not understood:
                ok = False
                reasons.append("no_understanding")

        if ok:
            passed += 1
        tag = "PASS" if ok else "FAIL"
        print(f"{i:2}. {tag}  {elapsed:5.1f}s mode={mode} status={status} intent={intent} understood={understood}")
        print(f"    Q: {q}")
        print(f"    A: {summary}")
        if reasons:
            print(f"    why: {', '.join(reasons)}")

        results.append(
            {
                "q": q,
                "ok": ok,
                "mode": mode,
                "status": status,
                "intent": intent,
                "understood": understood,
                "method": method,
                "summary": summary,
                "reasons": reasons,
            }
        )
        prior_q = q
        prior_plan = out.get("query_plan") if isinstance(out.get("query_plan"), dict) else prior_plan
        prior_status = status
        prior_sql = str(out.get("sql") or "")

    print(f"\nSUMMARY: {passed}/{len(QUESTIONS)} passed")
    out_path = ROOT / "chatgpt_style_10q_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0 if passed == len(QUESTIONS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
