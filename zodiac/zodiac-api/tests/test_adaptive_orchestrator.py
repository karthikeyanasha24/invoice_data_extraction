from __future__ import annotations

from app.services.adaptive_analyst.capabilities import schema_capabilities
from app.services.adaptive_analyst.conversation_state import InvestigationState
from app.services.adaptive_analyst.orchestrator import (
    _force_general_chat,
    missing_result_dimensions,
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


def test_hello_never_classified_as_database_safety_net():
    assert _force_general_chat("Hello")
    assert _force_general_chat("how are you?")
    assert _force_general_chat("What is the meaning of life?")
    assert not _force_general_chat("Which customer had the highest sales?")


def test_missing_industry_dimension_detected():
    rows = [{"customer": "A", "country": "DE", "total_sales": 1}]
    missing = missing_result_dimensions(rows, ["customer", "country", "industry"])
    assert missing == ["industry"]


def test_capabilities_reports_vbed_absent_vbep_present():
    cap = schema_capabilities()
    by_name = {r["table"].upper(): r for r in cap["tables"]}
    assert by_name["VBED"]["discovered"] is False
    assert by_name["VBEP"]["discovered"] is True
    assert cap["table_count"] > 20
