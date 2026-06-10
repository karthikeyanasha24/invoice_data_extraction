"""OpenAI Chat Completions: ``max_tokens`` vs ``max_completion_tokens`` by model."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _openai_strict_chat_completion_model_id(model: Optional[str]) -> bool:
    """GPT-5 family and reasoning models with stricter Chat Completions parameters."""
    m = (model or "").strip().lower()
    if not m:
        return False
    if "gpt-5" in m:
        return True
    for p in ("o1", "o3", "o4"):
        if m.startswith(p):
            return True
    return False


def model_requires_max_completion_tokens(model: Optional[str]) -> bool:
    """
    GPT-5+ and some reasoning models return 400 if ``max_tokens`` is sent;
    they require ``max_completion_tokens`` instead.
    """
    env = os.getenv("OPENAI_USE_MAX_COMPLETION_TOKENS", "").strip().lower()
    if env in ("1", "true", "yes", "all"):
        return True
    return _openai_strict_chat_completion_model_id(model)


def model_omits_temperature(model: Optional[str]) -> bool:
    """
    Some models reject non-default ``temperature`` (e.g. only default 1 is allowed).
    Omit the parameter so the API uses its default.
    """
    if os.getenv("OPENAI_OMIT_TEMPERATURE", "").strip().lower() in ("1", "true", "yes", "all"):
        return True
    return _openai_strict_chat_completion_model_id(model)


def openai_chat_temperature_kwargs(model: Optional[str], temperature: float) -> Dict[str, float]:
    """Args for ``chat.completions.create``; empty when the model fixes sampling."""
    if model_omits_temperature(model):
        return {}
    return {"temperature": float(temperature)}


def langchain_openai_temperature_kwargs(model: Optional[str], temperature: float) -> Dict[str, Any]:
    """Args for ``ChatOpenAI``; uses temperature=1.0 for restricted models.

    LangChain's ChatOpenAI (Pydantic v2) requires ``temperature`` to be a
    float — it cannot be None.  For gpt-5/o1/o3/o4 models the API only
    accepts the default (1); passing 1.0 satisfies both Pydantic validation
    and the OpenAI API constraint.  This prevents the 400 error:
      "temperature does not support 0.7 … Only the default (1) is supported."
    """
    if model_omits_temperature(model):
        return {"temperature": 1.0}
    return {"temperature": float(temperature)}


def openai_completion_limit_kwargs(model: Optional[str], limit: int) -> Dict[str, Any]:
    """Args for ``OpenAI().chat.completions.create`` output token cap.

    Reasoning models (gpt-5 / o-series) spend hidden reasoning tokens BEFORE the
    visible answer. If ``max_completion_tokens`` is small (e.g. 900), reasoning
    consumes the whole budget and ``message.content`` comes back EMPTY with
    finish_reason="length" — surfacing as blank answers like "Could not generate
    follow-up answer." So for these models we (a) add headroom for reasoning and
    (b) default reasoning_effort to "low" for fast, non-empty answers.
    Override with OPENAI_REASONING_EFFORT=minimal|low|medium|high|off.
    """
    n = max(1, int(limit))
    if model_requires_max_completion_tokens(model):
        kwargs: Dict[str, Any] = {"max_completion_tokens": max(n + 1600, n * 2)}
        effort = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower()
        if effort not in ("off", "none", ""):
            kwargs["reasoning_effort"] = effort
        return kwargs
    return {"max_tokens": n}


def langchain_openai_limit_kwargs(model: Optional[str], limit: int) -> Dict[str, Any]:
    """Args for ``langchain_openai.ChatOpenAI`` output token cap."""
    n = max(1, int(limit))
    if model_requires_max_completion_tokens(model):
        return {"max_completion_tokens": n}
    return {"max_tokens": n}
