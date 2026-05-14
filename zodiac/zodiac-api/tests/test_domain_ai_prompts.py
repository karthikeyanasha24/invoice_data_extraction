"""Domain 'What can you ask?' prompts: operational resolver must not steal SAP questions."""

from __future__ import annotations

from typing import List, Optional, Tuple

import pytest

from app.services.operational_query_resolver import (
    _is_operational_question,
    resolve_operational_query,
)

# Sync with zodiac-front/src/components/DashboardAIAnalysis.tsx DOMAIN_QUERY_EXAMPLES
DOMAIN_ROWS: List[Tuple[str, str, Optional[str]]] = [
    (
        "Invoices & Billing",
        "Top sold-to customers (KUNAG) by SUM(vbrp.NETWR) for calendar year 2004 using VBRK.FKDAT year filter",
        None,
    ),
    (
        "Invoices & Billing",
        "Total billed amount: SUM(vbrp.NETWR) with VBRK join for FKDAT calendar year 2004",
        None,
    ),
    (
        "Invoices & Billing",
        "Sample VBRK billing headers for year 2004: VBELN, FKART, WAERK, FKDAT, NETWR (LIMIT 50)",
        None,
    ),
    (
        "Invoices & Billing",
        "Count vbrp billing lines for 2004 grouped by VBRK.FKART (billing type)",
        None,
    ),
    (
        "Invoices & Billing",
        "Compare total vbrp.NETWR revenue between calendar years 2003 and 2004 using VBRK.FKDAT filters",
        None,
    ),
    (
        "Deliveries & Logistics",
        "Show LIKP delivery headers joined to LIPS lines for WADAT year 2004: VBELN, MATNR, LFIMG, WERKS (LIMIT 100)",
        None,
    ),
    (
        "Deliveries & Logistics",
        "Summarize LIPS delivery quantities by LFART from LIKP for year 2004",
        None,
    ),
    (
        "Deliveries & Logistics",
        "Sample open-delivery pattern: LIKP for 2004 with VBELN, LFART, WADAT, KUNNR (LIMIT 50)",
        None,
    ),
    (
        "Deliveries & Logistics",
        "Which LFART delivery types occur most in LIKP headers for year 2004?",
        None,
    ),
    (
        "Sales Orders",
        "Show VBAK sales order headers with VBAP lines for ERDAT year 2004: VBELN, AUART, MATNR, KWMENG (LIMIT 100)",
        None,
    ),
    (
        "Sales Orders",
        "Which VBAK orders from ERDAT year 2004 look not fully delivered vs VBAP quantities (sample LIMIT 40)",
        None,
    ),
    (
        "Sales Orders",
        "VBEP schedule lines with EDATU for orders in 2004: VBELN, POSNR, ETENR, EDATU, WMENG (LIMIT 100)",
        None,
    ),
    (
        "Sales Orders",
        "KONV pricing conditions (KSCHL, KBETR, WAERS) for VBAK documents in 2004 via KNUMV (LIMIT 80)",
        None,
    ),
    (
        "Purchasing",
        "Top vendors by SUM(EKPO.NETWR) for purchase orders with EKKO.BEDAT in calendar year 2004",
        None,
    ),
    (
        "Purchasing",
        "Open purchase requisitions EBAN with BADAT in 2004 and LOEKZ empty (LIMIT 50)",
        None,
    ),
    (
        "Purchasing",
        "Sample RBKP logistics invoice headers with RSEG lines referencing EBELN from 2004 (LIMIT 40)",
        None,
    ),
    (
        "Purchasing",
        "Purchasing info EINA/EINE with material keys tied to EKPO lines for POs in 2004 (LIMIT 40)",
        None,
    ),
    (
        "Master Data",
        "Customer master KNA1 joined KNVV: KUNNR, NAME1, VKORG, VTWEG, SPART (LIMIT 60)",
        None,
    ),
    (
        "Master Data",
        "KNA1 customer names with KNBK bank details where LAND1 is populated (LIMIT 40)",
        None,
    ),
    (
        "Master Data",
        "Material master MARA with MARC plant data and MARD storage stock snapshot (LIMIT 50)",
        None,
    ),
    (
        "Master Data",
        "Vendor LFA1 with LFB1 company code and LFM1 purchasing org data (LIMIT 50)",
        None,
    ),
    (
        "Finance / GL",
        "Sample FAGLFLEXA GL actual lines for fiscal year 2004: RYEAR, RACCT, DRCRK, HSL (LIMIT 100)",
        None,
    ),
    (
        "Finance / GL",
        "BKPF accounting document headers with BSEG lines for GJAHR 2004 and BUDAT filter (LIMIT 50)",
        None,
    ),
    (
        "Finance / GL",
        "BSAD customer open items sample joined to KNA1 NAME1 (LIMIT 50)",
        None,
    ),
    (
        "Finance / GL",
        "Sample COEP CO object postings for GJAHR 2004 with OBJNR and WRTTP (LIMIT 80)",
        None,
    ),
    (
        "Costing & CO-PA",
        "CKIS cost estimate items with CKHS costing run header for KALDAT in 2004 (LIMIT 50)",
        None,
    ),
    (
        "Costing & CO-PA",
        "KEPH cost components with KEKO product costing header sample for 2004 (LIMIT 40)",
        None,
    ),
    (
        "Costing & CO-PA",
        "Sample CE1PR22 CO-PA actual line rows if the table exists — filter by calendar year 2004 fields (LIMIT 30)",
        None,
    ),
    (
        "Costing & CO-PA",
        "CKMLPR material ledger prices with CKMLPP period data sample (LIMIT 40)",
        None,
    ),
    (
        "Zodiac / EDI",
        "EDI status: count succeeded vs failed EDI submissions by Zodiac account for the last 30 days",
        "edi_customer_status",
    ),
    (
        "Zodiac / EDI",
        "Show average total amount and tax amount by currency from invoice app tables (invoice_v2_business_data, last 90 days)",
        "invoice_amount_tax_by_currency",
    ),
    (
        "Zodiac / EDI",
        "Show outbound process flow with document counts per V2 funnel stage (v2_invoice_documents, v2_validated_invoices)",
        "outbound_funnel",
    ),
    (
        "Zodiac / EDI",
        "Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers (sat_canonical_merged)",
        "inbound_sat_merge",
    ),
    (
        "Cross-cutting",
        "VBFA document flow for a VBRK billing document in 2004: show preceding sales order and delivery VBELN chain (LIMIT 40)",
        None,
    ),
    (
        "Cross-cutting",
        "SAT raw documents sat_documents: status distribution and sample supplier RFC rows (LIMIT 40)",
        None,
    ),
    (
        "Cross-cutting",
        "Sample rows from sat_company_mappings (supplier RFC, company keys) LIMIT 40",
        None,
    ),
    (
        "Cross-cutting",
        "Top sold-to KUNAG by SUM(vbrp.NETWR) in 2004 with KNA1.NAME1 customer name join",
        None,
    ),
]


@pytest.mark.parametrize("category,question,expected_op", DOMAIN_ROWS)
def test_domain_question_operational_route(
    category: str, question: str, expected_op: Optional[str]
) -> None:
    out = resolve_operational_query(question, time_scope="current", api_key=None)
    got = None if out is None else out[1]
    assert got == expected_op, f"{category}: {got!r} != {expected_op!r} for {question[:80]}..."


def test_ambiguous_sap_top_customer_not_operational() -> None:
    q = "Show invoices for the top customer in the last 30 days"
    assert resolve_operational_query(q, time_scope="current", api_key=None) is None
    assert _is_operational_question(q) is False
