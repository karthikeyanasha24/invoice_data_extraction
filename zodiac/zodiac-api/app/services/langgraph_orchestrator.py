"""
langgraph_orchestrator.py

9-node deterministic state machine — Python port of the reference project's
LangGraph StateGraph pattern (ai-langchain-query.js).

Flow:
  load_schema → retrieve_context → generate_sql → check_sql
      → execute_sql → [error_recovery (×3)] → generate_answer → verify_answer → END
                   → [zero_rows_recovery (×1)]

Does NOT require the `langgraph` package — implemented as a plain Python
directed graph executed by a run-loop, which is equivalent for our use-case.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
import hashlib as _hashlib

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# 30-second SQL result cache
# ---------------------------------------------------------------------------
_SQL_RESULT_CACHE: dict = {}
_SQL_RESULT_CACHE_TTL = 30.0


def _sql_cache_key(sql: str) -> str:
    return _hashlib.sha256((sql or "").strip().lower().encode()).hexdigest()


def _get_cached_result(sql: str):
    import time as _t
    entry = _SQL_RESULT_CACHE.get(_sql_cache_key(sql))
    if entry and (_t.monotonic() - entry[1]) < _SQL_RESULT_CACHE_TTL:
        return entry[0]
    return None


def _set_cached_result(sql: str, rows: list) -> None:
    import time as _t
    _SQL_RESULT_CACHE[_sql_cache_key(sql)] = (rows, _t.monotonic())
_OPENAI_FAST_MODEL = "gpt-4o-mini"
_OPENAI_INSIGHTS_MODEL = "gpt-4o"


# ---------------------------------------------------------------------------
# STATE OBJECT
# ---------------------------------------------------------------------------

@dataclass
class GraphState:
    """Mutable state threaded through every node."""
    # ── inputs ──────────────────────────────────────────────────────────────
    question: str = ""
    db: Any = None                          # SQLAlchemy Session
    client: Any = None                      # OpenAI client
    conversation_history: List[Dict] = field(default_factory=list)
    time_scope: Optional[str] = None
    date_range: Optional[Dict[str, str]] = None
    thread_id: Optional[str] = None
    period_info: Optional[str] = None
    client_platform: str = ""

    # ── schema discovery ────────────────────────────────────────────────────
    schema: Optional[Dict[str, Any]] = None
    schema_text: Optional[str] = None

    # ── RAG ─────────────────────────────────────────────────────────────────
    rag_context: Optional[str] = None

    # ── SQL lifecycle ────────────────────────────────────────────────────────
    generated_sql: Optional[str] = None
    checked_sql: Optional[str] = None
    execution_result: Any = None            # SqlAgentResult | None
    retry_count: int = 0
    retry_errors: List[str] = field(default_factory=list)
    zero_rows_retried: bool = False
    relax_attempted: bool = False

    # ── outputs ──────────────────────────────────────────────────────────────
    final_answer: Optional[str] = None
    final_data: Optional[List[Dict[str, Any]]] = None
    final_sql: Optional[str] = None
    confidence: str = "medium"              # "high" | "medium" | "low"
    charts: Optional[List[Dict[str, Any]]] = None

    # ── trace ─────────────────────────────────────────────────────────────────
    node_log: List[str] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# RESULT WRAPPER (mirrors OrchestratorResult shape)
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    reply: str
    action: str = "new"
    reason: str = "sql_success"
    sql: str = ""
    rows_preview: Optional[List[Dict[str, Any]]] = None
    charts: Optional[List[Dict[str, Any]]] = None
    memory_updated: bool = True
    performance: Optional[Dict[str, Any]] = None
    time_scope: Optional[str] = None
    date_range: Optional[Dict[str, str]] = None
    period_info: Optional[str] = None
    confidence: str = "medium"
    node_log: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# NODE: load_schema
# ---------------------------------------------------------------------------

def _node_load_schema(state: GraphState) -> str:
    """Load SAP schema from DB and build a text representation."""
    state.node_log.append("load_schema")
    try:
        from .schema_loader import get_schema_dict  # type: ignore
        schema = get_schema_dict(state.db)
        if not schema:
            state.error = "Schema unavailable"
            return "error"
        state.schema = schema

        # Build a compact text block: TABLE (N cols): col1, col2, ...
        lines = []
        for table, cols in list(schema.items())[:40]:
            if isinstance(cols, list):
                col_names = [c.get("column", c) if isinstance(c, dict) else str(c) for c in cols[:20]]
                lines.append(f"{table} ({len(cols)} cols): {', '.join(col_names[:12])}" +
                             ("..." if len(cols) > 12 else ""))
        state.schema_text = "\n".join(lines)
        logger.debug("load_schema: %d tables loaded", len(schema))
        return "retrieve_context"
    except Exception as exc:
        logger.warning("load_schema failed: %s", exc)
        state.schema_text = ""
        return "retrieve_context"  # proceed without schema


# ---------------------------------------------------------------------------
# NODE: retrieve_context
# ---------------------------------------------------------------------------

def _node_retrieve_context(state: GraphState) -> str:
    """RAG: fetch similar past queries + glossary for grounding."""
    state.node_log.append("retrieve_context")
    try:
        from .rag_store_service import retrieve_similar_examples, format_rag_context_for_prompt
        results = retrieve_similar_examples(state.db, state.client, state.question)
        state.rag_context = format_rag_context_for_prompt(results) if results else None
        logger.debug("retrieve_context: %d RAG hits", len(results) if results else 0)
    except Exception as exc:
        logger.debug("retrieve_context: RAG skip (%s)", exc)
        state.rag_context = None
    return "generate_sql"


# ---------------------------------------------------------------------------
# NODE: generate_sql
# ---------------------------------------------------------------------------

def _node_generate_sql(state: GraphState) -> str:
    """Use LLM to generate SQL from question + schema + RAG context."""
    state.node_log.append("generate_sql")
    try:
        from .sap_sql_agent import run_schema_driven_sql_agent  # type: ignore

        # On retries, append previous errors to question context
        question_with_context = state.question
        if state.retry_errors:
            error_ctx = "\n".join(f"- Attempt {i+1} failed: {e}"
                                    for i, e in enumerate(state.retry_errors[-3:]))
            question_with_context = (
                f"{state.question}\n\n[PREVIOUS ATTEMPTS FAILED — DO NOT REPEAT:\n{error_ctx}]"
            )

        result = run_schema_driven_sql_agent(
            question=question_with_context,
            db=state.db,
            rag_context=state.rag_context,
        )
        if result and result.sql:
            state.generated_sql = _normalize_table_case(result.sql.strip(), state.schema or {})
            logger.debug("generate_sql: got SQL (%d chars)", len(state.generated_sql))
            return "check_sql"

        # LLM returned nothing useful — escalate to error recovery
        state.error = "SQL generation returned no query"
        return "error_recovery"
    except Exception as exc:
        logger.warning("generate_sql failed: %s", exc)
        state.error = str(exc)
        return "error_recovery"


# ---------------------------------------------------------------------------
# NODE: check_sql
# ---------------------------------------------------------------------------

_CHECK_SQL_PROMPT = """You are a PostgreSQL + SAP data expert reviewing a generated SQL query for correctness before execution.

Check the following 18 points:
1. Only SELECT (no DML — no UPDATE/DELETE/INSERT/DROP/ALTER/TRUNCATE/EXEC)
2. All table names exist in the provided schema
3. All column names exist in the specified tables
4. JOIN conditions reference matching column types
5. LPAD joins for SAP document keys (VBELN, BELNR, KUNAG, KUNRG, KUNNR, LIFNR, MATNR) — all SAP key fields are stored as zero-padded strings; joins MUST use LPAD(TRIM(col), N, '0') on BOTH sides (VBELN/BELNR → 10 chars; customer/vendor numbers → 10 chars; MATNR → 18 chars)
6. SAP date columns (FKDAT, BUDAT) stored as CHAR(8) YYYYMMDD — use SUBSTRING(TRIM(col),1,4) for year extraction, NOT EXTRACT(YEAR FROM col)
7. NETWR / KWMENG / FKIMG stored as TEXT — must CAST(TRIM(col) AS NUMERIC) before arithmetic
8. GJAHR column is unreliable (often '0000') — use FKDAT/BUDAT year extraction instead
9. No cartesian product (every JOIN has an ON clause)
10. GROUP BY includes all non-aggregate SELECT columns
11. HAVING used for aggregate filters (not WHERE)
12. Decimal precision — NETWR values are in the document currency as stored (no division needed unless values are clearly 100× too large)
13. Result size: non-aggregate queries have TOP/LIMIT; aggregate queries have a sensible LIMIT
14. Currency filters use WAERK column when needed
15. NULL-safe aggregation: use COALESCE(CAST(TRIM(col) AS NUMERIC), 0) for SUM/AVG on TEXT money columns
16. CRITICAL — Customer field selection in VBRK: use VBRK.KUNAG (sold-to party, the actual purchasing customer) when the question asks about customer sales/revenue. NEVER use VBRK.KUNRG (payer) for customer ranking — KUNRG is the paying party (often a bank or parent company) and will collapse many customers into one entity, producing wrong results. Only use KUNRG when the user explicitly asks about "payer".
17. CRITICAL — KNA1 join: JOIN KNA1 ON LPAD(TRIM(VBRK.kunag),10,'0') = LPAD(TRIM(KNA1.kunnr),10,'0'). Without LPAD on both sides, rows with different leading-zero counts silently fail to match.
18. VBRP join: always join VBRP ON LPAD(TRIM(VBRK.vbeln),10,'0') = LPAD(TRIM(VBRP.vbeln),10,'0') and also match VBRK.mandt = VBRP.mandt when mandt column exists.
19. CRITICAL — Table name casing: PostgreSQL stores SAP tables under their EXACT UPPERCASE names (VBRK, VBRP, MAKT, KNA1, etc.) using quoted identifiers. Always write table names as double-quoted uppercase — "VBRK" not vbrk or VBRK. Unquoted identifiers (lowercase or uppercase) are folded to lowercase by PostgreSQL and cause "relation does not exist". If the SQL uses unquoted or lowercase table names, add double quotes and uppercase them in corrected_sql.

Return JSON only:
{
  "is_valid": true/false,
  "issues": ["issue1", "issue2"],
  "corrected_sql": "...(only if is_valid=false and you can fix it, else omit)..."
}

Schema (selected tables):
{schema}

SQL to check:
{sql}"""


def _node_check_sql(state: GraphState) -> str:
    """LLM pre-validates the SQL before hitting the DB."""
    state.node_log.append("check_sql")
    sql = state.generated_sql or ""
    if not sql:
        state.error = "Empty SQL from generator"
        return "error_recovery"

    try:
        # Build concise schema excerpt for the tables actually used
        schema_excerpt = _extract_used_schema(sql, state.schema or {})

        prompt = _CHECK_SQL_PROMPT.format(schema=schema_excerpt[:3000], sql=sql[:2000])
        response = state.client.chat.completions.create(
            model=_OPENAI_FAST_MODEL,
            messages=[
                {"role": "system", "content": "You are a SQL validator. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "{}").strip()
        result = json.loads(raw)

        if result.get("is_valid", True):
            state.checked_sql = _normalize_table_case(sql, state.schema or {})
            logger.debug("check_sql: valid ✅")
        else:
            issues = result.get("issues", [])
            corrected = result.get("corrected_sql", "")
            logger.info("check_sql: issues found: %s", issues)
            if corrected and len(corrected) > 20:
                state.checked_sql = _normalize_table_case(corrected.strip(), state.schema or {})
                logger.info("check_sql: using corrected SQL")
            else:
                # Can't auto-fix — record issue and re-generate
                state.retry_errors.append("check_sql issues: " + "; ".join(issues[:3]))
                state.retry_count += 1
                if state.retry_count >= MAX_RETRIES:
                    state.checked_sql = _normalize_table_case(sql, state.schema or {})  # best effort
                else:
                    return "generate_sql"

        return "execute_sql"

    except Exception as exc:
        logger.warning("check_sql failed (%s) — skipping to execute", exc)
        state.checked_sql = _normalize_table_case(sql, state.schema or {})
        return "execute_sql"


def _extract_used_schema(sql: str, schema: Dict[str, Any]) -> str:
    """Extract schema only for tables referenced in the SQL."""
    sql_upper = sql.upper()
    lines = []
    for table, cols in schema.items():
        if table.upper() in sql_upper:
            if isinstance(cols, list):
                col_names = [c.get("column", c) if isinstance(c, dict) else str(c) for c in cols[:30]]
                lines.append(f"{table}: {', '.join(col_names)}")
    return "\n".join(lines) if lines else "(schema not available)"


def _normalize_table_case(sql: str, schema: Dict[str, Any]) -> str:
    """
    Ensure SAP table names are properly double-quoted uppercase in PostgreSQL SQL.

    PostgreSQL stores SAP tables as quoted uppercase identifiers (e.g. ``"VBRK"``).
    An unquoted identifier — whether written as ``vbrk``, ``VBRK``, or ``Vbrk`` —
    is always folded to lowercase by PostgreSQL and causes
    ``relation "vbrk" does not exist``.

    Strategy: for every table name in the schema, replace any unquoted occurrence
    (regardless of case) with the properly quoted form ``"TABLENAME"``.
    Already-quoted occurrences (preceded by ``"``) are left untouched.

    Also fixes column qualifiers: when FROM has "VBRK" but SELECT/WHERE uses vbrk.col,
    PostgreSQL raises "missing FROM-clause entry for table vbrk" because unquoted lowercase
    'vbrk' is a different identifier from quoted '"VBRK"'.
    """
    result = sql
    for table in schema:
        # Step 1: Fix unquoted table name occurrences (FROM/JOIN and other uses)
        pattern = re.compile(r'(?<!")\b' + re.escape(table) + r'\b(?!")', re.IGNORECASE)
        quoted = f'"{table}"'
        if pattern.search(result):
            result = pattern.sub(quoted, result)

    # Step 2: Fix column qualifier casing — "vbrk".col → "VBRK".col and vbrk.col → "VBRK".col
    # This is needed when the LLM uses lowercase table names as column qualifiers even though
    # the physical table is uppercase-quoted (e.g. SELECT vbrk.waerk FROM "VBRK").
    for table in schema:
        if table != table.upper():
            continue  # only fix uppercase tables
        table_lower = table.lower()
        # "vbrk".col → "VBRK".col (lowercase quoted qualifier)
        result = re.sub(
            r'"' + re.escape(table_lower) + r'"\.',
            f'"{table}".',
            result,
        )
        # vbrk.col → "VBRK".col (bare lowercase qualifier, not preceded by " to avoid double-fixing)
        result = re.sub(
            r'(?<!["\w])' + re.escape(table_lower) + r'\.',
            f'"{table}".',
            result,
        )

    return result


# ---------------------------------------------------------------------------
# NODE: execute_sql
# ---------------------------------------------------------------------------

def _node_execute_sql(state: GraphState) -> str:
    """Execute the validated SQL against the database."""
    state.node_log.append("execute_sql")
    sql = state.checked_sql or state.generated_sql or ""
    if not sql:
        state.error = "No SQL to execute"
        return "error_recovery"

    # Check 30-second result cache before hitting DB
    cached = _get_cached_result(sql)
    if cached is not None:
        logger.info("execute_sql: cache hit (%d rows)", len(cached))
        state.final_sql = sql
        state.execution_result = cached
        return "generate_answer"

    try:
        from .sap_sql_agent import _run_sql  # type: ignore
        rows = _run_sql(state.db, sql)
        state.final_sql = sql

        if rows is None:
            state.error = "SQL execution returned None"
            state.retry_errors.append(state.error)
            state.retry_count += 1
            return "error_recovery" if state.retry_count < MAX_RETRIES else "generate_answer"

        if len(rows) == 0 and not state.zero_rows_retried:
            if not state.relax_attempted:
                logger.info("execute_sql: zero rows — trying relax_filters")
                return "relax_filters"
            logger.info("execute_sql: zero rows after relax — trying zero_rows_recovery")
            return "zero_rows_recovery"

        _set_cached_result(sql, rows)
        state.execution_result = rows
        logger.info("execute_sql: %d rows ✅", len(rows))
        return "generate_answer"

    except Exception as exc:
        err_msg = str(exc)
        logger.warning("execute_sql error: %s", err_msg)
        state.error = err_msg
        state.retry_errors.append(err_msg)
        state.retry_count += 1
        if state.retry_count < MAX_RETRIES:
            return "error_recovery"
        # Final attempt failed — proceed to answer with what we have
        state.execution_result = []
        return "generate_answer"


# ---------------------------------------------------------------------------
# NODE: relax_filters
# ---------------------------------------------------------------------------

def _node_relax_filters(state: GraphState) -> str:
    """Remove the year filter from SQL and retry once when execute_sql returned 0 rows."""
    import re as _re
    state.node_log.append("relax_filters")
    if state.relax_attempted:
        return "zero_rows_recovery"
    sql = state.checked_sql or state.generated_sql or ""
    # Remove SUBSTRING-based year predicates (FKDAT year filter)
    relaxed = _re.sub(
        r"\s*AND\s+SUBSTRING\s*\(.*?fkdat.*?\)\s*IN\s*\([^)]+\)",
        "", sql, flags=_re.IGNORECASE
    )
    state.relax_attempted = True
    if relaxed.strip() == sql.strip():
        # nothing was removed — nothing to relax
        return "zero_rows_recovery"
    state.checked_sql = relaxed.strip()
    logger.info("relax_filters: removed year filter, retrying SQL")
    return _node_execute_sql(state)


# ---------------------------------------------------------------------------
# NODE: error_recovery
# ---------------------------------------------------------------------------

_ERROR_RECOVERY_PROMPT = """The following SQL query failed to execute against a SAP PostgreSQL database.

Error: {error}

Failed SQL:
{sql}

Schema context (tables used):
{schema}

SAP rules to follow when rewriting:
- CRITICAL: Table names MUST be double-quoted uppercase — "VBRK", "VBRP", "MAKT", "KNA1", "EKKO", "EKPO", etc. PostgreSQL stores SAP tables with quoted uppercase names; writing vbrk or VBRK (unquoted) causes "relation does not exist". Fix ALL lowercase/unquoted table names.
- fkdat / budat columns are CHAR(8) strings — use SUBSTRING(TRIM(col),1,4) = 'YYYY' for year, NOT EXTRACT
- NETWR / KWMENG are TEXT, must CAST(col AS NUMERIC)
- VBELN joins: use LPAD(TRIM(a.vbeln),10,'0') = LPAD(TRIM(b.vbeln),10,'0')
- GJAHR is unreliable, avoid it
- Never use INNER as an alias (it is a SQL keyword)
- Use COALESCE(col, 0) in numeric aggregations

Write ONLY the corrected SQL query, no explanation, no markdown fencing."""


def _node_error_recovery(state: GraphState) -> str:
    """Ask LLM to rewrite the SQL given the error message."""
    state.node_log.append("error_recovery")

    if state.retry_count >= MAX_RETRIES:
        logger.warning("error_recovery: max retries reached")
        state.execution_result = []
        return "generate_answer"

    sql = state.checked_sql or state.generated_sql or ""
    error = state.error or "Unknown error"
    schema_ctx = _extract_used_schema(sql, state.schema or {})

    try:
        prompt = _ERROR_RECOVERY_PROMPT.format(
            error=error[:500],
            sql=sql[:2000],
            schema=schema_ctx[:2000],
        )
        response = state.client.chat.completions.create(
            model=_OPENAI_FAST_MODEL,
            messages=[
                {"role": "system", "content": "You are a SQL repair expert. Output SQL only, no explanation."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        raw = (response.choices[0].message.content or "").strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw).strip()

        if raw and len(raw) > 20:
            state.generated_sql = _normalize_table_case(raw, state.schema or {})
            state.checked_sql = None  # force re-check
            logger.info("error_recovery: generated new SQL (attempt %d)", state.retry_count + 1)
            return "check_sql"

    except Exception as exc:
        logger.warning("error_recovery LLM call failed: %s", exc)

    state.retry_count += 1
    if state.retry_count >= MAX_RETRIES:
        state.execution_result = []
        return "generate_answer"
    return "generate_sql"  # try fresh generation


# ---------------------------------------------------------------------------
# NODE: zero_rows_recovery
# ---------------------------------------------------------------------------

def _node_zero_rows_recovery(state: GraphState) -> str:
    """
    When SQL executes successfully but returns 0 rows, widen the date filter
    and retry once.  Strategy: drop or broaden WHERE year/date constraints.
    """
    state.node_log.append("zero_rows_recovery")
    state.zero_rows_retried = True
    sql = state.checked_sql or state.generated_sql or ""
    if not sql:
        state.execution_result = []
        return "generate_answer"

    try:
        widened = _widen_date_filter(sql)
        if widened and widened != sql:
            logger.info("zero_rows_recovery: widened date filter, retrying")
            state.checked_sql = widened
            state.final_sql = widened
            from .sap_sql_agent import _run_sql  # type: ignore
            rows = _run_sql(state.db, widened) or []
            if rows:
                state.execution_result = rows
                state.node_log.append("zero_rows_recovery:found_rows")
                return "generate_answer"

        # Widen didn't help — ask LLM to try a broader query
        prompt = (
            f"The following SAP SQL returned 0 rows.\n\n"
            f"SQL:\n{sql[:1500]}\n\n"
            f"Rewrite it to return SOMETHING relevant by:\n"
            f"1. Broadening or removing date filters\n"
            f"2. If filtered to a specific year, try without year filter\n"
            f"3. If still nothing, return the top 20 rows without date filter\n"
            f"Output only the SQL, no explanation."
        )
        response = state.client.chat.completions.create(
            model=_OPENAI_FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600,
        )
        new_sql = (response.choices[0].message.content or "").strip()
        new_sql = re.sub(r"^```(?:sql)?\s*", "", new_sql, flags=re.I)
        new_sql = re.sub(r"\s*```$", "", new_sql).strip()
        if new_sql and len(new_sql) > 20:
            from .sap_sql_agent import _run_sql  # type: ignore
            rows2 = _run_sql(state.db, new_sql) or []
            state.execution_result = rows2
            if rows2:
                state.final_sql = new_sql
                state.checked_sql = new_sql
                state.node_log.append(f"zero_rows_recovery:llm_widened({len(rows2)} rows)")
        else:
            state.execution_result = []

    except Exception as exc:
        logger.warning("zero_rows_recovery error: %s", exc)
        state.execution_result = []

    return "generate_answer"


def _widen_date_filter(sql: str) -> str:
    """
    Heuristic: remove the most restrictive date year filter from a SAP SQL.
    e.g. SUBSTRING(TRIM(fkdat),1,4) = '2009'  →  removed
    """
    # Remove SAP-style year equality: SUBSTRING(TRIM(col),1,4) = 'YYYY'
    widened = re.sub(
        r"AND\s+SUBSTRING\s*\(\s*TRIM\s*\([^)]*(?:fkdat|budat|bldat|erdat)[^)]*\)\s*,\s*1\s*,\s*4\s*\)\s*=\s*'\d{4}'",
        "",
        sql,
        flags=re.IGNORECASE,
    )
    # Remove year columns in WHERE: col = 'YYYY'
    widened = re.sub(
        r'AND\s+"?(?:fkdat|budat|gjahr|bldat)"?\s*=\s*\'\d{4}\'',
        "",
        widened,
        flags=re.IGNORECASE,
    )
    # Remove BETWEEN date literals
    widened = re.sub(
        r'AND\s+"?(?:fkdat|budat|bldat)"?\s+BETWEEN\s+\'[\d\-]+\'\s+AND\s+\'[\d\-]+\'',
        "",
        widened,
        flags=re.IGNORECASE,
    )
    return widened.strip() if widened.strip() != sql.strip() else sql


# ---------------------------------------------------------------------------
# NODE: generate_answer
# ---------------------------------------------------------------------------

_ANSWER_PROMPT = """You are a business intelligence assistant analyzing SAP ERP data.

Question: {question}

SQL executed:
{sql}

Data returned ({row_count} rows):
{data_sample}

{rag_note}

Write a concise, accurate business answer (2-4 sentences). Rules:
- State specific numbers from the data (no vague phrases like "various amounts")
- Use Indian number formatting: values ≥ 10,00,000 → "X.XX Cr", ≥ 1,00,000 → "X.XX L"
  (1 Crore = 100 Lakhs = 10,000,000; 1 Lakh = 100,000)
- For USD/EUR values > 1,000,000, use "X.XX M"
- If 0 rows: explain what was searched and suggest possible reasons
- Do not mention SQL, tables, or column names
- Do not say "based on the data" — just state the facts"""


def _node_generate_answer(state: GraphState) -> str:
    """LLM turns raw rows into a plain-English business answer."""
    state.node_log.append("generate_answer")

    rows = state.execution_result or []
    sql = state.final_sql or state.checked_sql or state.generated_sql or ""

    if not rows:
        state.final_answer = (
            f"The query returned no results. This could mean no transactions match "
            f"the specified criteria, or the data may be in a different time period."
        )
        state.final_data = []
        state.confidence = "low"
        return "verify_answer"

    # Build data sample (max 10 rows for prompt)
    try:
        data_sample = json.dumps(rows[:10], default=str, indent=2)[:2000]
    except Exception:
        data_sample = str(rows[:5])[:1000]

    rag_note = ""
    if state.rag_context:
        rag_note = "Context from similar past queries:\n" + state.rag_context[:500]

    prompt = _ANSWER_PROMPT.format(
        question=state.question,
        sql=sql[:600],
        row_count=len(rows),
        data_sample=data_sample,
        rag_note=rag_note,
    )

    try:
        import os as _os
        _is_mobile = (getattr(state, "client_platform", "") == "mobile") or \
                     (_os.getenv("LANGGRAPH_FORCE_SHORT_ANSWERS", "").strip().lower() in ("1", "true", "yes"))
        _token_limit = 400 if _is_mobile else 800
        _system_prefix = "Reply in 2-3 sentences maximum. " if _is_mobile else ""

        # Resolve model — guard against "auto" or blank (would cause API 404)
        model = _OPENAI_INSIGHTS_MODEL
        try:
            from ..config.config import AI_INSIGHTS_MODEL  # type: ignore
            _cfg_model = (AI_INSIGHTS_MODEL or "").strip().lower()
            if _cfg_model and _cfg_model not in ("auto", "none", ""):
                model = AI_INSIGHTS_MODEL
        except ImportError:
            pass

        response = state.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"{_system_prefix}You are a concise BI analyst. Answer factually using only the data provided."},
                {"role": "user", "content": prompt},
            ],
            **openai_chat_temperature_kwargs(model, 0.2),
            **openai_completion_limit_kwargs(model, _token_limit),
        )
        generated = (response.choices[0].message.content or "").strip()
        # Only accept non-empty responses; fall through to data-driven fallback otherwise
        if generated:
            state.final_answer = generated
        state.final_data = rows
        state.confidence = "high" if len(rows) >= 1 else "low"

    except Exception as exc:
        logger.warning("generate_answer LLM failed: %s", exc)
        state.final_data = rows
        state.confidence = "medium"

    # Guarantee a non-empty answer when rows are present
    if not state.final_answer and rows:
        top = rows[0]
        state.final_answer = (
            f"Query returned {len(rows)} row(s). "
            f"Top result: {', '.join(f'{k}={v}' for k, v in list(top.items())[:4])}."
        )

    return "verify_answer"


# ---------------------------------------------------------------------------
# NODE: verify_answer
# ---------------------------------------------------------------------------

_VERIFY_PROMPT = """You are a fact-checker for a BI assistant. Verify that the answer is numerically accurate against the raw data.

Question: {question}
Answer to verify: {answer}
Raw data (first 5 rows):
{data}

Rules:
1. Check every number mentioned in the answer against the data
2. If a number is WRONG, silently correct it (do not say "I corrected" — just state the right number)
3. If the answer is already correct, return it unchanged
4. If the answer mentions a total that differs from the sum in the data, fix the total
5. Keep the same tone and length — just fix wrong numbers

Return only the (possibly corrected) answer text."""


def _node_verify_answer(state: GraphState) -> str:
    """Cross-check the generated answer against actual row data."""
    state.node_log.append("verify_answer")

    # Allow ops teams to skip this hop for faster responses
    import os as _os
    if _os.getenv("LANGGRAPH_SKIP_VERIFY_ANSWER", "").strip().lower() in ("1", "true", "yes"):
        return "END"

    answer = state.final_answer or ""
    rows = state.final_data or []

    if not answer or not rows:
        return "END"

    # Only verify if there are numbers in the answer worth checking
    if not re.search(r"\d", answer):
        return "END"

    try:
        data_sample = json.dumps(rows[:5], default=str, indent=2)[:1500]
        prompt = _VERIFY_PROMPT.format(
            question=state.question,
            answer=answer,
            data=data_sample,
        )
        response = state.client.chat.completions.create(
            model=_OPENAI_FAST_MODEL,
            messages=[
                {"role": "system", "content": "You are a fact-checker. Output only the corrected answer text, nothing else."},
                {"role": "user", "content": prompt},
            ],
            **openai_chat_temperature_kwargs(_OPENAI_FAST_MODEL, 0.0),
            **openai_completion_limit_kwargs(_OPENAI_FAST_MODEL, 350),
        )
        verified = (response.choices[0].message.content or "").strip()
        # SAFETY: only replace if verified is meaningfully long and not shorter
        # than the original — prevents overwriting a good answer with LLM garbage
        if verified and len(verified) >= max(10, len(answer) // 2):
            state.final_answer = verified
            logger.debug("verify_answer: answer updated (%d→%d chars)", len(answer), len(verified))
        else:
            logger.debug("verify_answer: keeping original (verified too short or empty)")

    except Exception as exc:
        logger.debug("verify_answer LLM failed (non-fatal): %s", exc)

    return "END"


# ---------------------------------------------------------------------------
# GRAPH RUNNER
# ---------------------------------------------------------------------------

_NODES = {
    "load_schema":          _node_load_schema,
    "retrieve_context":     _node_retrieve_context,
    "generate_sql":         _node_generate_sql,
    "check_sql":            _node_check_sql,
    "execute_sql":          _node_execute_sql,
    "relax_filters":        _node_relax_filters,
    "error_recovery":       _node_error_recovery,
    "zero_rows_recovery":   _node_zero_rows_recovery,
    "generate_answer":      _node_generate_answer,
    "verify_answer":        _node_verify_answer,
}

_START_NODE = "load_schema"
_MAX_STEPS = 30   # safety limit to prevent infinite loops


def run_pipeline(
    question: str,
    db: Any,
    client: Any,
    *,
    conversation_history: Optional[List[Dict]] = None,
    time_scope: Optional[str] = None,
    date_range: Optional[Dict[str, str]] = None,
    thread_id: Optional[str] = None,
    period_info: Optional[str] = None,
    client_platform: str = "",
) -> PipelineResult:
    """
    Execute the 9-node AI pipeline and return a PipelineResult.

    This is the main entry point called from ai_analysis_orchestrator.py.
    """
    t0 = time.time()

    state = GraphState(
        question=question,
        db=db,
        client=client,
        conversation_history=conversation_history or [],
        time_scope=time_scope,
        date_range=date_range,
        thread_id=thread_id,
        period_info=period_info,
        client_platform=client_platform or "",
    )

    # Build chart specs after the pipeline completes (chart engine is pure — no DB calls)
    def _build_charts(rows: List[Dict]) -> List[Dict]:
        try:
            from .chart_decision_engine import build_chart_specs_for_rows
            return build_chart_specs_for_rows(rows, question) or []
        except Exception as ce:
            logger.debug("chart build failed: %s", ce)
            return []

    current_node = _START_NODE
    steps = 0

    while current_node != "END" and steps < _MAX_STEPS:
        steps += 1
        node_fn = _NODES.get(current_node)
        if node_fn is None:
            logger.error("Unknown node: %s", current_node)
            break
        try:
            logger.debug("→ node: %s (step %d)", current_node, steps)
            next_node = node_fn(state)
            current_node = next_node
        except Exception as exc:
            logger.error("Node %s raised: %s", current_node, exc, exc_info=True)
            state.error = str(exc)
            # Emergency exit
            if current_node in ("generate_answer", "verify_answer"):
                break
            current_node = "generate_answer"

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        "pipeline done: %d steps, %dms | sql=%s | rows=%d | confidence=%s",
        steps, elapsed_ms,
        "✅" if state.final_sql else "❌",
        len(state.final_data or []),
        state.confidence,
    )

    # Build charts from the final data
    charts = _build_charts(state.final_data or [])

    # RAG auto-save: persist successful NL→SQL pairs
    if (state.final_sql and state.final_data and len(state.final_data) >= 1
            and not state.zero_rows_retried and state.retry_count == 0):
        try:
            from .rag_store_service import save_successful_query
            save_successful_query(db, client, question, state.final_sql)
        except Exception:
            pass

    preview = (state.final_data or [])[:50]

    # Build a data-driven fallback if LLM never produced prose
    _reply = state.final_answer or ""
    if not _reply and (state.final_data or []):
        top = (state.final_data or [])[0]
        _reply = (
            f"Query returned {len(state.final_data or [])} row(s). "
            f"Top result: {', '.join(f'{k}={v}' for k, v in list(top.items())[:4])}."
        )
    _reply = _reply or "The query completed but no summary could be generated."

    return PipelineResult(
        reply=_reply,
        action="new",
        reason="langgraph_pipeline" if state.final_sql else "no_sql",
        sql=state.final_sql or state.generated_sql or "",
        rows_preview=preview,
        charts=charts,
        memory_updated=True,
        performance={"total_ms": elapsed_ms, "steps": steps, "retries": state.retry_count},
        time_scope=state.time_scope,
        date_range=state.date_range,
        period_info=state.period_info,
        confidence=state.confidence,
        node_log=state.node_log,

    )
