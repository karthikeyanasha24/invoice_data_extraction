"""Regression tests for adaptive NL→SQL hardening (GA critical/high items)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.api.adaptive_query import (
    _chart_title,
    _compose_drilldown_user_message,
    _schema_reference_violations,
    _sql_guardrail_violations,
)
from app.core.cors_origins import origin_is_allowed, resolve_cors_origins
from app.services.adaptive_nl_sql_hardening import (
    apply_ranking_discipline,
    clarification_payload,
    customer_not_found_payload,
    extract_cte_names,
    extract_named_customer,
    extract_requested_limit,
    inject_customer_name_predicate,
    inject_single_currency_filter,
    ranking_wants_single_currency,
    apply_plan_sql_deltas,
    is_supported_business_question,
    public_chart_title,
    repair_generated_sql,
    rewrite_netwr_empty_coalesce,
    sanitize_chart_payloads,
    sql_has_customer_name_filter,
)
from app.services.intent_extractor import _extract_top_n
from app.services.sap_sql_agent import _lookup_sql_catalog

EVAL_PATH = Path(__file__).resolve().parent.parent / "app" / "tests" / "generative_ai_eval_cases.json"

# Verification-report Section K (eval single_turn st01–st20) — must NOT be gated.
SECTION_K_QUESTIONS = [
    "What are total sales?",
    "What are total sales for 2004?",
    "What was the highest-selling customer?",
    "What was the lowest-selling customer?",
    "What is the average sales value?",
    "Show highest sales by customer.",
    "Show top 10 customers.",
    "Which customer generated the most revenue in 2004?",
    "Show customer and industry together for highest sales in 2004.",
    "Show me highest sales for the year 2004 with customer and industry",
    "Who had the highest sales in 2004?",
    "Which customer sold the most in 2004?",
    "Show the top customer for 2004.",
    "Who generated the most revenue during 2004?",
    "Show sales by industry.",
    "Which industry generated the highest sales?",
    "Show the top customers in the Trading industry.",
    "Show sales in 2004.",
    "Show sales by year.",
    "Compare 2003 vs 2004.",
]

_PRODUCT_CTE_SQL = """
WITH base AS (
  SELECT p."matnr" AS material,
         SUM(CAST(COALESCE(p."netwr", '') AS NUMERIC)) AS total_sales
  FROM "vbrp" p
  GROUP BY p."matnr"
)
SELECT * FROM base
ORDER BY total_sales DESC
LIMIT 10
"""

_CATALOG_TOP_CUSTOMERS_SQL = """
SELECT vk.kunag AS customer_number,
       k.name1 AS customer_name,
       SUM(CAST(NULLIF(TRIM(vk.netwr), '') AS NUMERIC)) AS total_sales,
       vk.waerk AS currency
FROM VBRK vk
LEFT JOIN KNA1 k ON vk.kunag = k.kunnr
GROUP BY vk.kunag, k.name1, vk.waerk
ORDER BY total_sales DESC
LIMIT 20
"""


def test_cte_names_multi_and_nested():
    sql = """
    WITH a AS (SELECT 1 AS n),
         b AS (SELECT n FROM a)
    SELECT * FROM b
    """
    assert {"a", "b"} <= extract_cte_names(sql)
    nested = """
    WITH outer_cte AS (
      WITH inner_cte AS (SELECT k."vbeln" FROM "VBRK" k)
      SELECT * FROM inner_cte
    )
    SELECT * FROM outer_cte
    """
    names = extract_cte_names(nested)
    assert "outer_cte" in names
    assert "inner_cte" in names


def test_schema_validator_accepts_cte_alias_base():
    assert _schema_reference_violations(_PRODUCT_CTE_SQL) == []


def test_schema_validator_accepts_cte_name_colliding_with_real_table():
    # KNA1 is a real table but this CTE is a local relation (no vbeln on KNA1).
    sql = """
    WITH kna1 AS (
      SELECT k."vbeln" FROM "VBRK" k
    )
    SELECT kna1.vbeln FROM kna1
    """
    assert _schema_reference_violations(sql) == []


def test_netwr_empty_coalesce_rewrite():
    raw = 'SELECT SUM(CAST(COALESCE(p."netwr", \'\') AS NUMERIC)) FROM "vbrp" p'
    fixed = rewrite_netwr_empty_coalesce(raw)
    assert "COALESCE(p.\"netwr\", '')" not in fixed.replace(" ", "")
    assert "NULLIF" in fixed.upper()
    repaired = repair_generated_sql(_PRODUCT_CTE_SQL, "show top products by sales")
    assert "COALESCE(p.\"netwr\", '')" not in repaired
    assert _schema_reference_violations(repaired) == []


def test_date_empty_guardrail_skips_when_no_date_asked():
    question = "show top products by sales"
    sql = """
    SELECT p."matnr", SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "vbrp" p
    JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"),10,'0') = LPAD(TRIM(k."vbeln"),10,'0')
    GROUP BY p."matnr"
    ORDER BY total DESC
    LIMIT 10
    """
    joined = " | ".join(_sql_guardrail_violations(question, sql)).lower()
    assert "empty values" not in joined


def test_date_empty_guardrail_still_requires_trim_when_year_asked():
    question = "product sales in 2004"
    sql = """
    SELECT p."matnr", SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) AS total
    FROM "vbrp" p
    JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"),10,'0') = LPAD(TRIM(k."vbeln"),10,'0')
    WHERE SUBSTRING(k."fkdat",1,4) = '2004'
    GROUP BY p."matnr"
    """
    joined = " | ".join(_sql_guardrail_violations(question, sql)).lower()
    assert "empty values" in joined


def test_intent_gate_blocks_nonsense_and_allows_section_k():
    for q in ("meaning of life", "tell me a joke", "write a poem"):
        ok, reason = is_supported_business_question(q)
        assert ok is False, q
        payload = clarification_payload(q, reason)
        assert payload["answer_status"] == "CLARIFICATION"
        assert not (payload.get("sql") or "").strip()

    ambiguous_ok, _ = is_supported_business_question("please help with this")
    assert ambiguous_ok is False

    for q in SECTION_K_QUESTIONS:
        ok, reason = is_supported_business_question(q)
        assert ok is True, f"{q} gated as {reason}"

    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    for item in cases["single_turn"][:20]:
        ok, reason = is_supported_business_question(item["question"])
        assert ok is True, f"{item['id']} {item['question']} gated as {reason}"


def test_named_customer_fabricated_vs_real():
    fake = "Customer XYZNOEXIST999"
    real = "sales for customer Motomarkt Stuttgart GmbH"
    assert extract_named_customer(fake) == "XYZNOEXIST999"
    named = extract_named_customer(real)
    assert named and "motomarkt" in named.lower()

    unfiltered = _CATALOG_TOP_CUSTOMERS_SQL
    filtered = inject_customer_name_predicate(unfiltered, "XYZNOEXIST999")
    assert sql_has_customer_name_filter(filtered, "XYZNOEXIST999")
    assert "ILIKE" in filtered.upper()

    kunag_only = """
    SELECT vk.kunag, SUM(CAST(NULLIF(TRIM(vk.netwr), '') AS NUMERIC)) AS total_sales
    FROM VBRK vk
    GROUP BY vk.kunag
    """
    filtered2 = inject_customer_name_predicate(kunag_only, "XYZNOEXIST999")
    assert sql_has_customer_name_filter(filtered2, "XYZNOEXIST999")
    assert "EXISTS" in filtered2.upper()

    payload = customer_not_found_payload(fake, "XYZNOEXIST999", filtered)
    assert "no matching customer" in payload["summary"].lower()
    assert payload["rowCount"] == 0
    assert payload.get("entity_not_found") is True


def test_chart_titles_never_contain_continuation_prompt():
    leaked = (
        "This is a CONTINUATION of an analysis session. The user already ran a query; "
        "now they want a NEW SQL query. New request (generate ONE new PostgreSQL SELECT for this): "
        "only Trading industry"
    )
    title = public_chart_title(leaked)
    assert "CONTINUATION" not in title.upper()
    assert "analysis session" not in title.lower()
    assert "trading" in title.lower()
    assert "CONTINUATION" not in _chart_title(leaked, "Results").upper()

    charts = sanitize_chart_payloads(
        [{"title": leaked, "chart_type": "bar", "data": [{"x": 1}]}],
        "only Trading industry",
    )
    assert charts
    assert "CONTINUATION" not in str(charts[0].get("title") or "").upper()

    composed = _compose_drilldown_user_message(
        "only Trading industry",
        "Show me highest sales for the year 2004",
        "SELECT 1",
        [{"customer_name": "Motomarkt"}],
    )
    assert "CONTINUATION" in composed
    assert "CONTINUATION" not in public_chart_title(composed).upper()
    assert _chart_title("only Trading industry", "Results") == "only Trading industry"


def test_top_n_and_single_currency_on_catalog_and_fast_path_helpers():
    q = "five biggest customers"
    assert extract_requested_limit(q) == 5
    assert _extract_top_n(q) == 5

    ranked = apply_ranking_discipline(_CATALOG_TOP_CUSTOMERS_SQL, q)
    assert "LIMIT 5" in ranked.upper().replace("LIMIT  5", "LIMIT 5")
    assert "LIMIT 20" not in ranked.upper()
    assert "waerk" in ranked.lower()
    assert "EUR" in ranked

    mixed_ok = inject_single_currency_filter(_CATALOG_TOP_CUSTOMERS_SQL, "top customers by currency")
    assert "waerk =" not in mixed_ok.lower()
    highest = apply_ranking_discipline(_CATALOG_TOP_CUSTOMERS_SQL, "highest sales for the year 2005 with customer and industry")
    assert "waerk =" not in highest.lower()

    y2004 = inject_single_currency_filter(_CATALOG_TOP_CUSTOMERS_SQL, "highest sales for the year 2004 with customer and industry")
    assert "waerk =" not in y2004.lower()
    explicit_eur = inject_single_currency_filter(_CATALOG_TOP_CUSTOMERS_SQL, "highest sales EUR")
    assert "EUR" in explicit_eur
    explicit_usd = inject_single_currency_filter(_CATALOG_TOP_CUSTOMERS_SQL, "highest sales USD")
    assert "USD" in explicit_usd
    assert ranking_wants_single_currency("five biggest customers") is True
    assert ranking_wants_single_currency("highest sales for the year 2005 with customer and industry") is False

    catalog_sql = _lookup_sql_catalog(q)
    if catalog_sql:
        disciplined = apply_ranking_discipline(catalog_sql, q)
        assert "LIMIT 5" in disciplined.upper()
        assert "LIMIT 20" not in disciplined.upper()


def test_cte_year_compare_without_join_is_not_cartesian_guardrail():
    sql = """
    WITH yearly AS (
      SELECT SUBSTRING(TRIM(k."fkdat"), 1, 4) AS year,
             k."waerk" AS currency,
             SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
      FROM "VBRK" k
      WHERE SUBSTRING(TRIM(k."fkdat"), 1, 4) IN ('2003', '2004')
      GROUP BY 1, 2
    )
    SELECT * FROM yearly
    """
    joined = " | ".join(_sql_guardrail_violations("Compare 2003 vs 2004", sql)).lower()
    assert "join is missing on" not in joined


def test_period_compare_routes_compare_vs_without_sales_word():
    from app.services.compare_query_router import should_route_period_compare, deterministic_year_compare_sql
    assert should_route_period_compare("Compare 2003 vs 2004.")
    sql = deterministic_year_compare_sql(["2003", "2004"])
    assert "2003" in sql and "2004" in sql
    assert "VBRK" in sql


def test_client_question_intent_sql_includes_year_customer_industry():
    from app.services.schema_loader import load_schema_from_mapping_file
    from app.services.intent_extractor import extract_intent
    from app.services.intent_sql_planner import build_sql_plan, generate_sql
    from app.services.adaptive_nl_sql_hardening import inject_year_filters_from_question

    q = "Show me highest sales for the year 2004 with customer and industry"
    schema = load_schema_from_mapping_file(max_columns_per_table=None)
    intent = extract_intent(q, schema)
    sql = generate_sql(build_sql_plan(intent, schema))
    sql = inject_year_filters_from_question(sql, q)
    low = sql.lower()
    assert "2004" in sql
    assert "name1" in low or "customer_name" in low
    assert "industry" in low or "brtxt" in low
    from app.services.adaptive_nl_sql_hardening import inject_year_filters_from_question
    sql = '''SELECT k."name1" FROM "VBRK" v JOIN "KNA1" k ON 1=1 WHERE v."fkdat" IS NOT NULL'''
    out = inject_year_filters_from_question(sql, "highest sales for the year 2004")
    assert "2004" in out
    assert "fkdat" in out.lower()
    origins = resolve_cors_origins(
        "https://zodiac-front.vercel.app",
        allow_all=False,
    )
    assert "https://www.bridgeedi.com" in origins
    assert origin_is_allowed("https://www.bridgeedi.com", origins)
    assert origin_is_allowed("https://zodiac-front.vercel.app", origins)
    assert not origin_is_allowed("https://evil.example", origins)
    assert "*" in resolve_cors_origins("", allow_all=True)


_INTENT_RANK_SQL = """
SELECT
    TRIM(v."kunag") AS customer,
    COALESCE(NULLIF(TRIM(k."name1"), ''), TRIM(v."kunag")) AS customer_name,
    COALESCE(NULLIF(TRIM(t."brtxt"), ''), 'Not available') AS industry,
    TRIM(v."waerk") AS currency,
    SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
FROM "VBRK" v
LEFT JOIN "KNA1" k ON TRIM(k."kunnr") = TRIM(v."kunag")
LEFT JOIN "T016T" t ON TRIM(CAST(k."brsch" AS TEXT)) = TRIM(CAST(t."brsch" AS TEXT))
WHERE v."fkdat" IS NOT NULL
  AND SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)), 1, 4) IN ('2004')
GROUP BY TRIM(v."kunag"), COALESCE(NULLIF(TRIM(k."name1"), ''), TRIM(v."kunag")), COALESCE(NULLIF(TRIM(t."brtxt"), ''), 'Not available'), TRIM(v."waerk")
ORDER BY total_sales DESC
LIMIT 10
"""


def test_compose_nl_and_followup_sql_deltas():
    from app.services.ai_query_plan import compose_nl_from_plan, merge_followup_plan

    prev_q = "Show me highest sales for the year 2004 with customer and industry"
    plan = merge_followup_plan(prev_q, "Only the Trading industry", _INTENT_RANK_SQL)
    composed = compose_nl_from_plan(plan)
    assert "2004" in composed
    assert "trading" in composed.lower()
    sql = apply_plan_sql_deltas(_INTENT_RANK_SQL, plan)
    assert "ILIKE" in sql.upper()
    assert "Trading" in sql

    plan5 = merge_followup_plan(prev_q, "Now show the top 5", sql, plan.to_dict())
    sql5 = apply_plan_sql_deltas(sql, plan5)
    assert re.search(r"LIMIT\s+5", sql5, re.I)
    assert "EUR" in sql5

    plan_cmp = merge_followup_plan(prev_q, "Compare with 2003", sql5, plan5.to_dict())
    sql_cmp = apply_plan_sql_deltas(sql5, plan_cmp)
    assert "2003" in sql_cmp and "2004" in sql_cmp
    assert re.search(r"AS\s+year", sql_cmp, re.I)
    assert not re.search(r"LIMIT\s+\d+", sql_cmp, re.I)

    plan_rm = merge_followup_plan(prev_q, "Remove the Trading filter", sql_cmp, plan_cmp.to_dict())
    sql_rm = apply_plan_sql_deltas(sql_cmp, plan_rm)
    assert "ILIKE" not in sql_rm.upper()

    plan_cnt = merge_followup_plan(prev_q, "Show invoice count instead", sql_rm, plan_rm.to_dict())
    sql_cnt = apply_plan_sql_deltas(sql_rm, plan_cnt)
    assert "count" in sql_cnt.lower() and "vbeln" in sql_cnt.lower()
    assert re.search(r"ORDER BY\s+invoice_count", sql_cnt, re.I)
    assert "ORDER BY total_sales" not in sql_cnt


def test_greeting_returns_friendly_welcome_not_capability_dump():
    for q in ("hi", "hai", "hello", "hey", "i said hi", "thanks"):
        ok, reason = is_supported_business_question(q)
        assert ok is False, q
        assert reason == "greeting", (q, reason)
        payload = clarification_payload(q, reason)
        assert payload["answer_status"] == "CLARIFICATION"
        assert "83 migrated" not in payload["summary"]
        assert "BridgeEDI AI Analyst" not in payload["summary"] or "Hi there" in payload["summary"]
        assert not (payload.get("sql") or "").strip()


def test_intent_gate_allows_short_business_blocks_chit_chat():
    for q in ("sales 2004", "top customers", "invoice count", "highest industry"):
        ok, _reason = is_supported_business_question(q)
        assert ok, q
    for q in ("meaning of life", "weather today", "tell me a joke", "who is the president", "hello",
              "what's your favorite color?", "who invented the telephone", "who is the ceo of microsoft"):
        ok, _reason = is_supported_business_question(q)
        assert not ok, q


_PRIOR_INVOICE_COUNT_ROWS = [
    {
        "year": "2004",
        "customer": "0000001172",
        "customer_name": "CBD Computer Based Design",
        "industry": "High Technology & Electronics",
        "currency": "EUR",
        "invoice_count": 53,
    }
]
_PRIOR_INVOICE_COUNT_CONTEXT = {
    "previousQuestion": "Show invoice count instead",
    "previousSQL": (
        'SELECT COUNT(DISTINCT TRIM(v."vbeln")) AS invoice_count '
        'FROM "VBRK" v WHERE SUBSTRING(TRIM(CAST(v."fkdat" AS TEXT)),1,4) IN (\'2003\',\'2004\')'
    ),
    "previousAnswerStatus": "SUCCESS",
    "data": _PRIOR_INVOICE_COUNT_ROWS,
}
_SIX_STEP_FOLLOWUPS = (
    "Show me highest sales for the year 2004 with customer and industry",
    "Only the Trading industry",
    "Now show the top 5",
    "Compare with 2003",
    "Remove the Trading filter",
    "Show invoice count instead",
)


def _assert_clarification_not_prior_result(payload: dict) -> None:
    assert payload.get("answer_status") == "CLARIFICATION"
    assert payload.get("type") == "clarification"
    assert not (payload.get("sql") or "").strip()
    assert payload.get("charts") in ([], None)
    assert (payload.get("data") or []) == []
    assert payload.get("rowCount", 0) == 0
    blob = json.dumps(payload).lower()
    assert "cbd" not in blob
    assert "computer based" not in blob
    assert "invoice_count" not in blob
    assert "from your result set" not in blob


async def _adaptive_direct(question: str, context=None):
    from unittest.mock import MagicMock, patch
    from app.api.adaptive_query import post_query_adaptive

    with patch(
        "app.api.adaptive_query._followup_analysis",
        side_effect=AssertionError("continuation narrative must not run for gated questions"),
    ):
        return await post_query_adaptive(
            question=question,
            tableHint=None,
            contextData=context,
            overrideSql=None,
            threadId=None,
            db=MagicMock(),
            current_user=None,
        )


def test_intent_gate_blocks_nonsense_after_followup_chain():
    """Test A: valid → follow-up → … → 'Meaning of life' must not re-summarize prior rows."""
    import asyncio

    payload = asyncio.run(_adaptive_direct("Meaning of life", _PRIOR_INVOICE_COUNT_CONTEXT))
    _assert_clarification_not_prior_result(payload)


def test_intent_gate_blocks_nonsense_after_single_valid_query():
    """Test B: one valid query then nonsense, with continuation context attached."""
    import asyncio

    ctx = {
        "previousQuestion": "Show me highest sales for the year 2004 with customer and industry",
        "previousSQL": 'SELECT 1 AS total_sales FROM "VBRK"',
        "previousAnswerStatus": "SUCCESS",
        "data": [{"customer_name": "Motomarkt Stuttgart GmbH", "total_sales": 6099225}],
    }
    payload = asyncio.run(_adaptive_direct("Meaning of life", ctx))
    _assert_clarification_not_prior_result(payload)
    assert "motomarkt" not in json.dumps(payload).lower()
    assert "6099225" not in json.dumps(payload)


def test_intent_gate_blocks_nonsense_as_first_message():
    """Test C: fresh session, no prior context — original gate must still fire."""
    import asyncio

    payload = asyncio.run(_adaptive_direct("Meaning of life", None))
    _assert_clarification_not_prior_result(payload)


def test_intent_gate_blocks_joke_and_favorite_color_after_followup():
    """Test D: continuation context must not bypass the gate for other chit-chat."""
    import asyncio

    for q in ("Tell me a joke", "What's your favorite color?"):
        payload = asyncio.run(_adaptive_direct(q, _PRIOR_INVOICE_COUNT_CONTEXT))
        _assert_clarification_not_prior_result(payload)


def test_intent_gate_still_allows_six_step_followups():
    """Test E: legitimate 6-step follow-ups must remain business-allowed."""
    for q in _SIX_STEP_FOLLOWUPS:
        ok, reason = is_supported_business_question(q)
        assert ok is True, f"{q} gated as {reason}"


def _intent_sql(question: str) -> str:
    from app.services.schema_loader import load_schema_from_mapping_file
    from app.services.intent_extractor import extract_intent
    from app.services.intent_sql_planner import build_sql_plan, generate_sql
    from app.services.adaptive_nl_sql_hardening import (
        apply_ranking_discipline,
        inject_year_filters_from_question,
        inject_lpad_join_keys,
    )

    schema = load_schema_from_mapping_file(max_columns_per_table=None)
    sql = generate_sql(build_sql_plan(extract_intent(question, schema), schema))
    sql = inject_year_filters_from_question(sql, question)
    sql = inject_lpad_join_keys(sql)
    return apply_ranking_discipline(sql, question)


def test_product_year_sql_uses_year_filtered_vbrk_fast_path():
    sql = _intent_sql("Top products 2004")
    low = sql.lower()
    assert "2004" in sql
    assert "sales_clean" not in low
    assert "matnr" in low
    assert re.search(r'from\s+"?vbrk"?', sql, re.I)
    assert "lpad" in low
    assert re.search(r"limit\s+\d+", sql, re.I)
    assert "waerk =" not in low


def test_highest_2004_and_2005_do_not_force_default_eur():
    q2004 = "Show me highest sales for the year 2004 with customer and industry"
    q2005 = "Show me highest sales for the year 2005 with customer and industry"
    s2004 = _intent_sql(q2004)
    s2005 = _intent_sql(q2005)
    assert "2004" in s2004 and "2005" in s2005
    assert not re.search(r"waerk\"?\s*=\s*'EUR'", s2004, re.I)
    assert not re.search(r"waerk\"?\s*=\s*'EUR'", s2005, re.I)
    top5 = apply_ranking_discipline(_CATALOG_TOP_CUSTOMERS_SQL, "five biggest customers")
    assert re.search(r"waerk\"?\s*=\s*'EUR'", top5, re.I)
    eur = inject_single_currency_filter(_CATALOG_TOP_CUSTOMERS_SQL, "highest sales EUR")
    usd = inject_single_currency_filter(_CATALOG_TOP_CUSTOMERS_SQL, "highest sales USD")
    assert re.search(r"waerk\"?\s*=\s*'EUR'", eur, re.I)
    assert re.search(r"waerk\"?\s*=\s*'USD'", usd, re.I)


def test_empty_rows_pass_dimension_validation():
    from app.services.result_validator_v2 import validate_result

    intent = {
        "dimensions": [{"logical": "customer"}, {"logical": "industry"}],
        "metric": {"alias": "total_sales"},
    }
    out = validate_result(intent, "SELECT 1", [])
    assert out["valid"] is True


def test_invoice_count_2004_uses_count_distinct_vbeln():
    sql = _intent_sql("Invoice count 2004")
    low = sql.lower()
    assert "2004" in sql
    assert "count" in low and "vbeln" in low
    assert "count(distinct" in low.replace(" ", "")
    assert not re.search(r"sum\s*\([^\)]*netwr", sql, re.I)
    from app.services.dashboard_query_router import _should_skip_operational_for_sap

    assert _should_skip_operational_for_sap("Show top 10 customers.") is True
    assert _should_skip_operational_for_sap("five biggest customers") is True
    assert _should_skip_operational_for_sap(
        "Show me highest sales for the year 2005 with customer and industry"
    ) is True
    assert _should_skip_operational_for_sap("Failed EDI invoices in the last 30 days") is False


def test_apply_statement_timeout_is_safe_on_none():
    from app.services.adaptive_nl_sql_hardening import apply_statement_timeout

    apply_statement_timeout(None)
    apply_statement_timeout(None, timeout_ms=0)


def test_ensure_chat_tables_is_cached_after_first_success():
    from app.services.chat_thread_store import (
        ensure_chat_tables,
        reset_chat_tables_cache_for_tests,
    )

    class _FakeDb:
        def __init__(self):
            self.calls = 0

        def execute(self, *_a, **_k):
            self.calls += 1

        def commit(self):
            pass

        def rollback(self):
            pass

    reset_chat_tables_cache_for_tests()
    db = _FakeDb()
    ensure_chat_tables(db)
    first = db.calls
    assert first >= 1
    ensure_chat_tables(db)
    ensure_chat_tables(db)
    assert db.calls == first
    reset_chat_tables_cache_for_tests()
