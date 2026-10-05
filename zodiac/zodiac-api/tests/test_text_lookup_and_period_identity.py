"""Execute regressions for multilingual fanout and impossible document matches."""
import sqlite3
from unittest.mock import MagicMock

import pytest
from sqlglot import exp, parse_one, transpile

from app.services.analytical_sql_safety import canonicalize_text_joins, identity_period_errors
from app.services.sql_structure import sql_structure_errors
from app.services.plan_satisfaction import sql_satisfies_analytical_intent


def reported_sql(base="2000", comparison="2001"):
    return f'''SELECT "vbrp"."vbeln", "vbrp"."posnr", "vbrp"."matnr",
        "MAKT"."maktx" AS "material_description", "VBRK"."fkdat" AS "fkdat_{base}",
        "vbrp"."netwr" AS "netwr_{base}", "v2"."netwr" AS "netwr_{comparison}",
        ("v2"."netwr" - "vbrp"."netwr") AS "difference_{comparison}_minus_{base}"
        FROM vbrp JOIN "VBRK" ON "vbrp"."vbeln" = "VBRK"."vbeln"
        LEFT JOIN ("vbrp" AS "v2" JOIN "VBRK" AS "h2" ON "v2"."vbeln" = "h2"."vbeln"
            AND SUBSTRING(TRIM(CAST("h2"."fkdat" AS TEXT)),1,4) = '{comparison}')
            ON "v2"."vbeln" = "vbrp"."vbeln" AND "v2"."posnr" = "vbrp"."posnr"
        LEFT JOIN "MAKT" ON "vbrp"."matnr" = "MAKT"."matnr"
        WHERE SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)),1,4) = '{base}'
            AND CAST(NULLIF(TRIM(CAST("vbrp"."netwr" AS TEXT)), '') AS NUMERIC) < 0
        ORDER BY CAST(NULLIF(TRIM(CAST("vbrp"."netwr" AS TEXT)), '') AS NUMERIC) ASC LIMIT 10'''


def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE "VBRK" (vbeln TEXT, fkdat TEXT)')
    db.execute('CREATE TABLE "vbrp" (vbeln TEXT, posnr TEXT, matnr TEXT, netwr TEXT)')
    db.execute('CREATE TABLE "MAKT" (mandt TEXT, matnr TEXT, spras TEXT, maktx TEXT, maktg TEXT)')
    db.executemany('INSERT INTO "VBRK" VALUES (?,?)', [("B1", "20001212"), ("B2", "20000601")])
    db.executemany('INSERT INTO vbrp VALUES (?,?,?,?)', [("B1", "000002", "M1", "-2.76"), ("B2", "000001", "M2", "-1.25")])
    db.executemany('INSERT INTO "MAKT" VALUES (?,?,?,?,?)', [
        ("100", "M1", "E", "English pizza", "") for _ in range(10)
    ] + [("100", "M1", "EN", "Other English", ""), ("100", "M1", "D", "German pizza", ""),
         ("100", "M1", "J", "Japanese pizza", ""), ("100", "M2", "D", "German bread", "")])
    return db


def execute(db, sql):
    return [dict(row) for row in db.execute(transpile(sql, read="postgres", write="sqlite")[0])]


def test_reported_query_reproduces_repeated_fact_slots_and_label_lookup_corrects_cardinality():
    db = database()
    try:
        wrong = execute(db, reported_sql())
        assert len(wrong) == 10 and {r["vbeln"] for r in wrong} == {"B1"}
        repaired = canonicalize_text_joins(reported_sql())
        rows = execute(db, repaired)
        assert len(rows) == 2
        assert [(r["vbeln"], r["posnr"]) for r in rows] == [("B1", "000002"), ("B2", "000001")]
        assert rows[0]["material_description"] == "English pizza"
        assert rows[1]["material_description"] == "German bread"
        assert canonicalize_text_joins(repaired) == repaired
        assert all(r["netwr_2001"] is None for r in rows)
    finally:
        db.close()


@pytest.mark.parametrize("base,comparison", [("2000", "2001"), ("2012", "2015"), ("2022", "2023")])
def test_same_document_cross_year_comparison_is_rejected_after_label_repair(base, comparison):
    question = f"Show lowest negative sales in {base} and compare with {comparison}"
    sql = canonicalize_text_joins(reported_sql(base, comparison))
    errors = identity_period_errors(parse_one(sql, read="postgres"))
    assert any("share document identity" in e for e in errors)
    assert any("share document identity" in e for e in sql_structure_errors(sql, question))
    assert not sql_satisfies_analytical_intent(sql, question)


def test_single_language_filter_does_not_leave_duplicate_english_labels():
    sql = '''SELECT p.vbeln, m.maktx FROM vbrp p LEFT JOIN "MAKT" m
        ON p.matnr=m.matnr AND m.spras IN ('E','EN') ORDER BY p.vbeln LIMIT 10'''
    db = database()
    try:
        rows = execute(db, canonicalize_text_joins(sql))
        assert rows == [{"vbeln": "B1", "maktx": "English pizza"}, {"vbeln": "B2", "maktx": None}]
    finally:
        db.close()


def test_explicit_language_filter_and_facet_are_preserved():
    sql = '''SELECT p.vbeln, m.maktx, m.spras FROM vbrp p LEFT JOIN "MAKT" m
        ON p.matnr=m.matnr WHERE m.spras IN ('E','D') ORDER BY p.vbeln,m.spras'''
    db = database()
    try:
        rows = execute(db, canonicalize_text_joins(sql))
        assert rows == [
            {"vbeln": "B1", "maktx": "German pizza", "spras": "D"},
            {"vbeln": "B1", "maktx": "English pizza", "spras": "E"},
            {"vbeln": "B2", "maktx": "German bread", "spras": "D"},
        ]
    finally:
        db.close()


def test_text_join_does_not_inflate_monetary_sums():
    sql = '''SELECT p.matnr, m.maktx, SUM(CAST(p.netwr AS NUMERIC)) AS amount
        FROM vbrp p LEFT JOIN "MAKT" m ON p.matnr=m.matnr GROUP BY p.matnr,m.maktx'''
    db = database()
    try:
        rows = execute(db, canonicalize_text_joins(sql))
        assert sorted(r["amount"] for r in rows) == [-2.76, -1.25]
    finally:
        db.close()


def test_different_document_periods_joined_by_customer_are_valid():
    sql = '''SELECT a.kunag, SUM(a.netwr), SUM(b.netwr) FROM "VBRK" a
        JOIN "VBRK" b ON a.kunag=b.kunag
        WHERE SUBSTRING(a.fkdat,1,4)='2012' AND SUBSTRING(b.fkdat,1,4)='2015' GROUP BY a.kunag'''
    assert not identity_period_errors(parse_one(sql, read="postgres"))


def test_optional_or_identity_match_does_not_imply_same_document():
    sql = '''SELECT a.vbeln FROM "VBRK" a JOIN "VBRK" b ON a.vbeln=b.vbeln OR a.kunag=b.kunag
        WHERE SUBSTRING(a.fkdat,1,4)='2012' AND SUBSTRING(b.fkdat,1,4)='2015' '''
    assert not identity_period_errors(parse_one(sql, read="postgres"))


@pytest.mark.parametrize("first,second", [
    ("a.fkdat >= '20120101' AND a.fkdat < '20130101'", "b.fkdat >= '20150101' AND b.fkdat < '20160101'"),
    ("a.fkdat BETWEEN '20120101' AND '20121231'", "b.fkdat BETWEEN '20150101' AND '20151231'"),
    ("EXTRACT(YEAR FROM a.fkdat)=2012", "EXTRACT(YEAR FROM b.fkdat)=2015"),
])
def test_other_date_syntax_cannot_bypass_document_identity_guard(first, second):
    sql = f'SELECT a.vbeln FROM "VBRK" a JOIN "VBRK" b ON a.vbeln=b.vbeln WHERE {first} AND {second}'
    assert any("share document identity" in e for e in identity_period_errors(parse_one(sql, read="postgres")))


def test_same_document_overlapping_date_scope_is_allowed():
    sql = '''SELECT a.vbeln FROM "VBRK" a JOIN "VBRK" b ON a.vbeln=b.vbeln
        WHERE SUBSTRING(a.fkdat,1,4) IN ('2012','2013') AND SUBSTRING(b.fkdat,1,4)='2013' '''
    assert not identity_period_errors(parse_one(sql, read="postgres"))


def test_document_suffix_equality_does_not_prove_same_document_identity():
    sql = '''SELECT a.vbeln FROM "VBRK" a JOIN "VBRK" b ON RIGHT(a.vbeln,5)=RIGHT(b.vbeln,5)
        WHERE SUBSTRING(a.fkdat,1,4)='2012' AND SUBSTRING(b.fkdat,1,4)='2015' '''
    assert not identity_period_errors(parse_one(sql, read="postgres"))


def test_pivoting_one_dated_document_across_years_is_not_a_valid_comparison_grain():
    sql = '''SELECT k.vbeln, SUM(CASE WHEN SUBSTRING(k.fkdat,1,4)='2012' THEN k.netwr END) AS period_a,
        SUM(CASE WHEN SUBSTRING(k.fkdat,1,4)='2015' THEN k.netwr END) AS period_b
        FROM "VBRK" k GROUP BY k.vbeln'''
    assert any("unique dated" in e for e in identity_period_errors(parse_one(sql, read="postgres")))
    assert not identity_period_errors(parse_one(sql.replace("k.vbeln", "k.kunag"), read="postgres"))


def test_common_executor_blocks_wrong_comparison_before_any_database_call(monkeypatch):
    from app.api.adaptive_query import _execute_sql
    db = MagicMock()
    with pytest.raises(ValueError, match="SQL analytical validation failed"):
        _execute_sql(db, reported_sql(), "Show lowest negative sales in 2000 and compare with 2001")
    db.execute.assert_not_called()


def test_native_planner_repair_cannot_execute_or_narrate_same_invalid_comparison(monkeypatch):
    from app.services import ai_native_pipeline as native
    question = "Show lowest negative sales in 2000 and compare with 2001"
    model_json = MagicMock(side_effect=[
        ({"kind": "data_question", "needs_sql": True, "restated_question": question}, "mock"),
        ({"tables": ["vbrp", "VBRK", "MAKT"]}, "mock"),
        ({"columns": {}, "joins": []}, "mock"),
    ])
    monkeypatch.setattr(native, "llm_json", model_json)
    model_sql = MagicMock(return_value=(reported_sql(), "mock"))
    monkeypatch.setattr(native, "llm_text", model_sql)
    executor = MagicMock()
    assert native.run_ai_native_pipeline(question, MagicMock(), executor) is None
    executor.assert_not_called()
    assert model_json.call_count == 3  # No result narrative without validated SQL.
    assert model_sql.call_count == 2


def test_native_repair_that_drops_requested_comparison_is_rejected(monkeypatch):
    from app.services import ai_native_pipeline as native
    question = "Show lowest negative sales in 2000 and compare with 2001"
    monkeypatch.setattr(native, "llm_json", MagicMock(side_effect=[
        ({"kind": "data_question", "needs_sql": True, "restated_question": question}, "mock"),
        ({"tables": ["vbrp", "VBRK", "MAKT"]}, "mock"),
        ({"columns": {}, "joins": []}, "mock"),
    ]))
    monkeypatch.setattr(native, "llm_text", MagicMock(side_effect=[
        (reported_sql(), "mock"), ('SELECT COUNT(*) AS n FROM "VBRK"', "mock"),
    ]))
    executor = MagicMock()
    assert native.run_ai_native_pipeline(question, MagicMock(), executor) is None
    executor.assert_not_called()


@pytest.mark.parametrize("base,comparison", [("2000", "2001"), ("2012", "2015")])
def test_fallback_comparison_preserves_base_period_ranking_instead_of_ranking_change(base, comparison):
    from app.services.adaptive_structured_sql import build_period_compare_sql
    question = f"Show bottom 10 customers by negative billed sales in {base} and compare with {comparison}"
    sql = build_period_compare_sql(question, ["VBRK", "KNA1"], force_dims=["customer"])
    assert sql and 'ORDER BY "period_a" ASC' in sql
    assert "AS NUMERIC) < 0" in sql
    growth = build_period_compare_sql(
        f"Show top 10 customers with the largest billed sales increase from {base} to {comparison}",
        ["VBRK", "KNA1"], force_dims=["customer"],
    )
    assert growth and 'ORDER BY "change" DESC' in growth


@pytest.mark.parametrize("base,comparison", [("2000", "2001"), ("2012", "2015")])
@pytest.mark.parametrize("scoped", [False, True])
def test_base_period_negative_ranking_excludes_comparison_only_customers(base, comparison, scoped):
    from app.services.adaptive_structured_sql import build_period_compare_sql
    question = f"Show bottom 10 customers by negative billed sales in {base} and compare with {comparison}"
    if scoped:
        question += " for the same customers returned previously"
    semantic = {"prior_result_rows": [{"customer_id": key} for key in ("A", "B", "E")]}
    sql = build_period_compare_sql(question, ["VBRK", "KNA1"], semantic, force_dims=["customer"])
    assert sql
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.create_function("LPAD", 3, lambda v, n, fill: None if v is None else str(v).rjust(n, fill)[:n])
    db.execute('CREATE TABLE "VBRK" (vbeln TEXT, kunag TEXT, fkdat TEXT, netwr TEXT, waerk TEXT)')
    db.execute('CREATE TABLE "KNA1" (kunnr TEXT, name1 TEXT)')
    db.executemany('INSERT INTO "KNA1" VALUES (?,?)', [(key, key) for key in ("A", "B", "C", "D", "E")])
    db.executemany('INSERT INTO "VBRK" VALUES (?,?,?,?,?)', [
        ("I1", "A", base + "0101", "-10", "USD"),
        ("I2", "A", comparison + "0101", "-8", "USD"),
        ("I3", "B", comparison + "0101", "-999", "USD"),
        ("I4", "C", base + "0101", "0", "USD"),
        ("I5", "D", base + "0101", "10", "USD"),
        ("I6", "E", base + "0101", "-5", "USD"),
    ])
    try:
        # SQLite supports this template directly, including named VALUES CTE
        # columns that sqlglot's SQLite writer otherwise drops.
        rows = [dict(row) for row in db.execute(sql)]
    finally:
        db.close()
    assert [row["customer_id"].lstrip("0") for row in rows] == ["A", "E"]
    assert rows[0]["period_a"] == -10 and rows[0]["period_b"] == -8
    assert rows[1]["period_a"] == -5 and rows[1]["period_b"] == 0


def test_result_validation_rejects_comparison_only_zero_in_negative_baseline_ranking():
    from app.services.plan_satisfaction import result_matches_analytical_intent
    question = "Show bottom 10 customers by negative billed sales in 2012 and compare with 2015"
    rows = [{"customer_id": "A", "currency": "USD", "period_a": -10, "period_b": -8, "change": 2},
            {"customer_id": "B", "currency": "USD", "period_a": 0, "period_b": -999, "change": -999}]
    assert any("base-period ranking" in w for w in result_matches_analytical_intent(rows, question))
    assert not any("base-period ranking" in w for w in result_matches_analytical_intent(rows[:1], question))
