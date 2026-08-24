"""R3 expansion tests: inventories, composition, grain safety, new intents."""
from __future__ import annotations

from app.services.analytical_deep_dive import build_analytical_plan, compile_queries
from app.services.analytical_followup_resolver import resolve_analytical_followup
from app.services.business_intelligence_inventory import compose_intent, inventory_payload
from app.services.business_semantic_layer import METRICS
from app.services.sql_grain_guard import grain_contract, sql_has_unsafe_monetary_fanout


PRIOR = {
    "deep_analysis": True,
    "intent": "product_profitability",
    "selected_products": ["MAT-A"],
    "metrics": ["revenue", "cogs", "gross_profit"],
    "dimensions": ["product"],
}


def test_baseline_metrics_still_supported():
    for name in ("revenue", "cogs", "gross_profit", "gross_margin_pct"):
        assert METRICS[name].status == "supported"
    assert METRICS["logistics_cost"].status == "unavailable"
    assert METRICS["net_profit"].status == "unavailable"


def test_new_governed_metrics_are_honest():
    assert METRICS["avg_selling_price"].status == "supported"
    assert METRICS["purchase_value"].status == "partial"
    assert METRICS["discount"].status == "unavailable"
    assert "cogs" in (METRICS["purchase_value"].substitutes_forbidden or ())


def test_inventory_payload_has_graph():
    payload = inventory_payload()
    assert payload["schema_table_count"] == 121
    assert "ACDOCA" in payload["missing_critical"]
    assert any(e["entity"] == "Supplier/Vendor" for e in payload["entities"])
    assert any(d["dimension"] == "supplier" for d in payload["dimensions"])


def test_compose_intent_is_generic():
    assert compose_intent(["supplier"]) == "suppliers_of_selection"
    assert compose_intent(["customer"]) == "customers_of_selection"
    assert compose_intent(["industry", "country"]) == "product_industry_region"


def test_supplier_followup_from_context():
    res = resolve_analytical_followup("Show their suppliers.", PRIOR)
    assert res.resolved
    assert res.intent == "suppliers_of_selection"
    plan = build_analytical_plan("Show their suppliers.", PRIOR)
    assert plan.intent == "suppliers_of_selection"
    queries, gaps = compile_queries(plan)
    assert queries
    sql = queries[0]["sql"].upper()
    assert "EKPO" in sql and "LFA1" in sql
    assert "VBRP" not in sql


def test_product_group_plan():
    plan = build_analytical_plan("Show product groups", PRIOR)
    assert plan.intent == "product_group_breakdown"
    queries, _ = compile_queries(plan)
    assert "matkl" in queries[0]["sql"].lower()
    assert "vbrp" in queries[0]["sql"].lower()


def test_grain_guard_flags_fanout():
    bad = 'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "EKPO" p ON v.matnr = p.matnr'
    assert sql_has_unsafe_monetary_fanout(bad)
    good = 'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "VBRK" vk ON v.vbeln = vk.vbeln'
    assert not sql_has_unsafe_monetary_fanout(good)
    g = grain_contract("suppliers_of_selection", ["supplier"])
    assert g["fact_grain"] == "po_item"
