"""
Pure-Python narrative guardrail helpers for "negative/lowest line amounts" questions.

Goal:
- Compute global numeric stats from a full result rowset.
- Enforce that an executive summary does not claim "all amounts are 0.0" when
  stats show non-zero values.

This module intentionally avoids importing SQLAlchemy/OpenAI/etc so it can be
used in lightweight fixture tests.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


def _parse_float_maybe(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None
    return None


def _infer_measure_and_currency_keys(rows: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    if not rows:
        return None, None
    keys = list((rows[0] or {}).keys())

    measure_key = None
    for k in keys:
        if str(k).lower() == "netwr_line_amount":
            measure_key = k
            break
    if measure_key is None:
        for k in keys:
            kl = str(k).lower()
            if "netwr" in kl:
                parsed_any = any(_parse_float_maybe((r or {}).get(k)) is not None for r in rows[:50])
                if parsed_any:
                    measure_key = k
                    break

    currency_key = None
    for k in keys:
        kl = str(k).lower()
        if kl in {"currency", "waerk", "waers", "rtcur", "hwaer"}:
            currency_key = k
            break

    return measure_key, currency_key


def _format_currency_value(value: float, currency_code: Optional[str]) -> str:
    code = (currency_code or "").upper().strip() if currency_code else ""
    symbol_map = {"USD": "$", "KRW": "₩", "EUR": "€", "GBP": "£"}
    if code in symbol_map:
        return f"{symbol_map[code]}{value:.2f}"
    if code:
        return f"{code} {value:.2f}"
    return f"{value:.2f}"


def _is_negative_or_lowest_line_query(user_query: str) -> bool:
    q = (user_query or "").lower()
    return bool(
        ("negative" in q or "credit memo" in q)
        or ("lowest" in q or "smallest" in q or "minimum" in q)
    ) and ("line" in q or "billing" in q or "netwr" in q)


def compute_global_numeric_stats(rows: List[Dict[str, Any]], question: str = "") -> Dict[str, Any]:
    """
    Compute global stats for numeric "money" columns (primarily netwr_line_amount).
    """
    measure_key, currency_key = _infer_measure_and_currency_keys(rows)
    if not measure_key:
        return {
            "measure_key": None,
            "currency_key": currency_key,
            "row_count_total": len(rows),
            "row_count_with_measure": 0,
        }

    values: List[Tuple[float, Dict[str, Any]]] = []
    for r in rows:
        v = _parse_float_maybe((r or {}).get(measure_key))
        if v is None:
            continue
        values.append((v, r))

    numeric_vals = [v for v, _ in values]
    if not numeric_vals:
        return {
            "measure_key": measure_key,
            "currency_key": currency_key,
            "row_count_total": len(rows),
            "row_count_with_measure": 0,
        }

    tol = 1e-9
    count_negative = sum(1 for v in numeric_vals if v < -tol)
    count_zero = sum(1 for v in numeric_vals if abs(v) <= tol)
    count_positive = sum(1 for v in numeric_vals if v > tol)
    min_netwr = min(numeric_vals)
    max_netwr = max(numeric_vals)

    def _get_currency(row: Dict[str, Any]) -> Optional[str]:
        if not currency_key:
            return None
        c = row.get(currency_key)
        if c is None:
            return None
        s = str(c).strip()
        return s if s else None

    currencies_present = sorted({(_get_currency(r) or "UNKNOWN") for _, r in values})
    if "UNKNOWN" in currencies_present and len(currencies_present) > 1:
        currencies_present = [c for c in currencies_present if c != "UNKNOWN"]

    values_sorted_small = sorted(values, key=lambda t: (t[0], str(t[1].get("vbeln", ""))))
    values_sorted_large = sorted(values, key=lambda t: (-t[0], str(t[1].get("vbeln", ""))))
    values_sorted_positive = [t for t in values_sorted_small if t[0] > tol]

    def _pick_example_row_fields(row: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in ["vbeln", "billing_doc", "posnr", "line_pos", "fkdat", "billing_date", "sold_to_party", "currency"]:
            if k in row:
                out[k] = row.get(k)
        if currency_key and currency_key in row:
            out["currency"] = row.get(currency_key)
        out[measure_key] = row.get(measure_key)
        return out

    top_5_smallest = [{**_pick_example_row_fields(r), "value": round(v, 6)} for v, r in values_sorted_small[:5]]
    top_5_largest = [{**_pick_example_row_fields(r), "value": round(v, 6)} for v, r in values_sorted_large[:5]]

    min_positive_netwr = None
    min_positive_example = None
    if values_sorted_positive:
        min_positive_netwr = float(values_sorted_positive[0][0])
        _, r0 = values_sorted_positive[0]
        min_positive_example = {**_pick_example_row_fields(r0), "value": round(min_positive_netwr, 6)}

    return {
        "measure_key": measure_key,
        "currency_key": currency_key,
        "row_count_total": len(rows),
        "row_count_with_measure": len(numeric_vals),
        "min_netwr": round(min_netwr, 6),
        "max_netwr": round(max_netwr, 6),
        "count_negative": int(count_negative),
        "count_zero": int(count_zero),
        "count_positive": int(count_positive),
        "currencies_present": currencies_present,
        "top_5_smallest": top_5_smallest,
        "top_5_largest": top_5_largest,
        "min_positive_netwr": round(min_positive_netwr, 6) if min_positive_netwr is not None else None,
        "min_positive_example": min_positive_example,
    }


def enforce_negative_lowest_summary_consistency(reply: str, user_query: str, stats: Dict[str, Any]) -> str:
    """
    Deterministically correct the narrative if it contradicts global stats
    (e.g. claims "all amounts are 0" but stats show non-zero).
    """
    if not _is_negative_or_lowest_line_query(user_query):
        return reply

    count_negative = int(stats.get("count_negative") or 0)
    count_zero = int(stats.get("count_zero") or 0)
    count_positive = int(stats.get("count_positive") or 0)
    min_netwr = float(stats.get("min_netwr") or 0.0)
    max_netwr = float(stats.get("max_netwr") or 0.0)

    if (count_negative + count_positive) <= 0:
        # Nothing to correct: everything is zero or missing.
        return reply

    contradiction_patterns = [
        r"all\s+.*amounts?\s+are\s+0(\.0+)?",
        r"all\s+.*line\s+amounts?\s+are\s+0(\.0+)?",
        r"everything\s+is\s+0(\.0+)?",
        r"all\s+identified.*0(\.0+)?",
        r"all\s+billing\s+line\s+amounts?\s+listed\s+are\s+0(\.0+)?",
        r"all\s+.*0\.0",
    ]

    if not any(re.search(pat, reply, flags=re.IGNORECASE) for pat in contradiction_patterns):
        return reply

    top_small = stats.get("top_5_smallest") or []
    top_large = stats.get("top_5_largest") or []

    def _ex_currency(ex: Dict[str, Any]) -> Optional[str]:
        if not ex:
            return None
        c = ex.get("currency")
        return str(c).strip() if c else None

    min_currency = _ex_currency(top_small[0]) if top_small else None
    max_currency = _ex_currency(top_large[0]) if top_large else None
    min_fmt = _format_currency_value(min_netwr, min_currency)
    max_fmt = _format_currency_value(max_netwr, max_currency)

    header_year = None
    m = re.search(r"\b((?:19|20)\d{2})\b", user_query or "")
    if m:
        header_year = m.group(1)

    negative_sentence = (
        "No negative line amounts (< 0) appear in this result set."
        if count_negative == 0
        else f"{count_negative} line(s) have net line amount < 0."
    )
    zero_sentence = f"{count_zero} line(s) have net line amount = 0."
    positive_sentence = f"{count_positive} line(s) have net line amount > 0."

    min_positive_netwr = stats.get("min_positive_netwr")
    smallest_positive_fmt = None
    if count_negative == 0 and min_positive_netwr is not None:
        min_pos_ex = stats.get("min_positive_example") or {}
        min_pos_currency = min_pos_ex.get("currency")
        smallest_positive_fmt = _format_currency_value(float(min_positive_netwr), str(min_pos_currency) if min_pos_currency else None)

    examples: List[str] = []
    for ex in top_small[:3]:
        v = ex.get("value", min_netwr)
        cur = ex.get("currency") or min_currency
        doc = ex.get("billing_doc") or ex.get("vbeln")
        pos = ex.get("line_pos") or ex.get("posnr")
        dt = ex.get("billing_date") or ex.get("fkdat")
        loc_parts = [p for p in [doc, pos, dt] if p not in (None, "")]
        loc = f" ({', '.join(str(p) for p in loc_parts)})" if loc_parts else ""
        examples.append(f"- {_format_currency_value(float(v), str(cur) if cur else None)}{loc}")

    deterministic = (
        "**Executive Summary**\n"
        + (f"For year {header_year}, the SQL result contains non-zero net line amounts.\n" if header_year else "The SQL result contains non-zero net line amounts.\n")
        + f"- Min net line amount: {min_fmt}\n"
        + f"- Max net line amount: {max_fmt}\n"
        + f"- {negative_sentence}\n"
        + f"- {zero_sentence}\n"
        + f"- {positive_sentence}\n"
        + (f"- Smallest positive net line amount: {smallest_positive_fmt}\n" if smallest_positive_fmt else "")
        + "\n"
        + "**Detailed Points**\n"
        + "Smallest values in the result set:\n"
        + "\n".join(examples) if examples else "**Detailed Points**\n- (No example rows available)"
        + "\n\n"
        + "**Short Recommendation**\n"
        + "> Re-check FKDAT year filters and document/type predicates if your expectation was different."
    )

    return deterministic

