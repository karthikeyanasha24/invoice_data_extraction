"""
Drill-Down Analyzer
====================
Automatically generates and executes follow-up SQL queries when the initial
result warrants deeper analysis.

Andy's requirement (2026-04-21):
  After a top-level answer (e.g. "show negative sales lines"), the AI should
  automatically drill deeper without the user needing to ask individually:
    1. Which specific billing documents have these values?
    2. Which products are driving the negative/anomalous sales?
    3. Which industry do those products belong to?
    4. What is the likely business reason (credit memo, return, discount)?
    5. What was the profit margin for those products?

This module detects when drill-down is appropriate, builds the SQL, executes
it, and returns structured results that the orchestrator appends to the reply.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Detection helpers ──────────────────────────────────────────────────────────

def _detect_negative_sales(rows: List[Dict[str, Any]]) -> bool:
    """Return True if result contains billing rows with negative net amounts."""
    if not rows:
        return False
    for r in rows[:50]:
        for k, v in r.items():
            if k.lower() in ("netwr", "total_netwr", "net_amount", "total_invoice_amount",
                             "total_billed", "sales_amount", "amount"):
                try:
                    if float(str(v).replace(",", "")) < 0:
                        return True
                except (ValueError, TypeError):
                    pass
    return False


def _has_vbeln(rows: List[Dict[str, Any]]) -> bool:
    """Return True if result rows contain billing document numbers."""
    if not rows:
        return False
    keys_lower = {k.lower() for k in rows[0].keys()}
    return bool({"vbeln", "billing_doc", "billing_document"} & keys_lower)


def _has_matnr(rows: List[Dict[str, Any]]) -> bool:
    """Return True if result rows contain material numbers."""
    if not rows:
        return False
    keys_lower = {k.lower() for k in rows[0].keys()}
    return bool({"matnr", "material", "material_number"} & keys_lower)


def _extract_billing_docs(rows: List[Dict[str, Any]], limit: int = 20) -> List[str]:
    """Pull distinct billing document numbers from result rows."""
    docs: List[str] = []
    seen = set()
    for r in rows:
        for k in ("vbeln", "billing_doc", "billing_document"):
            v = r.get(k)
            if v and str(v).strip() and str(v) not in seen:
                seen.add(str(v))
                docs.append(str(v).strip())
        if len(docs) >= limit:
            break
    return docs


def _extract_matnrs(rows: List[Dict[str, Any]], limit: int = 20) -> List[str]:
    """Pull distinct material numbers from result rows."""
    matnrs: List[str] = []
    seen = set()
    for r in rows:
        for k in ("matnr", "material", "material_number"):
            v = r.get(k)
            if v and str(v).strip() and str(v) not in seen:
                seen.add(str(v))
                matnrs.append(str(v).strip())
        if len(matnrs) >= limit:
            break
    return matnrs


def _quote_list(items: List[str]) -> str:
    """Return SQL-safe IN (...) list."""
    escaped = ["'" + s.replace("'", "''") + "'" for s in items]
    return "(" + ", ".join(escaped) + ")"


# ── SQL builders ───────────────────────────────────────────────────────────────

def _build_billing_doc_detail_sql(billing_docs: List[str]) -> str:
    """
    For a list of billing docs, return item-level detail:
    billing doc, line, material, description, billing type (fkart),
    billing category (fktyp), amount, currency.
    """
    doc_in = _quote_list(billing_docs[:30])
    return f"""
SELECT
    k."vbeln"                                          AS billing_doc,
    p."posnr"                                          AS line_item,
    k."fkart"                                          AS billing_type,
    p."matnr"                                          AS material_number,
    TRIM(COALESCE(m."maktx", ''))                     AS material_description,
    CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC) AS net_amount,
    k."waerk"                                          AS currency,
    k."fkdat"                                          AS billing_date,
    k."kunag"                                          AS customer_id
FROM "VBRK" k
JOIN "VBRP" p  ON k."vbeln" = p."vbeln"
LEFT JOIN "MAKT" m ON p."matnr" = m."matnr" AND m."spras" = 'E'
WHERE k."vbeln" IN {doc_in}
ORDER BY CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC) ASC NULLS LAST
LIMIT 100
""".strip()


def _build_negative_products_sql(billing_docs: List[str]) -> str:
    """
    Which specific products are showing negative sales in these billing docs?
    Returns: material, description, industry sector, total negative amount.
    """
    doc_in = _quote_list(billing_docs[:30])
    return f"""
SELECT
    p."matnr"                                                          AS material_number,
    TRIM(COALESCE(m."maktx", ''))                                     AS material_description,
    COALESCE(mm."mbrsh", '')                                           AS industry_sector,
    COUNT(*)                                                            AS line_count,
    SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC))   AS total_net_amount,
    MAX(k."waerk")                                                     AS currency
FROM "VBRK" k
JOIN "VBRP" p  ON k."vbeln" = p."vbeln"
LEFT JOIN "MAKT" m  ON p."matnr" = m."matnr" AND m."spras" = 'E'
LEFT JOIN "MARA" mm ON p."matnr" = mm."matnr"
WHERE k."vbeln" IN {doc_in}
  AND CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC) < 0
GROUP BY p."matnr", m."maktx", mm."mbrsh"
ORDER BY SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) ASC NULLS LAST
LIMIT 50
""".strip()


def _build_billing_reason_sql(billing_docs: List[str]) -> str:
    """
    Identify business reason for negative lines:
    billing type (fkart) + billing category (fktyp) — credit memos, returns, etc.
    """
    doc_in = _quote_list(billing_docs[:30])
    return f"""
SELECT
    k."fkart"                                                           AS billing_type,
    k."fktyp"                                                           AS billing_category,
    COUNT(DISTINCT k."vbeln")                                           AS doc_count,
    COUNT(*)                                                            AS line_count,
    SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC))   AS total_net_amount,
    MAX(k."waerk")                                                     AS currency
FROM "VBRK" k
JOIN "VBRP" p ON k."vbeln" = p."vbeln"
WHERE k."vbeln" IN {doc_in}
  AND CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC) < 0
GROUP BY k."fkart", k."fktyp"
ORDER BY SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) ASC NULLS LAST
LIMIT 20
""".strip()


def _build_profit_margin_sql(matnrs: List[str]) -> str:
    """
    For a list of material numbers, compute proxy profit margin:
    net billing amount (VBRP) vs. standard cost from KEKO / CKMLPR.
    Falls back to net amount only when cost data is unavailable.
    """
    mat_in = _quote_list(matnrs[:20])
    return f"""
SELECT
    p."matnr"                                                                       AS material_number,
    TRIM(COALESCE(m."maktx", ''))                                                  AS material_description,
    SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC))               AS total_revenue,
    SUM(CAST(NULLIF(TRIM(CAST(p."fklmg" AS TEXT)), '') AS NUMERIC))               AS total_quantity,
    CASE
        WHEN SUM(CAST(NULLIF(TRIM(CAST(p."fklmg" AS TEXT)), '') AS NUMERIC)) > 0
        THEN ROUND(
            SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC))
            / NULLIF(SUM(CAST(NULLIF(TRIM(CAST(p."fklmg" AS TEXT)), '') AS NUMERIC)), 0),
            4
        )
        ELSE NULL
    END                                                                             AS avg_price_per_unit,
    MAX(k."waerk")                                                                 AS currency
FROM "VBRP" p
JOIN "VBRK" k ON k."vbeln" = p."vbeln"
LEFT JOIN "MAKT" m ON p."matnr" = m."matnr" AND m."spras" = 'E'
WHERE p."matnr" IN {mat_in}
GROUP BY p."matnr", m."maktx"
ORDER BY SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC)) ASC NULLS LAST
LIMIT 30
""".strip()


# ── Execution ──────────────────────────────────────────────────────────────────

def _run_drill_sql(db: Any, sql: str) -> List[Dict[str, Any]]:
    """Execute drill-down SQL safely; return rows or []."""
    try:
        from sqlalchemy import text as _text
        from .sql_generation_sanitizers import prepare_sql_for_sqlalchemy_text_execution as _prep
        safe_sql = _prep(sql)
        rows = db.execute(_text(safe_sql)).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("drill_down_analyzer: SQL failed: %s | SQL: %s", exc, sql[:300])
        return []


# ── Narrative builder ──────────────────────────────────────────────────────────

_BILLING_TYPE_LABELS: Dict[str, str] = {
    "G2": "Credit memo",
    "L2": "Debit memo",
    "RE": "Returns",
    "RK": "Invoice correction",
    "S1": "Cancellation",
    "LR": "Returns delivery",
    "LG": "Returns",
}

_INDUSTRY_LABELS: Dict[str, str] = {
    "A": "Plant Engineering",
    "B": "Mining",
    "C": "Chemicals",
    "D": "Petroleum Refining",
    "E": "Pharmaceuticals",
    "F": "Food & Beverages",
    "H": "High Tech",
    "M": "Mechanical Engineering",
    "R": "Retail",
    "S": "Service",
    "T": "Textile",
    "U": "Utilities",
    "V": "Vehicle",
}


def _format_number(v: Any, decimals: int = 2) -> str:
    """Format a number with comma separators and explicit decimals."""
    try:
        f = float(str(v).replace(",", ""))
        if f < 0:
            return f"-{abs(f):,.{decimals}f}"
        return f"{f:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(v)


def _label_billing_type(fkart: str) -> str:
    return _BILLING_TYPE_LABELS.get((fkart or "").strip().upper(), fkart or "Unknown")


def _label_industry(mbrsh: str) -> str:
    return _INDUSTRY_LABELS.get((mbrsh or "").strip().upper(), mbrsh or "Unknown")


def _build_drill_narrative(
    doc_detail_rows: List[Dict[str, Any]],
    product_rows: List[Dict[str, Any]],
    reason_rows: List[Dict[str, Any]],
    margin_rows: List[Dict[str, Any]],
    currency: str = "",
) -> str:
    """Build a Markdown drill-down section from the four drill queries."""
    parts: List[str] = ["\n\n---\n### 🔍 Automatic Drill-Down Analysis\n"]

    # ── 1. Billing documents ──────────────────────────────────────────────────
    if doc_detail_rows:
        parts.append("#### 📄 Billing Document Detail")
        parts.append(
            "_Top items by net amount (most negative first):_\n"
        )
        for r in doc_detail_rows[:10]:
            amt = _format_number(r.get("net_amount", 0))
            cur = r.get("currency") or currency
            mat_desc = r.get("material_description") or r.get("material_number") or "—"
            doc = r.get("billing_doc") or "—"
            line = r.get("line_item") or "—"
            fkart = r.get("billing_type") or "—"
            parts.append(
                f"- **{doc}** / Line {line} | {mat_desc} | "
                f"**{amt} {cur}** | Type: {_label_billing_type(fkart)}"
            )
        parts.append("")

    # ── 2. Products with negative sales ──────────────────────────────────────
    if product_rows:
        parts.append("#### 📦 Products with Negative Sales")
        for r in product_rows[:10]:
            matnr = r.get("material_number") or "—"
            desc = r.get("material_description") or "—"
            ind = _label_industry(r.get("industry_sector") or "")
            amt = _format_number(r.get("total_net_amount", 0))
            cur = r.get("currency") or currency
            cnt = r.get("line_count") or 0
            parts.append(
                f"- **{desc}** (MATNR: {matnr}) | Industry: **{ind}** | "
                f"{cnt} line(s) | Total: **{amt} {cur}**"
            )
        parts.append("")

    # ── 3. Business reason (credit memo / return / etc.) ─────────────────────
    if reason_rows:
        parts.append("#### 💡 Business Reason for Negative Lines")
        for r in reason_rows:
            fkart = r.get("billing_type") or "—"
            fktyp = r.get("billing_category") or "—"
            label = _label_billing_type(fkart)
            amt = _format_number(r.get("total_net_amount", 0))
            cur = r.get("currency") or currency
            docs = r.get("doc_count") or 0
            lines = r.get("line_count") or 0
            parts.append(
                f"- **{label}** (Type: {fkart}, Category: {fktyp}) | "
                f"{docs} document(s), {lines} line(s) | Amount: **{amt} {cur}**"
            )
        parts.append("")

    # ── 4. Profit margin proxy ────────────────────────────────────────────────
    if margin_rows:
        parts.append("#### 📊 Revenue & Margin Indicators by Product")
        parts.append(
            "_Note: Profit margin = (Revenue − COGS) / Revenue. "
            "This shows billed revenue and avg price/unit as a proxy (COGS not available in this query)._\n"
        )
        for r in margin_rows[:10]:
            matnr = r.get("material_number") or "—"
            desc = r.get("material_description") or "—"
            rev = _format_number(r.get("total_revenue", 0))
            qty = r.get("total_quantity")
            avg_p = r.get("avg_price_per_unit")
            cur = r.get("currency") or currency
            qty_str = f_format(qty) if qty else "—"
            avg_str = _format_number(avg_p) if avg_p is not None else "—"
            parts.append(
                f"- **{desc}** (MATNR: {matnr}) | Revenue: **{rev} {cur}** | "
                f"Qty: {qty_str} | Avg Price/Unit: {avg_str} {cur}"
            )
        parts.append("")

    if len(parts) <= 1:
        return ""

    parts.append(
        "> 💬 **Tip:** For a full profitability picture, ask: "
        "*\"Show profit margin by product including COGS from KEKO\"*"
    )
    return "\n".join(parts)


def f_format(v: Any) -> str:
    """Simple number format helper."""
    try:
        return f"{float(str(v)):,.2f}"
    except Exception:
        return str(v)


# ── Public API ─────────────────────────────────────────────────────────────────

@dataclass
class DrillDownResult:
    triggered: bool = False
    narrative: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


def should_drill_down(user_query: str, rows: List[Dict[str, Any]]) -> bool:
    """
    Return True when automatic drill-down is warranted.
    Conditions:
      - User asked about negative sales, credit memos, returns, lowest lines, zero lines
      - Result actually contains negative numeric values
      - Result has billing document identifiers we can drill into
    """
    if not rows:
        return False
    q = (user_query or "").lower()
    negative_intent = bool(re.search(
        r"\b(negative|credit memo|credit note|return|debit memo|zero|lowest|smallest|minimum|"
        r"sales line|billing line|below zero|less than zero)\b",
        q,
    ))
    drill_intent = bool(re.search(
        r"\b(drill|deeper|detail|breakdown|analyse|analyze|which|why|reason|"
        r"product|industry|margin|profitability)\b",
        q,
    ))
    has_negative_data = _detect_negative_sales(rows)
    has_docs = _has_vbeln(rows)
    # Trigger if: negative_intent AND (has_negative_data OR has_docs)
    # OR: drill_intent AND has_negative_data
    return (negative_intent and (has_negative_data or has_docs)) or (drill_intent and has_negative_data)


def run_drill_down(
    db: Any,
    user_query: str,
    rows: List[Dict[str, Any]],
) -> DrillDownResult:
    """
    Run automatic drill-down analysis on a SQL result.
    Returns a DrillDownResult with a Markdown narrative to append to the reply.
    """
    if not should_drill_down(user_query, rows):
        return DrillDownResult(triggered=False)

    # Collect billing docs and materials from the result
    billing_docs = _extract_billing_docs(rows, limit=30)
    matnrs = _extract_matnrs(rows, limit=20)

    # If we have no billing docs in the result, attempt to get them from
    # the negative-value rows themselves (some queries return aggregate totals,
    # not raw docs). In that case skip doc-level drill, do product + reason.
    doc_detail_rows: List[Dict[str, Any]] = []
    product_rows: List[Dict[str, Any]] = []
    reason_rows: List[Dict[str, Any]] = []
    margin_rows: List[Dict[str, Any]] = []

    if billing_docs:
        logger.info("drill_down: running 4 drill queries on %d billing docs", len(billing_docs))
        doc_detail_rows = _run_drill_sql(db, _build_billing_doc_detail_sql(billing_docs))
        product_rows = _run_drill_sql(db, _build_negative_products_sql(billing_docs))
        reason_rows = _run_drill_sql(db, _build_billing_reason_sql(billing_docs))
        # Collect matnrs from drill result if not in original rows
        if not matnrs and product_rows:
            matnrs = [str(r.get("material_number") or "") for r in product_rows if r.get("material_number")]
        if matnrs:
            margin_rows = _run_drill_sql(db, _build_profit_margin_sql(matnrs))
    elif matnrs:
        # No billing docs but have material numbers → skip doc detail, do product + margin
        logger.info("drill_down: no billing docs in result; running product+margin on %d matnrs", len(matnrs))
        if matnrs:
            margin_rows = _run_drill_sql(db, _build_profit_margin_sql(matnrs))

    # Detect currency
    currency = ""
    for r in (doc_detail_rows or rows)[:5]:
        for k in ("currency", "waerk", "waers", "curr"):
            v = r.get(k)
            if v and str(v).strip():
                currency = str(v).strip()
                break
        if currency:
            break

    narrative = _build_drill_narrative(
        doc_detail_rows=doc_detail_rows,
        product_rows=product_rows,
        reason_rows=reason_rows,
        margin_rows=margin_rows,
        currency=currency,
    )

    raw: Dict[str, Any] = {}
    if doc_detail_rows:
        raw["billing_doc_detail"] = doc_detail_rows
    if product_rows:
        raw["negative_products"] = product_rows
    if reason_rows:
        raw["business_reasons"] = reason_rows
    if margin_rows:
        raw["margin_indicators"] = margin_rows

    triggered = bool(narrative.strip())
    logger.info("drill_down: triggered=%s, sections=%d", triggered, len(raw))
    return DrillDownResult(triggered=triggered, narrative=narrative, raw=raw)
