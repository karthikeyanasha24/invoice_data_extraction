"""Governed tests for the interrogative sales-ranking normalizer.

The normalizer must rewrite failing interrogative sales/revenue ranking phrasings
into the canonical governed form, and must NEVER touch other governed intents
(profit/margin/COGS/count/inventory/supplier) or already-working phrasings.
"""
from __future__ import annotations

from app.services.ranking_question_normalizer import normalize_ranking_question as N


def test_client_exact_question_is_rewritten() -> None:
    q = "Can you show me which customer and country and industry the highest sales reflected?"
    assert N(q) == "top customers by sales with countries and industries"


def test_customer_sales_ranking_variants() -> None:
    assert N("Which customer had the highest sales?") == "top customers by sales"
    assert N("Which customer generated the most sales") == "top customers by sales"
    assert N("Which customer reflects the highest sales") == "top customers by sales"
    assert N("Who had the highest sales?") == "top customers by sales"
    assert N("Who generated the most revenue?") == "top customers by revenue"


def test_period_and_limit_preserved() -> None:
    assert N("Which customer had the highest sales in 2004?") == "top customers by sales in 2004"
    assert N("Which top 5 customers had the highest sales?") == "top 5 customers by sales"


def test_country_primary_rewrites_correctly() -> None:
    assert N("Which country had the highest sales?") == "top countries by sales"


def test_sales_orders_not_rewritten_to_billing_ranking() -> None:
    q = "Which customers had the highest sales orders?"
    assert N(q) == q
    assert N("Show me sales from VBAK") == "Show me sales from VBAK"
    # Governed engine does not return the correct dimension for these as a primary,
    # so an honest failure is preferable to a wrong-dimension answer.
    assert N("Which industry had the highest sales?") == "Which industry had the highest sales?"
    assert N("Which product had the highest sales?") == "Which product had the highest sales?"


def test_other_intents_untouched() -> None:
    keep = [
        "Show me the products with the highest profits.",
        "Show highest sales for 2004 with customer and industry.",
        "Show supplier concentration.",
        "Show top 3.",
        "Which products have the highest inventory?",
        "Which quarter had the highest gross profit?",
        "Which quarter had the biggest decline?",
        "Compare 2004 and 2005.",
        "top customers by sales",
        "Show me cost of goods.",
        "Which products have the lowest margins?",
        "Show their suppliers.",
        "What is the meaning of life?",
        "Show net profit.",
    ]
    for q in keep:
        assert N(q) == q, f"must not rewrite: {q!r} -> {N(q)!r}"


def test_no_metric_or_no_rank_not_rewritten() -> None:
    assert N("Which customer bought pumps?") == "Which customer bought pumps?"
    assert N("Show customers.") == "Show customers."
    assert N("") == ""
