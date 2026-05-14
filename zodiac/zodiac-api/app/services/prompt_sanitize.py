"""
Lightweight sanitization before user text is embedded in LLM prompts.
Not a security boundary — only reduces casual prompt-injection noise.
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

_INJECTION_SNIPPETS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?is)\bignore\s+(all\s+)?(previous|prior)\s+instructions?\b"), "[removed]"),
    (re.compile(r"(?is)\bdisregard\s+(all\s+)?(previous|prior)\s+instructions?\b"), "[removed]"),
    (re.compile(r"(?is)\bforget\s+(everything|all)\s+(above|before)\b"), "[removed]"),
    (re.compile(r"(?is)```\s*system\b"), "```"),
    (re.compile(r"(?is)\brole\s*:\s*system\b"), "role: user"),
]


def clean_user_input(text: str) -> str:
    if not text:
        return ""
    original = text
    s = text
    for pat, repl in _INJECTION_SNIPPETS:
        s = pat.sub(repl, s)
    if s != original:
        logger.warning(
            "prompt_sanitize: removed or neutralized suspicious patterns from user input (len=%d)",
            len(original),
        )
    return s.strip()


def format_rows_bullet_fallback(rows: list, *, max_rows: int = 3, max_cols: int = 8) -> str:
    """Plain-language fallback when the summarizer returns nothing but rows exist."""
    if not rows:
        return ""
    lines: List[str] = []
    for row in rows[: max(1, int(max_rows))]:
        if not isinstance(row, dict):
            continue
        bits = [f"{k}={v}" for k, v in list(row.items())[: max(1, int(max_cols))]]
        if bits:
            lines.append("- " + ", ".join(bits))
    body = "\n".join(lines) if lines else ""
    intro = (
        "I ran the query successfully but could not summarize the result. "
        "Here are the raw numbers:\n\n"
    )
    return intro + body
