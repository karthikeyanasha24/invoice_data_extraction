"""An unanswered analytical request is intent context, never result evidence."""
from __future__ import annotations

from typing import Any, Dict, Optional


def pending_analysis_context(
    plan: Optional[Dict[str, Any]], question: str = "", status: str = "",
) -> Optional[Dict[str, Any]]:
    plan = plan if isinstance(plan, dict) else {}
    pending = plan.get("pending_analysis")
    if isinstance(pending, dict) and pending.get("question"):
        return dict(pending)
    # Older clients have the original question and clarification status, but
    # no explicit pending-request marker. Do not reinterpret a missing-result
    # safeguard or a result-backed currency choice as an unexecuted request.
    if plan.get("requires_result_anchor") or plan.get("pending_clarification"):
        return None
    inv = plan.get("investigation_state") or {}
    inv = inv if isinstance(inv, dict) else {}
    if status.upper() != "CLARIFICATION" and plan.get("last_mode") != "clarification":
        return None
    original = str(question or inv.get("last_user_question") or "").strip()
    if not original:
        return None
    understanding = plan.get("understanding") or {}
    understanding = understanding if isinstance(understanding, dict) else {}
    return {
        "question": original,
        "clarification_question": str(understanding.get("clarification_question") or inv.get("last_summary") or ""),
        "understanding": understanding,
    }


def pending_analysis_plan(
    question: str, understanding: Any, previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # A further clarification must retain the accumulated, standalone request
    # rather than making the latest short reply the next turn's entire goal.
    resolved = str(understanding.resolved_question or "").strip()
    continuing = understanding.turn_relation == "clarification_answer" and previous
    return {
        "question": resolved or (str(previous["question"]) if continuing else question),
        "clarification_question": str(understanding.clarification_question or ""),
        "understanding": understanding.to_public_dict(),
    }
