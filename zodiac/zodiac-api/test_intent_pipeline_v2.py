"""
Regression tests for strict intent-driven pipeline modules (no DB, no OpenAI).
"""
from __future__ import annotations

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

from app.services.intent_extractor import extract_intent  # noqa: E402
from app.services.intent_sql_planner import build_sql_plan, generate_sql  # noqa: E402
from app.services.result_validator_v2 import validate_result  # noqa: E402
from app.services.intent_summary import generate_summary  # noqa: E402
from app.services.intent_charting import generate_chart_config  # noqa: E402


SCHEMA = {
    "VBRP": ["VBELN", "NETWR", "MATNR"],
    "VBRK": ["VBELN", "FKDAT", "KUNAG", "WAERK", "LAND1"],
    "KNA1": ["KUNNR", "NAME1", "LAND1"],
}


class TestIntentExtractor(unittest.TestCase):
    def test_compare_years_forces_year_dimension_and_filter(self):
        i = extract_intent("Compare 1998 vs 1999 total revenue", SCHEMA)
        self.assertEqual(i["intent_type"], "comparison")
        self.assertTrue(any(d.get("alias") == "year" for d in i.get("dimensions") or []))
        self.assertTrue(any(f.get("operator") == "IN_YEAR" for f in i.get("filters") or []))

    def test_top_customers_by_revenue_year(self):
        i = extract_intent("Top 5 customers by revenue 1999", SCHEMA)
        self.assertEqual(i["intent_type"], "ranking")
        self.assertTrue(i["ranking"]["enabled"])
        self.assertEqual(i["ranking"]["limit"], 5)
        self.assertTrue(any(d.get("alias") == "customer" for d in i.get("dimensions") or []))
        self.assertTrue(any(f.get("operator") == "IN_YEAR" for f in i.get("filters") or []))

    def test_raw_rows(self):
        i = extract_intent("Show last 5 rows from VBRK", SCHEMA)
        self.assertEqual(i["intent_type"], "raw_inspection")


class TestSqlPlanner(unittest.TestCase):
    def test_year_group_and_filter(self):
        i = extract_intent("Compare 1998 vs 1999 total revenue", SCHEMA)
        plan = build_sql_plan(i, SCHEMA)
        sql = generate_sql(plan)
        self.assertIn("GROUP BY", sql)
        self.assertIn("SUBSTRING", sql)  # year extraction
        self.assertIn("IN ('1998', '1999')", sql)

    def test_sales_by_year_hard_rule_no_product_grouping(self):
        i = extract_intent("Sales by year", SCHEMA)
        plan = build_sql_plan(i, SCHEMA)
        sql = generate_sql(plan)
        self.assertIn("AS year", sql)
        self.assertIn("AS total_sales", sql)
        self.assertIn("GROUP BY", sql)


class TestValidatorSummaryChart(unittest.TestCase):
    def test_validator_blocks_missing_dim(self):
        i = extract_intent("Which years had highest revenue?", SCHEMA)
        # fake result missing year column
        rows = [{"value": 1.0}]
        v = validate_result(i, "SELECT 1", rows)
        self.assertFalse(v["valid"])

    def test_summary_ranking(self):
        i = extract_intent("Top 2 customers by revenue", SCHEMA)
        # mimic planner output columns (customer + value)
        rows = [{"customer": "C1", "total_sales": 10.0}, {"customer": "C2", "total_sales": 9.0}]
        v = validate_result(i, "x", rows)
        self.assertTrue(v["valid"])
        s = generate_summary(i, rows, v)
        self.assertIn("Top", s)

    def test_chart_trend(self):
        i = extract_intent("Revenue trend by year", SCHEMA)
        rows = [{"year": "1998", "total_sales": 1.0}, {"year": "1999", "total_sales": 2.0}, {"year": "2000", "total_sales": 3.0}]
        v = validate_result(i, "x", rows)
        self.assertTrue(v["valid"])
        charts = generate_chart_config(i, rows, v)
        self.assertEqual(charts[0]["chart_type"], "line")
        self.assertEqual(charts[0]["x_key"], "year")


if __name__ == "__main__":
    unittest.main()

