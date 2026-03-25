"""
Regression tests: compare routing, adaptive chart selection, merged year rows.
No DB or OpenAI — pure logic.
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

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class _DummyOpenAI:
        def __init__(self, *a, **k):
            pass

    openai_stub.OpenAI = _DummyOpenAI  # type: ignore
    sys.modules["openai"] = openai_stub

from app.services.compare_query_router import (  # noqa: E402
    merge_year_compare_rows_for_chart,
    should_route_period_compare,
)
from app.services.ai_chart_generator import (  # noqa: E402
    analyze_visualization_needs,
    is_raw_table_inspection_query,
    plan_adaptive_chart_specs,
    plan_compare_year_bar_chart,
)


class TestCompareRouting(unittest.TestCase):
    def test_should_route_two_years_revenue(self):
        self.assertTrue(
            should_route_period_compare("Compare 1998 vs 1999 total revenue")
        )
        self.assertTrue(
            should_route_period_compare("How did total revenue change from 1998 to 1999?")
        )
        self.assertTrue(
            should_route_period_compare("1998 vs 1999 total revenue")
        )

    def test_merge_year_rows(self):
        datasets = [
            ("y1998", [{"total_revenue": 100.0, "y": "1998"}]),
            ("y1999", [{"total_revenue": 150.0}]),
        ]
        merged = merge_year_compare_rows_for_chart(["1998", "1999"], datasets)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["calendar_year"], "1998")
        self.assertEqual(merged[0]["total_revenue"], 100.0)
        self.assertEqual(merged[1]["total_revenue"], 150.0)


class TestAdaptiveCharts(unittest.TestCase):
    def test_raw_inspection_is_table_not_bar(self):
        self.assertTrue(is_raw_table_inspection_query("show me the last 5 rows from VBRK"))
        specs = plan_adaptive_chart_specs(
            [{"a": 1, "b": "x"}],
            "last 5 rows please",
            "SELECT 1",
            None,
            "new",
        )
        self.assertIsNotNone(specs)
        assert specs is not None
        self.assertEqual(specs[0].chart_type, "table")

    def test_compare_question_with_year_column_gets_bar(self):
        rows = [
            {"calendar_year": "1998", "total_revenue": 10.0},
            {"calendar_year": "1999", "total_revenue": 12.0},
        ]
        specs = plan_adaptive_chart_specs(
            rows,
            "Compare revenue between 1998 and 1999",
            "SELECT ...",
            None,
            "new",
        )
        self.assertIsNotNone(specs)
        assert specs is not None
        self.assertEqual(specs[0].chart_type, "bar")
        self.assertEqual(specs[0].x_key, "calendar_year")
        self.assertIn("total_revenue", specs[0].y_keys or [])

    def test_ranking_query_bar(self):
        rows = [{"kunnr": "C1", "total": 500}, {"kunnr": "C2", "total": 400}]
        specs = plan_adaptive_chart_specs(
            rows,
            "top customers by revenue 1999",
            "SELECT ...",
            None,
            "new",
        )
        self.assertIsNotNone(specs)
        assert specs is not None
        self.assertEqual(specs[0].chart_type, "bar")

    def test_single_row_aggregate_table(self):
        specs = plan_adaptive_chart_specs(
            [{"total_revenue": 1.0}],
            "total revenue for 1999",
            "SELECT SUM...",
            None,
            "new",
        )
        self.assertIsNotNone(specs)
        assert specs is not None
        self.assertEqual(specs[0].chart_type, "table")

    def test_plan_compare_year_bar_chart(self):
        specs = plan_compare_year_bar_chart(
            [
                {"calendar_year": "1998", "total_revenue": 100},
                {"calendar_year": "1999", "total_revenue": 120},
            ],
            "Compare 1998 vs 1999",
        )
        self.assertIsNotNone(specs)
        assert specs is not None
        self.assertEqual(specs[0].chart_type, "bar")
        self.assertEqual(specs[0].x_key, "calendar_year")

    def test_analyze_visualization_needs_returns_adaptive_without_openai(self):
        """Adaptive path must return before any LLM call."""
        specs = analyze_visualization_needs(
            [{"calendar_year": "1998", "total_revenue": 1}, {"calendar_year": "1999", "total_revenue": 2}],
            "Compare 1998 and 1999 revenue",
            "new",
            "SELECT 1",
            result_scope=None,
        )
        self.assertTrue(len(specs) >= 1)
        self.assertEqual(specs[0].chart_type, "bar")


if __name__ == "__main__":
    unittest.main()
