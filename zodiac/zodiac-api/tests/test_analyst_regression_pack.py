from app.services.analyst_agent import _is_complete_analytical_request
from app.services.analytical_operations import extract_analytical_operations

GOLDEN_QUESTIONS = [
    "Hi",
    "How many tables?",
    "What can you do?",
    "Show me the lowest sales for the year 2000 by country, customer, and product.",
    "Top 10 customers by billed sales",
    "Show the highest sales by country.",
    "Show me highest sales for the year 2004 with customer and industry",
    "Show the top 10 customers by billed sales, with currency shown separately.",
    "Break down by country",
    "Only for year 2000",
    "Show me the SQL",
    "Show me negative sales for the year 2000",
    "List customer names",
    "How many billing documents in 2000?",
    "Show the products with the highest profits.",
    "Show me the lowest negative billed sales in calendar year 2000 and compare with 2001.",
    "Year over year billed sales for 2000 vs 2001",
    "Show me the growth.",
    "How much?",
]

PROVE_FAILURES = [
    GOLDEN_QUESTIONS[3],
    GOLDEN_QUESTIONS[14],
    "Did the insurance company in 2004 have any sales?",
]


def test_regression_pack_covers_the_nineteen_analyst_questions():
    assert len(GOLDEN_QUESTIONS) == 19
    assert GOLDEN_QUESTIONS[3].startswith("Show me the lowest sales for the year 2000")
    assert "highest profits" in GOLDEN_QUESTIONS[14]


def test_prove_failures_are_complete_analytical_requests():
    for question in PROVE_FAILURES:
        assert _is_complete_analytical_request(question), question


def test_lowest_sales_2000_requires_all_three_dimensions():
    ops = extract_analytical_operations(GOLDEN_QUESTIONS[3])
    assert {"country", "customer", "material"} <= set(ops.get("group_by") or [])
