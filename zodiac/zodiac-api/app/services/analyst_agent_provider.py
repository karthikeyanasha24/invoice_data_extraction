"""Responses transport for the analyst's bounded tool loop."""
from __future__ import annotations

import os
from typing import Any

from .ai_native_pipeline import _openai_key, _provider_available, _provider_failed, _provider_identity, _PROVIDER_FAILURE_ERRORS
from .analyst_model_policy import analyst_openai_model
from .investigation_budget import current_budget, InvestigationTimeout


def agent_enabled() -> bool:
    return os.getenv("AI_ANALYST_AGENT_ENABLED", "true").strip().lower() in {"true", "1", "yes", "on"}


def create_agent_response(*, instructions: str, input: list[Any], tools: list[dict], output_schema: dict) -> Any:
    from openai import OpenAI

    budget = current_budget()
    if budget:
        budget.checkpoint("agent_decision")
        if not budget.allow_llm():
            raise InvestigationTimeout("agent_decision", budget.elapsed_s(), cancelled=budget.cancelled)
    key = _openai_key()
    if not key:
        raise RuntimeError("No OpenAI API key configured for the analyst agent")
    if not _provider_available("openai"):
        raise _PROVIDER_FAILURE_ERRORS.get(_provider_identity("openai")) or RuntimeError("Model service is cooling down")
    timeout = budget.llm_timeout_s(default=45) if budget else 45
    try:
        client = OpenAI(api_key=key, timeout=timeout, max_retries=0)
        response = client.responses.create(
            model=os.getenv("AI_ANALYST_AGENT_MODEL") or analyst_openai_model(),
            instructions=instructions,
            input=input,
            tools=tools,
            parallel_tool_calls=False,
            store=False,
            include=["reasoning.encrypted_content"],
            reasoning={"effort": os.getenv("AI_ANALYST_AGENT_REASONING_EFFORT") or "medium"},
            max_output_tokens=8000,
            text={"format": {"type": "json_schema", "name": "analyst_answer", "strict": True, "schema": output_schema}},
        )
        if response.status != "completed":
            raise RuntimeError("The agent model did not complete its response; partial answers are not accepted")
        return response
    except InvestigationTimeout:
        raise
    except Exception as error:
        _provider_failed("openai", error)
        raise
