"""Task-scoped model settings for the conversational analyst.

Helper models must not silently become the SQL planner or answer model.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

_TASK: ContextVar[str] = ContextVar("analyst_model_task", default="")


@contextmanager
def analyst_model_task(task: str):
    token = _TASK.set(task)
    try:
        yield
    finally:
        _TASK.reset(token)


def current_model_task() -> str:
    explicit = _TASK.get()
    if explicit:
        return explicit
    from .investigation_budget import current_budget
    budget = current_budget()
    stage = budget.pipeline_stage if budget else ""
    if stage == "PREPARING_ANSWER":
        return "answer"
    if stage in {"BUILDING_PLAN", "GENERATING_SQL", "REPAIRING"}:
        return "planning"
    return "understanding" if stage == "UNDERSTANDING" else "selection"


def analyst_openai_model() -> str:
    task = current_model_task().upper()
    return next((value.strip() for name in (
        f"AI_ANALYST_{task}_MODEL", "AI_ANALYST_MODEL", "AI_NATIVE_OPENAI_MODEL",
        "OPENAI_MODEL", "LANGGRAPH_OPENAI_MODEL",
    ) if (value := os.getenv(name, "")).strip()), "gpt-6.1-sol")


def analyst_reasoning_effort() -> str:
    task = current_model_task()
    return (os.getenv(f"AI_ANALYST_{task.upper()}_REASONING_EFFORT")
            or os.getenv("OPENAI_REASONING_EFFORT")
            or ("medium" if task == "planning" else "low")).strip().lower()


def analyst_output_limit(json_mode: bool) -> int:
    task = current_model_task()
    default = 8000 if task == "answer" else 6000 if task == "planning" else 3000
    raw = (os.getenv(f"AI_ANALYST_{task.upper()}_MAX_TOKENS")
           or os.getenv("AI_JSON_MAX_TOKENS" if json_mode else "AI_RESPONSE_MAX_TOKENS"))
    try:
        return max(256, min(int(raw or default), 32000))
    except ValueError:
        return default
