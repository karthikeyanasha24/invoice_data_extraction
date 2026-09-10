"""Unit tests for generic analytical SQL builders (no question-specific handlers)."""
from __future__ import annotations

from app.services.adaptive_structured_sql import (
    build_above_average_sql,
    build_dimension_ranking_sql,
    build_document_count_by_period_sql,
    build_negation_anti_join_sql,
    build_partitioned_topn_sql,
    build_period_compare_sql,
)
from app.services.analytical_operations import extract_analytical_operations
from app.services.plan_satisfaction import sql_satisfies_analytical_intent


def test_vendor_purchase_ranking_is_generic():
    q = "List the top 8 vendors by purchase order value."
    sql = build_dimension_ranking_sql(q, [])
    assert sql and "lifnr" in sql.lower() and "LIMIT 8" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_document_count_by_year():
    q = "How many billing documents were created each year?"
    sql = build_document_count_by_period_sql(q, [])
    assert sql and "GROUP BY" in sql.upper() and "COUNT" in sql.upper()
    assert "SUBSTRING" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_above_average_builder():
    q = "Which customers had billed sales above the average customer sales?"
    sql = build_above_average_sql(q, [])
    assert sql and "AVG" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_plant_partition_detection():
    q = "Which materials had the highest billed quantity in each plant?"
    ops = extract_analytical_operations(q)
    assert "plant" in (ops.get("partition_by") or [])
    sql = build_partitioned_topn_sql(q, [])
    assert sql and "PARTITION BY" in sql.upper() and "plant" in sql.lower()
    assert sql_satisfies_analytical_intent(sql, q)


def test_period_decline_has_having():
    q = "Which country had the largest decline in sales between 2004 and 2005?"
    sql = build_period_compare_sql(q, [])
    assert sql and "HAVING" in sql.upper() and "2004" in sql and "2005" in sql
    assert sql_satisfies_analytical_intent(sql, q)


def test_declined_past_tense_is_decrease_condition():
    from app.services.semantic_requirements import required_semantics
    from app.services.analytical_operations import extract_analytical_operations

    q = "Which country declined the most in billed sales between 2004 and 2005?"
    ops = extract_analytical_operations(q)
    assert (ops.get("period_compare") or {}).get("condition") == "decreased"
    req = required_semantics(q)
    assert (req.get("period_compare") or {}).get("condition") == "decreased"
    sql = build_period_compare_sql(q, [])
    assert sql and "< 0" in sql and "HAVING" in sql.upper()


def test_supplier_invoice_amount_uses_vendor_invoice_measure():
    from app.services.adaptive_structured_sql import detect_ranking_measure

    q = "Show the top 10 suppliers by invoice amount."
    assert detect_ranking_measure(q) == "vendor_invoice_value"
    sql = build_dimension_ranking_sql(q, [])
    assert sql and "RBKP" in sql.upper() and "invoice_amount" in sql.lower()
    assert "EKPO" not in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)

def test_negation_anti_join():
    q = "Which suppliers have purchase orders but no invoices?"
    sql = build_negation_anti_join_sql(q, [])
    assert sql and "NOT EXISTS" in sql.upper()
    assert "RBKP" in sql.upper() or "VBRK" in sql.upper()
    assert sql_satisfies_analytical_intent(sql, q)


def test_plural_industry_ranking_limit_not_top1():
    from app.services.semantic_requirements import required_semantics
    from app.services.plan_satisfaction import result_matches_analytical_intent

    q = "Which industries generated the most billed sales?"
    req = required_semantics(q)
    assert int((req.get("ranking") or {}).get("limit") or 0) >= 10
    sql = (
        'SELECT industry, total_sales FROM t ORDER BY total_sales DESC LIMIT 10'
    )
    warnings = result_matches_analytical_intent(
        [{"industry": f"I{i}", "total_sales": 100 - i} for i in range(10)],
        q,
        semantic=req,
        sql=sql,
    )
    assert not any("ranking limit" in w for w in warnings)


def test_vendor_po_ranking_ignores_polluted_negation():
    from app.services.semantic_requirements import required_semantics

    q = "Which vendor has the highest purchase order value?"
    # Simulate LLM pollution: required PO without absence language.
    sem = {
        "dimensions": ["vendor"],
        "group_by": ["vendor"],
        "measure": {"concept": "purchase_order", "aggregation": "SUM"},
        "ranking": {"direction": "DESC", "limit": 1},
        "negation": {"required": "purchase_order", "forbidden": None},
    }
    req = required_semantics(q, sem)
    assert not req.get("negation")
    sql = build_dimension_ranking_sql(q, [])
    assert sql and sql_satisfies_analytical_intent(sql, q, sem)


def test_cte_schema_violations_allow_local_relations():
    from app.services.ai_native_pipeline import _schema_violations

    sql = build_above_average_sql(
        "Which customers have sales above the average?",
        [],
    )
    assert sql and sql.upper().startswith("WITH")
    viol = _schema_violations(sql)
    assert not any("unknown table cust" in v.lower() for v in viol), viol
    assert not any("unknown table avg_v" in v.lower() for v in viol), viol


def test_multi_entity_having_uses_transactional_country():
    from app.services.adaptive_structured_sql import build_multi_entity_having_sql
    from app.services.analytical_operations import extract_analytical_operations

    q = "Which customers bought products in more than one country?"
    ops = extract_analytical_operations(q)
    assert ops.get("having_distinct")
    assert ops["having_distinct"]["grain"] == "transaction"
    sql = build_multi_entity_having_sql(q, [])
    assert sql and "HAVING" in sql.upper() and "COUNT(DISTINCT" in sql.upper()
    assert 'k."land1"' in sql.lower() or 'k."LAND1"' in sql
    # Must not count master-only KNA1.land1 for transactional attribution.
    assert "c.\"land1\"" not in sql.lower().replace(" ", "")
    assert sql_satisfies_analytical_intent(sql, q)


def test_qualitative_threshold_clarification_generic():
    from app.services.threshold_semantics import detect_threshold_clarification
    from app.services.analytical_operations import extract_analytical_operations

    q = "Which materials generated high quantity but relatively low billed value?"
    clar = detect_threshold_clarification(q)
    assert clar and clar["type"] == "threshold_definition"
    ops = extract_analytical_operations(q)
    assert (ops.get("clarification") or {}).get("type") == "threshold_definition"

    # Ranking must not ask for thresholds.
    assert detect_threshold_clarification("Which customers generated the highest billed sales?") is None
    # Explicit average is executable.
    assert detect_threshold_clarification(
        "Which customers had billed sales above the average customer sales?"
    ) is None


def test_cancel_sets_cancelled_answer_status():
    from app.services.investigation_budget import (
        begin_investigation,
        cancel_investigation,
        end_investigation,
        timeout_response,
    )

    b = begin_investigation("test cancel", limit_s=30, request_id="cancel-unit-test-1")
    assert cancel_investigation(b.request_id) is True
    payload = timeout_response("sql_generation", question="test cancel")
    assert payload["answer_status"] == "CANCELLED"
    assert payload["status"] == "cancelled"
    end_investigation("cancelled")
    # Case E: cancel after completion must not flip status.
    b2 = begin_investigation("done", limit_s=30, request_id="cancel-unit-test-2")
    end_investigation("completed")
    assert cancel_investigation(b2.request_id) is False
