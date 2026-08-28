"""R4-4 supplier concentration: PO-grain share of purchase value. Not supplier profit."""
from __future__ import annotations

from app.services.analytical_deep_dive import build_analytical_plan, compile_queries
from app.services.analytical_followup_resolver import resolve_analytical_followup
from app.services.sql_grain_guard import grain_contract, sql_has_unsafe_monetary_fanout

PRIOR = {
    "deep_analysis": True,
    "intent": "product_profitability",
    "selected_products": ["P-103", "P-104"],
    "metrics": ["revenue", "cogs", "gross_profit"],
    "dimensions": ["product"],
}


def test_r3_suppliers_followup_unchanged():
    plan = build_analytical_plan("Show their suppliers.", PRIOR)
    assert plan.intent == "suppliers_of_selection"


def test_concentration_intent_from_question():
    plan = build_analytical_plan("Show supplier concentration.", PRIOR)
    assert plan.intent == "supplier_concentration"


def test_concentration_followup_keeps_product_context():
    res = resolve_analytical_followup("Show supplier concentration.", PRIOR)
    assert res.resolved
    assert res.intent == "supplier_concentration"
    plan = build_analytical_plan("Show supplier concentration.", PRIOR)
    queries, gaps = compile_queries(plan)
    assert queries
    sql = queries[0]["sql"]
    upper = sql.upper()
    assert "EKPO" in upper and "EKKO" in upper and "LFA1" in upper
    assert "SHARE_OF_PO_VALUE_PCT" in upper
    assert "VBRP" not in upper
    assert "P-103" in sql
    assert any("not supplier profit" in g.lower() for g in gaps)


def test_concentration_grain_is_po_item():
    g = grain_contract("supplier_concentration", ["supplier"])
    assert g["fact_grain"] == "po_item"
    assert g["aggregation_grain"] == "supplier"
    bad = 'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "EKPO" p ON v.matnr = p.matnr'
    assert sql_has_unsafe_monetary_fanout(bad)
    queries, _ = compile_queries(build_analytical_plan("Show supplier concentration.", PRIOR))
    assert not sql_has_unsafe_monetary_fanout(queries[0]["sql"])


def test_single_source_phrase_routes_to_concentration():
    plan = build_analytical_plan("Which suppliers are single source?", PRIOR)
    assert plan.intent == "supplier_concentration"


def test_supplier_profit_still_not_concentration():
    plan = build_analytical_plan("Show supplier profit.", PRIOR)
    assert plan.intent != "product_profitability" or "supplier" in (plan.intent or "")
    # Must not attribute billing profit to suppliers via VBRP⋈EKPO.
    queries, _ = compile_queries(plan)
    if queries:
        assert not sql_has_unsafe_monetary_fanout(queries[0]["sql"])
