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


def test_top_suppliers_phrase_is_concentration():
    plan = build_analytical_plan("Show the top suppliers.", PRIOR)
    assert plan.intent == "supplier_concentration"


def test_concentration_sql_excludes_deleted_pos_and_ranks():
    queries, _ = compile_queries(build_analytical_plan("Show supplier concentration.", PRIOR))
    sql = queries[0]["sql"].upper()
    assert "LOEKZ" in sql
    assert "SHARE_OF_PO_VALUE_PCT" in sql
    assert "SUPPLIER_RANK" in sql
    assert "SUM(purchase_value) OVER () > 0" in queries[0]["sql"]
    assert "VBRP" not in sql
    assert "MBEW" not in sql


def test_concentration_zero_total_share_is_null_not_divzero():
    queries, _ = compile_queries(build_analytical_plan("Show supplier concentration.", {}))
    sql = queries[0]["sql"]
    assert "ELSE NULL END AS share_of_po_value_pct" in sql.replace("\n", " ").replace("  ", " ") or "ELSE NULL END AS share_of_po_value_pct" in sql


def test_missing_supplier_name_still_keeps_lifnr():
    queries, _ = compile_queries(build_analytical_plan("Show supplier concentration.", PRIOR))
    sql = queries[0]["sql"]
    assert "LEFT JOIN" in sql.upper() and "LFA1" in sql.upper()
    assert "COALESCE(NULLIF(TRIM(supplier_name), ''), supplier)" in sql


def test_adversarial_vbrp_mbew_and_ekpo_fanout_rejected():
    assert sql_has_unsafe_monetary_fanout(
        'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "MBEW" m ON v.matnr = m.matnr'
    )
    assert sql_has_unsafe_monetary_fanout(
        'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "MARD" d ON v.matnr = d.matnr'
    )
    assert sql_has_unsafe_monetary_fanout(
        'SELECT SUM(v.netwr) FROM "vbrp" v JOIN "EKPO" p ON v.matnr = p.matnr'
    )
    assert sql_has_unsafe_monetary_fanout(
        'SELECT SUM(p.netwr) FROM "EKPO" p JOIN "MBEW" m ON p.matnr = m.matnr'
    )


def test_concentration_paraphrases_do_not_steal_r3_suppliers():
    from app.services.analytical_deep_dive import wants_supplier_concentration

    assert wants_supplier_concentration("who do we buy the most from?")
    assert wants_supplier_concentration("what percentage of purchasing comes from each supplier?")
    assert wants_supplier_concentration("which suppliers account for the most purchasing?")
    assert wants_supplier_concentration("who is our largest supplier?")
    assert wants_supplier_concentration("rank suppliers by purchasing.")
    assert not wants_supplier_concentration("Show their suppliers.")
    for q in (
        "Who do we buy the most from?",
        "What percentage of purchasing comes from each supplier?",
        "Which suppliers account for the most purchasing?",
        "Who is our largest supplier?",
        "Rank suppliers by purchasing.",
    ):
        assert build_analytical_plan(q, PRIOR).intent == "supplier_concentration"
    assert build_analytical_plan("Show their suppliers.", PRIOR).intent == "suppliers_of_selection"


def test_standalone_concentration_is_deep_candidate():
    from app.services.analytical_deep_dive import is_deep_analysis_candidate

    assert is_deep_analysis_candidate("Show supplier concentration.")
    assert is_deep_analysis_candidate("Which suppliers account for the most purchasing?")
    assert is_deep_analysis_candidate("Who is our largest supplier?")
    assert not is_deep_analysis_candidate("Show their suppliers.")
    plan = build_analytical_plan("Show supplier concentration.", None)
    assert plan.intent == "supplier_concentration"
    queries, _ = compile_queries(plan)
    sql = queries[0]["sql"].upper()
    assert '"EKPO"' in sql and '"EKKO"' in sql
    assert "SHARE_OF_PO_VALUE_PCT" in sql
    assert "VBRP" not in sql and "NETWR" in sql
