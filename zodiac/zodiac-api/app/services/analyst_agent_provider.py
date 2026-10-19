"""Responses transport for the analyst's bounded tool loop."""
from __future__ import annotations

import os
import time
from typing import Any, Optional

from .ai_native_pipeline import (
    _is_transient_provider_error,
    _openai_key,
    _provider_available,
    _provider_failed,
    _provider_identity,
    _provider_recovered,
    _PROVIDER_FAILURE_ERRORS,
)
from .analyst_model_policy import analyst_openai_model
from contextvars import ContextVar

from .investigation_budget import current_budget, InvestigationTimeout

_RESPONSE_MODEL: ContextVar[str] = ContextVar("analyst_response_model", default="")


class AnalystResponseIncomplete(ValueError):
    """The provider responded, but did not finish a usable model turn."""


def use_response_model(model: str):
    return _RESPONSE_MODEL.set(model)


def restore_response_model(token) -> None:
    _RESPONSE_MODEL.reset(token)


def agent_enabled() -> bool:
    return os.getenv("AI_ANALYST_AGENT_ENABLED", "true").strip().lower() in {"true", "1", "yes", "on"}


def _annotate_openai_error(error: BaseException) -> BaseException:
    body = getattr(error, "body", None)
    payload = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else body
    if not isinstance(payload, dict):
        return error
    if not getattr(error, "code", None):
        try:
            error.code = payload.get("code") or payload.get("type") or ""
        except Exception:
            pass
    if not getattr(error, "status_code", None):
        try:
            error.status_code = int(getattr(error, "status_code", 0) or payload.get("status") or 0)
        except Exception:
            pass
    return error


def _quota_or_auth_error(error: BaseException) -> bool:
    code = str(getattr(error, "code", "") or "").lower()
    text = str(error or "").lower()
    status = int(getattr(error, "status_code", 0) or 0)
    return (
        code in {"insufficient_quota", "credit_balance_exhausted", "invalid_api_key"}
        or "insufficient_quota" in text
        or "credit_balance_exhausted" in text
        or status in {401, 403, 404}
    )


def create_agent_response(*, instructions: str, input: list[Any], tools: list[dict], output_schema: dict) -> Any:
    from .basic_local_provider import local_agent_active, create_local_response
    if local_agent_active():
        from .basic_hosted_provider import basic_provider, create_hosted_response
        if basic_provider() == "groq":
            return create_hosted_response(instructions=instructions, input=input, tools=tools, output_schema=output_schema)
        return create_local_response(instructions=instructions, input=input, tools=tools, output_schema=output_schema)
    from openai import OpenAI

    budget = current_budget()
    if budget:
        budget.checkpoint("agent_decision")
        if not budget.allow_llm():
            raise InvestigationTimeout("agent_decision", budget.elapsed_s(), cancelled=budget.cancelled)
    from .investigation_budget import paid_models_blocked
    if paid_models_blocked():
        raise RuntimeError("Basic mode does not call a paid model")
    key = _openai_key()
    if not key:
        raise RuntimeError("No OpenAI API key configured for the analyst agent")
    if not _provider_available("openai"):
        stored = _PROVIDER_FAILURE_ERRORS.get(_provider_identity("openai"))
        if stored is not None:
            raise stored
        cooling = RuntimeError("Model service is cooling down after a provider failure.")
        cooling.code = "model_unavailable"
        cooling.status_code = 503
        raise cooling
    timeout = budget.llm_timeout_s(default=90) if budget else 90
    from .analyst_usage import model_limits, record_response, AnalystResourceLimit
    model = _RESPONSE_MODEL.get() or os.getenv("AI_ANALYST_AGENT_MODEL") or analyst_openai_model()
    output_limit = model_limits(input, instructions, tools, model=model)
    started = time.monotonic()
    last_error: Optional[BaseException] = None
    attempts = 3
    for attempt in range(attempts):
        try:
            client = OpenAI(api_key=key, timeout=timeout, max_retries=0)
            response = client.responses.create(
                model=model,
                instructions=instructions,
                input=input,
                tools=tools,
                parallel_tool_calls=False,
                store=False,
                include=["reasoning.encrypted_content"],
                reasoning={"effort": os.getenv("AI_ANALYST_AGENT_REASONING_EFFORT") or "medium"},
                max_output_tokens=output_limit,
                text={"format": {"type": "json_schema", "name": "analyst_answer", "strict": True, "schema": output_schema}},
            )
            record_response(response, model, round((time.monotonic()-started)*1000))
            if response.status != "completed":
                raise AnalystResponseIncomplete(
                    "The model reached its response limit before completing this analysis. "
                    "No unverified answer was returned. Partial answers are not returned.")
            _provider_recovered("openai")
            return response
        except (InvestigationTimeout, AnalystResourceLimit):
            raise
        except AnalystResponseIncomplete as error:
            last_error = error
            if attempt + 1 >= attempts or (budget is not None and budget.remaining_s() <= 8):
                raise
            continue
        except Exception as error:
            if isinstance(error, InvestigationTimeout):
                raise
            _annotate_openai_error(error)
            last_error = error
            retryable = _is_transient_provider_error(error) and not _quota_or_auth_error(error)
            if retryable and attempt + 1 < attempts and (budget is None or budget.remaining_s() > 8):
                time.sleep(min(1.5, 0.4 * (attempt + 1)))
                if budget:
                    budget.checkpoint("agent_decision")
                    timeout = budget.llm_timeout_s(default=90)
                continue
            _provider_failed("openai", error)
            raise
    if last_error is not None:
        if not isinstance(last_error, AnalystResponseIncomplete):
            _provider_failed("openai", last_error)
        raise last_error
    raise RuntimeError("The AI model service did not complete a verified response")
