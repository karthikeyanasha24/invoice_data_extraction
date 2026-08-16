"""Unit tests for Generative AI R1 (follow-up), R3 (grain/date/currency/industry), R5 (memory)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.api.adaptive_query import _sql_guardrail_violations
from app.services.ai_followup_routing import follow_up_requires_fresh_sql, resolve_follow_up_sql_need
from app.services.ai_query_memory_service import (
    MEMORY_REUSE_SCORE_THRESHOLD,
    _similarity_score,
    classify_memory_entry,
)
from app.services.ai_query_plan import (
    extract_query_plan,
    fingerprints_compatible as plan_fps_compatible,
)

EVAL_PATH = Path(__file__).resolve().parent / "generative_ai_eval_cases.json"


def _load_eval():
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))


def test_followup_add_industry_dimension_needs_fresh_sql():
    prev = "Show highest sales in 2004."
    need, plan = resolve_follow_up_sql_need("Show me the industry", prev, "")
    assert need is True
    assert "industry" in plan.dimensions
    assert plan.filters.get("years") == ["2004"]
    assert plan.grain == "header"


def test_followup_trading_filter_needs_fresh_sql():
    prev_plan = extract_query_plan("Show highest sales in 2004.").to_dict()
    need, plan = resolve_follow_up_sql_need(
        "Only the Trading industry", "Show highest sales in 2004.", "", prev_plan
    )
    assert need is True
    assert plan.filters.get("industry")
    assert "trading" in str(plan.filters.get("industry")).lower()


def test_followup_top5_changes_ranking():
    prev = extract_query_plan("Show highest sales in 2004.")
    need, plan = resolve_follow_up_sql_need(
        "Now show the top 5", "Show highest sales in 2004.", "", prev.to_dict()
    )
    assert need is True
    assert plan.limit == 5
    assert plan.filters.get("years") == ["2004"]


def test_followup_compare_merges_years():
    prev = extract_query_plan("Show highest sales in 2004.")
    need, plan = resolve_follow_up_sql_need(
        "Compare this with 2003", "Show highest sales in 2004.", "", prev.to_dict()
    )
    assert need is True
    assert plan.operation == "compare"
    assert set(plan.filters.get("years") or []) == {"2003", "2004"}


def test_followup_thanks_is_narrative():
    need, plan = resolve_follow_up_sql_need("thanks", "Show highest sales in 2004.", "")
    assert need is False
    assert "narrative" in plan.delta_ops


def test_followup_change_metric_to_count():
    prev = extract_query_plan("Top customers 2004")
    need, plan = resolve_follow_up_sql_need(
        "Show invoice count instead", "Top customers 2004", "", prev.to_dict()
    )
    assert need is True
    assert plan.metric == "count"


def test_followup_backward_compat_question_only():
    assert follow_up_requires_fresh_sql("Show sales in 2004") is True


def test_sales_defaults_to_header_grain():
    plan = extract_query_plan("Show highest sales by customer in 2004")
    assert plan.grain == "header"
    assert plan.metric == "sales"


def test_product_query_uses_line_grain():
    plan = extract_query_plan("Show product-level sales for 2004")
    assert plan.grain == "line"
    assert "product" in plan.dimensions


def test_guardrail_rejects_gjahr_for_year_sales():
    q = "highest sales in 2004 by customer"
    sql = (
        'SELECT c."name1", SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),\'\') AS NUMERIC)) AS sales, k."waerk" '
        'FROM "VBRK" k LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr" '
        'WHERE k."gjahr" = \'2004\' GROUP BY c."name1", k."waerk" ORDER BY sales DESC LIMIT 5'
    )
    violations = _sql_guardrail_violations(q, sql)
    assert any("gjahr" in v.lower() or "fkdat" in v.lower() for v in violations)


def test_guardrail_rejects_vbrp_sum_for_header_sales():
    q = "highest sales by customer in 2004"
    sql = (
        'SELECT c."name1", SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)),\'\') AS NUMERIC)) AS sales, k."waerk" '
        'FROM "vbrp" p JOIN "VBRK" k ON p."vbeln" = k."vbeln" '
        'LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr" '
        "WHERE SUBSTRING(TRIM(k.\"fkdat\"),1,4)='2004' "
        'GROUP BY c."name1", k."waerk" ORDER BY sales DESC'
    )
    violations = _sql_guardrail_violations(q, sql)
    assert any("header" in v.lower() or "vbrk.netwr" in v.lower() for v in violations)


def test_guardrail_rejects_mara_industry_for_customer_industry():
    q = "highest sales 2004 with customer and industry"
    sql = (
        'SELECT c."name1", m."mbrsh" AS industry, '
        'SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),\'\') AS NUMERIC)) AS sales, k."waerk" '
        'FROM "VBRK" k LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr" '
        'LEFT JOIN "vbrp" p ON k."vbeln" = p."vbeln" '
        'LEFT JOIN "MARA" m ON p."matnr" = m."matnr" '
        "WHERE SUBSTRING(TRIM(k.\"fkdat\"),1,4)='2004' "
        'GROUP BY c."name1", m."mbrsh", k."waerk" ORDER BY sales DESC'
    )
    violations = _sql_guardrail_violations(q, sql)
    assert any("mara" in v.lower() or "t016t" in v.lower() for v in violations)


def test_guardrail_requires_currency_grouping_for_sales_aggregate():
    q = "total sales for 2004"
    sql = (
        'SELECT SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),\'\') AS NUMERIC)) AS sales '
        'FROM "VBRK" k WHERE SUBSTRING(TRIM(k."fkdat"),1,4)=\'2004\''
    )
    violations = _sql_guardrail_violations(q, sql)
    assert any("currency" in v.lower() for v in violations)


def test_valid_header_customer_industry_sql_passes_key_guards():
    q = "highest sales for 2004 with customer and industry"
    sql = (
        'SELECT COALESCE(c."name1", \'Unknown / unmapped\') AS customer, '
        'COALESCE(t."brtxt", \'Not available\') AS industry, '
        'SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),\'\') AS NUMERIC)) AS sales, '
        'k."waerk" AS currency FROM "VBRK" k '
        'LEFT JOIN "KNA1" c ON TRIM(k."kunag") = TRIM(c."kunnr") '
        'LEFT JOIN "T016T" t ON TRIM(c."brsch") = TRIM(t."brsch") '
        "WHERE SUBSTRING(TRIM(k.\"fkdat\"),1,4) = '2004' "
        'GROUP BY c."name1", t."brtxt", k."waerk" ORDER BY sales DESC NULLS LAST LIMIT 10'
    )
    violations = _sql_guardrail_violations(q, sql)
    joined = " | ".join(violations).lower()
    assert "gjahr" not in joined
    assert "mara" not in joined


def test_fingerprint_blocks_dimension_change_reuse():
    a = extract_query_plan("highest sales by customer 2004").fingerprint()
    b = extract_query_plan("highest sales by industry 2004").fingerprint()
    assert plan_fps_compatible(a, a)
    assert not plan_fps_compatible(a, b)


def test_fingerprint_blocks_year_change_reuse():
    a = extract_query_plan("total sales 2004").fingerprint()
    b = extract_query_plan("total sales 2003").fingerprint()
    assert not plan_fps_compatible(a, b)


def test_fingerprint_blocks_grain_change_reuse():
    a = extract_query_plan("highest sales by customer 2004").fingerprint()
    b = extract_query_plan("highest product-level sales 2004").fingerprint()
    assert "grain=line" in b
    assert "grain=header" in a
    assert not plan_fps_compatible(a, b)


def test_similarity_still_rejects_year_mismatch():
    sql = (
        'SELECT SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),\'\') AS NUMERIC)) AS total_sales, k."waerk" '
        'FROM "VBRK" k WHERE SUBSTRING(TRIM(k."fkdat"),1,4)=\'1999\' GROUP BY k."waerk"'
    )
    score = _similarity_score(
        question="total sales for year 2000",
        record_question="total sales for year 1999",
        record_sql=sql,
        source="user",
        use_count=5,
    )
    assert score < MEMORY_REUSE_SCORE_THRESHOLD


def test_classify_raw_sql_question():
    assert classify_memory_entry("SELECT * FROM VBRK", "SELECT 1") == "raw_sql"


def test_classify_mara_industry_contamination():
    q = "show industry of customers"
    sql = 'SELECT m."mbrsh" FROM "MARA" m'
    assert classify_memory_entry(q, sql) in {"suspicious", "incompatible"}


def test_ground_truth_plan_for_client_question():
    plan = extract_query_plan(
        "Show me highest sales for the year 2004 with customer and industry"
    )
    assert plan.grain == "header"
    assert "customer" in plan.dimensions
    assert "industry" in plan.dimensions
    assert plan.filters.get("years") == ["2004"]
    assert plan.operation == "top"


def test_ground_truth_header_sql_against_database():
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    eng = create_engine(url)
    with eng.connect() as c:
        row = c.execute(
            text(
                """
            SELECT COALESCE(k."name1", 'Unknown / unmapped') AS customer,
                   COALESCE(t."brtxt", 'Not available') AS industry,
                   SUM(CAST(NULLIF(TRIM(CAST(vk."netwr" AS TEXT)),'') AS NUMERIC)) AS sales,
                   vk."waerk" AS currency
            FROM "VBRK" vk
            LEFT JOIN "KNA1" k ON TRIM(vk."kunag") = TRIM(k."kunnr")
            LEFT JOIN "T016T" t ON TRIM(k."brsch") = TRIM(t."brsch")
            WHERE SUBSTRING(TRIM(vk."fkdat"),1,4) = '2004'
              AND vk."waerk" = 'EUR'
            GROUP BY k."name1", t."brtxt", vk."waerk"
            ORDER BY sales DESC NULLS LAST
            LIMIT 1
            """
            )
        ).fetchone()
    assert row is not None
    assert row[0] == "Motomarkt Stuttgart GmbH"
    assert "Trading" in (row[1] or "")
    assert float(row[2]) == pytest.approx(6099225.0, rel=0, abs=0.01)
    assert row[3] == "EUR"


def _plan_matches(plan, expected: dict) -> None:
    if "metric" in expected:
        assert plan.metric == expected["metric"]
    if "grain" in expected:
        assert plan.grain == expected["grain"]
    if "operation" in expected:
        assert plan.operation == expected["operation"]
    if "limit" in expected:
        assert plan.limit == expected["limit"]
    if "years" in expected:
        assert plan.filters.get("years") == expected["years"]
    if "years_include" in expected:
        assert set(expected["years_include"]).issubset(set(plan.filters.get("years") or []))
    if "dimensions_include" in expected:
        for d in expected["dimensions_include"]:
            assert d in plan.dimensions
    if expected.get("industry_filter"):
        assert plan.filters.get("industry")
    if "currency" in expected:
        assert plan.filters.get("currency") == expected["currency"]


def test_eval_single_turn_plans_cover_30_plus():
    data = _load_eval()
    cases = data["single_turn"]
    assert len(cases) >= 30
    failures = []
    for case in cases:
        plan = extract_query_plan(case["question"])
        try:
            _plan_matches(plan, case["expected_plan"])
        except AssertionError as e:
            failures.append(f"{case['id']}: {e}")
    assert not failures, "Single-turn plan failures:\n" + "\n".join(failures)


def test_eval_multi_turn_conversations_cover_10_plus():
    data = _load_eval()
    chains = data["multi_turn"]
    assert len(chains) >= 10
    failures = []
    for chain in chains:
        prev_q = ""
        prev_plan_dict = None
        for i, turn in enumerate(chain["turns"]):
            exp = chain["expectations"][i]
            if i == 0:
                plan = extract_query_plan(turn)
                need = True
            else:
                need, plan = resolve_follow_up_sql_need(turn, prev_q, "", prev_plan_dict)
            try:
                assert need is exp["fresh_sql"]
                if exp.get("fresh_sql"):
                    _plan_matches(plan, {k: v for k, v in exp.items() if k != "fresh_sql"})
            except AssertionError as e:
                failures.append(f"{chain['id']}#{i+1} ({turn!r}): {e}")
            prev_q = turn
            prev_plan_dict = plan.to_dict()
    assert not failures, "Multi-turn failures:\n" + "\n".join(failures)
