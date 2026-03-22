import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config.config import OPENAI_API_KEY, AI_INSIGHTS_MODEL, AI_FAST_MODEL
from .ai_analysis_memory_store import AiAnalysisMemory, load_memory, save_memory, upsert_knowledge
from .sap_sql_agent import run_sap_sql_agent, run_adaptive_sap_sql_agent, run_schema_driven_sql_agent, run_purchase_order_fallback, _serialize_value  # type: ignore
from .ai_chart_generator import analyze_visualization_needs, chart_specs_to_json
from .training_data_collector import log_query_execution, get_few_shot_examples
from .sql_example_library import get_sql_examples_for_question
from .query_cache import find_similar_cached_query, cache_query_result
from .multi_llm_client import get_multi_llm_client, get_best_available_model, smart_chat_completion
from .sql_generation_sanitizers import sanitize_generated_sap_sql

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    reply: str
    action: str
    reason: str = ""
    sql: str = ""
    rows_preview: Optional[List[Dict[str, Any]]] = None
    compare: Optional[Dict[str, Any]] = None
    memory_updated: bool = False
    charts: Optional[List[Dict[str, Any]]] = None
    performance: Optional[Dict[str, Any]] = None
    time_scope: Optional[str] = None
    date_range: Optional[Dict[str, str]] = None
    period_info: Optional[str] = None
    # Invoice-bot: insights (best + alternatives) and analysis plan (calculations, visualizations, data_notes)
    insights: Optional[Dict[str, Any]] = None  # { "best_provider", "best_text", "alternatives": [(name, text), ...] }
    analysis_plan: Optional[Dict[str, Any]] = None  # { "calculations", "visualizations", "data_notes" }
    # Analytics layer: KPIs and executive insights (after SQL execution)
    metrics: Optional[Dict[str, Any]] = None  # { column: { total, avg, max, min, kpi_type } }
    analytics_insights: Optional[Dict[str, Any]] = None  # { executive_summary, key_metrics[], insights[], recommendations[] }
    # Andy's training loop: when LLM fails, ChatGPT proposes SQL → user approves → store
    needs_approval: bool = False
    proposed_sql: Optional[str] = None


def _get_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def _compute_period_info(time_scope: str, days: int = 30) -> Tuple[str, Dict[str, str]]:
    """
    Compute human-readable period_info and date_range dict based on time_scope.
    
    Returns:
        (period_info, date_range) where:
        - period_info: Human-readable string like "Historical (1994-2010)" or "Last 30 days"
        - date_range: Dict with min_date and max_date in ISO format
    """
    from datetime import datetime, timedelta
    
    if time_scope == "historical":
        return (
            "Historical Data (1994-2010)",
            {"min_date": "1994-01-01", "max_date": "2010-12-31"}
        )
    elif time_scope == "both":
        today = datetime.now().date()
        return (
            f"All Periods (1994-{today.year})",
            {"min_date": "1994-01-01", "max_date": today.isoformat()}
        )
    else:  # current
        today = datetime.now().date()
        start_date = today - timedelta(days=days)
        return (
            f"Last {days} days",
            {"min_date": start_date.isoformat(), "max_date": today.isoformat()}
        )


def _safe_json_extract(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def _should_force_new_action(user_query: str) -> bool:
    """
    Detect queries that definitely need new SQL execution.
    This prevents misclassification of data queries as "follow-up".
    """
    q = (user_query or "").strip().lower()
    if not q:
        return False
    
    # Time-based queries (different periods than default 30-day context)
    time_indicators = [
        "year", "month", "quarter", "last year", "this year", "next year",
        "2020", "2021", "2022", "2023", "2024", "2025", "2026",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "q1", "q2", "q3", "q4", "ytd", "mtd",
        "specific year", "specific month", "particular year", "particular month"
    ]
    
    # Aggregation and analytical queries
    agg_keywords = [
        "total", "sum", "average", "avg", "count", "highest", "lowest",
        "best", "worst", "top", "bottom", "most", "least", "maximum", "minimum",
        "compare", "comparison", "versus", "vs", "difference", "trend", "growth"
    ]
    
    # Data request keywords
    data_keywords = [
        "show", "display", "list", "get", "find", "search", "calculate", "compute",
        "sales", "revenue", "invoice", "invoices", "customer", "customers",
        "product", "products", "order", "orders", "amount", "value", "price",
        "cost", "profit", "margin", "quantity", "volume"
    ]
    
    # Check for combinations that indicate new data queries
    has_time = any(t in q for t in time_indicators)
    has_agg = any(a in q for a in agg_keywords)
    has_data = any(d in q for d in data_keywords)
    
    # Force "new" if asking for specific time period data
    if has_time and (has_agg or has_data):
        return True
    
    # Force "new" if asking for aggregated/analytical data
    if has_agg and has_data:
        return True
    
    # Force "new" for "show me..." or "display..." queries with data keywords
    if q.startswith(("show me", "show the", "display", "list", "get me", "find")):
        if has_data or has_agg:
            return True
    
    return False


def _decide_action(client: OpenAI, user_query: str, mem: AiAnalysisMemory) -> Tuple[str, str]:
    # Fast keyword-based detection first (avoid unnecessary LLM call)
    if _should_force_new_action(user_query):
        logger.info(f"🚀 Forcing 'new' action for data query: {user_query[:100]}")
        return "new", "data_query_detected_by_keywords"
    
    last_sql = (mem.last_sql or "")[:2000]
    last_q = (mem.last_user_query or "")[:500]
    prompt = f"""
You are assisting with SQL query generation for an analytics chat.

User query: "{user_query}"
Last user query in this chat: "{last_q}"
Last SQL query (if any): "{last_sql}"

Task:
Decide whether this query is:
1) identical to a query asked before (reuse)
2) a comparison between multiple datasets/periods (compare)
3) a follow-up that can be answered from prior results/context without new SQL (follow-up)
4) new knowledge/instructions the user wants remembered (knowledge)
5) a new query requiring new SQL and new data (new)

IMPORTANT: If the query asks for data analysis, aggregations, or specific metrics (sales, revenue, counts, etc.), 
it should almost always be "new" unless it's EXACTLY the same as the last query.

Return JSON only:
{{
  "action": "reuse"|"compare"|"follow-up"|"knowledge"|"new",
  "reason": "short reason"
}}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=120,
    )
    decision = _safe_json_extract((resp.choices[0].message.content or "").strip())
    action = str(decision.get("action") or "new").strip()
    reason = str(decision.get("reason") or "").strip()
    if action not in {"reuse", "compare", "follow-up", "knowledge", "new"}:
        action = "new"
    
    logger.info(f"📋 Action decision: {action} ({reason})")
    return action, reason


def _is_explicit_knowledge_instruction(user_query: str) -> bool:
    """
    Detect when the user is clearly giving an instruction to save/remember,
    so we always treat it as "knowledge" and do not run SQL or answer from context.
    """
    q = (user_query or "").strip().lower()
    if not q or len(q) < 10:
        return False
    prefixes = (
        "remember:",
        "remember that",
        "save this:",
        "save that",
        "store this:",
        "store that",
        "note:",
        "note that",
        "for future:",
        "when i ask about",
        "when i ask for",
    )
    return any(q.startswith(p) for p in prefixes)


def _is_small_chitchat(user_query: str) -> bool:
    """
    Fast heuristic: detect trivial greetings/thanks that should NOT trigger SQL.
    """
    q = (user_query or "").strip().lower()
    if not q:
        return False
    # Single-word or very short chit-chat
    simple_greetings = {
        "hi",
        "hello",
        "hey",
        "yo",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "hola",
        "bye",
        "good morning",
        "good evening",
        "good night",
    }
    # If the query is very short and matches a greeting/thanks, treat as chit-chat
    if len(q.split()) <= 3 and any(g in q for g in simple_greetings):
        # Avoid false positives when there are clear data keywords
        data_keywords = ["invoice", "invoices", "sales", "revenue", "customer", "product", "country", "industry"]
        if not any(k in q for k in data_keywords):
            return True
    return False


def _rows_preview(rows: List[Dict[str, Any]], limit: int = 30) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows[:limit]:
        clean = {str(k): _serialize_value(v) for k, v in (r or {}).items()}
        out.append(clean)
    return out


def _split_compare_query(client: OpenAI, user_query: str) -> List[str]:
    """
    INVOICE_BOT uses split_comparison_query. We mimic via LLM:
    return 2+ sub-questions that can be executed separately.
    """
    prompt = f"""
User query: "{user_query}"

Task:
If the user is asking to compare two or more things (time periods, customers, products, countries),
rewrite into multiple standalone questions that can be answered by SQL independently.

Return JSON only:
{{
  "subqueries": ["...", "..."]
}}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=250,
    )
    data = _safe_json_extract((resp.choices[0].message.content or "").strip())
    subs = data.get("subqueries")
    if isinstance(subs, list):
        cleaned = [str(s).strip() for s in subs if str(s).strip()]
        return cleaned[:4]
    return []


def _compare_numeric(datasets: List[Tuple[str, List[Dict[str, Any]]]]) -> Dict[str, Any]:
    """
    Lightweight compare: for each dataset compute numeric column sums/means where possible.
    """
    def is_num(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    summary: Dict[str, Any] = {"datasets": []}
    for label, rows in datasets:
        if not rows:
            summary["datasets"].append({"label": label, "row_count": 0, "numeric": {}})
            continue
        numeric_acc: Dict[str, Dict[str, float]] = {}
        counts: Dict[str, int] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            for k, v in r.items():
                if is_num(v):
                    if k not in numeric_acc:
                        numeric_acc[k] = {"sum": 0.0}
                        counts[k] = 0
                    numeric_acc[k]["sum"] += float(v)
                    counts[k] += 1
        numeric_out: Dict[str, Dict[str, float]] = {}
        for k, agg in numeric_acc.items():
            c = counts.get(k, 0) or 0
            numeric_out[k] = {"sum": agg["sum"], "mean": (agg["sum"] / c) if c else 0.0}
        summary["datasets"].append({"label": label, "row_count": len(rows), "numeric": numeric_out})
    return summary


def run_ai_analysis_orchestrator(
    *,
    api_key: Optional[str],
    user_id: int,
    user_query: str,
    db: Session,
    conversation_history: Optional[list] = None,
    context_str: str = "",
    sap_db: Optional[Session] = None,
    time_scope: str = "current",
    days: int = 30,
) -> OrchestratorResult:
    """
    Orchestrates INVOICE_BOT-like behaviors:
    - action decision (reuse/compare/follow-up/knowledge/new)
    - persisted memory per user (last SQL, last rows, knowledge)
    - runs sap_sql_agent when needed
    
    Args:
        time_scope: 'current' (recent data), 'historical' (1994-2010), or 'both' (compare periods)
        days: Number of days for current period context
    
    Returns a response payload that keeps `reply` for the current frontend.
    """
    # Performance tracking
    perf_start = time.time()
    timings = {}
    
    # Compute period information based on time_scope
    period_info, date_range = _compute_period_info(time_scope, days)
    
    effective_key = api_key or OPENAI_API_KEY
    if not effective_key:
        return OrchestratorResult(
            reply="AI analysis is not configured (missing OPENAI_API_KEY).", 
            action="error", 
            reason="missing_api_key",
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info
        )

    client = _get_client(effective_key)
    mem = load_memory(db, user_id)
    
    # NOTE: ULTRA-FAST PATH (reuse-instant) intentionally removed.
    # Every query must run fresh SQL against the correct table — returning cached data for a
    # different question caused wrong results (e.g. FAGLFLEXA query returning VBRK rows).

    # If user clearly says "Remember:" or "Save this:", always treat as knowledge (don't run SQL).
    if _is_explicit_knowledge_instruction(user_query):
        action, reason = "knowledge", "explicit_save_instruction"
        timings["action_decision_ms"] = 0
    else:
        action_start = time.time()
        action, reason = _decide_action(client, user_query, mem)
        timings["action_decision_ms"] = int((time.time() - action_start) * 1000)

    # For reliability and to avoid reusing stale context, strongly prefer fresh "new" executions.
    # We keep "knowledge" and "compare" behaviors, but treat generic "reuse" and "follow-up"
    # classifications as "new" so each business question runs its own SQL.
    if action in {"reuse", "follow-up"}:
        logger.info(f"🔁 Overriding action '{action}' to 'new' for fresh SQL execution")
        action = "new"
        reason = (reason or "") + "|forced_new_for_fresh_results"

    # Pure chit-chat (greetings, thanks, etc.) – do NOT hit the database.
    if _is_small_chitchat(user_query):
        prompt = f"""
You are a friendly business assistant.

The user sent a short greeting or casual message that does NOT require database queries.
Respond briefly and naturally. Do NOT mention SQL or data, just be polite.

User: {user_query}
"""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=80,
        )
        reply = (resp.choices[0].message.content or "").strip()
        mem.last_user_query = user_query
        save_memory(db, mem)
        return OrchestratorResult(
            reply=reply or "Hello!",
            action="chitchat",
            reason="short_greeting_no_sql",
            sql="",
            rows_preview=None,
            memory_updated=True,
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info
        )

    # knowledge: store a short instruction snippet
    if action == "knowledge":
        upsert_knowledge(db, user_id, f"note_{len(mem.knowledge())+1}", user_query.strip()[:2000])
        return OrchestratorResult(
            reply="Saved that as a note for this chat session. Ask me a question anytime and I’ll use it as context.",
            action=action,
            reason=reason,
            memory_updated=True,
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info
        )

    # follow-up: respond from memory + context without new SQL
    if action == "follow-up":
        last_rows = mem.last_rows()
        prompt = f"""
You are a business analyst assistant. Answer the user's follow-up using prior context and the last result sample when relevant.

Dashboard context:
{context_str[:6000]}

Last SQL (if any):
{(mem.last_sql or '')[:3000]}

Last result sample (JSON, may be empty):
{json.dumps(last_rows[:10], default=str)[:6000]}

Conversation (latest last):
{json.dumps((conversation_history or [])[-10:], default=str)[:6000]}

User follow-up:
{user_query}

Answer concisely using MARKDOWN formatting:
- Use **bold** for key numbers and terms
- Use bullet points for lists
- Use > blockquotes for key insights
- Use the correct currency symbol ($ for USD, ₩ for KRW, € for EUR, £ for GBP, or 3-letter code for others). Never use $ for non-USD values.
"""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=700,
        )
        return OrchestratorResult(
            reply=(resp.choices[0].message.content or "").strip() or "I couldn’t generate a response.",
            action=action,
            reason=reason,
            sql=mem.last_sql or "",
            rows_preview=last_rows[:30] if last_rows else None,
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info
        )

    # compare: run multiple subqueries, compare numeric summaries, then summarize differences
    if action == "compare":
        subqueries = _split_compare_query(client, user_query)
        if len(subqueries) < 2:
            action = "new"
        else:
            sql_db = sap_db or db
            knowledge = mem.knowledge()
            knowledge_context = "\n".join(str(v) for v in knowledge.values()) if knowledge else None
            datasets: List[Tuple[str, List[Dict[str, Any]]]] = []
            sqls: List[str] = []
            for sq in subqueries[:3]:
                few_shot = get_sql_examples_for_question(
                    sq, additional_examples=get_few_shot_examples(db, 2)
                )
                r = run_sap_sql_agent(
                    sq, sql_db,
                    knowledge_context=knowledge_context,
                    time_scope=time_scope,
                    few_shot_examples=few_shot,
                )
                if not r or not r.rows:
                    datasets.append((sq, []))
                    sqls.append(r.sql if r else "")
                else:
                    datasets.append((sq, r.rows))
                    sqls.append(r.sql)
            compare_summary = _compare_numeric(datasets)
            prompt = f"""
You are a data analyst. The user asked for a comparison:
"{user_query}"

We executed these sub-questions:
{json.dumps(subqueries, indent=2)}

Comparison summary (auto-computed numeric sums/means):
{json.dumps(compare_summary, indent=2)}

Write a DEEP comparison analysis using MARKDOWN formatting:
- Start with **executive summary** (biggest difference and business impact)
- Use ### main heading, #### subheadings for each comparison aspect
- Use **bold** for important differences, numbers, and percentages
- Include % change and absolute differences
- Use bullet points to organize findings
- Add > blockquote for the most important strategic insight
- Use the correct currency symbol per the data: $ for USD, ₩ for KRW, € for EUR, £ for GBP, or 3-letter code otherwise. Never use $ for non-USD values.
- Explain WHY the differences matter for business strategy
If data is missing for a dataset, mention it clearly.
"""
            
            try:
                # Use smart completion with best available model
                reply, model_used = smart_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4,
                    max_tokens=1200,
                    require_premium=True,
                )
                logger.info(f"💡 Comparison analysis using {model_used}")
            except Exception:
                # Fallback
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4,
                    max_tokens=800,
                )
                reply = (resp.choices[0].message.content or "").strip()
            # update memory to last dataset (helps follow-ups)
            last_sql = next((s for s in reversed(sqls) if s), "")
            last_rows = next((rows for _, rows in reversed(datasets) if rows), [])
            
            # Generate comparison charts
            charts_data = None
            try:
                if last_rows:
                    chart_specs = analyze_visualization_needs(last_rows, user_query, "compare", last_sql)
                    if chart_specs:
                        charts_data = chart_specs_to_json(chart_specs)
                        logger.info(f"Generated {len(charts_data)} comparison chart(s)")
            except Exception as chart_err:
                logger.warning(f"Comparison chart generation failed: {chart_err}")
            
            mem.last_user_query = user_query
            mem.last_sql = last_sql
            mem.last_rows_json = json.dumps(_rows_preview(last_rows, limit=80), default=str)
            save_memory(db, mem)
            return OrchestratorResult(
                reply=reply or "Comparison complete, but I couldn’t generate a narrative summary.",
                action="compare",
                reason=reason,
                sql=last_sql,
                rows_preview=_rows_preview(last_rows) if last_rows else None,
                compare={"subqueries": subqueries, "sqls": sqls, "summary": compare_summary},
                memory_updated=True,
                charts=charts_data,
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info
            )

    # reuse: re-run last SQL if we have it, otherwise treat as new
    if action == "reuse" and mem.last_sql:
        # In serverless, re-executing arbitrary SQL can be expensive/unreliable.
        # Prefer reusing the last cached rows preview for "reuse" answers; "new" will re-run via sap_sql_agent.
        rows_list = mem.last_rows()
        prompt = f"""
User asked: "{user_query}"

We are reusing the prior SQL:
```sql
{mem.last_sql}
```

Result preview JSON:
{json.dumps(_rows_preview(rows_list, limit=20), default=str)}

Explain the answer using MARKDOWN formatting (3-8 sentences):
- Use **bold** for key numbers
- Use bullet points if listing items
- Use the correct currency symbol: $ for USD, ₩ for KRW, € for EUR, £ for GBP, or 3-letter code for others. Never use $ for non-USD amounts.
If result is empty, say so and suggest a refined question.
"""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=650,
        )
        reply = (resp.choices[0].message.content or "").strip()
        mem.last_user_query = user_query
        mem.last_rows_json = json.dumps(_rows_preview(rows_list, limit=80), default=str)
        save_memory(db, mem)
        return OrchestratorResult(
            reply=reply or "Reused the prior query, but no response was generated.",
            action="reuse",
            reason=reason,
            sql=mem.last_sql,
            rows_preview=_rows_preview(rows_list) if rows_list else None,
            memory_updated=True,
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info
        )

    # new: run SAP SQL agent, store sql+rows and return summary.
    # IMPORTANT: semantic cache and pattern shortcuts are disabled for analysis answers
    # to guarantee fresh, question-specific SQL execution for every data query.
    timings["cache_lookup_ms"] = 0
    timings["pattern_matching_ms"] = 0
    timings["used_pattern"] = False

    sql_db = sap_db or db
    sql_start = time.time()

    result = None
    # Andy's training loop: check ai_query_memory first for user-approved queries
    try:
        from .ai_query_memory_service import find_similar_stored_query
        stored_sql = find_similar_stored_query(db, user_query, user_id)
        if stored_sql:
            from .sap_sql_agent import _quote_catalog_sql_tables, _run_sql, SqlAgentResult
            quoted_sql = _quote_catalog_sql_tables(stored_sql)
            stored_rows = _run_sql(sql_db, quoted_sql)
            if stored_rows:
                result = SqlAgentResult(sql=quoted_sql, rows=stored_rows)
                logger.info("ai_query_memory: reused stored SQL for %r (%d rows)", user_query[:60], len(stored_rows))
    except Exception as mem_err:
        logger.debug("ai_query_memory lookup failed: %s", mem_err)

    # Always go through the SAP SQL agent using live schema instead of predefined patterns.
    knowledge = mem.knowledge()
    knowledge_context = "\n".join(str(v) for v in knowledge.values()) if knowledge else None

    # Re-enabled few-shot examples: they help the LLM pick correct join patterns for
    # invoice/industry/customer queries. The SQL catalog fast-path handles generic
    # aggregation queries before LLM is called, so examples now only guide complex joins.
    _few_shot = get_sql_examples_for_question(
        user_query, additional_examples=get_few_shot_examples(db, 2)
    )

    # Procurement-from-list: "from the list below which are procured internally/externally" → use prior result materials
    try:
        from .invoice_bot_helpers import (
            is_from_list_below_procurement_query,
            get_material_numbers_from_dataframe,
            query_procurement_type_for_materials,
        )
        from .sap_sql_agent import _run_sql, SqlAgentResult
        last_rows = mem.last_rows()
        if is_from_list_below_procurement_query(user_query) and last_rows:
            matnrs = get_material_numbers_from_dataframe(last_rows)
            if matnrs:
                def _run_sql_fn(sql: str):
                    return _run_sql(sql_db, sql)
                proc_rows, proc_sql = query_procurement_type_for_materials(_run_sql_fn, matnrs)
                if proc_rows:
                    result = SqlAgentResult(sql=proc_sql, rows=proc_rows)
                    logger.info("Procurement-from-list: %d rows for %d materials", len(proc_rows), len(matnrs))
    except Exception as proc_err:
        logger.warning("Procurement-from-list check failed: %s", proc_err)

    if result is None:
        # 1) Schema-driven agent: LLM reads schema → selects tables → generates SQL (no keyword rules).
        try:
            result = run_schema_driven_sql_agent(user_query, sql_db, few_shot_examples=_few_shot)
            if result and getattr(result, "rows", None):
                logger.info("Schema-driven SQL agent returned %d rows", len(result.rows))
        except Exception as schema_err:
            logger.debug("Schema-driven agent failed: %s", schema_err)
        # 2) Fall back to adaptive (keyword/heuristic) then standard sap_sql_agent.
        if result is None or not getattr(result, "rows", None):
            result = run_adaptive_sap_sql_agent(
                user_query,
                sql_db,
                knowledge_context=knowledge_context,
                time_scope=time_scope,
                few_shot_examples=_few_shot,
            )
    if result is None or not (getattr(result, "rows", None)):
        logger.info("Adaptive SQL path returned no result; falling back to standard sap_sql_agent")
        result = run_sap_sql_agent(
            user_query,
            sql_db,
            knowledge_context=knowledge_context,
            time_scope=time_scope,
            few_shot_examples=_few_shot,
        )
    # Purchase-order direct fallback: when all agents fail and question is about purchase orders, run EKPO aggregate
    if result is None or not getattr(result, "rows", None):
        try:
            po_result = run_purchase_order_fallback(sql_db, user_query)
            if po_result and getattr(po_result, "rows", None):
                result = po_result
                logger.info("Purchase order fallback returned %d rows", len(po_result.rows))
        except Exception as po_err:
            logger.debug("Purchase order fallback failed: %s", po_err)
    timings["sql_execution_ms"] = int((time.time() - sql_start) * 1000)

    # ── Post-generation SQL sanitizers ──────────────────────────────────────────
    # Run both sanitizers on every result to fix known data-quality issues:
    #   1. gjahr='0000' for all rows → rewrite to FKDAT-based year expression
    #   2. SUM(netwr) bare → rewrite to safe NULLIF TEXT cast
    if result and getattr(result, "sql", None):
        _orig_sql = result.sql
        _clean_sql = sanitize_generated_sap_sql(_orig_sql)
        if _clean_sql != _orig_sql:
            logger.info("SQL sanitizers applied (gjahr→fkdat and/or netwr), re-executing")
            try:
                from .sap_sql_agent import _run_sql, SqlAgentResult
                _clean_rows = _run_sql(sql_db, _clean_sql)
                result = SqlAgentResult(sql=_clean_sql, rows=_clean_rows)
            except Exception as _sg_err:
                logger.warning("SQL sanitizer re-execution failed: %s", _sg_err)

    # FAGLFLEXA link fallback: when user asks to link profit center costs to customers/products
    # and the main query fails or returns 0 rows, return profit center costs only with a note
    if (result is None or not getattr(result, "rows", None)) or (result and not result.rows):
        _q = (user_query or "").lower()
        _is_fagl_link = (
            ("faglflexa" in _q or ("profit center" in _q and "cost" in _q))
            and any(x in _q for x in ("link", "back to", "attribute", "customers", "products", "major"))
        )
        if _is_fagl_link:
            try:
                from .sap_sql_agent import (
                    _resolve_faglflexa_table_and_mappings,
                    _run_faglflexa_cost_by_profit_center_sql,
                    _run_sql,
                    SqlAgentResult,
                )
                fagl_table, fagl_mappings = _resolve_faglflexa_table_and_mappings(sql_db)
                if fagl_table and fagl_mappings:
                    _last_24 = "last 24" in _q or "24 months" in _q
                    pc_result = _run_faglflexa_cost_by_profit_center_sql(
                        sql_db, fagl_table, last_24_months=_last_24, column_mappings=fagl_mappings
                    )
                    if pc_result:
                        _sql, _rows = pc_result
                        if _rows:
                            _note = (
                                "The database has no direct link between FAGLFLEXA (GL costs) and billing/customer data "
                                "for the requested period, or the link query returned no rows. "
                                "Below is the **cost by profit center** from FAGLFLEXA. "
                                "To see customers and products, use sales tables (VBRK, VBRP) separately."
                            )
                            result = SqlAgentResult(sql=_sql, rows=_rows)
                            user_query = f"{user_query}\n\n[Note to AI: {_note}]"
                            logger.info("FAGLFLEXA link fallback: returned profit center costs only (%d rows)", len(_rows))
            except Exception as fagl_err:
                logger.debug("FAGLFLEXA link fallback failed: %s", fagl_err)

    # Product-performance fallback: when both adaptive and standard return 0 rows, try known-good VBRK/VBRP/MAKT SQL
    if result and not result.rows:
        try:
            from .invoice_bot_helpers import get_product_performance_fallback_sql
            from .sap_sql_agent import _run_sql
            fallback_sql = get_product_performance_fallback_sql(user_query)
            if fallback_sql:
                fallback_rows = _run_sql(sql_db, fallback_sql)
                if fallback_rows:
                    logger.info("Product performance fallback returned %d rows", len(fallback_rows))
                    result = type(result)(sql=fallback_sql, rows=fallback_rows)
                else:
                    fallback_sql_all = get_product_performance_fallback_sql(user_query, with_date_filter=False)
                    if fallback_sql_all and fallback_sql_all != fallback_sql:
                        fallback_rows = _run_sql(sql_db, fallback_sql_all)
                        if fallback_rows:
                            result = type(result)(sql=fallback_sql_all, rows=fallback_rows)
        except Exception as fallback_err:
            logger.warning("Product performance fallback failed: %s", fallback_err)

    if not result or not result.rows:
        # Profit margin early fallback: when question clearly asks for profit margin, try catalog directly
        q_lower = (user_query or "").lower()
        margin_phrases = ("profit margin", "margin by product", "margin for all products", "product profitability")
        if any(p in q_lower for p in margin_phrases):
            try:
                from .sap_sql_agent import _get_sql_catalog, _quote_catalog_sql_tables, _run_sql, SqlAgentResult
                catalog = _get_sql_catalog()
                profit_entry = next((e for e in catalog if e.get("id") == "profit_margin_by_product"), None)
                if profit_entry and profit_entry.get("sql"):
                    quoted = _quote_catalog_sql_tables(profit_entry["sql"])
                    margin_rows = _run_sql(sql_db, quoted)
                    if margin_rows:
                        result = SqlAgentResult(sql=quoted, rows=margin_rows)
                        logger.info("Profit margin catalog fallback returned %d rows", len(margin_rows))
            except Exception as pm_err:
                logger.debug("Profit margin fallback failed: %s", pm_err)

    # Catalog fallback: when all LLM paths and other fallbacks failed, try pre-built sql_catalog.
        if not (result and result.rows):
            try:
                from .sap_sql_agent import _lookup_sql_catalog, _quote_catalog_sql_tables, _run_sql, SqlAgentResult
                catalog_sql = _lookup_sql_catalog(user_query)
                if catalog_sql:
                    quoted_sql = _quote_catalog_sql_tables(catalog_sql)
                    catalog_rows = _run_sql(sql_db, quoted_sql)
                    if catalog_rows:
                        result = SqlAgentResult(sql=quoted_sql, rows=catalog_rows)
                        logger.info("SQL catalog fallback returned %d rows for: %r", len(catalog_rows), user_query[:60])
            except Exception as catalog_err:
                logger.debug("SQL catalog fallback failed: %s", catalog_err)

    if not result or not result.rows:
        q_lower = (user_query or "").lower()
        knowledge = mem.knowledge()
        knowledge_str = " ".join(str(v) for v in knowledge.values()).lower()
        sql_query = result.sql if result else ""
        
        # Diagnostic for year-specific queries
        if any(year in q_lower for year in ["2024", "2023", "2025", "2022", "year"]) and sql_query:
            logger.warning(f"⚠️ Year-specific query returned no data. SQL:\n{sql_query}")
            
            # Try diagnostic to check if ANY 2024 data exists
            try:
                diag_sql = 'SELECT MIN("FKDAT") as min_date, MAX("FKDAT") as max_date, COUNT(*) as count FROM "VBRK"'
                diag_result = db.execute(text(diag_sql)).fetchone()
                if diag_result:
                    logger.info(f"🔍 VBRK date range: {diag_result[0]} to {diag_result[1]}, count: {diag_result[2]}")
            except Exception:
                pass
        
        # If user asked about costs and primary query returned no rows, try two intelligent fallbacks:
        # 1) Search KEKO (standard cost estimate) for the product by name — most accurate unit cost source
        # 2) Search VBRP + MAKT (sales data) to show the selling price as a useful proxy
        # Only if BOTH return nothing do we show a helpful "not found" explanation.
        cost_related = any(w in q_lower for w in ("cost", "costing", "price", "how much", "what is the cost"))
        # Detect if the question is about a SPECIFIC named product (not a bulk aggregation query).
        # Exclude: SAP table names, generic aggregation words, SQL keywords.
        _GENERIC_WORDS = {
            "cost", "price", "know", "what", "from", "show", "tell", "does", "have", "much",
            "this", "that", "total", "purchased", "quantity", "each", "material", "materials",
            "using", "ekpo", "ekko", "rbkp", "rseg", "vbrp", "vbrk", "makt", "faglflexa",
            "keko", "ckis", "coep", "bsad", "ckmlcr", "marc", "resb", "konv", "likp", "lips",
            "highest", "lowest", "average", "count", "list", "products", "vendors", "customers",
            "across", "plants", "years", "periods", "fiscal", "plant", "year", "month",
            "purchase", "purchasing", "sales", "billing", "invoice", "orders", "order", "items",
            "standard", "actual", "planned", "data", "table", "tables", "query", "show", "give",
        }
        # Named-table queries (e.g. "using EKPO") are NEVER product-specific cost searches
        _named_table = any(
            w.upper() in {"EKPO", "EKKO", "RBKP", "RSEG", "VBRP", "VBRK", "FAGLFLEXA",
                          "KEKO", "CKIS", "COEP", "BSAD", "CKMLCR", "MARC", "RESB"}
            for w in re.split(r"\W+", user_query)
        )
        _product_keywords = [w for w in re.split(r"\W+", user_query)
                             if len(w) >= 4 and w.lower() not in _GENERIC_WORDS]
        # A query is product-specific only when it names a specific item AND doesn't name SAP tables
        is_product_specific = bool(_product_keywords) and not _named_table
        # Do NOT treat "profit center" / "cost by profit center" as a product name — it's an accounting dimension
        if "profit center" in q_lower or "profit centre" in q_lower or "cost by profit" in q_lower:
            is_product_specific = False
        # Do NOT treat "cost of manufacturing" / "costs of manufacturing" as product search — it's CKIS/KEKO cost data
        if any(phrase in q_lower for phrase in (
            "cost of manufacturing", "costs of manufacturing", "manufacturing cost",
            "cost of manufacturings", "manufacturing costs", "production cost"
        )):
            is_product_specific = False
        # Do NOT treat "profit margin" as product search — it's margin analysis (VBRP+CKIS)
        if "profit margin" in q_lower or "margin by product" in q_lower or "margin analysis" in q_lower:
            is_product_specific = False

        if cost_related and is_product_specific:
            # Build a natural-language product search term from the question keywords
            product_hint = " ".join(_product_keywords[:4])

            # --- Fallback 1: KEKO standard cost for this product ---
            keko_question = f"standard cost from KEKO for product matching {product_hint}"
            logger.info(f"🔄 Primary cost query returned no rows. Trying KEKO fallback for: {product_hint}")
            keko_result = run_sap_sql_agent(
                keko_question, sql_db,
                knowledge_context=knowledge_context,
                max_retries=1,
                time_scope="both",
            )
            if keko_result and keko_result.rows:
                logger.info(f"✅ KEKO fallback returned {len(keko_result.rows)} rows")
                result = keko_result  # use this result going forward; falls through to summarization below
            else:
                # --- Fallback 2: VBRP + MAKT to show sales price as a reference ---
                vbrp_question = f"sales price and total sales from VBRP for product matching {product_hint}"
                logger.info(f"🔄 KEKO returned no rows. Trying VBRP sales price fallback for: {product_hint}")
                vbrp_result = run_sap_sql_agent(
                    vbrp_question, sql_db,
                    knowledge_context=knowledge_context,
                    max_retries=1,
                    time_scope="both",
                )
                if vbrp_result and vbrp_result.rows:
                    logger.info(f"✅ VBRP fallback returned {len(vbrp_result.rows)} rows — presenting as sales price proxy")
                    result = vbrp_result
                    # Inject a note so the summarizer knows this is sales price, not purchase cost
                    user_query = (
                        f"{user_query}\n\n"
                        "[Note to AI: The database has no purchase order (EKPO) or standard cost (KEKO) records "
                        "for this product. The data below is from SALES (VBRP) and shows the SELLING PRICE, "
                        "not the purchase cost. Please clearly state this distinction in your answer.]"
                    )
                else:
                    # Nothing found in any table — give a clear, helpful explanation
                    search_term = _product_keywords[0] if _product_keywords else product_hint
                    fallback_reply = (
                        f"I searched for **{product_hint}** across the cost tables (EKPO, RBKP, RSEG), "
                        "the standard cost estimates (KEKO), and the sales billing data (VBRP), "
                        "but found no matching records in any of these tables.\n\n"
                        "This can happen when:\n"
                        f"- The product name spelling differs from what's in the database "
                        f"(try a shorter or exact term, e.g. search MAKT for the correct material description)\n"
                        "- The material has no purchase orders or cost estimates recorded\n"
                        f"- You can also ask: **\"Show all products containing '{search_term}' from MAKT\"** to find the exact material name"
                    )
                    mem.last_user_query = user_query
                    save_memory(db, mem)
                    return OrchestratorResult(
                        reply=fallback_reply,
                        action="new",
                        reason=reason or "cost_query_all_fallbacks_empty",
                        sql=result.sql if result else "",
                        rows_preview=None,
                        memory_updated=True,
                        time_scope=time_scope,
                        date_range=date_range,
                        period_info=period_info
                    )
        # ── Generic retry: if query named specific tables or asked for customer/listing data
        # and returned 0 rows, retry once with a simplified rephrasing so the agent can
        # choose a different strategy (e.g. drop KNA1, use VBRK.kunag directly, etc.)
        if result and result.sql and not context_str.strip():
            _simplify_hints = []
            if any(w in q_lower for w in ("customer", "by customer", "customers")):
                _simplify_hints.append(
                    "Try grouping by VBRK.kunag (customer number) directly instead of joining KNA1. "
                    "If KNA1 has no matching records, skip the KNA1 join entirely."
                )
            if any(w in q_lower for w in ("country", "by country", "land1")):
                _simplify_hints.append(
                    "Use VBRK.land1 for country instead of KNA1.land1 — VBRK has its own land1 column."
                )
            if _simplify_hints:
                _simplified_q = (
                    user_query + "\n\n[Note: Previous SQL returned 0 rows. "
                    + " ".join(_simplify_hints)
                    + " Remove any IS NOT NULL filters that convert LEFT JOINs to INNER JOINs.]"
                )
                logger.info("🔄 Retrying with simplified strategy for zero-row result: %s", _simplify_hints)
                retry_result = run_sap_sql_agent(
                    _simplified_q, sql_db,
                    knowledge_context=knowledge_context,
                    max_retries=1,
                    time_scope="both",
                )
                if retry_result and retry_result.rows:
                    logger.info(f"✅ Simplified retry returned {len(retry_result.rows)} rows")
                    result = retry_result

        # NOTE: context_str fallback intentionally removed.
        # Answering a new question from old dashboard context caused completely wrong results
        # (e.g. a FAGLFLEXA query being answered with cached VBRK/sales data).
        # Each query must get its own fresh SQL result. If SQL returns 0 rows, tell the user clearly.

        # If we have no SQL result: Andy's training loop — try catalog first, then ChatGPT fallback
        if not (result and result.rows):
            sql_attempted = result.sql if result else ""
            proposed_sql = None
            # 1) Try sql_catalog first — has correct SQL for "highest spend by vendor", etc.
            try:
                from .sap_sql_agent import _lookup_sql_catalog, _quote_catalog_sql_tables
                from .ai_query_memory_service import validate_sql_for_safe_execution
                catalog_sql = _lookup_sql_catalog(user_query)
                if catalog_sql:
                    quoted = _quote_catalog_sql_tables(catalog_sql)
                    is_valid, err = validate_sql_for_safe_execution(quoted)
                    if is_valid:
                        proposed_sql = quoted
            except Exception:
                pass
            # 2) ChatGPT fallback: when catalog has no match, ask OpenAI to propose SQL
            if not proposed_sql:
                try:
                    from .schema_loader import get_schema_text
                    from .ai_query_memory_service import validate_sql_for_safe_execution
                    schema_text = get_schema_text(sql_db, include_semantic_map=True)
                    # Build entity filter hint so ChatGPT uses ILIKE (not exact match)
                    _chatgpt_entity_hint = ""
                    try:
                        from .invoice_bot_helpers import get_specific_entity_request
                        _ce = get_specific_entity_request(user_query)
                        if _ce and _ce.get("value"):
                            _cv = _ce["value"].replace("'", "''")
                            if _ce.get("entity") == "customer":
                                _chatgpt_entity_hint = (
                                    f'\n- ENTITY FILTER (CRITICAL): The question asks about customer "{_ce["value"]}".'
                                    f' You MUST use: WHERE "KNA1".name1 ILIKE \'%{_cv}%\''
                                    f' with JOIN "KNA1" ON "VBRK".kunag = "KNA1".kunnr'
                                    f' and JOIN "VBRP" ON "VBRK".vbeln = "VBRP".vbeln.'
                                    f' NEVER use exact = match for customer names — always use ILIKE.'
                                )
                            elif _ce.get("entity") == "vendor":
                                _chatgpt_entity_hint = (
                                    f'\n- ENTITY FILTER (CRITICAL): The question asks about vendor "{_ce["value"]}".'
                                    f' You MUST use: WHERE "LFA1".name1 ILIKE \'%{_cv}%\''
                                    f' with JOIN "LFA1" ON "RBKP".lifnr = "LFA1".lifnr.'
                                    f' NEVER use exact = match for vendor names — always use ILIKE.'
                                )
                            elif _ce.get("entity") == "product":
                                _chatgpt_entity_hint = (
                                    f'\n- ENTITY FILTER (CRITICAL): The question asks about product "{_ce["value"]}".'
                                    f' You MUST use: WHERE "MAKT".maktx ILIKE \'%{_cv}%\' AND "MAKT".spras = \'E\''
                                    f' with JOIN "MAKT" ON "VBRP".matnr = "MAKT".matnr.'
                                    f' NEVER use exact = match for product names — always use ILIKE.'
                                )
                    except Exception:
                        pass
                    prompt = f"""You are an SAP SQL expert. The user asked: "{user_query}"

Database schema (PostgreSQL, table names may need double quotes for uppercase):
{schema_text[:6000]}

Generate a single PostgreSQL SELECT query to answer this. Rules:
- Use only SELECT, JOIN, GROUP BY, ORDER BY, LIMIT
- No DELETE, UPDATE, DROP, INSERT
- Quote uppercase table names: "VBRP", "VBRK", "MAKT", etc.{_chatgpt_entity_hint}
- YEAR FILTERING (CRITICAL): VBRK.gjahr stores '0000' in this DB — NEVER use it for year queries. ALWAYS filter by fkdat: SUBSTRING(TRIM(r."fkdat"), 1, 4) = '2000' for year 2000, or fkdat BETWEEN '20000101' AND '20001231'. Never use gjahr.
- VBRP.netwr is TEXT — cast with NULLIF(TRIM(v."netwr"::text), '')::NUMERIC.
- CKIS TEXT COLUMNS (CRITICAL): The CKIS.wertn and CKIS.gpreis columns are stored as TEXT, not numeric. NEVER use COALESCE(wertn, 0) — it fails with type mismatch. ALWAYS cast with: SUM(NULLIF(TRIM(wertn::text), '')::NUMERIC). Safe subquery: (SELECT matnr, SUM(NULLIF(TRIM(wertn::text), '')::NUMERIC) AS total_cost FROM "CKIS" GROUP BY matnr) c.
- For profit margin: revenue from vbrp.netwr (cast via NULLIF(TRIM(netwr::text),'')::NUMERIC), cost from CKIS subquery above. Join vbrp→MAKT for product name, vbrp→CKIS on matnr.
- NEVER use SQLAlchemy bind parameters (%(year)s, :year) — always inline literal values.
- Return ONLY a single SELECT statement. No multiple statements, no comments, no markdown."""
                    resp = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=800,
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    # Extract SQL (remove markdown if present)
                    if "```" in raw:
                        import re as _re
                        m = _re.search(r"```(?:\w+)?\s*([\s\S]*?)```", raw)
                        if m:
                            raw = m.group(1).strip()
                    proposed_sql = raw if raw and "SELECT" in raw.upper() else None
                    if proposed_sql:
                        is_valid, err = validate_sql_for_safe_execution(proposed_sql)
                        if not is_valid:
                            proposed_sql = None
                            logger.warning("ChatGPT proposed invalid SQL: %s", err)
                except Exception as chat_err:
                    logger.debug("ChatGPT fallback failed: %s", chat_err)

            # --- Entity diagnostic: check if the named entity actually exists in the DB
            # before offering ChatGPT SQL or a bare "no data" message.
            _entity_diag_msg = ""
            try:
                from .invoice_bot_helpers import get_specific_entity_request
                from .sap_sql_agent import _diagnose_entity_no_results
                _diag_entity = get_specific_entity_request(user_query)
                if _diag_entity and _diag_entity.get("value"):
                    _entity_diag_msg = _diagnose_entity_no_results(
                        sql_db, _diag_entity.get("entity", ""), _diag_entity.get("value", "")
                    )
                    if _entity_diag_msg:
                        logger.info("entity diagnostic: %s", _entity_diag_msg[:160])
            except Exception as _diag_ex:
                logger.debug("entity diagnostic error: %s", _diag_ex)

            if proposed_sql:
                return OrchestratorResult(
                    reply=(
                        "I couldn't generate a query automatically, but I have a suggested SQL from ChatGPT. "
                        "**Review it below and click Approve** to run it and save it for future similar questions. "
                        "Or try rephrasing your question."
                        + (f"\n\n⚠️ {_entity_diag_msg.strip()}" if _entity_diag_msg else "")
                    ),
                    action="new",
                    reason="chatgpt_fallback_needs_approval",
                    sql=sql_attempted,
                    time_scope=time_scope,
                    date_range=date_range,
                    period_info=period_info,
                    needs_approval=True,
                    proposed_sql=proposed_sql,
                )

            return OrchestratorResult(
                reply=(
                    "No data was found for that query. "
                    + ("The SQL ran but returned 0 rows — the table may not have matching records for those filters. " if sql_attempted else "A SQL query could not be generated for this request. ")
                    + ("" if not _entity_diag_msg else _entity_diag_msg + " ")
                    + "Try rephrasing with a specific table name, material, customer, plant, or time period."
                ),
                action="new",
                reason=reason or "sap_sql_agent_no_result",
                sql=sql_attempted,
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info
            )
        # result now has rows (from the simplified retry) — fall through to summarization below.

    # Invoice-bot result shaping: dedupe, aggregate by customer, filter by product name, apply display labels
    try:
        from .invoice_bot_helpers import (
            deduplicate_material_price_rows,
            deduplicate_supplier_per_part_rows,
            aggregate_by_customer_sales,
            filter_dataframe_by_specific_entity_if_requested,
            apply_procurement_type_display,
            apply_industry_display,
            is_sales_by_customer_query,
        )
        rows = result.rows
        rows, _ = deduplicate_material_price_rows(rows)
        rows, _ = deduplicate_supplier_per_part_rows(rows)
        if is_sales_by_customer_query(user_query):
            rows, _ = aggregate_by_customer_sales(rows)
        rows = filter_dataframe_by_specific_entity_if_requested(user_query, rows)
        rows = apply_procurement_type_display(rows)
        rows = apply_industry_display(rows)
        result = type(result)(sql=result.sql, rows=rows)
    except Exception as shape_err:
        logger.warning("Result shaping failed: %s", shape_err)

    # Summarize rows with LLM.
    # IMPORTANT: All numeric values and rankings MUST come from the SQL result rows only.
    # We do NOT allow the model to invent numbers or reuse stale narrative context.
    preview = _rows_preview(result.rows, limit=20)

    # Analytics layer: KPIs + executive insights (lightweight, after SQL execution)
    metrics_out = None
    analytics_insights_out = None
    try:
        from ..analytics import compute_metrics, generate_analytics_insights, generate_chart_from_rows
        metrics_out = compute_metrics(result.rows)
        analytics_insights_out = generate_analytics_insights(
            user_query, result.rows, metrics=metrics_out, sql=result.sql
        )
    except Exception as analytics_err:
        logger.debug("Analytics layer skipped: %s", analytics_err)

    # Extra safety: if the user asks about a very specific term (like "Harley leather jacket"
    # or "cost of the jacket") and that term never appears in any row (material/product/description),
    # we should clearly say that the precise item-level answer is not available instead of
    # talking about unrelated aggregates (e.g. vendor totals).
    q_tokens = {t for t in re.split(r"\W+", (user_query or "").lower()) if t}
    specific_entity = None
    try:
        from .invoice_bot_helpers import get_specific_entity_request
        specific_entity = get_specific_entity_request(user_query)
    except Exception:
        specific_entity = None
    focus_terms = {t for t in q_tokens if len(t) >= 4}
    if specific_entity and specific_entity.get("value"):
        focus_terms = {specific_entity["value"].lower()}
    row_text = " ".join(json.dumps(r, default=str).lower() for r in preview) if preview else ""
    missing_focus = focus_terms and not any(term in row_text for term in focus_terms)
    asks_for_cost = any(w in q_tokens for w in {"cost", "price", "margin"})
    if specific_entity and missing_focus:
        # Before giving up, attempt one targeted retry with an explicit filter instruction embedded
        # in the question. This catches cases where the first SQL pass missed the entity filter.
        _entity_type = specific_entity.get("entity", "item")
        _entity_val = specific_entity.get("value", "")
        _retry_result = None
        try:
            if _entity_type == "customer":
                _filter_hint = (
                    f" [MANDATORY: Filter WHERE KNA1.name1 ILIKE '%{_entity_val}%',"
                    f" JOIN KNA1 ON VBRK.kunag = KNA1.kunnr if not already joined.]"
                )
            elif _entity_type == "vendor":
                _filter_hint = (
                    f" [MANDATORY: Filter WHERE LFA1.name1 ILIKE '%{_entity_val}%',"
                    f" JOIN LFA1 ON RBKP.lifnr = LFA1.lifnr if not already joined.]"
                )
            elif _entity_type == "product":
                _filter_hint = (
                    f" [MANDATORY: Filter WHERE MAKT.maktx ILIKE '%{_entity_val}%' AND MAKT.spras = 'E',"
                    f" JOIN MAKT ON fact_table.matnr = MAKT.matnr if not already joined.]"
                )
            else:
                _filter_hint = f" [MANDATORY: Filter results to only include '{_entity_val}'.]"
            _augmented_q = user_query + _filter_hint
            logger.info(
                "missing_focus retry: entity '%s' not in rows, retrying with explicit filter hint for %s",
                _entity_val, _entity_type,
            )
            _retry_result = run_schema_driven_sql_agent(_augmented_q, sql_db, few_shot_examples=_few_shot)
            if not (_retry_result and _retry_result.rows):
                _retry_result = run_sap_sql_agent(_augmented_q, sql_db, max_retries=1)
        except Exception as _retry_err:
            logger.debug("missing_focus entity retry failed: %s", _retry_err)

        if _retry_result and _retry_result.rows:
            # Retry succeeded — update result and allow normal summarisation to proceed
            logger.info("missing_focus retry succeeded with %d rows", len(_retry_result.rows))
            result = _retry_result
            preview = _rows_preview(result.rows, limit=20)
            # Re-evaluate missing_focus with the new rows
            _new_row_text = " ".join(json.dumps(r, default=str).lower() for r in preview) if preview else ""
            missing_focus = focus_terms and not any(term in _new_row_text for term in focus_terms)

        if missing_focus:
            # Retry still didn't place the entity in rows — return the informative message
            safe_reply = (
                "I ran a fresh SQL query, but the returned rows do not contain the specific "
                f"{_entity_type} you asked about ({_entity_val}). "
                "The result is still broader than the question, so I cannot give a reliable item-level answer from it. "
                "The SQL needs an explicit filter for that exact record."
            )
            timings["summarization_ms"] = 0
            timings["insights_model"] = None
            mem.last_user_query = user_query
            mem.last_sql = result.sql
            mem.last_rows_json = json.dumps(preview, default=str)
            mem.last_reply = safe_reply
            mem.last_charts_json = "[]"
            save_memory(db, mem)
            total_time = int((time.time() - perf_start) * 1000)
            timings["total_ms"] = total_time
            timings["row_count"] = len(result.rows)
            timings["chart_count"] = 0
            timings["used_cache"] = False
            return OrchestratorResult(
                reply=safe_reply,
                action="new",
                reason=reason or "specific_entity_not_present_in_rows",
                sql=result.sql,
                rows_preview=preview,
                memory_updated=True,
                charts=None,
                performance=timings,
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info,
            )
    if asks_for_cost and missing_focus:
        safe_reply = (
            "I ran a fresh SQL query, but the returned rows do not contain the specific item or text you asked about "
            f"(for example: {', '.join(sorted(list(focus_terms)))}). "
            "The result set only has higher-level aggregates (such as vendor or total costs), "
            "so I cannot give an accurate cost for that exact jacket or product from this data. "
            "You may need a query that filters by the product code or material number for that jacket."
        )
        timings["summarization_ms"] = 0
        timings["insights_model"] = None
        mem.last_user_query = user_query
        mem.last_sql = result.sql
        mem.last_rows_json = json.dumps(preview, default=str)
        mem.last_reply = safe_reply
        mem.last_charts_json = "[]"
        save_memory(db, mem)
        total_time = int((time.time() - perf_start) * 1000)
        timings["total_ms"] = total_time
        timings["row_count"] = len(result.rows)
        timings["chart_count"] = 0
        timings["used_cache"] = False
        return OrchestratorResult(
            reply=safe_reply,
            action="new",
            reason=reason or "specific_item_not_present_in_rows",
            sql=result.sql,
            rows_preview=preview,
            memory_updated=True,
            charts=None,
            performance=timings,
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info,
        )
    
    # Summarize results with BEST available model for deep, reliable insights
    summary_start = time.time()
    
    # Use configured model or auto-select best available
    if AI_INSIGHTS_MODEL and AI_INSIGHTS_MODEL != "auto":
        # User specified a model
        insights_model = AI_INSIGHTS_MODEL
        logger.info(f"📌 Using user-configured model: {insights_model}")
    else:
        # Auto-select best model
        insights_model = get_best_available_model()
    
    prompt = f"""
You are an expert SAP sales/finance analyst.

User question:
{user_query}

SQL executed:
```sql
{result.sql}
```

Result preview as JSON (this is the ONLY source of truth for numbers):
{json.dumps(preview, default=str)}

STRICT RULES (do NOT break these):
- All numeric values, rankings, and comparisons MUST come directly from the rows above.
- Do NOT reuse or copy text from any previous answer or dashboard.
- Do NOT invent totals, averages, or percentages that cannot be computed from these rows.
- If a value is not visible in the rows, say that you cannot see it instead of guessing.

Write a clear MARKDOWN answer:
1. **Executive summary** (2–4 sentences; if there are date columns, mention the overall period covered).
2. **Detailed points**:
   - Use bullet points.
   - Highlight top/bottom items that are visible in the rows.
   - Use **bold** for key figures.
   - CRITICAL: Use the correct currency symbol based on the 'currency' column in the data rows.
     * USD → $  (e.g. $95,200)
     * KRW → ₩  (e.g. ₩2,700,000,000) — NEVER show KRW amounts with $
     * EUR → €  (e.g. €50,000)
     * GBP → £  (e.g. £30,000)
     * Any other currency → prefix with the 3-letter code (e.g. AUD 12,000)
     * If multiple currencies exist in the data, show each with its own correct symbol.
     * Do NOT default to $ unless the currency column actually says "USD".
3. **Short recommendation** (1–2 sentences) in a blockquote.
"""
    
    try:
        # Use smart completion with automatic fallback
        reply, model_used = smart_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=1500,
            require_premium=True,
        )
        logger.info(f"💡 Generated insights using {model_used}")
        insights_model = model_used
    except Exception as model_err:
        logger.error(f"❌ All premium models failed: {model_err}")
        # Final fallback to standard OpenAI
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=800,
        )
        reply = (resp.choices[0].message.content or "").strip()
        insights_model = "gpt-4o-mini (emergency fallback)"
    
    timings["summarization_ms"] = int((time.time() - summary_start) * 1000)
    timings["insights_model"] = insights_model

    # Prepend analytics layer: executive summary + key metrics (if available)
    if analytics_insights_out and reply:
        summary = (analytics_insights_out.get("executive_summary") or "").strip()
        key_metrics = analytics_insights_out.get("key_metrics") or []
        if summary:
            reply = f"**Executive Summary**\n{summary}\n\n{reply}"
        if key_metrics:
            kpi_block = "**Key Metrics**\n" + "\n".join(f"- {m}" for m in key_metrics[:8])
            reply = f"{kpi_block}\n\n{reply}"

    # Generate charts for visualization
    charts_data = None
    try:
        chart_start = time.time()
        logger.info(f"📊 Attempting chart generation for query with {len(result.rows)} rows")
        chart_specs = analyze_visualization_needs(result.rows, user_query, "new", result.sql)
        timings["chart_generation_ms"] = int((time.time() - chart_start) * 1000)
        
        if chart_specs:
            charts_data = chart_specs_to_json(chart_specs)
            logger.info(f"✅ Generated {len(charts_data)} chart(s) for user query")
            logger.info(f"Chart types: {[c.get('chart_type') for c in charts_data]}")
            
            # Debug: Log chart structure to help diagnose issues
            for idx, chart in enumerate(charts_data):
                chart_type = chart.get('chart_type')
                sample_data = chart.get('data', [])[:2] if chart.get('data') else []
                logger.info(f"📊 Chart {idx+1}: type={chart_type}, name_key={chart.get('name_key')}, value_key={chart.get('value_key')}, x_key={chart.get('x_key')}, y_keys={chart.get('y_keys')}")
                if sample_data:
                    logger.info(f"   Sample data keys: {list(sample_data[0].keys()) if sample_data else 'none'}")
        else:
            logger.info("⚠️ No charts generated - analyze_visualization_needs returned empty list")
        # Analytics layer fallback: one auto bar chart if no chart specs
        if (not charts_data or len(charts_data) == 0):
            try:
                from ..analytics import generate_chart_from_rows
                auto_chart = generate_chart_from_rows(result.rows, title="Result", return_base64=True)
                if auto_chart:
                    charts_data = [auto_chart]
                    logger.info("Analytics layer: added auto bar chart")
            except Exception as ac_err:
                logger.debug("Auto chart fallback skipped: %s", ac_err)
    except Exception as chart_err:
        logger.error(f"❌ Chart generation failed: {chart_err}", exc_info=True)
        timings["chart_generation_ms"] = 0

    # Invoice-bot: dynamic analysis plan, insights from all providers, COGS explanation, single-material cost summary
    analysis_plan_out = None
    insights_out = None
    reply_extra: List[str] = []
    try:
        from .invoice_bot_helpers import (
            get_dynamic_analysis_plan,
            perform_analysis_from_plan,
            get_insights_from_all_providers,
            pick_best_analysis,
            get_cogs_calculation_answer_if_asked,
            get_single_material_cost_summary,
        )
        # Analysis plan (calculations, visualizations, data_notes)
        plan = get_dynamic_analysis_plan(user_query, result.rows, client)
        if plan:
            analysis_plan_out = perform_analysis_from_plan(result.rows, plan, user_query)
        # Multi-provider insights and best analysis
        all_insights = get_insights_from_all_providers(
            user_query, result.rows, client,
            sql_query=result.sql,
        )
        if all_insights:
            best_provider, best_text, alternatives = pick_best_analysis(user_query, all_insights, client)
            insights_out = {"best_provider": best_provider, "best_text": best_text, "alternatives": alternatives}
            if best_text and "No provider" not in best_provider:
                reply_extra.append(f"\n\n### Insights ({best_provider})\n{best_text}")
        # COGS explanation when user asks how cost of goods is calculated
        cogs_answer = get_cogs_calculation_answer_if_asked(user_query, result.rows)
        if cogs_answer:
            reply_extra.append(f"\n\n### How cost of goods is calculated\n{cogs_answer}")
        # Single-material cost summary when result has one material
        cost_summary = get_single_material_cost_summary(user_query, result.rows)
        if cost_summary:
            lines = [f"**Material number:** {cost_summary.get('material_number', '')}"]
            if cost_summary.get("description"):
                lines.append(f"**Description:** {cost_summary['description']}")
            for f in cost_summary.get("fields", []):
                lines.append(f"**{f.get('label', '')}:** {f.get('value', '')}")
            if cost_summary.get("note"):
                lines.append(cost_summary["note"])
            reply_extra.append("\n\n### Cost for product number\n" + "\n".join(lines))
    except Exception as inv_err:
        logger.warning("Invoice-bot analysis/insights/COGS failed: %s", inv_err)

    # Analytics layer: recommendations and insights bullets
    if analytics_insights_out:
        recs = analytics_insights_out.get("recommendations") or []
        insights_bullets = analytics_insights_out.get("insights") or []
        if recs:
            reply_extra.append("\n\n### Recommendations\n" + "\n".join(f"- {r}" for r in recs[:5]))
        if insights_bullets and not any("Insights" in x for x in reply_extra):
            reply_extra.append("\n\n### Insights\n" + "\n".join(f"- {i}" for i in insights_bullets[:5]))

    if reply_extra:
        reply = (reply or "") + "".join(reply_extra)

    mem.last_user_query = user_query
    mem.last_sql = result.sql
    mem.last_rows_json = json.dumps(_rows_preview(result.rows, limit=80), default=str)
    mem.last_reply = reply  # Save the AI-generated reply for instant reuse
    mem.last_charts_json = json.dumps(charts_data or [], default=str)  # Save charts for reuse
    save_memory(db, mem)

    # Log to training data for fine-tuning
    try:
        log_query_execution(
            db=db,
            user_id=user_id,
            user_query=user_query,
            sql_query=result.sql,
            result_summary=reply,
            action_type="new",
            metadata={
                "rows_count": len(result.rows),
                "has_charts": bool(charts_data),
                "chart_count": len(charts_data) if charts_data else 0,
            },
        )
    except Exception as log_err:
        logger.warning(f"Failed to log training data: {log_err}")

    # Cache the result for future queries
    try:
        cache_query_result(
            db=db,
            query_text=user_query,
            sql_query=result.sql,
            result_summary=reply,
            result_preview=preview,
            charts=charts_data,
            ttl_hours=24,
        )
    except Exception as cache_err:
        logger.warning(f"Failed to cache query result: {cache_err}")

    # Calculate total time and compile performance metrics
    total_time = int((time.time() - perf_start) * 1000)
    timings["total_ms"] = total_time
    timings["row_count"] = len(result.rows)
    timings["chart_count"] = len(charts_data) if charts_data else 0
    timings["used_cache"] = False
    
    logger.info(f"⏱️ Query performance: {total_time}ms (action: {timings.get('action_decision_ms', 0)}ms, sql: {timings.get('sql_execution_ms', 0)}ms, summary: {timings.get('summarization_ms', 0)}ms, charts: {timings.get('chart_generation_ms', 0)}ms)")

    return OrchestratorResult(
        reply=reply or "Query executed, but I couldn’t generate a summary.",
        action="new",
        reason=reason,
        sql=result.sql,
        rows_preview=preview,
        memory_updated=True,
        charts=charts_data,
        performance=timings,
        time_scope=time_scope,
        date_range=date_range,
        period_info=period_info,
        insights=insights_out,
        analysis_plan=analysis_plan_out,
        metrics=metrics_out,
        analytics_insights=analytics_insights_out,
    )


def orchestrator_payload(result: OrchestratorResult) -> Dict[str, Any]:
    payload = asdict(result)
    # keep payload small and frontend-safe
    if payload.get("rows_preview") is not None and len(payload["rows_preview"]) > 30:
        payload["rows_preview"] = payload["rows_preview"][:30]
    # Keep performance metrics
    if payload.get("performance"):
        logger.debug(f"Performance data: {payload['performance']}")
    return payload
