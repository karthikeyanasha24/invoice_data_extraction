"""Offline acceptance: controlled planner, real executor, synthetic local database.

The SQLite dialect adapter is test-only. Production still executes PostgreSQL.
No provider or configured application database is contacted by these tests.
"""
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlglot import transpile

from app.api import adaptive_query
from app.services import ai_native_pipeline as native


class LocalDatabase:
    def __init__(self, connection):
        self.connection = connection
        self.executed = []

    def rollback(self):
        self.connection.rollback()

    def execute(self, statement, params):
        postgres_sql = str(statement)
        self.executed.append(postgres_sql)
        local_sql = transpile(postgres_sql, read="postgres", write="sqlite")[0]
        return self.connection.execute(text(local_sql), params)


def comparison_sql(base, comparison):
    amount = "CAST(NULLIF(TRIM(CAST(p.netwr AS TEXT)), '') AS NUMERIC)"
    year = "SUBSTRING(TRIM(CAST(k.fkdat AS TEXT)),1,4)"
    first = f"SUM(CASE WHEN {year}='{base}' THEN {amount} END)"
    second = f"SUM(CASE WHEN {year}='{comparison}' THEN {amount} END)"
    return f'''SELECT p.matnr, m.maktx AS material_description, k.waerk AS currency,
        {first} AS period_a, {second} AS period_b, ({second}-{first}) AS change
        FROM vbrp p JOIN "VBRK" k ON p.vbeln=k.vbeln
        LEFT JOIN "MAKT" m ON p.matnr=m.matnr
        WHERE {year} IN ('{base}','{comparison}') AND {amount}<0
        GROUP BY p.matnr,m.maktx,k.waerk ORDER BY period_a ASC LIMIT 10'''


@pytest.mark.parametrize("base,comparison", [(2000, 2001), (2012, 2015), (2022, 2023)])
@pytest.mark.parametrize("pipeline", ["native", "four_stage"])
def test_planner_repair_executes_verified_comparison_and_narrates_actual_local_rows(monkeypatch, base, comparison, pipeline):
    question = f"Show bottom 10 materials by negative billed sales in {base} and compare with {comparison}"
    valid_sql = comparison_sql(base, comparison)
    # An invalid initial draft aggregates across years at unique document grain.
    invalid_sql = valid_sql.replace("p.matnr, m.maktx AS", "k.vbeln, p.matnr, m.maktx AS").replace(
        "GROUP BY p.matnr,m.maktx", "GROUP BY k.vbeln,p.matnr,m.maktx"
    )
    model_sql = MagicMock(side_effect=[(invalid_sql, "offline"), (valid_sql, "offline")])
    monkeypatch.setattr(native, "llm_text", model_sql)
    narrative_inputs = []
    stage_answers = iter([
        {"kind": "data_question", "needs_sql": True, "restated_question": question},
        {"tables": ["vbrp", "VBRK", "MAKT"]},
        {"columns": {}, "joins": []},
    ])

    def controlled_json(system, user):
        if not system.startswith("You are a business analyst"):
            return next(stage_answers), "offline"
        sample = user.split("Sample: ", 1)[1].split("\n", 1)[0]
        rows = json.loads(sample)
        narrative_inputs.append(rows)
        return {"summary": f"The local query returned {len(rows)} materials.", "key_findings": []}, "offline"

    monkeypatch.setattr(native, "llm_json", controlled_json)
    if pipeline == "four_stage":
        from app.services import four_stage_db_pipeline as four_stage
        from app.services.semantic_requirements import required_semantics

        def select_tables(question, ctx):
            ctx.tables = ["vbrp", "VBRK", "MAKT"]
            ctx.semantic_requirements = required_semantics(question)

        def select_columns(question, ctx):
            ctx.columns = ["vbrp.vbeln", "vbrp.matnr", "vbrp.netwr", "VBRK.vbeln", "VBRK.fkdat", "VBRK.waerk", "MAKT.matnr", "MAKT.maktx"]

        def select_plan(question, ctx, db):
            ctx.query_plan = {"metric": "billed_sales"}

        def local_narrative(question, sql, rows, ctx, **kwargs):
            narrative_inputs.append(rows)
            return {"summary": f"The local query returned {len(rows)} materials.", "findings": []}

        monkeypatch.setattr(four_stage, "pipeline1_table_selection", select_tables)
        monkeypatch.setattr(four_stage, "pipeline2_column_selection", select_columns)
        monkeypatch.setattr(four_stage, "pipeline25_query_plan", select_plan)
        stage_sql = MagicMock(side_effect=[invalid_sql, valid_sql])
        monkeypatch.setattr(four_stage, "pipeline3_sql_generation", stage_sql)
        monkeypatch.setattr(four_stage, "pipeline4_result_analysis", local_narrative)
        # Any accidental provider call makes this offline acceptance test fail.
        monkeypatch.setattr(four_stage, "analyze_json", MagicMock(side_effect=AssertionError("external model call")))
        monkeypatch.setattr(four_stage, "complete_text", MagicMock(side_effect=AssertionError("external model call")))
    monkeypatch.setattr(adaptive_query, "apply_statement_timeout", lambda *a, **kw: None)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            connection.connection.driver_connection.create_function(
                "LPAD", 3, lambda value, width, fill: None if value is None else str(value).rjust(width, fill)[:width]
            )
            connection.execute(text('CREATE TABLE "VBRK" (vbeln TEXT, fkdat TEXT, waerk TEXT)'))
            connection.execute(text('CREATE TABLE vbrp (vbeln TEXT, posnr TEXT, matnr TEXT, netwr TEXT)'))
            connection.execute(text('CREATE TABLE "MAKT" (mandt TEXT, matnr TEXT, spras TEXT, maktx TEXT, maktg TEXT)'))
            connection.execute(text('INSERT INTO "VBRK" VALUES (:doc,:day,\'USD\')'), [
                {"doc": "B1", "day": f"{base}1212"}, {"doc": "B2", "day": f"{base}0601"},
                {"doc": "B3", "day": f"{comparison}0701"}, {"doc": "B4", "day": f"{base-1}0701"},
            ])
            connection.execute(text('INSERT INTO vbrp VALUES (:doc,:item,:material,:amount)'), [
                {"doc": "B1", "item": "2", "material": "M1", "amount": "-2.76"},
                {"doc": "B2", "item": "1", "material": "M2", "amount": "-1.25"},
                {"doc": "B3", "item": "1", "material": "M1", "amount": "-1.00"},
                {"doc": "B4", "item": "1", "material": "M1", "amount": "-999.00"},
            ])
            connection.execute(text('INSERT INTO "MAKT" VALUES (:client,:material,:language,:label,\'\')'), [
                {"client": "100", "material": "M1", "language": "E", "label": "English pizza"} for _ in range(10)
            ] + [
                {"client": "100", "material": "M1", "language": "D", "label": "German pizza"},
                {"client": "100", "material": "M2", "language": "D", "label": "German bread"},
            ])
            connection.commit()
            database = LocalDatabase(connection)
            if pipeline == "native":
                result = native.run_ai_native_pipeline(question, database, adaptive_query._execute_sql)
                assert result is not None and result["answer_status"] == "SUCCESS"
                assert model_sql.call_count == 2
                assert "unique dated" in model_sql.call_args.args[1]
                rows = result["data"]
                summary = result["summary"]
            else:
                result = four_stage.run_four_stage_database_query(question, database, adaptive_query._execute_sql)
                assert not result.get("error"), result.get("detail")
                assert stage_sql.call_count == 2
                assert any("unique dated" in error for error in result["pipeline_log"]["SQL_VALIDATION"]["errors"])
                rows = result["rows"]
                summary = result["narrative"]["summary"]
            assert len(database.executed) == 1  # The invalid draft never reached SQL execution.
            assert "ROW_NUMBER() OVER" in database.executed[0]
            assert len(rows) == 2
            assert [row["matnr"] for row in rows] == ["M1", "M2"]
            assert rows[0]["period_a"] == pytest.approx(-2.76)
            assert rows[0]["period_b"] == pytest.approx(-1.00)
            assert rows[0]["change"] == pytest.approx(1.76)
            assert rows[1]["period_a"] == pytest.approx(-1.25)
            assert rows[1]["period_b"] is None and rows[1]["change"] is None
            assert rows[0]["material_description"] == "English pizza"
            assert narrative_inputs == [rows]
            assert summary == "The local query returned 2 materials."
    finally:
        engine.dispose()
