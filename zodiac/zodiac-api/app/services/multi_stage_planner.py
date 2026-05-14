from __future__ import annotations

import logging
import json
import operator
import re
from typing import Any, Dict, List, Optional, Tuple, Annotated, TypedDict

from sqlalchemy.orm import Session
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from .schema_intelligence import ColumnProfile, schema_intelligence, TableProfile
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
# from .sap_sql_precision_validator import _validate_sql_candidate

logger = logging.getLogger("zodiac-api.multi_stage_planner")

# ERP RULES (Ported from reference architecture)
ERP_SQL_RULES = """
══ ERP T-SQL RULES — ALL MANDATORY ══

1. Use ONLY column names that appear in the provided schema — never guess or invent columns.
2. DATE ARITHMETIC (critical for time-range queries)
   - Date columns are often strings or datetimes — always CAST to date before comparison.
   - SAP date fields may be stored as YYYYMMDD text (example: fkdat). In PostgreSQL, parse with to_date(col, 'YYYYMMDD') before filtering/grouping.
   - For "monthly trend", bucket with date_trunc('month', parsed_date) and output YYYY-MM.
3. JOINS (always explicit — direction depends on the question)
   - Normal ranking / top products / invoices (sales rows drive the grain): INNER JOIN or LEFT JOIN.
   - NEVER use implicit cross joins (missing ON clause).
4. RESULT SIZE
   - Non-aggregate SELECT → MUST include TOP (N) or LIMIT N.
   - "Top 10" questions → LIMIT 10 ... ORDER BY metric DESC.
5. NULL SAFETY
   - Wrap nullable numeric cols.
6. FORMAT
   - No semicolons at end.
   - Always alias all aggregates: SUM(x) AS TotalX, COUNT(*) AS TxnCount.
   - Always include ORDER BY for trend/ranking queries.
   - Column aliases must not contain spaces (use CamelCase or underscore).
   - **Table identifiers:** Match the SCHEMA exactly. Many SAP replicas use lowercase physical names (`vbrk`, `vbrp`, `makt`). Unquoted lowercase is correct there. `"VBRP"` is case-sensitive uppercase and **fails** if the real table is `vbrp` — never invent casing; copy from the schema list.
   - When the schema snapshot shows uppercase quoted names only, quote those identifiers consistently with the snapshot.
   - VERY IMPORTANT: SAP **columns** in PostgreSQL are almost always lowercase (e.g. vbrk.vbeln, vbrp.netwr, ekko.ebeln when using lowercase tables). Do NOT use uppercase column names.
7. GROUPING AND AGGREGATION (CRITICAL)
   - Every non-aggregate SELECT column must appear in GROUP BY.
   - When asked for "Top N vendors/customers/products" or similar ranking, you MUST group by the entity ID/Name and aggregate the metric (e.g., SUM(netwr) AS TotalAmount). DO NOT select all columns and just append LIMIT.
   - Example for Top 5 Vendors by Purchase Order Value:
     SELECT "EKKO".lifnr AS Vendor, SUM("EKPO".netwr) AS TotalOrderValue FROM "EKKO" INNER JOIN "EKPO" ON "EKKO".ebeln = "EKPO".ebeln GROUP BY "EKKO".lifnr ORDER BY TotalOrderValue DESC LIMIT 5
8. MASTER DATA FOR READABLE RESULTS (when user asks customers, vendors, materials, products, or industry context)
   - Include BOTH technical key AND description/name in SELECT when schema lists those columns.
   - Customers (sold-to / payer): JOIN "KNA1" ON "KNA1".kunnr = <customer key from fact table>; SELECT kunnr plus name1 (and brsch for industry if needed).
   - Materials: JOIN "MAKT" ON "MAKT".matnr = <material from lines> AND spras = 'E' (or appropriate language); SELECT matnr plus maktx.
   - Vendors: JOIN "LFA1" ON "LFA1".lifnr = <vendor from PO/header>.
9. NEVER generate DROP, DELETE, UPDATE, INSERT, ALTER statements. READ ONLY.
10. PLANT / SLOC: warehouse or plant filters often use werks (plant) and lgort (storage location) on MARD/LIPS/EKPO/VBRP — use columns from the schema only.
11. PRICING: SD header tables VBRK / VBAK expose knumv — join "KONV" ON "KONV".knumv = header.knumv; align line kposn with VBRP.posnr or VBAP.posnr when filtering item-level conditions.
12. FI-AR open items: customer secondary index "BSAD" links customers to financial docs — join "KNA1" on kunnr; tie to "BSEG"/"BKPF" via belnr (and bukrs/gjahr when present in schema) for full document context.
"""

# Related SAP tables pulled into the schema prompt when a seed table is chosen (improves joins & labels).
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
}


def _effective_schema_table_budget(question: str) -> int:
    """Widen schema context when the user implies joins / drill-down (bounded)."""
    q = (question or "").lower()
    complex_q = bool(
        re.search(r"\bjoin\b", q)
        or any(
            p in q
            for p in (
                "together with",
                "combined with",
                "drill down",
                "drill-down",
                "multiple tables",
                "cross-reference",
                "cross reference",
            )
        )
        or any(
            p in q
            for p in (
                "plant",
                "factory",
                "storage location",
                "by customer and",
                "by material and",
            )
        )
        or re.search(r"\bwerk\b", q)
        or re.search(r"\bsloc\b", q)
        or any(
            p in q
            for p in (
                "pricing",
                "condition record",
                "document flow",
                "schedule line",
                "schedule lines",
                "preceding document",
                "subsequent document",
                "open item",
                "open items",
                "receivable",
                "dunning",
                "cost center",
                "cost centre",
            )
        )
    )
    n = LANGGRAPH_MAX_SCHEMA_TABLES + (LANGGRAPH_SCHEMA_JOIN_BOOST if complex_q else 0)
    return max(4, min(LANGGRAPH_MAX_SCHEMA_TABLES_HARD_CAP, n))


def _expand_table_names(seed_names: List[str], max_tables: int) -> List[str]:
    """Breadth-first add related tables up to max_tables (preserves seed order)."""
    seen: List[str] = []
    for s in seed_names:
        u = (s or "").upper()
        if u and u not in seen and u in schema_intelligence.tables:
            seen.append(u)
    i = 0
    while i < len(seen) and len(seen) < max_tables:
        name = seen[i]
        i += 1
        for rel in _SAP_RELATED_TABLES.get(name, ()):
            if len(seen) >= max_tables:
                break
            ru = rel.upper()
            if ru not in seen and ru in schema_intelligence.tables:
                seen.append(ru)
    return seen[:max_tables]


def _prioritized_column_lines(t: TableProfile, max_cols: int) -> List[str]:
    """Wide SAP tables: surface keys, amounts, dates, and descriptions first."""
    cols = list(t.columns.values())

    def score(col: ColumnProfile) -> Tuple[int, str]:
        role = (getattr(col, "semantic_role", None) or "").lower()
        name_u = col.name.upper()
        s = 0
        if role == "key":
            s += 100
        elif role == "amount":
            s += 85
        elif role == "date":
            s += 75
        if name_u in ("NAME1", "NAME2", "MAKTX", "SPRAS", "WAERS", "WAERK", "MEINS"):
            s += 55
        if name_u.endswith("TXT") or name_u.endswith("_TXT"):
            s += 25
        return (-s, name_u)

    cols_sorted = sorted(cols, key=score)
    cap = max(12, max_cols)
    shown = cols_sorted[:cap]
    lines: List[str] = []
    for c in shown:
        role = getattr(c, "semantic_role", "") or ""
        role_tag = f" [{role}]" if role else ""
        lines.append(f"  {c.name} ({c.data_type}){role_tag}")
    if len(cols) > cap:
        lines.append(f"  … ({len(cols) - cap} more columns omitted for {t.name})")
    return lines


def _take_first_sql_statement(sql: str) -> str:
    """Execute only the first statement if the model emitted multiple (; injection guard)."""
    s = (sql or "").strip().rstrip(";")
    if ";" not in s:
        return s
    parts = [p.strip() for p in s.split(";") if p.strip()]
    return parts[0] if parts else s


def _needs_automatic_row_cap(sql: str) -> bool:
    """True when the query looks like an unbounded row scan (no LIMIT / GROUP BY / aggregates)."""
    if not sql or not sql.strip():
        return False
    if re.search(r"\bLIMIT\s+\d+", sql, re.I):
        return False
    if re.search(r"\bGROUP\s+BY\b", sql, re.I):
        return False
    if re.search(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", sql, re.I):
        return False
    return True


def _append_row_limit(sql: str, max_rows: int) -> str:
    if max_rows <= 0 or not sql:
        return sql
    s = sql.strip().rstrip(";")
    return f"{s} LIMIT {max_rows}"


_FORBIDDEN_WRITE_SQL = re.compile(
    r"\b("
    r"DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|"
    r"EXECUTE|CALL\b"
    r")\b|\bMERGE\s+INTO\b|\bCOPY\s+",
    re.I,
)


def _validate_readonly_sql(sql: str) -> Optional[str]:
    """Return error message if SQL is not a safe read-only query."""
    s = (sql or "").strip()
    if not s:
        return "Empty SQL."
    head = re.sub(r"^\s+", "", s)
    up = head.upper()
    if up.startswith("WITH"):
        if not re.search(r"\bSELECT\b", s, re.I):
            return "Only read-only WITH … SELECT is allowed."
    elif not up.startswith("SELECT"):
        return "Only SELECT (or WITH … SELECT) queries are allowed."
    if _FORBIDDEN_WRITE_SQL.search(s):
        return "Forbidden statement — read-only SELECT only."
    return None


def _extract_top_n_from_question(question: str) -> Optional[int]:
    for pat in (
        r"\btop\s+(\d+)\b",
        r"\bfirst\s+(\d+)\b",
        r"\bbottom\s+(\d+)\b",
        r"\blimit\s+to\s+(\d+)\b",
        r"\b(\d+)\s+(?:largest|biggest|highest)\b",
        r"\b(\d+)\s+(?:smallest|lowest)\b",
    ):
        m = re.search(pat, question or "", re.I)
        if m:
            try:
                n = int(m.group(1))
                return n if 1 <= n <= 10_000 else None
            except ValueError:
                return None
    return None


def _build_dynamic_question_hints(question: str, days: int) -> str:
    """Lightweight NL hints to steer SQL (dates, ranking) — no schema coupling."""
    q = question or ""
    lines: List[str] = []
    ql = q.lower()

    n = _extract_top_n_from_question(q)
    if n is not None:
        want_low = bool(
            re.search(r"\b(bottom|lowest|smallest|worst|least)\b", ql)
            or re.search(r"\b(\d+)\s+(?:smallest|lowest)\b", ql)
        )
        if want_low:
            lines.append(
                f"- Ranking: user wants the bottom/lowest side — ORDER BY the main metric ASC, LIMIT {n}."
            )
        else:
            lines.append(
                f"- Ranking: user asked for roughly TOP {n} — ORDER BY the main metric DESC, LIMIT {n}."
            )

    # Relative windows (PostgreSQL-oriented phrasing)
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:day|days)\b", ql)
    if m:
        lines.append(f"- Time: last {m.group(1)} day(s) → filter parsed SAP dates ≥ CURRENT_DATE - INTERVAL '{m.group(1)} days'.")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:week|weeks)\b", ql)
    if m:
        w = int(m.group(1))
        lines.append(f"- Time: last {w} week(s) → ≥ CURRENT_DATE - INTERVAL '{w * 7} days'.")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:month|months)\b", ql)
    if m:
        lines.append(f"- Time: last {m.group(1)} month(s) → ≥ CURRENT_DATE - INTERVAL '{m.group(1)} months'.")
    if "ytd" in ql or "year to date" in ql:
        lines.append("- Time: year-to-date → from date_trunc('year', CURRENT_DATE) through CURRENT_DATE.")
    if "this quarter" in ql or "current quarter" in ql:
        lines.append("- Time: current calendar quarter → date_trunc('quarter', CURRENT_DATE) bounds.")
    if "last quarter" in ql or "previous quarter" in ql:
        lines.append("- Time: previous calendar quarter → date_trunc on CURRENT_DATE - INTERVAL '3 months'.")
    if any(k in ql for k in ("this year", "current year", "calendar year to date")):
        lines.append("- Time: this calendar year → parsed dates ≥ date_trunc('year', CURRENT_DATE).")
    if any(k in ql for k in ("last year", "previous year", "prior year")):
        lines.append(
            "- Time: last calendar year → parsed dates >= date_trunc('year', CURRENT_DATE - INTERVAL '1 year') "
            "AND < date_trunc('year', CURRENT_DATE)."
        )
    if any(k in ql for k in ("rolling 12", "rolling twelve", "trailing twelve", "ttm", "last 12 months")):
        lines.append("- Time: rolling 12 months → ≥ CURRENT_DATE - INTERVAL '12 months'.")
    if "fiscal" in ql:
        lines.append("- If fiscal year applies, approximate with calendar year unless schema has fiscal period fields.")
    if any(k in ql for k in ("compare", "versus", " vs ")) or "comparison" in ql:
        lines.append(
            "- Comparison / vs: use two explicit date buckets or periods (e.g. subqueries or CASE) with clear labels in SELECT."
        )

    if days and ("recent" in ql or "dashboard" in ql or "default period" in ql):
        lines.append(f"- Dashboard context uses ~{days} day(s); align date filters if the question does not specify another range.")

    if not lines:
        return ""
    return "══ QUESTION-DERIVED HINTS (apply if consistent with schema) ══\n" + "\n".join(lines)


def _infer_period_blurb(question: str, days: int, time_scope: str) -> str:
    """Short UI/API summary of how the question's time intent was interpreted."""
    ql = (question or "").lower()
    bits: List[str] = []
    ts = (time_scope or "").strip().lower()
    if ts and ts not in ("current", ""):
        bits.append(f"scope={time_scope}")
    if any(k in ql for k in ("rolling 12", "trailing twelve", "ttm")) or "last 12 months" in ql:
        bits.append("rolling ~12 months")
    elif any(k in ql for k in ("last year", "previous year", "prior year")):
        bits.append("prior calendar year")
    elif any(k in ql for k in ("this year", "current year")) and "last year" not in ql:
        bits.append("current calendar year")
    elif "ytd" in ql or "year to date" in ql:
        bits.append("year-to-date")
    elif "this quarter" in ql or "current quarter" in ql:
        bits.append("current quarter")
    elif "last quarter" in ql or "previous quarter" in ql:
        bits.append("previous quarter")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:month|months)\b", ql)
    if m:
        bits.append(f"last {m.group(1)} month(s)")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(?:day|days)\b", ql)
    if m:
        bits.append(f"last {m.group(1)} day(s)")
    if days and ("recent" in ql or "dashboard" in ql or "default period" in ql):
        bits.append(f"dashboard ~{days} day window")
    if not bits:
        return ""
    return "Interpreted period: " + "; ".join(bits)


def _format_conversation_history_for_prompt(
    history: List[Dict[str, Any]],
    sql_snippet_max: int = 2800,
) -> str:
    """Include assistant sql in the transcript when the client sends it (follow-up accuracy)."""
    if not history:
        return "No previous conversation."
    chunks: List[str] = []
    for msg in history:
        role = (msg.get("role") or "unknown").upper()
        content = (msg.get("content") or "").strip()
        sql = (msg.get("sql") or "").strip()
        if role == "ASSISTANT" and sql:
            sq = sql[:sql_snippet_max]
            chunks.append(f"{role}: {content}\n[LAST_EXECUTED_SQL]\n{sq}")
        else:
            chunks.append(f"{role}: {content}")
    return "\n".join(chunks)


def _extract_sql(text: str) -> str:
    if not text:
        return ""
    # Try to find markdown fences
    fenced = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    # Otherwise just strip and return
    return text.strip()


def _build_monthly_billing_revenue_sql_if_applicable(question: str) -> str:
    """Deterministic fallback for monthly VBRK billing trend queries."""
    q = (question or "").lower()
    if "monthly" not in q:
        return ""
    if "billing" not in q and "revenue" not in q:
        return ""
    if "past year" not in q and "last year" not in q and "12 month" not in q:
        return ""

    # SAP extracts often store FKDAT as YYYYMMDD text; parse safely before filtering.
    return """
SELECT
  to_char(date_trunc('month', to_date("VBRK".fkdat, 'YYYYMMDD')), 'YYYY-MM') AS billing_month,
  SUM(COALESCE(CAST("VBRK".netwr AS numeric), 0)) AS total_billing_revenue,
  "VBRK".waerk AS currency
FROM "VBRK"
WHERE "VBRK".fkdat IS NOT NULL
  AND "VBRK".fkdat ~ '^[0-9]{8}$'
  AND to_date("VBRK".fkdat, 'YYYYMMDD') >= (CURRENT_DATE - INTERVAL '12 months')
GROUP BY date_trunc('month', to_date("VBRK".fkdat, 'YYYYMMDD')), "VBRK".waerk
ORDER BY billing_month
""".strip()

# State Schema
class AgentState(TypedDict):
    question: str
    date_context: str
    table_hint: Optional[str]
    user_date_range: Dict[str, str]

    top_views: List[str]
    schema_text: str

    sample_text: str

    generated_sql: str
    checked_sql: str
    execution_result: Dict[str, Any]
    retry_count: int
    retry_errors: Annotated[List[str], operator.add]
    zero_rows_retried: bool

    rag_context: str
    dashboard_context: str
    days: int
    time_scope: str

    final_answer: str
    final_data: List[Dict[str, Any]]
    final_sql: str
    confidence: str
    confidence_note: str
    
    node_log: Annotated[List[str], operator.add]
    chart_policy: Optional[str]
    conversation_history: List[Dict[str, Any]]

class LangGraphPlanner:
    def __init__(self, db: Session, api_key: str):
        self.db = db
        self.api_key = api_key
        sql_model = LANGGRAPH_SQL_MODEL
        ans_model = LANGGRAPH_ANSWER_MODEL
        logger.info("[langgraph] SQL model: %s | answer model: %s", sql_model, ans_model)
        # GPT-5 / o-series: use max_completion_tokens (not max_tokens) and API-safe temperature via helpers.
        self.llm_sql = ChatOpenAI(
            api_key=api_key,
            model=sql_model,
            **langchain_openai_temperature_kwargs(sql_model, 0.0),
            **langchain_openai_limit_kwargs(sql_model, max(512, LANGGRAPH_SQL_MAX_TOKENS)),
        )
        self.llm_answer = ChatOpenAI(
            api_key=api_key,
            model=ans_model,
            **langchain_openai_temperature_kwargs(ans_model, 0.2),
            **langchain_openai_limit_kwargs(ans_model, max(256, LANGGRAPH_ANSWER_MAX_TOKENS)),
        )

    def load_schema(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: load_schema")
        
        # Use schema_intelligence to resolve tables
        from app.services.explicit_table_sql import extract_explicit_table_identifiers, strip_generative_client_routing_block
        
        # 1. Strip the [ZODIAC_GENERATIVE_CLIENT_ROUTING] block first
        clean_query = strip_generative_client_routing_block(state["question"])
        
        # 2. Try to get explicit tables (like EKKO, EKPO)
        explicit_ids = extract_explicit_table_identifiers(clean_query)
        tables = []
        
        if explicit_ids:
            for t_name in explicit_ids:
                t_obj = schema_intelligence.tables.get(t_name) or schema_intelligence.tables.get(t_name.upper())
                if t_obj:
                    tables.append(t_obj)
                    
        # 3. If no explicit tables found, use semantic resolution
        if not tables:
            tables = schema_intelligence.resolve_entities(clean_query)
            
        if not tables:
            table_names = ["VBRK", "VBRP", "KNA1", "MARA"]
            tables = [schema_intelligence.tables.get(t) for t in table_names if t in schema_intelligence.tables]

        # Pull in related masters / line tables so the model sees join keys (KNA1, MAKT, …).
        seed_names = [t.name for t in tables if t]
        table_budget = _effective_schema_table_budget(clean_query)
        expanded_names = _expand_table_names(seed_names, table_budget)
        tables = [schema_intelligence.tables[n] for n in expanded_names if n in schema_intelligence.tables]

        schema_text_lines = []
        top_views = []
        for t in tables:
            if not t: continue
            top_views.append(t.name)
            cols = _prioritized_column_lines(t, LANGGRAPH_MAX_COLUMNS_PER_TABLE)
            schema_text_lines.append(f"\n{t.name}:")
            schema_text_lines.extend(cols)
            
        schema_text = "\n".join(schema_text_lines)
        return {
            "top_views": top_views,
            "schema_text": schema_text,
            "node_log": ["load_schema"]
        }

    def retrieve_context(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: retrieve_context")
        chunks: List[str] = []
        dc = (state.get("dashboard_context") or "").strip()
        if dc:
            chunks.append(
                "[DASHBOARD SNAPSHOT — use for filters, labels, and period hints when relevant]\n" + dc[:8000]
            )
        views = set(state.get("top_views") or [])
        hints: List[str] = []
        for edge in getattr(schema_intelligence, "join_graph", None) or []:
            if edge.source_table in views and edge.target_table in views:
                hints.append(
                    f'"{edge.source_table}".{edge.source_column.lower()} = '
                    f'"{edge.target_table}".{edge.target_column.lower()}'
                )
        if hints:
            chunks.append(
                "══ KNOWN JOIN KEYS (prefer these ON clauses when both tables appear in FROM) ══\n"
                + "\n".join(sorted(set(hints)))
            )
        # Prior SQL is already under [LAST_EXECUTED_SQL] in CONVERSATION HISTORY — omit here to save tokens.
        rag = "\n\n".join(chunks)
        return {"rag_context": rag, "node_log": ["retrieve_context"]}

    def generate_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: generate_sql")
        
        retry_guidance = ""
        if state.get("retry_count", 0) > 0 and state.get("retry_errors"):
            retry_guidance = f"\n\n══ PREVIOUS ERRORS — do NOT repeat these mistakes ══\n" + "\n".join(state["retry_errors"])

        system_prompt = f"""You are a SQL expert for an SAP ERP system.
Write ONE valid SQL SELECT statement that answers the user's question.
Use ONLY column names that appear in the provided schema — never guess or invent columns.
{ERP_SQL_RULES}
Output ONLY the SQL — no explanation, no markdown fences, no semicolons at end."""

        scope_lines: List[str] = []
        if state.get("time_scope"):
            scope_lines.append(f"time_scope: {state['time_scope']}")
        if state.get("days"):
            scope_lines.append(f"dashboard_recent_days: {state['days']}")
        scope_block = "\n".join(scope_lines) if scope_lines else "None."
        rag = (state.get("rag_context") or "").strip()
        rag_block = f"\n\n{rag}" if rag else ""
        dyn_hints = _build_dynamic_question_hints(state["question"], int(state.get("days") or 30))
        hints_block = f"\n\n{dyn_hints}" if dyn_hints else ""

        hist_txt = _format_conversation_history_for_prompt(state.get("conversation_history") or [])
        follow_block = ""
        if "LAST_EXECUTED_SQL" in hist_txt:
            follow_block = """
══ FOLLOW-UP (when [LAST_EXECUTED_SQL] appears above) ══
Prefer EDITING that query (filters, JOINs, GROUP BY, ORDER BY, LIMIT) to satisfy the new question.
Do not rebuild from unrelated tables unless the user clearly switched topics."""

        user_prompt = f"""[SCHEMA — ONLY use columns listed here]
{state.get('schema_text', '')}

[DATE / SCOPE HINTS]
{scope_block}{rag_block}{hints_block}

[CONVERSATION HISTORY]
{hist_txt}{follow_block}

[QUESTION]
{state['question']}
{retry_guidance}"""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        sql = _extract_sql(response.content)
        return {"generated_sql": sql, "node_log": ["generate_sql"]}

    def check_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: check_sql")
        # Perform both LLM-based check and deterministic validator check
        system_prompt = f"""You are a SQL code reviewer for SAP data.
Your job is to FIX BUGS without changing the intent or scope of the query.
══ ABSOLUTE DO-NOT-CHANGE RULES ══
1. NEVER change FROM table name or JOIN table name.
2. NEVER increase TOP N if the user asked for a specific number.
3. NEVER remove or change a JOIN that already has a valid ON clause.
4. PostgreSQL requires quotes for uppercase table names. You MUST quote tables like "EKKO", "EKPO" or PostgreSQL will convert them to lowercase and fail to find the table.
5. VERY IMPORTANT: In PostgreSQL, all SAP column names are LOWERCASE. You MUST use lowercase for all column names (e.g. "EKKO"."ebeln", "EKPO"."netwr").

{ERP_SQL_RULES}

Output ONLY the SQL — no explanation, no markdown fences."""

        rag = (state.get("rag_context") or "").strip()
        rag_block = f"\n\n{rag}" if rag else ""
        dyn_hints = _build_dynamic_question_hints(state["question"], int(state.get("days") or 30))
        hints_block = f"\n\n{dyn_hints}" if dyn_hints else ""
        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}{rag_block}{hints_block}

[SQL TO REVIEW]
{state.get('generated_sql', '')}"""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        checked_sql = _extract_sql(response.content)
        
        # Now run through deterministic validator
        # Note: In dashboard.py, _validate_sql_candidate is already called after the payload is returned.
        # So we skip running it here to avoid circular imports.
        # validation, blocking_detail = _validate_sql_candidate(self.db, state["question"], checked_sql)
        # if blocking_detail:
        #     logger.warning(f"[langgraph] deterministic validation blocking: {blocking_detail}")
            
        return {"checked_sql": checked_sql, "node_log": ["check_sql"]}

    def execute_sql(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: execute_sql")
        sql = _take_first_sql_statement(state.get("checked_sql") or state.get("generated_sql") or "")
        exec_warnings: List[str] = []
        auto_limit_applied = False

        readonly_err = _validate_readonly_sql(sql)
        if readonly_err:
            execution_result = {
                "error": readonly_err,
                "data": [],
                "row_count": 0,
                "warnings": [],
            }
            return {
                "execution_result": execution_result,
                "final_sql": None,
                "final_data": [],
                "node_log": ["execute_sql"],
            }

        if sql and LANGGRAPH_SELECT_ROW_CAP > 0 and _needs_automatic_row_cap(sql):
            sql = _append_row_limit(sql, LANGGRAPH_SELECT_ROW_CAP)
            auto_limit_applied = True
            logger.info(
                "[langgraph] applied automatic LIMIT %s for unbounded SELECT",
                LANGGRAPH_SELECT_ROW_CAP,
            )

        # Map LLM table ids to physical Postgres names (db_table_mapping.json: e.g. vbrp vs "VBRP").
        try:
            from .sap_sql_agent import _quote_catalog_sql_tables

            sql = _quote_catalog_sql_tables(sql)
        except Exception as _qct_err:
            logger.debug("[langgraph] _quote_catalog_sql_tables skipped: %s", _qct_err)
        try:
            from .sql_generation_sanitizers import (
                prepare_sql_for_sqlalchemy_text_execution as _prep_sql,
                sanitize_generated_sap_sql as _sanitize_sap,
            )
            sql = _sanitize_sap(sql, state.get("question"))
            sql = _prep_sql(sql)
        except Exception as _prep_err:
            logger.debug("[langgraph] prepare_sql skipped: %s", _prep_err)

        result_data: List[Dict[str, Any]] = []
        error_msg = ""

        try:
            result = self.db.execute(text(sql))
            result_data = [dict(row) for row in result.mappings().all()]
        except Exception as e:
            error_msg = str(e)
            try:
                self.db.rollback()
            except Exception:
                pass

        if (
            not error_msg
            and auto_limit_applied
            and LANGGRAPH_SELECT_ROW_CAP > 0
            and len(result_data) >= LANGGRAPH_SELECT_ROW_CAP
        ):
            exec_warnings.append(
                f"Results may be truncated at LIMIT {LANGGRAPH_SELECT_ROW_CAP} (safety cap on unbounded SELECT)."
            )

        execution_result = {
            "error": error_msg,
            "data": result_data,
            "row_count": len(result_data),
            "warnings": exec_warnings,
        }
        
        return {
            "execution_result": execution_result,
            "final_sql": None if error_msg else sql,
            "final_data": [] if error_msg else result_data,
            "node_log": ["execute_sql"]
        }

    def error_recovery(self, state: AgentState) -> Dict[str, Any]:
        attempt = state.get("retry_count", 0) + 1
        err_msg = state.get("execution_result", {}).get("error", "unknown error")
        failed_sql = state.get("checked_sql") or state.get("generated_sql")
        logger.info(f"[langgraph] node: error_recovery attempt {attempt}, error: {err_msg}")
        
        system_prompt = f"""You are a SQL debugger. A query failed with the error shown. Fix the SQL so it executes without error.
Study the error carefully.
IMPORTANT: Table name CASE must match the schema snapshot in [SCHEMA]. Many SAP replicas use lowercase physical names (vbrp, vbrk) while others use quoted uppercase ("VBRK"). Copy identifiers EXACTLY from the schema list — do not guess.
PostgreSQL: unquoted identifiers fold to lowercase; double-quoted identifiers are case-sensitive.
VERY IMPORTANT: SAP column names are almost always lowercase (e.g. vbeln, netwr, fkdat).
{ERP_SQL_RULES}
Output ONLY the corrected SQL — no explanation."""

        rag = (state.get("rag_context") or "").strip()
        rag_block = f"\n\n{rag}" if rag else ""
        dyn_hints = _build_dynamic_question_hints(state["question"], int(state.get("days") or 30))
        hints_block = f"\n\n{dyn_hints}" if dyn_hints else ""
        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}{rag_block}{hints_block}

[FAILED SQL]
{failed_sql}

[DB ERROR]
{err_msg}

Fix the SQL."""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        fixed_sql = _extract_sql(response.content)
        return {
            "checked_sql": fixed_sql,
            "generated_sql": fixed_sql,
            "retry_count": attempt,
            "retry_errors": [f"Attempt {attempt}: {err_msg}"],
            "node_log": ["error_recovery"]
        }

    def zero_rows_recovery(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: zero_rows_recovery")
        deterministic_sql = _build_monthly_billing_revenue_sql_if_applicable(state.get("question", ""))
        if deterministic_sql:
            logger.info("[langgraph] zero_rows_recovery: applying deterministic monthly billing fallback")
            return {
                "generated_sql": deterministic_sql,
                "checked_sql": deterministic_sql,
                "zero_rows_retried": True,
                "node_log": ["zero_rows_recovery"]
            }

        system_prompt = f"""You are a SQL expert. A query returned 0 rows.
Common causes: date range too narrow, filter value misspelled.
Fix the query so it returns data.
{ERP_SQL_RULES}
Output ONLY the corrected SQL."""

        rag = (state.get("rag_context") or "").strip()
        rag_block = f"\n\n{rag}" if rag else ""
        dyn_hints = _build_dynamic_question_hints(state["question"], int(state.get("days") or 30))
        hints_block = f"\n\n{dyn_hints}" if dyn_hints else ""
        user_prompt = f"""[SCHEMA]
{state.get('schema_text', '')}{rag_block}{hints_block}

[ZERO-ROW QUERY — widen date range or relax filters]
{state.get('checked_sql') or state.get('generated_sql')}

Hint: remove or widen date filters; if filtering by name, try removing the filter."""

        response = self.llm_sql.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        
        fixed_sql = _extract_sql(response.content)
        return {
            "generated_sql": fixed_sql,
            "checked_sql": fixed_sql,
            "zero_rows_retried": True,
            "node_log": ["zero_rows_recovery"]
        }

    def generate_answer(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: generate_answer")
        rows = state.get("final_data", [])
        
        if not rows:
            err = state.get("execution_result", {}).get("error")
            msg = f"Could not retrieve data due to error: {err}" if err else "No matching records found. Try widening filters."
            return {
                "final_answer": msg,
                "confidence": "low",
                "confidence_note": "0 rows returned",
                "node_log": ["generate_answer"]
            }
            
        exec_ws = (state.get("execution_result") or {}).get("warnings") or []
        sample_n = min(50, len(rows))
        sample = json.dumps(rows[:sample_n], default=str)
        system_prompt = """You are a business intelligence analyst for an ERP system.
Summarize the query results in 2-5 plain English sentences.
Rules:
- Lead with the single most important number or finding.
- Use standard number formatting with commas.
- Be precise — include actual numbers from the data, not vague descriptions.
- If there are totals/sums in the data, state them prominently.
- If the data shows a trend, describe the direction clearly.
- If EXECUTION NOTES mention row caps or truncation, qualify that figures are based on the returned sample only.
- Do NOT mention SQL, database, columns, or technical details.
- Speak directly ("Total sales were...", "Revenue is...")."""

        dc = (state.get("dashboard_context") or "").strip()
        dc_block = f"\n\n[CONTEXT]\n{dc[:4000]}\n" if dc else ""
        warn_block = (
            "\n\n[EXECUTION NOTES]\n" + "\n".join(exec_ws) + "\n"
            if exec_ws
            else ""
        )

        user_prompt = f"""[QUESTION]
{state['question']}{dc_block}{warn_block}
[DATA — {len(rows)} row(s)]
{sample}"""

        response = self.llm_answer.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        body = (response.content or "").strip()
        if not body and rows:
            body = (
                "Here are the results for your question. "
                f"The table shows **{len(rows)}** row(s); see the preview below for figures."
            )

        return {
            "final_answer": body,
            "confidence": "medium" if exec_ws else "high",
            "confidence_note": (
                "Figures reflect returned rows only; see warnings for any row cap."
                if exec_ws
                else ""
            ),
            "node_log": ["generate_answer"]
        }

    def verify_answer(self, state: AgentState) -> Dict[str, Any]:
        logger.info("[langgraph] node: verify_answer")
        if LANGGRAPH_SKIP_VERIFY_ANSWER:
            return {"node_log": ["verify_answer_skipped"]}
        rows = state.get("final_data", [])
        if not state.get("final_answer") or not rows:
            return {"node_log": ["verify_answer"]}
            
        sample_n = min(50, len(rows))
        sample = json.dumps(rows[:sample_n], default=str)
        system_prompt = """You are a fact-checker.
Verify every number in the answer is correct according to the data.
If a number is wrong, silently correct it.
Respond ONLY with the (possibly corrected) answer text."""

        exec_ws = (state.get("execution_result") or {}).get("warnings") or []
        notes_block = (
            "\n\n[EXECUTION NOTES]\n" + "\n".join(exec_ws)
            if exec_ws
            else ""
        )
        user_prompt = f"""[ANSWER TO VERIFY]
{state['final_answer']}

[ACTUAL DATA]
{sample}{notes_block}"""

        response = self.llm_answer.invoke([
            SystemMessage(
                content=system_prompt
                + " If notes mention truncation/caps, ensure the answer does not imply complete population totals."
            ),
            HumanMessage(content=user_prompt),
        ])

        verified = (response.content or "").strip()
        if not verified:
            # Do not wipe a good summary if the verifier returns nothing (common on slow/mobile timeouts).
            return {"node_log": ["verify_answer_empty_kept_prior"]}

        return {
            "final_answer": verified,
            "node_log": ["verify_answer"],
        }
        
    def visualize(self, state: AgentState) -> Dict[str, Any]:
        """Detect chart policy based on data shape, matching frontend ECharts capabilities."""
        logger.info("[langgraph] node: visualize")
        rows = state.get("final_data", [])
        policy = "table"
        
        if rows:
            import decimal

            keys = list(rows[0].keys())
            has_numeric = False
            for k in keys:
                val = rows[0][k]
                if isinstance(val, (int, float, decimal.Decimal)):
                    has_numeric = True
                    break
                if isinstance(val, str) and val.replace(".", "", 1).replace("-", "", 1).isdigit():
                    has_numeric = True
                    break

            qlow = (state.get("question") or "").lower()
            trend_q = any(
                w in qlow
                for w in (
                    "trend",
                    "monthly",
                    "over time",
                    "time series",
                    "by month",
                    "quarter",
                    "weekly",
                    "year over year",
                    "yoy",
                )
            )

            if has_numeric and len(keys) >= 2:
                policy = "line" if trend_q else "bar"
                if not trend_q and len(rows) > 10:
                    policy = "line"
                if "pie" in qlow or "share" in qlow:
                    policy = "pie"
                    
        return {
            "chart_policy": policy,
            "node_log": ["visualize"]
        }

def route_after_execute(state: AgentState) -> str:
    err = state.get("execution_result", {}).get("error")
    rows = len(state.get("final_data", []))
    
    if err:
        el = (err or "").lower()
        # Non-recoverable policy violations — don't waste repair attempts
        if "read-only" in el or "forbidden statement" in el or "only select" in el:
            return "generate_answer"
        if state.get("retry_count", 0) < 3:
            return "error_recovery"
        return "generate_answer"
    
    if rows == 0 and not state.get("zero_rows_retried", False):
        return "zero_rows_recovery"
        
    return "visualize"

def build_graph(planner: LangGraphPlanner) -> Any:
    graph = StateGraph(AgentState)
    
    graph.add_node("load_schema", planner.load_schema)
    graph.add_node("retrieve_context", planner.retrieve_context)
    graph.add_node("generate_sql", planner.generate_sql)
    graph.add_node("check_sql", planner.check_sql)
    graph.add_node("execute_sql", planner.execute_sql)
    graph.add_node("error_recovery", planner.error_recovery)
    graph.add_node("zero_rows_recovery", planner.zero_rows_recovery)
    graph.add_node("visualize", planner.visualize)
    graph.add_node("generate_answer", planner.generate_answer)
    graph.add_node("verify_answer", planner.verify_answer)
    
    graph.add_edge(START, "load_schema")
    graph.add_edge("load_schema", "retrieve_context")
    graph.add_edge("retrieve_context", "generate_sql")
    graph.add_edge("generate_sql", "check_sql")
    graph.add_edge("check_sql", "execute_sql")
    
    graph.add_conditional_edges(
        "execute_sql", 
        route_after_execute,
        {
            "error_recovery": "error_recovery",
            "zero_rows_recovery": "zero_rows_recovery",
            "visualize": "visualize",
            "generate_answer": "generate_answer"
        }
    )
    
    graph.add_edge("error_recovery", "execute_sql")
    graph.add_edge("zero_rows_recovery", "execute_sql")
    
    graph.add_edge("visualize", "generate_answer")
    graph.add_edge("generate_answer", "verify_answer")
    graph.add_edge("verify_answer", END)
    
    return graph.compile()

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
    try:
        days_int = int(days)
    except (TypeError, ValueError):
        days_int = 30

    # Billing/revenue ranking & aggregates: deterministic SQL — avoids multi-minute LangGraph loops.
    try:
        from .intent_dashboard_fast_path import try_intent_dashboard_fast_path

        fast = try_intent_dashboard_fast_path(
            db,
            query or "",
            days=days_int,
            time_scope=(time_scope or "current").strip(),
        )
        if fast is not None:
            return fast
    except Exception as _fast_err:
        logger.debug("intent fast path skipped: %s", _fast_err)

    planner = LangGraphPlanner(db, api_key)
    app = build_graph(planner)
    
    initial_state = {
        "question": query,
        "date_context": "",
        "table_hint": None,
        "user_date_range": {},
        "top_views": [],
        "schema_text": "",
        "sample_text": "",
        "generated_sql": "",
        "checked_sql": "",
        "execution_result": {},
        "retry_count": 0,
        "retry_errors": [],
        "zero_rows_retried": False,
        "rag_context": "",
        "dashboard_context": (dashboard_context or "").strip()[:12000],
        "days": max(1, min(365, days_int)),
        "time_scope": (time_scope or "current").strip(),
        "final_answer": "",
        "final_data": [],
        "final_sql": "",
        "confidence": "medium",
        "confidence_note": "",
        "node_log": [],
        "chart_policy": None,
        "conversation_history": conversation_history or []
    }
    
    result = app.invoke(initial_state)

    period_blurb = _infer_period_blurb(
        query or "",
        max(1, min(365, days_int)),
        (time_scope or "current").strip(),
    )

    chart_spec = None
    if result.get("chart_policy") and result.get("chart_policy") != "table":
        chart_spec = {
            "chart_type": result["chart_policy"],
            "title": f"{result['chart_policy'].capitalize()} Chart",
            "data": result.get("final_data", []),
        }
        
    exec_meta = result.get("execution_result") or {}
    exec_warnings = list(exec_meta.get("warnings") or [])
    retries = result.get("retry_errors") or []
    conf = result.get("confidence", "medium")
    exec_err = exec_meta.get("error")
    if exec_err:
        conf = "low"
    elif len(retries) >= 2:
        conf = "low"
    elif len(retries) == 1 and conf == "high":
        conf = "medium"
    warn_blob = " ".join(exec_warnings).lower()
    if exec_warnings and "truncat" in warn_blob and conf == "high":
        conf = "medium"

    cn = (result.get("confidence_note") or "").strip()
    if len(retries) >= 1:
        cn = (cn + " " if cn else "").strip() + (
            f" SQL required {len(retries)} repair attempt(s) before success."
        )
    if exec_warnings and not cn:
        cn = "See warnings — results may be subject to row or sampling limits."

    final_rows = result.get("final_data") or []
    reply_text = (result.get("final_answer") or "").strip()
    if not reply_text:
        reply_text = (
            "The model did not return a written summary. "
            "Use the **table and chart** below for the query results."
            if final_rows
            else "Analysis complete."
        )

    payload = {
        "reply": reply_text,
        "action": "new",
        "reason": "langgraph_pipeline",
        "schema_tables": result.get("top_views") or [],
        "sql": result.get("final_sql", ""),
        "rows_preview": result.get("final_data", []),
        "charts": [chart_spec] if chart_spec else [],
        "time_scope": result.get("time_scope") or "current",
        "date_range": {},
        "period_info": period_blurb,
        "errors": retries,
        "warnings": exec_warnings,
        "confidence": conf,
        "confidence_note": cn.strip(),
        "node_log": result.get("node_log", []),
    }
    
    return payload