"""Unit tests for adaptive planner architecture (no question-specific patches)."""
from __future__ import annotations

import time

import pytest

from app.services.analytics_authority import (
    CATALOG_IS_RUNTIME_AUTHORITY,
    DETERMINISTIC_QUESTION_SQL_IS_RUNTIME_AUTHORITY,
    FOUR_STAGE_IS_SAP_ANALYTICS_AUTHORITY,
    INTENT_FAST_PATH_IS_RUNTIME_AUTHORITY,
    KEYWORD_TABLE_MAP_IS_AUTHORITY,
    SALES_ORDER_COMPILER_IS_RUNTIME_AUTHORITY,
)
from app.services.analytical_operations import extract_analytical_operations, merge_semantic_requirements
from app.services.investigation_budget import (
    InvestigationBudget,
    InvestigationTimeout,
    begin_investigation,
    cancel_investigation,
    timeout_response,
)
from app.services.plan_satisfaction import sql_satisfies_analytical_intent, result_matches_analytical_intent
from app.services.result_first_followup import try_answer_from_prior_rows
from app.services.adaptive_analyst.governed import try_governed_database


def test_by_month_is_group_by_not_grand_total():
    ops = extract_analytical_operations("Show sales order count by month")
    assert "month" in ops["group_by"]
    assert ops["aggregation"] == "COUNT"


def test_top_n_ranking_and_revenue_measure():
    ops = extract_analytical_operations("Show top 10 customers by revenue")
    assert ops["ranking"]["limit"] == 10
    assert ops["ranking"]["direction"] == "DESC"
    assert ops["measure_concept"] == "revenue"
    assert ops["aggregation"] == "SUM"


def test_catalog_master_sql_rejected_for_revenue_ranking():
    sql = 'SELECT k."kunnr", k."name1" FROM "KNA1" k LIMIT 50'
    assert sql_satisfies_analytical_intent(sql, "Show top 10 customers by revenue") is False


def test_grouped_count_sql_accepted_for_monthly_count():
    sql = (
        'SELECT SUBSTRING(TRIM(CAST("VBAK"."audat" AS TEXT)), 1, 6) AS "month", '
        'COUNT(*) AS "count" FROM "VBAK" '
        'GROUP BY SUBSTRING(TRIM(CAST("VBAK"."audat" AS TEXT)), 1, 6) '
        'ORDER BY "month" ASC'
    )
    assert sql_satisfies_analytical_intent(sql, "Show sales order count by month") is True


def test_ungrouped_count_rejected_for_monthly_count():
    sql = 'SELECT COUNT(*) AS "count" FROM "VBAK"'
    assert sql_satisfies_analytical_intent(sql, "Show sales order count by month") is False


def test_result_validation_flags_master_listing():
    rows = [{"kunnr": "0001", "name1": "Acme"}]
    warnings = result_matches_analytical_intent(rows, "Show top 10 customers by revenue")
    assert warnings


def test_result_first_followup_from_prior_rows():
    prior = [
        {"customer_name": "A", "supplier": "S1"},
        {"customer_name": "B", "supplier": "S1"},
        {"customer_name": "C", "supplier": "S2"},
    ]
    out = try_answer_from_prior_rows(
        "Which supplier appears most in this result?",
        prior,
    )
    assert out is not None
    assert not out.get("needs_plan_expansion")
    assert out["data"][0]["occurrence_count"] == 2


def test_result_first_missing_dimension_does_not_invent():
    prior = [{"customer_name": "A", "total_sales": 10}]
    out = try_answer_from_prior_rows(
        "Which supplier appears most in this result?",
        prior,
    )
    assert out is not None
    assert out.get("needs_plan_expansion") is True
    assert "supplier" in (out.get("summary") or "").lower()


def test_timeout_payload_is_user_safe():
    payload = timeout_response("sql_generation", 120.0, question="billing documents")
    assert payload["answer_status"] == "TIMEOUT"
    assert payload["status"] == "timeout"
    assert "psycopg2" not in payload["summary"].lower()
    assert "stopped" in payload["summary"].lower()
    assert payload["data"] == []


def test_budget_expires_after_hard_limit():
    budget = InvestigationBudget(limit_s=0.02)
    time.sleep(0.03)
    assert budget.expired() is True
    with pytest.raises(InvestigationTimeout):
        budget.checkpoint("late")


def test_cancel_stops_further_stages():
    budget = begin_investigation("slow question")
    assert cancel_investigation(budget.request_id) is True
    with pytest.raises(InvestigationTimeout) as exc:
        budget.checkpoint("sql_generation")
    assert exc.value.cancelled is True


def test_runtime_authorities_are_adaptive_only():
    assert CATALOG_IS_RUNTIME_AUTHORITY is False
    assert INTENT_FAST_PATH_IS_RUNTIME_AUTHORITY is False
    assert SALES_ORDER_COMPILER_IS_RUNTIME_AUTHORITY is False
    assert DETERMINISTIC_QUESTION_SQL_IS_RUNTIME_AUTHORITY is False
    assert KEYWORD_TABLE_MAP_IS_AUTHORITY is False
    assert FOUR_STAGE_IS_SAP_ANALYTICS_AUTHORITY is True


def test_governed_compilers_are_disabled():
    assert try_governed_database("Show sales order count by month", None, lambda *_a, **_k: []) is None


def test_partitioned_ranking_is_first_class():
    ops = extract_analytical_operations("Top 3 customers in each country by revenue")
    assert ops["ranking"]["limit"] == 3
    assert "country" in ops["ranking"]["partition_by"]
    assert ops["measure_concept"] == "revenue"


def test_negation_is_first_class():
    ops = extract_analytical_operations("Which suppliers have purchase orders but no invoices?")
    assert ops.get("negation")


def test_period_compare_is_generic_not_year_hardcoded():
    ops = extract_analytical_operations("Which customers increased sales between 2004 and 2005?")
    base = ops["period_compare"]["base_period"]
    cmp_ = ops["period_compare"]["comparison_period"]
    assert (base if isinstance(base, str) else base.get("year")) == "2004"
    assert (cmp_ if isinstance(cmp_, str) else cmp_.get("year")) == "2005"
    assert ops["period_compare"].get("condition") == "increased"
    ops2 = extract_analytical_operations("Which customers increased sales between 1999 and 2001?")
    base2 = ops2["period_compare"]["base_period"]
    assert (base2 if isinstance(base2, str) else base2.get("year")) == "1999"


def test_relative_date_is_generic():
    ops = extract_analytical_operations("Show invoices from last month")
    assert ops.get("relative_period") == "last_month"


def test_synonym_client_maps_to_revenue_ranking():
    ops = extract_analytical_operations("Which clients generated the highest billed value?")
    assert ops.get("ranking")
    assert ops.get("measure_concept") in {"revenue", "sales"}


def test_result_validation_rejects_ungrouped_month_total():
    rows = [{"count": 65720}]
    warnings = result_matches_analytical_intent(
        rows,
        "Show sales order count by month",
        sql='SELECT COUNT(*) AS "count" FROM "VBAK"',
    )
    assert warnings


def test_empty_valid_sql_is_not_mismatch():
    sql = (
        'SELECT SUBSTRING(TRIM(CAST("VBAK"."audat" AS TEXT)), 1, 6) AS "month", '
        'COUNT(*) AS "count" FROM "VBAK" '
        'GROUP BY SUBSTRING(TRIM(CAST("VBAK"."audat" AS TEXT)), 1, 6)'
    )
    warnings = result_matches_analytical_intent([], "Show sales order count by month", sql=sql)
    assert warnings == []


def test_list_with_amounts_is_not_forced_aggregation():
    ops = extract_analytical_operations("Show billing documents with amounts and currency")
    assert ops.get("aggregation") != "SUM" or not ops.get("ranking")
    assert ops.get("ranking") is None
    merged = merge_semantic_requirements(
        "Show sales order count by month",
        {"measure": {"concept": "count", "aggregation": "COUNT"}, "dimensions": []},
    )
    assert "month" in merged["group_by"]
    assert merged["measure"]["aggregation"] == "COUNT"
