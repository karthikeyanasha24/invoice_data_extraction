"""R4-3: inventory snapshot ↔ sales — planner, grain, rankings, DATA GAPs, follow-ups."""
from __future__ import annotations

from app.services.analytical_deep_dive import (
    build_analytical_plan,
    compile_queries,
    is_deep_analysis_candidate,
)
from app.services.analytical_followup_resolver import resolve_analytical_followup
from app.services.inventory_sales import (
    INVENTORY_GAP_INTENTS,
    availability_sql,
    ratio_sql,
    resolve_inventory_intent,
    resolve_risk_direction,
    wants_inventory_aging,
    wants_true_inventory_turnover,
)
from app.services.sql_grain_guard import grain_contract, sql_has_unsafe_monetary_fanout


PRIOR = {
    "deep_analysis": True,
    "intent": "product_profitability",
    "selected_products": ["MAT-A", "MAT-B"],
    "selected_customers": ["C-1"],
    "selected_regions": ["US"],
    "metrics": ["revenue", "cogs", "gross_profit"],
    "dimensions": ["product"],
    "base_question": "highest profit products",
}

INV_PRIOR = {
    **PRIOR,
    "intent": "inventory_analysis",
    "metrics": ["inventory_value", "inventory_qty"],
    "dimensions": ["product", "valuation_area"],
}


def _sql(question: str, prior=None) -> str:
    plan = build_analytical_plan(question, prior)
    queries, _ = compile_queries(plan)
    return queries[0]["sql"] if queries else ""


def test_helpers_null_safe_ratio_and_availability():
    r = ratio_sql("a", "b", "x")
    assert "CASE WHEN" in r and "= 0 THEN NULL" in r
    a = availability_sql("stock_value", "revenue")
    assert "SALES_ONLY" in a and "INVENTORY_ONLY" in a and "BOTH" in a


def test_snapshot_intents():
    for q in (
        "Show inventory.",
        "Show inventory value.",
        "Show inventory quantity.",
        "Which products have the highest inventory?",
        "Which products have the lowest inventory?",
        "Show stock for these products.",
        "Which products have the highest inventory value?",
        "Which products have the highest stock quantity?",
    ):
        assert is_deep_analysis_candidate(q), q
        plan = build_analytical_plan(q)
        assert plan.intent == "inventory_analysis", f"{q} → {plan.intent}"


def test_inventory_vs_sales_intent():
    for q in (
        "Show inventory versus sales.",
        "Compare inventory with revenue.",
        "Compare inventory with quantity sold.",
        "Show inventory and sales for these products.",
    ):
        plan = build_analytical_plan(q)
        assert plan.intent == "inventory_sales_comparison", f"{q} → {plan.intent}"


def test_high_inv_low_sales_and_low_inv_high_sales():
    hi = build_analytical_plan("Which products have high inventory but low sales?")
    assert hi.intent == "inventory_risk_analysis"
    assert hi.filters.get("risk_direction") == "high_inv_low_sales"
    lo = build_analytical_plan("Which products have low inventory but high sales?")
    assert lo.intent == "inventory_risk_analysis"
    assert lo.filters.get("risk_direction") == "low_inv_high_sales"
    assert resolve_risk_direction("which products appear overstocked based on inventory versus sales") == (
        "high_inv_low_sales"
    )
    assert resolve_risk_direction("which products have strong sales but low inventory") == "low_inv_high_sales"


def test_plant_and_product_group():
    p = build_analytical_plan("Show inventory by plant.")
    assert p.intent == "inventory_by_plant"
    g = build_analytical_plan("Compare sales and inventory by product group.")
    assert g.intent == "inventory_sales_comparison"
    assert g.filters.get("inventory_grain") == "product_group"
    assert build_analytical_plan("Which plants hold the most inventory?").intent == "inventory_by_plant"


def test_aging_turnover_trend_are_data_gaps():
    assert wants_inventory_aging("Show inventory aging.")
    assert wants_inventory_aging("How long has this stock been sitting?")
    assert wants_true_inventory_turnover("Show inventory turnover.")
    assert resolve_inventory_intent("show inventory aging") == "inventory_aging_gap"
    assert resolve_inventory_intent("show inventory turnover") == "inventory_turnover_gap"
    assert resolve_inventory_intent("show inventory trend") == "inventory_trend_gap"
    for q, intent in (
        ("Show inventory aging.", "inventory_aging_gap"),
        ("Which inventory is older?", "inventory_aging_gap"),
        ("Show inventory turnover.", "inventory_turnover_gap"),
        ("Show inventory trend.", "inventory_trend_gap"),
        ("Show inventory in 2004.", "inventory_trend_gap"),
    ):
        plan = build_analytical_plan(q)
        assert plan.intent == intent, f"{q} → {plan.intent}"
        queries, gaps = compile_queries(plan)
        assert queries == []
        assert gaps


def test_r3_inventory_not_hijacked_by_risk():
    plan = build_analytical_plan("Show the inventory.")
    assert plan.intent == "inventory_analysis"
    sql = _sql("Show the inventory.")
    assert "MBEW" in sql.upper()
    assert "SALK3" in sql.upper() or "salk3" in sql
    assert "JOIN \"MARD\"" not in sql.upper().replace(" ", "") or "vbrp" not in sql.lower()


def test_snapshot_sql_grain_and_product_filter():
    plan = build_analytical_plan("Show their inventory.", PRIOR)
    assert plan.selected_products == ["MAT-A", "MAT-B"]
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"]
    assert "MBEW" in sql
    assert "MAT-A" in sql
    assert not sql_has_unsafe_monetary_fanout(sql)
    assert 'JOIN "MARD"' not in sql
    assert 'JOIN "MBEW"' not in sql  # FROM MBEW is allowed; JOIN MBEW from billing is not


def test_comparison_sql_independent_aggs_no_fanout():
    sql = _sql("Show inventory versus sales.")
    su = sql.upper()
    assert "WITH" in su
    assert "INVENTORY_AGG" in su
    assert "SALES_AGG" in su
    assert "FULL OUTER JOIN" in su
    assert "VBRP" in su and "VBRK" in su and "MBEW" in su
    assert not sql_has_unsafe_monetary_fanout(sql)
    assert "SALES_QTY_TO_STOCK_QTY" in su
    assert "INVENTORY_VALUE_TO_REVENUE" in su
    assert "DATA_AVAILABILITY" in su
    assert "INVENTORY TURNOVER" not in su
    # Must not join inventory into billing before SUM
    assert 'JOIN "MBEW"' not in sql
    assert 'JOIN "MARD"' not in sql


def test_risk_sql_uses_percent_rank_not_thresholds():
    sql = _sql("Which products have high inventory but low sales?")
    su = sql.upper()
    assert "PERCENT_RANK" in su
    assert "OVERSTOCK_SCORE" in su
    assert "100000" not in sql
    assert "inventory >" not in sql.lower()
    assert not sql_has_unsafe_monetary_fanout(sql)
    sql2 = _sql("Which products have low inventory but high sales?")
    assert "UNDERSUPPLY_SCORE" in sql2.upper()


def test_product_group_sql_independent():
    sql = _sql("Break inventory down by product group.")
    su = sql.upper()
    assert "MATKL" in su
    assert "MARA" in su
    assert "INVENTORY_AGG" in su and "SALES_AGG" in su
    assert not sql_has_unsafe_monetary_fanout(sql)


def test_plant_sql_uses_mard_werks_not_t001w():
    sql = _sql("Show inventory by plant.")
    su = sql.upper()
    assert "MARD" in su
    assert "WERKS" in su
    assert "LABST" in su
    assert "T001W" not in su
    assert "VBRP" not in su  # plant snapshot is inventory-only
    assert not sql_has_unsafe_monetary_fanout(sql)


def test_grain_guard_rejects_vbrp_join_mard():
    bad = 'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "MARD" d ON v.matnr = d.matnr'
    assert sql_has_unsafe_monetary_fanout(bad)
    bad2 = 'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "MBEW" b ON v.matnr = b.matnr'
    assert sql_has_unsafe_monetary_fanout(bad2)
    good = 'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "VBRK" vk ON v.vbeln = vk.vbeln'
    assert not sql_has_unsafe_monetary_fanout(good)
    cte = """
    WITH inv AS (SELECT matnr, SUM(salk3) AS stock_value FROM "MBEW" GROUP BY matnr)
    SELECT SUM(v.netwr), i.stock_value FROM "vbrp" v JOIN "VBRK" vk ON v.vbeln = vk.vbeln
    JOIN inv i ON v.matnr = i.matnr
    """
    assert not sql_has_unsafe_monetary_fanout(cte)
    g = grain_contract("inventory_sales_comparison", ["product"])
    assert "sales_agg" in g["fact_grain"]


def test_lowest_inventory_orders_asc():
    plan = build_analytical_plan("Which products have the lowest inventory?")
    assert plan.filters.get("inventory_rank_dir") == "ASC"
    sql = _sql("Which products have the lowest inventory?")
    assert "ASC" in sql.upper()


def test_followups_preserve_products_and_route():
    res = resolve_analytical_followup("Show their inventory.", PRIOR)
    assert res.resolved and res.intent == "inventory_analysis"
    res2 = resolve_analytical_followup("Show inventory versus sales.", PRIOR)
    assert res2.intent == "inventory_sales_comparison"
    res3 = resolve_analytical_followup("Which have high inventory but low sales?", PRIOR)
    assert res3.intent == "inventory_risk_analysis"
    res4 = resolve_analytical_followup("Show their customers.", INV_PRIOR)
    assert res4.intent == "customers_of_selection"
    res5 = resolve_analytical_followup("Show their suppliers.", INV_PRIOR)
    assert res5.intent == "suppliers_of_selection"
    res6 = resolve_analytical_followup("Show their regions.", INV_PRIOR)
    assert res6.intent == "country_breakdown"
    res7 = resolve_analytical_followup("Break that down by plant.", INV_PRIOR)
    assert res7.intent == "inventory_by_plant"
    res8 = resolve_analytical_followup("Compare their sales with last year.", INV_PRIOR)
    assert res8.intent == "period_compare_selection"
    res9 = resolve_analytical_followup("Show inventory aging.", INV_PRIOR)
    assert res9.intent in INVENTORY_GAP_INTENTS
    res10 = resolve_analytical_followup("Show inventory again.", INV_PRIOR)
    assert res10.intent == "inventory_analysis"
    res11 = resolve_analytical_followup("Why?", INV_PRIOR)
    assert res11.intent == "inventory_analysis"


def test_data_gap_recovery_context():
    gap = resolve_analytical_followup("Show inventory aging.", INV_PRIOR)
    assert gap.intent == "inventory_aging_gap"
    after = resolve_analytical_followup("Show inventory.", INV_PRIOR)
    assert after.intent == "inventory_analysis"
    net = resolve_analytical_followup("Show net profit.", INV_PRIOR)
    assert net.data_gap_metric == "net_profit"
    after2 = resolve_analytical_followup("Show inventory.", INV_PRIOR)
    assert after2.intent == "inventory_analysis"


def test_r3_r4_regression_guards():
    assert build_analytical_plan("Which products had the biggest margin decline?").intent == (
        "margin_decline_drivers"
    )
    assert build_analytical_plan("Which month had the biggest margin decline?").intent == "monthly_trend"
    assert build_analytical_plan("Which products grew the most?").intent == "product_growth_decline"
    assert build_analytical_plan("Show monthly sales.").intent == "monthly_trend"
    assert build_analytical_plan("Show their suppliers.", PRIOR).intent == "suppliers_of_selection"


def test_does_not_call_ratio_turnover():
    sql = _sql("Show inventory versus sales.")
    assert "turnover" not in sql.lower()
    plan = build_analytical_plan("Show inventory versus sales.")
    blob = " ".join(plan.data_gaps).lower()
    assert "turnover" not in blob or "not inventory turnover" in blob or "not" in blob


def test_paraphrases():
    cases = {
        "inventory_analysis": [
            "Show the inventory.",
            "Show stock value.",
            "Highest inventory products",
        ],
        "inventory_sales_comparison": [
            "inventory vs sales",
            "compare inventory with sales",
        ],
        "inventory_risk_analysis": [
            "high stock and low sales",
            "low stock and high sales",
        ],
        "inventory_by_plant": [
            "inventory by warehouse",
        ],
        "inventory_aging_gap": [
            "show inventory age",
        ],
    }
    for intent, questions in cases.items():
        for q in questions:
            assert resolve_inventory_intent(q.lower()) == intent, f"{q} → {resolve_inventory_intent(q.lower())}"
