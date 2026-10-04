"""
Chart generator: produce a simple bar chart from SQL result rows (matplotlib).
Returns base64 PNG or chart spec for frontend.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try optional matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False
    plt = None


def _detect_label_and_value_columns(rows: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """Pick best label column (x) and value column (y) for a bar chart."""
    if not rows:
        return None, None
    first = rows[0]
    label_candidates = [
        "customer_name", "name1", "product", "material", "maktx", "description",
        "profit_center", "prctr", "country", "land1", "currency", "waerk",
        "customer", "vendor", "industry", "brsch",
    ]
    value_candidates = [
        "total_sales", "revenue", "netwr", "total", "total_cost", "hsl",
        "amount", "quantity", "menge", "count", "sum",
    ]
    label_key = None
    value_key = None
    for k in label_candidates:
        if k in first and first.get(k) is not None:
            label_key = k
            break
    if not label_key:
        for k in first.keys():
            v = first.get(k)
            if v is not None and not isinstance(v, (int, float)):
                try:
                    float(str(v).replace(",", ""))
                except ValueError:
                    label_key = k
                    break
    for k in value_candidates:
        if k in first:
            v = first.get(k)
            if v is not None and isinstance(v, (int, float)):
                value_key = k
                break
    if not value_key:
        for k in first.keys():
            v = first.get(k)
            if v is not None and isinstance(v, (int, float)):
                value_key = k
                break
    return label_key, value_key


def generate_chart_from_rows(
    rows: List[Dict[str, Any]],
    title: str = "Result",
    max_bars: int = 20,
    return_base64: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Generate a bar chart from rows (list of dicts).
    Returns either a chart spec with base64 image, or Recharts-compatible data.
    """
    if not rows or not _MATPLOTLIB_AVAILABLE:
        return None
    label_key, value_key = _detect_label_and_value_columns(rows)
    if not label_key or not value_key:
        return None
    try:
        x = []
        y = []
        for r in rows[:max_bars]:
            lb = r.get(label_key)
            val = r.get(value_key)
            if lb is not None and val is not None:
                try:
                    y_val = float(val) if not isinstance(val, (int, float)) else val
                except (TypeError, ValueError):
                    continue
                x.append(str(lb)[:30])
                y.append(y_val)
        if not x or not y:
            return None
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(range(len(x)), y, color="steelblue", alpha=0.8)
        ax.set_xticks(range(len(x)))
        ax.set_xticklabels(x, rotation=45, ha="right")
        ax.set_ylabel(value_key.replace("_", " ").title())
        ax.set_title(title[:80])
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        if return_base64:
            b64 = base64.b64encode(buf.read()).decode("utf-8")
            return {
                "chart_type": "image",
                "title": title,
                "description": f"Bar chart: {label_key} vs {value_key}",
                "image_base64": b64,
                "data": [{"name": a, "value": b} for a, b in zip(x, y)],
            }
        return {
            "chart_type": "bar",
            "title": title,
            "x_key": "name",
            "value_key": "value",
            "data": [{"name": a, "value": b} for a, b in zip(x, y)],
        }
    except Exception as e:
        logger.warning("chart_generator: failed to create chart: %s", e)
        return None
