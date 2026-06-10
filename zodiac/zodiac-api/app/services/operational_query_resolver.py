"""
Operational DB query resolver for Real-time (current) time_scope questions.

Uses GPT-4 with the Zodiac operational schema to dynamically generate SQL
for questions about Zodiac's own tables (invoice processing, SAT merges, etc.)
that live on the app DB — NOT the SAP read-replica (which only has 1994-2010 data).

This resolver runs BEFORE the intent pipeline so current-period questions
don't hit the SAP historical dataset and return zero rows.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Zodiac Operational Schema — provided to AI for dynamic SQL generation
# ---------------------------------------------------------------------------

ZODIAC_OPERATIONAL_SCHEMA = """
## Zodiac Operational Database Tables (PostgreSQL)

### zodiac_invoice_success_edi
Stores successfully processed EDI invoice documents (outbound/legacy pipeline).
Columns:
- id (INTEGER, primary key)
- tracking_id (UUID)
- user_id (INTEGER, FK to zodiac_users)
- uploaded_at (TIMESTAMPTZ) — when the invoice was uploaded/processed
- deleted_at (TIMESTAMPTZ, nullable) — soft-delete; always filter WHERE deleted_at IS NULL
- xml_validation_pass (BOOLEAN) — did XML structure validation pass?
- xml_convert_message (TEXT, nullable) — XML conversion message/error detail
- edi_convert_pass (BOOLEAN) — did EDI conversion succeed?
- edi_convert_message (TEXT, nullable) — EDI conversion message/error detail
- invoice_number (TEXT, nullable)
- request_type (TEXT) — 'web' or 'api'
- target_file_format (TEXT, nullable)

### zodiac_invoice_failed_edi
Stores invoices that failed EDI/XML processing (outbound/legacy pipeline).
Same columns as zodiac_invoice_success_edi. Key failure columns:
- xml_validation_pass (BOOLEAN) — False = XML validation failed
- edi_convert_pass (BOOLEAN) — False = EDI conversion failed
- xml_convert_message (TEXT) — reason XML failed
- edi_convert_message (TEXT) — reason EDI failed

### v2_invoice_documents
Entry point for all V2 outbound invoices (current pipeline). Tracks all uploaded files.
Columns:
- id (INTEGER, primary key)
- tracking_id (UUID)
- user_id (INTEGER, FK to zodiac_users)
- source (TEXT) — 'manual' or 'sap'
- filename (TEXT)
- validation_status (TEXT) — 'not_validated', 'processing', 'validated'
- uploaded_at (TIMESTAMPTZ)
- deleted_at (TIMESTAMPTZ, nullable) — always filter WHERE deleted_at IS NULL

### v2_validated_invoices
Stores validation results for V2 invoices. JOIN to v2_invoice_documents on document_id = v2_invoice_documents.id.
Columns:
- id (INTEGER, primary key)
- document_id (INTEGER, FK to v2_invoice_documents.id) — one-to-one
- status (TEXT) — 'success' or 'failed'
- invoice_data (JSONB) — extracted fields: invoice_number, issue_date, currency, customer_id, customer_name, supplier_name, total, etc.
- missing_fields (JSONB, nullable) — array of field names that are missing
- validation_errors (JSONB, nullable) — array of {field, message} error objects
- validation_notes (TEXT, nullable)
- validated_at (TIMESTAMPTZ)

OUTBOUND FUNNEL NOTE: To show the processing funnel for V2 invoices:
  - Total received = COUNT(*) from v2_invoice_documents WHERE deleted_at IS NULL
  - Validated = COUNT(*) from v2_validated_invoices WHERE status = 'success'
  - Failed = COUNT(*) from v2_validated_invoices WHERE status = 'failed'
  - Not yet validated = v2_invoice_documents WHERE validation_status = 'not_validated'

### invoice_v2_business_data
Business-level extracted invoice metrics (current app pipeline).
Columns:
- id (INTEGER, primary key)
- user_id (INTEGER)
- customer_id (TEXT, nullable)
- customer_name (TEXT, nullable)
- total_amount (NUMERIC, nullable)
- tax_amount (NUMERIC, nullable)
- currency (TEXT, nullable)
- invoice_date (DATE, nullable)
- created_at (TIMESTAMPTZ)
- updated_at (TIMESTAMPTZ)

### invoice_business_data
Legacy invoice business metrics table.
Columns:
- id (INTEGER, primary key)
- user_id (INTEGER)
- customer_id (TEXT, nullable)
- customer_name (TEXT, nullable)
- total_amount (NUMERIC, nullable)
- tax_amount (NUMERIC, nullable)
- currency (TEXT, nullable)
- created_at (TIMESTAMPTZ)
- updated_at (TIMESTAMPTZ)

### zodiac_customers
Registered customer configurations.
Columns:
- id (INTEGER, primary key)
- customer_id (TEXT, unique) — customer identifier/RFC
- target_format (TEXT) — output format, e.g. 'xml', 'edi'
- tax_value (NUMERIC 10,2)
- tax_percentage (NUMERIC 5,2)
- created_at (DATETIME)

### sat_canonical_merged
Inbound SAT (Mexican tax authority) CFDI documents after merge/dedup processing.
Columns:
- id (UUID, primary key)
- status (TEXT) — 'MERGED' = pending/not sent to SAP; 'SAP_SENT' = sent; 'SAP_CONFIRMED' = confirmed
- vendor_name (TEXT) — supplier/vendor name
- vendor_rfc (TEXT) — supplier RFC (tax ID)
- net_amount (NUMERIC 15,2) — net document amount
- tax_amount (NUMERIC, nullable)
- total_amount (NUMERIC, nullable)
- currency (TEXT)
- created_at (TIMESTAMPTZ) — when the record was created/merged
- updated_at (TIMESTAMPTZ)
- folio (TEXT, nullable) — document folio number
- uuid (TEXT, nullable) — SAT UUID

### sat_documents
Raw CFDI/SAT documents before merge processing.
Columns:
- id (UUID, primary key)
- supplier_rfc (TEXT)
- supplier_name (TEXT)
- doc_type (TEXT) — INVOICE, PAYMENT, CREDIT_NOTE
- status (TEXT) — document processing status
- received_at (TIMESTAMPTZ) — when document arrived in portal (USE THIS for date filters)
- updated_at (TIMESTAMPTZ)
- total (TEXT)
- moneda (TEXT)
- xml_content (TEXT, nullable)

### zodiac_users
Application users (each user is a company using Zodiac).
- id (INTEGER, primary key)
- email (TEXT)
- username (TEXT)
- is_admin (BOOLEAN)
- is_active (BOOLEAN)
- created_at (TIMESTAMPTZ)
"""

# ---------------------------------------------------------------------------
# Keyword-based fast detection (no LLM needed for common patterns)
# ---------------------------------------------------------------------------

def _is_operational_question(question: str) -> bool:
    """
    Quick heuristic check: is this question likely about Zodiac operational data?
    Returns True if the question mentions invoice processing, SAT docs, EDI, or
    other Zodiac-specific operational concepts.
    """
    if not question:
        return False
    q = question.lower()

    operational_signals = (
        # Invoice processing
        "invoice volume", "invoices per month", "invoices by month",
        "invoice trend", "month-over-month", "month over month",
        "invoice processing", "invoice success", "invoice fail",
        "successful invoice", "failed invoice", "xml validation",
        "edi convert", "edi processing",
        # Failed invoice patterns
        "failure reason", "failure reasons", "why did invoice", "why invoices fail",
        "summarize failed", "failed edi", "edi failure", "validation failure",
        "xml fail", "conversion fail", "processing fail",
        # SAT / CFDI
        "inbound sat", "sat document", "sat merge", "cfdi", "sat inbound",
        "canonical merge", "merge pending", "merges pending",
        "sent to sap", "pending vs sent", "merge status",
        # Outbound / funnel patterns
        "outbound funnel", "processing funnel", "invoice funnel",
        "received vs validated", "validated vs converted",
        "received → validated", "validated → converted",
        "how many received", "how many validated", "how many converted",
        "funnel breakdown", "pipeline funnel",
        # Inbound vs outbound comparison (Andy realtime analysis)
        "inbound vs outbound", "inbound versus outbound", "compare inbound",
        "compare with outbound", "sat vs outbound", "inbound and outbound",
        "conversion success rate", "conversion rate", "v2 invoice conversion",
        "edi status", "edi success", "edi failed", "edi submissions",
        "invoice business data", "extracted zodiac",
        # Week-over-week / comparison patterns
        "this week vs last week", "week vs last week", "this week compared",
        "compare this week", "compare week", "week over week",
        "week comparison", "weekly comparison", "weekly vs",
        "this month vs last month", "month comparison",
        # Customer invoice patterns
        "customer invoice", "invoices by customer", "customer with invoice",
        "customers by invoice", "customer invoice count", "top customer",
        "customer activity", "invoices per customer",
        # Volume / trend patterns + operational context
        "invoice count", "document count", "processing rate",
        "volume trend", "how many invoices", "how many documents",
        "top supplier", "top 5 supplier", "suppliers by volume",
        "supplier volume", "vendor volume",
        # Operational keywords
        "zodiac", "inbound document", "inbound merge",
        # Status queries
        "invoice status", "current status", "processing status",
        "pending invoice", "stuck invoice", "backlog invoice",
        # App analytics wording
        "invoice app tables", "invoice app table", "invoice business table",
        "total amount", "tax amount",
    )

    # Also detect "last N months/weeks/days" + invoice/document context
    has_invoice_ctx = any(w in q for w in ("invoice", "document", "cfdi", "sat", "edi", "supplier", "vendor"))
    has_time_window = bool(re.search(r"\blast\s+\d+\s+(months?|weeks?|days?)\b", q))

    if has_invoice_ctx and has_time_window:
        return True

    # Detect "this week" / "last week" + invoice context
    has_week_ctx = bool(re.search(r"\b(this|last)\s+week\b", q))
    if has_invoice_ctx and has_week_ctx:
        return True

    return any(p in q for p in operational_signals)


# ---------------------------------------------------------------------------
# AI-driven SQL generation against Zodiac schema
# ---------------------------------------------------------------------------

def _generate_zodiac_sql_with_ai(
    question: str,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Use GPT-4 to dynamically generate SQL for a question about Zodiac operational data.
    Returns a SQL string or None if the question is not about operational data or AI fails.
    """
    if not api_key:
        try:
            from ..config.config import OPENAI_API_KEY
            api_key = OPENAI_API_KEY
        except Exception:
            pass

    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        prompt = f"""You are an expert PostgreSQL analyst for the Zodiac Invoice Management System.

The user asked: "{question}"

Here is the Zodiac operational database schema:
{ZODIAC_OPERATIONAL_SCHEMA}

IMPORTANT RULES:
1. Only generate SQL if the question is about Zodiac operational data (invoices, SAT documents, suppliers, etc.)
2. If the question is NOT about operational data, respond with exactly: NOT_OPERATIONAL
3. Use PostgreSQL syntax. All table names are lowercase (no quotes needed).
4. For "current" or "recent" data: use NOW() - INTERVAL 'N months/days' for date filtering.
5. For invoice volume trends: combine zodiac_invoice_success_edi and zodiac_invoice_failed_edi with UNION ALL.
6. For SAT merge status: use sat_canonical_merged.status values ('MERGED'=pending, 'SAP_SENT'/'SAP_CONFIRMED'=sent).
7. Always include WHERE deleted_at IS NULL for zodiac_invoice_* tables.
8. Return ONLY a single SELECT statement. No markdown, no explanation, no multiple statements.
9. Keep the query focused and efficient. Use LIMIT 100 if no natural limit applies.
10. Use TO_CHAR(DATE_TRUNC('month', col), 'YYYY-MM') for month grouping.

Generate the SQL now (or respond NOT_OPERATIONAL if not applicable):"""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600,
        )

        raw = (response.choices[0].message.content or "").strip()

        # Check if AI determined this isn't an operational question
        if "NOT_OPERATIONAL" in raw.upper():
            return None

        # Extract SQL from markdown if present
        if "```" in raw:
            m = re.search(r"```(?:sql)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()

        # Validate it's a SELECT statement
        if raw and "SELECT" in raw.upper() and "FROM" in raw.upper():
            # Basic safety check: no destructive statements
            raw_upper = raw.upper()
            if any(kw in raw_upper for kw in ("DROP ", "DELETE ", "UPDATE ", "INSERT ", "TRUNCATE ")):
                logger.warning("operational_resolver: AI generated unsafe SQL, discarding")
                return None
            return raw

    except Exception as ai_err:
        logger.warning("operational_resolver: AI SQL generation failed: %s", ai_err)

    return None


# ---------------------------------------------------------------------------
# Hard-coded fast-path SQL builders (for the two most common patterns)
# These run without an LLM call for speed when intent is clear.
# ---------------------------------------------------------------------------

def _extract_months(question: str, default: int = 12) -> int:
    """Extract 'last N months' window from question, default 12."""
    m = re.search(r"\blast\s+(\d{1,2})\s+months?\b", question.lower())
    return max(1, min(36, int(m.group(1)) if m else default))


def build_invoice_volume_trend_sql(months: int = 12) -> str:
    """
    Month-over-month invoice volume trend combining success + failed EDI tables.
    """
    return f"""
SELECT
    TO_CHAR(DATE_TRUNC('month', COALESCE(uploaded_at, NOW())), 'YYYY-MM') AS month,
    COUNT(CASE WHEN invoice_status = 'success' THEN 1 END) AS successful_invoices,
    COUNT(CASE WHEN invoice_status = 'failed' THEN 1 END) AS failed_invoices,
    COUNT(*) AS total_invoices
FROM (
    SELECT uploaded_at, 'success' AS invoice_status
    FROM zodiac_invoice_success_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{months} months'
      AND deleted_at IS NULL
    UNION ALL
    SELECT uploaded_at, 'failed' AS invoice_status
    FROM zodiac_invoice_failed_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{months} months'
      AND deleted_at IS NULL
) AS combined_invoices
GROUP BY DATE_TRUNC('month', COALESCE(uploaded_at, NOW()))
ORDER BY month ASC
LIMIT 24
""".strip()


def build_failed_invoices_sql(days: int = 30) -> str:
    """
    Summarize failed EDI invoices grouped by top failure reasons.
    Covers both XML validation failures and EDI conversion failures.
    """
    return f"""
WITH xml_failures AS (
    SELECT
        COALESCE(NULLIF(TRIM(xml_convert_message), ''), 'XML validation failed (no detail)') AS failure_reason,
        'XML Validation'::TEXT AS failure_stage,
        uploaded_at
    FROM zodiac_invoice_failed_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{days} days'
      AND deleted_at IS NULL
      AND (xml_validation_pass = FALSE OR xml_validation_pass IS NULL)
),
edi_failures AS (
    SELECT
        COALESCE(NULLIF(TRIM(edi_convert_message), ''), 'EDI conversion failed (no detail)') AS failure_reason,
        'EDI Conversion'::TEXT AS failure_stage,
        uploaded_at
    FROM zodiac_invoice_failed_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{days} days'
      AND deleted_at IS NULL
      AND xml_validation_pass = TRUE
      AND (edi_convert_pass = FALSE OR edi_convert_pass IS NULL)
),
all_failures AS (
    SELECT failure_reason, failure_stage, uploaded_at FROM xml_failures
    UNION ALL
    SELECT failure_reason, failure_stage, uploaded_at FROM edi_failures
),
totals AS (
    SELECT COUNT(*) AS grand_total FROM all_failures
)
SELECT
    f.failure_stage,
    LEFT(f.failure_reason, 120) AS failure_reason,
    COUNT(*) AS invoice_count,
    ROUND(100.0 * COUNT(*) / NULLIF(t.grand_total, 0), 1) AS percentage_of_failures,
    MIN(f.uploaded_at) AS first_seen,
    MAX(f.uploaded_at) AS last_seen
FROM all_failures f, totals t
GROUP BY f.failure_stage, LEFT(f.failure_reason, 120), t.grand_total
ORDER BY invoice_count DESC
LIMIT 25
""".strip()


def build_outbound_funnel_sql() -> str:
    """
    Show the full outbound V2 invoice processing funnel:
    received → validated (success/failed) → not yet processed.
    """
    return """
SELECT
    'Total Received'       AS funnel_stage,
    COUNT(*)               AS invoice_count,
    1                      AS sort_order
FROM v2_invoice_documents
WHERE deleted_at IS NULL

UNION ALL

SELECT
    'Validated (Success)'  AS funnel_stage,
    COUNT(*)               AS invoice_count,
    2                      AS sort_order
FROM v2_validated_invoices
WHERE status = 'success'

UNION ALL

SELECT
    'Failed Validation'    AS funnel_stage,
    COUNT(*)               AS invoice_count,
    3                      AS sort_order
FROM v2_validated_invoices
WHERE status = 'failed'

UNION ALL

SELECT
    'Pending (Not Yet Validated)' AS funnel_stage,
    COUNT(*)               AS invoice_count,
    4                      AS sort_order
FROM v2_invoice_documents
WHERE deleted_at IS NULL
  AND validation_status = 'not_validated'

ORDER BY sort_order
""".strip()


def build_top_customers_sql(days: int = 7, limit: int = 10) -> str:
    """
    Top customers by invoice submission volume for the last N days.
    Joins zodiac_users (email) with invoice counts.
    """
    return f"""
SELECT
    COALESCE(u.email, 'user_' || combined.user_id::TEXT) AS customer,
    combined.user_id,
    COUNT(*) AS total_invoices,
    COUNT(CASE WHEN combined.invoice_status = 'success' THEN 1 END) AS successful,
    COUNT(CASE WHEN combined.invoice_status = 'failed'  THEN 1 END) AS failed,
    MIN(combined.uploaded_at) AS first_submission,
    MAX(combined.uploaded_at) AS last_submission
FROM (
    SELECT user_id, uploaded_at, 'success' AS invoice_status
    FROM zodiac_invoice_success_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{days} days'
      AND deleted_at IS NULL
    UNION ALL
    SELECT user_id, uploaded_at, 'failed' AS invoice_status
    FROM zodiac_invoice_failed_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{days} days'
      AND deleted_at IS NULL
) combined
LEFT JOIN zodiac_users u ON u.id = combined.user_id
GROUP BY combined.user_id, u.email
ORDER BY total_invoices DESC
LIMIT {limit}
""".strip()


def build_invoice_amount_tax_by_currency_sql(days: int = 90, limit: int = 50) -> str:
    """
    Average total/tax by currency from invoice app business tables.
    Uses current V2 business table.
    """
    return f"""
SELECT
    COALESCE(NULLIF(TRIM(currency), ''), 'UNKNOWN') AS currency,
    COUNT(*) AS invoice_count,
    ROUND(AVG(total_amount), 2) AS avg_total_amount,
    ROUND(AVG(tax_amount), 2) AS avg_tax_amount,
    ROUND(SUM(total_amount), 2) AS total_amount_sum,
    ROUND(SUM(tax_amount), 2) AS tax_amount_sum
FROM invoice_v2_business_data
WHERE created_at >= NOW() - INTERVAL '{days} days'
  AND total_amount IS NOT NULL
GROUP BY COALESCE(NULLIF(TRIM(currency), ''), 'UNKNOWN')
ORDER BY total_amount_sum DESC
LIMIT {limit}
""".strip()


def _extract_days(question: str, default: int = 30) -> int:
    """Extract 'last N days' window from question, default 30."""
    m = re.search(r"\blast\s+(\d{1,3})\s+days?\b", question.lower())
    return max(1, min(365, int(m.group(1)) if m else default))


def build_sat_documents_by_received_date_sql(limit: int = 100) -> str:
    """List inbound SAT documents ordered by portal received_at (newest first)."""
    lim = max(1, min(500, int(limit)))
    return f"""
SELECT
    id,
    supplier_rfc,
    supplier_name,
    doc_type,
    cfdi_uuid,
    serie,
    folio,
    fecha,
    total,
    moneda,
    status,
    source,
    received_at
FROM sat_documents
ORDER BY received_at DESC NULLS LAST
LIMIT {lim}
""".strip()


def build_top_sat_suppliers_sql(limit: int = 10, days: int = 365) -> str:
    """Top suppliers by inbound SAT document count (sat_documents table)."""
    lim = max(1, min(100, int(limit)))
    d = max(1, min(365, int(days)))
    return f"""
SELECT
    supplier_rfc,
    supplier_name,
    COUNT(*) AS sat_document_count
FROM sat_documents
WHERE received_at >= (CURRENT_TIMESTAMP - INTERVAL '{d} days')
GROUP BY supplier_rfc, supplier_name
ORDER BY sat_document_count DESC
LIMIT {lim}
""".strip()


def build_sat_documents_this_week_sql(limit: int = 100) -> str:
    """SAT documents received in the current calendar week."""
    lim = max(1, min(500, int(limit)))
    return f"""
SELECT
    id,
    supplier_rfc,
    supplier_name,
    doc_type,
    cfdi_uuid,
    total,
    moneda,
    status,
    received_at
FROM sat_documents
WHERE received_at >= DATE_TRUNC('week', CURRENT_TIMESTAMP)
ORDER BY received_at DESC NULLS LAST
LIMIT {lim}
""".strip()


def build_sat_document_count_by_type_sql() -> str:
    """SAT document counts grouped by doc_type."""
    return """
SELECT
    doc_type,
    COUNT(*) AS document_count
FROM sat_documents
GROUP BY doc_type
ORDER BY document_count DESC
""".strip()


def build_inbound_sat_merge_sql() -> str:
    """
    Inbound SAT document merge status breakdown + top 5 suppliers by volume.
    """
    return """
WITH merge_status AS (
    SELECT
        CASE
            WHEN status = 'MERGED' THEN 'Pending (not yet sent to SAP)'
            WHEN status = 'SAP_SENT' THEN 'Sent to SAP'
            WHEN status = 'SAP_CONFIRMED' THEN 'Confirmed by SAP'
            ELSE status
        END AS merge_status,
        COUNT(*) AS count,
        COALESCE(SUM(net_amount), 0) AS total_net_amount
    FROM sat_canonical_merged
    GROUP BY
        CASE
            WHEN status = 'MERGED' THEN 'Pending (not yet sent to SAP)'
            WHEN status = 'SAP_SENT' THEN 'Sent to SAP'
            WHEN status = 'SAP_CONFIRMED' THEN 'Confirmed by SAP'
            ELSE status
        END
    ORDER BY count DESC
),
top_suppliers AS (
    SELECT
        COALESCE(vendor_name, vendor_rfc) AS supplier_name,
        vendor_rfc,
        COUNT(*) AS document_count,
        COALESCE(SUM(net_amount), 0) AS total_net_amount,
        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS rn
    FROM sat_canonical_merged
    GROUP BY vendor_name, vendor_rfc
)
SELECT
    'merge_status' AS section,
    merge_status AS label,
    count AS doc_count,
    total_net_amount,
    NULL::TEXT AS supplier_name,
    NULL::TEXT AS vendor_rfc
FROM merge_status
UNION ALL
SELECT
    'top_supplier' AS section,
    supplier_name AS label,
    document_count AS doc_count,
    total_net_amount,
    supplier_name,
    vendor_rfc
FROM top_suppliers
WHERE rn <= 5
ORDER BY section, doc_count DESC
""".strip()


def build_top_customers_business_currency_sql(days: int = 30, limit: int = 20) -> str:
    """Top customers from invoice_v2_business_data with currency breakdown."""
    d = max(1, min(365, int(days)))
    lim = max(1, min(100, int(limit)))
    return f"""
SELECT
    COALESCE(NULLIF(TRIM(customer_name), ''), NULLIF(TRIM(customer_id), ''), 'Unknown') AS customer,
    COALESCE(NULLIF(TRIM(currency), ''), 'UNKNOWN') AS currency,
    COUNT(*) AS invoice_count,
    ROUND(SUM(COALESCE(total_amount, 0)), 2) AS total_amount,
    ROUND(AVG(COALESCE(total_amount, 0)), 2) AS avg_amount
FROM invoice_v2_business_data
WHERE created_at >= NOW() - INTERVAL '{d} days'
  AND customer_name IS NOT NULL
GROUP BY customer, currency
ORDER BY total_amount DESC
LIMIT {lim}
""".strip()


def build_edi_customer_status_sql(days: int = 30, limit: int = 50) -> str:
    """EDI success vs failed submissions by Zodiac account."""
    d = max(1, min(365, int(days)))
    lim = max(1, min(200, int(limit)))
    return f"""
SELECT
    COALESCE(u.email, 'user_' || combined.user_id::TEXT) AS account,
    combined.user_id,
    COUNT(CASE WHEN combined.outcome = 'success' THEN 1 END) AS edi_success,
    COUNT(CASE WHEN combined.outcome = 'failed' THEN 1 END) AS edi_failed,
    COUNT(*) AS total_submissions
FROM (
    SELECT user_id, 'success' AS outcome
    FROM zodiac_invoice_success_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{d} days'
      AND deleted_at IS NULL
    UNION ALL
    SELECT user_id, 'failed' AS outcome
    FROM zodiac_invoice_failed_edi
    WHERE uploaded_at >= NOW() - INTERVAL '{d} days'
      AND deleted_at IS NULL
) combined
LEFT JOIN zodiac_users u ON u.id = combined.user_id
GROUP BY combined.user_id, u.email
ORDER BY total_submissions DESC
LIMIT {lim}
""".strip()


def build_invoice_conversion_kpi_sql() -> str:
    """V2 funnel stages + conversion success rate."""
    return """
WITH received AS (
    SELECT COUNT(*) AS cnt FROM v2_invoice_documents WHERE deleted_at IS NULL
),
validated_ok AS (
    SELECT COUNT(*) AS cnt FROM v2_validated_invoices WHERE status = 'success'
),
validated_fail AS (
    SELECT COUNT(*) AS cnt FROM v2_validated_invoices WHERE status = 'failed'
),
pending AS (
    SELECT COUNT(*) AS cnt FROM v2_invoice_documents
    WHERE deleted_at IS NULL AND validation_status = 'not_validated'
)
SELECT 'Documents received' AS funnel_stage, (SELECT cnt FROM received)::BIGINT AS count, 1 AS sort_order
UNION ALL SELECT 'Validated (success)', (SELECT cnt FROM validated_ok), 2
UNION ALL SELECT 'Failed validation', (SELECT cnt FROM validated_fail), 3
UNION ALL SELECT 'Pending validation', (SELECT cnt FROM pending), 4
UNION ALL SELECT
    'Conversion success rate %',
    CASE WHEN (SELECT cnt FROM received) > 0
        THEN ROUND(100.0 * (SELECT cnt FROM validated_ok) / (SELECT cnt FROM received), 2)
        ELSE 0 END,
    5
ORDER BY sort_order
""".strip()


def _detect_inbound_outbound_dimension(question: str) -> str:
    q = (question or "").lower()
    if any(w in q for w in ("country", "countries", "nation")):
        return "country"
    if any(w in q for w in ("product", "products", "material", "sku")):
        return "product"
    if any(w in q for w in ("supplier", "vendor")):
        return "supplier"
    if any(w in q for w in ("document type", "doc type", "doc_type", "type of document")):
        return "doc_type"
    return "doc_type"


def build_inbound_vs_outbound_comparison_sql(question: str, days: int = 30) -> str:
    """
    Side-by-side inbound SAT vs outbound invoice metrics.
    Supports grouping by document type, supplier, country, or product.
    """
    d = max(1, min(365, int(days)))
    dim = _detect_inbound_outbound_dimension(question)

    if dim == "country":
        return f"""
SELECT
    COALESCE(NULLIF(TRIM(b.customer_country), ''), 'UNKNOWN') AS dimension_value,
    0::BIGINT AS inbound_sat_docs,
    COUNT(*) AS outbound_invoices,
    ROUND(SUM(COALESCE(b.total_amount, 0)), 2) AS outbound_total_amount,
    COALESCE(NULLIF(TRIM(b.currency), ''), 'UNKNOWN') AS currency
FROM invoice_v2_business_data b
WHERE b.created_at >= NOW() - INTERVAL '{d} days'
GROUP BY dimension_value, currency
UNION ALL
SELECT
    'MX (inbound SAT)' AS dimension_value,
    COUNT(*) AS inbound_sat_docs,
    0::BIGINT AS outbound_invoices,
    ROUND(SUM(COALESCE(NULLIF(TRIM(total), '')::NUMERIC, 0)), 2) AS outbound_total_amount,
    COALESCE(NULLIF(TRIM(moneda), ''), 'MXN') AS currency
FROM sat_documents
WHERE received_at >= NOW() - INTERVAL '{d} days'
GROUP BY currency
ORDER BY inbound_sat_docs DESC, outbound_invoices DESC
LIMIT 50
""".strip()

    if dim == "supplier":
        return f"""
WITH inbound AS (
    SELECT
        COALESCE(NULLIF(TRIM(supplier_name), ''), supplier_rfc, 'Unknown') AS label,
        COUNT(*) AS inbound_count,
        ROUND(SUM(COALESCE(NULLIF(TRIM(total), '')::NUMERIC, 0)), 2) AS inbound_amount
    FROM sat_documents
    WHERE received_at >= NOW() - INTERVAL '{d} days'
    GROUP BY label
),
outbound AS (
    SELECT
        COALESCE(NULLIF(TRIM(supplier_name), ''), NULLIF(TRIM(supplier_id), ''), 'Unknown') AS label,
        COUNT(*) AS outbound_count,
        ROUND(SUM(COALESCE(total_amount, 0)), 2) AS outbound_amount
    FROM invoice_v2_business_data
    WHERE created_at >= NOW() - INTERVAL '{d} days'
    GROUP BY label
)
SELECT
    COALESCE(i.label, o.label) AS supplier,
    COALESCE(i.inbound_count, 0) AS inbound_sat_docs,
    COALESCE(o.outbound_count, 0) AS outbound_invoices,
    COALESCE(i.inbound_amount, 0) AS inbound_amount,
    COALESCE(o.outbound_amount, 0) AS outbound_amount
FROM inbound i
FULL OUTER JOIN outbound o ON i.label = o.label
ORDER BY COALESCE(i.inbound_count, 0) + COALESCE(o.outbound_count, 0) DESC
LIMIT 50
""".strip()

    if dim == "product":
        return f"""
WITH outbound_products AS (
    SELECT
        COALESCE(NULLIF(TRIM(prod->>'name'), ''), NULLIF(TRIM(prod->>'description'), ''), 'Unknown') AS product_name,
        COUNT(*) AS outbound_line_count,
        ROUND(SUM(COALESCE((prod->>'revenue')::NUMERIC, (prod->>'price')::NUMERIC, 0)), 2) AS outbound_amount
    FROM invoice_v2_business_data b,
        LATERAL jsonb_array_elements(COALESCE(b.products::jsonb, '[]'::jsonb)) AS prod
    WHERE b.created_at >= NOW() - INTERVAL '{d} days'
    GROUP BY product_name
),
inbound_types AS (
    SELECT doc_type AS product_name, COUNT(*) AS inbound_count
    FROM sat_documents
    WHERE received_at >= NOW() - INTERVAL '{d} days'
    GROUP BY doc_type
)
SELECT
    COALESCE(op.product_name, it.product_name) AS dimension_value,
    COALESCE(it.inbound_count, 0) AS inbound_sat_docs,
    COALESCE(op.outbound_line_count, 0) AS outbound_lines,
    COALESCE(op.outbound_amount, 0) AS outbound_amount
FROM outbound_products op
FULL OUTER JOIN inbound_types it ON op.product_name = it.product_name
ORDER BY COALESCE(it.inbound_count, 0) + COALESCE(op.outbound_line_count, 0) DESC
LIMIT 50
""".strip()

    # doc_type default
    return f"""
SELECT 'inbound_sat' AS pipeline, doc_type AS dimension_value, COUNT(*) AS doc_count,
       ROUND(SUM(COALESCE(NULLIF(TRIM(total), '')::NUMERIC, 0)), 2) AS total_amount
FROM sat_documents
WHERE received_at >= NOW() - INTERVAL '{d} days'
GROUP BY doc_type
UNION ALL
SELECT 'outbound_v2' AS pipeline,
       CASE WHEN v.status = 'success' THEN 'VALIDATED_SUCCESS' ELSE 'VALIDATED_FAILED' END AS dimension_value,
       COUNT(*) AS doc_count,
       NULL::NUMERIC AS total_amount
FROM v2_validated_invoices v
JOIN v2_invoice_documents d ON d.id = v.document_id
WHERE d.deleted_at IS NULL
  AND d.uploaded_at >= NOW() - INTERVAL '{d} days'
GROUP BY v.status
ORDER BY pipeline, doc_count DESC
""".strip()


# ---------------------------------------------------------------------------
# Public resolution entry point
# ---------------------------------------------------------------------------

def _extract_user_question(question: str) -> str:
    """Strip generative routing prefix; match on user text only."""
    s = (question or "").strip()
    marker = "User question:"
    if "[ZODIAC_GENERATIVE_CLIENT_ROUTING" in s and marker in s:
        idx = s.rfind(marker)
        if idx >= 0:
            tail = s[idx + len(marker):].strip()
            if tail:
                return tail
    return s


def resolve_operational_query(
    question: str,
    time_scope: str = "current",
    api_key: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Returns (sql, query_type) if the question should be answered from
    the Zodiac operational DB, or None if it should fall through to the
    intent pipeline / SAP path.

    Priority order:
    1. Hard-coded fast-path for known common patterns (no LLM needed)
    2. AI-driven dynamic SQL generation for any other operational question

    Fires for time_scope 'current' or 'both' when the question is operational (Zodiac app DB).
    """
    ts = (time_scope or "current").strip().lower()
    if ts not in ("current", "both"):
        return None
    if ts == "both" and not _is_operational_question(_extract_user_question(question)):
        return None

    q = _extract_user_question(question).lower()

    has_invoice_ctx = any(w in q for w in ("invoice", "billing", "document volume"))

    # --- Fast-path 0: EDI status (before generic failed-invoice matcher) ---
    edi_status_signals = (
        "edi status", "succeeded vs failed edi", "edi submissions",
        "success vs failed edi", "edi success", "failed edi submissions",
        "edi failure by", "count succeeded vs failed edi",
    )
    if any(p in q for p in edi_status_signals):
        days_val = _extract_days(question, default=30)
        sql = build_edi_customer_status_sql(days=days_val)
        logger.info("operational_resolver: fast-path edi_customer_status (%d days)", days_val)
        return sql, "edi_customer_status"

    # --- Fast-path 1: V2 conversion KPI (before generic funnel) ---
    conversion_signals = (
        "conversion success rate", "conversion rate", "v2 invoice conversion",
        "success rate versus documents received", "largest backlog",
        "funnel step shows", "invoice conversion",
    )
    if any(p in q for p in conversion_signals):
        sql = build_invoice_conversion_kpi_sql()
        logger.info("operational_resolver: fast-path invoice_conversion_kpi")
        return sql, "invoice_conversion_kpi"

    # --- Fast-path 2: Failed invoice summary / failure reasons ---
    failed_invoice_signals = (
        "failed invoice", "invoice failed", "failure reason", "failure reasons",
        "why invoices fail", "why did invoice", "summarize failed",
        "failed edi", "edi failure", "xml validation fail", "xml fail",
        "conversion fail", "processing fail", "invoice error",
        "top failure", "group failure", "top reasons",
    )
    if any(p in q for p in failed_invoice_signals) and has_invoice_ctx:
        days_val = _extract_days(question, default=30)
        sql = build_failed_invoices_sql(days=days_val)
        logger.info("operational_resolver: fast-path failed_invoices_summary (%d days)", days_val)
        return sql, "failed_invoices_summary"

    # --- Fast-path 2: Invoice volume trend (month-over-month) ---
    invoice_trend_signals = (
        "month-over-month", "month over month", "monthly trend",
        "invoice volume trend", "invoice trend", "volume trend",
        "invoices per month", "invoices by month", "volume by month",
        "how does invoice volume", "invoice volume over", "trend month",
        "week over week", "weekly trend",
    )
    has_trend = any(p in q for p in invoice_trend_signals)
    has_month_window = bool(re.search(r"\blast\s+\d+\s+months?\b", q))

    if has_invoice_ctx and (has_trend or has_month_window):
        months = _extract_months(question, default=12)
        sql = build_invoice_volume_trend_sql(months=months)
        logger.info("operational_resolver: fast-path invoice_volume_trend (%d months)", months)
        return sql, "invoice_volume_trend"

    # --- Fast-path 3: Outbound invoice funnel (V2 pipeline) ---
    funnel_signals = (
        "outbound funnel", "processing funnel", "invoice funnel",
        "outbound process flow", "outbound process", "process flow",
        "v2 funnel", "funnel stage", "funnel stages",
        "received vs validated", "validated vs converted",
        "how many received", "how many validated", "funnel breakdown",
        "pipeline funnel", "v2 invoice", "validation funnel",
    )
    if any(p in q for p in funnel_signals):
        sql = build_outbound_funnel_sql()
        logger.info("operational_resolver: fast-path outbound_funnel")
        return sql, "outbound_funnel"

    # --- Fast-path 3b: Inbound vs outbound comparison (country / doc type / product / supplier) ---
    compare_signals = (
        "inbound vs outbound", "inbound versus outbound", "compare inbound",
        "compare with outbound", "sat vs outbound", "inbound and outbound",
        "inbound sat vs outbound", "compare sat with outbound",
    )
    has_compare = any(p in q for p in compare_signals) or (
        "compare" in q and "inbound" in q and "outbound" in q
    )
    if has_compare or (
        "outbound" in q and any(w in q for w in ("country", "document type", "product", "supplier"))
        and any(w in q for w in ("inbound", "sat", "cfdi"))
    ):
        days_val = _extract_days(question, default=30)
        sql = build_inbound_vs_outbound_comparison_sql(question, days=days_val)
        logger.info("operational_resolver: fast-path inbound_vs_outbound (%s)", _detect_inbound_outbound_dimension(question))
        return sql, "inbound_vs_outbound_comparison"

    # --- Fast-path 3e: Top customers from business data (with currency) ---
    business_customer_signals = (
        "invoice business data", "business data", "extracted zodiac",
        "ranked invoice counts", "with currency",
    )
    if any(p in q for p in business_customer_signals) and "customer" in q:
        days_val = _extract_days(question, default=30)
        sql = build_top_customers_business_currency_sql(days=days_val)
        logger.info("operational_resolver: fast-path top_customers_business_currency (%d days)", days_val)
        return sql, "top_customers_business_currency"

    # --- Fast-path 4: Top customers by invoice volume ---
    customer_signals = (
        "top customer", "customers by invoice", "invoices by customer",
        "customer invoice count", "customer activity", "invoices per customer",
        "customer volume", "top 10 customer", "top 5 customer",
    )
    if any(p in q for p in customer_signals) and "revenue" not in q and "business data" not in q:
        days_val = _extract_days(question, default=7)
        sql = build_top_customers_sql(days=days_val)
        logger.info("operational_resolver: fast-path top_customers (%d days)", days_val)
        return sql, "top_customers"

    # --- Fast-path 5: Invoice avg total/tax by currency (app tables) ---
    amount_tax_signals = (
        "average total amount", "avg total amount", "tax amount by currency",
        "total amount and tax amount by currency", "invoice app tables",
        "invoice business data by currency", "invoice_v2_business_data",
    )
    if any(p in q for p in amount_tax_signals):
        days_val = _extract_days(question, default=90)
        sql = build_invoice_amount_tax_by_currency_sql(days=days_val, limit=50)
        logger.info("operational_resolver: fast-path invoice_amount_tax_by_currency (%d days)", days_val)
        return sql, "invoice_amount_tax_by_currency"

    # --- Fast-path 6a: List SAT documents by received date ---
    list_sat_signals = (
        "show all inbound sat",
        "all inbound sat document",
        "sat documents ordered",
        "ordered by received",
        "order by received",
    )
    if any(p in q for p in list_sat_signals) or (
        "sat document" in q and "received" in q and ("order" in q or "ordered" in q)
    ):
        sql = build_sat_documents_by_received_date_sql()
        logger.info("operational_resolver: fast-path sat_documents_by_received_date")
        return sql, "sat_documents_by_received_date"

    # --- Fast-path 6c: Inbound SAT merge stats (before top-suppliers) ---
    sat_merge_signals = (
        "sat merge", "canonical merge", "merge pending", "merges pending",
        "sent to sap", "pending vs sent", "merge status",
        "summarize inbound sat",
    )
    if any(p in q for p in sat_merge_signals) or (
        "inbound sat" in q and any(w in q for w in ("merge", "pending", "sent to sap", "summarize"))
    ):
        sql = build_inbound_sat_merge_sql()
        logger.info("operational_resolver: fast-path inbound_sat_merge")
        return sql, "inbound_sat_merge"

    # --- Fast-path 6b: Top suppliers by SAT document count (sat_documents) ---
    if "sat" in q and any(
        p in q
        for p in (
            "suppliers sent the most",
            "supplier sent the most",
            "most sat document",
            "top supplier",
            "top 5 supplier",
            "suppliers by volume",
            "supplier volume",
            "which suppliers",
        )
    ):
        days_val = _extract_days(question, default=365)
        sql = build_top_sat_suppliers_sql(days=days_val)
        logger.info("operational_resolver: fast-path top_sat_suppliers (%d days)", days_val)
        return sql, "top_sat_suppliers"

    # --- Fast-path 6b2: SAT documents received this week ---
    if "sat" in q and re.search(r"\b(this|current)\s+week\b", q):
        sql = build_sat_documents_this_week_sql()
        logger.info("operational_resolver: fast-path sat_documents_this_week")
        return sql, "sat_documents_this_week"

    # --- Fast-path 6b3: SAT document count by type ---
    if "sat" in q and "count" in q and "type" in q:
        sql = build_sat_document_count_by_type_sql()
        logger.info("operational_resolver: fast-path sat_document_count_by_type")
        return sql, "sat_document_count_by_type"

    # --- AI-driven path: for any other operational question ---
    user_q = _extract_user_question(question)
    if _is_operational_question(user_q):
        logger.info("operational_resolver: using AI-driven SQL generation for: %s", user_q[:80])
        sql = _generate_zodiac_sql_with_ai(user_q, api_key=api_key)
        if sql:
            logger.info("operational_resolver: AI generated SQL (%d chars)", len(sql))
            return sql, "ai_generated_operational"
        else:
            logger.info("operational_resolver: AI returned NOT_OPERATIONAL or failed")

    return None
