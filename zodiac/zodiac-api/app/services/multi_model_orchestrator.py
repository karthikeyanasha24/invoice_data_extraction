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
        
        messages = [
            {"role": "system", "content": f"You are an expert SAP data analyst.\n\nContext:\n{context[:4000]}"},
            {"role": "user", "content": prompt},
        ]
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.4,
            max_tokens=800,
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
    """Call Google Gemini 1.5 Flash asynchronously."""
    start_time = time.time()
    try:
        if not GOOGLE_API_KEY:
            return ModelResponse(
                model_name="Google Gemini 1.5 Flash",
                content="",
                response_time_ms=0,
                success=False,
                error="GOOGLE_API_KEY not configured",
            )
        
        import google.generativeai as genai
        
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        full_prompt = f"""You are an expert SAP data analyst.

Context:
{context[:4000]}

User question:
{prompt}

Provide a clear, concise answer (3-10 sentences)."""
        
        # Gemini doesn't have async support in the current SDK, so we run in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(full_prompt)
        )
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        content = response.text if response and hasattr(response, 'text') else ""
        
        return ModelResponse(
            model_name="Google Gemini 1.5 Flash",
            content=content,
            response_time_ms=elapsed_ms,
            success=True,
        )
    
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Gemini call failed: {e}")
        return ModelResponse(
            model_name="Google Gemini 1.5 Flash",
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
        
        system_message = f"You are an expert SAP data analyst.\n\nContext:\n{context[:4000]}"
        
        response = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=800,
            temperature=0.4,
            system=system_message,
            messages=[
                {"role": "user", "content": prompt}
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
) -> MultiModelResult:
    """
    Run all three AI models in parallel and synthesize the best response.
    
    Args:
        user_query: User's natural language question
        context: Dashboard context and data
    
    Returns:
        MultiModelResult with individual responses and synthesized answer
    """
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
    
    return MultiModelResult(
        synthesized_answer=synthesized,
        individual_responses=individual_responses,
        best_model=best_model,
        total_time_ms=total_time_ms,
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
        
        synthesis_prompt = f"""You are comparing answers from multiple AI models to the same question.

User question: "{user_query}"

Model responses:
{responses_text}

Task:
1. Identify which model gave the best answer (most accurate, complete, and clear)
2. Synthesize a final answer that combines the best insights from all models
3. Keep it concise (3-10 sentences)

Return JSON only:
{{
  "best_model": "model name",
  "synthesized_answer": "final answer combining best insights"
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
