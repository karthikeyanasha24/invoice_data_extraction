"""
Deterministic, intent-locked summaries (no generic filler).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _fmt(v: Any, currency: Optional[str] = None) -> str:
    if isinstance(v, float):
        base = f"{v:,.2f}"
    elif isinstance(v, int):
        base = f"{v:,d}"
    else:
        base = str(v)
    c = (currency or "").strip().upper()
    if c:
        return f"{base} {c}"
    return base


def _currency_from_row(row: Dict[str, Any]) -> str:
    for key in ("waerk", "currency", "WAERK", "CURRENCY"):
        if key in row and row[key] is not None:
            s = str(row[key]).strip()
            if s:
                return s.upper()
    return ""


def _currency_annotation_for_rows(rows: List[Dict[str, Any]], _metric_alias: str) -> Tuple[str, bool]:
    """
    Returns (suffix_for_plain_numbers, mixed_currency_flag).
    When rows carry multiple currencies, caller should mention mixed currencies.
    """
    if not rows:
        return "", False
    cur_set = set()
    for r in rows:
        c = _currency_from_row(r)
        if c:
            cur_set.add(c)
    if len(cur_set) <= 1:
        only = next(iter(cur_set)) if cur_set else ""
        return only, False
    return "", True


def _years_phrase_from_intent(intent: Dict[str, Any]) -> str:
    """Human-readable year filter for ranking headlines (e.g. ' in 2004')."""
    years: List[str] = []
    for f in intent.get("filters") or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("operator") or "").upper() != "IN_YEAR":
            continue
        v = f.get("value")
        if isinstance(v, (list, tuple)):
            years.extend(str(x).strip() for x in v if str(x).strip())
        elif v is not None and str(v).strip():
            years.append(str(v).strip())
    if not years:
        dbg = intent.get("debug") or {}
        for y in dbg.get("years") or []:
            ys = str(y).strip()
            if ys:
                years.append(ys)
    if not years:
        tf = intent.get("time_filter") or {}
        y = tf.get("years")
        if isinstance(y, (list, tuple)):
            years = [str(x).strip() for x in y if str(x).strip()]
    uniq = sorted({y for y in years if y})
    if not uniq:
        return ""
    if len(uniq) == 1:
        return f" in {uniq[0]}"
    return f" in {', '.join(uniq)}"


def generate_summary(intent: Dict[str, Any], rows: List[Dict[str, Any]], validation: Dict[str, Any]) -> str:
    if not validation.get("valid"):
        return (
            "```json\n"
            + str(
                {
                    "error": "RESULT_MISMATCH",
                    "reason": "; ".join(validation.get("errors") or ["Result did not match intent"]),
                }
            )
            + "\n```"
        )
    it = str(intent.get("intent_type") or "")
    metric = intent.get("metric") or {}
    metric_alias = str(metric.get("alias") or metric.get("logical") or "value")
    dims = intent.get("dimensions") or []
    dim0 = dims[0] if dims else None
    dim_logical = str((dim0 or {}).get("alias") or (dim0 or {}).get("logical") or "") if dim0 else ""
    has_names = intent.get("has_customer_names", True)

    def _resolve_dim_key(logical: str, row: dict) -> str:
        """
        Adaptively find the actual column name in `row` for a logical dimension.
        No hardcoded map — works for any column name the SQL happens to generate:
          1. Exact match:          "product"   → "product"
          2. Prefixed match:       "product"   → "product_name", "product_id"
          3. Suffixed match:       "customer"  → "top_customer"
          4. First non-metric col: last resort fallback
        """
        if not logical or not row:
            return logical
        keys = list(row.keys())
        # Exact match
        if logical in keys:
            return logical
        # Prefix match (e.g. "product" matches "product_name", "product_id")
        for k in keys:
            if k.startswith(logical + "_") or k.endswith("_" + logical):
                return k
        # First non-numeric column as last resort (the dimension is usually text)
        for k in keys:
            if not isinstance(row[k], (int, float)):
                return k
        return logical

    dim_key = dim_logical  # default; overridden per-row below

    if not rows:
        return "No rows returned for this query."

    # Raw inspection: factual
    if it == "raw_inspection":
        cols = list(rows[0].keys())
        return (
            f"Returned **{len(rows)}** row(s).\n\n"
            f"- **Columns**: {', '.join(cols[:16])}{'…' if len(cols) > 16 else ''}\n"
        )

    # Trend: mention peak
    if it == "trend" and dim_logical and metric_alias in rows[0]:
        best = None
        best_v = None
        for r in rows:
            v = r.get(metric_alias)
            if isinstance(v, (int, float)):
                if best_v is None or float(v) > float(best_v):
                    best_v = float(v)
                    best = r
        if best is not None:
            best_dim_key = _resolve_dim_key(dim_logical, best)
            cur = _currency_from_row(best)
            return (
                f"**{metric.get('logical', metric_alias)} over {dim_logical}** shows the peak in "
                f"**{best.get(best_dim_key)}** at **{_fmt(best_v, cur)}**."
            )

    # Ranking
    if it == "ranking" and dim_logical:
        top = rows[0]
        top_dim_key = _resolve_dim_key(dim_logical, top)
        top_val = top.get(top_dim_key)

        # Prefer a human-readable name column over a raw ID (e.g. customer_name > customer number)
        name_key = None
        if has_names:
            for candidate in (f"{dim_logical}_name", "name", "name1", "customer_name", "product_name"):
                if candidate in top and candidate != top_dim_key:
                    raw = top.get(candidate)
                    if raw and str(raw).strip() and str(raw).strip() != str(top_val).strip():
                        name_key = candidate
                        break
        display_val = f"{top.get(name_key)} ({top_val})" if name_key else top_val

        metric_label = metric.get("logical", metric_alias)
        total_shown = len(rows)
        year_bit = _years_phrase_from_intent(intent)
        _, mixed_cur = _currency_annotation_for_rows(rows, metric_alias)
        mixed_note = ""
        if mixed_cur:
            mixed_note = " _(mixed currencies — see table)_"

        if total_shown > 1:
            lines = []
            for i, r in enumerate(rows[:total_shown], 1):
                r_dim_key = _resolve_dim_key(dim_logical, r)
                r_id = r.get(r_dim_key)
                r_name = r.get(name_key) if name_key else None
                r_label = (
                    f"{r_name} ({r_id})"
                    if (r_name and str(r_name).strip() and str(r_name).strip() != str(r_id).strip())
                    else str(r_id)
                )
                cur = _currency_from_row(r)
                lines.append(f"{i}. **{r_label}** — **{_fmt(r.get(metric_alias), cur)}**")
            headline = f"Top **{total_shown}** **{dim_logical}**{year_bit} by **{metric_label}**{mixed_note}:\n\n"
            return headline + "\n".join(lines)

        cur0 = _currency_from_row(top)
        id_only_note = ""
        if not has_names and dim_logical == "customer":
            id_only_note = " _(customer numbers only; name master not in schema)_"
        return (
            f"Top **{dim_logical}**{year_bit} is **{display_val}** with **{_fmt(top.get(metric_alias), cur0)}** "
            f"{metric_label}{id_only_note}{mixed_note}."
        )

    # Comparison (year/period dimension) — 2+ rows
    if it == "comparison" and dim_logical and len(rows) >= 2:
        lines_out: List[str] = []
        prev_v: Optional[float] = None
        prev_dim: Any = None
        first_v: Optional[float] = None
        last_v: Optional[float] = None
        first_dim: Any = None
        last_dim: Any = None
        for idx, r in enumerate(rows):
            dk = _resolve_dim_key(dim_logical, r)
            va = r.get(metric_alias)
            dim_val = r.get(dk)
            cur = _currency_from_row(r)
            if isinstance(va, (int, float)):
                fv = float(va)
                if first_v is None:
                    first_v, first_dim = fv, dim_val
                last_v, last_dim = fv, dim_val
                line = f"{idx + 1}. **{dim_val}** = **{_fmt(fv, cur)}**"
                if prev_v is not None and prev_dim is not None:
                    diff = fv - prev_v
                    pct = (diff / prev_v * 100.0) if prev_v != 0 else None
                    pct_s = f" (vs prior: {pct:+.2f}%)" if pct is not None else ""
                    line += pct_s
                lines_out.append(line)
                prev_v, prev_dim = fv, dim_val
            else:
                lines_out.append(f"{idx + 1}. **{dim_val}** = **{_fmt(va, cur)}**")
                prev_dim = dim_val

        overall = ""
        if (
            isinstance(first_v, float)
            and isinstance(last_v, float)
            and first_dim is not None
            and last_dim is not None
            and len(rows) >= 2
        ):
            odiff = last_v - first_v
            opct = (odiff / first_v * 100.0) if first_v != 0 else None
            if opct is not None:
                overall = f"\n\n**Overall change** from **{first_dim}** to **{last_dim}**: **{opct:+.2f}%**."
            else:
                overall = f"\n\n**Overall change** from **{first_dim}** to **{last_dim}**: **{_fmt(odiff)}**."

        return (
            f"**Comparison by {dim_logical}** ({len(rows)} period(s)):\n\n"
            + "\n".join(lines_out)
            + overall
        )

    # Distribution
    if it == "distribution" and dim_logical:
        return f"Distribution of **{metric.get('logical', metric_alias)}** by **{dim_logical}** across **{len(rows)}** categories."

    # Aggregate/lookup/breakdown default: direct statement
    if len(rows) == 1 and metric_alias in rows[0]:
        cur = _currency_from_row(rows[0])
        return f"**{metric.get('logical', metric_alias)}** = **{_fmt(rows[0].get(metric_alias), cur)}**."
    return f"Returned **{len(rows)}** row(s) for intent **{it}**."
