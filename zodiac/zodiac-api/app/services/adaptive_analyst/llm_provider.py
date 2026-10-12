"""Thin LLM provider facade. Orchestrator must not contain OpenAI vs Gemini branches."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ..ai_native_pipeline import llm_json as _llm_json
from ..ai_native_pipeline import llm_text as _llm_text


def _refuse_paid_call() -> None:
    from ..investigation_budget import paid_models_blocked
    if paid_models_blocked():
        raise RuntimeError("Basic mode does not call a paid model")


def analyze_json(system: str, user: str) -> Tuple[Dict[str, Any], str]:
    _refuse_paid_call()
    return _llm_json(system, user)


def complete_text(system: str, user: str) -> Tuple[str, str]:
    _refuse_paid_call()
    return _llm_text(system, user)
