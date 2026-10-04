"""Thin LLM provider facade. Orchestrator must not contain OpenAI vs Gemini branches."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ..ai_native_pipeline import llm_json as _llm_json
from ..ai_native_pipeline import llm_text as _llm_text


def analyze_json(system: str, user: str) -> Tuple[Dict[str, Any], str]:
    return _llm_json(system, user)


def complete_text(system: str, user: str) -> Tuple[str, str]:
    return _llm_text(system, user)
