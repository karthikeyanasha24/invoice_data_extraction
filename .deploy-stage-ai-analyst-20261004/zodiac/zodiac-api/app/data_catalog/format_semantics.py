"""Presentation semantics. Does not change stored database values."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def semantic_for_column(name: str) -> Dict[str, Any]:
    n = (name or "").lower()
    if any(x in n for x in ("pct", "percent", "margin", "share", "ratio")):
        return {"semantic_type": "percentage", "precision": 2}
    if any(
        x in n
        for x in (
            "netwr",
            "wavwr",
            "revenue",
            "value",
            "amount",
            "price",
            "netpr",
            "salk3",
            "cost",
            "profit",
        )
    ) and "count" not in n:
        return {"semantic_type": "money", "precision": 2, "currency_field": "currency"}
    if any(x in n for x in ("qty", "quantity", "kwmeng", "fkimg", "menge", "labst", "lbkum", "gamng")):
        return {"semantic_type": "quantity", "precision": 2}
    if n.endswith("_count") or n in {"order_count", "invoice_count", "row_count"} or n.endswith("count"):
        return {"semantic_type": "integer", "precision": 0}
    if any(x in n for x in ("fkdat", "audat", "erdat", "bedat", "edatu", "budat", "date")):
        return {"semantic_type": "date", "format": "human"}
    return {"semantic_type": "text"}


def column_semantics_for_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not rows:
        return {}
    keys = rows[0].keys()
    return {str(k): semantic_for_column(str(k)) for k in keys}


def format_value(value: Any, semantic: Optional[Dict[str, Any]] = None) -> str:
    if value is None or value == "":
        return ""
    sem = semantic or {}
    kind = sem.get("semantic_type")
    if kind == "integer":
        try:
            return f"{int(float(value)):,}"
        except (TypeError, ValueError):
            return str(value)
    if kind == "percentage":
        try:
            return f"{float(value):.2f}%"
        except (TypeError, ValueError):
            return str(value)
    if kind in {"money", "quantity"}:
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if kind == "date":
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[6:8]} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(s[4:6])-1]} {s[:4]}"
        return s
    return str(value)
