"""
AI analysis constraint validator.

Goal: enforce that the executed SQL actually satisfies explicit user constraints
extracted from the natural-language question (year, billing category/type, count vs
sum semantics, currency).

This is used to:
1) prevent stale/reused SQL from silently ignoring explicit filters
2) suppress charts when SQL cannot satisfy the question (no misleading titles)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


_COMMON_CURRENCY_CODES: Set[str] = {
    "USD",
    "EUR",
    "GBP",
    "KRW",
    "JPY",
    "INR",
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "SEK",
    "NOK",
    "DKK",
    "BRL",
    "MXN",
    "SGD",
    "HKD",
    "NZD",
    "ZAR",
    "TRY",
    "RUB",
}


@dataclass(frozen=True)
class UserConstraints:
    years: Set[str]
    billing_category: Optional[str]
    billing_type: Optional[str]
    currency_code: Optional[str]          # first code (backwards compat)
    currency_codes: Tuple[str, ...]       # all codes (multi-currency support)
    wants_count: bool
    wants_sum: bool
    wants_negative_lines: bool


def _extract_years(question: str) -> Set[str]:
    return set(re.findall(r"\b((?:19|20)\d{2})\b", question or ""))


def _extract_currency_codes(question: str) -> List[str]:
    """Return ALL ISO-4217 codes mentioned — supports 'show me CAD and USD sales'."""
    q = (question or "").upper()
    found: List[str] = []
    for code in sorted(_COMMON_CURRENCY_CODES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(code)}\b", q):
            found.append(code)
    if not found:
        if "€" in question:
            found.append("EUR")
        elif "£" in question:
            found.append("GBP")
        elif "$" in question and "USD" in q:
            found.append("USD")
    return found


def _extract_currency_code(question: str) -> Optional[str]:
    """Return the first currency code found (backwards compat)."""
    codes = _extract_currency_codes(question)
    return codes[0] if codes else None


def _extract_billing_category(question: str) -> Optional[str]:
    q = question or ""
    # Prefer explicit "billing category X"
    m = re.search(
        r"(?:billing\s*category|fktyp)\s*[:=\-]?\s*[\"']?([A-Za-z0-9]{1,10})[\"']?",
        q,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # Fallback: "category X" only when "billing" is mentioned somewhere.
    if re.search(r"\bbilling\b", q, flags=re.IGNORECASE) and re.search(r"\bcategory\b", q, flags=re.IGNORECASE):
        m2 = re.search(r"\bcategory\s*[\"']?([A-Za-z0-9]{1,10})[\"']?", q, flags=re.IGNORECASE)
        if m2:
            return m2.group(1).strip()
    return None


def _extract_billing_type(question: str) -> Optional[str]:
    q = question or ""
    m = re.search(
        r"(?:billing\s*type|fkart)\s*[:=\-]?\s*[\"']?([A-Za-z0-9]{1,10})[\"']?",
        q,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def _extract_metric_intent(question: str) -> Tuple[bool, bool]:
    q = (question or "").lower()
    wants_count = bool(
        re.search(r"\b(count|how many|number of)\b", q)
        or "invoice count" in q
        or "number of invoices" in q
    )
    # Only require SUM() when the question EXPLICITLY asks for aggregates/totals.
    # Bare "show me sales" or "show me invoice amounts" could be row-level queries —
    # the constraint validator should NOT require SUM() in those cases.
    wants_sum = bool(
        re.search(r"\b(total|sum|aggregate|cumulative|overall)\b", q)
        or "total sales" in q
        or "total revenue" in q
        or "total amount" in q
        or "sum of" in q
        or re.search(r"\b(top|bottom|highest|lowest|largest|smallest)\s+\d+", q)  # ranking queries always aggregate
        or re.search(r"\bby\s+(customer|product|country|material|vendor|region|year|month|quarter)\b", q)
        # Explicit revenue/sales WITH a year = aggregate intent
        or (re.search(r"\b(revenue|sales)\b", q) and re.search(r"\b(19|20)\d{2}\b", q)
            and re.search(r"\b(total|sum|how much|what is|what was)\b", q))
    )
    return wants_count, wants_sum


def extract_user_constraints(question: str) -> UserConstraints:
    wants_count, wants_sum = _extract_metric_intent(question)

    q = (question or "").lower()
    wants_negative_lines = bool(
        re.search(r"\bnegative\b", q)
        or "credit memo" in q
        or "credit memos" in q
    )

    # Negative / credit memo requests are line-item oriented in this schema.
    # Treat them as a line-item intent so we don't incorrectly require SUM().
    if wants_negative_lines:
        wants_sum = False

    currency_codes_list = _extract_currency_codes(question)
    return UserConstraints(
        years=_extract_years(question),
        billing_category=_extract_billing_category(question),
        billing_type=_extract_billing_type(question),
        currency_code=currency_codes_list[0] if currency_codes_list else None,
        currency_codes=tuple(currency_codes_list),
        wants_count=wants_count,
        wants_sum=wants_sum,
        wants_negative_lines=wants_negative_lines,
    )


def should_try_deterministic_sql_for_quality(question: str) -> bool:
    """
    Deterministic resolver is most valuable when the question contains explicit filters
    that are easy to express and must never be dropped:
      - explicit year(s)
      - billing category/type predicates
      - count-vs-sum semantics
      - explicit currency code (USD, EUR, etc.)
    """
    c = extract_user_constraints(question)
    # Deterministic resolver covers:
    #   - year + billing category/type (count and totals)
    #   - year + totals-like questions where we can express FKDAT-based year logic
    return bool(c.years) and (bool(c.billing_category or c.billing_type) or c.wants_sum or bool(c.currency_code))


def should_skip_sql_memory_reuse(question: str) -> bool:
    """
    We skip ai_query_memory reuse when the question contains explicit constraints,
    because similarity-based reuse can still ignore/override those filters.
    """
    c = extract_user_constraints(question)
    return bool(c.years) or bool(c.billing_category or c.billing_type) or bool(c.currency_code) or c.wants_count


def _extract_fkdat_years_from_sql(sql: str) -> Set[str]:
    s = sql or ""
    years: Set[str] = set()

    # Pattern: SUBSTRING(TRIM(r."fkdat"),1,4) = '1999'
    for m in re.finditer(
        r"SUBSTRING\s*\(\s*TRIM\s*\(\s*[^)]*fkdat[^)]*\)\s*,\s*1\s*,\s*4\s*\)\s*=\s*'((?:19|20)\d{2})'",
        s,
        flags=re.IGNORECASE,
    ):
        years.add(m.group(1))

    # Pattern: r."fkdat" BETWEEN '19990101' AND '19991231'
    for m in re.finditer(
        r"fkdat\s+BETWEEN\s*'((?:19|20)\d{2})\d{4}'\s+AND\s*'((?:19|20)\d{2})\d{4}'",
        s,
        flags=re.IGNORECASE,
    ):
        years.add(m.group(1))
        years.add(m.group(2))

    # Best-effort fallback: if fkdat appears near a 4-digit year literal, accept.
    if not years:
        for y in re.findall(r"\b((?:19|20)\d{2})\b", s):
            if re.search(rf"fkdat[^;]{{0,200}}{re.escape(y)}", s, flags=re.IGNORECASE):
                years.add(y)

    return years


def _sql_has_fktyp_value(sql: str, billing_category: str) -> bool:
    s = sql or ""
    v = re.escape(billing_category)

    # equality: ... fktyp = 'X'
    if re.search(rf"fktyp\"\s*=\s*'[^{chr(0)}]*?{v}'", s, flags=re.IGNORECASE):
        return True
    if re.search(rf"fktyp\s*=\s*'{v}'", s, flags=re.IGNORECASE):
        return True

    # IN list: fktyp IN ('A','B')
    m = re.search(r"fktyp\"\s*IN\s*\((?P<list>[^)]+)\)", s, flags=re.IGNORECASE)
    if m and re.search(rf"'{billing_category}'", m.group("list")):
        return True
    m2 = re.search(r"fktyp\s*IN\s*\((?P<list>[^)]+)\)", s, flags=re.IGNORECASE)
    if m2 and re.search(rf"'{billing_category}'", m2.group("list")):
        return True

    # Fallback: fktyp + value somewhere near each other
    return bool(re.search(rf"fktyp[^;]{{0,200}}'{billing_category}'", s, flags=re.IGNORECASE))


def _sql_has_fkart_value(sql: str, billing_type: str) -> bool:
    s = sql or ""
    v = re.escape(billing_type)

    if re.search(rf"fkart\"\s*=\s*'{v}'", s, flags=re.IGNORECASE):
        return True
    if re.search(rf"fkart\s*=\s*'{v}'", s, flags=re.IGNORECASE):
        return True

    m = re.search(r"fkart\"\s*IN\s*\((?P<list>[^)]+)\)", s, flags=re.IGNORECASE)
    if m and re.search(rf"'{billing_type}'", m.group("list")):
        return True
    m2 = re.search(r"fkart\s*IN\s*\((?P<list>[^)]+)\)", s, flags=re.IGNORECASE)
    if m2 and re.search(rf"'{billing_type}'", m2.group("list")):
        return True

    return bool(re.search(rf"fkart[^;]{{0,200}}'{billing_type}'", s, flags=re.IGNORECASE))


def _sql_has_count(sql: str) -> bool:
    return bool(re.search(r"\bCOUNT\s*\(", sql or "", flags=re.IGNORECASE))


def _sql_has_sum(sql: str) -> bool:
    return bool(re.search(r"\bSUM\s*\(", sql or "", flags=re.IGNORECASE))


def _sql_has_currency_filter(sql: str, currency_code: str) -> bool:
    """Check that the SQL filters on the given currency (single-code check, backwards compat)."""
    s = sql or ""
    code = currency_code or ""
    # Matches equality:  waerk = 'CAD'
    if re.search(rf"waerk[^;]{{0,200}}'{re.escape(code)}'", s, flags=re.IGNORECASE):
        return True
    # Matches IN list:   waerk IN ('CAD','USD')
    if re.search(rf"waerk[^;]{{0,200}}IN\s*\([^)]*'{re.escape(code)}'", s, flags=re.IGNORECASE):
        return True
    return False


def _sql_has_all_currency_filters(sql: str, codes: Tuple[str, ...]) -> bool:
    """For multi-currency queries, verify the SQL references every requested code."""
    if not codes:
        return True
    if len(codes) == 1:
        return _sql_has_currency_filter(sql, codes[0])
    s = sql or ""
    # Accept either: an IN list containing all codes, or individual equality filters
    all_present = all(
        re.search(rf"waerk[^;]{{0,300}}'{re.escape(c)}'", s, flags=re.IGNORECASE)
        for c in codes
    )
    return all_present


def validate_sql_against_user_constraints(sql: str, question: str) -> Tuple[bool, List[str]]:
    """
    Returns (ok, reasons). If ok=False, reasons contain short human-readable strings.
    """
    constraints = extract_user_constraints(question)
    sql_s = sql or ""
    reasons: List[str] = []

    if constraints.years:
        fkdat_years = _extract_fkdat_years_from_sql(sql_s)
        missing = constraints.years - fkdat_years
        if not fkdat_years:
            reasons.append("Missing FKDAT-based year filter in SQL.")
        elif missing:
            reasons.append(f"SQL year filter missing: {', '.join(sorted(missing))}.")

        # Strong sanity: if the question mentions a year, we should not rely on GJAHR.
        # (sanitizers usually rewrite, but keep the guard)
        if re.search(r"\bgjahr\b", sql_s, flags=re.IGNORECASE) and constraints.years:
            # Only warn/fail if we also didn't detect fkdat years.
            if not fkdat_years:
                reasons.append("SQL appears to use GJAHR for year logic.")

    if constraints.billing_category:
        if "fktyp" not in sql_s.lower():
            reasons.append("Missing VBRK.FKTYP predicate for requested billing category.")
        elif not _sql_has_fktyp_value(sql_s, constraints.billing_category):
            reasons.append("SQL FKTYP predicate does not match requested billing category.")

    if constraints.billing_type:
        if "fkart" not in sql_s.lower():
            reasons.append("Missing VBRK.FKART predicate for requested billing type.")
        elif not _sql_has_fkart_value(sql_s, constraints.billing_type):
            reasons.append("SQL FKART predicate does not match requested billing type.")

    if constraints.currency_codes:
        # Multi-currency: accept if ALL requested codes appear in the SQL (equality or IN list).
        # Single-currency: enforce equality/IN match for the one code.
        if not _sql_has_all_currency_filters(sql_s, constraints.currency_codes):
            if len(constraints.currency_codes) == 1:
                reasons.append(f"SQL does not filter WAERK = {constraints.currency_codes[0]}.")
            else:
                missing = [c for c in constraints.currency_codes
                           if not _sql_has_currency_filter(sql_s, c)]
                reasons.append(
                    f"SQL currency filter incomplete — missing: {', '.join(missing)}."
                )

    if constraints.wants_count:
        if not _sql_has_count(sql_s):
            reasons.append("Question asks for a count, but SQL contains no COUNT().")

    if constraints.wants_sum and not constraints.wants_count and not constraints.wants_negative_lines:
        if not _sql_has_sum(sql_s):
            reasons.append("Question asks for totals/revenue, but SQL contains no SUM().")

    if constraints.wants_negative_lines:
        sql_l = sql_s.lower()
        if "from vbrp" not in sql_l and "vbrp" not in sql_l:
            reasons.append("Question asks for negative/credit memo line items, but SQL does not appear to use VBRP.")
        # If the user asked for ONLY negative amounts, enforce `netwr < 0`.
        # For mixed intents like "negative and lowest/highest", we may only be ordering
        # by line amount (negatives first) rather than filtering them.
        q_l = (question or "").lower()
        mixed_order_intent = bool(
            re.search(r"\b(lowest|highest|top|bottom|best|worst|smallest|minimum|maximum)\b", q_l)
        )
        if not mixed_order_intent:
            # Best-effort: require netwr cast comparison to < 0
            if not (
                re.search(r"netwr[^;]{0,200}<\s*0", sql_s, flags=re.IGNORECASE)
                or re.search(r"netwr[^;]{0,200}::numeric[^;]{0,200}<\s*0", sql_s, flags=re.IGNORECASE)
                or re.search(r"CAST\s*\([^)]{0,200}netwr[^;]{0,200}<\s*0", sql_s, flags=re.IGNORECASE)
            ):
                reasons.append("SQL does not appear to filter negative line items (expected netwr < 0).")

    return (len(reasons) == 0), reasons


def build_charts_blocked_reason(reasons: List[str]) -> Optional[str]:
    if not reasons:
        return None
    # Keep it short: frontend will show it verbatim.
    return " | ".join(reasons[:4])

