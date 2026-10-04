"""
Deterministic SAP purchasing fast path for /dashboard/ai-analysis/chat.

Avoids multi-minute LangGraph loops for common PO questions (open POs by vendor, etc.).
Uses EKKO/EKPO/LFA1 with TEXT-safe casts — no wemng (not in this schema replica).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("zodiac-api.sap_purchasing_fast_path")


def _is_open_po_by_vendor_question(question: str) -> bool:
    q = (question or "").lower()
    if re.search(r"open\s+purchase\s+orders?\s+by\s+vendor", q):
        return True
    has_po = any(
        p in q
        for p in ("purchase order", "purchase orders", " po ", " po?", " pos ", "procurement order")
    )
    has_open = any(p in q for p in ("open", "pending", "outstanding", "not delivered", "not fully delivered"))
    has_vendor = any(p in q for p in ("vendor", "supplier", "lifnr"))
    return has_po and has_open and has_vendor


def build_open_po_by_vendor_sql(limit: int = 50) -> str:
    lim = max(1, min(200, int(limit)))
    return f"""
SELECT
    k."lifnr" AS vendor_id,
    l."name1" AS vendor_name,
    COUNT(DISTINCT k."ebeln") AS open_po_count,
    COUNT(*) AS open_line_count
FROM "EKKO" k
INNER JOIN "EKPO" p ON k."ebeln" = p."ebeln"
LEFT JOIN "LFA1" l ON k."lifnr" = l."lifnr"
WHERE TRIM(COALESCE(p."elikz", '')) = ''
  AND TRIM(COALESCE(p."loekz", '')) = ''
  AND TRIM(COALESCE(k."loekz", '')) = ''
GROUP BY k."lifnr", l."name1"
ORDER BY open_po_count DESC
LIMIT {lim}
""".strip()


def _period_blurb(question: str) -> str:
    years = list(dict.fromkeys(re.findall(r"\b((?:19|20)\d{2})\b", question or "")))
    if years:
        return f"Open PO lines across SAP snapshot (calendar year filter: {', '.join(years)})."
    return "Open PO lines (delivery incomplete, not deleted) grouped by vendor — full SAP snapshot, no recent-date filter."


def try_sap_purchasing_fast_path(
    db: Session,
    question: str,
    *,
    rows_preview_limit: int = 80,
) -> Optional[Dict[str, Any]]:
    """Return a run_planner-shaped payload, or None to fall through."""
    q = (question or "").strip()
    if not q:
        return None

    sql: Optional[str] = None
    query_type = ""

    if _is_open_po_by_vendor_question(q):
        sql = build_open_po_by_vendor_sql()
        query_type = "open_po_by_vendor"

    if not sql:
        return None

    try:
        from .sql_generation_sanitizers import prepare_sql_for_sqlalchemy_text_execution as _prep

        safe_sql = _prep(sql)
    except Exception:
        safe_sql = sql

    rows_raw = db.execute(text(safe_sql)).mappings().all()
    result_rows = [dict(r) for r in rows_raw]
    preview = result_rows[: max(1, min(rows_preview_limit, 500))]
    row_count = len(result_rows)

    if row_count:
        top = result_rows[0]
        vendor_label = top.get("vendor_name") or top.get("vendor_id") or "top vendor"
        reply = (
            f"Found **{row_count}** vendor(s) with open purchase order lines. "
            f"Top vendor: **{vendor_label}** with **{top.get('open_po_count', 0)}** open PO(s)."
        )
    else:
        reply = (
            "No open purchase order lines matched (delivery complete or all POs deleted in this SAP snapshot). "
            "Try removing date filters or ask for **purchase orders by vendor** without the open filter."
        )

    return {
        "reply": reply,
        "action": "new",
        "reason": f"sap_purchasing_{query_type}",
        "schema_tables": ["EKKO", "EKPO", "LFA1"],
        "sql": sql,
        "rows_preview": preview,
        "charts": [],
        "time_scope": "current",
        "date_range": {},
        "period_info": _period_blurb(q),
        "errors": [],
        "warnings": [],
        "confidence": "high" if row_count else "medium",
        "confidence_note": "Deterministic SAP purchasing SQL (skipped LangGraph).",
        "node_log": [
            {
                "service": "sap_purchasing_fast_path",
                "kind": "deterministic",
                "message": f"Routed to SAP purchasing resolver ({query_type}).",
            }
        ],
        "sql_path_reason": f"sap_purchasing_{query_type}",
    }
