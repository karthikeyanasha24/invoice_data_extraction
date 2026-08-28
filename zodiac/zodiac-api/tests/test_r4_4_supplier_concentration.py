"""R4-4 supplier concentration: PO-grain share of purchase value. Not supplier profit."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

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


def test_first_question_concentration_paraphrases():
    from app.services.analytical_deep_dive import is_deep_analysis_candidate

    for q in (
        "Show supplier concentration.",
        "Show supplier concentration",
        "What is supplier concentration?",
        "Which suppliers account for most purchase value?",
        "Show top suppliers by purchase value.",
        "Show supplier PO concentration.",
        "Which suppliers have the highest PO value?",
        "Show the top 3 suppliers by purchase value.",
        "Who are the most concentrated suppliers?",
        "Which suppliers dominate purchases?",
        "Which supplier has the largest PO share?",
        "Compare suppliers by PO value",
    ):
        assert is_deep_analysis_candidate(q), q
        assert build_analytical_plan(q, None).intent == "supplier_concentration", q
    assert not is_deep_analysis_candidate("Show their suppliers.")
    assert build_analytical_plan("Show their suppliers.", PRIOR).intent == "suppliers_of_selection"


def test_standalone_top_n_limit_is_honored():
    sql = compile_queries(
        build_analytical_plan("Show the top 3 suppliers by purchase value.", None)
    )[0][0]["sql"].upper()
    assert "LIMIT 3" in sql
    assert "LIMIT 20" not in sql
    assert "EKPO" in sql and "VBRP" not in sql


def test_concentration_heading_is_business_facing():
    from app.services.analytical_deep_dive import _analysis_heading, _interpret

    assert "supplier_concentration" not in _analysis_heading("supplier_concentration")
    assert "_" not in _analysis_heading("supplier_concentration")
    assert _analysis_heading("supplier_concentration", {"limit": 3}) == "Top 3 suppliers by purchase value"
    assert _analysis_heading("supplier_concentration", {"limit": 1}) == "Highest supplier by purchase value"
    plan = build_analytical_plan("Show supplier concentration.", None)
    summary, _ = _interpret(plan, [{"id": "supplier_concentration", "sql": "SELECT 1", "rows": []}])
    assert "supplier_concentration" not in summary
    assert "deep_multidim" not in summary.lower()


def test_concentration_followups_stay_in_intent():
    ctx = {
        "deep_analysis": True,
        "intent": "supplier_concentration",
        "metrics": ["purchase_value", "share_of_po_value_pct"],
        "dimensions": ["supplier"],
        "selected_products": [],
    }
    for q in (
        "Show the highest one.",
        "Show the highest supplier.",
        "Show the percentage.",
        "Show top 3.",
        "Show PO value.",
        "Show the largest supplier.",
        "Why is the first one highest?",
    ):
        assert build_analytical_plan(q, ctx).intent == "supplier_concentration", q
    top3 = build_analytical_plan("Show top 3.", ctx)
    assert top3.intent == "supplier_concentration"
    sql = compile_queries(top3)[0][0]["sql"].upper()
    assert "LIMIT 3" in sql
    highest = compile_queries(build_analytical_plan("Show the highest one.", ctx))[0][0]["sql"].upper()
    assert "LIMIT 1" in highest
    assert build_analytical_plan("Show their suppliers.", ctx).intent == "suppliers_of_selection"


def test_standalone_concentration_default_limit_is_display_size():
    sql = compile_queries(build_analytical_plan("Show supplier concentration.", None))[0][0]["sql"].upper()
    assert "LIMIT 20" in sql
    assert "VBRP" not in sql


def test_first_question_turn_is_new_analytical():
    from app.services.ai_followup_routing import TurnIntent, classify_turn

    turn = classify_turn("Show supplier concentration.")
    assert turn.intent == TurnIntent.NEW_ANALYTICAL_QUERY
    turn3 = classify_turn("Show the top 3 suppliers by purchase value.")
    assert turn3.intent == TurnIntent.NEW_ANALYTICAL_QUERY


def test_concentration_context_exposes_po_grain_not_billing():
    ctx = build_analytical_plan("Show supplier concentration.", None).to_context()
    assert ctx["fact_grain"] == "po_item"
    assert ctx["aggregation_grain"] == "supplier"
    assert "purchase" in (ctx.get("period_label") or "").lower()
    assert "vbrp" not in str(ctx).lower()


def test_independent_po_grain_shares_match_compiled_sql():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not url:
        pytest.skip("DATABASE_URL missing")
    from sqlalchemy import create_engine, text

    sql = compile_queries(build_analytical_plan("Show supplier concentration.", None))[0][0]["sql"]
    assert "vbrp" not in sql.lower()
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(sql))]
    assert rows
    by_id = {str(r.get("supplier")): r for r in rows}
    s5557 = by_id.get("0000005557")
    s1095 = by_id.get("0000001095")
    assert s5557 is not None and s1095 is not None
    assert abs(float(s5557["share_of_po_value_pct"]) - 49.86) <= 0.05
    assert abs(float(s1095["share_of_po_value_pct"]) - 42.45) <= 0.05
    assert float(s5557["purchase_value"]) >= float(s1095["purchase_value"])
    top3_sql = compile_queries(
        build_analytical_plan("Show the top 3 suppliers by purchase value.", None)
    )[0][0]["sql"]
    with engine.connect() as conn:
        top3 = [dict(r._mapping) for r in conn.execute(text(top3_sql))]
    assert len(top3) == 3
    assert str(top3[0]["supplier"]) == str(rows[0]["supplier"])

