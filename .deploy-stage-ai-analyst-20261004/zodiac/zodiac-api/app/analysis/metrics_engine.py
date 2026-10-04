"""
Metrics engine: extract KPIs from SQL result rows.
Computes total, avg, max, min for numeric columns; auto-detects revenue, cost, margin, quantity, spend.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Column name patterns that map to standard KPIs (case-insensitive)
REVENUE_LIKE = {"revenue", "sales", "netwr", "total_sales", "billed", "amount", "value", "income"}
COST_LIKE = {"cost", "hsl", "spend", "expense", "purchase_cost", "total_cost", "amount"}
MARGIN_LIKE = {"margin", "profit", "gross_margin", "contribution"}
QUANTITY_LIKE = {"quantity", "menge", "qty", "count", "fkimg", "volume"}
SPEND_LIKE = {"spend", "total_spend", "rmwwr", "invoice_amount"}


def _to_float(v: Any) -> Optional[float]:
    """Convert value to float; handle Decimal, int, str."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _is_numeric_column(rows: List[Dict[str, Any]], key: str) -> bool:
    """Return True if the column has numeric values in the first N rows."""
    if not rows:
        return False
    count = 0
    for r in rows[:50]:
        v = r.get(key)
        if _to_float(v) is not None:
            count += 1
    return count >= min(3, len(rows)) or (count > 0 and len(rows) == 1)


def detect_kpi_columns(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Detect which numeric columns are revenue, cost, margin, quantity, spend.
    Returns dict: column_name -> kpi_type (e.g. "revenue", "cost").
    """
    if not rows:
        return {}
    first = rows[0]
    out: Dict[str, str] = {}
    for key in first.keys():
        if not _is_numeric_column(rows, key):
            continue
        k = (key or "").lower().replace(" ", "_")
        if any(p in k for p in REVENUE_LIKE):
            out[key] = "revenue"
        elif any(p in k for p in COST_LIKE):
            out[key] = "cost"
        elif any(p in k for p in MARGIN_LIKE):
            out[key] = "margin"
        elif any(p in k for p in QUANTITY_LIKE):
            out[key] = "quantity"
        elif any(p in k for p in SPEND_LIKE):
            out[key] = "spend"
        elif _is_numeric_column(rows, key):
            out[key] = "metric"
    return out


def compute_metrics(
    rows: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    max_numeric_columns: int = 10,
) -> Dict[str, Any]:
    """
    Extract KPIs from SQL result rows (list of dicts).
    Returns dict: column_name -> { total, avg, max, min, count, kpi_type }.
    """
    if not rows:
        return {}
    first = rows[0]
    keys = columns or list(first.keys())
    kpi_hints = detect_kpi_columns(rows)
    metrics: Dict[str, Any] = {}
    numeric_count = 0
    for col in keys:
        if col not in first:
            continue
        values = []
        for r in rows:
            v = _to_float(r.get(col))
            if v is not None:
                values.append(v)
        if not values:
            continue
        numeric_count += 1
        if numeric_count > max_numeric_columns:
            break
        total = sum(values)
        n = len(values)
        metrics[col] = {
            "total": round(total, 2),
            "avg": round(total / n, 2) if n else 0,
            "max": round(max(values), 2),
            "min": round(min(values), 2),
            "count": n,
            "kpi_type": kpi_hints.get(col, "metric"),
        }
    return metrics
