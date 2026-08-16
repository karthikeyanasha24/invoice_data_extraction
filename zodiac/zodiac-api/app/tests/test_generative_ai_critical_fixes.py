"""Regression tests for live Generative AI critical fixes (post LIVE_UI_VALIDATION FAILED)."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.api.adaptive_query import (
    _annotate_answer_status,
    _cannot_answer_payload,
    _guardrail_intent_text,
    _is_sap_erp_intent,
    _sql_guardrail_violations,
    _table_has_column,
)
from app.services.ai_followup_routing import resolve_follow_up_sql_need
from app.services.ai_query_plan import extract_query_plan


CLIENT_Q = "Show me highest sales for the year 2004 with customer and industry"

_VALID_INDUSTRY_SQL = """
SELECT
  COALESCE(c."name1", 'Unknown / unmapped') AS customer_name,
  COALESCE(t."brtxt", 'Not available') AS industry,
  k."waerk" AS currency,
  SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
FROM "VBRK" k
LEFT JOIN "KNA1" c
  ON LPAD(TRIM(k."kunag"), 10, '0') = LPAD(TRIM(c."kunnr"), 10, '0')
LEFT JOIN "T016T" t
  ON TRIM(CAST(c."brsch" AS TEXT)) = TRIM(CAST(t."brsch" AS TEXT))
WHERE TRIM(COALESCE(k."fkdat", '')) <> ''
  AND SUBSTRING(TRIM(k."fkdat"), 1, 4) = '2004'
GROUP BY
  COALESCE(c."name1", 'Unknown / unmapped'),
  COALESCE(t."brtxt", 'Not available'),
  k."waerk"
ORDER BY total_sales DESC
LIMIT 20
"""


def test_t016t_has_no_spras_in_live_schema():
    assert _table_has_column("T016T", "brsch") is True
    assert _table_has_column("T016T", "brtxt") is True
    assert _table_has_column("T016T", "spras") is False


def test_t016t_without_spras_industry_sql_accepted():
    v = _sql_guardrail_violations(CLIENT_Q, _VALID_INDUSTRY_SQL)
    joined = " | ".join(v).lower()
    assert "spras" not in joined
    assert "t016t" not in joined or "industry-only" not in joined


def test_t016t_with_spras_still_requires_language_filter(monkeypatch):
    real = _table_has_column

    def fake_has(table: str, column: str) -> bool:
        if table.upper() == "T016T" and column.lower() == "spras":
            return True
        return real(table, column)

    monkeypatch.setattr("app.api.adaptive_query._table_has_column", fake_has)
    sql_no_spras = _VALID_INDUSTRY_SQL
    v = _sql_guardrail_violations(CLIENT_Q, sql_no_spras)
    assert any("spras" in x.lower() for x in v)


def test_makt_still_requires_spras():
    question = "show top materials by billed amount with description"
    sql = """
    SELECT p."matnr", t."maktx",
           SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total,
           p."waerk" AS currency
    FROM "vbrp" p
    LEFT JOIN "MAKT" t ON p."matnr" = t."matnr"
    GROUP BY p."matnr", t."maktx", p."waerk"
    ORDER BY total DESC LIMIT 20
    """
    # may also flag other issues; spras must still be required for MAKT
    v = _sql_guardrail_violations(question, sql)
    assert any("spras" in x.lower() and "makt" in x.lower() for x in v)


def test_normal_sales_not_flagged_as_zero_negative():
    q = "Show me highest sales for the year 2004 by customer"
    sql = """
    SELECT COALESCE(c."name1",'Unknown') AS customer_name, k."waerk" AS currency,
           SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
    FROM "VBRK" k
    LEFT JOIN "KNA1" c ON LPAD(TRIM(k."kunag"),10,'0') = LPAD(TRIM(c."kunnr"),10,'0')
    WHERE SUBSTRING(TRIM(k."fkdat"),1,4)='2004' AND TRIM(COALESCE(k."fkdat",'')) <> ''
    GROUP BY COALESCE(c."name1",'Unknown'), k."waerk"
    ORDER BY total_sales DESC LIMIT 5
    """
    v = _sql_guardrail_violations(q, sql)
    joined = " | ".join(v).lower()
    assert "zero-negative" not in joined
    assert "zero/negative" not in joined


def test_followup_boilerplate_does_not_trigger_zero_negative():
    plan = extract_query_plan(CLIENT_Q)
    augmented = """This is a CONTINUATION of an analysis session.
New request (generate ONE new PostgreSQL SELECT for this):
Include industry

Rules:
- For invoice zero/negative: WHERE on "VBRK"."netwr" — not vbrp.
"""
    intent = _guardrail_intent_text(augmented, plan)
    assert "zero/negative" not in intent.lower()
    assert "include industry" in intent.lower()
    v = _sql_guardrail_violations(augmented, _VALID_INDUSTRY_SQL, plan=plan)
    joined = " | ".join(v).lower()
    assert "zero/negative" not in joined
    assert "zero-negative" not in joined


def test_header_grain_blocks_vbrp_sum_for_customer_sales():
    q = "highest sales by customer in 2004"
    sql = """
    SELECT TRIM(v."kunag") AS customer,
           SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales,
           v."waerk" AS currency
    FROM vbrp p
    JOIN "VBRK" v ON LPAD(TRIM(p."vbeln"),10,'0') = LPAD(TRIM(v."vbeln"),10,'0')
    WHERE SUBSTRING(TRIM(v."fkdat"),1,4)='2004'
    GROUP BY TRIM(v."kunag"), v."waerk"
    ORDER BY total_sales DESC LIMIT 5
    """
    v = _sql_guardrail_violations(q, sql)
    assert any("header" in x.lower() or "vbrk" in x.lower() for x in v)


def test_line_grain_allows_vbrp_for_products():
    q = "Show me the top products by sales in 2004"
    plan = extract_query_plan(q)
    assert plan.grain == "line"
    sql = """
    SELECT p."matnr", t."maktx", k."waerk" AS currency,
           SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
    FROM "vbrp" p
    JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"),10,'0') = LPAD(TRIM(k."vbeln"),10,'0')
    LEFT JOIN "MAKT" t ON p."matnr" = t."matnr" AND t."spras" = 'E'
    WHERE SUBSTRING(TRIM(k."fkdat"),1,4)='2004' AND TRIM(COALESCE(k."fkdat",'')) <> ''
    GROUP BY p."matnr", t."maktx", k."waerk"
    ORDER BY total_sales DESC LIMIT 10
    """
    v = _sql_guardrail_violations(q, sql, plan=plan)
    joined = " | ".join(v).lower()
    assert "do not aggregate vbrp.netwr" not in joined


def test_currency_grouping_required_for_sales_aggregate():
    q = "total sales in 2005"
    sql = """
    SELECT SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
    FROM "VBRK" k
    WHERE SUBSTRING(TRIM(k."fkdat"),1,4)='2005'
    """
    v = _sql_guardrail_violations(q, sql)
    assert any("currency" in x.lower() for x in v)


def test_gjahr_still_rejected_for_billing_year():
    q = CLIENT_Q
    sql = """
    SELECT k."kunag", SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS s, k."waerk"
    FROM "VBRK" k WHERE k."gjahr" = '2004'
    GROUP BY k."kunag", k."waerk" ORDER BY s DESC LIMIT 5
    """
    v = _sql_guardrail_violations(q, sql)
    assert any("gjahr" in x.lower() or "fkdat" in x.lower() for x in v)


def test_sap_intent_locks_client_question():
    assert _is_sap_erp_intent(CLIENT_Q) is True


def test_invoice_count_by_customer_not_forced_sap():
    assert _is_sap_erp_intent("Show me invoice count by customer") is False


def test_cannot_answer_payload_has_contract():
    p = _cannot_answer_payload(CLIENT_Q, reason="test failure", plan=extract_query_plan(CLIENT_Q))
    assert p["answer_status"] == "CANNOT_ANSWER"
    assert p["type"] == "cannot_answer"
    assert "invoice_v2" not in (p.get("sql") or "").lower()
    assert p["rowCount"] == 0
    annotated = _annotate_answer_status({"sql": "SELECT COUNT(*) AS total_rows FROM invoice_v2_business_data", "data": [{"total_rows": 59}]})
    assert annotated["answer_status"] == "CANNOT_ANSWER"


def test_followup_deltas_change_fingerprint():
    prev = extract_query_plan(CLIENT_Q)
    need, p1 = resolve_follow_up_sql_need(
        "Only the Trading industry", CLIENT_Q, "", prev.to_dict()
    )
    assert need is True
    assert p1.fingerprint() != prev.fingerprint()
    need2, p2 = resolve_follow_up_sql_need("Now show the top 5", CLIENT_Q, "", p1.to_dict())
    assert need2 is True
    assert p2.limit == 5
    assert p2.fingerprint() != p1.fingerprint()


def test_ddl_still_not_accepted_by_guardrail_select_star():
    v = _sql_guardrail_violations("list invoices", "SELECT * FROM \"VBRK\"")
    assert any("select *" in x.lower() for x in v)
