"""Unit tests for adaptive_ai_context (no DB, no OpenAI)."""
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

from app.services.adaptive_ai_context import (  # noqa: E402
    analyze_sql_result_shape,
    build_adaptive_query_profile,
    build_result_bound_summary_block,
    choose_dimension_column,
    wants_table_first,
)


class TestQueryProfile(unittest.TestCase):
    def test_rank_kind(self):
        p = build_adaptive_query_profile("top 5 customers by revenue in 1999")
        self.assertEqual(p["kind"], "rank")
        self.assertIn("rank", p["tags"])

    def test_trend_kind(self):
        p = build_adaptive_query_profile("revenue trend over time by month")
        self.assertEqual(p["kind"], "trend")

    def test_explicit_tables_listed(self):
        p = build_adaptive_query_profile("SELECT * FROM VBRK limit 5")
        self.assertIn("VBRK", " ".join(p.get("explicit_tables") or []))

    def test_compare_two_years(self):
        p = build_adaptive_query_profile("Compare total revenue 1998 vs 1999")
        self.assertEqual(p["kind"], "compare")


class TestResultShape(unittest.TestCase):
    def test_mixed_currency(self):
        rows = [
            {"cust": "A", "total": 100, "waerk": "USD"},
            {"cust": "B", "total": 200, "waerk": "EUR"},
        ]
        s = analyze_sql_result_shape(rows, "SELECT ...")
        self.assertTrue(s["mixed_currency"])
        self.assertIn("total", s["measure_columns"])

    def test_choose_dimension_prefers_name(self):
        s = {
            "dimension_columns": ["kunnr", "name1"],
            "measure_columns": ["total"],
        }
        self.assertEqual(choose_dimension_column(s), "name1")


class TestTableFirst(unittest.TestCase):
    def test_raw_inspection(self):
        p = build_adaptive_query_profile("last 10 rows from VBRK")
        s = analyze_sql_result_shape([{"a": 1}], "x")
        self.assertTrue(wants_table_first(p, s))


class TestSummaryBinding(unittest.TestCase):
    def test_binding_mentions_kind(self):
        p = build_adaptive_query_profile("top vendors by spend")
        s = analyze_sql_result_shape(
            [{"lifnr": "L1", "t": 1.0}, {"lifnr": "L2", "t": 2.0}], "SELECT 1"
        )
        b = build_result_bound_summary_block(p, s)
        self.assertIn("rank", b.lower())
        self.assertIn("ADAPTIVE CONTEXT", b)


if __name__ == "__main__":
    unittest.main()
