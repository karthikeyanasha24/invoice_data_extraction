"""
Fixture tests for the negative/lowest narrative consistency guardrail.

This does NOT call the LLM. It verifies that if a narrative incorrectly
claims "all amounts are 0.0" while global stats show positive/negative values,
the deterministic guardrail rewrites the narrative to match the stats.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.negative_lowest_narrative_guard import (
    compute_global_numeric_stats,
    enforce_negative_lowest_summary_consistency,
)


def _run_case(question: str, rows: list[dict], bad_reply: str, asserts: list[str]) -> None:
    stats = compute_global_numeric_stats(rows, question=question)
    corrected = enforce_negative_lowest_summary_consistency(bad_reply, question, stats)

    if corrected == bad_reply:
        raise AssertionError("Guardrail did not correct the narrative when it should have.")

    lower = corrected.lower()
    for a in asserts:
        if a.lower() not in lower:
            raise AssertionError(f"Expected substring not found: {a}\nCorrected reply:\n{corrected}")


def main() -> int:
    question = "Negative or lowest billing line amounts for year 1999"

    # Fixture: no negatives, but non-zero positives exist.
    rows = [
        {"netwr_line_amount": 0.0, "currency": "DEM", "vbeln": "1", "posnr": "10", "fkdat": "19990101"},
        {"netwr_line_amount": 0.0, "currency": "DEM", "vbeln": "2", "posnr": "10", "fkdat": "19990102"},
        {"netwr_line_amount": 15.03, "currency": "DEM", "vbeln": "3", "posnr": "10", "fkdat": "19990103"},
        {"netwr_line_amount": 22.89, "currency": "DEM", "vbeln": "4", "posnr": "10", "fkdat": "19990104"},
    ]
    bad_reply = (
        "**Executive Summary**\n"
        "The analysis focuses on negative or lowest billing line amounts for 1999; all identified line amounts are 0.0.\n"
        "\n**Detailed Points**\n"
        "All billing line amounts listed are 0.0."
    )

    _run_case(
        question=question,
        rows=rows,
        bad_reply=bad_reply,
        asserts=[
            "no negative line amounts",
            "2 line(s) have net line amount > 0",
            "smallest positive net line amount",
            "dem 15.03",
        ],
    )

    # Fixture: negatives exist.
    rows2 = [
        {"netwr_line_amount": -5.0, "currency": "USD", "vbeln": "10", "posnr": "10", "fkdat": "19990101"},
        {"netwr_line_amount": 0.0, "currency": "USD", "vbeln": "11", "posnr": "20", "fkdat": "19990102"},
        {"netwr_line_amount": 3.0, "currency": "USD", "vbeln": "12", "posnr": "30", "fkdat": "19990103"},
    ]
    bad_reply2 = "**Executive Summary**\nAll billing line amounts listed are 0.0."

    _run_case(
        question=question,
        rows=rows2,
        bad_reply=bad_reply2,
        asserts=[
            "line(s) have net line amount < 0",
            "$-5.00".replace("$-5.00".lower(), "$-5.00".lower()),  # keep substring check stable
        ],
    )

    print("OK: negative/lowest narrative guardrail fixtures passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

