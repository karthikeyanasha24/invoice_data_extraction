from app.services.schema_index import build_canonical_schema_index
from app.services.schema_context_builder import build_schema_context
from app.services.sap_sql_agent import validate_sql_spec
from app.services.sql_validator import validate_sql
from app.services.sql_generation_sanitizers import sanitize_generated_sap_sql
from app.services.explicit_table_sql import extract_explicit_table_identifiers
from app.services.operational_query_resolver import resolve_operational_query
import json
from pathlib import Path


def test_canonical_schema_index_loads_tables_and_columns() -> None:
    index = build_canonical_schema_index(include_non_sap=True)
    table_map = index.get_table_columns_map()
    assert table_map, "schema index should not be empty"
    assert any(len(cols) > 0 for cols in table_map.values())


def test_validate_sql_spec_reports_unknown_column_with_hint() -> None:
    spec = {
        "tables": [{"name": "VBRK"}, {"name": "VBRP"}],
        "columns": [{"table": "VBRK", "name": "VBELN"}, {"table": "VBRP", "name": "NETWRX"}],
        "joins": [{"left": "VBRK", "right": "VBRP", "on": "VBRK.VBELN = VBRP.VBELN"}],
        "filters": [],
        "group_by": [],
        "order_by": [],
    }
    valid, errors = validate_sql_spec(spec)
    assert not valid
    joined = " | ".join(errors)
    assert "Unknown column" in joined
    assert "Did you mean" in joined


def test_validate_sql_rejects_non_select_statement() -> None:
    schema = {"VBRK": ["vbeln", "fkdat"]}
    valid, err = validate_sql("DELETE FROM VBRK", schema)
    assert not valid
    assert err and "Only SELECT statements are allowed" in err


def test_validate_sql_checks_table_column_references() -> None:
    schema = {"VBRK": ["vbeln", "fkdat"], "VBRP": ["vbeln", "netwr"]}
    sql = 'SELECT a."vbeln", b."netwr" FROM "VBRK" a JOIN "VBRP" b ON a."vbeln" = b."vbeln"'
    valid, err = validate_sql(sql, schema)
    assert valid, err


def test_benchmark_question_suite_exists_and_has_minimum_coverage() -> None:
    path = Path(__file__).resolve().parent / "benchmark_questions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 8


def test_schema_index_suggest_similar_columns_is_case_insensitive() -> None:
    index = build_canonical_schema_index(include_non_sap=True)
    vbrp_cols = index.get_table_columns_map().get("VBRP") or index.get_table_columns_map().get("vbrp")
    if not vbrp_cols or not any(c.lower() == "netwr" for c in vbrp_cols):
        return
    sug = index.suggest_similar_columns("VBRP", "NETWRX", n=2)
    assert sug
    assert any(s.lower() == "netwr" for s in sug)


def test_schema_index_nl_table_scores_boost_domain_tables() -> None:
    index = build_canonical_schema_index(include_non_sap=True)
    ranked = dict(index.score_tables_for_natural_language("vendor invoice totals by currency", None))
    if not ranked:
        return
    assert max(ranked.values()) > 0
    assert any(t in ranked and ranked[t] > 0 for t in ("RBKP", "RSEG", "LFA1"))


def test_nl_lexicon_attaches_revenue_phrases_to_netwr() -> None:
    index = build_canonical_schema_index(include_non_sap=True)
    tbl = index.get_table("VBRP") or index.get_table("vbrp")
    if not tbl:
        return
    netwr = next((c for c in tbl.columns if str(c.name).lower() == "netwr"), None)
    assert netwr is not None
    assert netwr.aliases
    joined = " ".join(netwr.aliases).lower()
    assert "revenue" in joined or "invoice amount" in joined


def test_nl_scoring_boosts_inventory_question() -> None:
    index = build_canonical_schema_index(include_non_sap=True)
    ranked = dict(index.score_tables_for_natural_language("inventory value by material and plant", None))
    if not ranked:
        return
    assert any(t in ranked and ranked[t] > 0 for t in ("MARD", "MBEW", "MARC", "MCHB"))


def test_build_schema_context_preamble_forbids_invented_identifiers() -> None:
    ctx = build_schema_context(question="VBRP line revenue", max_tables=2, max_cols_per_table=6)
    low = ctx.lower()
    assert "do not" in low and "invent" in low


def test_build_schema_context_includes_column_data_types() -> None:
    ctx = build_schema_context(question="VBRK billing document header", max_tables=2, max_cols_per_table=8)
    if not ctx.strip():
        return
    assert "schema contract" in ctx.lower()
    assert "(" in ctx and ")" in ctx
    low = ctx.lower()
    assert "vbrk" in low
    assert "(text)" in low or "(numeric)" in low or "(bigint)" in low or "(integer)" in low


def test_build_schema_context_preamble_includes_nl_table_relevance_line() -> None:
    ctx = build_schema_context(
        question="vendor invoice totals by currency",
        max_tables=10,
        max_cols_per_table=5,
    )
    low = ctx.lower()
    assert "table relevance" in low
    assert "rbkp" in low or "rseg" in low


def test_build_schema_context_fuzzy_column_typo_netwar_to_netwr() -> None:
    ctx = build_schema_context(
        question="sum netwar by billing document for top customers",
        max_tables=10,
        max_cols_per_table=16,
    )
    low = ctx.lower()
    assert "netwr" in low


def test_build_schema_context_fuzzy_table_typo_resolves_to_catalog_name() -> None:
    """Near-miss SAP table tokens (e.g. vbrick) should map to real tables in the CSV."""
    ctx = build_schema_context(
        question="vbrick billing header netwr by customer",
        max_tables=6,
        max_cols_per_table=10,
    )
    low = ctx.lower()
    assert "vbrk" in low


def test_build_schema_context_matches_four_letter_catalog_columns() -> None:
    """Tokens that equal real 4-char column names in CSV should surface those fields."""
    ctx = build_schema_context(
        question="billing breakdown by btyp and otyp for recent documents",
        max_tables=18,
        max_cols_per_table=14,
    )
    low = ctx.lower()
    assert "btyp" in low or "otyp" in low


def test_build_schema_context_quarter_phrase_boosts_period_columns() -> None:
    ctx = build_schema_context(
        question="FAGLFLEXA ledger actuals for Q2 2025 by profit center",
        max_tables=8,
        max_cols_per_table=18,
    )
    low = ctx.lower()
    if "faglflexa" not in low:
        return
    assert "poper" in low


def test_build_schema_context_month_phrase_boosts_calendar_columns() -> None:
    ctx = build_schema_context(
        question="BKPF accounting documents posted in March 2025",
        max_tables=6,
        max_cols_per_table=20,
    )
    low = ctx.lower()
    if "bkpf" not in low:
        return
    assert "monat" in low or "fkdat" in low or "budat" in low


def test_build_schema_context_year_literal_boosts_date_columns() -> None:
    ctx = build_schema_context(
        question="VBRK billing header metrics in 2024",
        max_tables=1,
        max_cols_per_table=22,
    )
    low = ctx.lower()
    assert "vbrk" in low
    assert "fkdat" in low or "gjahr" in low


def test_build_schema_context_synonym_expansion_surfaces_metric_columns() -> None:
    """Business wording (invoice amount) should expand to catalog tokens like netwr."""
    ctx = build_schema_context(
        question="total invoice amount by customer name",
        max_tables=12,
        max_cols_per_table=14,
    )
    low = ctx.lower()
    assert "netwr" in low


def test_build_schema_context_adds_join_candidate_hints_for_shared_columns() -> None:
    ctx = build_schema_context(
        question="join header and item on vbeln and sum netwr",
        max_tables=20,
        max_cols_per_table=8,
    )
    low = ctx.lower()
    if "vbeln" not in low:
        return
    assert "shared columns" in low and "join candidates" in low


def test_build_schema_context_adds_column_ownership_hints() -> None:
    ctx = build_schema_context(
        question="which tables have netwr and fkdat columns",
        max_tables=25,
        max_cols_per_table=8,
    )
    low = ctx.lower()
    if "netwr" not in low and "fkdat" not in low:
        return
    assert "column ownership hints" in low


def test_build_schema_context_adds_shared_columns_for_named_tables() -> None:
    ctx = build_schema_context(
        question="what common columns exist between VBRK and VBRP",
        max_tables=8,
        max_cols_per_table=8,
    )
    low = ctx.lower()
    if "vbrk" not in low or "vbrp" not in low:
        return
    assert "shared columns across named tables" in low


def test_build_schema_context_surfaces_tables_for_sap_column_tokens() -> None:
    """Questions that name SAP columns (no table names) should still pull billing tables."""
    ctx = build_schema_context(
        question="sum netwr by fkdat for last invoices",
        max_tables=35,
        max_cols_per_table=12,
    )
    low = ctx.lower()
    if "netwr" not in low:
        return
    assert "vbrk" in low or "vbrp" in low


def test_build_schema_context_keeps_all_user_named_tables() -> None:
    """Explicit table tokens in the question must all appear in the schema slice."""
    ctx = build_schema_context(
        question="Join VBRK to VBRP and KNA1 for customer billing",
        max_tables=8,
        max_cols_per_table=5,
    )
    low = ctx.lower()
    if "user-referenced tables" not in low:
        return
    assert "vbrk" in low and "vbrp" in low and "kna1" in low


def test_build_schema_context_prioritizes_named_columns() -> None:
    """Columns mentioned in the question should appear earlier in that table's line."""
    ctx = build_schema_context(
        question="VBRP billing item netwr kunnr for revenue",
        max_tables=4,
        max_cols_per_table=25,
    )
    low = ctx.lower()
    if "vbrp" not in low or "netwr" not in low:
        return
    line = next(
        (
            ln
            for ln in ctx.splitlines()
            if "vbrp" in ln.split(":", 1)[0].lower() and "netwr" in ln.lower() and "mandt" in ln.lower()
        ),
        "",
    )
    if not line:
        return
    pos_netwr = line.lower().find("netwr")
    pos_mandt = line.lower().find("mandt")
    assert pos_netwr != -1 and pos_mandt != -1
    assert pos_netwr < pos_mandt


def test_table_name_nl_hints_resolve_and_rank_vbrk() -> None:
    index = build_canonical_schema_index(include_non_sap=True)
    if not index.get_table("VBRK"):
        return
    assert index.resolve_table_name("billing document header") == "VBRK"
    ranked = dict(index.score_tables_for_natural_language("billing document header totals by customer", None))
    if not ranked:
        return
    assert ranked.get("VBRK", 0) > 0


def test_sanitize_generated_sap_sql_casts_hsl_aggregates() -> None:
    sql = (
        'SELECT f."prctr", SUM(f."hsl") AS total_cost '
        'FROM "FAGLFLEXA" AS f '
        'GROUP BY f."prctr" '
        'HAVING SUM(f."hsl") > 0 '
        'ORDER BY total_cost DESC LIMIT 20;'
    )
    out = sanitize_generated_sap_sql(sql, "Top 20 profit centers by total GL cost")
    low = out.lower()
    assert "sum(cast(nullif(trim(cast(f.\"hsl\" as text)), '') as numeric))" in low


def test_extract_explicit_table_identifiers_ignores_generic_invoice_words() -> None:
    q = "Show average total amount and tax amount by currency from invoice app tables"
    ids = [x.lower() for x in extract_explicit_table_identifiers(q)]
    assert "invoice" not in ids
    assert "app" not in ids
    assert "tables" not in ids


def test_explicit_table_extractor_strips_generative_ai_routing_preamble() -> None:
    """Dashboard prepends [...]ROUTING hints; column tokens must not become table names."""
    q = """[ZODIAC_GENERATIVE_CLIENT_ROUTING v=1]
query_mode: new
table_hints:
  - VBRK: { role: transaction_header, columns: [VBELN, FKDAT, KUNRG] }
[/ZODIAC_GENERATIVE_CLIENT_ROUTING]

User question:
Show invoices for the top customer in the last 30 days"""
    ids = extract_explicit_table_identifiers(q)
    assert not ids


def test_operational_resolver_fast_path_invoice_amount_tax_by_currency() -> None:
    q = "Show average total amount and tax amount by currency from invoice app tables"
    out = resolve_operational_query(q, time_scope="current", api_key=None)
    assert out is not None
    sql, query_type = out
    assert query_type == "invoice_amount_tax_by_currency"
    assert "invoice_v2_business_data" in sql
    assert "avg(total_amount)" in sql.lower()
