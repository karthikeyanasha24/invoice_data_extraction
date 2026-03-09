import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy.orm import Session

from ..config.config import OPENAI_API_KEY, AI_INSIGHTS_MODEL, AI_FAST_MODEL
from .ai_analysis_memory_store import AiAnalysisMemory, load_memory, save_memory, upsert_knowledge
from .sap_sql_agent import run_sap_sql_agent, _serialize_value  # type: ignore
from .ai_chart_generator import analyze_visualization_needs, chart_specs_to_json
from .training_data_collector import log_query_execution, get_few_shot_examples
from .sql_example_library import get_sql_examples_for_question
from .query_cache import find_similar_cached_query, cache_query_result
from .multi_llm_client import get_multi_llm_client, get_best_available_model, smart_chat_completion

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
    
    # ULTRA-FAST PATH: If exact same query was just asked, reuse immediately from memory
    if mem.last_user_query and mem.last_user_query.strip().lower() == user_query.strip().lower():
        last_rows = mem.last_rows()
        last_charts = mem.last_charts()
        if last_rows and mem.last_sql:
            logger.info(f"⚡ INSTANT REUSE: exact same query as last request ({len(last_rows)} rows, {len(last_charts)} charts)")
            # Use cached reply or regenerate from data
            cached_reply = mem.last_reply or "Based on the previous analysis, here are the results:"
            return OrchestratorResult(
                reply=cached_reply,
                action="reuse-instant",
                reason="exact_query_repeat",
                sql=mem.last_sql,
                rows_preview=_rows_preview(last_rows, limit=30),
                charts=last_charts if last_charts else None,
                memory_updated=False,
                performance={"total_ms": 50, "used_cache": True, "instant_reuse": True},
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info
            )
    
    # If user clearly says "Remember:" or "Save this:", always treat as knowledge (don't run SQL).
    if _is_explicit_knowledge_instruction(user_query):
        action, reason = "knowledge", "explicit_save_instruction"
        timings["action_decision_ms"] = 0
    else:
        action_start = time.time()
        action, reason = _decide_action(client, user_query, mem)
        timings["action_decision_ms"] = int((time.time() - action_start) * 1000)

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
- Always add $ for currency values
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
- ALWAYS use $ for monetary values
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
- Use $ for monetary values
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
    # Check cache first for similar queries
    try:
        cache_start = time.time()
        cached_result = find_similar_cached_query(db, user_query, threshold=0.78)
        timings["cache_lookup_ms"] = int((time.time() - cache_start) * 1000)
        
        if cached_result:
            logger.info(f"✅ Serving from cache (similarity={cached_result.get('similarity', 0):.3f})")
            total_time = int((time.time() - perf_start) * 1000)
            return OrchestratorResult(
                reply=cached_result["result_summary"],
                action="cached",
                reason=f"cache_hit_similarity_{cached_result.get('similarity', 0):.2f}",
                sql=cached_result.get("sql_query", ""),
                rows_preview=cached_result.get("result_preview"),
                memory_updated=False,
                charts=cached_result.get("charts"),
                performance={**timings, "total_ms": total_time, "used_cache": True},
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info
            )
    except Exception as cache_err:
        logger.warning(f"Cache lookup failed: {cache_err}")
        timings["cache_lookup_ms"] = 0
    
    # Try pattern matching first for faster execution
    sql_db = sap_db or db
    pattern_result = None
    try:
        from .query_optimizer import try_pattern_optimization
        pattern_start = time.time()
        pattern_result = try_pattern_optimization(user_query, db)
        timings["pattern_matching_ms"] = int((time.time() - pattern_start) * 1000)
        
        if pattern_result:
            logger.info(f"✅ Using pattern optimization: {pattern_result.get('pattern_used')}")
            timings["used_pattern"] = True
    except Exception as pattern_err:
        logger.warning(f"Pattern matching failed: {pattern_err}")
        timings["pattern_matching_ms"] = 0
        timings["used_pattern"] = False
    
    # Execute SQL query (either from pattern or from SQL agent)
    sql_start = time.time()
    
    if pattern_result and pattern_result.get("sql"):
        # Execute pattern-generated SQL directly
        try:
            from .sap_sql_agent import _run_sql, SqlAgentResult
            sql = pattern_result["sql"]
            rows = _run_sql(sql_db, sql)
            result = SqlAgentResult(sql=sql, rows=rows)
            timings["sql_execution_ms"] = int((time.time() - sql_start) * 1000)
            logger.info(f"✅ Pattern SQL executed: {len(rows)} rows in {timings['sql_execution_ms']}ms")
        except Exception as exec_err:
            logger.warning(f"⚠️ Pattern SQL execution failed: {exec_err}, falling back to agent")
            knowledge = mem.knowledge()
            knowledge_context = "\n".join(str(v) for v in knowledge.values()) if knowledge else None
            few_shot = get_sql_examples_for_question(
                user_query, additional_examples=get_few_shot_examples(db, 2)
            )
            result = run_sap_sql_agent(
                user_query, sql_db,
                knowledge_context=knowledge_context,
                time_scope=time_scope,
                few_shot_examples=few_shot,
            )
            timings["sql_execution_ms"] = int((time.time() - sql_start) * 1000)
            timings["used_pattern"] = False
    else:
        # Use full SQL agent
        knowledge = mem.knowledge()
        knowledge_context = "\n".join(str(v) for v in knowledge.values()) if knowledge else None
        few_shot = get_sql_examples_for_question(
            user_query, additional_examples=get_few_shot_examples(db, 2)
        )
        result = run_sap_sql_agent(
            user_query, sql_db,
            knowledge_context=knowledge_context,
            time_scope=time_scope,
            few_shot_examples=few_shot,
        )
        timings["sql_execution_ms"] = int((time.time() - sql_start) * 1000)
        timings["used_pattern"] = False
    
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
        
        # If user asked about costs and we have cost-table knowledge, explain that the query ran but returned no rows.
        cost_related = "cost" in q_lower or "costing" in q_lower or "vendor" in q_lower
        has_cost_tables_note = knowledge and ("ekpo" in knowledge_str or "rbkp" in knowledge_str or "rseg" in knowledge_str)
        if cost_related and has_cost_tables_note:
            fallback_reply = (
                "I generated and ran a live SQL query against your cost tables (e.g. EKPO, RBKP, RSEG), "
                "but for this exact combination of filters and time period it returned no rows. "
                "The tables themselves do contain cost data (as your dashboards show), so this slice is likely filtered out. "
                "Try broadening the date range (for example, all periods) or simplifying the question, such as total spend by vendor or by material."
            )
            mem.last_user_query = user_query
            save_memory(db, mem)
            return OrchestratorResult(
                reply=fallback_reply,
                action="new",
                reason=reason or "cost_query_no_rows",
                sql=result.sql if result else "",
                rows_preview=None,
                memory_updated=True,
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info
            )
        # Fallback: answer from context_str alone, without relying on live SQL rows
        if context_str.strip():
            prompt = f"""
You are a business analyst assistant.

You have the following SALES and INVOICE context (plain text, already computed from the database):

{context_str[:8000]}

User question:
{user_query}

Task:
- Answer ONLY using the context above (do NOT invent numbers that are not implied there).
- Use MARKDOWN formatting:
  * **Bold** for important numbers
  * Bullet points for lists
  * > Blockquotes for key insights
  * $ for monetary values
- If the context already includes information about top products, customers, revenues, etc., reuse those numbers.
- If something is missing, say clearly what is missing instead of guessing.
"""
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=800,
            )
            reply = (resp.choices[0].message.content or "").strip()
            mem.last_user_query = user_query
            save_memory(db, mem)
            return OrchestratorResult(
                reply=reply or "I used your dashboard context, but it doesn’t include enough detail to answer that exactly.",
                action="new",
                reason=reason or "fallback_to_context_only",
                sql="",
                rows_preview=None,
                memory_updated=True,
                time_scope=time_scope,
                date_range=date_range,
                period_info=period_info
            )
        # If we have neither a useful SQL result nor context, return a clear error.
        return OrchestratorResult(
            reply="I couldn’t generate a SQL query or find enough dashboard context to answer that. Try rephrasing with more detail (customer, product, country, and time period).",
            action="new",
            reason=reason or "sap_sql_agent_no_result",
            time_scope=time_scope,
            date_range=date_range,
            period_info=period_info
        )

    # Summarize rows with LLM (same as sap_sql_agent summarizer, but we add memory/knowledge/context)
    preview = _rows_preview(result.rows, limit=20)
    
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
You are an expert SAP sales/finance analyst with deep business intelligence expertise.

Dashboard context (optional):
{context_str[:6000]}

Saved knowledge/notes (optional):
{json.dumps(mem.knowledge(), indent=2, default=str)[:4000]}

User question:
{user_query}

SQL executed:
```sql
{result.sql}
```

Result preview as JSON:
{json.dumps(preview, default=str)}

Task - Provide DEEP BUSINESS INSIGHTS using MARKDOWN formatting:

🗓️ **CRITICAL**: ALWAYS include period/date context at the start:
- State the time period being analyzed (e.g., "Analysis Period: January-March 2024", "Data from 1994-2010", "Last 30 days")
- For each metric, mention the period (e.g., "Q1 2024 sales: $5M", "2023 total revenue")
- Use date badges: 📅 2024, 📊 Q1 2024, 🗓️ Jan-Mar 2024

1. **📅 Period Overview & Executive Summary** (MANDATORY FIRST)
   - 🗓️ **Analysis Period**: Clearly state date range
   - **Time Scope**: {time_scope} data
   - **Key Finding**: Most critical insight with period context
   - Use **bold** for key numbers with $ for currency

2. **📊 Detailed Analysis** (organized with #### subheadings)
   - Break down by TIME PERIOD first (year, quarter, month)
   - Then by other dimensions (geography, category, etc.)
   - For each metric, include: **[Period]** Amount
   - Identify trends, patterns, and anomalies OVER TIME
   - Compare periods (YoY, MoM, QoQ)
   - **Bold** all important metrics

3. **🔍 Key Insights** (as bullet points with period context)
   - Highlight what's surprising or notable WITH DATES
   - Explain "why" this matters for the business
   - Call out risks or opportunities BY PERIOD
   - Include growth rates and time-based comparisons

4. **💡 Actionable Recommendations** (as > blockquote)
   - What should leadership do WITH TIMING
   - Prioritize by impact and urgency
   - Include time-bound goals

Formatting rules:
- 🗓️ ALWAYS start with period context
- ### Main heading with period
- #### Subheadings with date ranges where applicable
- **Bold** for ALL important numbers, percentages, names, DATES
- Use bullet points (-) for lists
- Use > blockquote for the most important recommendation
- ALWAYS use $ for monetary values
- Highlight extremes: highest, lowest, best, worst performers
- Include percentages and comparisons where meaningful
- 📅 Use date emojis for period indicators
- Format dates clearly: Q1 2024, Jan-Mar 2024, FY2023

Be thorough and insightful (10-25 sentences). This is for executive decision-making.
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
    except Exception as chart_err:
        logger.error(f"❌ Chart generation failed: {chart_err}", exc_info=True)
        timings["chart_generation_ms"] = 0

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
        period_info=period_info
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

