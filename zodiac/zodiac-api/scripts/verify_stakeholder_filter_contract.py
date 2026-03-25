"""
Lightweight SQL contract test for stakeholder-critical prompts.

Fails when generated deterministic SQL for fixed questions does not contain the
required filter/metric structure (year via FKDAT, billing category, count vs sum).
"""

from __future__ import annotations

import os
import sys
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ai_analysis_constraint_validator import validate_sql_against_user_constraints
from app.services.deterministic_sql_resolver import resolve_deterministic_sql


def _assert_ok(question: str) -> None:
    sql = resolve_deterministic_sql(question, available_tables=["VBRK", "VBRP"])
    if not sql:
        raise AssertionError(f"No deterministic SQL for question: {question}")
    ok, failures = validate_sql_against_user_constraints(sql, question)
    if not ok:
        raise AssertionError(
            "Constraint contract failed.\n"
            f"Question: {question}\n"
            f"SQL: {sql}\n"
            f"Failures: {failures}"
        )


def main() -> int:
    scenarios: List[str] = [
        "invoice count for year 1999 and billing category X",
        "total sales for year 1999 and billing category X in USD",
    ]
    for q in scenarios:
        _assert_ok(q)
        print(f"OK: {q}")
    print("All stakeholder SQL contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

