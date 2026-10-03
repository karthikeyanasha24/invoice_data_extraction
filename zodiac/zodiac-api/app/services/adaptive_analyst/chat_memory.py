"""Bounded conversational memory, independent of active SQL/filter state."""
from __future__ import annotations

import re
from typing import Any, Dict, List


_MEMORY_STOP_WORDS = frozenset(
    {
        "about", "after", "again", "also", "and", "any", "are", "around", "before",
        "between", "can", "could", "data", "did", "does", "for", "from", "get",
        "had", "has", "have", "how", "into", "just", "most", "much", "need",
        "not", "our", "please", "show", "some", "that", "the", "their", "them",
        "there", "these", "they", "this", "those", "through", "use", "using",
        "was", "what", "when", "where", "which", "who", "with", "would", "you",
        "your",
    }
)


def relevant_conversation(
    question: str,
    turns: Any,
    *,
    recent_limit: int = 12,
    max_chars: int = 12000,
    relevant_pair_limit: int = 4,
) -> List[Dict[str, str]]:
    """Keep recent turns and retrieve a few older turns that match the new ask.

    The rolling chat is bounded, but a strict last-N window can discard a result
    that a later follow-up explicitly refers to. This adds lexical retrieval over
    the bounded history without treating any old turn as an instruction.
    """
    cleaned = recent_conversation(turns)
    if not cleaned:
        return []

    recent_start = max(0, len(cleaned) - recent_limit)
    selected = set(range(recent_start, len(cleaned)))
    q_tokens = {
        token
        for token in re.findall(r"[a-z0-9_]{3,}", (question or "").lower())
        if token not in _MEMORY_STOP_WORDS
    }
    if q_tokens and recent_start:
        pairs: List[tuple[int, int, str]] = []
        i = 0
        while i < recent_start:
            j = i + 1 if i + 1 < len(cleaned) and cleaned[i + 1].get("role") == "assistant" else i
            pair_text = " ".join(str(cleaned[k].get("content") or "") for k in range(i, j + 1)).lower()
            pair_tokens = {
                token
                for token in re.findall(r"[a-z0-9_]{3,}", pair_text)
                if token not in _MEMORY_STOP_WORDS
            }
            overlap = q_tokens & pair_tokens
            if overlap:
                # Rare, specific terms such as table names and identifiers should
                # outweigh generic overlap; recency breaks ties among matching pairs.
                score = sum(2 if any(ch.isdigit() for ch in token) or "_" in token else 1 for token in overlap)
                pairs.append((score, i, pair_text))
            i = j + 1
        pairs.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _score, start, _text in pairs[:relevant_pair_limit]:
            selected.add(start)
            if start + 1 < len(cleaned) and cleaned[start + 1].get("role") == "assistant":
                selected.add(start + 1)

    ordered = sorted(selected)
    result: List[Dict[str, str]] = []
    remaining = max_chars
    for index in ordered:
        item = cleaned[index]
        content = str(item.get("content") or "")
        # Older turns are retrieval evidence, so keep their summaries compact.
        if index < recent_start:
            content = content[:1200]
        if not content or len(content) > remaining:
            continue
        row = {"role": str(item.get("role") or ""), "content": content}
        if item.get("mode"):
            row["mode"] = str(item["mode"])
        result.append(row)
        remaining -= len(content)
    return result


def compact_sql_lineage(sql: str, *, max_chars: int = 1800) -> str:
    """Keep query shape for later follow-ups while removing literal values."""
    text = re.sub(r"/\*[\s\S]*?\*/|--[^\r\n]*", " ", str(sql or ""))
    text = re.sub(r"'(?:''|[^'])*'", "?", text)
    text = re.sub(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?(?![A-Za-z0-9_])", "?", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


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
