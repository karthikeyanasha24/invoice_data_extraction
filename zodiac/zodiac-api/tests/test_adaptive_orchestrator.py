from __future__ import annotations

from app.services.adaptive_analyst.capabilities import schema_capabilities
from app.services.adaptive_analyst.conversation_state import InvestigationState
from app.services.adaptive_analyst.orchestrator import (
    _force_general_chat,
    _is_limit_clarify,
    _is_questionnaire,
    _is_sales_vs_billing_clarify,
    adapt_user_turn,
    missing_result_dimensions,
    resolve_sales_choice,
    resolve_topn_choice,
    ensure_default_ranking_limit,
)
from app.services.adaptive_analyst.schema_retrieval import retrieve_candidate_tables


def test_investigation_state_roundtrip():
    st = InvestigationState.from_context(
        {
            "investigation_state": {
                "metric": "sales",
                "dimensions": ["customer", "country"],
                "time_period": "2004",
            }
        },
        previous_question="highest sales",
        previous_sql="SELECT 1",
    )
    assert st.metric == "sales"
    assert "country" in st.dimensions
    assert st.time_period == "2004"
    assert st.last_sql == "SELECT 1"


def test_retrieve_sales_orders_prefers_vbak():
    tables = retrieve_candidate_tables("how many sales orders from VBAK")
    assert "VBAK" in tables


def test_retrieve_vbed_maps_to_vbep_not_invented():
    tables = retrieve_candidate_tables("show data from VBED")
    assert "VBEP" in tables


def test_sales_questionnaire_is_collapsed():
    essay = (
        "Do you mean sales orders or billed invoices? Which metrics? "
        "Which dimensions? What time period? Any filters? Preferred output? "
        "Include returns/credit memos and currency conversion?"
    )
    assert _is_questionnaire(essay)
    assert _force_general_chat("Hello")
    assert _force_general_chat("how are you?")
    assert _force_general_chat("What is the meaning of life?")
    assert not _force_general_chat("Which customer had the highest sales?")


def test_missing_industry_dimension_detected():
    rows = [{"customer": "A", "country": "DE", "total_sales": 1}]
    missing = missing_result_dimensions(rows, ["customer", "country", "industry"])
    assert missing == ["industry"]


def test_sales_choice_resolves_without_reasking():
    assert resolve_sales_choice("sales order") == "How many sales orders are there?"
    assert resolve_sales_choice("Sales orders") == "How many sales orders are there?"
    assert resolve_sales_choice("1") is None
    assert resolve_sales_choice("1", awaiting=True) == "How many sales orders are there?"
    assert resolve_sales_choice("billed invoices") == "Show the top customers by billed sales."
    assert resolve_sales_choice("2") is None
    assert resolve_sales_choice("2", awaiting=True) == "Show the top customers by billed sales."
    assert resolve_sales_choice("first") is None
    assert resolve_sales_choice("first", awaiting=True) == "How many sales orders are there?"
    assert resolve_sales_choice("the second one", awaiting=True) == "Show the top customers by billed sales."
    assert resolve_sales_choice("Who had the highest sales in 2004?") is None
    assert _is_sales_vs_billing_clarify(
        "Both sales orders and billed invoices exist. Which one do you want me to use?"
    )


def test_topn_reply_after_highest_sales():
    assert resolve_topn_choice("5", "Who had the highest sales in 2004?") == (
        "top 5 customers by sales in 2004"
    )
    assert resolve_topn_choice("five", "top customers by sales in 2004") == (
        "top 5 customers by sales in 2004"
    )
    assert resolve_topn_choice("5", "How many sales orders are there?") is None
    assert _is_limit_clarify("How many top customers should I return? Please answer with a number.")
    assert ensure_default_ranking_limit("top customers by sales in 2004") == (
        "top 10 customers by sales in 2004"
    )
    assert ensure_default_ranking_limit("top 5 customers by sales") == "top 5 customers by sales"


def test_adapt_user_turn_each_message_in_thread():
    first = adapt_user_turn("Show me our sales data.")
    assert first.action == "clarify"

    picked = adapt_user_turn(
        "sales order",
        prior_question="Show me our sales data.",
        prior_plan={"awaiting_sales_choice": True},
        prior_status="CLARIFICATION",
    )
    assert picked.action == "query"
    assert "sales orders" in picked.question.lower()

    ranking = adapt_user_turn(
        "Who had the highest sales in 2004?",
        prior_question="How many sales orders are there?",
        prior_status="SUCCESS",
    )
    assert ranking.action == "query"
    assert ranking.drop_prior is True
    assert "top 10 customers by sales" in ranking.question.lower()
    assert "2004" in ranking.question

    top5 = adapt_user_turn(
        "5",
        prior_question="Who had the highest sales in 2004?",
        prior_status="CLARIFICATION",
    )
    assert top5.action == "query"
    assert top5.question == "top 5 customers by sales in 2004"


def test_capabilities_reports_vbed_absent_vbep_present():
    cap = schema_capabilities()
    by_name = {r["table"].upper(): r for r in cap["tables"]}
    assert by_name["VBED"]["discovered"] is False
    assert by_name["VBEP"]["discovered"] is True
    assert cap["table_count"] > 20
