from __future__ import annotations

import logging
import json
import operator
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Annotated, TypedDict

from sqlalchemy.orm import Session
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from .schema_intelligence import ColumnProfile, schema_intelligence, TableProfile
from .schema_nl_lexicon import SAP_COLUMN_NL_HINTS
from ..utils.openai_chat_params import (
    langchain_openai_limit_kwargs,
    langchain_openai_temperature_kwargs,
)
from ..config.config import (
    LANGGRAPH_ANSWER_MAX_TOKENS,
    LANGGRAPH_ANSWER_MODEL,
    LANGGRAPH_MAX_COLUMNS_PER_TABLE,
    LANGGRAPH_MAX_SCHEMA_TABLES,
    LANGGRAPH_MAX_SCHEMA_TABLES_HARD_CAP,
    LANGGRAPH_SCHEMA_JOIN_BOOST,
    LANGGRAPH_SELECT_ROW_CAP,
    LANGGRAPH_SKIP_VERIFY_ANSWER,
    LANGGRAPH_SQL_MAX_TOKENS,
    LANGGRAPH_SQL_MODEL,
)

logger = logging.getLogger("zodiac-api.multi_stage_planner")

# ═══════════════════════════════════════════════════════════════════════
# SCHEMA INTELLIGENCE BOOTSTRAP
# schema_intelligence is a shared singleton that starts empty (no tables,
# no join graph) until .initialize() is called. Without this, every
# query gets an empty schema/join context — the planner "doesn't
# understand" ANY question, not just dimension questions. Lazily
# initialize it on first use here.
# ═══════════════════════════════════════════════════════════════════════
_SCHEMA_EXPORT_PATH = Path(__file__).resolve().parents[2] / "schema_export.json"
_TABLE_KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "sap_table_knowledge.json"


def _ensure_schema_intelligence() -> None:
    """Lazily populate schema_intelligence.tables / join_graph on first use."""
    if schema_intelligence._initialized:
        return
    try:
        schema_intelligence.initialize(_SCHEMA_EXPORT_PATH, _TABLE_KNOWLEDGE_PATH)
        logger.info(
            "schema_intelligence bootstrapped: %d tables, %d join edges (export=%s, knowledge=%s)",
            len(schema_intelligence.tables),
            len(schema_intelligence.join_graph),
            _SCHEMA_EXPORT_PATH,
            _TABLE_KNOWLEDGE_PATH,
        )
    except Exception:
        logger.exception("Failed to initialize schema_intelligence")

# ═══════════════════════════════════════════════════════════════════════
# DOMAIN → TABLE MAP  (Stage 2/3: Domain Classification + Category Discovery)
# ═══════════════════════════════════════════════════════════════════════
DOMAIN_TABLE_MAP: Dict[str, Dict[str, List[str]]] = {
    "sales": {
        "primary": ["VBRK", "VBRP", "VBAK", "VBAP"],
        "support": ["KNA1", "MAKT", "VBFA", "VBEP", "KONV", "MVKE", "LIKP"],
    },
    "delivery": {
        "primary": ["LIKP", "LIPS"],
        "support": ["KNA1", "MAKT", "VBFA", "VBRP"],
    },
    "finance": {
        "primary": ["BKPF", "BSEG"],
        "support": ["BSAD", "KNA1", "FAGLFLEXA", "DFKKOP"],
    },
    "purchasing": {
        "primary": ["EKKO", "EKPO"],
        "support": ["LFA1", "MAKT", "MARA", "EBAN", "EINA"],
    },
    "inventory": {
        "primary": ["MARA", "MARD", "MARC"],
        "support": ["MAKT", "MBEW", "MCHB"],
    },
    "customer": {
        "primary": ["KNA1", "KNVV"],
        "support": ["VBRK", "BSAD", "KNVP"],
    },
    "vendor": {
        "primary": ["LFA1", "LFB1"],
        "support": ["EKKO", "LFM1", "EKPO"],
    },
    "controlling": {
        "primary": ["COEP", "CEPC", "CSKS"],
        "support": ["COSP", "COSS", "AUFK", "CRHD"],
    },
    "costing": {
        "primary": ["CKIS", "KEKO", "CKHS"],
        "support": ["KEPH", "CKMLCR", "MBEW"],
    },
    "sat_inbound": {
        "primary": ["sat_documents"],
        "support": ["sat_canonical_merged", "sat_simple_merged", "supplier_tokens", "sat_company_mappings"],
    },
    "edi_operations": {
        "primary": ["zodiac_invoice_failed_edi", "zodiac_invoice_success_edi"],
        "support": ["converted_invoices", "invoice_v2_documents", "invoice_v2_validated"],
    },
    "general": {
        "primary": ["VBRK", "VBRP", "KNA1"],
        "support": ["MAKT", "MARA", "VBAK"],
    },
}

# Domain keyword signals for fast classification
_DOMAIN_SIGNALS: Dict[str, List[str]] = {
    "sat_inbound": ["sat", "cfdi", "inbound document", "inbound invoice", "supplier sent", "payment complement", "sat document", "cfdi uuid"],
    "edi_operations": ["edi", "failed invoice", "zodiac invoice", "conversion", "v2 invoice", "outbound", "conversion rate", "funnel"],
    "sales": ["billing", "revenue", "invoice", "vbrk", "vbrp", "net value", "billed amount", "billing document", "sales order", "vbak", "vbap", "sales organization", "sales org", "product group", "material group", "destination country", "document category", "sd document type", "sales region"],
    "delivery": ["delivery", "shipment", "dispatch", "likp", "lips", "shipped", "goods issue", "transport mode", "shipping type", "mode of transport", "route", "vsart"],
    "finance": ["accounting", "gl", "general ledger", "bkpf", "bseg", "posting", "fiscal year", "open item", "receivable", "payable", "bsad"],
    "purchasing": ["purchase order", "vendor", "procurement", "ekko", "ekpo", "po value", "goods receipt", "purchase requisition"],
    "inventory": ["stock", "inventory", "material", "warehouse", "mara", "mard", "mchb", "storage location", "plant stock"],
    "customer": ["customer", "client", "buyer", "kna1", "knvv", "customer master", "customer list"],
    "vendor": ["vendor", "supplier", "lfa1", "lfb1", "vendor master"],
    "controlling": ["cost center", "profit center", "controlling", "coep", "cepc", "csks", "co document"],
    "costing": ["costing", "cost estimate", "ckis", "keko", "product cost", "standard cost"],
}

# ═══════════════════════════════════════════════════════════════════════
# ERP SQL RULES (shared across generation + validation prompts)
# ═══════════════════════════════════════════════════════════════════════
ERP_SQL_RULES = """
══ ERP SQL RULES — ALL MANDATORY ══
1. Use ONLY column names that appear in the provided schema — never guess or invent columns.
2. DATE ARITHMETIC
   - SAP date fields (fkdat, erdat, budat) are stored as YYYYMMDD text — parse with to_date(col,'YYYYMMDD').
   - For monthly trend: date_trunc('month', parsed_date) → output YYYY-MM.
   - For PostgreSQL date ranges use INTERVAL: CURRENT_DATE - INTERVAL '30 days'.
3. JOINS — always explicit with ON clause. Never implicit cross joins.
4. RESULT SIZE — handled by smart execution layer. Do NOT add LIMIT unless the user explicitly asked for top N.
   If user says "top 10" → add ORDER BY metric DESC LIMIT 10.
5. NULL SAFETY — wrap nullable numeric cols with COALESCE(col, 0).
6. FORMAT
   - No semicolons at end. Always alias aggregates: SUM(x) AS TotalX.
   - Column aliases must not contain spaces (use CamelCase or underscore).
   - Always ORDER BY for ranking/trend queries.
   - SAP tables in PostgreSQL: uppercase quoted ("VBRK") or lowercase unquoted (vbrk) — copy EXACTLY from schema list.
   - SAP COLUMNS are almost always lowercase (vbeln, netwr, fkdat) — never uppercase column names.
7. GROUP BY — every non-aggregate SELECT column must be in GROUP BY.
8. MASTER DATA — include name/description columns when available (KNA1.name1, MAKT.maktx, LFA1.name1).
9. READ ONLY — never generate DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE.
10. SAT/CFDI — use sat_documents table with lowercase column names. Key fields:
    supplier_rfc, supplier_name, receiver_rfc, total, subtotal, fecha (invoice date), received_at (arrival), doc_type, status.
"""

# SAP related tables for join expansion
_SAP_RELATED_TABLES: Dict[str, Tuple[str, ...]] = {
    "VBRK": ("VBRP", "KNA1", "KONV", "VBFA"),
    "VBRP": ("VBRK", "MAKT", "MARA"),
    "VBAK": ("VBAP", "KNA1", "VBEP", "KONV", "VBFA"),
    "VBAP": ("VBAK", "MAKT", "MARA", "VBEP"),
    "LIKP": ("LIPS", "KNA1", "VBFA"),
    "LIPS": ("LIKP", "MAKT"),
    "EKKO": ("EKPO", "LFA1"),
    "EKPO": ("EKKO", "MAKT", "LFA1"),
    "BKPF": ("BSEG", "BSAD"),
    "BSEG": ("BKPF", "BSAD"),
    "BSAD": ("KNA1", "BKPF", "BSEG"),
    "MARA": ("MAKT", "MARD", "MBEW"),
    "MARD": ("MARA", "MAKT"),
    "MBEW": ("MARA", "MAKT"),
    "sat_documents": ("sat_simple_merged", "supplier_tokens"),
    "SAT_DOCUMENTS": ("sat_simple_merged", "supplier_tokens"),
}


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _classify_domain(question: str) -> str:
    """Stage 2: Rule-based domain classification — fast, no LLM call needed."""
    q = question.lower()
    best_domain = "general"
    best_score = 0
    for domain, signals in _DOMAIN_SIGNALS.items():
        score = sum(1 for s in signals if s in q)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain


def _select_tables_for_domain(domain: str, question: str, max_tables: int = 8) -> List[str]:
    """Stage 3/4: Category → Table selection. Returns resolved table names from schema_intelligence."""
    _ensure_schema_intelligence()
    domain_def = DOMAIN_TABLE_MAP.get(domain, DOMAIN_TABLE_MAP["general"])
    primary = domain_def["primary"]
    support = domain_def["support"]

    # Resolve to actual keys in schema_intelligence
    all_candidates = primary + support
    resolved: List[str] = []
    for name in all_candidates:
        key = _resolve_table_key(name)
        if key and key not in resolved:
            resolved.append(key)
        if len(resolved) >= max_tables:
            break

    # If we didn't find enough, fall back to schema_intelligence semantic resolution
    if len(resolved) < 2:
        fallback = schema_intelligence.resolve_entities(question)
        for t in fallback:
            if t and t.name not in resolved:
                resolved.append(t.name)

    return resolved[:max_tables]


def _resolve_table_key(name: str) -> Optional[str]:
    """Resolve a table name to the actual key in schema_intelligence (handles case)."""
    if not name:
        return None
    if name in schema_intelligence.tables:
        return name
    u = name.upper()
    if u in schema_intelligence.tables:
        return u
    lo = name.lower()
    if lo in schema_intelligence.tables:
        return lo
    return None


def _score_columns(cols: List[ColumnProfile], question: str) -> List[ColumnProfile]:
    """Stage 6: Column Ranking — score columns by relevance to the question. Return top N."""
    q = question.lower()
    q_words = set(re.findall(r'\w+', q))

    def score(col: ColumnProfile) -> int:
        s = 0
        role = (getattr(col, "semantic_role", None) or "").lower()
        name_u = col.name.upper()
        name_l = col.name.lower()

        # Semantic role scoring
        if role == "key": s += 80
        elif role == "amount": s += 90
        elif role == "date": s += 75
        elif role == "dimension": s += 60

        # Question relevance
        if name_l in q_words: s += 100
        if any(name_l in w or w in name_l for w in q_words if len(w) > 3): s += 30

        # NL dimension/synonym hints (e.g. "country" -> land1, "sales org" -> vkorg,
        # "product group" -> matkl, "transport mode" -> vsart, "document category" -> vbtyp)
        if any(hint in q for hint in SAP_COLUMN_NL_HINTS.get(name_l, ())): s += 95

        # Common important columns
        if name_u in ("NAME1", "NAME2", "MAKTX", "WAERS", "WAERK", "MEINS"): s += 50
        if name_u in ("KUNNR", "MATNR", "VBELN", "EBELN", "BELNR", "LIFNR"): s += 70
        if name_u in ("NETWR", "DMBTR", "WRBTR", "NETPR", "MENGE", "FKIMG"): s += 85
        if name_u in ("FKDAT", "ERDAT", "BUDAT", "BLDAT", "AEDAT"): s += 70
        if name_u.endswith("TXT") or name_u.endswith("_TXT"): s += 20

        # Penalize audit/internal cols
        if name_u in ("MANDT", "LOEKZ", "AENAM", "ERNAM", "ERZEIT", "AEZEIT"): s -= 20
        if any(p in name_l for p in ("created_by", "modified_by", "internal", "_code")): s -= 10

        return s

    scored = sorted(cols, key=score, reverse=True)
    cap = max(LANGGRAPH_MAX_COLUMNS_PER_TABLE, 20)
    return scored[:cap]


def _build_schema_text(table_names: List[str], question: str) -> Tuple[str, List[str]]:
    """Stage 5: Column Discovery — build focused schema text for SQL generation."""
    lines: List[str] = []
    resolved_names: List[str] = []

    for name in table_names:
        t = schema_intelligence.tables.get(name)
        if not t:
            continue
        resolved_names.append(t.name)
        cols = list(t.columns.values())
        top_cols = _score_columns(cols, question)

        lines.append(f"\n{t.name}:")
        for c in top_cols:
            role = getattr(c, "semantic_role", "") or ""
            role_tag = f" [{role}]" if role else ""
            hints = SAP_COLUMN_NL_HINTS.get(c.name.lower())
            hint_tag = f" — {', '.join(hints[:3])}" if hints else ""
            lines.append(f"  {c.name} ({c.data_type}){role_tag}{hint_tag}")
        omitted = len(cols) - len(top_cols)
        if omitted > 0:
            lines.append(f"  … ({omitted} lower-relevance columns omitted)")

    return "\n".join(lines), resolved_names


def _get_join_hints(table_names: List[str]) -> str:
    """Stage 7: Relationship Graph — return known join edges for selected tables."""
    table_set = set(table_names)
    hints: List[str] = []
    for edge in (getattr(schema_intelligence, "join_graph", None) or []):
        if edge.source_table in table_set and edge.target_table in table_set:
            hints.append(
                f'"{edge.source_table}".{edge.source_column.lower()} = '
                f'"{edge.target_table}".{edge.target_column.lower()}'
            )
    return "\n".join(sorted(set(hints))) if hints else ""


def _extract_sql(text: str) -> str:
    if not text:
        return ""
    fenced = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def _take_first_sql_statement(sql: str) -> str:
    s = (sql or "").strip().rstrip(";")
    if ";" not in s:
        return s
    parts = [p.strip() for p in s.split(";") if p.strip()]
    return parts[0] if parts else s


_FORBIDDEN_WRITE_SQL = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXECUTE|CALL)\b|\bMERGE\s+INTO\b|\bCOPY\s+",
    re.I,
)


def _validate_readonly_sql(sql: str) -> Optional[str]:
    s = (sql or "").strip()
    if not s:
        return "Empty SQL."
    up = re.sub(r"^\s+", "", s).upper()
    if up.startswith("WITH"):
        if not re.search(r"\bSELECT\b", s, re.I):
            return "Only WITH…SELECT is allowed."
    elif not up.startswith("SELECT"):
        return "Only SELECT queries are allowed."
    if _FORBIDDEN_WRITE_SQL.search(s):
        return "Forbidden statement — read-only SELECT only."
    return None


def _is_aggregation_query(sql: str) -> bool:
    """True if SQL already has GROUP BY or aggregate functions — don't add LIMIT."""
    return bool(
        re.search(r"\bGROUP\s+BY\b", sql, re.I) or
        re.search(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", sql, re.I)
    )


def _has_explicit_limit(sql: str) -> bool:
    return bool(re.search(r"\bLIMIT\s+\d+", sql, re.I))


def _extract_top_n(question: str) -> Optional[int]:
    for pat in (r"\btop\s+(\d+)\b", r"\bfirst\s+(\d+)\b", r"\bbottom\s+(\d+)\b"):
        m = re.search(pat, question or "", re.I)
        if m:
            n = int(m.group(1))
            return n if 1 <= n <= 10_000 else None
    return None


def _build_time_hints(question: str, days: int) -> str:
    """Build time-range SQL hints from natural language question."""
    q = question.lower()
    lines: List[str] = []

    top_n = _extract_top_n(question)
    if top_n:
        want_low = bool(re.search(r"\b(bottom|lowest|smallest|worst|least)\b", q))
        direction = "ASC" if want_low else "DESC"
        lines.append(f"- Ranking: ORDER BY metric {direction}, LIMIT {top_n}.")

    if re.search(r"\b(?:last|past)\s+(\d+)\s*days?\b", q):
        m = re.search(r"\b(?:last|past)\s+(\d+)\s*days?\b", q)
        lines.append(f"- Time: last {m.group(1)} day(s) → ≥ CURRENT_DATE - INTERVAL '{m.group(1)} days'.")
    if re.search(r"\b(?:last|past)\s+(\d+)\s*months?\b", q):
        m = re.search(r"\b(?:last|past)\s+(\d+)\s*months?\b", q)
        lines.append(f"- Time: last {m.group(1)} month(s) → ≥ CURRENT_DATE - INTERVAL '{m.group(1)} months'.")
    if "ytd" in q or "year to date" in q:
        lines.append("- Time: YTD → from date_trunc('year', CURRENT_DATE).")
    if "last quarter" in q or "previous quarter" in q:
        lines.append("- Time: last quarter → date_trunc('quarter', CURRENT_DATE - INTERVAL '3 months').")
    if "this quarter" in q or "current quarter" in q:
        lines.append("- Time: current quarter → date_trunc('quarter', CURRENT_DATE).")
    if "last year" in q or "previous year" in q:
        lines.append("- Time: last year → date_trunc('year', CURRENT_DATE - INTERVAL '1 year') through date_trunc('year', CURRENT_DATE).")
    if any(k in q for k in ("this year", "current year")):
        lines.append("- Time: this year → ≥ date_trunc('year', CURRENT_DATE).")
    if "rolling 12" in q or "last 12 months" in q or "ttm" in q:
        lines.append("- Time: rolling 12 months → ≥ CURRENT_DATE - INTERVAL '12 months'.")
    if "monthly" in q or "by month" in q:
        lines.append("- Monthly bucketing: date_trunc('month', parsed_date) AS Month, output 'YYYY-MM'.")

    # SAT-specific hints
    sat_triggers = ("sat ", "cfdi", "inbound document", "sat document", "sat invoice", "payment complement")
    if any(k in q for k in sat_triggers) or re.search(r"\bsat\b", q):
        lines.append(
            "- SAT CONTEXT: Use `sat_documents` table. Key date column: received_at (arrival), fecha (invoice date).\n"
            "  supplier_rfc, supplier_name, receiver_rfc, total, subtotal, doc_type, status.\n"
            "  Example: SELECT supplier_name, COUNT(*) AS docs, SUM(total) AS total_amount FROM sat_documents GROUP BY supplier_name ORDER BY docs DESC LIMIT 10;"
        )

    if not lines:
        return ""
    return "══ QUERY HINTS ══\n" + "\n".join(lines)


def _infer_period_blurb(question: str, days: int) -> str:
    q = question.lower()
    if "last year" in q or "previous year" in q:
        return "Interpreted period: prior calendar year"
    if "this year" in q or "ytd" in q or "year to date" in q:
        return "Interpreted period: year-to-date"
    if "last quarter" in q:
        return "Interpreted period: previous quarter"
    if "this quarter" in q or "current quarter" in q:
        return "Interpreted period: current quarter"
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*months?\b", q)
    if m:
        return f"Interpreted period: last {m.group(1)} month(s)"
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*days?\b", q)
    if m:
        return f"Interpreted period: last {m.group(1)} day(s)"
    if days:
        return f"Interpreted period: last {days} day(s)"
    return ""


def _format_conversation_history(history: List[Dict[str, Any]]) -> str:
    if not history:
        return "No previous conversation."
    chunks = []
    for msg in history:
        role = (msg.get("role") or "unknown").upper()
        content = (msg.get("content") or "").strip()
        sql = (msg.get("sql") or "").strip()
        if role == "ASSISTANT" and sql:
            chunks.append(f"{role}: {content}\n[LAST_EXECUTED_SQL]\n{sql[:2000]}")
        else:
            chunks.append(f"{role}: {content}")
    return "\n".join(chunks)


# ═══════════════════════════════════════════════════════════════════════
# SMART EXECUTION — Stage 10
# ═══════════════════════════════════════════════════════════════════════

def _determine_execution_strategy(sql: str, question: str) -> str:
    """
    Determine how to execute the query:
    - 'direct': aggregation/grouped query → run as-is, return all rows
    - 'top_n': user asked for top N → apply LIMIT if not already present
    - 'bounded_scan': raw row scan, add safety LIMIT 1000
    - 'summary_needed': potentially huge dataset → generate summary query
    """
    if _is_aggregation_query(sql):
        return "direct"
    top_n = _extract_top_n(question)
    if top_n:
        return "top_n"
    q = question.lower()
    if any(k in q for k in ("all ", "every ", "full list", "show me all", "list all", "everything")):
        return "bounded_scan"
    return "bounded_scan"


def _apply_execution_strategy(sql: str, strategy: str, question: str) -> str:
    """Apply the execution strategy to the SQL."""
    if strategy == "direct":
        return sql  # No limit on aggregation queries
    if strategy == "top_n":
        if not _has_explicit_limit(sql):
            top_n = _extract_top_n(question) or 100
            return sql.rstrip(";").strip() + f" LIMIT {top_n}"
        return sql
    if strategy == "bounded_scan":
        if not _has_explicit_limit(sql) and not _is_aggregation_query(sql):
            return sql.rstrip(";").strip() + " LIMIT 1000"
        return sql
    return sql


# ═══════════════════════════════════════════════════════════════════════
# MULTI-CHART GENERATION — Stage 12/13
# ═══════════════════════════════════════════════════════════════════════

def _detect_column_types(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """Detect column types: 'numeric', 'date', 'category'."""
    if not rows:
        return {}
    sample = rows[0]
    types: Dict[str, str] = {}
    for k, v in sample.items():
        import decimal
        if isinstance(v, (int, float, decimal.Decimal)):
            types[k] = "numeric"
        elif isinstance(v, str):
            # Check if it looks like a date
            if re.match(r"^\d{4}-\d{2}", str(v)):
                types[k] = "date"
            elif re.match(r"^\d+\.?\d*$", str(v).replace(",", "")):
                types[k] = "numeric"
            else:
                types[k] = "category"
        else:
            types[k] = "category"
    return types


def _generate_multi_charts(
    rows: List[Dict[str, Any]],
    question: str,
    domain: str,
) -> List[Dict[str, Any]]:
    """
    Stage 12/13: Auto Visualization + Multi-Visualization Output.
    Generate 1-3 chart specs from the query results.
    """
    if not rows:
        return []

    col_types = _detect_column_types(rows)
    numeric_cols = [k for k, t in col_types.items() if t == "numeric"]
    date_cols = [k for k, t in col_types.items() if t == "date"]
    cat_cols = [k for k, t in col_types.items() if t == "category"]

    q = question.lower()
    charts: List[Dict[str, Any]] = []

    # ── Primary chart ──
    primary_type = "bar"  # default
    if date_cols or any(w in q for w in ("trend", "monthly", "over time", "time series", "by month", "timeline", "quarterly", "weekly", "year")):
        primary_type = "line"
    elif any(w in q for w in ("share", "distribution", "breakdown", "portion", "pie", "contribution")) and 2 <= len(rows) <= 10:
        primary_type = "pie"
    elif len(cat_cols) > 0 and len(rows) > 20:
        primary_type = "line"  # many data points → line is cleaner

    if numeric_cols and (cat_cols or date_cols):
        x_key = date_cols[0] if date_cols else (cat_cols[0] if cat_cols else list(rows[0].keys())[0])
        primary_chart = {
            "chart_type": primary_type,
            "title": question[:70],
            "data": rows,
            "x_key": x_key,
            "y_keys": numeric_cols[:3],
            "period_info": _infer_period_blurb(question, 30),
        }
        charts.append(primary_chart)

    # ── Secondary chart — add contrast ──
    if len(rows) >= 2 and numeric_cols:
        if primary_type == "line" and len(rows) <= 20 and cat_cols:
            # Add bar for comparison
            charts.append({
                "chart_type": "bar",
                "title": f"Comparison: {question[:50]}",
                "data": rows,
            })
        elif primary_type == "bar" and len(rows) <= 8 and numeric_cols:
            # Add pie for share view
            charts.append({
                "chart_type": "pie",
                "title": f"Share: {cat_cols[0] if cat_cols else 'Distribution'} — {numeric_cols[0] if numeric_cols else ''}",
                "data": rows,
            })

    # If no chart could be determined but there's data, return a bar
    if not charts and rows and len(rows) > 0:
        keys = list(rows[0].keys())
        if len(keys) >= 2:
            charts.append({
                "chart_type": "bar",
                "title": question[:70],
                "data": rows,
            })

    return charts[:3]  # max 3 charts


# ═══════════════════════════════════════════════════════════════════════
# AGENT STATE
# ═══════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    question: str
    conversation_history: List[Dict[str, Any]]
    dashboard_context: str
    days: int
    time_scope: str

    # Stage 2/3: Domain + Schema
    domain: str
    selected_tables: List[str]
    schema_text: str
    top_views: List[str]
    rag_context: str

    # Stage 3: SQL
    generated_sql: str
    checked_sql: str

    # Stage 5: Execution
    execution_strategy: str
    execution_result: Dict[str, Any]
    final_sql: str
    final_data: List[Dict[str, Any]]
    retry_count: int
    retry_errors: Annotated[List[str], operator.add]
    zero_rows_retried: bool

    # Stage 6: Answer + Insights
    final_answer: str
    confidence: str
    confidence_note: str
    kpis: List[Dict[str, Any]]
    insights: List[str]

    # Stage 7: Visualization
    charts: List[Dict[str, Any]]
    chart_policy: Optional[str]

    node_log: Annotated[List[str], operator.add]


# ═══════════════════════════════════════════════════════════════════════
# INTELLIGENT PLANNER
# ═══════════════════════════════════════════════════════════════════════

class IntelligentPlanner:
    """
    8-stage AI Data Analyst pipeline:
    1. domain_classify  — fast rule-based domain detection
    2. select_schema    — domain → tables → ranked columns (no full schema dump)
    3. build_context    — join hints + RAG
    4. generate_sql     — SQL generation with focused context
    5. check_sql        — SQL validation + fix
    6. smart_execute    — adaptive execution (no dumb limits on aggregations)
    7. generate_answer  — AI analyst summary + KPIs + insights
    8. auto_visualize   — multiple chart specs
    """

    def __init__(self, db: Session, api_key: str):
        self.db = db
        self.api_key = api_key
        self.llm_sql = ChatOpenAI(
            api_key=api_key,
            model=LANGGRAPH_SQL_MODEL,
            **langchain_openai_temperature_kwargs(LANGGRAPH_SQL_MODEL, 0.0),
            **langchain_openai_limit_kwargs(LANGGRAPH_SQL_MODEL, max(512, LANGGRAPH_SQL_MAX_TOKENS)),
        )
        self.llm_answer = ChatOpenAI(
            api_key=api_key,
            model=LANGGRAPH_ANSWER_MODEL,
            **langchain_openai_temperature_kwargs(LANGGRAPH_ANSWER_MODEL, 0.2),
            **langchain_openai_limit_kwargs(LANGGRAPH_ANSWER_MODEL, max(256, LANGGRAPH_ANSWER_MAX_TOKENS)),
        )

    # ── Stage 1+2: Domain Classify ───────────────────────────────────
    def domain_classify(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: domain_classify")
        from .explicit_table_sql import strip_generative_client_routing_block
        clean = strip_generative_client_routing_block(state["question"])
        domain = _classify_domain(clean)
        logger.info("[planner] domain=%s", domain)
        return {"domain": domain, "node_log": [f"domain_classify:{domain}"]}

    # ── Stage 3+4+5: Select Schema ───────────────────────────────────
    def select_schema(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: select_schema")
        from .explicit_table_sql import extract_explicit_table_identifiers, strip_generative_client_routing_block
        clean = strip_generative_client_routing_block(state["question"])

        # Explicit table names take priority (e.g., user mentions EKKO, VBRK)
        explicit = extract_explicit_table_identifiers(clean)
        if explicit:
            table_names = [_resolve_table_key(t) for t in explicit if _resolve_table_key(t)]
            # Expand with related tables
            domain_extras = DOMAIN_TABLE_MAP.get(state["domain"], DOMAIN_TABLE_MAP["general"])
            for t in domain_extras.get("support", [])[:3]:
                key = _resolve_table_key(t)
                if key and key not in table_names:
                    table_names.append(key)
        else:
            table_names = _select_tables_for_domain(state["domain"], clean, max_tables=8)

        table_names = [t for t in table_names if t][:10]
        schema_text, resolved = _build_schema_text(table_names, clean)

        # Build join hints (Stage 7: Relationship Graph)
        join_hints = _get_join_hints(resolved)
        rag_parts = []
        dc = (state.get("dashboard_context") or "").strip()
        if dc:
            rag_parts.append("[DASHBOARD CONTEXT]\n" + dc[:6000])
        if join_hints:
            rag_parts.append("══ KNOWN JOIN KEYS ══\n" + join_hints)
        rag = "\n\n".join(rag_parts)

        logger.info("[planner] selected tables: %s", resolved)
        return {
            "selected_tables": resolved,
            "schema_text": schema_text,
            "top_views": resolved,
            "rag_context": rag,
            "node_log": [f"select_schema:{len(resolved)}_tables"],
        }

    # ── Stage 8: Generate SQL ────────────────────────────────────────
    def generate_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: generate_sql")
        retry_guidance = ""
        if state.get("retry_count", 0) > 0 and state.get("retry_errors"):
            retry_guidance = "\n\n══ PREVIOUS ERRORS — do NOT repeat ══\n" + "\n".join(state["retry_errors"])

        system_prompt = f"""You are a senior SQL expert for an SAP ERP / PostgreSQL system.
Write ONE valid SQL SELECT statement answering the user's question.
{ERP_SQL_RULES}
Output ONLY the SQL — no explanation, no markdown fences, no semicolons at end.
IMPORTANT: Do NOT add LIMIT unless the user explicitly asked for top N. The execution layer handles result sizing."""

        rag = (state.get("rag_context") or "").strip()
        time_hints = _build_time_hints(state["question"], state.get("days", 30))
        hist_txt = _format_conversation_history(state.get("conversation_history") or [])
        follow_block = ""
        if "LAST_EXECUTED_SQL" in hist_txt:
            follow_block = "\n\n══ FOLLOW-UP: prefer editing the last SQL rather than rebuilding from scratch ══"

        user_prompt = f"""[SCHEMA — {len(state.get('selected_tables', []))} tables selected based on your question]
{state.get('schema_text', '')}

[DOMAIN: {state.get('domain', 'general').upper()}]

{f'[RAG CONTEXT]{chr(10)}{rag}' if rag else ''}

{time_hints}

[CONVERSATION HISTORY]
{hist_txt}{follow_block}

[QUESTION]
{state['question']}
{retry_guidance}"""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        sql = _extract_sql(response.content)
        logger.info("[planner] generated SQL length=%d", len(sql))
        return {"generated_sql": sql, "node_log": ["generate_sql"]}

    # ── Stage 9: Check SQL ───────────────────────────────────────────
    def check_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: check_sql")
        system_prompt = f"""You are a SQL reviewer for SAP/PostgreSQL.
Fix bugs without changing intent or scope.
Rules:
- NEVER change table names or remove valid JOINs.
- PostgreSQL: uppercase table names MUST be quoted ("VBRK"). SAP column names are lowercase.
- Do NOT add LIMIT unless user asked for top N — let execution layer handle sizing.
{ERP_SQL_RULES}
Output ONLY the corrected SQL."""

        rag = (state.get("rag_context") or "").strip()
        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}

{f'[CONTEXT]{chr(10)}{rag}' if rag else ''}

[SQL TO REVIEW]
{state.get('generated_sql', '')}"""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        checked = _extract_sql(response.content)
        return {"checked_sql": checked, "node_log": ["check_sql"]}

    # ── Stage 10: Smart Execute ──────────────────────────────────────
    def smart_execute(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: smart_execute")
        raw_sql = _take_first_sql_statement(
            state.get("checked_sql") or state.get("generated_sql") or ""
        )

        readonly_err = _validate_readonly_sql(raw_sql)
        if readonly_err:
            return {
                "execution_result": {"error": readonly_err, "data": [], "row_count": 0},
                "final_sql": None,
                "final_data": [],
                "execution_strategy": "blocked",
                "node_log": ["smart_execute_blocked"],
            }

        # Determine strategy
        strategy = _determine_execution_strategy(raw_sql, state["question"])
        sql = _apply_execution_strategy(raw_sql, strategy, state["question"])
        logger.info("[planner] execution strategy=%s", strategy)

        # Apply SQL sanitizers
        try:
            from .sap_sql_agent import _quote_catalog_sql_tables
            sql = _quote_catalog_sql_tables(sql)
        except Exception:
            pass
        try:
            from .sql_generation_sanitizers import (
                prepare_sql_for_sqlalchemy_text_execution as _prep,
                sanitize_generated_sap_sql as _sanitize,
            )
            sql = _sanitize(sql, state.get("question"))
            sql = _prep(sql)
        except Exception:
            pass

        result_data: List[Dict[str, Any]] = []
        error_msg = ""
        warnings: List[str] = []

        try:
            result = self.db.execute(text(sql))
            result_data = [dict(row) for row in result.mappings().all()]
        except Exception as e:
            error_msg = str(e)
            try:
                self.db.rollback()
            except Exception:
                pass

        if not error_msg and strategy == "bounded_scan" and len(result_data) >= 1000:
            warnings.append("Results capped at 1000 rows for row-scan queries. The data may be truncated — consider adding aggregation for complete totals.")

        execution_result = {
            "error": error_msg,
            "data": result_data,
            "row_count": len(result_data),
            "warnings": warnings,
        }
        return {
            "execution_result": execution_result,
            "execution_strategy": strategy,
            "final_sql": None if error_msg else sql,
            "final_data": [] if error_msg else result_data,
            "node_log": [f"smart_execute:{strategy}:{len(result_data)}_rows"],
        }

    # ── Error Recovery ───────────────────────────────────────────────
    def error_recovery(self, state: AgentState) -> Dict[str, Any]:
        attempt = state.get("retry_count", 0) + 1
        err_msg = (state.get("execution_result") or {}).get("error", "unknown error")
        failed_sql = state.get("checked_sql") or state.get("generated_sql")
        logger.info("[planner] node: error_recovery attempt=%d error=%s", attempt, err_msg[:120])

        system_prompt = f"""You are a SQL debugger for SAP/PostgreSQL.
Fix the SQL to eliminate the error below.
- PostgreSQL: unquoted identifiers fold to lowercase. Double-quote uppercase names: "VBRK", "EKKO".
- SAP column names are almost always lowercase: vbeln, netwr, fkdat.
{ERP_SQL_RULES}
Output ONLY the corrected SQL."""

        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}

[FAILED SQL]
{failed_sql}

[DB ERROR]
{err_msg}

Fix the SQL."""
        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        fixed = _extract_sql(response.content)
        return {
            "checked_sql": fixed,
            "generated_sql": fixed,
            "retry_count": attempt,
            "retry_errors": [f"Attempt {attempt}: {err_msg}"],
            "node_log": ["error_recovery"],
        }

    # ── Zero Rows Recovery ───────────────────────────────────────────
    def zero_rows_recovery(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: zero_rows_recovery")
        system_prompt = f"""A query returned 0 rows. Widen filters or relax conditions.
Common causes: date range too narrow, filter value misspelled, wrong join direction.
{ERP_SQL_RULES}
Output ONLY the corrected SQL."""

        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}

[ZERO-ROW SQL]
{state.get('checked_sql') or state.get('generated_sql')}

Widen date filters or remove overly specific filters."""
        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        fixed = _extract_sql(response.content)
        return {
            "generated_sql": fixed,
            "checked_sql": fixed,
            "zero_rows_retried": True,
            "node_log": ["zero_rows_recovery"],
        }

    # ── Stage 11: Generate Answer + Insights ────────────────────────
    def generate_answer(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: generate_answer")
        rows = state.get("final_data", [])

        if not rows:
            err = (state.get("execution_result") or {}).get("error")
            msg = f"Could not retrieve data: {err}" if err else "No matching records found. Try widening your filters or rephrasing your question."
            return {
                "final_answer": msg,
                "confidence": "low",
                "confidence_note": "0 rows returned",
                "kpis": [],
                "insights": [],
                "node_log": ["generate_answer_no_data"],
            }

        sample_n = min(80, len(rows))
        sample = json.dumps(rows[:sample_n], default=str)
        exec_ws = (state.get("execution_result") or {}).get("warnings") or []
        warn_block = ("\n[EXECUTION NOTES]\n" + "\n".join(exec_ws)) if exec_ws else ""

        system_prompt = """You are a senior business intelligence analyst for an ERP system.
Analyse the query results and respond with a JSON object ONLY (no extra text):
{
  "summary": "2-4 sentence plain-English executive summary. Lead with the most important number. Be specific — include actual values. Use currency symbols where appropriate.",
  "kpis": [{"label": "string", "value": "string", "unit": "string (optional)"}],
  "insights": ["finding 1", "finding 2", "finding 3"],
  "recommendations": ["action 1", "action 2"]
}
Rules:
- summary: precise, data-driven, no technical jargon (no SQL, columns, tables)
- kpis: 2-4 key metrics extracted or calculated from the data (totals, averages, top values)
- insights: 2-3 patterns, trends, or anomalies noticed in the data
- recommendations: 1-2 actionable business suggestions based on the findings
- If EXECUTION NOTES mention truncation, qualify figures as "based on sample"
"""
        dc = (state.get("dashboard_context") or "").strip()
        user_prompt = f"""[QUESTION]
{state['question']}
[DOMAIN: {state.get('domain', '').upper()}]
{f'[CONTEXT]{chr(10)}{dc[:3000]}' if dc else ''}
{warn_block}
[DATA — {len(rows)} row(s), sample of {sample_n}]
{sample}"""

        try:
            response = self.llm_answer.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            raw = (response.content or "").strip()
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group())
                summary = parsed.get("summary", "")
                kpis = parsed.get("kpis", [])
                insights = parsed.get("insights", [])
            else:
                summary = raw
                kpis = []
                insights = []
        except Exception as e:
            logger.warning("[planner] generate_answer JSON parse failed: %s", e)
            summary = f"Query returned {len(rows)} row(s)."
            kpis = []
            insights = []

        if not summary:
            summary = f"The query returned **{len(rows)}** row(s). See the table and charts below for details."

        conf = "medium" if exec_ws else "high"
        return {
            "final_answer": summary,
            "kpis": kpis,
            "insights": insights,
            "confidence": conf,
            "confidence_note": "See warnings — results may be sampled." if exec_ws else "",
            "node_log": ["generate_answer"],
        }

    # ── Stage 12/13: Auto Visualize ──────────────────────────────────
    def auto_visualize(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[planner] node: auto_visualize")
        rows = state.get("final_data", [])
        domain = state.get("domain", "general")
        charts = _generate_multi_charts(rows, state.get("question", ""), domain)
        policy = charts[0]["chart_type"] if charts else "table"
        logger.info("[planner] generated %d chart(s), primary=%s", len(charts), policy)
        return {
            "charts": charts,
            "chart_policy": policy,
            "node_log": [f"auto_visualize:{len(charts)}_charts"],
        }


# ═══════════════════════════════════════════════════════════════════════
# GRAPH BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _route_after_execute(state: AgentState) -> str:
    err = (state.get("execution_result") or {}).get("error", "")
    rows = len(state.get("final_data", []))

    if err:
        el = err.lower()
        if any(k in el for k in ("read-only", "forbidden statement", "only select")):
            return "generate_answer"
        if state.get("retry_count", 0) < 3:
            return "error_recovery"
        return "generate_answer"

    if rows == 0 and not state.get("zero_rows_retried", False):
        return "zero_rows_recovery"

    return "auto_visualize"


def _build_intelligent_graph(planner: IntelligentPlanner) -> Any:
    g = StateGraph(AgentState)
    g.add_node("domain_classify", planner.domain_classify)
    g.add_node("select_schema", planner.select_schema)
    g.add_node("generate_sql", planner.generate_sql)
    g.add_node("check_sql", planner.check_sql)
    g.add_node("smart_execute", planner.smart_execute)
    g.add_node("error_recovery", planner.error_recovery)
    g.add_node("zero_rows_recovery", planner.zero_rows_recovery)
    g.add_node("auto_visualize", planner.auto_visualize)
    g.add_node("generate_answer", planner.generate_answer)

    g.add_edge(START, "domain_classify")
    g.add_edge("domain_classify", "select_schema")
    g.add_edge("select_schema", "generate_sql")
    g.add_edge("generate_sql", "check_sql")
    g.add_edge("check_sql", "smart_execute")

    g.add_conditional_edges(
        "smart_execute",
        _route_after_execute,
        {
            "error_recovery": "error_recovery",
            "zero_rows_recovery": "zero_rows_recovery",
            "auto_visualize": "auto_visualize",
            "generate_answer": "generate_answer",
        },
    )
    g.add_edge("error_recovery", "smart_execute")
    g.add_edge("zero_rows_recovery", "smart_execute")
    g.add_edge("auto_visualize", "generate_answer")
    g.add_edge("generate_answer", END)

    return g.compile()


# ═══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def _run_intelligent_pipeline(
    db: Session,
    api_key: str,
    query: str,
    conversation_history: list,
    dashboard_context: str,
    days_int: int,
    time_scope: str,
) -> Dict[str, Any]:
    t0 = time.time()
    from .ai_query_accuracy import build_query_telemetry, log_query_telemetry

    planner = IntelligentPlanner(db, api_key)
    app = _build_intelligent_graph(planner)

    initial_state: AgentState = {
        "question": query,
        "conversation_history": conversation_history or [],
        "dashboard_context": (dashboard_context or "").strip()[:10000],
        "days": max(1, min(365, days_int)),
        "time_scope": (time_scope or "current").strip(),
        "domain": "general",
        "selected_tables": [],
        "schema_text": "",
        "top_views": [],
        "rag_context": "",
        "generated_sql": "",
        "checked_sql": "",
        "execution_strategy": "",
        "execution_result": {},
        "final_sql": "",
        "final_data": [],
        "retry_count": 0,
        "retry_errors": [],
        "zero_rows_retried": False,
        "final_answer": "",
        "confidence": "medium",
        "confidence_note": "",
        "kpis": [],
        "insights": [],
        "charts": [],
        "chart_policy": None,
        "node_log": [],
    }

    result = app.invoke(initial_state)

    def _to_json_safe(obj: Any) -> Any:
        try:
            return json.loads(json.dumps(obj, default=str))
        except Exception:
            return obj if not isinstance(obj, list) else []

    safe_data = _to_json_safe(result.get("final_data") or [])
    charts = _to_json_safe(result.get("charts") or [])
    kpis = result.get("kpis") or []
    insights = result.get("insights") or []

    exec_meta = result.get("execution_result") or {}
    exec_warnings = list(exec_meta.get("warnings") or [])
    retries = result.get("retry_errors") or []
    conf = result.get("confidence", "medium")
    if exec_meta.get("error"):
        conf = "low"
    elif len(retries) >= 2:
        conf = "low"

    reply_text = (result.get("final_answer") or "").strip()
    if not reply_text:
        reply_text = (
            "Query complete. See the table and charts below."
            if safe_data
            else "No data found. Try rephrasing or widening your filters."
        )

    # Build reply with insights appended
    if insights:
        reply_text += "\n\n**Key Insights:**\n" + "\n".join(f"- {i}" for i in insights[:3])

    payload = {
        "reply": reply_text,
        "action": "new",
        "reason": "intelligent_pipeline",
        "sql_path_reason": "intelligent_pipeline",
        "domain": result.get("domain", "general"),
        "schema_tables": result.get("top_views") or [],
        "sql": result.get("final_sql", ""),
        "rows_preview": safe_data,
        "charts": charts,
        "kpis": kpis,
        "insights": insights,
        "time_scope": time_scope or "current",
        "date_range": {},
        "period_info": _infer_period_blurb(query or "", days_int),
        "errors": retries,
        "warnings": exec_warnings,
        "confidence": conf,
        "confidence_note": (result.get("confidence_note") or "").strip(),
        "node_log": result.get("node_log", []),
        "execution_strategy": result.get("execution_strategy", ""),
    }

    elapsed_ms = int((time.time() - t0) * 1000)
    try:
        tel = build_query_telemetry(
            question=query or "",
            pipeline="intelligent_pipeline",
            reason="intelligent_pipeline",
            sql=str(payload.get("sql") or ""),
            preview_row_count=len(safe_data),
            total_ms=elapsed_ms,
            sql_repair_count=len(retries),
            node_log_count=len(result.get("node_log") or []),
            execution_error=(exec_meta.get("error") if isinstance(exec_meta, dict) else None),
            extra={"confidence": conf, "domain": result.get("domain", "")},
        )
        payload["query_telemetry"] = tel
        log_query_telemetry(tel, question_snip=query or "")
    except Exception:
        pass

    logger.info("[planner] intelligent_pipeline done: %dms, %d rows, %d charts, domain=%s",
                elapsed_ms, len(safe_data), len(charts), result.get("domain", ""))
    return payload


def run_planner(
    db: Session,
    api_key: str,
    query: str,
    conversation_history: list = None,
    *,
    dashboard_context: str = "",
    days: int = 30,
    time_scope: str = "current",
) -> Dict[str, Any]:
    """
    Main entry point. Runs fast-path resolvers first (operational + catalog),
    then falls back to the intelligent multi-stage pipeline.
    """
    try:
        days_int = int(days)
    except (TypeError, ValueError):
        days_int = 30

    # ── Fast path 1: Operational Zodiac queries ──────────────────────
    try:
        from .dashboard_query_router import (
            _try_operational, _try_sql_catalog, _build_payload,
            _serialize_rows, _execute_sql
        )
        from ..config.config import USE_SAP_DB_FOR_AI

        if not USE_SAP_DB_FOR_AI:
            op_result = _try_operational(
                db, query or "",
                time_scope=time_scope or "current",
                days=days_int,
                api_key=api_key,
            )
            if op_result:
                logger.info("[planner] fast-path: operational match")
                return op_result
    except Exception as e:
        logger.debug("[planner] operational fast-path skipped: %s", e)

    # ── Fast path 2: SQL catalog patterns ──────────────────────────────────────────────────────────────────────────────────────────────
    try:
        from .dashboard_query_router import _try_sql_catalog, _build_payload
        catalog_result = _try_sql_catalog(db, query or "")
        if catalog_result:
            sql, rows, tables = catalog_result
            logger.info("[planner] fast-path: catalog match")
            return _build_payload(
                query=query or "",
                pipeline="sql_catalog",
                reason="sql_catalog",
                sql=sql,
                rows=rows,
                reply=f"Found **{len(rows)}** row(s) matching your query.",
                schema_tables=tables,
                time_scope=time_scope or "current",
                period_info=_infer_period_blurb(query or "", days_int),
                confidence="high" if rows else "medium",
                charts=_generate_multi_charts(rows, query or "", "general") if rows else [],
                elapsed_ms=0,
            )
    except Exception as e:
        logger.debug("[planner] catalog fast-path skipped: %s", e)

    # ── Primary: Intelligent multi-stage pipeline ────────────────────────────────────────
    return _run_intelligent_pipeline(
        db=db,
        api_key=api_key,
        query=query or "",
        conversation_history=conversation_history or [],
        dashboard_context=dashboard_context or "",
        days_int=days_int,
        time_scope=time_scope or "current",
    )
