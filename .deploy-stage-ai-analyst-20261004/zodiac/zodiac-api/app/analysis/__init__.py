"""
Lightweight analytics layer for the SAP SQL agent pipeline.
After SQL execution: compute KPIs, generate charts, produce executive insights.
"""
from .metrics_engine import compute_metrics, detect_kpi_columns
from .chart_generator import generate_chart_from_rows
from .insight_generator import generate_analytics_insights

__all__ = [
    "compute_metrics",
    "detect_kpi_columns",
    "generate_chart_from_rows",
    "generate_analytics_insights",
]
