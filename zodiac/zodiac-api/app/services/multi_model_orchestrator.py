"""
Multi-model AI orchestrator for parallel comparison.

Runs OpenAI GPT-4o, Google Gemini, and Anthropic Claude in parallel.
All three models receive the SAME real SQL result rows + GLOBAL_NUMERIC_STATS
so their answers are grounded in actual database data — not hallucinated.

Flow:
  1. Caller executes SQL (via main orchestrator) → gets rows + global_stats
  2. This module passes those rows + stats to each model for NARRATIVE ONLY
  3. Models interpret the same data → consistent, accurate, non-hallucinated answers
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

from ..config.config import OPENAI_API_KEY, GOOGLE_API_KEY, ANTHROPIC_API_KEY, ENABLE_MULTI_MODEL

logger = logging.getLogger(__name__)


@dataclass
class ModelResponse:
    """Response from a single AI model."""
    model_name: str
    content: str
    response_time_ms: int
    success: bool
    error: Optional[str] = None
    token_usage: Optional[Dict[str, int]] = None


@dataclass
class MultiModelResult:
    """Result from running multiple models."""
    synthesized_answer: str
    individual_responses: List[ModelResponse]
    best_model: str
    total_time_ms: int
    time_scope: Optional[str] = None
    date_range: Optional[Dict[str, str]] = None
    period_info: Optional[str] = None


def _build_grounded_prompt(
    user_query: str,
    sql: str,
    rows: List[Dict[str, Any]],
    global_stats: Dict[str, Any],
    result_scope: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a data-grounded analysis prompt that prevents hallucination.
    All three model wrappers use this same prompt so they see identical data.
    """
    scope_json = json.dumps(result_scope or {}, default=str)
    stats_json = json.dumps(global_stats, default=str)
    rows_json = json.dumps(rows[:25], default=str)  # up to 25 representative rows

    return f"""You are an expert SAP business intelligence analyst.

User question:
{user_query}

SQL executed against the database:
```sql
{sql}
```

Representative result rows (up to 25):
{rows_json}

GLOBAL_NUMERIC_STATS (source of truth for all numeric claims):
{stats_json}

RESULT_SCOPE:
{scope_json}

STRICT ANTI-HALLUCINATION RULES (never break these):
- ALL numbers, totals, averages, and rankings MUST come from GLOBAL_NUMERIC_STATS or the result rows above.
- Do NOT invent amounts, percentages, or counts that are not visible in the data.
- Do NOT use years, customer names, or vendor names from your training data — only from the rows.
- If the rows are empty or contain no matching data, say "No data was found" — do not fabricate an answer.
- Do NOT default to $ unless the currency column says USD. Use the correct symbol per currency.
- If RESULT_SCOPE.kind is "limited", say the conclusion is based on a sample of rows.
- Never mention years like 1999 or 2000 unless those exact values appear in the result rows.

Write a clear MARKDOWN answer:
1. **Executive summary** (2–4 sentences; mention the period if date columns are present).
2. **Key findings** (bullet points — highlight top/bottom items, use **bold** for key numbers).
3. **Short recommendation** (1–2 sentences) in a blockquote.
"""


async def _call_openai_async(
    prompt: str,
    context: str,
    grounded_prompt: Optional[str] = None,
) -> ModelResponse:
    """Call OpenAI GPT-4o asynchronously."""
    start_time = time.time()
    try:
        if not OPENAI_API_KEY:
            return ModelResponse(
                model_name="OpenAI GPT-4o",
                content="",
                response_time_ms=0,
                success=False,
                error="OPENAI_API_KEY not configured",
            )

        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        # Prefer grounded prompt when real SQL rows are available
        if grounded_prompt:
            final_prompt = grounded_prompt
        else:
            final_prompt = f"""You are an expert SAP business intelligence analyst.

CONTEXT:
{context[:4000]}

USER QUESTION:
{prompt}

Provide a structured response:
**Summary:** [Brief overview]
**Key Findings:**
- [Finding 1]
- [Finding 2]
**Recommendation:** [If applicable]"""

        messages = [
            {"role": "system", "content": "You are an expert SAP data analyst. Only state facts that appear in the provided data. Never invent numbers."},
            {"role": "user", "content": final_prompt},
        ]

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.2,
            max_tokens=1200,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        content = response.choices[0].message.content or ""

        return ModelResponse(
            model_name="OpenAI GPT-4o",
            content=content,
            response_time_ms=elapsed_ms,
            success=True,
            token_usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"OpenAI call failed: {e}")
        return ModelResponse(
            model_name="OpenAI GPT-4o",
            content="",
            response_time_ms=elapsed_ms,
            success=False,
            error=str(e),
        )


async def _call_gemini_async(
    prompt: str,
    context: str,
    grounded_prompt: Optional[str] = None,
) -> ModelResponse:
    """Call Google Gemini 2.5 Flash asynchronously."""
    start_time = time.time()
    try:
        if not GOOGLE_API_KEY:
            return ModelResponse(
                model_name="Google Gemini 2.5 Flash",
                content="",
                response_time_ms=0,
                success=False,
                error="GOOGLE_API_KEY not configured",
            )

        import google.generativeai as genai

        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        if grounded_prompt:
            full_prompt = grounded_prompt
        else:
            full_prompt = f"""You are an expert SAP business intelligence analyst.

CONTEXT:
{context[:4000]}

USER QUESTION:
{prompt}

**Summary:** [Brief overview]
**Key Findings:**
• [Finding 1]
• [Finding 2]
**Recommendation:** [If applicable]"""

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(full_prompt)
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        content = response.text if response and hasattr(response, 'text') else ""

        return ModelResponse(
            model_name="Google Gemini 2.5 Flash",
            content=content,
            response_time_ms=elapsed_ms,
            success=True,
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Gemini call failed: {e}")
        return ModelResponse(
            model_name="Google Gemini 2.5 Flash",
            content="",
            response_time_ms=elapsed_ms,
            success=False,
            error=str(e),
        )


async def _call_claude_async(
    prompt: str,
    context: str,
    grounded_prompt: Optional[str] = None,
) -> ModelResponse:
    """Call Anthropic Claude 3.5 Sonnet asynchronously."""
    start_time = time.time()
    try:
        if not ANTHROPIC_API_KEY:
            return ModelResponse(
                model_name="Anthropic Claude 3.5 Sonnet",
                content="",
                response_time_ms=0,
                success=False,
                error="ANTHROPIC_API_KEY not configured",
            )

        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        system_message = (
            "You are an expert SAP business intelligence analyst. "
            "You only state facts that are present in the provided data rows. "
            "You never invent numbers, totals, or year references not in the data."
        )

        if grounded_prompt:
            structured_prompt = grounded_prompt
        else:
            structured_prompt = f"""Analyze the following business data and provide a well-structured response.

CONTEXT:
{context[:4000]}

USER QUESTION:
{prompt}

**Executive Summary:** [Brief overview]
**Key Insights:**
• [Insight 1]
• [Insight 2]
**Recommendations:** [Strategic actions]"""

        response = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1200,
            temperature=0.2,
            system=system_message,
            messages=[
                {"role": "user", "content": structured_prompt}
            ]
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        content = response.content[0].text if response.content else ""

        return ModelResponse(
            model_name="Anthropic Claude 3.5 Sonnet",
            content=content,
            response_time_ms=elapsed_ms,
            success=True,
            token_usage={
                "prompt_tokens": response.usage.input_tokens if response.usage else 0,
                "completion_tokens": response.usage.output_tokens if response.usage else 0,
            },
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Claude call failed: {e}")
        return ModelResponse(
            model_name="Anthropic Claude 3.5 Sonnet",
            content="",
            response_time_ms=elapsed_ms,
            success=False,
            error=str(e),
        )


async def run_all_models_parallel(
    user_query: str,
    context: str,
    time_scope: str = "current",
    days: int = 30,
    global_numeric_stats: Optional[Dict[str, Any]] = None,
    result_scope: Optional[Dict[str, Any]] = None,
    # New: real SQL result data — when provided, all models use grounded prompt
    sql_result_rows: Optional[List[Dict[str, Any]]] = None,
    sql_executed: Optional[str] = None,
) -> MultiModelResult:
    """
    Run all three AI models in parallel and synthesize the best response.

    When sql_result_rows + global_numeric_stats are provided, all three models
    receive a data-grounded prompt containing the actual DB rows and stats so they
    cannot hallucinate answers.  Without these, the models fall back to interpreting
    the pre-built dashboard context string (less accurate).

    Args:
        user_query: User's natural language question
        context: Dashboard context string (used only if sql_result_rows is None)
        time_scope: Time scope for analysis (current/historical/both)
        days: Number of days for current period
        global_numeric_stats: Numeric statistics from actual SQL result
        result_scope: Scope metadata (kind, row_count, etc.)
        sql_result_rows: Actual rows returned by the SQL query
        sql_executed: The SQL that was executed
    """
    from datetime import datetime, timedelta

    # Compute period information
    if time_scope == "historical":
        period_info = "Historical Data (1994-2010)"
        date_range = {"min_date": "1994-01-01", "max_date": "2010-12-31"}
    elif time_scope == "both":
        today = datetime.now().date()
        period_info = f"All Periods (1994-{today.year})"
        date_range = {"min_date": "1994-01-01", "max_date": today.isoformat()}
    else:  # current
        today = datetime.now().date()
        start_date = today - timedelta(days=days)
        period_info = f"Last {days} days"
        date_range = {"min_date": start_date.isoformat(), "max_date": today.isoformat()}

    start_time = time.time()

    # Build data-grounded prompt when real rows are available
    grounded_prompt: Optional[str] = None
    if sql_result_rows is not None and global_numeric_stats and sql_executed:
        grounded_prompt = _build_grounded_prompt(
            user_query=user_query,
            sql=sql_executed,
            rows=sql_result_rows,
            global_stats=global_numeric_stats,
            result_scope=result_scope,
        )
        logger.info(
            "multi_model_orchestrator: using data-grounded prompt (%d rows, %s stats keys)",
            len(sql_result_rows),
            len(global_numeric_stats),
        )
    else:
        logger.warning(
            "multi_model_orchestrator: sql_result_rows not provided — "
            "falling back to context-string mode (less accurate)"
        )

    # Run all models in parallel with the same grounded prompt
    results = await asyncio.gather(
        _call_openai_async(user_query, context, grounded_prompt),
        _call_gemini_async(user_query, context, grounded_prompt),
        _call_claude_async(user_query, context, grounded_prompt),
        return_exceptions=True,
    )

    # Filter out exceptions and failed responses
    individual_responses: List[ModelResponse] = []
    successful_responses: List[ModelResponse] = []

    for result in results:
        if isinstance(result, ModelResponse):
            individual_responses.append(result)
            if result.success and result.content:
                successful_responses.append(result)
        else:
            logger.error(f"Model execution exception: {result}")

    # Synthesize response
    if not successful_responses:
        synthesized = "All AI models failed to generate a response. Please try again."
        best_model = "None"
    elif len(successful_responses) == 1:
        synthesized = successful_responses[0].content
        best_model = successful_responses[0].model_name
    else:
        try:
            synthesized, best_model = await _synthesize_responses(
                user_query,
                successful_responses,
                global_numeric_stats=global_numeric_stats,
            )
        except Exception as synth_err:
            logger.error(f"Synthesis failed: {synth_err}")
            fastest = min(successful_responses, key=lambda r: r.response_time_ms)
            synthesized = fastest.content
            best_model = fastest.model_name

    total_time_ms = int((time.time() - start_time) * 1000)

    # Narrative guard: enforce numeric consistency in synthesized answer
    if global_numeric_stats:
        try:
            from .negative_lowest_narrative_guard import enforce_narrative_stats_consistency

            guarded_stats = dict(global_numeric_stats)
            if result_scope and "result_scope" not in guarded_stats:
                guarded_stats["result_scope"] = result_scope
            synthesized = enforce_narrative_stats_consistency(
                synthesized,
                user_query,
                guarded_stats,
            )
        except Exception as guard_err:
            logger.warning("multi_model_orchestrator: narrative guard failed: %s", guard_err)
    else:
        logger.warning("multi_model_orchestrator: narrative guard skipped (no GLOBAL_NUMERIC_STATS)")

    return MultiModelResult(
        synthesized_answer=synthesized,
        individual_responses=individual_responses,
        best_model=best_model,
        total_time_ms=total_time_ms,
        time_scope=time_scope,
        date_range=date_range,
        period_info=period_info,
    )


async def _synthesize_responses(
    user_query: str,
    responses: List[ModelResponse],
    global_numeric_stats: Optional[Dict[str, Any]] = None,
) -> tuple:
    """
    Synthesize multiple model responses into a single best answer.
    Uses GPT-4o for synthesis to pick the most accurate response.
    """
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        responses_text = "\n\n".join([
            f"**{r.model_name}** (in {r.response_time_ms}ms):\n{r.content}"
            for r in responses
        ])

        stats_hint = ""
        if global_numeric_stats:
            stats_hint = f"\n\nGLOBAL_NUMERIC_STATS (ground truth — synthesized answer must not contradict these):\n{json.dumps(global_numeric_stats, default=str)}"

        synthesis_prompt = f"""You are synthesizing answers from multiple AI models to produce the single most accurate, data-grounded response.

USER QUESTION: "{user_query}"

MODEL RESPONSES:
{responses_text}
{stats_hint}

TASK:
1. Identify which model gave the most accurate, data-grounded answer (never picks up hallucinated numbers).
2. Synthesize a final answer combining the best insights from all models.
3. The synthesized answer MUST NOT contain any numbers not present in GLOBAL_NUMERIC_STATS or the model responses.
4. Structure as:
   **Executive Summary:** [1-2 sentences]
   **Key Findings:**
   - [Finding 1]
   - [Finding 2]
   **Recommendation:** [If applicable]

Return JSON only:
{{
  "best_model": "model name",
  "synthesized_answer": "the full markdown answer"
}}
"""

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0.1,
            max_tokens=1200,
        )

        content = response.choices[0].message.content or ""

        import re
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            data = json.loads(match.group(0))
            return (
                data.get("synthesized_answer", responses[0].content),
                data.get("best_model", responses[0].model_name),
            )

        return responses[0].content, responses[0].model_name

    except Exception as e:
        logger.error(f"Response synthesis failed: {e}")
        return responses[0].content, responses[0].model_name
