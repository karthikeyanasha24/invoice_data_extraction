"""
Build Generative AI context from the SAP database.
Used only when AI_CONTEXT_SOURCE=sap and SAP_DATABASE_URL is set.
Queries are configurable via environment variables so you can adapt to your SAP schema.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("zodiac-api.sap_ai_context")

# Optional: schema prefix for SAP (e.g. empty, or "SAPHANADB." for HANA)
SAP_SCHEMA_PREFIX = os.getenv("SAP_AI_SCHEMA_PREFIX", "").strip()
if SAP_SCHEMA_PREFIX and not SAP_SCHEMA_PREFIX.endswith("."):
    SAP_SCHEMA_PREFIX = SAP_SCHEMA_PREFIX + "."


def _days_ago(days: int) -> str:
    """Return date string for SAP (YYYYMMDD)."""
    d = datetime.utcnow() - timedelta(days=days)
    return d.strftime("%Y%m%d")


def _run_safe(conn, sql: str, params: dict | None = None):
    """Execute SQL and return list of dict-like rows, or empty list on error."""
    if not sql or not sql.strip():
        return []
    try:
        result = conn.execute(text(sql), params or {})
        rows = result.fetchall()
        keys = result.keys()
        return [dict(zip(keys, row)) for row in rows]
    except Exception as e:
        logger.warning("SAP AI context query failed: %s", e)
        return []


def build_ai_context_from_sap(context_keys: list, sap_db: Session, days: int = 30) -> str:
    """
    Build the same shape of context string as _build_ai_analysis_context but from SAP DB.
    context_keys: stats, failed_summary, top_customers, inbound_summary, business_summary, process_flow.
    """
    if not sap_db or not context_keys:
        return ""

    parts = []
    date_from = _days_ago(days)

    # Optional custom SQL overrides (must return expected column names)
    q_top_customers = os.getenv("SAP_AI_QUERY_TOP_CUSTOMERS", "").strip()
    q_stats = os.getenv("SAP_AI_QUERY_STATS", "").strip()
    q_inbound = os.getenv("SAP_AI_QUERY_INBOUND", "").strip()
    q_revenue = os.getenv("SAP_AI_QUERY_REVENUE", "").strip()

    if "stats" in context_keys:
        if q_stats:
            rows = _run_safe(sap_db, q_stats, {"date_from": date_from, "days": days})
            if rows:
                r = rows[0]
                parts.append(
                    f"Dashboard statistics (last {days} days, from SAP). "
                    f"Outbound: {r.get('documents_received', 0)} documents received; "
                    f"validated: {r.get('validated_success', 0)} success, {r.get('validated_failed', 0)} failed; "
                    f"converted: {r.get('converted_success', 0)} success, {r.get('converted_failed', 0)} failed, {r.get('converted_pending', 0)} pending. "
                    f"Inbound: {r.get('inbound_total', 0)} merged ({r.get('inbound_sent', 0)} sent to SAP, {r.get('inbound_pending', 0)} pending)."
                )
            else:
                parts.append("Dashboard statistics (SAP): query returned no data. Check SAP_AI_QUERY_STATS.")
        else:
            # Default: count sales docs (VBAK). Override with SAP_AI_QUERY_STATS for your schema.
            default_stats = f"""
            SELECT COUNT(*) AS documents_received
            FROM {SAP_SCHEMA_PREFIX}VBAK
            WHERE ERDAT >= :date_from
            """
            rows = _run_safe(sap_db, default_stats, {"date_from": date_from})
            if rows:
                r = rows[0]
                total = int(r.get("documents_received", 0))
                parts.append(
                    f"Dashboard statistics (last {days} days, from SAP). "
                    f"Sales documents (VBAK): {total} in period. "
                    f"Set SAP_AI_QUERY_STATS for full stats (validated, converted, inbound)."
                )
            else:
                parts.append("Dashboard statistics (SAP): no data. Set SAP_AI_QUERY_STATS for your schema.")

    if "failed_summary" in context_keys:
        q_failed = os.getenv("SAP_AI_QUERY_FAILED", "").strip()
        if q_failed:
            rows = _run_safe(sap_db, q_failed, {"date_from": date_from})
            count = rows[0].get("failed_count", 0) if rows else 0
            parts.append(f"Failed invoices (last {days} days, from SAP): {count} failed.")
        else:
            parts.append("Failed invoices (SAP): set SAP_AI_QUERY_FAILED to report failures.")

    if "top_customers" in context_keys:
        if q_top_customers:
            rows = _run_safe(sap_db, q_top_customers, {"date_from": date_from, "days": days})
        else:
            # Default: VBAK + KNA1. Expect columns: customer_id, customer_name, currency, invoice_count
            default_top = f"""
            SELECT
                V.KUNNR AS customer_id,
                COALESCE(K.NAME1, V.KUNNR) AS customer_name,
                COALESCE(V.WAERK, '—') AS currency,
                COUNT(*) AS invoice_count
            FROM {SAP_SCHEMA_PREFIX}VBAK V
            LEFT JOIN {SAP_SCHEMA_PREFIX}KNA1 K ON K.KUNNR = V.KUNNR
            WHERE V.ERDAT >= :date_from
            GROUP BY V.KUNNR, K.NAME1, V.WAERK
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """
            rows = _run_safe(sap_db, default_top, {"date_from": date_from})
        if rows:
            top = [
                {
                    "customer_id": str(r.get("customer_id", "")),
                    "customer_name": str(r.get("customer_name", "")),
                    "currency": str(r.get("currency", "—")),
                    "invoice_count": int(r.get("invoice_count", 0)),
                }
                for r in rows
            ]
            parts.append("Top customers (from SAP): " + json.dumps(top))
        else:
            parts.append("Top customers (SAP): no data. Set SAP_AI_QUERY_TOP_CUSTOMERS for your schema.")

    if "inbound_summary" in context_keys:
        if q_inbound:
            rows = _run_safe(sap_db, q_inbound, {"date_from": date_from})
            if rows:
                r = rows[0]
                parts.append(
                    f"Inbound (SAP): {r.get('total_documents', 0)} documents; "
                    f"{r.get('merges_total', 0)} merges ({r.get('merges_sent', 0)} sent, {r.get('merges_pending', 0)} pending). "
                    f"Top suppliers: " + json.dumps(rows[:10] if len(rows) > 10 else rows)
                )
            else:
                parts.append("Inbound (SAP): no data from SAP_AI_QUERY_INBOUND.")
        else:
            parts.append("Inbound (SAP): set SAP_AI_QUERY_INBOUND for inbound/supplier data.")

    if "business_summary" in context_keys:
        if q_revenue:
            rows = _run_safe(sap_db, q_revenue, {"date_from": date_from})
            if rows:
                revenue_list = [
                    {
                        "customer_id": str(r.get("customer_id", "")),
                        "customer_name": str(r.get("customer_name", "")),
                        "invoice_count": int(r.get("invoice_count", 0)),
                        "total_revenue": float(r.get("total_revenue", 0)),
                    }
                    for r in rows[:10]
                ]
                parts.append(f"Business (revenue from SAP): " + json.dumps(revenue_list))
            else:
                parts.append("Business (SAP): no revenue data. Check SAP_AI_QUERY_REVENUE.")
        else:
            # Optional: default from VBAK net value
            default_rev = f"""
            SELECT
                V.KUNNR AS customer_id,
                COALESCE(K.NAME1, V.KUNNR) AS customer_name,
                COUNT(*) AS invoice_count,
                COALESCE(SUM(V.NETWR), 0) AS total_revenue
            FROM {SAP_SCHEMA_PREFIX}VBAK V
            LEFT JOIN {SAP_SCHEMA_PREFIX}KNA1 K ON K.KUNNR = V.KUNNR
            WHERE V.ERDAT >= :date_from
            GROUP BY V.KUNNR, K.NAME1
            ORDER BY SUM(V.NETWR) DESC
            LIMIT 10
            """
            rows = _run_safe(sap_db, default_rev, {"date_from": date_from})
            if rows:
                revenue_list = [
                    {
                        "customer_id": str(r.get("customer_id", "")),
                        "customer_name": str(r.get("customer_name", "")),
                        "invoice_count": int(r.get("invoice_count", 0)),
                        "total_revenue": float(r.get("total_revenue", 0)),
                    }
                    for r in rows
                ]
                parts.append("Business (revenue from SAP): " + json.dumps(revenue_list))
            else:
                parts.append("Business (SAP): set SAP_AI_QUERY_REVENUE for revenue by customer.")

    if "process_flow" in context_keys:
        parts.append(
            "Process flow (SAP): Outbound = Sales order (VBAK) -> Delivery (LIKP) -> Billing. "
            "Inbound = Documents -> Merge -> Send to SAP. Set SAP_AI_QUERY_* for current counts."
        )

    return "\n".join(parts) if parts else ""
