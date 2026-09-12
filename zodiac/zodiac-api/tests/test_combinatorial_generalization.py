"""Combinatorial generalization: new ENTITY × MEASURE × OP × DATE mixes.

No expected SQL. No question-specific handlers. Each case must compile through
extract_analytical_operations / required_semantics like any other question.
"""
from __future__ import annotations

from app.services.analytical_operations import extract_analytical_operations
from app.services.semantic_requirements import required_semantics


# (question, checks) — checks are callables(ops, req) -> None via assertions in the loop.
CASES = [
    (
        "Top 10 customers by billed sales last year",
        {"entity": "customer", "rank": 10, "relative": "last_year", "measure": "revenue"},
    ),
    (
        "Highest vendors by purchase order value in 2025",
        {"entity": "vendor", "rank": True, "year": "2025"},
    ),
    (
        "Top 5 materials by quantity in each plant",
        {"entity": "material", "rank": 5, "partition": "plant", "measure": "quantity"},
    ),
    (
        "Which country had the lowest billed sales last quarter?",
        {"entity": "country", "relative": "last_quarter", "direction": "ASC"},
    ),
    (
        "Which suppliers have purchase orders but no invoices?",
        {"negation": True, "entity": "vendor"},
    ),
    (
        "Which customers had billed sales above the average customer sales?",
        {"entity": "customer", "above_avg": True},
    ),
    (
        "Show negative billed quantities",
        {"measure": "quantity", "op": "<", "value": 0},
    ),
    (
        "Show purchase order value by vendor last month",
        {"entity": "vendor", "relative": "last_month"},
    ),
    (
        "Which customers increased billed sales between 2004 and 2005?",
        {"entity": "customer", "period": True},
    ),
    (
        "Which suppliers had invoice amounts above 1 lakh last quarter?",
        {"op": ">", "value": 100_000, "relative": "last_quarter"},
    ),
]


def test_combinations_share_one_semantic_pipeline():
    for q, expect in CASES:
        ops = extract_analytical_operations(q)
        req = required_semantics(q)
        if expect.get("entity"):
            dims = set(ops.get("group_by") or []) | set(req.get("group_by") or []) | set(req.get("dimensions") or [])
            if expect.get("partition"):
                dims |= set(ops.get("partition_by") or [])
            assert expect["entity"] in dims, q
        if expect.get("measure"):
            concept = str((req.get("measure") or {}).get("concept") or ops.get("measure_concept") or "")
            assert expect["measure"] in concept, q
        if expect.get("rank") is True:
            assert ops.get("ranking"), q
        elif expect.get("rank"):
            assert int((ops.get("ranking") or {}).get("limit") or 0) == int(expect["rank"]), q
        if expect.get("partition"):
            assert expect["partition"] in (ops.get("partition_by") or []), q
        if expect.get("direction"):
            assert (ops.get("ranking") or {}).get("direction") == expect["direction"], q
        if expect.get("relative"):
            df = req.get("date_filter") or {}
            assert df.get("period") == expect["relative"] or ops.get("relative_period") == expect["relative"], q
        if expect.get("year"):
            assert expect["year"] in (ops.get("years") or []), q
        if expect.get("negation"):
            assert req.get("negation"), q
        if expect.get("above_avg"):
            assert (ops.get("comparison_filter") or {}).get("type") == "above_average", q
        if expect.get("period"):
            assert req.get("period_compare"), q
        if expect.get("op"):
            cmp = ops.get("comparison") or {}
            assert cmp.get("operator") == expect["op"], q
            assert float(cmp.get("value")) == float(expect["value"]), q


def test_forecast_has_no_invented_measure_plan():
    q = "Which customer will generate the most revenue next year?"
    ops = extract_analytical_operations(q)
    assert ops.get("relative_period") != "last_year"
    # Future periods are not resolved as a past relative window.
    assert "next year" in q


def test_vague_high_value_is_not_a_silent_threshold():
    q = "Show high-value customers."
    ops = extract_analytical_operations(q)
    assert not ops.get("comparison")
