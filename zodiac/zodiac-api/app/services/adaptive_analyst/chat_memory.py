"""Bounded conversational memory, independent of active SQL/filter state."""
from __future__ import annotations

from typing import Any, Dict, List


def recent_conversation(turns: Any) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    if not isinstance(turns, list):
        return cleaned
    remaining = 26000
    for turn in reversed(turns[-40:]):
        if not isinstance(turn, dict) or turn.get("role") not in {"user", "assistant"}:
            continue
        content = str(turn.get("content") or "")[:6000]
        if not content or len(content) > remaining:
            if len(content) > remaining:
                break
            continue
        item = {"role": turn["role"], "content": content}
        if turn.get("mode"):
            item["mode"] = str(turn["mode"])[:40]
        cleaned.append(item)
        remaining -= len(content)
    return list(reversed(cleaned))


def context_from_stored_turns(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Reconstruct the same context contract used by the browser after reload."""
    prior: Dict[str, Any] = {}
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get("role") != "assistant":
            continue
        metrics = turn.get("key_metrics") or {}
        metrics = metrics if isinstance(metrics, dict) else {}
        question = next((str(t.get("content") or "") for t in reversed(turns[:index]) if t.get("role") == "user"), "")
        plan = metrics.get("query_plan") if isinstance(metrics, dict) else None
        prior = {
            "previousQuestion": question,
            "previousSQL": turn.get("sql_executed") or "",
            "previousPlan": plan if isinstance(plan, dict) else {},
            "previousAnswerStatus": metrics.get("answer_status") or "SUCCESS",
            "data": turn.get("result_rows") or [],
        }
        break
    prior["previousPlan"] = {**(prior.get("previousPlan") or {}), "recent_turns": recent_conversation(turns)}
    return prior


def remember_response(plan: Any, turns: Any, question: str, answer: str, mode: str) -> Dict[str, Any]:
    result = dict(plan) if isinstance(plan, dict) else {}
    inv_raw = result.get("investigation_state")
    inv = dict(inv_raw) if isinstance(inv_raw, dict) else {}
    history = recent_conversation(turns)
    history.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer, "mode": mode},
    ])
    history = recent_conversation(history)
    inv["recent_turns"] = history
    result["recent_turns"] = history
    result["investigation_state"] = inv
    return result
