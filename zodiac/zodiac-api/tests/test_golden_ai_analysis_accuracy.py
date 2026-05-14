"""
Golden regression cases for billing analytics intent + SQL shape (no DB, no OpenAI).
"""
from __future__ import annotations

import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.inspect = lambda *a, **k: None  # type: ignore
    sqlalchemy_stub.text = lambda s: s  # type: ignore
    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_stub.Session = object  # type: ignore
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_stub

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *a, **k: None  # type: ignore
    sys.modules["dotenv"] = dotenv_stub

from app.services.intent_extractor import extract_intent, is_intent_pipeline_appropriate  # noqa: E402
from app.services.intent_sql_planner import build_sql_plan, generate_sql  # noqa: E402
from app.services.ai_query_accuracy import (  # noqa: E402
    calendar_years_in_question,
    evaluate_golden_sql_checks,
    sql_reflects_calendar_years,
)

_SCHEMA = {
    "VBRP": ["VBELN", "NETWR", "MATNR", "MANDT"],
    "VBRK": ["VBELN", "FKDAT", "KUNAG", "KUNRG", "WAERK", "LAND1", "MANDT"],
    "KNA1": ["KUNNR", "NAME1", "LAND1"],
}

_CASES_PATH = os.path.join(os.path.dirname(__file__), "golden_ai_analysis_accuracy.json")


class TestGoldenAiAnalysisAccuracy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_CASES_PATH, "r", encoding="utf-8") as f:
            cls._doc = json.load(f)

    def test_all_golden_cases(self):
        for case in self._doc.get("cases", []):
            cid = case.get("id", "?")
            q = case["question"]
            with self.subTest(case_id=cid):
                if case.get("expect_intent_appropriate") is not None:
                    self.assertEqual(
                        is_intent_pipeline_appropriate(q),
                        case["expect_intent_appropriate"],
                        msg=f"{cid}: intent routing",
                    )
                if not case.get("expect_intent_appropriate"):
                    continue
                intent = extract_intent(q, _SCHEMA)
                if case.get("expect_intent_type"):
                    self.assertEqual(
                        intent.get("intent_type"),
                        case["expect_intent_type"],
                        msg=f"{cid}: intent_type",
                    )
                for y in case.get("expect_year_filters") or []:
                    filt = intent.get("filters") or []
                    has_year = any(
                        (f.get("operator") == "IN_YEAR" and y in str(f.get("value", "")))
                        for f in filt
                    )
                    self.assertTrue(has_year, msg=f"{cid}: missing IN_YEAR {y} in {filt}")
                plan = build_sql_plan(intent, _SCHEMA)
                sql = generate_sql(plan)
                ok, _yq, miss = sql_reflects_calendar_years(q, sql)
                self.assertTrue(ok, msg=f"{cid}: year coverage missing={miss}")
                checks = case.get("sql_checks")
                if checks:
                    good, reasons = evaluate_golden_sql_checks(sql, checks)
                    self.assertTrue(good, msg=f"{cid}: {'; '.join(reasons)} SQL={sql[:400]}")


class TestAiQueryAccuracyHelpers(unittest.TestCase):
    def test_calendar_years_and_sql_reflects(self):
        self.assertEqual(calendar_years_in_question("Sales in 2004 and 2005"), ["2004", "2005"])
        ok, yq, miss = sql_reflects_calendar_years("totals for 2004", "SELECT 1 WHERE fkdat = '20040101'")
        self.assertTrue(ok)
        self.assertEqual(yq, ["2004"])
        self.assertEqual(miss, [])

    def test_evaluate_golden_sql_checks(self):
        good, r = evaluate_golden_sql_checks(
            "SELECT 2004 AS x",
            {"must_contain_any": [["2004"]], "must_not_contain": ["GJAHR = '2004'"]},
        )
        self.assertTrue(good)
        self.assertEqual(r, [])


if __name__ == "__main__":
    unittest.main()
