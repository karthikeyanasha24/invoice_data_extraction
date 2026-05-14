"""Ensure Dashboard AI Real-time chip prompts map to operational fast paths (or SAP fallthrough)."""

from __future__ import annotations

from typing import Optional

import pytest

from app.services.operational_query_resolver import resolve_operational_query

# Keep in sync with zodiac-front/src/components/DashboardAIAnalysis.tsx REALTIME_PROMPTS[].query
REALTIME_QUERIES = [
    (
        "Failed invoices",
        "Summarize failed invoices and main failure reasons in the last 30 days (Zodiac EDI failure tables)",
        "failed_invoices_summary",
    ),
    (
        "Inbound SAT",
        "Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers (sat_canonical_merged)",
        "inbound_sat_merge",
    ),
    (
        "Top customers",
        "Show top customers with currency and ranked invoice counts from extracted Zodiac invoice business data (last 30 days)",
        "top_customers_business_currency",
    ),
    (
        "Outbound flow",
        "Show outbound process flow with document counts per V2 funnel stage (received, validated, failed, pending)",
        "outbound_funnel",
    ),
    (
        "EDI status",
        "EDI status: count succeeded vs failed EDI submissions by Zodiac account for the last 30 days",
        "edi_customer_status",
    ),
    (
        "Conversion rate",
        "What is the V2 invoice conversion success rate versus documents received, and which funnel step shows the largest backlog?",
        "invoice_conversion_kpi",
    ),
    (
        "Open orders",
        "Show open purchase requisitions (EBAN) and purchase orders that are still pending in SAP",
        None,
    ),
    (
        "Delivery status",
        "Show recent delivery header and item status for current shipments from LIKP and LIPS tables",
        None,
    ),
]


@pytest.mark.parametrize("label,query,expected_type", REALTIME_QUERIES)
def test_realtime_prompt_resolves_operational(
    label: str, query: str, expected_type: Optional[str]
) -> None:
    out = resolve_operational_query(query, time_scope="current", api_key=None)
    if expected_type is None:
        assert out is None, f"{label}: expected SAP/LangGraph fallthrough, got {out}"
        return
    assert out is not None, f"{label}: expected operational SQL, got None"
    _sql, qtype = out
    assert qtype == expected_type, f"{label}: got {qtype}, want {expected_type}"


def test_augmented_routing_prefix_does_not_block_operational() -> None:
    q = """[ZODIAC_GENERATIVE_CLIENT_ROUTING v=1]
routing_bucket: Billing & revenue (billing_sales)
[/ZODIAC_GENERATIVE_CLIENT_ROUTING]

User question:
EDI status: count succeeded vs failed EDI submissions by Zodiac account for the last 30 days"""
    out = resolve_operational_query(q, time_scope="current", api_key=None)
    assert out is not None
    assert out[1] == "edi_customer_status"
