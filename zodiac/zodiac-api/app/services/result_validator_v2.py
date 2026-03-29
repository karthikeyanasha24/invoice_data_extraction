"""
Strict result validation: blocks summaries/charts when SQL result doesn't match intent.
"""

from __future__ import annotations

from typing import Any, Dict, List


def validate_result(intent: Dict[str, Any], sql: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    cols = set()
    if rows and isinstance(rows[0], dict):
        cols = {str(k) for k in rows[0].keys()}
    dims = intent.get("dimensions") or []
    metric = intent.get("metric") or {}
    metric_alias = str(metric.get("alias") or metric.get("logical") or "value")

    errors: List[str] = []
    warnings: List[str] = []

    for d in dims:
        logical = str(d.get("alias") or d.get("logical") or "")
        if not logical:
            continue
        # Adaptive: accept if the logical name itself OR any column whose name
        # contains or starts with the logical name is present in the result.
        # This works without any hardcoded map: "product" matches "product",
        # "product_name", "product_id", etc. automatically.
        found = any(
            col == logical or col.startswith(logical + "_") or col.endswith("_" + logical)
            for col in cols
        )
        if not found:
            errors.append(f"Missing required dimension column: {logical}")

    if metric_alias and metric_alias not in cols and rows:
        errors.append(f"Missing required metric column: {metric_alias}")

    # Ranking: best-effort check sortedness on first few rows
    ranking = intent.get("ranking") or {}
    if ranking.get("enabled") and rows and metric_alias in cols:
        order = str(ranking.get("order") or "desc").lower()
        vals = []
        for r in rows[:8]:
            v = r.get(metric_alias)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        if len(vals) >= 3:
            if order == "desc" and any(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
                warnings.append("Ranking requested but result does not appear sorted descending (sample check).")
            if order == "asc" and any(vals[i] > vals[i + 1] for i in range(len(vals) - 1)):
                warnings.append("Ranking requested but result does not appear sorted ascending (sample check).")

    # Currency mix warning
    currency_keys = [k for k in cols if k.lower() in ("waerk", "waers", "currency", "curr")]
    if currency_keys:
        seen = set()
        for r in rows[:400]:
            for ck in currency_keys:
                v = r.get(ck)
                if v is not None and str(v).strip():
                    seen.add(str(v).strip())
        if len(seen) > 1:
            warnings.append(f"Mixed currencies present in rows ({', '.join(sorted(list(seen))[:6])}).")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "observed_columns": sorted(list(cols)),
        "metric_alias": metric_alias,
    }

