"""
Multi-model AI orchestrator for parallel comparison.

Runs OpenAI GPT, Google Gemini, and Anthropic Claude in parallel,
then synthesizes the best response.
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


async def _call_openai_async(prompt: str, context: str) -> ModelResponse:
    """Call OpenAI GPT-4o-mini asynchronously."""
    start_time = time.time()
    try:
        if not OPENAI_API_KEY:
            return ModelResponse(
                model_name="OpenAI GPT-4o-mini",
                content="",
                response_time_ms=0,
                success=False,
                error="OPENAI_API_KEY not configured",
            )
        
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        structured_prompt = f"""You are an expert SAP business intelligence analyst. Provide a well-structured analysis.

CONTEXT:
{context[:4000]}

USER QUESTION:
{prompt}

INSTRUCTIONS:
- Provide a clear, structured response
- Use bullet points or numbered lists where appropriate
- Start with a brief summary (1-2 sentences)
- Include specific metrics and insights
- Keep it concise but comprehensive (5-8 key points)
- Use **bold** for emphasis on key findings
- Format numbers clearly (e.g., $2.5M, 92%)

Structure your response as:
**Summary:** [Brief overview]
**Key Findings:**
- [Finding 1]
- [Finding 2]
...
**Recommendation:** [If applicable]"""

        messages = [
            {"role": "system", "content": "You are an expert SAP data analyst providing structured business intelligence insights."},
            {"role": "user", "content": structured_prompt},
        ]
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=1000,
        )
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        content = response.choices[0].message.content or ""
        
        return ModelResponse(
            model_name="OpenAI GPT-4o-mini",
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
            model_name="OpenAI GPT-4o-mini",
            content="",
            response_time_ms=elapsed_ms,
            success=False,
            error=str(e),
        )


async def _call_gemini_async(prompt: str, context: str) -> ModelResponse:
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
        # Use Gemini 2.5 Flash model (fast, better free tier limits)
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        
        full_prompt = f"""You are an expert SAP business intelligence analyst. Provide a well-structured analysis.

CONTEXT:
{context[:4000]}

USER QUESTION:
{prompt}

INSTRUCTIONS:
- Provide a clear, structured response
- Use bullet points or numbered lists where appropriate
- Start with a brief summary (1-2 sentences)
- Include specific metrics and insights from the context
- Keep it concise but comprehensive (5-8 key points)
- Use **bold** for emphasis on key findings
- Format numbers clearly (e.g., $2.5M, 92%)

Structure your response as:
**Summary:** [Brief overview]

**Key Findings:**
• [Finding 1]
• [Finding 2]
• [Finding 3]

**Recommendation:** [If applicable]"""
        
        # Gemini doesn't have async support in the current SDK, so we run in executor
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


async def _call_claude_async(prompt: str, context: str) -> ModelResponse:
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
        
        system_message = "You are an expert SAP business intelligence analyst providing structured, actionable insights."
        
        structured_prompt = f"""Analyze the following business data and provide a well-structured response.

CONTEXT:
{context[:4000]}

USER QUESTION:
{prompt}

INSTRUCTIONS:
- Provide a clear, structured response with logical sections
- Use bullet points or numbered lists for clarity
- Start with an executive summary (1-2 sentences)
- Include specific metrics and data-driven insights
- Provide 5-8 key findings or points
- Use **bold** for emphasis on critical findings
- Format numbers clearly (e.g., $2.5M, 92%)
- End with actionable recommendations if applicable

Structure your response as:
**Executive Summary:** [Brief overview]

**Key Insights:**
• [Insight 1 with supporting data]
• [Insight 2 with supporting data]
• [Insight 3 with supporting data]

**Recommendations:** [Strategic actions]"""
        
        response = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            temperature=0.3,
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
) -> MultiModelResult:
    """
    Run all three AI models in parallel and synthesize the best response.
    
    Args:
        user_query: User's natural language question
        context: Dashboard context and data
        time_scope: Time scope for analysis (current/historical/both)
        days: Number of days for current period
    
    Returns:
        MultiModelResult with individual responses and synthesized answer
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
    
    # Run all models in parallel
    results = await asyncio.gather(
        _call_openai_async(user_query, context),
        _call_gemini_async(user_query, context),
        _call_claude_async(user_query, context),
        return_exceptions=True,
    )
    
    # Filter out exceptions and failed responses
    individual_responses = []
    successful_responses = []
    
    for result in results:
        if isinstance(result, ModelResponse):
            individual_responses.append(result)
            if result.success and result.content:
                successful_responses.append(result)
        else:
            logger.error(f"Model execution exception: {result}")
    
    # Synthesize response
    if not successful_responses:
        # All models failed
        synthesized = "All AI models failed to generate a response. Please try again."
        best_model = "None"
    elif len(successful_responses) == 1:
        # Only one model succeeded
        synthesized = successful_responses[0].content
        best_model = successful_responses[0].model_name
    else:
        # Multiple models succeeded - use GPT to synthesize
        try:
            synthesized, best_model = await _synthesize_responses(
                user_query,
                successful_responses,
            )
        except Exception as synth_err:
            logger.error(f"Synthesis failed: {synth_err}")
            # Fallback: use the fastest successful response
            fastest = min(successful_responses, key=lambda r: r.response_time_ms)
            synthesized = fastest.content
            best_model = fastest.model_name
    
    total_time_ms = int((time.time() - start_time) * 1000)
    
    # Optional narrative guard (if caller provides stats/scope from executed SQL rows).
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
            logger.warning("multi_model_orchestrator: narrative stats guard failed: %s", guard_err)
    else:
        logger.warning("multi_model_orchestrator: narrative stats guard skipped (missing GLOBAL_NUMERIC_STATS)")

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
) -> tuple[str, str]:
    """
    Synthesize multiple model responses into a single best answer.
    
    Args:
        user_query: Original user question
        responses: List of successful model responses
    
    Returns:
        Tuple of (synthesized_answer, best_model_name)
    """
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        responses_text = "\n\n".join([
            f"**{r.model_name}** (in {r.response_time_ms}ms):\n{r.content}"
            for r in responses
        ])
        
        synthesis_prompt = f"""You are synthesizing answers from multiple AI models to provide the best possible response.

USER QUESTION: "{user_query}"

MODEL RESPONSES:
{responses_text}

TASK:
1. Identify which model gave the best answer (most accurate, complete, and clear)
2. Synthesize a final answer that combines the best insights from ALL models
3. Create a well-structured response with:
   - Executive summary (1-2 sentences)
   - Key findings (bullet points)
   - Specific metrics and data points
   - Recommendations if applicable
4. Use **bold** for emphasis on critical points
5. Format numbers clearly (e.g., $2.5M, 92%)
6. Keep it comprehensive but concise

Return JSON only with this exact structure:
{{
  "best_model": "model name",
  "synthesized_answer": "**Summary:** [Brief overview]\\n\\n**Key Findings:**\\n• [Finding 1]\\n• [Finding 2]\\n• [Finding 3]\\n\\n**Recommendations:** [If applicable]"
}}
"""
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0.2,
            max_tokens=1000,
        )
        
        content = response.choices[0].message.content or ""
        
        # Try to extract JSON
        import re
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            data = json.loads(match.group(0))
            return data.get("synthesized_answer", responses[0].content), data.get("best_model", responses[0].model_name)
        
        # Fallback
        return responses[0].content, responses[0].model_name
    
    except Exception as e:
        logger.error(f"Response synthesis failed: {e}")
        return responses[0].content, responses[0].model_name
