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


def user_conversation_preferences(turns: Any) -> List[str]:
    """Return user-authored communication instructions without inventing their meaning.

    Keep the original wording, including scope and later corrections, so the
    response model can resolve applicable preferences for the current message.
    Assistant acknowledgements and questions about preferences are not rules.
    """
    preferences: List[str] = []
    for turn in recent_conversation(turns):
        if turn.get("role") != "user":
            continue
        content = str(turn.get("content") or "").strip()
        durable_instruction = bool(re.search(
            r"\b(?:I\s+(?:prefer|would\s+prefer)|from\s+now\s+on|"
            r"for\s+(?:this|our|the)\s+(?:chat|conversation)|"
            r"(?:remember|keep\s+in\s+mind)\s+(?:that\s+)?I\s+(?:prefer|want)|"
            r"(?:always|please)\s+(?:answer|respond|reply|write|keep|use))\b",
            content,
            re.I,
        ))
        communication_change = bool(re.search(
            r"\b(?:forget|ignore|stop|change|replace|use|keep)\b.{0,100}"
            r"\b(?:preferences?|answers?|responses?|replies|reply|format|tone|language|style|concise|brief|brevity)\b",
            content,
            re.I,
        ))
        asks_about_rule = bool(re.match(r"(?:what|which|did|do|have|can|could)\b", content, re.I))
        if (durable_instruction or communication_change) and not asks_about_rule:
            preferences.append(content)
    # Bound prompt memory while keeping corrections in chronological order.
    return preferences[-8:]


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
    preferences = set(user_conversation_preferences(cleaned))
    for index, item in enumerate(cleaned):
        if item.get("role") == "user" and item.get("content") in preferences:
            selected.add(index)
            if index + 1 < len(cleaned) and cleaned[index + 1].get("role") == "assistant":
                selected.add(index + 1)
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
    """Reconstruct a usable context, skipping failed turns and retaining SQL lineage."""
    failed = {"CANNOT_ANSWER", "ERROR", "TIMEOUT", "CANCELLED"}

    def turn_details(index: int) -> Dict[str, Any]:
        turn = turns[index]
        metrics = turn.get("key_metrics") or {}
        metrics = metrics if isinstance(metrics, dict) else {}
        question = next(
            (
                str(item.get("content") or "")
                for item in reversed(turns[:index])
                if item.get("role") == "user"
            ),
            "",
        )
        plan = metrics.get("query_plan") if isinstance(metrics.get("query_plan"), dict) else {}
        status = str(metrics.get("answer_status") or "SUCCESS").strip().upper()
        mode = str(metrics.get("mode") or turn.get("mode") or "").strip().lower()
        sql = str(turn.get("sql_executed") or "").strip()
        rows = turn.get("result_rows")
        rows = rows if isinstance(rows, list) else []
        return {
            "question": question,
            "plan": plan,
            "status": status,
            "mode": mode,
            "sql": sql,
            "rows": rows,
        }

    assistants = [i for i, turn in enumerate(turns) if turn.get("role") == "assistant"]
    recent_turns = recent_conversation(turns)

    def latest_successful_sql_before(index: int) -> Dict[str, Any] | None:
        for previous_index in reversed(assistants):
            if previous_index >= index:
                continue
            candidate = turn_details(previous_index)
            if candidate["status"] not in failed and re.search(r"\bselect\b", candidate["sql"], re.I):
                return candidate
        return None

    for index in reversed(assistants):
        detail = turn_details(index)
        if detail["status"] in failed:
            continue

        plan = detail["plan"]
        sql = detail["sql"]
        rows = detail["rows"]

        # Result-first answers are calculated from previous validated rows and
        # intentionally have no newly executed SQL. Reattach their source query.
        if detail["mode"] == "result_first" and not sql:
            source = latest_successful_sql_before(index)
            if source:
                source_plan = source["plan"]
                return {
                    "previousQuestion": detail["question"],
                    "previousSQL": source["sql"],
                    "previousPlan": {**source_plan, **plan, "recent_turns": recent_turns},
                    "previousAnswerStatus": detail["status"],
                    "data": rows[:30],
                }

        if re.search(r"\bselect\b", sql, re.I):
            return {
                "previousQuestion": detail["question"],
                "previousSQL": sql,
                "previousPlan": {**plan, "recent_turns": recent_turns},
                "previousAnswerStatus": detail["status"],
                "data": rows[:30],
            }

        # A general reply or clarification is still the latest conversational
        # turn, but keep the most recent successful database result available
        # as a separate follow-up anchor.
        if detail["mode"] in {"general_chat", "clarification"} or detail["status"] == "CLARIFICATION":
            source = latest_successful_sql_before(index)
            if source:
                retained = {
                    "previousQuestion": source["question"],
                    "previousSQL": source["sql"],
                    "previousPlan": source["plan"],
                    "previousAnswerStatus": source["status"],
                    "data": source["rows"][:30],
                }
                plan = {**plan, "retained_analytical_context": retained}
            return {
                "previousQuestion": detail["question"],
                "previousSQL": "",
                "previousPlan": {**plan, "recent_turns": recent_turns},
                "previousAnswerStatus": detail["status"],
                "data": rows[:30],
            }

        # Other successful metadata/tool replies can be useful conversational
        # context even though they do not have an SQL query. Keep the prior
        # analysis separately available so a later data follow-up can resume it.
        source = latest_successful_sql_before(index)
        if source:
            plan = {
                **plan,
                "retained_analytical_context": {
                    "previousQuestion": source["question"],
                    "previousSQL": source["sql"],
                    "previousPlan": source["plan"],
                    "previousAnswerStatus": source["status"],
                    "data": source["rows"][:30],
                },
            }
        return {
            "previousQuestion": detail["question"],
            "previousSQL": "",
            "previousPlan": {**plan, "recent_turns": recent_turns},
            "previousAnswerStatus": detail["status"],
            "data": rows[:30],
        }

    # If the thread contains no successful turn, keep the latest failure for
    # display while the caller continues to report that no verified result exists.
    if assistants:
        index = assistants[-1]
        detail = turn_details(index)
        return {
            "previousQuestion": detail["question"],
            "previousSQL": "",
            "previousPlan": {**detail["plan"], "recent_turns": recent_turns},
            "previousAnswerStatus": detail["status"],
            "data": [],
        }
    return {"previousPlan": {"recent_turns": recent_turns}, "data": []}


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
